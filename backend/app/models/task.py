"""VideoTask 数据模型。

任务01 阶段仅使用 pending;任务02/03 扩展字段(comfy_prompt_id、output、
错误信息、起止时间)一并列出,避免后续迁移。
"""
from __future__ import annotations

import time

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.batch import _now


class VideoTask(Base):
    __tablename__ = "video_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("batches.id"), index=True)
    scene_key: Mapped[str] = mapped_column(String(50))
    scene_order: Mapped[int] = mapped_column(Integer)
    image_path: Mapped[str] = mapped_column(String(500), default="")
    prompt: Mapped[str] = mapped_column(Text, default="")
    negative_prompt: Mapped[str] = mapped_column(Text, default="")
    speech: Mapped[str] = mapped_column(Text, default="")
    width: Mapped[int] = mapped_column(Integer, default=768)
    height: Mapped[int] = mapped_column(Integer, default=1024)
    fps: Mapped[int] = mapped_column(Integer, default=24)
    num_frames: Mapped[int] = mapped_column(Integer, default=121)

    comfy_prompt_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    output_path: Mapped[str] = mapped_column(String(500), default="")
    output_filename: Mapped[str] = mapped_column(String(300), default="")
    output_subfolder: Mapped[str] = mapped_column(String(300), default="")
    output_type: Mapped[str] = mapped_column(String(20), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[int] = mapped_column(Integer, default=time.time)
    started_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    finished_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
