"""FL2VA 首尾帧请求契约单测，不需要 GPU。"""
import asyncio
import json

import httpx
import pytest

from app.services.h3_keyframes import (
    FrameImage, H3Settings, H3RequestError, build_form,
    generate_first_last, sync_endpoint,
)


@pytest.fixture
def pair():
    return (FrameImage("first.png", b"first", "image/png"),
            FrameImage("last.png", b"last", "image/png"))


def test_multipart_order(pair):
    first, last = pair
    data, files = build_form(H3Settings(prompt="山水过渡"), first, last)
    assert json.loads(data["extra_params"])["frame_indices"] == [0, -1]
    assert json.loads(data["extra_params"])["task"] == "fl2va"
    assert [f[0] for f in files] == ["input_references", "input_references"]
    assert [f[1][1] for f in files] == [b"first", b"last"]
    assert "lora" not in data


def test_turbo_contract(pair):
    data, _ = build_form(H3Settings(prompt="诗词", turbo=True), *pair)
    assert data["num_inference_steps"] == "9"
    assert data["flow_shift"] == "6"
    assert json.loads(data["lora"])["scale"] == 1.0


def test_invalid_params(pair):
    with pytest.raises(H3RequestError):
        H3Settings(prompt="")
    with pytest.raises(H3RequestError):
        H3Settings(prompt="x", width=777)
    with pytest.raises(H3RequestError):
        FrameImage("bad.gif", b"GIF", "image/gif")


def test_endpoint():
    assert sync_endpoint("http://127.0.0.1:8000") == "http://127.0.0.1:8000/v1/videos/sync"
    assert sync_endpoint("http://127.0.0.1:8000/v1") == "http://127.0.0.1:8000/v1/videos/sync"


def test_mock_h3_call(pair):
    captured = {}
    def fake(request):
        captured["url"] = str(request.url)
        captured["body"] = request.read()
        return httpx.Response(200, content=b"\x00\x00\x00\x14ftypisomVIDEO")

    async def call():
        return await generate_first_last(
            base_url="http://127.0.0.1:8000", first=pair[0], last=pair[1],
            settings=H3Settings(prompt="过渡"),
            transport=httpx.MockTransport(fake),
        )
    video = asyncio.run(call())
    assert video[4:8] == b"ftyp"
    assert captured["url"].endswith("/v1/videos/sync")
    assert captured["body"].count(b'name="input_references"') == 2
    assert captured["body"].index(b"first") < captured["body"].index(b"last")


def test_api_failure_surfaces(pair):
    async def call():
        await generate_first_last(
            base_url="http://127.0.0.1:8000", first=pair[0], last=pair[1],
            settings=H3Settings(prompt="过渡"),
            transport=httpx.MockTransport(
                lambda r: httpx.Response(422, json={"detail": "frame_indices unsupported"})
            ),
        )
    with pytest.raises(H3RequestError, match="422"):
        asyncio.run(call())
