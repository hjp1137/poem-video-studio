"""系统状态 API:健康检查与运行状态,不触发任何 H3 推理。"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.database import engine
from app.services import workflow_template_service
from app.services.comfyui_client import ComfyUIClient, ComfyUIError

router = APIRouter(prefix="/api/system", tags=["system"])


def _check_sqlite() -> tuple[bool, str]:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "正常"
    except Exception as exc:
        return False, f"异常:{exc}"


def _check_data_dir() -> tuple[bool, str]:
    try:
        settings.ensure_dirs()
        probe = settings.data_root / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, "可写"
    except Exception as exc:
        return False, f"不可写:{exc}"


def _check_workflow() -> tuple[bool, str]:
    # 以「模板管理」页设置的默认模板为准(存于 DATA_ROOT/workflows)
    try:
        workflow_template_service.get_default_adapter()
    except FileNotFoundError as exc:
        return False, f"失效:{exc}"
    except (ValueError, OSError) as exc:
        return False, f"失效:{exc}"
    return True, f"正常(默认模板:{workflow_template_service.get_default()})"


async def _check_comfyui() -> dict:
    client = ComfyUIClient(
        base_url=settings.comfyui_base_url,
        client_id=settings.comfyui_client_id,
        connect_timeout=settings.comfyui_connect_timeout,
    )
    result: dict = {"http": [False, "异常"], "queue": [False, "不可用"]}
    try:
        ok = await client.ping()
        result["http"] = [ok, "正常" if ok else f"不可达:{settings.comfyui_base_url}"]
        if ok:
            try:
                queue = await client.get_queue()
                running = len(queue.get("queue_running", []))
                pending = len(queue.get("queue_pending", []))
                result["queue"] = [True, f"可用(执行中 {running},排队 {pending})"]
            except ComfyUIError as exc:
                result["queue"] = [False, f"不可用:{exc}"]
    finally:
        await client.aclose()
    return result


def _assemble(api_ok: bool, sqlite_, data_dir, workflow_, comfy) -> dict:
    checks = {
        "api": [api_ok, "正常" if api_ok else "异常"],
        "sqlite": list(sqlite_),
        "data_dir": list(data_dir),
        "workflow_template": list(workflow_),
        "comfyui_http": list(comfy["http"]),
        "comfyui_queue": list(comfy["queue"]),
    }
    critical = ["api", "sqlite", "data_dir"]
    if all(checks[k][0] for k in critical):
        overall = "ok" if all(v[0] for v in checks.values()) else "degraded"
    else:
        overall = "error"
    return {"status": overall, "checks": {k: {"ok": v[0], "message": v[1]} for k, v in checks.items()}}


@router.get("/health")
async def health():
    comfy = await _check_comfyui()
    return _assemble(True, _check_sqlite(), _check_data_dir(), _check_workflow(), comfy)


@router.get("/status")
async def status():
    return await health()


@router.get("/comfyui")
async def comfyui_status():
    return await _check_comfyui()
