"""reconcile_task 对账修复回归:执行中不得误判 recover_pending,真消失才标记。"""
from __future__ import annotations

import asyncio

from app.core.database import SessionLocal, init_db
from app.models.batch import Batch
from app.models.task import VideoTask
from app.services import task_tracker


class FakeClient:
    def __init__(self, history: dict, queue: dict):
        self._history = history
        self._queue = queue

    async def get_history(self, prompt_id: str, max_items: int = 64) -> dict:
        return self._history

    async def get_queue(self) -> dict:
        return self._queue

    async def aclose(self) -> None:
        pass


def _prepare_task(status: str, prompt_id: str) -> tuple:
    from app.core.config import settings

    settings.ensure_dirs()  # 建全 uploads/outputs/database 子目录(单跑无 lifespan 兜底)
    init_db()
    db = SessionLocal()
    batch = Batch(id="b-reconcile-test", title="测试", dynasty="唐", author="测试", status="running",
                  raw_batch_text="POEM_VIDEO_BATCH_V1")
    db.add(batch)
    task = VideoTask(
        id="t-reconcile-test", batch_id=batch.id, scene_key="cover", scene_order=0,
        status=status, comfy_prompt_id=prompt_id,
    )
    db.add(task)
    db.commit()
    return db, task


def test_running_task_with_empty_history_kept_queued():
    """执行中:history 尚未写入但仍在 ComfyUI 队列 → 状态不得变 recover_pending。"""
    db, task = _prepare_task("queued", "pid-running")
    try:
        client = FakeClient(
            {},
            {"queue_running": [[1, "pid-running", {}, {}, []]], "queue_pending": []},
        )
        asyncio.run(task_tracker.reconcile_task(db, client, task))
        assert task.status == "queued"
    finally:
        db.query(VideoTask).filter_by(id="t-reconcile-test").delete()
        db.query(Batch).filter_by(id="b-reconcile-test").delete()
        db.commit()
        db.close()


def test_lost_task_marked_recover_pending():
    """真消失:history 无记录且不在队列 → recover_pending。"""
    db, task = _prepare_task("queued", "pid-lost")
    try:
        client = FakeClient({}, {"queue_running": [], "queue_pending": []})
        asyncio.run(task_tracker.reconcile_task(db, client, task))
        assert task.status == "recover_pending"
    finally:
        db.query(VideoTask).filter_by(id="t-reconcile-test").delete()
        db.query(Batch).filter_by(id="b-reconcile-test").delete()
        db.commit()
        db.close()


def test_recover_pending_task_recovers_on_success_history():
    """recover_pending 任务在 history 出现完成记录后被恢复(避免永久卡死)。"""
    db, task = _prepare_task("recover_pending", "pid-done")
    try:
        # SaveVideo 在 history 中经 images 通道输出(真实 199 记录验证)
        entry = {
            "status": {"status_str": "completed", "completed": True, "messages": []},
            "outputs": {
                "13": {
                    "images": [{
                        "filename": "out_00001_.mp4",
                        "subfolder": "bb/00",
                        "type": "output",
                    }],
                }
            },
        }

        class DownloadClient(FakeClient):
            async def fetch_view(self, filename, subfolder="", output_type="output"):
                return b"fake-mp4"

        async def fake_download(client, video_info, batch_id, scene_order, scene_key):
            from pathlib import Path
            from app.core.config import settings
            target = settings.data_root / "outputs" / batch_id / f"{scene_order:02d}_{scene_key}.mp4"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"fake-mp4")
            return target

        # task_tracker 以 from-import 绑定了 download_output,须替换该命名空间的名字
        original = task_tracker.download_output
        task_tracker.download_output = fake_download
        try:
            client = DownloadClient({"pid-done": entry}, {"queue_running": [], "queue_pending": []})
            asyncio.run(task_tracker.reconcile_task(db, client, task))
            assert task.status == "completed"
            assert task.output_path.endswith(".mp4")
            # 对账完成时须同步刷新批次状态,否则批次停留在 queued
            batch = db.get(Batch, "b-reconcile-test")
            assert batch.status == "completed"
        finally:
            task_tracker.download_output = original
    finally:
        db.query(VideoTask).filter_by(id="t-reconcile-test").delete()
        db.query(Batch).filter_by(id="b-reconcile-test").delete()
        db.commit()
        db.close()


def test_cancel_queued_batch_returns_tasks_to_pending(monkeypatch):
    """移除队列:queued 任务清 prompt_id 回 pending;ComfyUI 队列删除被调用。"""
    from app.models.task import VideoTask as VT

    db, _ = _prepare_task("queued", "pid-cancel-1")
    # 再补两个不同状态的任务:running 不动、pending 不动
    db.add(VT(id="t-cancel-2", batch_id="b-reconcile-test", scene_key="1", scene_order=1,
              status="running", comfy_prompt_id="pid-cancel-2"))
    db.commit()

    deleted: list[list[str]] = []

    class QueueClient:
        async def delete_queue_items(self, prompt_ids):
            deleted.append(prompt_ids)

        async def aclose(self):
            pass

    monkeypatch.setattr(task_tracker, "_client", lambda: QueueClient())
    result = asyncio.run(task_tracker.cancel_queued_batch(db, "b-reconcile-test"))
    try:
        assert result["cancelled"] == 1
        assert deleted and deleted[0] == ["pid-cancel-1"]  # 只删排队中的
        tasks = {t.id: t for t in db.query(VT).filter_by(batch_id="b-reconcile-test").all()}
        assert tasks["t-reconcile-test"].status == "pending"
        assert tasks["t-reconcile-test"].comfy_prompt_id is None
        assert tasks["t-cancel-2"].status == "running"  # 执行中不受影响
    finally:
        db.query(VT).filter_by(batch_id="b-reconcile-test").delete()
        db.query(Batch).filter_by(id="b-reconcile-test").delete()
        db.commit()
        db.close()
