"""Power Limit 管理:区间校验、受控设置、gpu-power.json 原子读写与开机批量应用。"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import agent_settings
from app.services import nvidia
from app.services.runner import CommandError, run

logger = logging.getLogger("poem.agent.power")


class PowerError(Exception):
    """功耗设置失败或配置非法。"""


class PowerConfigError(PowerError):
    """gpu-power.json 解析失败(不得导致 Agent 崩溃,由调用方按配置错误上报)。"""


@dataclass
class GpuPowerConfig:
    enabled: bool = False
    default_power_limit: int | None = None
    per_gpu: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "default_power_limit": self.default_power_limit,
            "per_gpu": dict(self.per_gpu),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GpuPowerConfig":
        if not isinstance(data, dict):
            raise PowerConfigError("配置根节点必须是对象")
        enabled = data.get("enabled", False)
        if not isinstance(enabled, bool):
            raise PowerConfigError("enabled 必须是布尔值")
        default = data.get("default_power_limit")
        if default is not None and (not isinstance(default, int) or isinstance(default, bool) or default <= 0):
            raise PowerConfigError("default_power_limit 必须是正整数瓦数")
        per_gpu_raw = data.get("per_gpu", {})
        if not isinstance(per_gpu_raw, dict):
            raise PowerConfigError("per_gpu 必须是对象")
        per_gpu: dict[str, int] = {}
        for key, watts in per_gpu_raw.items():
            if not isinstance(watts, int) or isinstance(watts, bool) or watts <= 0:
                raise PowerConfigError(f"per_gpu[{key}] 必须是正整数瓦数")
            per_gpu[str(key)] = watts
        return cls(enabled=enabled, default_power_limit=default, per_gpu=per_gpu)


def load_config(path: Path | None = None) -> GpuPowerConfig:
    """读取 gpu-power.json;文件不存在返回默认空配置,非法 JSON 抛 PowerConfigError。"""
    path = path or agent_settings.gpu_power_config
    if not path.is_file():
        return GpuPowerConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PowerConfigError(f"gpu-power.json 解析失败({path}):{exc}") from exc
    return GpuPowerConfig.from_dict(data)


def save_config(config: GpuPowerConfig, path: Path | None = None) -> None:
    """原子写入:同目录临时文件 + os.replace,避免半截配置。"""
    path = path or agent_settings.gpu_power_config
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".gpu-power-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(config.to_dict(), fp, ensure_ascii=False, indent=2)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_name, path)
    except OSError as exc:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise PowerError(f"gpu-power.json 写入失败({path}):{exc}") from exc


def set_power_limit(index: int, watts: int) -> dict:
    """校验区间后执行 nvidia-smi -i INDEX -pl WATTS,并回读实际值。

    禁止信任外部提交的 min/max:区间每次都从驱动实查。
    """
    if not isinstance(watts, int) or isinstance(watts, bool) or watts <= 0:
        raise PowerError("watts 必须是正整数")
    try:
        gpus = nvidia.list_gpus()
    except nvidia.NvidiaError as exc:
        raise PowerError(f"无法读取 GPU 状态:{exc}") from exc
    gpu = next((g for g in gpus if g.get("index") == index), None)
    if gpu is None:
        raise PowerError(f"GPU index {index} 不存在(当前共 {len(gpus)} 张卡)")
    before = gpu.get("power_limit_w")
    min_w = gpu.get("min_power_limit_w")
    max_w = gpu.get("max_power_limit_w")
    if min_w is None or max_w is None:
        raise PowerError(
            f"GPU {index} 驱动未上报功耗区间(min/max power limit),拒绝盲设;"
            "请升级 NVIDIA 驱动后重试"
        )
    if watts < min_w or watts > max_w:
        raise PowerError(f"GPU {index} 功耗 {watts}W 超出驱动允许区间 [{min_w}W, {max_w}W]")
    argv = [agent_settings.nvidia_smi, "-i", str(index), "-pl", str(watts)]
    try:
        run(argv, sudo=agent_settings.use_sudo)
    except CommandError as exc:
        raise PowerError(f"nvidia-smi 设置功耗失败:{exc}") from exc
    # 回读实际值,返回 before/requested/after
    try:
        after_gpu = next(
            (g for g in nvidia.list_gpus() if g.get("index") == index), None
        )
    except nvidia.NvidiaError as exc:
        raise PowerError(f"设置后回读失败(设置可能已生效):{exc}") from exc
    after = after_gpu.get("power_limit_w") if after_gpu else None
    logger.info("power limit gpu=%s before=%s requested=%s after=%s", index, before, watts, after)
    return {
        "index": index,
        "before_watts": before,
        "requested_watts": watts,
        "after_watts": after,
        "min_power_limit_w": min_w,
        "max_power_limit_w": max_w,
    }


def apply_config(path: Path | None = None) -> dict:
    """按 gpu-power.json 批量应用(开机 oneshot 与测试共用)。

    单张 GPU 失败记录该 index 并继续,不阻断其余卡;总结果汇总返回。
    """
    config = load_config(path)
    result: dict = {"enabled": config.enabled, "applied": [], "failed": [], "skipped": []}
    if not config.enabled or (config.default_power_limit is None and not config.per_gpu):
        result["skipped"].append("配置未启用或未配置功耗值")
        return result
    try:
        gpus = nvidia.list_gpus()
    except nvidia.NvidiaError as exc:
        result["failed"].append({"index": None, "error": f"无法读取 GPU 状态:{exc}"})
        return result
    for gpu in gpus:
        index = gpu.get("index")
        target = config.per_gpu.get(str(index), config.default_power_limit)
        if target is None:
            result["skipped"].append({"index": index, "reason": "无配置功耗值"})
            continue
        if gpu.get("power_limit_w") == target:
            result["applied"].append({"index": index, "watts": target, "already": True})
            continue
        try:
            outcome = set_power_limit(index, target)
            result["applied"].append({
                "index": index, "watts": outcome["after_watts"], "already": False,
            })
        except PowerError as exc:
            logger.error("开机应用功耗失败 gpu=%s:%s", index, exc)
            result["failed"].append({"index": index, "error": str(exc)})
    return result
