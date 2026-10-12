"""请求保护:可选 Bearer Token。Token 未配置时不拦截(依赖 localhost 绑定)。"""
from __future__ import annotations

from fastapi import HTTPException, Request

from app.core.config import agent_settings


def require_token(request: Request) -> None:
    token = agent_settings.token
    if not token:
        return
    auth = request.headers.get("authorization", "")
    if auth != f"Bearer {token}":
        raise HTTPException(status_code=401, detail="Agent Token 无效或缺失")
