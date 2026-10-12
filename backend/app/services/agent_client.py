"""poem-video-agent HTTP 客户端:Web API 的全部宿主机动经此通道。

不执行任何本地命令;错误分类(不可达 / 4xx / 5xx)与 ComfyUIClient 风格一致,
支持注入 httpx MockTransport 供测试。
"""
from __future__ import annotations

import re
from typing import Any

import httpx


class AgentError(Exception):
    """Agent 交互异常,携带可诊断信息。"""


class AgentUnreachable(AgentError):
    pass


class AgentResponseError(AgentError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message or f"Agent 返回 {status_code}")


_SERVICE_NAME_RE = re.compile(r"^[a-z0-9_]{1,64}$")


class AgentClient:
    def __init__(
        self,
        base_url: str,
        token: str = "",
        connect_timeout: float = 3.0,
        request_timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        headers = {"authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(request_timeout, connect=connect_timeout),
            headers=headers,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            resp = await self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise AgentUnreachable(f"Agent 不可达({path}):{exc}") from exc
        if resp.status_code >= 400:
            detail = ""
            try:
                body = resp.json()
                detail = str(body.get("detail", "")) if isinstance(body, dict) else str(body)
            except ValueError:
                detail = resp.text[:300]
            raise AgentResponseError(resp.status_code, detail)
        return resp

    async def _request_json(self, method: str, path: str, **kwargs) -> Any:
        resp = await self._request(method, path, **kwargs)
        try:
            return resp.json()
        except ValueError as exc:
            raise AgentError(f"Agent 返回非法 JSON({path})") from exc

    # ---- health ----
    async def health(self) -> dict:
        return await self._request_json("GET", "/v1/health")

    # ---- GPU ----
    async def get_gpus(self) -> list[dict]:
        data = await self._request_json("GET", "/v1/gpus")
        return data.get("gpus", [])

    async def set_gpu_power_limit(self, index: int, watts: int) -> dict:
        return await self._request_json("PUT", f"/v1/gpus/{index}/power-limit", json={"watts": watts})

    async def get_gpu_power_config(self) -> dict:
        return await self._request_json("GET", "/v1/gpu-power/config")

    async def put_gpu_power_config(self, payload: dict) -> dict:
        return await self._request_json("PUT", "/v1/gpu-power/config", json=payload)

    # ---- 服务控制:name 只允许注册表风格命名,由 Agent 侧注册表二次校验 ----
    @staticmethod
    def validate_service_name(name: str) -> None:
        if not _SERVICE_NAME_RE.match(name):
            raise AgentError(f"非法服务名:{name}")

    async def list_services(self) -> list[dict]:
        data = await self._request_json("GET", "/v1/services")
        return data.get("services", [])

    async def get_service(self, name: str) -> dict:
        self.validate_service_name(name)
        return await self._request_json("GET", f"/v1/services/{name}")

    async def service_action(self, name: str, verb: str) -> dict:
        if verb not in ("start", "stop", "restart"):
            raise AgentError(f"非法动作:{verb}")
        self.validate_service_name(name)
        return await self._request_json("POST", f"/v1/services/{name}/{verb}")

    async def service_logs(self, name: str, lines: int) -> dict:
        self.validate_service_name(name)
        return await self._request_json("GET", f"/v1/services/{name}/logs", params={"lines": lines})

    # ---- GPU 工作负载(自动检测占用 GPU 的容器/服务) ----
    async def get_gpu_workloads(self) -> list[dict]:
        data = await self._request_json("GET", "/v1/gpu-workloads")
        return data.get("workloads", [])

    async def stop_gpu_workload(self, container: str) -> dict:
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$", container):
            raise AgentError(f"非法容器名:{container}")
        return await self._request_json("POST", f"/v1/gpu-workloads/{container}/stop")


def agent_client() -> AgentClient:
    from app.core.config import settings

    return AgentClient(
        base_url=settings.agent_base_url,
        token=settings.agent_token,
        connect_timeout=settings.agent_connect_timeout,
        request_timeout=settings.agent_request_timeout,
    )
