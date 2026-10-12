"""任务 API:详情、首帧、视频预览/下载、多版本输出、参数修改、重试。"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.batch import Batch
from app.models.task import VideoTask
from app.models.task_output import TaskOutput
from app.schemas.common import TaskOut
from app.services.task_tracker import retry_task

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

# 与批量解析一致的参数范围(batch_parser.GLOBAL_INT_RANGES)
PARAM_RANGES = {"width": (64, 8192), "height": (64, 8192), "fps": (1, 240), "num_frames": (1, 4096)}


def task_outputs_of(db: Session, task: VideoTask) -> list[dict]:
    """输出历史(重试多次累积);旧数据无记录时用最新输出兜底一条。"""
    records = (
        db.execute(
            select(TaskOutput).where(TaskOutput.task_id == task.id).order_by(TaskOutput.created_at)
        )
        .scalars()
        .all()
    )
    items: list[dict] = []
    for idx, rec in enumerate(records, start=1):
        items.append(
            {
                "output_id": rec.id,
                "version": idx,
                "output_path": rec.output_path,
                "filename": rec.output_filename,
                "created_at": rec.created_at,
                "download_url": f"/api/tasks/{task.id}/outputs/{rec.id}/download",
            }
        )
    if not items and task.output_path:
        items.append(
            {
                "output_id": "",
                "version": 1,
                "output_path": task.output_path,
                "filename": task.output_filename,
                "created_at": task.finished_at or task.created_at,
                "download_url": f"/api/tasks/{task.id}/download",
            }
        )
    return items


def task_to_out(db: Session, task: VideoTask) -> TaskOut:
    has_output = bool(task.output_path)
    return TaskOut(
        id=task.id,
        batch_id=task.batch_id,
        scene_key=task.scene_key,
        scene_order=task.scene_order,
        image_path=task.image_path,
        image_url=f"/api/tasks/{task.id}/image",
        prompt=task.prompt,
        negative_prompt=task.negative_prompt,
        speech=task.speech,
        width=task.width,
        height=task.height,
        fps=task.fps,
        num_frames=task.num_frames,
        comfy_prompt_id=task.comfy_prompt_id,
        status=task.status,
        output_path=task.output_path,
        video_url=f"/api/tasks/{task.id}/video" if has_output else None,
        download_url=f"/api/tasks/{task.id}/download" if has_output else None,
        error_message=task.error_message,
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
        outputs=task_outputs_of(db, task),
    )


def _get_task(db: Session, task_id: str) -> VideoTask:
    task = db.get(VideoTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task


def _resolve_output(task: VideoTask) -> Path:
    """只允许访问数据库登记的输出文件,并防目录穿越。"""
    if not task.output_path:
        raise HTTPException(status_code=404, detail="该任务尚无输出视频")
    path = (settings.data_root / task.output_path).resolve()
    outputs_root = settings.outputs_dir.resolve()
    if not str(path).startswith(str(outputs_root)):
        raise HTTPException(status_code=403, detail="非法输出路径")
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"输出文件不存在:{task.output_path}")
    return path


def _download_name(db: Session, task: VideoTask) -> str:
    batch = db.get(Batch, task.batch_id)
    title = re.sub(r'[\\/:*?"<>|\s]+', "_", (batch.title if batch else "") or "未命名")[:40]
    speech = re.sub(r'[\\/:*?"<>|\s]+', "_", task.speech)[:16]
    suffix = speech or task.scene_key
    return f"{title}_{task.scene_order:02d}_{suffix}.mp4"


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(task_id: str, db: Session = Depends(get_db)):
    return task_to_out(db, _get_task(db, task_id))


@router.get("/{task_id}/image")
async def get_task_image(task_id: str, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    if not task.image_path:
        raise HTTPException(status_code=404, detail="该任务没有首帧图片")
    path = (settings.data_root / task.image_path).resolve()
    uploads_root = settings.uploads_dir.resolve()
    if not str(path).startswith(str(uploads_root)):
        raise HTTPException(status_code=403, detail="非法图片路径")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="首帧图片文件不存在")
    return FileResponse(path)


@router.get("/{task_id}/video")
async def get_task_video(task_id: str, db: Session = Depends(get_db)):
    path = _resolve_output(_get_task(db, task_id))
    return FileResponse(path, media_type="video/mp4")


@router.get("/{task_id}/download")
async def download_task_video(task_id: str, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    path = _resolve_output(task)
    from urllib.parse import quote

    filename = _download_name(db, task)
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.post("/{task_id}/retry", response_model=TaskOut)
async def retry(task_id: str, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    if task.status in ("queued", "running", "submitting"):
        raise HTTPException(status_code=409, detail="任务正在排队或生成中,不能重试")
    out = await retry_task(db, task)
    return task_to_out(db, out)


class TaskParamsRequest(BaseModel):
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    num_frames: int | None = None
    prompt: str | None = None
    negative_prompt: str | None = None
    speech: str | None = None


@router.put("/{task_id}/params", response_model=TaskOut)
async def update_params(task_id: str, req: TaskParamsRequest, db: Session = Depends(get_db)):
    """修改场景生成参数,保存后重试即按新参数二次创作。"""
    task = _get_task(db, task_id)
    if task.status in ("queued", "running", "submitting"):
        raise HTTPException(status_code=409, detail="任务正在排队或生成中,不能修改参数")
    updates = req.model_dump(exclude_none=True)
    for key, (low, high) in PARAM_RANGES.items():
        if key in updates and not (low <= updates[key] <= high):
            raise HTTPException(status_code=400, detail=f"{key} 取值 {updates[key]} 超出合法范围 [{low}, {high}]")
    if "prompt" in updates and not updates["prompt"].strip():
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    for key, value in updates.items():
        setattr(task, key, value)
    db.commit()
    return task_to_out(db, task)


@router.get("/{task_id}/outputs/{output_id}/download")
async def download_task_output(task_id: str, output_id: str, db: Session = Depends(get_db)):
    """下载指定版本的历史输出视频。"""
    task = _get_task(db, task_id)
    record = db.get(TaskOutput, output_id)
    if record is None or record.task_id != task.id:
        raise HTTPException(status_code=404, detail="输出记录不存在")
    path = (settings.data_root / record.output_path).resolve()
    outputs_root = settings.outputs_dir.resolve()
    if not str(path).startswith(str(outputs_root)) or not path.is_file():
        raise HTTPException(status_code=404, detail=f"输出文件不存在:{record.output_path}")
    from urllib.parse import quote

    filename = _download_name(db, task)
    return FileResponse(
        path,
        media_type="video/mp4",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )
