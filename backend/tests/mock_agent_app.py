"""E2E 用 Mock Agent:模拟 4×RTX 4090 + 服务状态机 + ComfyUI 队列端点。

仅供本地 Playwright E2E 使用(端口 8310),不是真实宿主机 Agent。
通过 /_e2e/control 端点在用例中切换状态(离线、队列繁忙等)。
运行:python tests/mock_agent_app.py [port]
"""
from __future__ import annotations

import sys
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="mock poem-video-agent (e2e)")

STATE = {
    "offline": False,
    "services": {
        "minimax_h3": {"process_state": "stopped", "health_state": "unknown", "ready_at": 0},
        "comfyui": {"process_state": "stopped", "health_state": "unknown", "ready_at": 0},
        "ollama": {"process_state": "running", "health_state": "healthy", "ready_at": 0},
    },
    "queue_busy": False,
    # E2E 可注入的 ComfyUI 完成记录:{prompt_id: {"status":..., "outputs":...}}
    "histories": {},
    "power_config": {"enabled": False, "default_power_limit": None, "per_gpu": {}},
    "gpu_fail_index": None,
    "workloads": [
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
    ],
}

DISPLAY = {
    "minimax_h3": ("MiniMax H3", "minimax-h3.service", "h3"),
    "comfyui": ("ComfyUI", "comfyui.service", "comfyui"),
    "ollama": ("Ollama", "ollama.service", ""),
}

READY_DELAY_SECONDS = 1.5  # start 后经过该时长 health 变 healthy


def _make_gpus() -> list[dict]:
    gpus = []
    for i in range(4):
        gpus.append({
            "index": i, "uuid": f"GPU-e2e-{i:04d}", "name": "NVIDIA GeForce RTX 4090",
            "temperature_c": 58 + i, "utilization_gpu_percent": 8 * i,
            "memory_used_mib": 1500 + 137 * i, "memory_total_mib": 24564,
            "power_draw_w": 95 + 7 * i, "power_limit_w": 300,
            "min_power_limit_w": 100, "max_power_limit_w": 450,
            "pstate": "P8" if i else "P2", "fan_speed_percent": 35,
            "processes": [] if i else [{
                "gpu_uuid": "GPU-e2e-0000", "pid": 12345 + i,
                "process_name": "python", "used_gpu_memory_mib": 20134,
            }],
        })
    return gpus


GPUS = _make_gpus()


@app.get("/v1/health")
def health():
    if STATE["offline"]:
        return JSONResponse(status_code=503, content={"detail": "mock agent offline"})
    return {"status": "ok", "problems": []}


@app.get("/v1/gpus")
def get_gpus():
    if STATE["offline"]:
        return JSONResponse(status_code=503, content={"detail": "mock agent offline"})
    return {"gpus": GPUS}


@app.put("/v1/gpus/{index}/power-limit")
async def set_power(index: int, request: Request):
    body = await yield_body(request)
    watts = body.get("watts")
    gpu = next((g for g in GPUS if g["index"] == index), None)
    if gpu is None:
        return JSONResponse(status_code=404, content={"detail": f"GPU index {index} 不存在(当前共 4 张卡)"})
    if not isinstance(watts, int) or watts <= 0:
        return JSONResponse(status_code=400, content={"detail": "watts 必须是正整数"})
    if watts < gpu["min_power_limit_w"] or watts > gpu["max_power_limit_w"]:
        return JSONResponse(
            status_code=400,
            content={"detail": f"GPU {index} 功耗 {watts}W 超出驱动允许区间 [100W, 450W]"},
        )
    if STATE["gpu_fail_index"] == index:
        return JSONResponse(status_code=502, content={"detail": f"GPU {index} nvidia-smi 执行失败(模拟)"})
    before = gpu["power_limit_w"]
    gpu["power_limit_w"] = watts
    return {"index": index, "before_watts": before, "requested_watts": watts, "after_watts": watts}


async def yield_body(request: Request) -> dict:
    import json as _json

    try:
        return _json.loads(await request.body() or b"{}")
    except ValueError:
        return {}


@app.get("/v1/gpu-power/config")
def get_power_config():
    return STATE["power_config"]


@app.put("/v1/gpu-power/config")
async def put_power_config(request: Request):
    STATE["power_config"] = await yield_body(request)
    return STATE["power_config"]


def _svc_status(name: str) -> dict:
    display, unit, profile = DISPLAY[name]
    info = STATE["services"][name]
    process = info["process_state"]
    if process == "running" and info["ready_at"] and time.time() >= info["ready_at"]:
        info["health_state"] = "healthy"
    elif process == "running":
        info["health_state"] = "unhealthy"  # 启动初期,模拟模型加载中
    return {
        "name": name, "display_name": display, "unit": unit, "gpu_profile": profile,
        "description": f"{display}(E2E 模拟)", "process_state": process,
        "health_state": info["health_state"], "health_url": "",
        "pid": 4242 if process == "running" else None,
        "started_at": 1700000000 if process == "running" else None,
        "uptime_seconds": 222 if process == "running" else None,
    }


@app.get("/v1/services")
def list_services():
    return {"services": [_svc_status(n) for n in STATE["services"]]}


@app.get("/v1/services/{name}")
def get_service(name: str):
    if name not in STATE["services"]:
        return JSONResponse(status_code=404, content={"detail": f"服务 {name} 未在注册表登记,拒绝操作"})
    return _svc_status(name)


@app.post("/v1/services/{name}/{verb}")
def service_action(name: str, verb: str):
    if name not in STATE["services"]:
        return JSONResponse(status_code=404, content={"detail": f"服务 {name} 未在注册表登记,拒绝操作"})
    if verb not in ("start", "stop", "restart"):
        return JSONResponse(status_code=404, content={"detail": "未知动作"})
    info = STATE["services"][name]
    if verb == "stop":
        info.update(process_state="stopped", health_state="unknown", ready_at=0)
    else:
        info.update(process_state="running", health_state="unhealthy", ready_at=time.time() + READY_DELAY_SECONDS)
    return _svc_status(name)


@app.get("/v1/services/{name}/logs")
def service_logs(name: str, lines: int = 100):
    if name not in STATE["services"]:
        return JSONResponse(status_code=404, content={"detail": f"服务 {name} 未在注册表登记,拒绝操作"})
    lines = max(1, min(lines, 1000))
    return {
        "name": name, "unit": DISPLAY[name][1], "lines": lines,
        "logs": [f"2026-09-22T10:00:{i % 60:02d}+08:00 host {DISPLAY[name][1]}[999]: 模拟日志第 {i} 行" for i in range(lines)],
    }


# ---- 假 ComfyUI 端点(同端口,E2E 后端 COMFYUI_BASE_URL 指到这里) ----

def _comfyui_down():
    return STATE["services"]["comfyui"]["process_state"] != "running"


@app.get("/system_stats")
def comfy_stats():
    if _comfyui_down():
        return JSONResponse(status_code=503, content={"detail": "comfyui service not running"})
    return {"system": {"os": "mock"}, "devices": []}


@app.get("/queue")
def comfy_queue():
    if _comfyui_down():
        return JSONResponse(status_code=503, content={"detail": "comfyui service not running"})
    if STATE["queue_busy"]:
        return {"queue_running": [{"prompt_id": "fake-running", "number": 1}], "queue_pending": [{"prompt_id": "fake-pending", "number": 2}]}
    # 与 POST /prompt 联动:提交的 prompt 停留在 pending,供对账与「移除队列」闭环
    pending = [{"prompt_id": p, "number": i + 1} for i, p in enumerate(STATE["prompt_queue"])]
    return {"queue_running": [], "queue_pending": pending}


@app.get("/history/{prompt_id}")
def comfy_history(prompt_id: str):
    if prompt_id in STATE["histories"]:
        return {prompt_id: STATE["histories"][prompt_id]}
    return {}


# 模拟 ComfyUI 队列:记录提交的 prompt_id,供「移除队列」端点删除
STATE["prompt_queue"] = []
_PROMPT_SEQ = {"n": 0}


@app.post("/upload/image")
async def comfy_upload_image(request: Request):
    if _comfyui_down():
        return JSONResponse(status_code=503, content={"detail": "comfyui service not running"})
    body = await request.body()
    name = request.query_params.get("name") or "e2e_upload.png"
    return {"name": name, "subfolder": "", "type": "input"}


@app.post("/prompt")
async def comfy_prompt(request: Request):
    if _comfyui_down():
        return JSONResponse(status_code=503, content={"detail": "comfyui service not running"})
    _PROMPT_SEQ["n"] += 1
    prompt_id = f"mock-prompt-{_PROMPT_SEQ['n']}"
    STATE["prompt_queue"].append(prompt_id)
    return {"prompt_id": prompt_id, "number": _PROMPT_SEQ["n"], "node_errors": []}


@app.delete("/queue")
async def comfy_delete_queue(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    deleted = body.get("delete") or []
    STATE["prompt_queue"] = [p for p in STATE["prompt_queue"] if p not in deleted]
    return {"event": "delete", "data": deleted}


@app.get("/view")
def comfy_view(filename: str, subfolder: str = "", type: str = "output"):
    if _comfyui_down():
        return JSONResponse(status_code=503, content={"detail": "comfyui service not running"})
    # 最小合法 MP4 头(ftyp isom)+填充
    payload = bytes([0, 0, 0, 0x18]) + b"ftypisom" + b"e2e-fake-video" * 64

@app.get("/object_info")
def comfy_object_info():
    """真实节点定义 fixture(199 服务器导出),供模板转换测试使用。"""
    if _comfyui_down():
        return JSONResponse(status_code=503, content={"detail": "comfyui service not running"})
    import json
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "object_info_h3.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


# ---- GPU 工作负载(自动检测模拟:占用 GPU 的容器/进程清单) ----

@app.get("/v1/gpu-workloads")
def gpu_workloads():
    if STATE["offline"]:
        return JSONResponse(status_code=503, content={"detail": "mock agent offline"})
    return {"workloads": STATE["workloads"]}


@app.post("/v1/gpu-workloads/{container}/stop")
def stop_gpu_workload(container: str):
    if STATE["offline"]:
        return JSONResponse(status_code=503, content={"detail": "mock agent offline"})
    target = next((w for w in STATE["workloads"] if w["kind"] == "docker" and w["name"] == container), None)
    if target is None:
        gpu_names = [w["name"] for w in STATE["workloads"] if w["kind"] == "docker"]
        return JSONResponse(
            status_code=404,
            content={"detail": f"容器 {container} 当前未占用 GPU,拒绝停止(当前占用 GPU 的容器:{gpu_names or '无'})"},
        )
    STATE["workloads"].remove(target)
    return {"stopped": container, "freed_memory_mib": target["used_memory_mib"]}


# ---- E2E 控制端点 ----

@app.post("/_e2e/control")
async def e2e_control(request: Request):
    body = await yield_body(request)
    action = body.get("action")
    if action == "offline":
        STATE["offline"] = bool(body.get("value", True))
    elif action == "reset":
        STATE["offline"] = False
        STATE["queue_busy"] = False
        STATE["histories"] = {}
        STATE["prompt_queue"] = []
        STATE["gpu_fail_index"] = None
        STATE["power_config"] = {"enabled": False, "default_power_limit": None, "per_gpu": {}}
        for g in GPUS:
            g["power_limit_w"] = 300
        STATE["workloads"] = [
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
        STATE["services"] = {
            "minimax_h3": {"process_state": "stopped", "health_state": "unknown", "ready_at": 0},
            "comfyui": {"process_state": "stopped", "health_state": "unknown", "ready_at": 0},
            "ollama": {"process_state": "running", "health_state": "healthy", "ready_at": 0},
        }
    elif action == "queue_busy":
        STATE["queue_busy"] = bool(body.get("value", True))
    elif action == "set_history":
        prompt_id = body.get("prompt_id") or ""
        sub = body.get("subfolder") or f"hist/{prompt_id[:8]}"
        STATE["histories"][prompt_id] = {
            "status": {"status_str": "completed", "completed": True, "messages": []},
            "outputs": {
                "13": {
                    "images": [{
                        "filename": f"{prompt_id[:12]}_00001_.mp4",
                        "subfolder": sub,
                        "type": "output",
                    }],
                }
            },
        }
        STATE["prompt_queue"] = [p for p in STATE["prompt_queue"] if p != prompt_id]
        return {"ok": True, "prompt_id": prompt_id}
    elif action == "set_service":
        name = body.get("name")
        if name in STATE["services"]:
            health = body.get("health_state", "unknown")
            # 运行中服务的健康由 ready_at 推导;显式置 healthy 时把 ready_at 设为过去
            ready_at = time.time() - 1 if health == "healthy" else 0
            STATE["services"][name].update(
                process_state=body.get("process_state", "stopped"),
                health_state=health,
                ready_at=ready_at,
            )
    return STATE


def main() -> None:
    import uvicorn

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8310
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
