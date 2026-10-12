"""服务器控制中心数据模型(任务04/05)。

- ServerOperation:所有修改型服务器操作的审计日志(功耗、服务、环境准备)。
- ServerSetting:KV 设置(默认功耗等),服务注册表刻意放配置文件而非数据库,
  防止 Web 页面动态扩权。
"""
from __future__ import annotations

import time

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _now() -> int:
    return int(time.time())


class ServerOperation(Base):
    __tablename__ = "server_operations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(40), default="")
    action: Mapped[str] = mapped_column(String(50), index=True)
    target_type: Mapped[str] = mapped_column(String(20), default="")
    target_name: Mapped[str] = mapped_column(String(100), default="")
    parameters_json: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(String(20), default="success")  # success / failed
    error_message: Mapped[str] = mapped_column(Text, default="")
    source_ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[int] = mapped_column(Integer, default=_now, index=True)
    finished_at: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ServerSetting(Base):
    __tablename__ = "server_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[int] = mapped_column(Integer, default=_now, onupdate=_now)
