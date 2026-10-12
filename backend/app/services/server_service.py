"""服务器控制中心业务层:KV 设置读写 + ServerOperation 审计。"""
from __future__ import annotations

import json
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.server import ServerOperation, ServerSetting

GPU_POWER_SETTING_KEY = "gpu_power"


class SettingError(Exception):
    pass


def get_setting_json(db: Session, key: str, default: dict | None = None) -> dict:
    row = db.get(ServerSetting, key)
    if row is None:
        return default or {}
    try:
        value = json.loads(row.value_json)
        return value if isinstance(value, dict) else (default or {})
    except ValueError:
        return default or {}


def put_setting_json(db: Session, key: str, value: dict) -> None:
    row = db.get(ServerSetting, key)
    if row is None:
        row = ServerSetting(key=key, value_json="{}", updated_at=int(time.time()))
        db.add(row)
    row.value_json = json.dumps(value, ensure_ascii=False)
    row.updated_at = int(time.time())
    db.commit()


def get_gpu_power_setting(db: Session) -> dict:
    data = get_setting_json(db, GPU_POWER_SETTING_KEY)
    return {
        "enabled": bool(data.get("enabled", False)),
        "default_power_limit": data.get("default_power_limit"),
    }


def put_gpu_power_setting(db: Session, enabled: bool, default_power_limit: int | None) -> dict:
    if default_power_limit is not None and (not isinstance(default_power_limit, int) or default_power_limit <= 0):
        raise SettingError("default_power_limit 必须是正整数")
    value = {"enabled": enabled, "default_power_limit": default_power_limit}
    put_setting_json(db, GPU_POWER_SETTING_KEY, value)
    return value


def record_operation(
    db: Session,
    *,
    request_id: str,
    action: str,
    target_type: str = "",
    target_name: str = "",
    parameters: dict | None = None,
    result: str = "success",
    error_message: str = "",
    source_ip: str = "",
    created_at: int | None = None,
) -> ServerOperation:
    op = ServerOperation(
        id=uuid.uuid4().hex[:12],
        request_id=request_id,
        action=action,
        target_type=target_type,
        target_name=target_name,
        parameters_json=json.dumps(parameters or {}, ensure_ascii=False)[:4000],
        result=result,
        error_message=(error_message or "")[:4000],
        source_ip=source_ip,
        created_at=created_at or int(time.time()),
        finished_at=int(time.time()),
    )
    db.add(op)
    db.commit()
    return op


def list_operations(db: Session, limit: int = 50, offset: int = 0) -> tuple[list[ServerOperation], int]:
    from sqlalchemy import func

    total = db.execute(select(func.count(ServerOperation.id))).scalar_one()
    rows = (
        db.execute(
            select(ServerOperation).order_by(ServerOperation.created_at.desc(), ServerOperation.id.desc())
            .limit(limit).offset(offset)
        )
        .scalars()
        .all()
    )
    return rows, total


def operation_to_out(op: ServerOperation) -> dict:
    try:
        parameters = json.loads(op.parameters_json) if op.parameters_json else {}
    except ValueError:
        parameters = {"raw": op.parameters_json[:200]}
    return {
        "id": op.id,
        "request_id": op.request_id,
        "action": op.action,
        "target_type": op.target_type,
        "target_name": op.target_name,
        "parameters": parameters,
        "result": op.result,
        "error_message": op.error_message,
        "source_ip": op.source_ip,
        "created_at": op.created_at,
        "finished_at": op.finished_at,
    }
