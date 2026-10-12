"""服务 API:name 只来自注册表;请求不携带 unit 字符串 / shell / PID / docker 命令。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.core.security import require_token
from app.services import registry, systemd

router = APIRouter(prefix="/v1/services", tags=["services"], dependencies=[Depends(require_token)])


def _resolve_or_404(name: str) -> registry.ServiceDef:
    try:
        return registry.resolve(name)
    except registry.RegistryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("")
def list_services() -> dict:
    try:
        services = registry.load_services()
    except registry.RegistryError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"services": [systemd.service_status(s) for s in services.values()]}


@router.get("/{name}")
def get_service(name: str) -> dict:
    return systemd.service_status(_resolve_or_404(name))


class ActionRequest(BaseModel):
    pass  # 预留扩展(如超时);V1.1 动词由路径决定,不接受额外命令参数


@router.post("/{name}/start")
def start_service(name: str, _req: ActionRequest | None = None) -> dict:
    return _do_action(name, "start")


@router.post("/{name}/stop")
def stop_service(name: str, _req: ActionRequest | None = None) -> dict:
    return _do_action(name, "stop")


@router.post("/{name}/restart")
def restart_service(name: str, _req: ActionRequest | None = None) -> dict:
    return _do_action(name, "restart")


def _do_action(name: str, verb: str) -> dict:
    service = _resolve_or_404(name)
    try:
        systemd.service_action(service.unit, verb)
    except systemd.SystemdError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return systemd.service_status(service)


@router.get("/{name}/logs")
def service_logs(
    name: str,
    lines: int = Query(default=systemd.LOG_DEFAULT_LINES, ge=1, le=systemd.LOG_MAX_LINES),
) -> dict:
    service = _resolve_or_404(name)
    try:
        logs = systemd.service_logs(service.unit, lines)
    except systemd.SystemdError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"name": service.name, "unit": service.unit, "lines": len(logs), "logs": logs}
