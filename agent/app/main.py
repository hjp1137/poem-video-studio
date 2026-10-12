"""poem-video-agent 入口:FastAPI,默认绑定 127.0.0.1,只提供白名单 API。"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app.api import gpu, health, services, workloads
from app.core.config import agent_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

app = FastAPI(title="poem-video-agent", version="1.1.0")
app.include_router(health.router)
app.include_router(gpu.router)
app.include_router(services.router)
app.include_router(workloads.router)


@app.get("/")
def root() -> dict:
    return {
        "app": "poem-video-agent",
        "version": "1.1.0",
        "listen": f"{agent_settings.host}:{agent_settings.port}",
        "note": "allowlist-only host agent; no shell/exec/command endpoints",
    }


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=agent_settings.host, port=agent_settings.port)


if __name__ == "__main__":
    main()
