"""Agent 健康:进程/配置自检,供上层判断 Agent 存活与配置是否损坏。"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import agent_settings
from app.services import power

router = APIRouter(prefix="/v1", tags=["health"])


@router.get("/health")
def health() -> dict:
    problems: list[str] = []
    # gpu-power.json 非法不得导致 Agent 崩溃:健康接口如实上报配置错误
    try:
        power.load_config()
    except power.PowerConfigError as exc:
        problems.append(str(exc))

    from app.services import registry

    try:
        registry.load_services()
    except registry.RegistryError as exc:
        problems.append(str(exc))

    return {
        "status": "ok" if not problems else "degraded",
        "config_dir": str(agent_settings.config_dir),
        "problems": problems,
    }
