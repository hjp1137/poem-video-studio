"""POEM_VIDEO_BATCH_V1 批量任务文本解析器。

格式示例见 docs/ 总体设计方案 6.3 节。解析规则:

- 首个非空行必须为 POEM_VIDEO_BATCH_V1。
- 头部支持 title / dynasty / author 单行键值。
- [GLOBAL] 可缺省,支持 width/height/fps/num_frames 单行整数与 negative_prompt 多行。
- [SCENE:cover] 可选,[SCENE:1..N] 数量不限,支持 speech / prompt(prompt 支持多行)。
- 多行值:key: 后不接内容时,后续行持续收集,直到下一个「当前节已知 key」行或节标题。
- speech / prompt / negative_prompt 一律原样保留,不做任何改写。
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field

BATCH_HEADER = "POEM_VIDEO_BATCH_V1"

HEADER_KEYS = ("title", "dynasty", "author")
GLOBAL_INT_KEYS = ("width", "height", "fps", "num_frames")
GLOBAL_KEYS = GLOBAL_INT_KEYS + ("negative_prompt",)
SCENE_KEYS = ("speech", "prompt")

SECTION_RE = re.compile(r"^\[(GLOBAL|SCENE:[^\]]+)\]$")
SCENE_RE = re.compile(r"^SCENE:(.+)$")
KEY_VALUE_RE = re.compile(r"^([a-zA-Z_]+)\s*:\s?(.*)$")

# 合法参数范围(仅做合法性兜底,不限制正常创作取值)
GLOBAL_INT_RANGES = {
    "width": (64, 8192),
    "height": (64, 8192),
    "fps": (1, 240),
    "num_frames": (1, 4096),
}


class ParsedScene(BaseModel):
    scene_key: str
    scene_order: int
    speech: str
    prompt: str


class ParsedGlobal(BaseModel):
    width: int | None = None
    height: int | None = None
    fps: int | None = None
    num_frames: int | None = None
    negative_prompt: str = ""


class ParsedMetadata(BaseModel):
    title: str = ""
    dynasty: str = ""
    author: str = ""


class ParseResult(BaseModel):
    version: str = BATCH_HEADER
    metadata: ParsedMetadata = ParsedMetadata()
    global_config: ParsedGlobal = Field(default_factory=ParsedGlobal, alias="global")
    scenes: list[ParsedScene] = []
    warnings: list[str] = []
    errors: list[str] = []
    ok: bool = False

    model_config = {"populate_by_name": True}


class BatchParseError(Exception):
    """携带 errors 列表的解析异常,供 API 层转换为 422。"""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _known_keys(section: str) -> tuple[str, ...]:
    if section == "header":
        return HEADER_KEYS
    if section == "GLOBAL":
        return GLOBAL_KEYS
    return SCENE_KEYS


def _clean_multiline(lines: list[str]) -> str:
    """去掉首尾空行,保留中间空行;行尾空白去除。"""
    text = "\n".join(line.rstrip() for line in lines)
    return text.strip("\n").strip()


def parse_batch_text(raw: str) -> ParseResult:
    result = ParseResult()
    if raw is None:
        raw = ""
    lines = raw.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    # 定位首个非空行,校验版本头
    start = 0
    for i, line in enumerate(lines):
        if line.strip():
            start = i
            break
    else:
        result.errors.append("批量文本为空")
        return result

    if lines[start].strip() != BATCH_HEADER:
        result.errors.append(f"首个非空行必须为 {BATCH_HEADER},当前为:{lines[start].strip()[:40]}")
        return result

    section = "header"          # header / GLOBAL / scene:<key>
    current_scene: dict | None = None
    scenes: list[dict] = []
    collecting_key: str | None = None   # 正在收集的多行字段
    collecting_lines: list[str] = []
    global_values: dict[str, str] = {}

    def finish_collection() -> None:
        nonlocal collecting_key, collecting_lines
        if collecting_key is None:
            return
        value = _clean_multiline(collecting_lines)
        if section == "GLOBAL" and collecting_key == "negative_prompt":
            global_values["negative_prompt"] = value
        elif current_scene is not None and collecting_key in SCENE_KEYS:
            existing = current_scene.get(collecting_key, "")
            current_scene[collecting_key] = f"{existing}\n{value}".strip() if existing else value
        collecting_key = None
        collecting_lines = []

    i = start + 1
    while i < len(lines):
        raw_line = lines[i]
        line = raw_line.strip()
        lineno = i + 1

        if collecting_key is not None and not (line and _line_starts_known_key(line, section, SECTION_RE)):
            # 多行值内部:节标题或当前节已知 key 才会终止收集
            collecting_lines.append(raw_line)
            i += 1
            continue

        if not line:
            i += 1
            continue

        m = SECTION_RE.match(line)
        if m:
            finish_collection()
            if m.group(1) == "GLOBAL":
                section = "GLOBAL"
                current_scene = None
            else:
                key = SCENE_RE.match(m.group(1)).group(1).strip()
                current_scene = {"scene_key": key, "speech": "", "prompt": "", "line": lineno}
                scenes.append(current_scene)
                section = "scene"
            i += 1
            continue

        km = KEY_VALUE_RE.match(line)
        if km and km.group(1) in _known_keys("header" if section == "header" else ("GLOBAL" if section == "GLOBAL" else "scene")):
            key, value = km.group(1), km.group(2).strip()
            if collecting_key is not None:
                finish_collection()
            if section == "header":
                setattr(result.metadata, key if key in HEADER_KEYS else "title", value)
            elif section == "GLOBAL":
                if key in GLOBAL_INT_KEYS:
                    global_values[key] = value
                else:
                    if value:
                        global_values["negative_prompt"] = value
                    else:
                        collecting_key, collecting_lines = "negative_prompt", []
            elif current_scene is not None:
                if value:
                    current_scene[key] = value
                else:
                    collecting_key, collecting_lines = key, []
            i += 1
            continue

        # 未识别行
        if section == "header":
            result.warnings.append(f"第 {lineno} 行:头部无法识别的内容「{line[:30]}」")
        elif section == "GLOBAL":
            result.warnings.append(f"第 {lineno} 行:[GLOBAL] 中无法识别的内容「{line[:30]}」")
        else:
            result.warnings.append(f"第 {lineno} 行:[SCENE:{current_scene['scene_key'] if current_scene else '?'}] 中无法识别的内容「{line[:30]}」")
        i += 1

    finish_collection()

    _validate_and_assemble(result, global_values, scenes)
    return result


def _line_starts_known_key(line: str, section: str, section_re) -> bool:
    if section_re.match(line):
        return True
    km = KEY_VALUE_RE.match(line)
    if not km:
        return False
    return km.group(1) in _known_keys(section)


def _validate_and_assemble(result: ParseResult, global_values: dict, scenes: list[dict]) -> None:
    # ---- 全局参数 ----
    g = ParsedGlobal()
    for key in GLOBAL_INT_KEYS:
        if key not in global_values:
            continue
        raw_val = global_values[key]
        try:
            val = int(raw_val)
        except (TypeError, ValueError):
            result.errors.append(f"[GLOBAL] {key} 必须是整数,当前为「{raw_val}」")
            continue
        low, high = GLOBAL_INT_RANGES[key]
        if not (low <= val <= high):
            result.errors.append(f"[GLOBAL] {key} 取值 {val} 超出合法范围 [{low}, {high}]")
            continue
        setattr(g, key, val)
    g.negative_prompt = global_values.get("negative_prompt", "")
    result.global_config = g

    # ---- 场景校验 ----
    seen: dict[str, int] = {}
    for sc in scenes:
        key = sc["scene_key"]
        if key in seen:
            result.errors.append(f"scene key 重复:[SCENE:{key}](第 {seen[key]} 行与第 {sc['line']} 行)")
            continue
        seen[key] = sc["line"]
        if key != "cover" and not key.isdigit():
            result.errors.append(f"非法 scene key「{key}」:必须为 cover 或正整数编号")
        if not sc["prompt"].strip():
            result.errors.append(f"[SCENE:{key}] 缺少 prompt")
        if not sc["speech"].strip():
            result.errors.append(f"[SCENE:{key}] 缺少 speech")

    if not scenes:
        result.errors.append("空批次:未发现任何 [SCENE:*] 段")

    # ---- 编号连续性(明确提示,不阻断) ----
    numbers = sorted({int(k) for k in seen if k.isdigit()})
    if numbers:
        missing = sorted(set(range(1, max(numbers) + 1)) - set(numbers))
        if missing:
            result.warnings.append(
                "场景编号断裂:缺少编号 " + "、".join(str(n) for n in missing) + "(请确认是否遗漏场景)"
            )

    # ---- 排序:cover → 数字升序 ----
    def order_of(item: dict) -> tuple[int, int]:
        key = item["scene_key"]
        return (0, 0) if key == "cover" else (1, int(key) if key.isdigit() else 1)

    ordered = sorted(scenes, key=order_of)
    result.scenes = [
        ParsedScene(scene_key=sc["scene_key"], scene_order=idx, speech=sc["speech"], prompt=sc["prompt"])
        for idx, sc in enumerate(ordered)
        if sc["scene_key"] in seen and seen[sc["scene_key"]] == sc["line"]
    ]

    # ---- 元数据提示 ----
    if not result.metadata.title:
        result.warnings.append("未提供 title,创建批次时请在表单中补齐诗词名称")

    result.ok = not result.errors


# 批量任务文本模板:与上述解析规则严格一致,供页面下载后编辑。
# 任何格式调整必须同步修改本模板,测试会校验模板始终可被本解析器接受。
BATCH_TEXT_TEMPLATE = """POEM_VIDEO_BATCH_V1
title: 宿建德江
dynasty: 唐
author: 孟浩然

[GLOBAL]
width: 768
height: 1024
fps: 24
num_frames: 121
negative_prompt:
模糊,低质量,变形的手部,多余肢体,文字水印,噪点
过曝,画面撕裂,比例失调

[SCENE:cover]
speech: 宿建德江,唐,孟浩然。
prompt:
中国水墨风格封面,一叶小舟停泊在暮色中的江渚旁,
远山如黛,江面雾气缭绕,留白构图,题款位于右上角

[SCENE:1]
speech: 移舟泊烟渚,日暮客愁新。
prompt:
黄昏江面,一叶小舟缓缓靠向烟雾朦胧的小洲,
夕阳西沉,旅人独坐船头神情惆怅,暖橙色天光与青灰江水对比

[SCENE:2]
speech: 野旷天低树,江清月近人。
prompt:
空旷原野尽头天幕低垂与远树相接,
清澈江面倒映一轮明月,小舟上的旅人抬头望月,静谧清冷
"""
