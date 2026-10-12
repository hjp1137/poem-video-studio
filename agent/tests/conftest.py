"""Agent 测试夹具:临时配置目录 + 关闭 sudo,隔离宿主机状态。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AGENT_DIR))

import os

_TMP_CONFIG = tempfile.mkdtemp(prefix="poem_agent_test_")
os.environ["AGENT_CONFIG_DIR"] = _TMP_CONFIG
os.environ["AGENT_USE_SUDO"] = "0"

import pytest  # noqa: E402


@pytest.fixture()
def config_dir(tmp_path, monkeypatch):
    """每个用例独立配置目录:AgentSettings.config_dir 指向临时目录,用后还原。"""
    original = agent_settings_module().config_dir
    monkeypatch.setattr(agent_settings_module(), "config_dir", tmp_path)
    yield tmp_path
    assert agent_settings_module().config_dir == tmp_path


def agent_settings_module():
    from app.core.config import agent_settings

    return agent_settings


@pytest.fixture()
def fake_gpus():
    """4×RTX 4090 标准状态(功耗区间 100~450W,当前 300W)。"""
    def make(power_limit=300):
        return [
            {
                "index": i, "uuid": f"GPU-aaaa-bbbb-{i:04d}", "name": "NVIDIA GeForce RTX 4090",
                "temperature_c": 60 + i, "utilization_gpu_percent": 10 * i,
                "memory_used_mib": 2000 + i, "memory_total_mib": 24564,
                "power_draw_w": 100 + 10 * i, "power_limit_w": power_limit,
                "min_power_limit_w": 100, "max_power_limit_w": 450,
                "pstate": "P2", "fan_speed_percent": 40, "processes": [],
            }
            for i in range(4)
        ]
    return make
