"""ComfyUI UI 格式工作流 → API Format 转换,以及节点映射(workflow-map)草稿推断。

- 转换依据:links 数组建立连接;widget 值按 object_info 中非连接型 input 的
  声明顺序消费 widgets_values(与 ComfyUI 前端渲染顺序一致)。
- 已知特例:upload(IMAGEUPLOAD 按钮占位)不消费;widgets_values 末尾多出的
  纯文本值视为 seed 控制项(randomize 等)丢弃并给出警告。
- 草稿推断只做特征匹配(LoadImage/生成节点/Text/SaveVideo),结果必须人工核对。
"""
from __future__ import annotations

from typing import Any

# UI 图中的纯装饰/路由节点,不进入 API Format
SKIP_NODE_TYPES = {"MarkdownNote", "Note", "Reroute", "PrimitiveNode"}

# 生成参数类字段:凡节点存在同名输入即视为候选
GEN_FIELDS = ("prompt", "negative_prompt", "width", "height", "fps", "num_frames")


def _is_link_socket(defn: Any) -> bool:
    """object_info 中连接型输入形如 ["IMAGE"]/["REMOTE_LORA"](单元素全大写类型名);
    widget 型形如 ["INT",{...}]/["a.png","b.png"]。"""
    if not isinstance(defn, (list, tuple)) or not defn:
        return False
    first = defn[0]
    return (
        isinstance(first, str)
        and len(defn) == 1
        and first.upper() == first
        and not first.isdigit()
    )


def convert_ui_to_api(ui: dict, object_info: dict) -> tuple[dict, list[str]]:
    """把 UI 格式工作流转换为 API Format;返回 (api_workflow, warnings)。"""
    warnings: list[str] = []
    links_by_id = {link[0]: link for link in ui.get("links") or []}
    api: dict[str, Any] = {}

    for node in ui.get("nodes") or []:
        ntype = node.get("type", "")
        if ntype in SKIP_NODE_TYPES:
            continue
        info = (object_info or {}).get(ntype)
        if not isinstance(info, dict) or not isinstance(info.get("input"), dict):
            warnings.append(
                f"节点 {node.get('id')}({ntype}) 不在 ComfyUI object_info 中,已跳过,其下游连接将缺失"
            )
            continue

        node_def: dict[str, Any] = {"class_type": ntype, "inputs": {}}
        if node.get("title"):
            node_def["_meta"] = {"title": node["title"]}

        inputs_def: dict[str, Any] = {}
        for group in ("required", "optional"):
            inputs_def.update((info["input"].get(group) or {}))
        widget_keys = [
            key for key, defn in inputs_def.items()
            if key != "upload" and not _is_link_socket(defn)
        ]
        ui_inputs = {i.get("name"): i.get("link") for i in node.get("inputs") or []}

        widgets = list(node.get("widgets_values") or [])
        for key in widget_keys:
            if ui_inputs.get(key) is not None:
                continue  # 该输入已由连接提供
            if not widgets:
                break  # 未提供时留空,ComfyUI 按默认值处理
            node_def["inputs"][key] = widgets.pop(0)
        if widgets and all(isinstance(w, str) for w in widgets):
            warnings.append(
                f"节点 {node.get('id')}({ntype}) 忽略末尾 {len(widgets)} 个疑似控制项的值:{widgets}"
            )

        for name, link_id in ui_inputs.items():
            if link_id is None:
                continue
            link = links_by_id.get(link_id)
            if link:
                node_def["inputs"][name] = [str(link[1]), link[2]]
        api[str(node["id"])] = node_def

    if not api:
        warnings.append("转换结果为空:没有可用节点")
    return api, warnings


def draft_map(api: dict) -> dict:
    """按节点特征推断 workflow-map 结构(草稿,必须人工核对后使用)。"""
    nodes: dict[str, dict[str, str]] = {}
    for nid, node_def in api.items():
        ntype = node_def.get("class_type", "")
        inputs = node_def.get("inputs") or {}
        if ntype == "LoadImage" and "image" in inputs:
            nodes.setdefault("image", {"id": nid, "input": "image"})
        if ntype in ("SaveVideo", "SaveImage") and "filename_prefix" in inputs:
            nodes.setdefault("save", {"id": nid, "input": "filename_prefix"})
        if ntype == "Text" and "text" in inputs:
            nodes.setdefault("speech", {"id": nid, "input": "text"})
        for field in GEN_FIELDS:
            if field in inputs:
                nodes.setdefault(field, {"id": nid, "input": field})
        if "seed" in inputs:
            nodes.setdefault("seed", {"id": nid, "input": "seed"})
    return {"name": "", "nodes": nodes}
