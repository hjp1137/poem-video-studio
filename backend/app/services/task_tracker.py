"""任务提交与状态跟踪。

- submit_batch:按 scene_order 逐个构造 Workflow 提交 ComfyUI;中途失败不丢已提交的 prompt_id。
- retry_task:单场景重试,生成新 prompt_id,保留历史错误信息。
- reconcile_task:用 /history/{prompt_id} 对账,完成则定位并下载 MP4。
- monitor_loop:后台任务,优先 WebSocket 事件,断线时 HTTP 周期对账兜底。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.batch import Batch
from app.models.task import VideoTask
from app.models.task_output import TaskOutput
from app.services.comfyui_client import (
    ComfyUIClient,
    ComfyUIError,
    ComfyUIUnreachable,
    parse_ws_message,
)
from app.services.output_service import download_output, find_video_in_history
from app.services.workflow_adapter import WorkflowAdapter, build_filename_prefix
from app.services import workflow_template_service

logger = logging.getLogger("poem.task_tracker")

# 状态机:pending → submitting → queued → running → completed / failed / cancelled
ACTIVE_STATUSES = ("queued", "running", "submitting")
ERROR_HISTORY_LIMIT = 2000


def _client() -> ComfyUIClient:
    return ComfyUIClient(
        base_url=settings.comfyui_base_url,
        ws_url=settings.comfyui_ws_url,
        client_id=settings.comfyui_client_id,
        connect_timeout=settings.comfyui_connect_timeout,
        request_timeout=settings.comfyui_request_timeout,
    )


def _get_adapter() -> WorkflowAdapter:
    # 使用「模板管理」页设置的默认模板;无默认/损坏时报可操作错误
    return workflow_template_service.get_default_adapter()


def _log_fields(task: VideoTask, batch_id: str) -> dict:    return {
        "batch_id": batch_id,
        "video_task_id": task.id,
        "scene_key": task.scene_key,
        "comfy_prompt_id": task.comfy_prompt_id,
        "prompt_len": len(task.prompt or ""),
        "prompt_hash": f"{hash(task.prompt) & 0xffffffff:08x}",
    }


def _append_error(task: VideoTask, message: str) -> None:
    """保留历史错误:新错误在前,旧错误追加,超过上限截断。"""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    new = f"[{stamp}] {message}"
    if task.error_message:
        combined = new + "\n" + task.error_message
    else:
        combined = new
    task.error_message = combined[:ERROR_HISTORY_LIMIT]


async def _submit_one(db: Session, client: ComfyUIClient, adapter: WorkflowAdapter, task: VideoTask) -> bool:
    """提交单个场景:上传首帧 → 构造 Workflow → POST /prompt。成功返回 True。"""
    task.status = "submitting"
    db.commit()
    try:
        image_abs = settings.data_root / task.image_path
        image_name = await client.upload_image(image_abs)
        workflow = adapter.build(
            image_name=image_name,
            prompt=task.prompt,
            negative_prompt=task.negative_prompt,
            speech=task.speech,
            width=task.width,
            height=task.height,
            fps=task.fps,
            num_frames=task.num_frames,
            filename_prefix=build_filename_prefix(task.batch_id, task.scene_order, task.scene_key),
        )
        prompt_id = await client.submit_prompt(workflow)
    except ComfyUIError as exc:
        task.status = "failed"
        _append_error(task, f"提交 ComfyUI 失败:{exc}")
        task.finished_at = int(time.time())
        db.commit()
        logger.warning("提交失败 %s %s", _log_fields(task, task.batch_id), exc)
        return False
    task.comfy_prompt_id = prompt_id
    task.status = "queued"
    task.error_message = ""
    task.started_at = None
    task.finished_at = None
    task.output_path = ""
    db.commit()
    logger.info("已提交 %s", _log_fields(task, task.batch_id))
    return True


def _refresh_batch_status(db: Session, batch_id: str) -> None:
    batch = db.get(Batch, batch_id)
    if batch is None:
        return
    tasks = db.execute(select(VideoTask).where(VideoTask.batch_id == batch_id)).scalars().all()
    statuses = {t.status for t in tasks}
    if not tasks:
        batch.status = "parsed"
    elif statuses <= {"completed"}:
        batch.status = "completed"
    elif statuses <= {"failed"}:
        batch.status = "failed"
    elif "failed" in statuses or "cancelled" in statuses:
        if "queued" in statuses or "running" in statuses or "submitting" in statuses:
            batch.status = "running"
        elif "completed" in statuses:
            batch.status = "partial_failed"
        else:
            batch.status = "failed"
    elif statuses & {"running", "submitting"}:
        batch.status = "running"
    elif "queued" in statuses:
        batch.status = "queued"
    else:
        batch.status = "running" if "running" in statuses else "parsed"
    db.commit()


async def submit_batch(db: Session, batch_id: str) -> dict:
    """把 Batch 内 pending / failed / recover_pending 的场景按序提交到 ComfyUI。"""
    tasks = (
        db.execute(
            select(VideoTask)
            .where(VideoTask.batch_id == batch_id)
            .where(VideoTask.status.in_(("pending", "failed", "recover_pending")))
            .order_by(VideoTask.scene_order)
        )
        .scalars()
        .all()
    )
    if not tasks:
        return {"batch_id": batch_id, "submitted": 0, "failed": 0, "message": "没有待提交的任务"}

    try:
        adapter = _get_adapter()
    except (FileNotFoundError, ValueError) as exc:
        for t in tasks:
            t.status = "failed"
            _append_error(t, f"Workflow 模板/映射不可用:{exc}")
        db.commit()
        _refresh_batch_status(db, batch_id)
        return {"batch_id": batch_id, "submitted": 0, "failed": len(tasks), "message": str(exc)}

    client = _client()
    submitted = failed = 0
    try:
        for task in tasks:
            ok = await _submit_one(db, client, adapter, task)
            submitted, failed = (submitted + 1, failed) if ok else (submitted, failed + 1)
    finally:
        await client.aclose()
    _refresh_batch_status(db, batch_id)
    message = (
        "全部提交成功"
        if failed == 0
        else f"{submitted} 个成功,{failed} 个失败;失败场景可单独重试,已提交的任务不受影响"
    )
    return {"batch_id": batch_id, "submitted": submitted, "failed": failed, "message": message}


async def cancel_queued_batch(db: Session, batch_id: str) -> dict:
    """把批次内尚未开始执行的任务移出生成队列。

    - 只处理 status=queued 的任务:通知 ComfyUI 从 pending 队列删除(执行中的不受影响),
      本地状态回 pending 并清空 prompt_id;
    - running/submitting/completed/failed 一律不动;
    - ComfyUI 队列中已不存在的(如服务重启清空)也一并回 pending,保证本地可重新提交。
    """
    tasks = (
        db.execute(
            select(VideoTask)
            .where(VideoTask.batch_id == batch_id)
            .where(VideoTask.status == "queued")
            .order_by(VideoTask.scene_order)
        )
        .scalars()
        .all()
    )
    if not tasks:
        _refresh_batch_status(db, batch_id)
        return {"batch_id": batch_id, "cancelled": 0, "message": "没有排队中的任务"}

    client = _client()
    cancelled = 0
    try:
        await client.delete_queue_items([t.comfy_prompt_id for t in tasks if t.comfy_prompt_id])
    except ComfyUIError as exc:
        # 队列删除失败不回滚本地状态:保持 queued 等待下次操作,避免状态错位
        logger.warning("移除队列失败(ComfyUI) batch=%s:%s", batch_id, exc)
        return {"batch_id": batch_id, "cancelled": 0, "message": f"ComfyUI 队列操作失败:{exc}"}
    finally:
        await client.aclose()

    for task in tasks:
        task.status = "pending"
        task.comfy_prompt_id = None
        task.started_at = None
        task.finished_at = None
        cancelled += 1
    db.commit()
    _refresh_batch_status(db, batch_id)
    remaining = db.execute(
        select(func.count()).select_from(VideoTask).where(
            VideoTask.batch_id == batch_id, VideoTask.status.in_(ACTIVE_STATUSES)
        )
    ).scalar_one()
    return {
        "batch_id": batch_id,
        "cancelled": cancelled,
        "remaining_running": remaining,
        "message": f"已移除 {cancelled} 个排队任务" + (f",{remaining} 个仍在执行" if remaining else ""),
    }


async def retry_task(db: Session, task: VideoTask) -> VideoTask:
    """单场景重试:复用原图片/参数,生成新 prompt_id,保留历史错误。"""
    try:
        adapter = _get_adapter()
    except (FileNotFoundError, ValueError) as exc:
        task.status = "failed"
        _append_error(task, f"Workflow 模板/映射不可用:{exc}")
        db.commit()
        _refresh_batch_status(db, task.batch_id)
        return task
    client = _client()
    try:
        await _submit_one(db, client, adapter, task)
    finally:
        await client.aclose()
    _refresh_batch_status(db, task.batch_id)
    return task


def _record_output(db: Session, task: VideoTask) -> None:
    """完成时追加输出历史;重试多次则累积多个可下载版本(同一路径去重)。"""
    if not task.output_path:
        return
    exists = db.execute(
        select(TaskOutput.id).where(
            TaskOutput.task_id == task.id, TaskOutput.output_path == task.output_path
        )
    ).scalar_one_or_none()
    if exists:
        return
    db.add(
        TaskOutput(
            id=f"{task.id}-{int(time.time() * 1000) % 10**10}-{uuid.uuid4().hex[:6]}",
            task_id=task.id,
            batch_id=task.batch_id,
            scene_key=task.scene_key,
            output_path=task.output_path,
            output_filename=task.output_filename or "",
            output_subfolder=task.output_subfolder or "",
            output_type=task.output_type or "output",
        )
    )


async def reconcile_task(db: Session, client: ComfyUIClient, task: VideoTask) -> None:
    """按 prompt_id 查询 history 对账;完成则定位 MP4 并下载落地。"""
    if not task.comfy_prompt_id:
        return
    try:
        history = await client.get_history(task.comfy_prompt_id)
    except ComfyUIUnreachable as exc:
        logger.warning("对账失败(ComfyUI 不可达) task=%s:%s", task.id, exc)
        return
    except ComfyUIError as exc:
        logger.warning("对账异常 task=%s:%s", task.id, exc)
        return

    entry = history.get(task.comfy_prompt_id)
    if entry is None:
        # ComfyUI 只在执行完成后写 history:仍在队列/执行中的任务不得判丢失
        try:
            queue = await client.get_queue()
        except ComfyUIError as exc:
            logger.warning("队列查询失败,跳过本次对账 task=%s:%s", task.id, exc)
            return
        in_queue = {item[1] for item in queue.get("queue_running", []) if len(item) > 1}
        in_queue |= {item[1] for item in queue.get("queue_pending", []) if len(item) > 1}
        if task.comfy_prompt_id in in_queue:
            return
        task.status = "recover_pending"
        db.commit()
        return

    status_info = entry.get("status") or {}
    completed = bool(status_info.get("status_str") == "completed" or status_info.get("completed"))
    if completed:
        video_info = find_video_in_history(entry)
        if video_info is None:
            task.status = "failed"
            _append_error(task, "history 显示完成,但未找到输出 MP4(Save 节点无视频输出)")
            task.finished_at = int(time.time())
            db.commit()
            return
        try:
            local = await download_output(
                client, video_info, task.batch_id, task.scene_order, task.scene_key
            )
        except ComfyUIError as exc:
            task.status = "failed"
            _append_error(task, f"输出视频下载失败:{exc}")
            task.finished_at = int(time.time())
            db.commit()
            return
        task.output_path = str(local.relative_to(settings.data_root)).replace("\\", "/")
        task.output_filename = video_info["filename"]
        task.output_subfolder = video_info.get("subfolder", "")
        task.output_type = video_info.get("type", "output")
        if not task.started_at:
            task.started_at = int(time.time())
        task.finished_at = int(time.time())
        task.status = "completed"
        _record_output(db, task)
        db.commit()
        _refresh_batch_status(db, task.batch_id)
        logger.info("任务完成 %s output=%s", _log_fields(task, task.batch_id), task.output_path)
        return

    # 未完成:检查执行错误
    status_str = status_info.get("status_str", "")
    if status_str in ("error", "failed"):
        messages = status_info.get("messages") or []
        task.status = "failed"
        _append_error(task, f"ComfyUI 执行失败:{json.dumps(messages, ensure_ascii=False)[:500]}")
        task.finished_at = int(time.time())
        db.commit()
        _refresh_batch_status(db, task.batch_id)


# ---- 后台监控:WebSocket 优先 + HTTP 周期对账兜底 ----

async def monitor_loop(stop_event: asyncio.Event, interval: float = 2.0, ws_idle_limit: float = 120.0) -> None:
    """常驻协程:订阅 ComfyUI /ws 更新任务状态;断线/无 WS 时周期对账兜底。"""
    last_reconcile = 0.0
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            # recover_pending 也须持续对账:否则误判后永远无人恢复
            prompt_to_task = {
                t.comfy_prompt_id: t.id
                for t in db.execute(
                    select(VideoTask).where(
                        VideoTask.status.in_(ACTIVE_STATUSES + ("recover_pending",))
                    )
                ).scalars()
                if t.comfy_prompt_id
            }
        finally:
            db.close()

        if not prompt_to_task:
            await asyncio.sleep(interval)
            continue

        # HTTP 对账兜底(周期执行,即使 WS 正常也做最终确认)
        now = time.time()
        if now - last_reconcile >= settings.reconcile_interval_seconds:
            await _reconcile_all()
            last_reconcile = now

        # WebSocket:短暂监听实时事件,异常则退回等待
        try:
            async for event in _listen_ws(prompt_to_task, stop_event):
                await _apply_ws_event(event)
        except Exception as exc:  # websockets 或网络异常统一按断线处理
            logger.warning("ComfyUI WebSocket 断开,%.1f 秒后重连:%s", interval, exc)
        await asyncio.sleep(interval)


async def _listen_ws(prompt_to_task: dict[str, str], stop_event: asyncio.Event, idle_timeout: float = 30.0):
    import websockets

    uri = settings.comfyui_ws_url
    if "?" in uri:
        uri += f"&clientId={settings.comfyui_client_id}"
    else:
        uri += f"?clientId={settings.comfyui_client_id}"
    async with websockets.connect(uri, open_timeout=settings.comfyui_connect_timeout) as ws:
        while not stop_event.is_set():
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=idle_timeout)
            except asyncio.TimeoutError:
                # 空闲超时:跳出以触发一次 HTTP 对账后重连
                return
            msg = parse_ws_message(raw)
            if msg:
                yield msg


async def _apply_ws_event(event: dict) -> None:
    etype = event.get("type")
    data = event.get("data") or {}
    prompt_id = data.get("prompt_id")
    if not prompt_id or etype not in (
        "execution_start", "executing", "executed", "execution_success",
        "execution_error", "execution_cached", "progress", "status",
    ):
        return
    db = SessionLocal()
    try:
        task = db.execute(
            select(VideoTask).where(VideoTask.comfy_prompt_id == prompt_id)
        ).scalar_one_or_none()
        if task is None:
            return
        if etype == "execution_start" and task.status == "queued":
            task.status = "running"
            task.started_at = int(time.time())
            db.commit()
        elif etype in ("execution_success", "execution_error"):
            client = _client()
            try:
                await reconcile_task(db, client, task)
            finally:
                await client.aclose()
        if etype == "status":
            _refresh_batch_status_if_needed(db)
    finally:
        db.close()


def _refresh_batch_status_if_needed(db: Session) -> None:
    for task in db.execute(select(VideoTask).where(VideoTask.status.in_(ACTIVE_STATUSES))).scalars():
        _refresh_batch_status(db, task.batch_id)
        break


async def _reconcile_all() -> None:
    db = SessionLocal()
    client = _client()
    try:
        tasks = db.execute(
            select(VideoTask).where(
                VideoTask.status.in_(("queued", "running", "submitting", "recover_pending"))
            )
        ).scalars().all()
        for task in tasks:
            try:
                await reconcile_task(db, client, task)
            except Exception as exc:
                logger.warning("对账单任务异常 task=%s:%s", task.id, exc)
    finally:
        await client.aclose()
        db.close()


async def startup_reconcile() -> None:
    """服务启动恢复:对 queued/running 任务按 prompt_id 查 history 补记账。"""
    logger.info("启动恢复:开始对账 ComfyUI history")
    await _reconcile_all()
    logger.info("启动恢复:对账完成")
