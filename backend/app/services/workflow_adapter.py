"""Workflow Adapter:读取 ComfyUI API Workflow 模板并注入场景参数。

节点映射集中在 workflows/workflow-map.yaml,不允许在业务代码中硬编码节点 ID。
映射在加载时校验:节点或 input 不存在时返回具体错误,禁止进入生成。
"""
from __future__ import annotations

import copy
import json
import random
from pathlib import Path
from typing import Any

import yaml

REQUIRED_FIELDS = ("image", "prompt", "save")
# speech 为可选:部分工作流(如用户自建首帧图生视频)无语音输入节点
OPTIONAL_FIELDS = ("last_image", "negative_prompt", "speech", "width", "height", "fps", "num_frames", "seed")


def load_workflow_map(path: Path) -> dict[str, dict[str, str]]:
    """加载并基本校验 workflow-map.yaml,返回 {field: {id, input}}。"""
    if not path.is_file():
        raise FileNotFoundError(f"workflow 映射文件不存在:{path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    nodes = data.get("nodes") or {}
    for field in REQUIRED_FIELDS:
        if field not in nodes:
            raise ValueError(f"workflow 映射缺少必需字段:{field}")
    result: dict[str, dict[str, str]] = {}
    for field in list(REQUIRED_FIELDS) + list(OPTIONAL_FIELDS):
        if field in nodes:
            entry = nodes[field]
            if "id" not in entry or "input" not in entry:
                raise ValueError(f"workflow 映射字段 {field} 必须同时包含 id 和 input")
            result[field] = {"id": str(entry["id"]), "input": str(entry["input"])}
    return result


def load_workflow_template(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Workflow 模板不存在:{path}")
    template = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(template, dict):
        raise ValueError("Workflow 模板必须是 API Format JSON 对象")
    return template


def validate_mapping(template: dict[str, Any], mapping: dict[str, dict[str, str]]) -> list[str]:
    """校验映射的节点与 input 是否存在于模板,返回问题列表(空列表=通过)。"""
    problems: list[str] = []
    for field, spec in mapping.items():
        node_id = spec["id"]
        node = template.get(node_id)
        if node is None:
            problems.append(f"映射字段 {field}:模板中不存在节点 {node_id}")
            continue
        inputs = (node or {}).get("inputs") or {}
        if spec["input"] not in inputs:
            problems.append(
                f"映射字段 {field}:节点 {node_id} 不存在 input「{spec['input']}」"
                f"(可用:{list(inputs.keys())})"
            )
    return problems


class WorkflowAdapter:
    def __init__(self, template_path: Path, map_path: Path):
        self.template_path = template_path
        self.map_path = map_path
        self.template = load_workflow_template(template_path)
        self.mapping = load_workflow_map(map_path)
        problems = validate_mapping(self.template, self.mapping)
        if problems:
            raise ValueError("workflow 映射校验失败:" + "; ".join(problems))

    def _set(self, workflow: dict[str, Any], field: str, value: Any) -> None:
        spec = self.mapping[field]
        workflow[spec["id"]]["inputs"][spec["input"]] = value

    def build(
        self,
        *,
        image_name: str,
        prompt: str,
        negative_prompt: str,
        speech: str,
        width: int,
        height: int,
        fps: int,
        num_frames: int,
        filename_prefix: str,
        randomize_seed: bool = True,
        last_image_name: str | None = None,
    ) -> dict[str, Any]:
        """深拷贝模板并注入全部动态字段,返回可直接 POST /prompt 的 JSON。"""
        workflow = copy.deepcopy(self.template)
        self._set(workflow, "image", image_name)
        if last_image_name is not None:
            if "last_image" not in self.mapping:
                raise ValueError("当前工作流不支持尾帧：请使用带 first_frame/last_frame 的模板并映射 last_image")
            self._set(workflow, "last_image", last_image_name)
        self._set(workflow, "prompt", prompt)
        self._set(workflow, "save", filename_prefix)
        # 可选字段(工作流不含对应节点时跳过,不注入)
        if "negative_prompt" in self.mapping:
            self._set(workflow, "negative_prompt", negative_prompt)
        if "speech" in self.mapping:
            self._set(workflow, "speech", speech)
        for field, value in (
            ("width", width), ("height", height), ("fps", fps), ("num_frames", num_frames),
        ):
            if field in self.mapping:
                self._set(workflow, field, value)
        if "seed" in self.mapping and randomize_seed:
            self._set(workflow, "seed", random.randint(0, 2**32 - 1))
        self._set(workflow, "save", filename_prefix)
        return workflow


def build_filename_prefix(batch_id: str, scene_order: int, scene_key: str) -> str:
    """输出命名:{batch_id}/{scene_order:02d}_{scene_key}"""
    return f"{batch_id}/{scene_order:02d}_{scene_key}"
