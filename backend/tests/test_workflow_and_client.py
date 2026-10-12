"""workflow_adapter 与 comfyui_client 单元测试(使用示例模板与 MockTransport)。"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.services.comfyui_client import (
    ComfyUIClient,
    ComfyUIResponseError,
    ComfyUIUnreachable,
    parse_ws_message,
)
from app.services.workflow_adapter import (
    WorkflowAdapter,
    build_filename_prefix,
    load_workflow_map,
    load_workflow_template,
    validate_mapping,
)

WORKFLOWS = Path(__file__).resolve().parents[2] / "workflows"
EXAMPLE_TEMPLATE = WORKFLOWS / "minimax_h3_poem_v1.example.json"
EXAMPLE_MAP = WORKFLOWS / "workflow-map.example.yaml"


@pytest.fixture()
def adapter():
    return WorkflowAdapter(EXAMPLE_TEMPLATE, EXAMPLE_MAP)


def test_adapter_build_injects_all_fields(adapter):
    original = load_workflow_template(EXAMPLE_TEMPLATE)
    wf = adapter.build(
        image_name="uploaded_cover.png",
        prompt="正向提示词",
        negative_prompt="反向提示词",
        speech="宿建德江,唐,孟浩然。",
        width=768,
        height=1024,
        fps=24,
        num_frames=121,
        filename_prefix="abc123/00_cover",
    )
    assert wf["12"]["inputs"]["image"] == "uploaded_cover.png"
    assert wf["35"]["inputs"]["prompt"] == "正向提示词"
    assert wf["36"]["inputs"]["negative_prompt"] == "反向提示词"
    assert wf["41"]["inputs"]["text"] == "宿建德江,唐,孟浩然。"
    assert wf["45"]["inputs"]["width"] == 768
    assert wf["45"]["inputs"]["height"] == 1024
    assert wf["45"]["inputs"]["fps"] == 24
    assert wf["45"]["inputs"]["num_frames"] == 121
    assert wf["50"]["inputs"]["filename_prefix"] == "abc123/00_cover"
    assert 0 <= wf["45"]["inputs"]["seed"] < 2**32
    # 原模板文件未被修改
    assert load_workflow_template(EXAMPLE_TEMPLATE) == original
    # 深拷贝:两次构建互不影响
    wf2 = adapter.build(
        image_name="x.png", prompt="p", negative_prompt="n", speech="s",
        width=1, height=1, fps=1, num_frames=1, filename_prefix="p",
    )
    assert wf2["35"]["inputs"]["prompt"] == "p" and wf["35"]["inputs"]["prompt"] == "正向提示词"


def test_filename_prefix_format():
    assert build_filename_prefix("a1b2c3", 0, "cover") == "a1b2c3/00_cover"
    assert build_filename_prefix("a1b2c3", 3, "2") == "a1b2c3/03_2"


def test_validate_mapping_detects_problems():
    template = load_workflow_template(EXAMPLE_TEMPLATE)
    mapping = load_workflow_map(EXAMPLE_MAP)
    assert validate_mapping(template, mapping) == []

    bad_node = dict(mapping, image={"id": "999", "input": "image"})
    problems = validate_mapping(template, bad_node)
    assert any("不存在节点 999" in p for p in problems)

    bad_input = dict(mapping, prompt={"id": "35", "input": "not_exist"})
    problems = validate_mapping(template, bad_input)
    assert any("not_exist" in p for p in problems)


def test_adapter_rejects_invalid_mapping(tmp_path):
    bad_map = tmp_path / "bad-map.yaml"
    bad_map.write_text("nodes:\n  image:\n    id: '1'\n    input: image\n", encoding="utf-8")
    with pytest.raises(ValueError, match="缺少必需字段"):
        WorkflowAdapter(EXAMPLE_TEMPLATE, bad_map)


# ---- ComfyUI Client(MockTransport) ----

def _mock_client(handler) -> ComfyUIClient:
    return ComfyUIClient(
        base_url="http://comfyui.test",
        client_id="test",
        transport=httpx.MockTransport(handler),
    )


def test_ping_ok():
    client = _mock_client(lambda req: httpx.Response(200, json={"system": {}}))
    import asyncio

    assert asyncio.run(client.ping()) is True
    asyncio.run(client.aclose())


def test_ping_unreachable():
    def raise_connect(req):
        raise httpx.ConnectError("refused")

    client = _mock_client(raise_connect)
    import asyncio

    assert asyncio.run(client.ping()) is False
    asyncio.run(client.aclose())


def test_submit_prompt_returns_id():
    def handler(req: httpx.Request) -> httpx.Response:
        assert req.url.path == "/prompt"
        body = json.loads(req.content)
        assert body["client_id"] == "test"
        assert "12" in body["prompt"]
        return httpx.Response(200, json={"prompt_id": "pid-1"})

    client = _mock_client(handler)
    import asyncio

    prompt_id = asyncio.run(client.submit_prompt({"12": {"class_type": "LoadImage", "inputs": {}}}))
    assert prompt_id == "pid-1"
    asyncio.run(client.aclose())


def test_submit_prompt_server_error():
    client = _mock_client(lambda req: httpx.Response(400, text='{"error": "bad workflow"}'))
    import asyncio

    with pytest.raises(ComfyUIResponseError):
        asyncio.run(client.submit_prompt({"x": {}}))
    asyncio.run(client.aclose())


def test_history_and_view():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.path.startswith("/history/"):
            return httpx.Response(200, json={"pid-9": {"status": {"status_str": "completed"}}})
        if req.url.path == "/view":
            assert req.url.params["filename"] == "video.mp4"
            return httpx.Response(200, content=b"mp4-bytes")
        return httpx.Response(404)

    client = _mock_client(handler)
    import asyncio

    async def run():
        history = await client.get_history("pid-9")
        assert history["pid-9"]["status"]["status_str"] == "completed"
        content = await client.fetch_view("video.mp4", "", "output")
        assert content == b"mp4-bytes"

    asyncio.run(run())
    asyncio.run(client.aclose())


def test_unreachable_wrapped():
    def raise_connect(req):
        raise httpx.ConnectError("refused")

    client = _mock_client(raise_connect)
    import asyncio

    with pytest.raises(ComfyUIUnreachable):
        asyncio.run(client.get_queue())
    asyncio.run(client.aclose())


def test_parse_ws_message():
    assert parse_ws_message('{"type": "executing", "data": {"prompt_id": "p1"}}')["type"] == "executing"
    assert parse_ws_message("not-json") == {}
    assert parse_ws_message(b'{"type": "progress", "data": {}}')["type"] == "progress"
