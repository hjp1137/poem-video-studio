"""浏览器侧 WebSocket:推送批次任务状态变化(后台轮询 DB 差异,断线由前端降级 HTTP 轮询)。"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.database import SessionLocal
from app.models.batch import Batch
from app.models.task import VideoTask

router = APIRouter(tags=["ws"])


def _snapshot(db, batch_id: str) -> dict:
    batch = db.get(Batch, batch_id)
    if batch is None:
        return {"error": "batch_not_found"}
    tasks = (
        db.execute(select(VideoTask).where(VideoTask.batch_id == batch_id).order_by(VideoTask.scene_order))
        .scalars()
        .all()
    )
    return {
        "batch_id": batch_id,
        "batch_status": batch.status,
        "tasks": [
            {
                "id": t.id,
                "scene_key": t.scene_key,
                "scene_order": t.scene_order,
                "status": t.status,
                "comfy_prompt_id": t.comfy_prompt_id,
                "output_path": t.output_path,
                "error_message": t.error_message,
                "started_at": t.started_at,
                "finished_at": t.finished_at,
            }
            for t in tasks
        ],
    }


@router.websocket("/api/ws/batches/{batch_id}")
async def batch_ws(websocket: WebSocket, batch_id: str):
    await websocket.accept()
    last_payload = ""
    try:
        while True:
            db = SessionLocal()
            try:
                payload = json.dumps(_snapshot(db, batch_id), ensure_ascii=False)
            finally:
                db.close()
            if payload != last_payload:
                await websocket.send_text(payload)
                last_payload = payload
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass
