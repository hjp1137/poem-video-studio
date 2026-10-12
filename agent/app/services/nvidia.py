"""NVIDIA GPU 数据采集:只使用 nvidia-smi 机器可解析的 query 参数,不做人类格式切割。"""
from __future__ import annotations

import csv
import io

from app.core.config import agent_settings
from app.services.runner import CommandError, run

# 基础字段:主流驱动均支持
_BASE_FIELDS = [
    "index", "uuid", "name", "temperature.gpu", "utilization.gpu",
    "memory.used", "memory.total", "power.draw", "power.limit", "pstate", "fan.speed",
]
# 功耗区间字段:较新驱动才支持,失败时降级为 null
_LIMIT_FIELDS = ["power.min_limit", "power.max_limit"]
# GPU 计算进程字段
_PROCESS_FIELDS = ["gpu_uuid", "pid", "process_name", "used_memory"]


class NvidiaError(Exception):
    """nvidia-smi 采集/执行失败。"""


def _query(fields: list[str]) -> list[list[str]]:
    argv = [
        agent_settings.nvidia_smi,
        f"--query-gpu={','.join(fields)}",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = run(argv)
    except CommandError as exc:
        raise NvidiaError(str(exc)) from exc
    # nvidia-smi 以 ", " 分隔且对含逗号字段加引号;skipinitialspace 让 csv 正确识别引号字段
    rows = [row for row in csv.reader(io.StringIO(proc.stdout), skipinitialspace=True) if row]
    return rows


def _cell(row: list[str], pos: int) -> str:
    return row[pos].strip() if pos < len(row) else ""


def _to_num(value: str) -> int | float | None:
    """'[N/A]'、空串返回 None;整数优先,其次浮点。"""
    value = value.strip()
    if not value or value.upper() in ("[N/A]", "N/A", "[NOT SUPPORTED]"):
        return None
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return None


def _gpu_row_to_dict(row: list[str], fields: list[str]) -> dict:
    data: dict = {"min_power_limit_w": None, "max_power_limit_w": None, "processes": []}
    for pos, field in enumerate(fields):
        key = {
            "index": "index", "uuid": "uuid", "name": "name",
            "temperature.gpu": "temperature_c",
            "utilization.gpu": "utilization_gpu_percent",
            "memory.used": "memory_used_mib", "memory.total": "memory_total_mib",
            "power.draw": "power_draw_w", "power.limit": "power_limit_w",
            "power.min_limit": "min_power_limit_w", "power.max_limit": "max_power_limit_w",
            "pstate": "pstate", "fan.speed": "fan_speed_percent",
        }.get(field, field)
        if key in ("uuid", "name", "pstate"):
            data[key] = _cell(row, pos) or None
        else:
            data[key] = _to_num(_cell(row, pos))
    return data


def list_gpus() -> list[dict]:
    """返回全部 GPU 状态;驱动不支持的区间字段为 null,不导致整体失败。"""
    fields = _BASE_FIELDS + _LIMIT_FIELDS
    try:
        rows = _query(fields)
    except NvidiaError:
        # 旧驱动不认识 power.min_limit/max_limit:去掉区间字段重试
        rows = _query(_BASE_FIELDS)
        fields = _BASE_FIELDS
    return [_gpu_row_to_dict(row, fields) for row in rows]


def list_compute_processes() -> list[dict]:
    """返回 GPU 计算进程列表(uuid → 前端经 index 关联)。"""
    argv = [
        agent_settings.nvidia_smi,
        f"--query-compute-apps={','.join(_PROCESS_FIELDS)}",
        "--format=csv,noheader,nounits",
    ]
    try:
        proc = run(argv)
    except CommandError as exc:
        # 无进程时部分驱动返回非 0(No running processes),视为空列表
        if "No running processes" in str(exc):
            return []
        raise NvidiaError(str(exc)) from exc
    result = []
    for row in csv.reader(io.StringIO(proc.stdout), skipinitialspace=True):
        if not row:
            continue
        result.append({
            "gpu_uuid": _cell(row, 0) or None,
            "pid": _to_num(_cell(row, 1)),
            "process_name": _cell(row, 2) or None,
            "used_gpu_memory_mib": _to_num(_cell(row, 3)),
        })
    return result


def gpus_with_processes() -> list[dict]:
    """GPU 状态 + 每卡进程;进程查询失败不影响 GPU 状态返回。"""
    gpus = list_gpus()
    index_by_uuid = {g["uuid"]: g["index"] for g in gpus if g.get("uuid")}
    try:
        processes = list_compute_processes()
    except NvidiaError:
        processes = []
    for proc in processes:
        gpu = next((g for g in gpus if proc.get("gpu_uuid") == g.get("uuid")), None)
        if gpu is not None:
            gpu["processes"].append(proc)
    # 兜底:进程查不到 uuid 时按 index 无法关联,保持只读展示在全局摘要
    return gpus
