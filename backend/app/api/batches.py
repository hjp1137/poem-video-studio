"""批次 API:解析、创建、查询。"""
from __future__ import annotations

import re
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.batch import Batch
from app.models.task import VideoTask
from app.models.upload import UploadFile
from app.schemas.common import BatchSummary, CreateBatchRequest, ParseRequest, TaskOut
from app.services import upload_service
from app.services import batch_parser
from app.services.batch_parser import parse_batch_text
from app.api.tasks import task_to_out

router = APIRouter(prefix="/api/batches", tags=["batches"])


@router.post("/parse")
async def parse_batch(req: ParseRequest):
    result = parse_batch_text(req.text)
    return result.model_dump(by_alias=True)


# 注意:必须定义在 GET /{batch_id} 之前,否则会被路径参数吞掉
@router.get("/text-template")
async def batch_text_template():
    """下载批量任务文本模板(与解析规则同源,勿手工改模板内容)。"""
    return PlainTextResponse(
        batch_parser.BATCH_TEXT_TEMPLATE,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="POEM_VIDEO_BATCH_V1_template.txt"'},
    )


def _effective_params(global_cfg) -> dict:
    return {
        "width": global_cfg.width or settings.default_width,
        "height": global_cfg.height or settings.default_height,
        "fps": global_cfg.fps or settings.default_fps,
        "num_frames": global_cfg.num_frames or settings.default_num_frames,
    }


@router.post("", response_model=BatchSummary)
async def create_batch(req: CreateBatchRequest, db: Session = Depends(get_db)):
    # 服务端重新解析校验:文本是唯一事实来源,前端结果只作展示
    result = parse_batch_text(req.raw_batch_text)
    if not result.ok:
        raise HTTPException(status_code=422, detail={"message": "批量文本解析失败", "errors": result.errors})

    # 图片绑定校验:每个场景必须绑定一张上传图片
    missing = [s.scene_key for s in result.scenes if not req.image_bindings.get(s.scene_key)]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"message": "以下场景未绑定图片:" + "、".join(missing), "errors": []},
        )
    bad_bindings = {
        k: v for k, v in req.image_bindings.items() if db.get(UploadFile, v) is None
    }
    if bad_bindings:
        raise HTTPException(
            status_code=422,
            detail={"message": "图片绑定失效(上传记录不存在):" + ", ".join(bad_bindings.values()), "errors": []},
        )

    batch_id = uuid.uuid4().hex[:12]
    now = int(time.time())
    batch = Batch(
        id=batch_id,
        title=req.title.strip(),
        dynasty=req.dynasty.strip(),
        author=req.author.strip(),
        raw_batch_text=req.raw_batch_text,
        status="parsed",
        created_at=now,
        updated_at=now,
    )
    db.add(batch)

    params = _effective_params(result.global_config)
    for scene in result.scenes:
        upload_id = req.image_bindings[scene.scene_key]
        dest_stem = f"{scene.scene_order:02d}_{scene.scene_key}"
        image_rel = upload_service.copy_into_batch(db, upload_id, batch_id, dest_stem)
        db.add(
            VideoTask(
                id=uuid.uuid4().hex[:12],
                batch_id=batch_id,
                scene_key=scene.scene_key,
                scene_order=scene.scene_order,
                image_path=image_rel,
                prompt=scene.prompt,
                negative_prompt=result.global_config.negative_prompt,
                speech=scene.speech,
                width=params["width"],
                height=params["height"],
                fps=params["fps"],
                num_frames=params["num_frames"],
                status="pending",
                created_at=now,
            )
        )
    db.commit()
    return BatchSummary(
        id=batch.id, title=batch.title, dynasty=batch.dynasty, author=batch.author,
        status=batch.status, total_tasks=len(result.scenes),
        created_at=batch.created_at, updated_at=batch.updated_at,
    )


def _summary(db: Session, batch: Batch) -> BatchSummary:
    rows = db.execute(
        select(VideoTask.status, func.count())
        .where(VideoTask.batch_id == batch.id)
        .group_by(VideoTask.status)
    ).all()
    counts = {status: cnt for status, cnt in rows}
    return BatchSummary(
        id=batch.id, title=batch.title, dynasty=batch.dynasty, author=batch.author,
        status=batch.status, total_tasks=sum(counts.values()),
        completed_tasks=counts.get("completed", 0),
        failed_tasks=counts.get("failed", 0),
        created_at=batch.created_at, updated_at=batch.updated_at,
    )


@router.get("", response_model=list[BatchSummary])
async def list_batches(db: Session = Depends(get_db)):
    batches = db.execute(select(Batch).order_by(Batch.created_at.desc())).scalars().all()
    return [_summary(db, b) for b in batches]


@router.get("/{batch_id}", response_model=BatchSummary)
async def get_batch(batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    return _summary(db, batch)


@router.get("/{batch_id}/tasks", response_model=list[TaskOut])
async def get_batch_tasks(batch_id: str, db: Session = Depends(get_db)):
    if db.get(Batch, batch_id) is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    tasks = db.execute(
        select(VideoTask).where(VideoTask.batch_id == batch_id).order_by(VideoTask.scene_order)
    ).scalars().all()
    return [task_to_out(db, t) for t in tasks]


@router.post("/{batch_id}/submit")
async def submit_batch_route(batch_id: str, db: Session = Depends(get_db)):
    from app.services.task_tracker import submit_batch as do_submit

    if db.get(Batch, batch_id) is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    return await do_submit(db, batch_id)


@router.post("/{batch_id}/cancel-queued")
async def cancel_queued_route(batch_id: str, db: Session = Depends(get_db)):
    """把批次内排队中(未开始执行)的任务移出生成队列,可再次提交。"""
    from app.services.task_tracker import cancel_queued_batch

    if db.get(Batch, batch_id) is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    return await cancel_queued_batch(db, batch_id)


@router.get("/{batch_id}/download")
async def download_batch_videos(batch_id: str, task_ids: str, db: Session = Depends(get_db)):
    """批量下载:把选中任务的全部输出版本打包 zip(文件名含场景与版本号)。"""
    from io import BytesIO
    from zipfile import ZIP_DEFLATED, ZipFile

    from app.models.task_output import TaskOutput
    from fastapi.responses import StreamingResponse
    from urllib.parse import quote

    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    ids = [x.strip() for x in task_ids.split(",") if x.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="未指定要下载的任务")
    tasks = {
        t.id: t
        for t in db.execute(select(VideoTask).where(VideoTask.batch_id == batch_id, VideoTask.id.in_(ids))).scalars()
    }
    if not tasks:
        raise HTTPException(status_code=404, detail="所选任务不存在")

    safe_title = re.sub(r'[\/:*?"<>|\s]+', "_", batch.title or "未命名")[:40]
    buffer = BytesIO()
    included = 0
    with ZipFile(buffer, "w", ZIP_DEFLATED) as zf:
        for task_id in ids:
            task = tasks.get(task_id)
            if task is None:
                continue
            records = (
                db.execute(
                    select(TaskOutput).where(TaskOutput.task_id == task.id).order_by(TaskOutput.created_at)
                )
                .scalars()
                .all()
            )
            entries = [(f"v{idx}", rec.output_path) for idx, rec in enumerate(records, start=1)]
            if not entries and task.output_path:
                entries = [("v1", task.output_path)]
            for version, rel_path in entries:
                path = (settings.data_root / rel_path).resolve()
                if not str(path).startswith(str(settings.outputs_dir.resolve())) or not path.is_file():
                    continue
                zf.write(path, arcname=f"{safe_title}/{task.scene_order:02d}_{task.scene_key}_{version}.mp4")
                included += 1
    if included == 0:
        raise HTTPException(status_code=400, detail="所选任务均无已生成的输出视频")
    buffer.seek(0)
    filename = f"{safe_title}_视频_{included}个.zip"
    return StreamingResponse(
        buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/{batch_id}/status")
async def batch_status(batch_id: str, db: Session = Depends(get_db)):
    batch = db.get(Batch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="批次不存在")
    tasks = db.execute(
        select(VideoTask).where(VideoTask.batch_id == batch_id).order_by(VideoTask.scene_order)
    ).scalars().all()
    return {
        "batch_id": batch_id,
        "status": batch.status,
        "total": len(tasks),
        "completed": sum(1 for t in tasks if t.status == "completed"),
        "failed": sum(1 for t in tasks if t.status == "failed"),
        "running": sum(1 for t in tasks if t.status == "running"),
        "queued": sum(1 for t in tasks if t.status in ("queued", "submitting")),
        "tasks": [task_to_out(db, t) for t in tasks],
    }
