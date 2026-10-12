"""一键「准备 MiniMax H3 视频环境」:后端编排,11 步状态机,后台任务 + 状态查询。

原则(任务05 §13/§14):
- 前端必须能看到步骤进度,而不是长时间只有 loading;
- 幂等:已停止服务 skip、功耗已正确 verified、Running+Healthy 不重复启动;
- 失败即停,保留已完成步骤,返回 failure_step,不做隐式大范围 rollback。
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import yaml

from app.core.config import settings
from app.core.database import SessionLocal
from app.services import server_service
from app.services.agent_client import AgentClient, AgentError, agent_client
from app.services.comfyui_client import ComfyUIClient, ComfyUIError

logger = logging.getLogger("poem.env_prepare")

H3_SERVICE = "minimax_h3"
COMFYUI_SERVICE = "comfyui"


class ProfileError(Exception):
    """profiles.yaml 缺失或非法。"""


@dataclass
class Profile:
    name: str
    display_name: str
    gpu_power_enabled: bool = False
    gpu_power_watts: int | None = None
    stop_services: list[str] = field(default_factory=list)
    start_services: list[str] = field(default_factory=list)
    h3_ready_timeout: int = 300
    comfyui_ready_timeout: int = 120

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "gpu_power": {"enabled": self.gpu_power_enabled, "watts": self.gpu_power_watts},
            "stop_services": self.stop_services,
            "start_services": self.start_services,
            "readiness": {
                "minimax_h3_timeout_seconds": self.h3_ready_timeout,
                "comfyui_timeout_seconds": self.comfyui_ready_timeout,
            },
        }


def load_profile(name: str = "h3_video") -> Profile:
    path = settings.server_profiles_file
    if not path.is_file():
        raise ProfileError(f"Profile 配置不存在:{path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileError(f"Profile 配置解析失败({path}):{exc}") from exc
    profiles = (raw or {}).get("profiles") or {}
    body = profiles.get(name)
    if not isinstance(body, dict):
        raise ProfileError(f"Profile {name} 未配置")
    gpu_power = body.get("gpu_power") or {}
    readiness = body.get("readiness") or {}
    profile = Profile(
        name=name,
        display_name=str(body.get("display_name", name)),
        gpu_power_enabled=bool(gpu_power.get("enabled", False)),
        gpu_power_watts=gpu_power.get("watts"),
        stop_services=[str(s) for s in body.get("stop_services", [])],
        start_services=[str(s) for s in body.get("start_services", [])],
        h3_ready_timeout=int(readiness.get("minimax_h3_timeout_seconds", 300)),
        comfyui_ready_timeout=int(readiness.get("comfyui_timeout_seconds", 120)),
    )
    if profile.gpu_power_enabled and not isinstance(profile.gpu_power_watts, int):
        raise ProfileError(f"Profile {name} gpu_power.watts 必须是整数")
    if H3_SERVICE not in profile.start_services or COMFYUI_SERVICE not in profile.start_services:
        raise ProfileError(f"Profile {name} start_services 必须包含 {H3_SERVICE} 与 {COMFYUI_SERVICE}")
    return profile


# ---- 运行状态(模块级,单实例只允许一个 prepare 任务) ----

@dataclass
class StepState:
    no: int
    key: str
    title: str
    state: str = "pending"  # pending / running / success / skipped / failed
    detail: str = ""
    started_at: int | None = None
    finished_at: int | None = None
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "no": self.no, "key": self.key, "title": self.title, "state": self.state,
            "detail": self.detail, "started_at": self.started_at,
            "finished_at": self.finished_at, "error": self.error,
        }


@dataclass
class PrepareRun:
    state: str = "never"  # never / running / success / failed
    profile: dict = field(default_factory=dict)
    steps: list[StepState] = field(default_factory=list)
    started_at: int | None = None
    finished_at: int | None = None
    failure_step: str = ""
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "state": self.state,
            "profile": self.profile,
            "steps": [s.to_dict() for s in self.steps],
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "failure_step": self.failure_step,
            "error_message": self.error_message,
            "total_seconds": (
                self.finished_at - self.started_at
                if self.started_at and self.finished_at else None
            ),
        }


STEP_TITLES = [
    ("agent_health", "检查 Agent"),
    ("gpu_health", "检查 NVIDIA 驱动与 GPU"),
    ("apply_power", "应用 GPU Power Limit"),
    ("inspect_processes", "巡检 GPU 进程"),
    ("stop_conflicts", "停止冲突的已登记服务"),
    ("start_h3", "启动 MiniMax H3"),
    ("wait_h3", "等待 MiniMax H3 Ready"),
    ("start_comfyui", "启动 ComfyUI"),
    ("wait_comfyui", "等待 ComfyUI Ready"),
    ("check_queue", "检查 ComfyUI Queue API"),
    ("ready", "环境就绪"),
]

_run = PrepareRun()
_task: asyncio.Task | None = None


def current_run() -> PrepareRun:
    return _run


def start_prepare() -> PrepareRun:
    """启动后台准备任务;已有任务运行中时抛 PrepareBusy。"""
    global _task, _run
    if _task is not None and not _task.done():
        raise RuntimeError("环境准备任务正在运行中,请等待完成后再试")
    profile = load_profile()  # 配置非法直接抛错,不启动
    _run = PrepareRun(state="running", profile=profile.to_dict(), started_at=int(time.time()))
    _run.steps = [StepState(no=i + 1, key=key, title=title) for i, (key, title) in enumerate(STEP_TITLES)]
    _task = asyncio.create_task(_execute(profile))
    return _run


class _StepFailed(Exception):
    pass


async def _execute(profile: Profile) -> None:
    steps = {s.key: s for s in _run.steps}

    def begin(key: str, detail: str = "") -> StepState:
        step = steps[key]
        step.state = "running"
        step.started_at = int(time.time())
        step.detail = detail
        return step

    def done(key: str, state: str = "success", detail: str = "") -> None:
        step = steps[key]
        step.state = state
        step.finished_at = int(time.time())
        if detail:
            step.detail = detail

    def fail(key: str, error: str) -> None:
        step = steps[key]
        step.state = "failed"
        step.error = error
        step.finished_at = int(time.time())
        raise _StepFailed(key)

    client = agent_client()
    try:
        # STEP 01 Agent Health
        begin("agent_health")
        try:
            health = await client.health()
        except AgentError as exc:
            fail("agent_health", str(exc))
        done("agent_health", detail=f"Agent 状态 {health.get('status', 'ok')}")

        # STEP 02 GPU Health
        begin("gpu_health")
        try:
            gpus = await client.get_gpus()
        except AgentError as exc:
            fail("gpu_health", str(exc))
        if not gpus:
            fail("gpu_health", "nvidia-smi 未返回任何 GPU(驱动未就绪?)")
        done("gpu_health", detail=f"检测到 {len(gpus)} 张 GPU:" + ",".join(str(g.get("name", "?")) for g in gpus[:4]))

        # STEP 03 Apply Power Limit(已正确的卡 verified,不重复设置)
        begin("apply_power")
        if not profile.gpu_power_enabled or profile.gpu_power_watts is None:
            done("apply_power", "skipped", "Profile 未启用功耗设置")
        else:
            applied, verified = [], []
            for gpu in gpus:
                index = gpu.get("index")
                if gpu.get("power_limit_w") == profile.gpu_power_watts:
                    verified.append(index)
                    continue
                try:
                    outcome = await client.set_gpu_power_limit(index, profile.gpu_power_watts)
                    applied.append(f"GPU{index}:{outcome.get('before_watts')}→{outcome.get('after_watts')}W")
                except AgentError as exc:
                    fail("apply_power", f"GPU{index} 设置 {profile.gpu_power_watts}W 失败:{exc}")
            done("apply_power", detail=(
                f"目标 {profile.gpu_power_watts}W;已验证一致 {len(verified)} 张"
                + (f";已设置 {';'.join(applied)}" if applied else "")
            ))
            gpus = await client.get_gpus()

        # STEP 04 Inspect GPU Processes(只读展示,不提供 kill)
        begin("inspect_processes")
        process_lines = []
        for gpu in gpus:
            for proc in gpu.get("processes") or []:
                process_lines.append(
                    f"GPU{gpu.get('index')} PID {proc.get('pid')} {proc.get('process_name', '?')}"
                    f" {proc.get('used_gpu_memory_mib', '?')}MiB(非受管进程,只读)"
                )
        done("inspect_processes", detail=(
            ";".join(process_lines) if process_lines else "GPU 上无第三方计算进程"
        ))

        # STEP 05 Stop Registered Conflicting Services(已停止 → skip)
        begin("stop_conflicts")
        stopped, skipped = [], []
        for name in profile.stop_services:
            try:
                status = await client.get_service(name)
            except AgentError as exc:
                fail("stop_conflicts", f"读取冲突服务 {name} 状态失败:{exc}")
            if status.get("process_state") == "stopped":
                skipped.append(name)
                continue
            try:
                await client.service_action(name, "stop")
                stopped.append(name)
            except AgentError as exc:
                fail("stop_conflicts", f"停止冲突服务 {name} 失败:{exc}")
        done("stop_conflicts", detail=(
            (f"已停止 {','.join(stopped)};" if stopped else "")
            + (f"已处于停止 {','.join(skipped)}" if skipped else "") or "Profile 未配置冲突服务"
        ))

        # STEP 06/07 MiniMax H3(Running+Healthy → skip;Running+Unhealthy → restart)
        begin("start_h3")
        await _ensure_service(client, H3_SERVICE, "start_h3", done, fail)

        begin("wait_h3")
        try:
            await _wait_ready(client, H3_SERVICE, profile.h3_ready_timeout)
        except AgentError as exc:
            fail("wait_h3", str(exc))
        done("wait_h3", detail="MiniMax H3 健康检查通过")

        # STEP 08/09 ComfyUI
        begin("start_comfyui")
        await _ensure_service(client, COMFYUI_SERVICE, "start_comfyui", done, fail)

        begin("wait_comfyui")
        try:
            await _wait_ready(client, COMFYUI_SERVICE, profile.comfyui_ready_timeout)
        except AgentError as exc:
            fail("wait_comfyui", str(exc))
        done("wait_comfyui", detail="ComfyUI HTTP 健康检查通过")

        # STEP 10 ComfyUI Queue API(不触发生成)
        begin("check_queue")
        comfy = ComfyUIClient(
            base_url=settings.comfyui_base_url,
            client_id=settings.comfyui_client_id,
            connect_timeout=settings.comfyui_connect_timeout,
        )
        try:
            queue = await comfy.get_queue()
        except ComfyUIError as exc:
            fail("check_queue", f"ComfyUI Queue API 不可用:{exc}")
        finally:
            await comfy.aclose()
        running = len(queue.get("queue_running", []))
        pending = len(queue.get("queue_pending", []))
        done("check_queue", detail=f"Queue 可用(执行中 {running},排队 {pending})")

        # STEP 11 READY
        done("ready", detail="MiniMax H3 视频环境 READY")
        _run.state = "success"
        _run.finished_at = int(time.time())
        _audit("success", "")
        logger.info("环境准备成功 profile=%s 耗时 %.1fs", profile.name, time.time() - _run.started_at)
    except _StepFailed as exc:
        _run.state = "failed"
        _run.failure_step = str(exc)
        _run.error_message = steps[str(exc)].error
        _run.finished_at = int(time.time())
        _audit("failed", f"failure_step={_run.failure_step}:{_run.error_message}")
        logger.warning("环境准备失败 profile=%s step=%s error=%s", profile.name, _run.failure_step, _run.error_message)
    except Exception as exc:  # 兜底:任何意外异常也必须落到状态与审计,不能卡死在 running
        _run.state = "failed"
        _run.failure_step = "internal"
        _run.error_message = f"未预期异常:{exc}"
        _run.finished_at = int(time.time())
        _audit("failed", _run.error_message)
        logger.exception("环境准备未预期异常")
    finally:
        await client.aclose()


async def _ensure_service(client: AgentClient, name: str, step_key: str, done, fail) -> None:
    """幂等启动:Running+Healthy → skip;Running+Unhealthy → restart;否则 start。"""
    try:
        status = await client.get_service(name)
    except AgentError as exc:
        fail(step_key, f"读取服务 {name} 状态失败:{exc}")
    state = status.get("process_state")
    if state == "running" and status.get("health_state") == "healthy":
        done(step_key, "skipped", f"{name} 已在运行且健康,跳过启动")
        return
    verb = "restart" if state == "running" else "start"
    try:
        await client.service_action(name, verb)
    except AgentError as exc:
        fail(step_key, f"{verb} {name} 失败:{exc}")
    done(step_key, detail=f"已执行 {verb} {name}")


async def _wait_ready(client: AgentClient, name: str, timeout: int) -> None:
    """轮询直到 health_state=healthy;超时抛 AgentError(由调用方记为步骤失败)。"""
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        try:
            status = await client.get_service(name)
        except AgentError as exc:
            last = str(exc)
        else:
            last = f"process={status.get('process_state')} health={status.get('health_state')}"
            if status.get("health_state") == "healthy":
                return
        await asyncio.sleep(settings.prepare_poll_interval)
    raise AgentError(f"等待 {name} Ready 超时({timeout}s),最后状态:{last}")


def _audit(result: str, error: str) -> None:
    try:
        db = SessionLocal()
        try:
            server_service.record_operation(
                db,
                request_id="",
                action="environment.prepare",
                target_type="environment",
                target_name="h3_video",
                parameters={"profile": _run.profile},
                result=result,
                error_message=error,
            )
        finally:
            db.close()
    except Exception:
        logger.exception("环境准备审计写入失败")
