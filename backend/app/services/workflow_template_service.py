"""Workflow 模板管理:模板存放于 DATA_ROOT/workflows/(数据卷,可写持久)。

- 每个模板一对文件:<name>.json(API Format) + <name>.map.yaml(节点映射);
- 默认模板名记录在 settings.json;生成提交/重试一律使用默认模板;
- 兼容导入:支持把 ComfyUI 用户工作流(UI 格式)转换为 API 格式模板。
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.core.config import settings
from app.services.comfyui_client import ComfyUIClient, ComfyUIError
from app.services.workflow_adapter import (
    WorkflowAdapter,
    load_workflow_map,
    load_workflow_template,
    validate_mapping,
)
from app.services.workflow_converter import convert_ui_to_api, draft_map

SAFE_NAME_RE = re.compile(r"^[\w\-\u4e00-\u9fff][\w\-. \u4e00-\u9fff]{0,63}$")
SETTINGS_FILE = "settings.json"


def _workflow_dir() -> Path:
    root = settings.data_root / "workflows"
    root.mkdir(parents=True, exist_ok=True)
    return root


class TemplateError(Exception):
    """模板名非法/不存在/损坏等业务错误,API 层转 4xx。"""


@dataclass
class TemplateInfo:
    name: str
    has_map: bool
    problems: list[str]
    updated_at: float
    is_default: bool

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "has_map": self.has_map,
            "valid": not self.problems,
            "problems": self.problems,
            "updated_at": int(self.updated_at),
            "is_default": self.is_default,
        }


def _validate_name(name: str) -> str:
    name = (name or "").strip()
    if not SAFE_NAME_RE.match(name):
        raise TemplateError(f"模板名非法:「{name}」(1~64 位中文/字母/数字/空格/._-)")
    if name in (SETTINGS_FILE,) or name.endswith(".map"):
        raise TemplateError(f"模板名不可使用保留名:{name}")
    return name


def list_templates() -> list[dict]:
    root = _workflow_dir()
    default = _read_default()
    result: list[dict] = []
    for path in sorted(root.glob("*.json")):
        if path.name == SETTINGS_FILE:
            continue
        name = path.stem
        map_path = root / f"{name}.map.yaml"
        problems: list[str] = []
        try:
            template = load_workflow_template(path)
            if not map_path.is_file():
                problems.append("缺少映射文件 <name>.map.yaml")
            else:
                mapping = load_workflow_map(map_path)
                problems.extend(validate_mapping(template, mapping))
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            problems.append(str(exc))
        result.append(
            TemplateInfo(
                name=name,
                has_map=map_path.is_file(),
                problems=problems,
                updated_at=path.stat().st_mtime,
                is_default=name == default,
            ).to_dict()
        )
    return result


def _read_default() -> str:
    path = _workflow_dir() / SETTINGS_FILE
    if not path.is_file():
        return ""
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("default", "") or "")
    except (json.JSONDecodeError, OSError):
        return ""


def set_default(name: str) -> dict:
    name = _validate_name(name)
    json_path = _workflow_dir() / f"{name}.json"
    if not json_path.is_file():
        raise TemplateError(f"模板不存在:{name}")
    # 设默认前先做完整校验,禁止把损坏模板设为默认
    check_template(name)
    (_workflow_dir() / SETTINGS_FILE).write_text(
        json.dumps({"default": name, "updated_at": int(time.time())}, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"default": name}


def get_default() -> str:
    return _read_default()


def check_template(name: str) -> dict:
    """加载并校验一个模板,返回 {node_count, problems}。"""
    root = _workflow_dir()
    template = load_workflow_template(root / f"{name}.json")
    mapping = load_workflow_map(root / f"{name}.map.yaml")
    problems = validate_mapping(template, mapping)
    return {"node_count": len(template), "problems": problems}


def save_template(name: str, workflow_api: dict, map_yaml: str) -> dict:
    name = _validate_name(name)
    if not isinstance(workflow_api, dict) or not workflow_api:
        raise TemplateError("workflow_api 必须是非空 JSON 对象(API Format)")
    try:
        parsed_map = yaml.safe_load(map_yaml) or {}
    except yaml.YAMLError as exc:
        raise TemplateError(f"映射 YAML 解析失败:{exc}") from exc
    if not (parsed_map.get("nodes") or {}):
        raise TemplateError("映射缺少 nodes 字段")
    # 落盘前先校验,坏模板不允许入库
    problems = validate_mapping(workflow_api, {k: v for k, v in (parsed_map.get("nodes") or {}).items()})
    if problems:
        raise TemplateError("映射校验失败:" + "; ".join(problems))
    root = _workflow_dir()
    (root / f"{name}.json").write_text(
        json.dumps(workflow_api, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (root / f"{name}.map.yaml").write_text(map_yaml, encoding="utf-8")
    return check_template(name)


def delete_template(name: str) -> dict:
    name = _validate_name(name)
    root = _workflow_dir()
    removed = []
    for path in (root / f"{name}.json", root / f"{name}.map.yaml"):
        if path.is_file():
            path.unlink()
            removed.append(path.name)
    if not removed:
        raise TemplateError(f"模板不存在:{name}")
    if _read_default() == name:
        (root / SETTINGS_FILE).unlink(missing_ok=True)
    return {"removed": removed}


def get_default_adapter() -> WorkflowAdapter:
    """生成链路入口:按默认模板构造 Adapter;无默认/损坏时报可操作错误。"""
    default = _read_default()
    if not default:
        raise FileNotFoundError("未设置默认 Workflow 模板:请到「模板管理」页导入或指定默认模板")
    root = _workflow_dir()
    try:
        return WorkflowAdapter(root / f"{default}.json", root / f"{default}.map.yaml")
    except (FileNotFoundError, ValueError) as exc:
        raise FileNotFoundError(f"默认模板「{default}」不可用:{exc}") from exc


def list_user_sources() -> list[dict]:
    """列出 ComfyUI 用户工作流目录下的 UI 格式工作流(容器内挂载路径)。"""
    src_dir = settings.comfyui_user_workflows_dir
    if not src_dir.is_dir():
        return []
    sources = []
    for path in sorted(src_dir.glob("*.json")):
        sources.append({"filename": path.name, "size": path.stat().st_size})
    return sources


async def convert_user_workflow(filename: str) -> dict:
    """读取一个 ComfyUI 用户工作流并转换为 API 格式+映射草稿(预览,不落盘)。"""
    src_dir = settings.comfyui_user_workflows_dir
    path = src_dir / (filename or "")
    if not src_dir.is_dir() or not path.is_file() or path.parent != src_dir:
        raise TemplateError(f"ComfyUI 用户工作流不存在:{filename}")
    try:
        ui = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise TemplateError(f"工作流文件读取失败:{exc}") from exc
    if not isinstance(ui.get("nodes"), list):
        raise TemplateError("不是有效的 ComfyUI UI 格式工作流(缺少 nodes)")

    client = ComfyUIClient(
        base_url=settings.comfyui_base_url,
        ws_url=settings.comfyui_ws_url,
        client_id=settings.comfyui_client_id,
        connect_timeout=settings.comfyui_connect_timeout,
        request_timeout=settings.comfyui_request_timeout,
    )
    try:
        object_info = await client.get_object_info()
    except ComfyUIError as exc:
        raise TemplateError(f"获取 ComfyUI object_info 失败:{exc}") from exc
    finally:
        await client.aclose()

    api, warnings = convert_ui_to_api(ui, object_info)
    if not api:
        raise TemplateError("转换失败:" + "; ".join(warnings))
    draft = draft_map(api)
    draft["name"] = path.stem
    missing = [f for f in ("image", "prompt", "save") if f not in draft["nodes"]]
    if missing:
        warnings.append("映射草稿缺少字段:" + ",".join(missing) + ",请手工在 YAML 中补齐")
    return {
        "source": filename,
        "suggested_name": path.stem,
        "workflow_api": api,
        "map_draft": yaml.safe_dump(draft, allow_unicode=True, sort_keys=False),
        "warnings": warnings,
    }
