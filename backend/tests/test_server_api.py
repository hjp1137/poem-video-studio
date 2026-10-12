"""服务器控制中心 API 测试:httpx.MockTransport 模拟 Agent,覆盖审计与停止保护。"""
from __future__ import annotations

import asyncio
import textwrap

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal, init_db
from app.main import app
from app.services import env_prepare

from app.api import server as server_api


FAKE_GPUS = [
    {
        "index": i, "uuid": f"GPU-fake-{i}", "name": "NVIDIA GeForce RTX 4090",
        "temperature_c": 60 + i, "utilization_gpu_percent": 5 * i,
        "memory_used_mib": 1000 + i, "memory_total_mib": 24564,
        "power_draw_w": 90 + i, "power_limit_w": 300, "min_power_limit_w": 100,
        "max_power_limit_w": 450, "pstate": "P8", "fan_speed_percent": 35, "processes": [],
    }
    for i in range(4)
]

SERVICES_STATE: dict[str, dict] = {}


def _service_status(name: str, process="stopped", health="unknown") -> dict:
    return {
        "name": name, "display_name": name, "unit": f"{name.replace('_', '-')}.service",
        "gpu_profile": "", "description": "", "process_state": process, "health_state": health,
        "health_url": "", "pid": 123 if process == "running" else None,
        "started_at": 1700000000 if process == "running" else None,
        "uptime_seconds": 60 if process == "running" else None,
    }


class FakeAgent:
    """内存态假 Agent:GPU 功耗可改、服务状态机可切换,供 MockTransport 路由。"""

    def __init__(self):
        self.gpus = [dict(g) for g in FAKE_GPUS]
        self.workloads = [
            {
                "kind": "docker", "name": "magic-pdf-server", "display_name": "magic-pdf-server",
                "pids": [100], "gpu_indices": [0], "used_memory_mib": 11190,
                "command": "mineru-api", "stoppable": True,
            },
            {
                "kind": "docker", "name": "bge-m3-server", "display_name": "bge-m3-server",
                "pids": [200], "gpu_indices": [1], "used_memory_mib": 3724,
                "command": "python -m infinity", "stoppable": True,
            },
        ]
        SERVICES_STATE.clear()
        SERVICES_STATE.update({
            "minimax_h3": _service_status("minimax_h3", "stopped"),
            "comfyui": _service_status("comfyui", "stopped"),
            "ollama": _service_status("ollama", "running", "healthy"),
        })
        self.power_calls: list[tuple[int, int]] = []
        self.fail_gpu: int | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        method = request.method
        if path == "/v1/health":
            return httpx.Response(200, json={"status": "ok", "problems": []})
        if path == "/v1/gpus" and method == "GET":
            return httpx.Response(200, json={"gpus": self.gpus})
        if method == "PUT" and path.startswith("/v1/gpus/") and path.endswith("/power-limit"):
            index = int(path.split("/")[3])
            watts = __import__("json").loads(request.content)["watts"]
            gpu = next((g for g in self.gpus if g["index"] == index), None)
            if gpu is None:
                return httpx.Response(404, json={"detail": f"GPU index {index} 不存在"})
            if watts < gpu["min_power_limit_w"] or watts > gpu["max_power_limit_w"]:
                return httpx.Response(400, json={"detail": f"GPU {index} 功耗超出区间"})
            if index == self.fail_gpu:
                return httpx.Response(502, json={"detail": f"GPU {index} nvidia-smi 执行失败"})
            before = gpu["power_limit_w"]
            gpu["power_limit_w"] = watts
            self.power_calls.append((index, watts))
            return httpx.Response(200, json={
                "index": index, "before_watts": before, "requested_watts": watts, "after_watts": watts,
            })
        if path == "/v1/gpu-power/config" and method == "GET":
            return httpx.Response(200, json={"enabled": False, "default_power_limit": None, "per_gpu": {}})
        if path == "/v1/gpu-power/config" and method == "PUT":
            return httpx.Response(200, json=__import__("json").loads(request.content))
        if path == "/v1/gpu-workloads" and method == "GET":
            return httpx.Response(200, json={"workloads": self.workloads})
        if path.startswith("/v1/gpu-workloads/") and method == "POST" and path.endswith("/stop"):
            container = path.strip("/").split("/")[2]
            target = next((w for w in self.workloads if w["name"] == container), None)
            if target is None:
                return httpx.Response(404, json={"detail": f"容器 {container} 当前未占用 GPU,拒绝停止"})
            self.workloads.remove(target)
            return httpx.Response(200, json={"stopped": container, "freed_memory_mib": target["used_memory_mib"]})
        if path == "/v1/services" and method == "GET":
            return httpx.Response(200, json={"services": list(SERVICES_STATE.values())})
        if path.startswith("/v1/services/"):
            parts = path.strip("/").split("/")
            name = parts[2]
            if name not in SERVICES_STATE:
                return httpx.Response(404, json={"detail": f"服务 {name} 未在注册表登记,拒绝操作"})
            if len(parts) == 3 and method == "GET":
                return httpx.Response(200, json=SERVICES_STATE[name])
            if len(parts) == 4 and method == "POST" and parts[3] in ("start", "stop", "restart"):
                verb = parts[3]
                if verb in ("start", "restart"):
                    SERVICES_STATE[name] = _service_status(name, "running", "healthy")
                else:
                    SERVICES_STATE[name] = _service_status(name, "stopped")
                return httpx.Response(200, json=SERVICES_STATE[name])
            if len(parts) == 4 and parts[3] == "logs" and method == "GET":
                lines = int(request.url.params.get("lines", 100))
                return httpx.Response(200, json={"name": name, "lines": lines, "logs": [f"[{name}] line {i}" for i in range(lines)]})
        return httpx.Response(404, json={"detail": f"mock 未实现 {method} {path}"})


from app.services.agent_client import AgentClient


@pytest.fixture()
def fake_agent(monkeypatch):
    agent = FakeAgent()

    def make_client():
        return AgentClient(base_url="http://fake-agent", transport=httpx.MockTransport(agent.handler))

    monkeypatch.setattr(server_api, "agent_client", make_client)
    monkeypatch.setattr(env_prepare, "agent_client", make_client)
    return agent


class _FakeComfyQueue:
    """env_prepare STEP10 用的假 ComfyUI 客户端:队列恒为空。"""

    def __init__(self, *args, **kwargs):
        pass

    async def get_queue(self):
        return {"queue_running": [], "queue_pending": []}

    async def aclose(self):
        pass


@pytest.fixture()
def client(fake_agent, tmp_path, monkeypatch):
    monkeypatch.setattr(env_prepare, "ComfyUIClient", _FakeComfyQueue)
    monkeypatch.setattr(server_api, "ComfyUIClient", _FakeComfyQueue)
    # Prepare 用小超时 profile,避免测试长时间轮询
    profile_file = tmp_path / "profiles.yaml"
    profile_file.write_text(textwrap.dedent("""\
        profiles:
          h3_video:
            display_name: 测试环境
            gpu_power: {enabled: true, watts: 280}
            stop_services: [ollama]
            start_services: [minimax_h3, comfyui]
            readiness: {minimax_h3_timeout_seconds: 2, comfyui_timeout_seconds: 2}
        """), encoding="utf-8")
    from app.core.config import settings as app_settings

    monkeypatch_holder = pytest.MonkeyPatch()
    monkeypatch_holder.setattr(app_settings, "server_profiles_file", profile_file)
    monkeypatch_holder.setattr(app_settings, "prepare_poll_interval", 0.05)
    app_settings.ensure_dirs()
    init_db()
    with TestClient(app) as c:
        yield c
    monkeypatch_holder.undo()


def _db():
    return SessionLocal()


def test_gpus_proxy_and_audit(fake_agent, client):
    resp = client.get("/api/server/gpus")
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_online"] is True and len(body["gpus"]) == 4

    # 单卡设置成功:返回 before/requested/after,审计落库
    resp = client.put("/api/server/gpus/2/power-limit", json={"watts": 280})
    assert resp.status_code == 200
    assert resp.json()["after_watts"] == 280
    db = _db()
    from app.models.server import ServerOperation

    ops = db.query(ServerOperation).filter_by(action="gpu.power_limit").all()
    assert len(ops) == 1 and ops[0].result == "success"
    assert ops[0].source_ip  # 来源 IP 必须记录
    db.close()


def test_single_gpu_invalid(fake_agent, client):
    assert client.put("/api/server/gpus/2/power-limit", json={"watts": 50}).status_code == 400  # 低于 min
    assert client.put("/api/server/gpus/9/power-limit", json={"watts": 280}).status_code == 404


def test_bulk_power_limit_partial_failure_not_fake_success(fake_agent, client):
    fake_agent.fail_gpu = 3  # 第 4 张卡失败
    resp = client.put("/api/server/gpus/power-limit", json={"watts": 280})
    assert resp.status_code == 200
    body = resp.json()
    assert body["all_ok"] is False
    ok_indices = {r["index"] for r in body["results"] if r["ok"]}
    failed = {r["index"] for r in body["results"] if not r["ok"]}
    assert ok_indices == {0, 1, 2} and failed == {3}
    db = _db()
    from app.models.server import ServerOperation

    op = db.query(ServerOperation).filter_by(action="gpu.power_limit_bulk").one()
    assert op.result == "failed" and "gpu3" in op.error_message
    db.close()


def test_settings_gpu_power_sync_and_apply(fake_agent, client):
    resp = client.put(
        "/api/server/settings/gpu-power",
        json={"enabled": True, "default_power_limit": 280, "apply_now": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agent_synced"] is True
    assert all(r["ok"] for r in body["apply_results"]) and len(body["apply_results"]) == 4
    # 本地 ServerSetting 落库
    db = _db()
    from app.models.server import ServerSetting

    row = db.get(ServerSetting, "gpu_power")
    assert row is not None and "280" in row.value_json
    db.close()


def test_services_proxy_and_unknown_rejected(fake_agent, client):
    body = client.get("/api/server/services").json()
    assert {s["name"] for s in body["services"]} == {"minimax_h3", "comfyui", "ollama"}
    assert client.post("/api/server/services/nginx/stop").status_code == 404  # 未登记拒绝
    logs = client.get("/api/server/services/comfyui/logs?lines=5").json()
    assert logs["lines"] == 5


def test_stop_protection_and_force(fake_agent, client):
    # 造一个排队中的 VideoTask 触发停止保护
    db = _db()
    from app.models.batch import Batch
    from app.models.task import VideoTask

    batch = Batch(id="bkg1", title="t", status="queued")
    db.add(batch)
    db.add(VideoTask(id="vt1", batch_id="bkg1", scene_key="1", scene_order=1, status="queued"))
    db.commit()
    db.close()

    resp = client.post("/api/server/services/comfyui/stop")
    assert resp.status_code == 409
    assert "生成任务" in resp.json()["detail"]["message"]
    assert resp.json()["detail"]["force_required"] is True

    # force=true 二次确认后放行,审计记录 force
    resp = client.post("/api/server/services/comfyui/stop", json={"force": True})
    assert resp.status_code == 200
    db = _db()
    from app.models.server import ServerOperation

    ops = db.query(ServerOperation).filter_by(action="service.stop", target_name="comfyui").all()
    assert {o.result for o in ops} == {"blocked", "success"}
    db.close()


def test_prepare_full_success_and_idempotent_reflag(fake_agent, client):
    resp = client.post("/api/server/environment/h3/prepare")
    assert resp.status_code == 200 and resp.json()["started"] is True

    for _ in range(200):  # 等待后台任务完成(readiness 2s 超时,轮询 0.05s)
        status = client.get("/api/server/environment/h3/status").json()
        if status["state"] in ("success", "failed"):
            break
        asyncio.run(asyncio.sleep(0.05))
    steps = {s["key"]: s for s in status["steps"]}
    assert status["state"] == "success", status["error_message"]
    assert steps["agent_health"]["state"] == "success"
    assert steps["apply_power"]["state"] == "success"
    assert steps["stop_conflicts"]["state"] == "success"  # ollama 由 running → stop
    assert steps["start_h3"]["state"] == "success"
    assert steps["ready"]["state"] == "success"
    assert status["total_seconds"] is not None

    # 环境就绪后 summary 返回 ready
    summary = client.get("/api/server/summary").json()
    assert summary["environment"]["ready"] is True

    # 审计记录 environment.prepare 成功
    db = _db()
    from app.models.server import ServerOperation

    op = db.query(ServerOperation).filter_by(action="environment.prepare").one()
    assert op.result == "success"
    db.close()


def test_prepare_h3_timeout_reports_failure_step(fake_agent, client, monkeypatch):
    # H3 start 后保持 unhealthy:mock 的 start 会置 healthy,这里改回 unhealthy 模拟不 Ready
    original_handler = fake_agent.handler

    def sick_handler(request: httpx.Request) -> httpx.Response:
        resp = original_handler(request)
        if request.url.path.startswith("/v1/services/minimax_h3") and resp.status_code == 200:
            import json as _json

            try:
                data = resp.json()
            except ValueError:
                return resp
            if isinstance(data, dict) and data.get("name") == "minimax_h3":
                data["health_state"] = "unhealthy"
                return httpx.Response(200, json=data)
        return resp

    # 替换 handler 引用:MockTransport 持有的是 bound method,直接改 fake_agent.handler 无法生效,
    # 因此重新 patch client 工厂
    def make_client():
        return AgentClient(base_url="http://fake-agent", transport=httpx.MockTransport(sick_handler))

    monkeypatch.setattr(server_api, "agent_client", make_client)
    monkeypatch.setattr(env_prepare, "agent_client", make_client)

    assert client.post("/api/server/environment/h3/prepare").status_code == 200
    for _ in range(300):
        status = client.get("/api/server/environment/h3/status").json()
        if status["state"] in ("success", "failed"):
            break
        asyncio.run(asyncio.sleep(0.05))
    assert status["state"] == "failed"
    assert status["failure_step"] == "wait_h3"
    assert "超时" in status["error_message"]
    # 失败后保留已完成步骤状态
    steps = {s["key"]: s for s in status["steps"]}
    assert steps["start_h3"]["state"] == "success"
    assert steps["wait_comfyui"]["state"] == "pending"


def test_environment_profile_readonly(client):
    body = client.get("/api/server/environment/h3/profile").json()
    assert body["name"] == "h3_video"
    assert body["gpu_power"] == {"enabled": True, "watts": 280}
    assert body["stop_services"] == ["ollama"]
    assert body["start_services"] == ["minimax_h3", "comfyui"]


def test_gpu_workloads_detect_and_stop(fake_agent, client):
    # 自动检测清单代理
    body = client.get("/api/server/gpu-workloads").json()
    names = [w["name"] for w in body["workloads"]]
    assert names == ["magic-pdf-server", "bge-m3-server"]

    # 停止占用 GPU 的容器:成功 + 审计;停止后清单移除
    resp = client.post("/api/server/gpu-workloads/magic-pdf-server/stop")
    assert resp.status_code == 200
    assert resp.json() == {"stopped": "magic-pdf-server", "freed_memory_mib": 11190}
    body = client.get("/api/server/gpu-workloads").json()
    assert [w["name"] for w in body["workloads"]] == ["bge-m3-server"]

    # 未占用 GPU 的容器被 Agent 拒绝 → 404 透传 + failed 审计
    assert client.post("/api/server/gpu-workloads/redis-server/stop").status_code == 404
    assert client.post("/api/server/gpu-workloads/x;rm/stop").status_code == 400

    db = _db()
    from app.models.server import ServerOperation

    ops = db.query(ServerOperation).filter_by(action="workload.docker_stop").all()
    assert {o.result for o in ops} == {"success", "failed"}
    db.close()


def test_prepare_busy_guard():
    """已有 prepare 任务运行中时,再次启动必须被拒绝(HTTP 层映射 409)。"""
    from app.services import env_prepare as ep

    async def scenario():
        async def sleeper():
            await asyncio.sleep(30)

        ep._task = asyncio.ensure_future(sleeper())
        try:
            ep.start_prepare()
            raise AssertionError("应当抛出运行中异常")
        except RuntimeError as exc:
            assert "正在运行" in str(exc)
        finally:
            ep._task.cancel()
            try:
                await ep._task
            except asyncio.CancelledError:
                pass
            ep._task = None

    asyncio.run(scenario())
