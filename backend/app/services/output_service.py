"""输出文件识别与落地。

以 prompt_id → ComfyUI history → Save 节点输出为唯一依据定位 MP4,
禁止凭“最后生成的文件”猜测。文件经 /view 下载复制到 outputs/{batch_id}/。
"""
from __future__ import annotations

import re
from pathlib import Path

from app.core.config import settings
from app.services.comfyui_client import ComfyUIClient, ComfyUIError


def find_video_in_history(history_entry: dict) -> dict | None:
    """在单个 history 条目的 outputs 中定位视频文件信息。"""
    outputs = history_entry.get("outputs") or {}
    for node_id, node_out in outputs.items():
        images = node_out.get("images") or node_out.get("gifs") or []
        for item in images:
            ftype = item.get("type", "")
            filename = item.get("filename", "")
            if ftype == "output" and filename.lower().endswith((".mp4", ".webm")):
                return {
                    "node_id": node_id,
                    "filename": filename,
                    "subfolder": item.get("subfolder", ""),
                    "type": ftype,
                }
    return None


def _safe_stem(batch_id: str, scene_order: int, scene_key: str) -> str:
    key = re.sub(r"[^a-zA-Z0-9_\-]+", "_", scene_key)
    return f"{scene_order:02d}_{key}"


async def download_output(
    client: ComfyUIClient,
    video_info: dict,
    batch_id: str,
    scene_order: int,
    scene_key: str,
) -> Path:
    """把 ComfyUI 输出视频下载复制到 outputs/{batch_id}/,返回本地绝对路径。"""
    content = await client.fetch_view(
        filename=video_info["filename"],
        subfolder=video_info.get("subfolder", ""),
        output_type=video_info.get("type", "output"),
    )
    if not content:
        raise ComfyUIError("输出视频下载内容为空")
    dest_dir = settings.outputs_dir / batch_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_stem(batch_id, scene_order, scene_key)
    # 重试多次各版本都保留:已存在同名文件时递增 _v2/_v3…,不覆盖旧版本
    dest = dest_dir / f"{stem}.mp4"
    seq = 2
    while dest.exists():
        dest = dest_dir / f"{stem}_v{seq}.mp4"
        seq += 1
    dest.write_bytes(content)
    return dest
