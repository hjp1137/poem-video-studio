"""PoemVideo Studio API 入口。"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import batches, keyframes, server, system, tasks, uploads, workflows, ws
from app.core.config import settings
from app.core.database import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("poem.main")

_monitor_task: asyncio.Task | None = None
_stop_event = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _monitor_task
    settings.ensure_dirs()
    init_db()
    # 启动恢复:按 prompt_id 与 ComfyUI history 对账(ComfyUI 不可达时仅记录日志)
    from app.services.task_tracker import monitor_loop, startup_reconcile

    try:
        await startup_reconcile()
    except Exception as exc:
        logger.warning("启动恢复未完成(ComfyUI 可能不可达):%s", exc)
    _monitor_task = asyncio.create_task(monitor_loop(_stop_event))
    logger.info(
        "PoemVideo Studio 启动完成 data_root=%s comfyui=%s",
        settings.data_root, settings.comfyui_base_url,
    )
    yield
    _stop_event.set()
    if _monitor_task:
        _monitor_task.cancel()
        try:
            await _monitor_task
        except (asyncio.CancelledError, Exception):
            pass


app = FastAPI(title="PoemVideo Studio API", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(uploads.router)
app.include_router(batches.router)
app.include_router(tasks.router)
app.include_router(workflows.router)
app.include_router(ws.router)
app.include_router(server.router)
app.include_router(keyframes.router)


@app.get("/")
async def root():
    return {"app": "PoemVideo Studio API", "version": "1.0.0", "docs": "/docs"}
