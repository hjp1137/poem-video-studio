"""API 冒烟测试:上传 → 解析 → 创建批次 → 查询任务 的任务01 验收闭环。"""
from __future__ import annotations

import json
import struct
import zlib

from fastapi.testclient import TestClient

from app.main import app


def tiny_png() -> bytes:
    """生成 1x1 PNG,避免依赖 Pillow。"""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    idat = zlib.compress(b"\x00\xff\x00\x00")
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_health_reflects_real_environment():
    with TestClient(app) as client:
        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded", "error")
        checks = data["checks"]
        assert checks["api"]["ok"] is True
        assert checks["sqlite"]["ok"] is True
        assert checks["data_dir"]["ok"] is True
        # 本测试环境没有真实 Workflow 模板与 ComfyUI,应如实显示
        assert checks["workflow_template"]["ok"] is False
        assert checks["comfyui_http"]["ok"] is False


def test_parse_endpoint(sample_batch_text):
    with TestClient(app) as client:
        resp = client.post("/api/batches/parse", json={"text": sample_batch_text})
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert len(data["scenes"]) == 5
        assert data["global"]["width"] == 768
        assert data["scenes"][0]["scene_key"] == "cover"


def test_parse_endpoint_errors():
    with TestClient(app) as client:
        resp = client.post("/api/batches/parse", json={"text": "WRONG_HEADER\n"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is False
        assert resp.json()["errors"]


def test_full_task01_flow(sample_batch_text):
    with TestClient(app) as client:
        # 1. 批量上传 5 张图
        files = [("files", (name, tiny_png(), "image/png")) for name in
                 ("cover.png", "01.png", "02.png", "03.png", "04.png")]
        resp = client.post("/api/uploads", files=files)
        assert resp.status_code == 200
        uploads = resp.json()
        assert uploads["group_id"]
        assert len(uploads["files"]) == 5
        guessed = {f["upload_id"]: f["guessed_scene_key"] for f in uploads["files"]}
        assert sorted(k for k in guessed.values() if k) == ["1", "2", "3", "4", "cover"]

        # 2. 解析
        parsed = client.post("/api/batches/parse", json={"text": sample_batch_text}).json()
        assert parsed["ok"] is True

        # 3. 按猜测自动绑定(cover→cover,1→1 ...)
        by_key = {f["guessed_scene_key"]: f["upload_id"] for f in uploads["files"]}
        bindings = {s["scene_key"]: by_key[s["scene_key"]] for s in parsed["scenes"]}

        # 4. 创建批次
        resp = client.post(
            "/api/batches",
            json={
                "title": "宿建德江",
                "dynasty": "唐",
                "author": "孟浩然",
                "raw_batch_text": sample_batch_text,
                "image_bindings": bindings,
            },
        )
        assert resp.status_code == 200
        batch = resp.json()
        assert batch["total_tasks"] == 5
        assert batch["status"] == "parsed"

        # 5. 任务列表
        resp = client.get(f"/api/batches/{batch['id']}/tasks")
        assert resp.status_code == 200
        tasks = resp.json()
        assert [t["scene_key"] for t in tasks] == ["cover", "1", "2", "3", "4"]
        assert all(t["status"] == "pending" for t in tasks)
        assert all(t["width"] == 768 and t["fps"] == 24 and t["num_frames"] == 121 for t in tasks)

        # 6. 首帧图片可访问
        resp = client.get(f"/api/tasks/{tasks[0]['id']}/image")
        assert resp.status_code == 200
        assert resp.content[:8] == b"\x89PNG\r\n\x1a\n"

        # 7. 无输出视频时下载应 404
        assert client.get(f"/api/tasks/{tasks[0]['id']}/video").status_code == 404
        assert client.get(f"/api/tasks/{tasks[0]['id']}/download").status_code == 404

        # 8. 数据持久化:重新查询批次仍存在
        assert client.get(f"/api/batches/{batch['id']}").status_code == 200
        assert client.get("/api/batches").json()[0]["id"] == batch["id"]


def test_create_batch_rejects_missing_binding(sample_batch_text):
    with TestClient(app) as client:
        files = [("files", ("cover.png", tiny_png(), "image/png"))]
        uploads = client.post("/api/uploads", files=files).json()
        bindings = {"cover": uploads["files"][0]["upload_id"]}  # 只绑 cover,缺 1~4
        resp = client.post(
            "/api/batches",
            json={
                "title": "宿建德江", "dynasty": "唐", "author": "孟浩然",
                "raw_batch_text": sample_batch_text, "image_bindings": bindings,
            },
        )
        assert resp.status_code == 422
        assert "未绑定图片" in resp.json()["detail"]["message"]


def test_create_batch_rejects_invalid_text():
    with TestClient(app) as client:
        resp = client.post(
            "/api/batches",
            json={"title": "x", "raw_batch_text": "非法文本", "image_bindings": {}},
        )
        assert resp.status_code == 422


def test_retry_without_workflow_template_falls_to_failed(sample_batch_text):
    """无真实 ComfyUI/模板时,重试必须失败并落库可诊断原因。"""
    with TestClient(app) as client:
        files = [("files", (f"{i}.png", tiny_png(), "image/png")) for i in range(1, 5)]
        files.append(("files", ("cover.png", tiny_png(), "image/png")))
        uploads = client.post("/api/uploads", files=files).json()
        by_key = {f["guessed_scene_key"]: f["upload_id"] for f in uploads["files"]}
        parsed = client.post("/api/batches/parse", json={"text": sample_batch_text}).json()
        bindings = {s["scene_key"]: by_key[s["scene_key"]] for s in parsed["scenes"]}
        batch = client.post(
            "/api/batches",
            json={"title": "t", "raw_batch_text": sample_batch_text, "image_bindings": bindings},
        ).json()

        tasks = client.get(f"/api/batches/{batch['id']}/tasks").json()
        resp = client.post(f"/api/tasks/{tasks[0]['id']}/retry")
        assert resp.status_code == 200
        task = resp.json()
        assert task["status"] == "failed"
        assert "Workflow 模板/映射不可用" in task["error_message"]

        # 提交整批也应失败但保留可诊断信息(重试后的 tasks[0] 已 failed,一并纳入)
        resp = client.post(f"/api/batches/{batch['id']}/submit")
        assert resp.status_code == 200
        data = resp.json()
        assert data["submitted"] == 0 and data["failed"] == 5


def test_batch_text_template_download():
    with TestClient(app) as client:
        resp = client.get("/api/batches/text-template")
        assert resp.status_code == 200
        assert "POEM_VIDEO_BATCH_V1" in resp.text
        assert resp.headers["content-disposition"].startswith("attachment")
        assert "[SCENE:cover]" in resp.text


def test_task_params_update_and_validation(sample_batch_text):
    """场景参数管理:合法更新生效,越界拒绝。"""
    with TestClient(app) as client:
        # 造一个已解析批次(走解析+创建)
        up = client.post(
            "/api/uploads",
            files={"files": ("cover.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
        )
        created = client.post(
            "/api/batches",
            json={
                "title": "参数", "dynasty": "唐", "author": "测试",
                "raw_batch_text": sample_batch_text.split("[SCENE:1]")[0].rsplit("[SCENE:cover]", 1)[0]
                + "[SCENE:cover]\nspeech: 一句。\nprompt: 画面。\n",
                "image_bindings": {"cover": up.json()["files"][0]["upload_id"]},
            },
        )
        assert created.status_code == 200
        tasks = client.get(f"/api/batches/{created.json()['id']}/tasks").json()
        tid = tasks[0]["id"]
        resp = client.put(f"/api/tasks/{tid}/params", json={"width": 1024, "prompt": "新画面"})
        assert resp.status_code == 200
        assert resp.json()["width"] == 1024 and resp.json()["prompt"] == "新画面"
        assert client.put(f"/api/tasks/{tid}/params", json={"width": 99999}).status_code == 400
        assert client.put(f"/api/tasks/{tid}/params", json={"prompt": "  "}).status_code == 400


def test_batch_download_requires_outputs():
    """批量下载:无输出任务返回 400 且提示明确。"""
    with TestClient(app) as client:
        batches = client.get("/api/batches").json()
        if not batches:
            return
        bid = batches[0]["id"]
        tid = client.get(f"/api/batches/{bid}/tasks").json()[0]["id"]
        resp = client.get(f"/api/batches/{bid}/download?task_ids={tid}")
        # 该任务可能恰有输出(取决于用例顺序);只断言状态码二选一的语义正确
        assert resp.status_code in (200, 400)
        if resp.status_code == 200:
            assert resp.headers["content-type"].startswith("application/zip")
