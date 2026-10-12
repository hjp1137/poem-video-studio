"""服务器控制中心 API:GPU、服务、设置、环境准备与操作日志。

Web API 不直接执行 nvidia-smi/systemctl 等宿主机命令,全部经 Agent;
所有修改型动作写 ServerOperation 审计(含 request_id 与来源 IP)。
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.models.task import VideoTask
from app.schemas.server import (
    BulkPowerLimitRequest,
    GpuPowerSettingsRequest,
    PowerLimitRequest,
    PrepareStartResponse,
    ServiceActionRequest,
)
from app.services import env_prepare, server_service
from app.services.agent_client import AgentError, AgentUnreachable, AgentResponseError, agent_client
from app.services.comfyui_client import ComfyUIClient, ComfyUIError
from app.services.server_service import operation_to_out

router = APIRouter(prefix="/api/server", tags=["server"])


def _meta(request: Request) -> tuple[str, str]:
    return uuid.uuid4().hex, (request.client.host if request.client else "")


def _agent_http_status(exc: AgentError) -> int:
    if isinstance(exc, AgentUnreachable):
        return 503
    if isinstance(exc, AgentResponseError):
        return 502 if exc.status_code >= 500 else exc.status_code
    return 502


def _fail(exc: AgentError) -> HTTPException:
    return HTTPException(status_code=_agent_http_status(exc), detail=str(exc))


# ---- 总览 ----

@router.get("/summary")
async def summary():
    client = agent_client()
    result: dict = {"agent": {"ok": False, "message": ""}, "gpus": [], "services": [], "environment": {}}
    try:
        try:
            health = await client.health()
            result["agent"] = {"ok": health.get("status") in ("ok", "degraded"), "message": health.get("status", "")}
            result["agent"]["problems"] = health.get("problems", [])
            gpus = await client.get_gpus()
            services = await client.list_services()
        except AgentError as exc:
            result["agent"] = {"ok": False, "message": str(exc)}
            result["environment"] = {"ready": False, "reason": "agent_offline"}
            return result
    finally:
        await client.aclose()

    result["gpus"] = gpus
    result["services"] = services
    by_name = {s.get("name"): s for s in services}
    h3 = by_name.get(env_prepare.H3_SERVICE)
    comfy = by_name.get(env_prepare.COMFYUI_SERVICE)
    env_ready = bool(
        h3 and comfy
        and h3.get("process_state") == "running" and h3.get("health_state") == "healthy"
        and comfy.get("process_state") == "running" and comfy.get("health_state") == "healthy"
        and gpus
    )
    result["environment"] = {
        "ready": env_ready,
        "minimax_h3": _service_brief(h3),
        "comfyui": _service_brief(comfy),
        "gpu_count": len(gpus),
        "power_limits": [g.get("power_limit_w") for g in gpus],
        "prepare": env_prepare.current_run().to_dict(),
    }
    return result


def _service_brief(service: dict | None) -> dict:
    if not service:
        return {"registered": False, "process_state": "unknown", "health_state": "unknown"}
    return {
        "registered": True,
        "process_state": service.get("process_state"),
        "health_state": service.get("health_state"),
    }


# ---- GPU ----

@router.get("/gpus")
async def get_gpus():
    client = agent_client()
    try:
        gpus = await client.get_gpus()
    except AgentError as exc:
        raise _fail(exc)
    finally:
        await client.aclose()
    return {"agent_online": True, "gpus": gpus}


@router.put("/gpus/{index}/power-limit")
async def set_gpu_power_limit(index: int, req: PowerLimitRequest, request: Request, db: Session = Depends(get_db)):
    if index < 0:
        raise HTTPException(status_code=404, detail=f"GPU index {index} 不存在")
    request_id, source_ip = _meta(request)
    client = agent_client()
    try:
        outcome = await client.set_gpu_power_limit(index, req.watts)
    except AgentError as exc:
        server_service.record_operation(
            db, request_id=request_id, action="gpu.power_limit", target_type="gpu",
            target_name=f"gpu{index}", parameters={"watts": req.watts}, result="failed",
            error_message=str(exc), source_ip=source_ip,
        )
        raise _fail(exc)
    finally:
        await client.aclose()
    server_service.record_operation(
        db, request_id=request_id, action="gpu.power_limit", target_type="gpu",
        target_name=f"gpu{index}",
        parameters={"watts": req.watts, "before": outcome.get("before_watts"), "after": outcome.get("after_watts")},
        result="success", source_ip=source_ip,
    )
    return outcome


@router.put("/gpus/power-limit")
async def set_all_gpu_power_limits(req: BulkPowerLimitRequest, request: Request, db: Session = Depends(get_db)):
    """逐卡调用 Agent,逐卡返回结果;任何一张失败都不伪装全部成功。"""
    request_id, source_ip = _meta(request)
    client = agent_client()
    try:
        try:
            gpus = await client.get_gpus()
        except AgentError as exc:
            raise _fail(exc)
        all_indices = [g.get("index") for g in gpus]
        indices = req.gpu_indices if req.gpu_indices is not None else all_indices
        unknown = [i for i in indices if i not in all_indices]
        if unknown:
            raise HTTPException(status_code=404, detail=f"GPU index 不存在:{unknown}(当前 {all_indices})")

        results = []
        for index in indices:
            try:
                outcome = await client.set_gpu_power_limit(index, req.watts)
                results.append({
                    "index": index, "ok": True,
                    "before_watts": outcome.get("before_watts"), "after_watts": outcome.get("after_watts"),
                })
            except AgentError as exc:
                results.append({"index": index, "ok": False, "error": str(exc)})
    finally:
        await client.aclose()

    all_ok = all(r["ok"] for r in results) and bool(results)
    server_service.record_operation(
        db, request_id=request_id, action="gpu.power_limit_bulk", target_type="gpu",
        target_name=",".join(f"gpu{i}" for i in indices), parameters={"watts": req.watts, "gpu_indices": indices},
        result="success" if all_ok else "failed",
        error_message=";".join(f"gpu{r['index']}:{r.get('error')}" for r in results if not r["ok"]),
        source_ip=source_ip,
    )
    return {"all_ok": all_ok, "watts": req.watts, "results": results}


# ---- GPU 功耗设置(默认值 + 开机自动应用)----

@router.get("/settings/gpu-power")
async def get_gpu_power_settings(db: Session = Depends(get_db)):
    local = server_service.get_gpu_power_setting(db)
    client = agent_client()
    try:
        agent_config = await client.get_gpu_power_config()
    except AgentError as exc:
        return {**local, "agent_online": False, "agent_config": None, "agent_message": str(exc)}
    finally:
        await client.aclose()
    return {**local, "agent_online": True, "agent_config": agent_config}


@router.put("/settings/gpu-power")
async def put_gpu_power_settings(req: GpuPowerSettingsRequest, request: Request, db: Session = Depends(get_db)):
    request_id, source_ip = _meta(request)
    try:
        local = server_service.put_gpu_power_setting(db, req.enabled, req.default_power_limit)
    except server_service.SettingError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    agent_synced = False
    apply_results: list | None = None
    client = agent_client()
    try:
        # 开机自动应用依赖 Agent 侧配置文件:同步落盘(原子替换)
        await client.put_gpu_power_config({
            "enabled": req.enabled,
            "default_power_limit": req.default_power_limit,
            "per_gpu": {},
        })
        agent_synced = True
        if req.apply_now and req.default_power_limit is not None:
            gpus = await client.get_gpus()
            apply_results = []
            for gpu in gpus:
                index = gpu.get("index")
                try:
                    outcome = await client.set_gpu_power_limit(index, req.default_power_limit)
                    apply_results.append({"index": index, "ok": True, "after_watts": outcome.get("after_watts")})
                except AgentError as exc:
                    apply_results.append({"index": index, "ok": False, "error": str(exc)})
    except AgentError as exc:
        # Agent 离线:本地设置仍保存,如实报告未同步
        server_service.record_operation(
            db, request_id=request_id, action="settings.gpu_power", target_type="settings",
            target_name="gpu_power", parameters=local, result="failed", error_message=f"Agent 同步失败:{exc}",
            source_ip=source_ip,
        )
        return {**local, "agent_synced": False, "agent_message": str(exc), "apply_results": None}
    finally:
        await client.aclose()

    server_service.record_operation(
        db, request_id=request_id, action="settings.gpu_power", target_type="settings",
        target_name="gpu_power",
        parameters={**local, "apply_now": req.apply_now, "agent_synced": agent_synced},
        result="success", source_ip=source_ip,
    )
    return {**local, "agent_synced": agent_synced, "apply_results": apply_results}


# ---- 模型服务 ----

async def _check_stop_safety(db: Session, name: str) -> str | None:
    """停止/重启保护:返回阻断原因;无风险返回 None。"""
    active = db.execute(
        select(func.count(VideoTask.id)).where(VideoTask.status.in_(("queued", "running", "submitting")))
    ).scalar_one()
    if active and name in (env_prepare.H3_SERVICE, env_prepare.COMFYUI_SERVICE):
        return f"当前有 {active} 个 PoemVideo 生成任务在排队/执行,停止 {name} 会中断视频生成"
    if name == env_prepare.COMFYUI_SERVICE:
        client = ComfyUIClient(
            base_url=settings.comfyui_base_url,
            client_id=settings.comfyui_client_id,
            connect_timeout=settings.comfyui_connect_timeout,
        )
        try:
            queue = await client.get_queue()
        except ComfyUIError:
            return None  # ComfyUI 不可达时不阻断停止(本来就可能因为要停它)
        finally:
            await client.aclose()
        busy = len(queue.get("queue_running", [])) + len(queue.get("queue_pending", []))
        if busy:
            return f"ComfyUI 队列非空(执行中+排队 {busy} 项),停止会丢弃/中断这些任务"
    return None


async def _service_action(name: str, verb: str, req: ServiceActionRequest | None, request: Request, db: Session):
    request_id, source_ip = _meta(request)
    force = bool(req and req.force)
    if verb in ("stop", "restart") and not force:
        reason = await _check_stop_safety(db, name)
        if reason:
            server_service.record_operation(
                db, request_id=request_id, action=f"service.{verb}", target_type="service",
                target_name=name, parameters={"force": False}, result="blocked", error_message=reason,
                source_ip=source_ip,
            )
            raise HTTPException(status_code=409, detail={"message": reason, "reason": "busy", "force_required": True})
    client = agent_client()
    try:
        status = await client.service_action(name, verb)
    except AgentError as exc:
        server_service.record_operation(
            db, request_id=request_id, action=f"service.{verb}", target_type="service",
            target_name=name, parameters={"force": force}, result="failed", error_message=str(exc),
            source_ip=source_ip,
        )
        raise _fail(exc)
    finally:
        await client.aclose()
    server_service.record_operation(
        db, request_id=request_id, action=f"service.{verb}", target_type="service",
        target_name=name, parameters={"force": force}, result="success",
        source_ip=source_ip,
    )
    return status


@router.get("/services")
async def list_services():
    client = agent_client()
    try:
        services = await client.list_services()
    except AgentError as exc:
        raise _fail(exc)
    finally:
        await client.aclose()
    return {"agent_online": True, "services": services}


@router.get("/services/{name}")
async def get_service(name: str):
    client = agent_client()
    try:
        status = await client.get_service(name)
    except AgentError as exc:
        raise _fail(exc)
    finally:
        await client.aclose()
    return status


@router.post("/services/{name}/start")
async def start_service(name: str, request: Request, req: ServiceActionRequest | None = None, db: Session = Depends(get_db)):
    return await _service_action(name, "start", req, request, db)


@router.post("/services/{name}/stop")
async def stop_service(name: str, request: Request, req: ServiceActionRequest | None = None, db: Session = Depends(get_db)):
    return await _service_action(name, "stop", req, request, db)


@router.post("/services/{name}/restart")
async def restart_service(name: str, request: Request, req: ServiceActionRequest | None = None, db: Session = Depends(get_db)):
    return await _service_action(name, "restart", req, request, db)


@router.get("/services/{name}/logs")
async def service_logs(name: str, lines: int = Query(default=100, ge=1, le=1000)):
    client = agent_client()
    try:
        logs = await client.service_logs(name, lines)
    except AgentError as exc:
        raise _fail(exc)
    finally:
        await client.aclose()
    return logs


# ---- GPU 工作负载(自动检测占用 GPU 的服务清单)----

@router.get("/gpu-workloads")
async def get_gpu_workloads():
    client = agent_client()
    try:
        workloads = await client.get_gpu_workloads()
    except AgentError as exc:
        raise _fail(exc)
    finally:
        await client.aclose()
    return {"agent_online": True, "workloads": workloads}


@router.post("/gpu-workloads/{container}/stop")
async def stop_gpu_workload(container: str, request: Request, db: Session = Depends(get_db)):
    """停止一个当前占用 GPU 的 Docker 容器(Agent 侧动态白名单校验)。"""
    import re

    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", container):
        raise HTTPException(status_code=400, detail=f"非法容器名:{container}")
    request_id, source_ip = _meta(request)
    client = agent_client()
    try:
        outcome = await client.stop_gpu_workload(container)
    except AgentError as exc:
        server_service.record_operation(
            db, request_id=request_id, action="workload.docker_stop", target_type="docker",
            target_name=container, parameters={}, result="failed", error_message=str(exc),
            source_ip=source_ip,
        )
        raise _fail(exc)
    finally:
        await client.aclose()
    server_service.record_operation(
        db, request_id=request_id, action="workload.docker_stop", target_type="docker",
        target_name=container,
        parameters={"freed_memory_mib": outcome.get("freed_memory_mib")},
        result="success", source_ip=source_ip,
    )
    return outcome


# ---- 一键环境准备 ----

@router.get("/environment/h3/profile")
async def environment_profile():
    """只读返回 h3_video Profile,供前端「手动逐项准备」展示目标功耗与操作清单。"""
    try:
        return env_prepare.load_profile().to_dict()
    except env_prepare.ProfileError as exc:
        raise HTTPException(status_code=500, detail=f"环境 Profile 配置错误:{exc}")


@router.post("/environment/h3/prepare", response_model=PrepareStartResponse)
async def prepare_environment():
    try:
        run = env_prepare.start_prepare()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except env_prepare.ProfileError as exc:
        raise HTTPException(status_code=500, detail=f"环境 Profile 配置错误:{exc}")
    return PrepareStartResponse(started=True, message=f"已开始执行「{run.profile.get('display_name', '')}」准备流程")


@router.get("/environment/h3/status")
async def prepare_status():
    return env_prepare.current_run().to_dict()


# ---- 操作日志 ----

@router.get("/operations")
async def list_operations_api(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0), db: Session = Depends(get_db)):
    rows, total = server_service.list_operations(db, limit, offset)
    return {"total": total, "items": [operation_to_out(r) for r in rows]}
