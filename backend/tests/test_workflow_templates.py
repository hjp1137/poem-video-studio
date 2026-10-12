"""workflow 模板管理测试:转换器、存储服务、API 全链路。

fixture 来源:199 服务器真实资产(用户 ComfyUI 工作流 + object_info 节点定义)。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"


def _load_ui():
    return json.loads((FIXTURES / "ui_workflow_h3.json").read_text(encoding="utf-8"))


def _load_object_info():
    return json.loads((FIXTURES / "object_info_h3.json").read_text(encoding="utf-8"))


# ---- 转换器 ----


def test_convert_real_user_workflow():
    from app.services.workflow_converter import convert_ui_to_api, draft_map

    api, warnings = convert_ui_to_api(_load_ui(), _load_object_info())
    assert set(api.keys()) == {"18", "8", "13", "27", "28", "16"}
    # LoadImage:消费文件名,upload 占位不消费
    assert api["28"]["class_type"] == "LoadImage"
    assert api["28"]["inputs"]["image"] == "王维《山居秋暝》7.png"
    assert "upload" not in api["28"]["inputs"]
    # 生成节点:widget 注入 + 连接引用
    gen = api["16"]["inputs"]
    assert gen["url"] == "http://127.0.0.1:8011/v1"
    assert gen["model"] == "/data/AI_Models/MiniMax-H3/FL2VA"
    assert gen["frame"] == ["28", 0]
    assert gen["sampling_params"] == ["8", 0]
    assert gen["lora"] == ["27", 0]
    assert gen["model_params"] == ["18", 0]
    assert "prompt" in gen and "negative_prompt" in gen and "num_frames" in gen
    # seed 控制尾巴:值被消费,randomize 文本被丢弃并警告
    assert api["8"]["inputs"]["seed"] == 4
    assert any("控制项" in w for w in warnings)
    # 映射草稿:必需字段齐,无 speech(该工作流无语音节点)
    draft = draft_map(api)
    nodes = draft["nodes"]
    for field in ("image", "prompt", "negative_prompt", "width", "height", "fps", "num_frames", "seed", "save"):
        assert field in nodes, field
    assert "speech" not in nodes
    assert nodes["image"] == {"id": "28", "input": "image"}
    assert nodes["save"] == {"id": "13", "input": "filename_prefix"}


def test_convert_skips_note_and_unknown():
    from app.services.workflow_converter import convert_ui_to_api

    ui = {
        "nodes": [
            {"id": 1, "type": "MarkdownNote", "widgets_values": ["说明"], "inputs": []},
            {"id": 2, "type": "NotExistNode", "widgets_values": [], "inputs": []},
        ],
        "links": [],
    }
    api, warnings = convert_ui_to_api(ui, {})
    assert api == {}
    assert any("NotExistNode" in w for w in warnings)


# ---- 存储服务 + API ----

MAP_YAML = """name: 测试模板
nodes:
  image:
    id: "28"
    input: image
  prompt:
    id: "16"
    input: prompt
  save:
    id: "13"
    input: filename_prefix
"""


@pytest.fixture()
def converted():
    from app.services.workflow_converter import convert_ui_to_api, draft_map
    import yaml

    api, _ = convert_ui_to_api(_load_ui(), _load_object_info())
    draft = draft_map(api)
    draft["name"] = "首帧图生视频"
    return api, yaml.safe_dump(draft, allow_unicode=True, sort_keys=False)


def _client_with_object_info(monkeypatch):
    from app.services import workflow_template_service as wts

    object_info = _load_object_info()

    class _FakeClient:
        async def get_object_info(self):
            return object_info

        async def aclose(self):
            pass

    # service 模块内直接导入了 ComfyUIClient,须替换该命名空间的名字
    monkeypatch.setattr(wts, "ComfyUIClient", lambda **kw: _FakeClient())


def test_template_service_crud_and_default(converted):
    from app.services import workflow_template_service as svc

    api, map_yaml = converted
    result = svc.save_template("首帧图生视频", api, map_yaml)
    assert result["problems"] == []

    templates = svc.list_templates()
    assert [t["name"] for t in templates] == ["首帧图生视频"]
    assert templates[0]["is_default"] is False

    svc.set_default("首帧图生视频")
    assert svc.get_default() == "首帧图生视频"
    assert svc.list_templates()[0]["is_default"] is True

    adapter = svc.get_default_adapter()
    workflow = adapter.build(
        image_name="cover.png",
        prompt="画面",
        negative_prompt="负面",
        speech="语音文本",
        width=768,
        height=1024,
        fps=24,
        num_frames=121,
        filename_prefix="batch/00_cover",
    )
    assert workflow["28"]["inputs"]["image"] == "cover.png"
    assert workflow["16"]["inputs"]["prompt"] == "画面"
    # 无 speech 映射:不注入也不报错
    assert workflow["16"]["inputs"]["num_frames"] == 121
    assert workflow["13"]["inputs"]["filename_prefix"] == "batch/00_cover"

    svc.delete_template("首帧图生视频")
    assert svc.get_default() == ""
    with pytest.raises(Exception):
        svc.get_default_adapter()


def test_workflows_api_flow(converted, monkeypatch):
    from app.main import app

    api, map_yaml = converted
    _client_with_object_info(monkeypatch)
    # 指向 fixture 的 ComfyUI 用户工作流目录
    from app.core.config import settings

    monkeypatch.setattr(settings, "comfyui_user_workflows_dir", FIXTURES)

    with TestClient(app) as client:
        # 无模板:列表空,默认空
        resp = client.get("/api/workflows")
        assert resp.status_code == 200
        assert resp.json() == {"templates": [], "default": ""}

        # 用户工作流来源与转换
        sources = client.get("/api/workflows/user-sources").json()["sources"]
        assert any(s["filename"] == "ui_workflow_h3.json" for s in sources)
        conv = client.post("/api/workflows/convert", json={"filename": "ui_workflow_h3.json"})
        assert conv.status_code == 200
        body = conv.json()
        assert body["suggested_name"] == "ui_workflow_h3"
        assert "16" in body["workflow_api"]
        assert "nodes" in body["map_draft"]

        # 保存 + 设默认 + 删除
        saved = client.post(
            "/api/workflows",
            json={"name": "首帧图生视频", "workflow_api": body["workflow_api"], "map_yaml": body["map_draft"]},
        )
        assert saved.status_code == 200
        assert saved.json()["problems"] == []
        assert client.put("/api/workflows/default", json={"name": "首帧图生视频"}).status_code == 200
        listed = client.get("/api/workflows").json()
        assert listed["default"] == "首帧图生视频"
        assert listed["templates"][0]["valid"] is True
        assert client.delete("/api/workflows/首帧图生视频").status_code == 200
        assert client.get("/api/workflows").json()["default"] == ""

        # 非法名与不存在模板
        assert client.post("/api/workflows/convert", json={"filename": "../etc/passwd"}).status_code == 400
        assert client.put("/api/workflows/default", json={"name": "不存在"}).status_code == 400


def test_health_workflow_check_uses_default(converted):
    from app.main import app
    from app.services import workflow_template_service as svc

    api, map_yaml = converted
    with TestClient(app) as client:
        resp = client.get("/api/system/health")
        checks = resp.json()["checks"]
        assert checks["workflow_template"]["ok"] is False  # 无默认模板 → 失效

        svc.save_template("临时模板", api, map_yaml)
        svc.set_default("临时模板")
        resp = client.get("/api/system/health")
        assert resp.json()["checks"]["workflow_template"]["ok"] is True
        svc.delete_template("临时模板")
