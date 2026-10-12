"""服务器控制中心 API 请求/响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class PowerLimitRequest(BaseModel):
    watts: int = Field(gt=0, le=2000)


class BulkPowerLimitRequest(BaseModel):
    watts: int = Field(gt=0, le=2000)
    gpu_indices: list[int] | None = None  # 缺省 = 全部 GPU


class GpuPowerSettingsRequest(BaseModel):
    enabled: bool = False
    default_power_limit: int | None = Field(default=None, gt=0, le=2000)
    apply_now: bool = False  # 保存的同时立即应用到全部 GPU


class ServiceActionRequest(BaseModel):
    force: bool = False  # 停止保护触发后,用户二次确认携带


class PrepareStartResponse(BaseModel):
    started: bool
    message: str = ""
