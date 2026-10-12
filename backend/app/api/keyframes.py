"""MiniMax H3 首尾帧视频生成 API：直接调用已运行的 FL2VA 服务。"""
from __future__ import annotations

import asyncio
import uuid

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.core.config import settings
from app.services.h3_keyframes import (
    FrameImage, H3RequestError, H3Settings, MAX_IMAGE_BYTES, generate_first_last,
)

router = APIRouter(prefix="/api/h3/keyframes", tags=["h3-keyframes"])
_gate = asyncio.Semaphore(1)  # 首尾帧测试任务串行，避免同时争夺 4×4090


@router.post("/generate")
async def generate(
    first_frame: UploadFile = File(...),
    last_frame: UploadFile = File(...),
    prompt: str = Form(...),
    width: int = Form(768),
    height: int = Form(1024),
    duration: float = Form(5.0),
    seed: int = Form(1101),
    turbo: bool = Form(False),
):
    """返回 MP4；首尾帧始终按上传顺序作为 0、-1 约束。"""
    try:
        first = FrameImage(
            first_frame.filename or "first.png",
            await first_frame.read(MAX_IMAGE_BYTES + 1),
            first_frame.content_type or "",
        )
        last = FrameImage(
            last_frame.filename or "last.png",
            await last_frame.read(MAX_IMAGE_BYTES + 1),
            last_frame.content_type or "",
        )
        params = H3Settings(
            prompt=prompt, width=width, height=height, duration=duration,
            seed=seed, turbo=turbo, turbo_path=settings.h3_turbo_lora_path,
        )
        async with _gate:
            video = await generate_first_last(
                base_url=settings.h3_api_base_url,
                first=first, last=last, settings=params,
            )
    except H3RequestError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await first_frame.close()
        await last_frame.close()

    folder = settings.outputs_dir / "keyframe-tests"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"h3-first-last-{uuid.uuid4().hex}.mp4"
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(video)
    temporary.replace(path)
    return FileResponse(path, media_type="video/mp4", filename=path.name)
