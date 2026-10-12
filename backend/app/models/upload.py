"""UploadFile 数据模型:批次创建前的暂存上传记录。"""
from __future__ import annotations

import time

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UploadFile(Base):
    __tablename__ = "upload_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    group_id: Mapped[str] = mapped_column(String(32), index=True)
    original_name: Mapped[str] = mapped_column(String(300))
    stored_path: Mapped[str] = mapped_column(String(600))   # 相对 data_root
    guessed_scene_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[int] = mapped_column(Integer, default=time.time)
