"""GPU API:状态查询与 Power Limit(所有变更动作内部构造 nvidia-smi 参数)。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import agent_settings
from app.core.security import require_token
from app.services import nvidia, power

router = APIRouter(prefix="/v1", tags=["gpu"], dependencies=[Depends(require_token)])


class PowerLimitRequest(BaseModel):
    watts: int = Field(gt=0, le=2000)


class GpuPowerConfigRequest(BaseModel):
    enabled: bool = False
    default_power_limit: int | None = Field(default=None, gt=0, le=2000)
    per_gpu: dict[str, int] = Field(default_factory=dict)


@router.get("/gpus")
def get_gpus() -> dict:
    try:
        gpus = nvidia.gpus_with_processes()
    except nvidia.NvidiaError as exc:
        raise HTTPException(status_code=502, detail=f"nvidia-smi 采集失败:{exc}") from exc
    return {"gpus": gpus}


@router.put("/gpus/{index}/power-limit")
def put_power_limit(index: int, req: PowerLimitRequest) -> dict:
    if index < 0:
        raise HTTPException(status_code=404, detail=f"GPU index {index} 不存在")
    try:
        return power.set_power_limit(index, req.watts)
    except power.PowerError as exc:
        message = str(exc)
        if "不存在" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        if "超出驱动允许区间" in message or "必须是正整数" in message or "未上报功耗区间" in message:
            raise HTTPException(status_code=400, detail=message) from exc
        raise HTTPException(status_code=502, detail=message) from exc


@router.get("/gpu-power/config")
def get_gpu_power_config() -> dict:
    try:
        config = power.load_config()
    except power.PowerConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return config.to_dict()


@router.put("/gpu-power/config")
def put_gpu_power_config(req: GpuPowerConfigRequest) -> dict:
    try:
        config = power.GpuPowerConfig(
            enabled=req.enabled,
            default_power_limit=req.default_power_limit,
            per_gpu={str(k): v for k, v in req.per_gpu.items()},
        )
        power.save_config(config)
    except power.PowerError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return power.load_config().to_dict()
