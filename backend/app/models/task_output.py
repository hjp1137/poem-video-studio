"""任务输出历史:重试多次产生的多个视频都保留可下载。"""
from __future__ import annotations

import time

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TaskOutput(Base):
    __tablename__ = "task_outputs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("video_tasks.id"), index=True)
    batch_id: Mapped[str] = mapped_column(String(32), index=True)
    scene_key: Mapped[str] = mapped_column(String(50), default="")
    output_path: Mapped[str] = mapped_column(String(500), default="")
    output_filename: Mapped[str] = mapped_column(String(300), default="")
    output_subfolder: Mapped[str] = mapped_column(String(300), default="")
    output_type: Mapped[str] = mapped_column(String(50), default="output")
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    note: Mapped[str] = mapped_column(Text, default="")
