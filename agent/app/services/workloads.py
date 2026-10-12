"""GPU 工作负载检测与受控停止。

检测链:nvidia-smi 计算进程 → /proc/<pid>/cgroup 归属(docker 容器 / systemd unit /
裸进程)→ docker ps 只读映射容器名。停止动作只对「当前实际占用 GPU 显存的容器」
放行(动态白名单),不允许停止任意容器;未归属的裸进程保持只读展示。
"""
from __future__ import annotations

import logging
import re

from app.core.config import agent_settings
from app.services import nvidia
from app.services.runner import CommandError, run

logger = logging.getLogger("poem.agent.workloads")

_CONTAINER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class WorkloadError(Exception):
    """检测或停止失败。"""


def _read_cgroup(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cgroup", encoding="utf-8", errors="replace") as fp:
            return fp.read()
    except OSError:
        return ""


def _read_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fp:
            return fp.read().replace(b"\0", b" ").decode("utf-8", "replace").strip()[:300]
    except OSError:
        return ""


def _docker_container_id(cgroup_text: str) -> str | None:
    """从 cgroup 文本提取 docker 容器 64 位 ID(兼容 v1/v2、docker-xxx.scope)。"""
    for match in re.finditer(r"docker[/-]([0-9a-f]{64})", cgroup_text):
        return match.group(1)
    return None


def _systemd_unit(cgroup_text: str) -> str | None:
    for match in re.finditer(r"([0-9A-Za-z@:\._-]+\.service)", cgroup_text):
        return match.group(1)
    return None


def _docker_ps_mapping() -> dict[str, str]:
    """docker ps 只读查询:容器 full/短 ID → 容器名(固定参数,不接受外部输入)。"""
    argv = [agent_settings.docker, "ps", "--format", "{{.ID}}\t{{.Names}}"]
    try:
        proc = run(argv)
    except CommandError as exc:
        raise WorkloadError(f"docker ps 查询失败:{exc}") from exc
    mapping: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if "\t" not in line:
            continue
        cid, name = line.split("\t", 1)
        mapping[cid.strip()] = name.strip()
    return mapping


def detect_gpu_workloads() -> list[dict]:
    """返回占用 GPU 显存的工作负载清单(按容器/服务/进程归组)。

    kind: docker(容器名可停止)/ systemd(unit,只读,控制走注册表)/
          process(裸进程,只读,不提供 kill)。
    """
    try:
        gpus = nvidia.list_gpus()
        processes = nvidia.list_compute_processes()
    except nvidia.NvidiaError as exc:
        raise WorkloadError(f"nvidia-smi 采集失败:{exc}") from exc

    # pid → cgroup/cmdline(去重,同一容器多进程合并)
    pid_info: dict[int, dict] = {}
    for proc in processes:
        pid = proc.get("pid")
        if pid is None or pid in pid_info:
            continue
        pid_info[int(pid)] = {
            "pid": int(pid),
            "mem": proc.get("used_gpu_memory_mib"),
            "cmdline": _read_cmdline(int(pid)),
            "cgroup": _read_cgroup(int(pid)),
        }

    # uuid → index
    index_by_uuid = {g.get("uuid"): g.get("index") for g in gpus if g.get("uuid")}
    proc_gpu: dict[int, int | None] = {}
    for proc in processes:
        if proc.get("pid") is not None:
            proc_gpu[int(proc["pid"])] = index_by_uuid.get(proc.get("gpu_uuid"))

    docker_names: dict[str, str] = {}
    if any(_docker_container_id(info["cgroup"]) for info in pid_info.values()):
        try:
            docker_names = _docker_ps_mapping()
        except WorkloadError as exc:
            logger.warning("docker ps 映射失败,容器负载将显示 ID:%s", exc)

    groups: dict[tuple[str, str], dict] = {}
    for pid, info in pid_info.items():
        container_id = _docker_container_id(info["cgroup"])
        if container_id:
            name = next(
                (cname for cid, cname in docker_names.items() if container_id.startswith(cid)),
                container_id[:12],
            )
            key = ("docker", name)
        else:
            unit = _systemd_unit(info["cgroup"])
            key = ("systemd", unit) if unit else ("process", f"pid-{pid}")
        group = groups.setdefault(key, {
            "kind": key[0],
            "name": key[1],
            "display_name": key[1],
            "pids": [],
            "gpu_indices": [],
            "used_memory_mib": 0,
            "command": info["cmdline"],
            "stoppable": key[0] == "docker",
        })
        group["pids"].append(pid)
        if info["mem"]:
            group["used_memory_mib"] += int(info["mem"])
        gpu_index = proc_gpu.get(pid)
        if gpu_index is not None and gpu_index not in group["gpu_indices"]:
            group["gpu_indices"].append(gpu_index)

    return sorted(
        groups.values(),
        key=lambda g: -g["used_memory_mib"],
    )


def stop_docker_workload(container: str) -> dict:
    """停止一个占用 GPU 的 Docker 容器。

    安全约束:目标必须是「当前检测到的 GPU 占用容器」(动态白名单),
    拒绝停止任意容器;命令固定参数构造。
    """
    if not _CONTAINER_NAME_RE.match(container):
        raise WorkloadError(f"容器名含非法字符:{container}")
    workloads = detect_gpu_workloads()
    target = next(
        (w for w in workloads if w["kind"] == "docker" and w["name"] == container), None
    )
    if target is None:
        gpu_names = [w["name"] for w in workloads if w["kind"] == "docker"]
        raise WorkloadError(
            f"容器 {container} 当前未占用 GPU,拒绝停止(当前占用 GPU 的容器:{gpu_names or '无'})"
        )
    argv = [agent_settings.docker, "stop", "-t", "30", container]
    try:
        run(argv, timeout=120.0)
    except CommandError as exc:
        raise WorkloadError(f"docker stop {container} 失败:{exc}") from exc
    logger.info("docker stop %s ok(释放显存约 %s MiB)", container, target["used_memory_mib"])
    return {"stopped": container, "freed_memory_mib": target["used_memory_mib"]}
