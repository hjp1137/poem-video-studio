"""MiniMax H3 FL2VA first-and-last-frame API adapter.

Independent of ComfyUI nodes so PoemVideo Studio can test its existing
vLLM-Omni server without upgrading that working environment.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from urllib.parse import urlsplit

import httpx

MAX_IMAGE_BYTES = 30 * 1024 * 1024
SUPPORTED_TYPES = {"image/png", "image/jpeg", "image/webp"}
DEFAULT_TURBO_PATH = (
    "/data/AI_Models/MiniMax-H3/Turbo/"
    "minimax_h3_fl2v_turbo_8step_v1.0_768p_bf16.safetensors"
)


class H3RequestError(Exception):
    """Clear error from validation or the H3 API."""


@dataclass(frozen=True)
class FrameImage:
    filename: str
    data: bytes
    media_type: str

    def __post_init__(self) -> None:
        if self.media_type not in SUPPORTED_TYPES:
            raise H3RequestError("只支持 PNG、JPG 或 WEBP 图片。")
        if not self.data or len(self.data) > MAX_IMAGE_BYTES:
            raise H3RequestError("图片不能为空，且每张不得超过 30MB。")
        # HTTP multipart filename should be a basename, not a client-side path.
        object.__setattr__(self, "filename", Path(self.filename).name)


@dataclass(frozen=True)
class H3Settings:
    prompt: str
    width: int = 768
    height: int = 1024
    duration: float = 5.0
    fps: int = 24
    seed: int = 1101
    turbo: bool = False
    turbo_path: str = DEFAULT_TURBO_PATH

    def __post_init__(self) -> None:
        if not self.prompt.strip():
            raise H3RequestError("请填写视频生成提示词。")
        if (not 256 <= self.width <= 2048 or not 256 <= self.height <= 2048
                or self.width % 32 or self.height % 32):
            raise H3RequestError("宽高必须为 256～2048 之间的 32 的倍数。")
        if self.fps != 24:
            raise H3RequestError("MiniMax H3 当前要求 24fps。")
        if not 4 <= self.duration <= 15:
            raise H3RequestError("MiniMax H3 时长应为 4～15 秒。")
        if self.seed < 0:
            raise H3RequestError("seed 不能为负数。")
        if self.turbo and not self.turbo_path.strip():
            raise H3RequestError("Turbo 模式缺少 LoRA 文件路径。")


def build_form(settings: H3Settings, first: FrameImage, last: FrameImage):
    """Construct ordered multipart payload; first and last must never reverse."""
    extra = {
        "task": "fl2va",
        "duration": settings.duration,
        "frame_indices": [0, -1],
        "audio_flow_shift": 3.0,
    }
    fields = {
        "prompt": settings.prompt,
        "width": str(settings.width),
        "height": str(settings.height),
        "fps": str(settings.fps),
        "seed": str(settings.seed),
        "num_inference_steps": "9" if settings.turbo else "50",
        "flow_shift": "6" if settings.turbo else "12",
        "extra_params": json.dumps(extra, ensure_ascii=False),
    }
    if settings.turbo:
        fields["lora"] = json.dumps({
            "name": "h3-turbo-8step",
            "path": settings.turbo_path,
            "scale": 1.0,
        }, ensure_ascii=False)
    files = [
        ("input_references", (first.filename, first.data, first.media_type)),
        ("input_references", (last.filename, last.data, last.media_type)),
    ]
    return fields, files


def sync_endpoint(base_url: str) -> str:
    base_url = base_url.rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise H3RequestError("H3_API_BASE_URL 需要有效的 HTTP 地址。")
    if base_url.endswith("/v1"):
        return base_url + "/videos/sync"
    return base_url + "/v1/videos/sync"


async def generate_first_last(
    *,
    base_url: str,
    first: FrameImage,
    last: FrameImage,
    settings: H3Settings,
    transport: httpx.AsyncBaseTransport | None = None,
) -> bytes:
    """Call H3 and return MP4. Optional transport enables offline unit tests."""
    fields, files = build_form(settings, first, last)
    url = sync_endpoint(base_url)
    timeout = httpx.Timeout(connect=20, read=14400, write=300, pool=20)
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(url, data=fields, files=files)
    except httpx.HTTPError as exc:
        raise H3RequestError(f"无法连接 H3 服务：{exc}") from exc
    if response.status_code >= 400:
        raise H3RequestError(
            f"H3 返回 HTTP {response.status_code}：{response.text[:1200]}"
        )
    # An HTTP 200 with a JSON error must not be saved as an MP4.
    if len(response.content) < 12 or response.content[4:8] != b"ftyp":
        raise H3RequestError(
            "H3 未返回有效 MP4，请查看 H3 服务日志和响应。"
        )
    return response.content
