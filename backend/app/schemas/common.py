"""API 请求/响应模型。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ParseRequest(BaseModel):
    text: str = Field(min_length=1)


class CreateBatchRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    dynasty: str = ""
    author: str = ""
    raw_batch_text: str = Field(min_length=1)
    image_bindings: dict[str, str] = Field(default_factory=dict)  # scene_key -> upload_id


class UploadItem(BaseModel):
    upload_id: str
    original_name: str
    guessed_scene_key: str | None = None
    size: int = 0
    image_url: str


class UploadResponse(BaseModel):
    group_id: str
    files: list[UploadItem]


class BatchSummary(BaseModel):
    id: str
    title: str
    dynasty: str
    author: str
    status: str
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    created_at: int
    updated_at: int


class TaskOut(BaseModel):
    id: str
    batch_id: str
    scene_key: str
    scene_order: int
    image_path: str
    image_url: str
    prompt: str
    negative_prompt: str
    speech: str
    width: int
    height: int
    fps: int
    num_frames: int
    comfy_prompt_id: str | None = None
    status: str
    output_path: str = ""
    video_url: str | None = None
    download_url: str | None = None
    error_message: str = ""
    created_at: int
    # 多版本输出历史(重试多次累积,版本号从 1 起)
    outputs: list[dict] = []
    started_at: int | None = None
    finished_at: int | None = None
