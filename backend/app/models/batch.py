"""Batch 数据模型。"""
from __future__ import annotations

import time

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> int:
    return int(time.time())


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    dynasty: Mapped[str] = mapped_column(String(50), default="")
    author: Mapped[str] = mapped_column(String(100), default="")
    raw_batch_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    created_at: Mapped[int] = mapped_column(Integer, default=_now)
    updated_at: Mapped[int] = mapped_column(Integer, default=_now, onupdate=_now)
