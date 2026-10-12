"""上传 API。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import UploadItem, UploadResponse
from app.services import upload_service

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post("", response_model=UploadResponse)
async def upload_images(files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    if not files:
        return UploadResponse(group_id="", files=[])
    group_id = uuid.uuid4().hex[:12]
    saved = upload_service.save_uploads(db, group_id, files)
    return UploadResponse(
        group_id=group_id,
        files=[
            UploadItem(
                upload_id=r.id,
                original_name=r.original_name,
                guessed_scene_key=r.guessed_scene_key,
                size=r.size,
                image_url=f"/api/uploads/{r.id}/image",
            )
            for r in saved
        ],
    )


@router.get("/{upload_id}/image")
async def get_upload_image(upload_id: str, db: Session = Depends(get_db)):
    path = upload_service.get_upload_path(db, upload_id)
    return FileResponse(path)
