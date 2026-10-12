"""pytest 公共夹具:在导入 app 前设置临时数据目录,隔离测试数据。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

_TMP_DATA = tempfile.mkdtemp(prefix="poem_video_test_")
os.environ["DATA_ROOT"] = _TMP_DATA
os.environ["WORKFLOW_TEMPLATE"] = str(BACKEND_DIR.parent / "workflows" / "minimax_h3_poem_v1.json")
os.environ["WORKFLOW_MAP"] = str(BACKEND_DIR.parent / "workflows" / "workflow-map.yaml")
os.environ["COMFYUI_BASE_URL"] = "http://127.0.0.1:18188"
os.environ["COMFYUI_WS_URL"] = "ws://127.0.0.1:18188/ws"

import pytest  # noqa: E402


@pytest.fixture()
def sample_batch_text() -> str:
    return """POEM_VIDEO_BATCH_V1

title: 宿建德江
dynasty: 唐
author: 孟浩然

[GLOBAL]
width: 768
height: 1024
fps: 24
num_frames: 121

negative_prompt:
文字变形,文字模糊,文字漂移,画面闪烁,主体扭曲,镜头剧烈晃动

[SCENE:cover]
speech: 宿建德江,唐,孟浩然。
prompt:
水墨风格封面,江面晨雾,标题文字保持清晰稳定,
整体画面安静克制,轻微雾气流动。

[SCENE:1]
speech: 移舟,泊烟渚。
prompt:
一叶扁舟缓缓停靠烟雾迷蒙的小洲,水面微波荡漾,
船夫撑篙动作轻缓,远山朦胧。

[SCENE:2]
speech: 日暮,客愁新。
prompt:
黄昏落日,旅人独立船头眺望远方,衣摆随风轻摆,
天边云霞缓慢流动,水面泛起金色波光。

[SCENE:3]
speech: 野旷,天低树。
prompt:
旷野辽阔,远树低垂,天地相接,薄雾缓缓飘动,
镜头轻微推移,层次分明。

[SCENE:4]
speech: 江清,月近人。
prompt:
夜色澄澈,明月倒映江中,波光粼粼,
月光随水波轻轻晃动,静谧安详。
"""
