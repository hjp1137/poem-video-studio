"""GPU 工作负载 API:自动检测占用 GPU 的容器/服务,并提供受控停止。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.core.security import require_token
from app.services import workloads

router = APIRouter(prefix="/v1/gpu-workloads", tags=["workloads"], dependencies=[Depends(require_token)])


@router.get("")
def list_workloads() -> dict:
    try:
        items = workloads.detect_gpu_workloads()
    except workloads.WorkloadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"workloads": items}


@router.post("/{container}/stop")
def stop_workload(container: str) -> dict:
    try:
        return workloads.stop_docker_workload(container)
    except workloads.WorkloadError as exc:
        message = str(exc)
        if "未占用 GPU" in message or "非法字符" in message:
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=502, detail=message) from exc
