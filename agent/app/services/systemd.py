"""systemd 服务控制:固定动词 + 注册表 unit,机器可解析属性,健康两层判定。"""
from __future__ import annotations

import logging
import time

import httpx

from app.core.config import agent_settings
from app.services.registry import ServiceDef
from app.services.runner import CommandError, run

logger = logging.getLogger("poem.agent.systemd")

_SHOW_PROPERTIES = "ActiveState,SubState,LoadState,MainPID,ExecMainStartTimestampMsec"
_VERBS = ("start", "stop", "restart")
LOG_DEFAULT_LINES = 100
LOG_MAX_LINES = 1000


class SystemdError(Exception):
    """systemctl / journalctl 执行失败。"""


def _show(unit: str) -> dict[str, str]:
    argv = [agent_settings.systemctl, "show", unit, f"--property={_SHOW_PROPERTIES}"]
    try:
        proc = run(argv)
    except CommandError as exc:
        raise SystemdError(str(exc)) from exc
    props: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            props[key.strip()] = value.strip()
    return props


def process_state(unit: str) -> str:
    """把 systemd ActiveState/SubState 映射为受控枚举。"""
    props = _show(unit)
    load_state = props.get("LoadState", "")
    if load_state == "not-found":
        return "unknown"
    active, sub = props.get("ActiveState", ""), props.get("SubState", "")
    if active == "active":
        if sub == "running":
            return "running"
        if sub in ("auto-restart", "start-pre", "start"):
            return "activating"
        return "unknown"
    if active == "activating":
        return "activating"
    if active == "deactivating":
        return "deactivating"
    if active == "failed":
        return "failed"
    if active == "inactive":
        return "stopped"
    return "unknown"


def unit_pid_started(unit: str) -> tuple[int | None, int | None]:
    """返回 (MainPID, 启动时间 epoch 秒);未运行时为 (None, None)。"""
    props = _show(unit)
    try:
        pid = int(props.get("MainPID") or 0) or None
    except ValueError:
        pid = None
    started: int | None = None
    msec = props.get("ExecMainStartTimestampMsec", "0")
    if msec and msec.isdigit():
        started = int(msec) // 1000
    return pid, started


def service_action(unit: str, verb: str) -> None:
    if verb not in _VERBS:
        raise SystemdError(f"非法动词:{verb}")
    argv = [agent_settings.systemctl, verb, unit]
    try:
        run(argv, sudo=agent_settings.use_sudo, timeout=120.0)
    except CommandError as exc:
        raise SystemdError(f"systemctl {verb} {unit} 失败:{exc}") from exc
    logger.info("systemctl %s %s ok", verb, unit)


def service_logs(unit: str, lines: int = LOG_DEFAULT_LINES) -> list[str]:
    """journalctl 固定参数读取最近日志;行数内部收敛,不接收用户自定义参数。"""
    lines = max(1, min(int(lines), LOG_MAX_LINES))
    argv = [
        agent_settings.journalctl, "-u", unit,
        "-n", str(lines), "--no-pager", "-o", "short-iso",
    ]
    try:
        proc = run(argv)
    except CommandError as exc:
        raise SystemdError(f"journalctl 读取 {unit} 失败:{exc}") from exc
    return proc.stdout.splitlines()


def health_state(service: ServiceDef, state: str) -> str:
    """health 与 process 分层:systemd active 不等于 Ready,必须实测 HTTP。"""
    if state == "activating":
        return "starting"
    if state != "running" or service.health.type != "http" or not service.health.url:
        return "unknown"
    try:
        with httpx.Client(timeout=service.health.timeout) as client:
            resp = client.get(service.health.url)
    except httpx.HTTPError:
        return "unhealthy"
    return "healthy" if resp.status_code < 500 else "unhealthy"


def service_status(service: ServiceDef) -> dict:
    state = process_state(service.unit)
    pid, started = unit_pid_started(service.unit)
    uptime = max(0, int(time.time()) - started) if (state == "running" and started) else None
    return {
        "name": service.name,
        "display_name": service.display_name,
        "unit": service.unit,
        "gpu_profile": service.gpu_profile,
        "description": service.description,
        "process_state": state,
        "health_state": health_state(service, state),
        "health_url": service.health.url if service.health.type == "http" else "",
        "pid": pid,
        "started_at": started,
        "uptime_seconds": uptime,
    }
