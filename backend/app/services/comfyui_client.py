"""ComfyUI HTTP / WebSocket 客户端。

封装 POST /prompt、GET /queue、GET /history、POST /upload/image、GET /view,
统一超时、错误分类(不可达 / 状态码异常 / JSON 异常),供上层稳定调用。
WebSocket 订阅由 task_tracker 的后台任务使用。
"""
from __future__ import annotations

import json
from typing import Any

import httpx


class ComfyUIError(Exception):
    """ComfyUI 交互异常,携带可诊断信息。"""


class ComfyUIUnreachable(ComfyUIError):
    pass


class ComfyUIResponseError(ComfyUIError):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body[:2000]
        super().__init__(f"ComfyUI 返回 {status_code}:{self.body[:300]}")


class ComfyUIClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        ws_url: str = "",
        connect_timeout: float = 5.0,
        request_timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.ws_url = ws_url
        self.client_id = client_id
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(request_timeout, connect=connect_timeout),
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---- 基础请求 ----
    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ComfyUIUnreachable(f"ComfyUI 不可达({path}):{exc}") from exc
        if resp.status_code >= 400:
            raise ComfyUIResponseError(resp.status_code, resp.text)
        return resp

    async def _request_json(self, method: str, path: str, **kwargs) -> Any:
        resp = await self._request(method, path, **kwargs)
        try:
            return resp.json()
        except ValueError as exc:
            raise ComfyUIError(f"ComfyUI 返回非法 JSON({path})") from exc

    # ---- HTTP API ----
    async def ping(self) -> bool:
        try:
            await self._request("GET", "/system_stats")
            return True
        except ComfyUIError:
            return False

    async def get_queue(self) -> dict:
        return await self._request_json("GET", "/queue")

    async def get_object_info(self) -> dict:
        """全量节点定义(含每个节点 required/optional 输入的类型与顺序)。"""
        return await self._request_json("GET", "/object_info")

    async def get_history(self, prompt_id: str, max_items: int = 64) -> dict:
        return await self._request_json("GET", f"/history/{prompt_id}", params={"max_items": max_items})

    async def upload_image(self, file_path, name: str | None = None) -> str:
        """上传首帧图片到 ComfyUI input,返回 ComfyUI 侧文件名。"""
        from pathlib import Path

        path = Path(file_path)
        if not path.is_file():
            raise ComfyUIError(f"首帧图片不存在:{path}")
        files = {"image": (name or path.name, path.open("rb"), "application/octet-stream")}
        data = {"overwrite": "true"}
        resp = await self._request("POST", "/upload/image", files=files, data=data)
        try:
            payload = resp.json()
        except ValueError as exc:
            raise ComfyUIError("上传图片返回非法 JSON") from exc
        name = payload.get("name")
        if not name:
            raise ComfyUIError(f"上传图片未返回文件名:{payload}")
        return name

    async def submit_prompt(self, prompt_workflow: dict, client_id: str | None = None) -> str:
        """POST /prompt,返回 prompt_id。"""
        payload = {"prompt": prompt_workflow, "client_id": client_id or self.client_id}
        resp = await self._request_json("POST", "/prompt", json=payload)
        prompt_id = resp.get("prompt_id")
        if not prompt_id:
            raise ComfyUIError(f"提交未返回 prompt_id:{json.dumps(resp, ensure_ascii=False)[:300]}")
        return prompt_id

    async def fetch_view(self, filename: str, subfolder: str = "", output_type: str = "output") -> bytes:
        params = {"filename": filename, "subfolder": subfolder, "type": output_type}
        resp = await self._request("GET", "/view", params=params)
        return resp.content

    async def interrupt(self) -> None:
        await self._request("POST", "/interrupt")

    async def delete_queue_items(self, prompt_ids: list[str]) -> None:
        """从 ComfyUI pending 队列删除指定任务(正在执行的不受影响)。"""
        if not prompt_ids:
            return
        await self._request("DELETE", "/queue", json={"delete": prompt_ids})


def parse_ws_message(raw: str | bytes) -> dict:
    """解析 ComfyUI /ws 消息为 {type, data};无法解析时返回空 dict。"""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except (ValueError, TypeError):
        pass
    return {}
