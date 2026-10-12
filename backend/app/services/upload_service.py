"""上传文件存储:保存、场景 key 猜测、受控读取。"""
from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.upload import UploadFile

# cover.png / cover.jpg → cover;01.png / 1.png / 1_标题.png → 1
_COVER_RE = re.compile(r"^cover\b", re.IGNORECASE)
_NUM_RE = re.compile(r"^0*(\d{1,3})\b")


def guess_scene_key(filename: str) -> str | None:
    stem = Path(filename).stem.strip()
    if _COVER_RE.match(stem):
        return "cover"
    m = _NUM_RE.match(stem)
    if m:
        return str(int(m.group(1)))
    return None


def _safe_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower().lstrip(".")
    if ext not in settings.allowed_extensions:
        raise HTTPException(
            status_code=415,
            detail=f"不支持的文件类型「.{ext}」,仅支持:{','.join(sorted(settings.allowed_extensions))}",
        )
    return ext


def save_uploads(db: Session, group_id: str, files: list[UploadFile]) -> list[UploadFile]:
    """保存一批上传文件,文件名带 uuid 前缀避免覆盖。"""
    saved: list[UploadFile] = []
    max_bytes = settings.upload_max_size_mb * 1024 * 1024
    for f in files:
        ext = _safe_ext(f.filename or "")
        upload_id = uuid.uuid4().hex[:12]
        dest_dir = settings.uploads_dir / group_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_name = f"{upload_id}_{Path(f.filename or 'image').name}"
        dest = dest_dir / dest_name
        size = 0
        with dest.open("wb") as out:
            while chunk := f.file.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件「{f.filename}」超过单文件上限 {settings.upload_max_size_mb}MB",
                    )
                out.write(chunk)
        record = UploadFile(
            id=upload_id,
            group_id=group_id,
            original_name=f.filename or dest_name,
            stored_path=str(dest.relative_to(settings.data_root)).replace("\\", "/"),
            guessed_scene_key=guess_scene_key(f.filename or ""),
            size=size,
        )
        db.add(record)
        saved.append(record)
    db.commit()
    return saved


def get_upload_path(db: Session, upload_id: str) -> Path:
    record = db.get(UploadFile, upload_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"上传文件不存在:{upload_id}")
    path = (settings.data_root / record.stored_path).resolve()
    if not str(path).startswith(str(settings.uploads_dir.resolve())):
        raise HTTPException(status_code=403, detail="非法文件路径")
    if not path.is_file():
        raise HTTPException(status_code=404, detail="上传文件已丢失")
    return path


def copy_into_batch(db: Session, upload_id: str, batch_id: str, dest_stem: str) -> str:
    """把上传图片复制到 uploads/{batch_id}/ 下,返回相对 data_root 的新路径。"""
    src = get_upload_path(db, upload_id)
    dest_dir = settings.uploads_dir / batch_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{dest_stem}{src.suffix.lower()}"
    shutil.copy2(src, dest)
    return str(dest.relative_to(settings.data_root)).replace("\\", "/")
