"""Agent HTTP API 测试(FastAPI TestClient + monkeypatch,不执行真实主机命令)。"""
from __future__ import annotations

import json
import textwrap

from fastapi.testclient import TestClient

from app.core.config import agent_settings
from app.main import app
from app.services import nvidia, power, registry, systemd

client = TestClient(app)

SERVICES_YAML = """\
    services:
      minimax_h3:
        display_name: MiniMax H3
        manager: systemd
        unit: minimax-h3.service
        health: {type: http, url: "http://127.0.0.1:8001/v1/models", timeout: 3}
      comfyui:
        display_name: ComfyUI
        manager: systemd
        unit: comfyui.service
        health: {type: http, url: "http://127.0.0.1:8188/system_stats", timeout: 3}
    """


def test_gpus_endpoint(monkeypatch):
    monkeypatch.setattr(nvidia, "gpus_with_processes", lambda: [
        {"index": 0, "name": "RTX 4090", "power_limit_w": 280, "processes": []},
    ])
    resp = client.get("/v1/gpus")
    assert resp.status_code == 200
    assert resp.json()["gpus"][0]["power_limit_w"] == 280


def test_gpus_endpoint_nvidia_failure(monkeypatch):
    def boom():
        raise nvidia.NvidiaError("命令失败(超时(15s)):nvidia-smi")

    monkeypatch.setattr(nvidia, "gpus_with_processes", boom)
    resp = client.get("/v1/gpus")
    assert resp.status_code == 502
    assert "nvidia-smi 采集失败" in resp.json()["detail"]


def test_power_limit_endpoint_success(monkeypatch):
    monkeypatch.setattr(power, "set_power_limit", lambda index, watts: {
        "index": index, "before_watts": 300, "requested_watts": watts, "after_watts": watts,
        "min_power_limit_w": 100, "max_power_limit_w": 450,
    })
    resp = client.put("/v1/gpus/0/power-limit", json={"watts": 280})
    assert resp.status_code == 200
    body = resp.json()
    assert (body["before_watts"], body["requested_watts"], body["after_watts"]) == (300, 280, 280)


def test_power_limit_endpoint_range_and_index(monkeypatch):
    def raise_range(index, watts):
        raise power.PowerError(f"GPU {index} 功耗 {watts}W 超出驱动允许区间 [100W, 450W]")

    monkeypatch.setattr(power, "set_power_limit", raise_range)
    assert client.put("/v1/gpus/0/power-limit", json={"watts": 50}).status_code == 400
    assert client.put("/v1/gpus/0/power-limit", json={"watts": -1}).status_code == 422  # pydantic gt=0

    def raise_missing(index, watts):
        raise power.PowerError(f"GPU index {index} 不存在(当前共 4 张卡)")

    monkeypatch.setattr(power, "set_power_limit", raise_missing)
    assert client.put("/v1/gpus/9/power-limit", json={"watts": 280}).status_code == 404


def test_gpu_power_config_roundtrip(config_dir):
    resp = client.put("/v1/gpu-power/config", json={"enabled": True, "default_power_limit": 280, "per_gpu": {}})
    assert resp.status_code == 200
    assert json.loads((config_dir / "gpu-power.json").read_text(encoding="utf-8")) == {
        "enabled": True, "default_power_limit": 280, "per_gpu": {},
    }
    assert client.get("/v1/gpu-power/config").json()["default_power_limit"] == 280


def test_services_endpoints(monkeypatch, config_dir):
    (config_dir / "services.yaml").write_text(textwrap.dedent(SERVICES_YAML), encoding="utf-8")

    def fake_status(service):
        return {
            "name": service.name, "display_name": service.display_name, "unit": service.unit,
            "gpu_profile": service.gpu_profile, "description": service.description,
            "process_state": "running", "health_state": "healthy",
            "health_url": service.health.url, "pid": 12345, "started_at": 1700000000,
            "uptime_seconds": 60,
        }

    monkeypatch.setattr(systemd, "service_status", fake_status)
    actions = []
    monkeypatch.setattr(systemd, "service_action", lambda unit, verb: actions.append((unit, verb)))

    body = client.get("/v1/services").json()
    assert {s["name"] for s in body["services"]} == {"minimax_h3", "comfyui"}

    resp = client.post("/v1/services/comfyui/restart")
    assert resp.status_code == 200
    assert actions == [("comfyui.service", "restart")]

    # 未登记服务一律 404,不接受任意 unit 字符串
    assert client.post("/v1/services/nginx/stop").status_code == 404
    assert client.get("/v1/services/..%2F..%2Fetc/logs").status_code == 404


def test_service_logs_endpoint(monkeypatch, config_dir):
    (config_dir / "services.yaml").write_text(textwrap.dedent(SERVICES_YAML), encoding="utf-8")
    monkeypatch.setattr(systemd, "service_logs", lambda unit, lines: [f"log-{i}" for i in range(lines)])
    body = client.get("/v1/services/comfyui/logs?lines=5").json()
    assert body["lines"] == 5 and body["logs"][0] == "log-0"
    # 超过上限被拒绝(查询参数 le=1000)
    assert client.get("/v1/services/comfyui/logs?lines=5000").status_code == 422


def test_health_reports_corrupt_config(config_dir):
    (config_dir / "gpu-power.json").write_text("{ broken", encoding="utf-8")
    (config_dir / "services.yaml").write_text("services: [", encoding="utf-8")
    body = client.get("/v1/health").json()
    assert body["status"] == "degraded"
    assert len(body["problems"]) == 2


def test_token_protection(monkeypatch):
    monkeypatch.setattr(agent_settings, "token", "s3cret")
    monkeypatch.setattr(nvidia, "gpus_with_processes", lambda: [])
    assert client.get("/v1/gpus").status_code == 401
    assert client.get("/v1/gpus", headers={"authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/v1/gpus", headers={"authorization": "Bearer s3cret"}).status_code == 200
    # 健康检查不要求 Token(仅绑定 localhost)
    assert client.get("/v1/health").status_code == 200
