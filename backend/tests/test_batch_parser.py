"""batch_parser 单元测试:覆盖任务01 §12 要求的全部场景。"""
from __future__ import annotations

from app.services.batch_parser import parse_batch_text


def _scenes_text(n: int, start: int = 1) -> str:
    scenes = "\n\n".join(
        f"[SCENE:{i}]\nspeech: 第{i}句。\nprompt: 第{i}句画面。" for i in range(start, start + n)
    )
    return f"POEM_VIDEO_BATCH_V1\n\ntitle: 测试\ndynasty: 唐\nauthor: 测试\n\n{scenes}\n"


def test_standard_4_scene_quatrain():
    result = parse_batch_text(_scenes_text(4))
    assert result.ok, result.errors
    assert [s.scene_key for s in result.scenes] == ["1", "2", "3", "4"]
    assert [s.scene_order for s in result.scenes] == [0, 1, 2, 3]
    assert result.metadata.title == "测试"


def test_5_scenes_with_cover(sample_batch_text):
    result = parse_batch_text(sample_batch_text)
    assert result.ok, result.errors
    assert len(result.scenes) == 5
    assert result.scenes[0].scene_key == "cover"
    assert result.scenes[0].scene_order == 0
    assert [s.scene_key for s in result.scenes[1:]] == ["1", "2", "3", "4"]
    assert result.global_config.width == 768
    assert result.global_config.num_frames == 121


def test_without_cover():
    result = parse_batch_text(_scenes_text(2))
    assert result.ok, result.errors
    assert [s.scene_key for s in result.scenes] == ["1", "2"]


def test_8_scene_regulated_verse():
    result = parse_batch_text(_scenes_text(8))
    assert result.ok, result.errors
    assert len(result.scenes) == 8
    assert result.scenes[-1].scene_key == "8"


def test_multiline_prompt_preserved(sample_batch_text):
    result = parse_batch_text(sample_batch_text)
    cover = result.scenes[0]
    assert "水墨风格封面" in cover.prompt
    assert "整体画面安静克制" in cover.prompt
    assert "\n" in cover.prompt  # 多行被完整保留


def test_multiline_negative_prompt():
    text = (
        "POEM_VIDEO_BATCH_V1\n\n[GLOBAL]\nnegative_prompt:\n第一行反向\n第二行反向\n\n"
        "[SCENE:1]\nspeech: 一句。\nprompt: 画面。\n"
    )
    result = parse_batch_text(text)
    assert result.ok, result.errors
    assert result.global_config.negative_prompt == "第一行反向\n第二行反向"


def test_duplicate_scene_key():
    text = _scenes_text(1) + "\n[SCENE:1]\nspeech: 重复。\nprompt: 重复画面。\n"
    result = parse_batch_text(text)
    assert not result.ok
    assert any("重复" in e for e in result.errors)


def test_scene_number_gap_warning():
    text = _scenes_text(1) + "\n[SCENE:3]\nspeech: 第三句。\nprompt: 画面。\n"
    result = parse_batch_text(text)
    assert result.ok  # 断裂是明确提示,不阻断
    assert any("断裂" in w and "2" in w for w in result.warnings), result.warnings


def test_missing_prompt():
    text = "POEM_VIDEO_BATCH_V1\n\n[SCENE:1]\nspeech: 一句。\n"
    result = parse_batch_text(text)
    assert not result.ok
    assert any("[SCENE:1]" in e and "prompt" in e for e in result.errors)


def test_missing_speech():
    text = "POEM_VIDEO_BATCH_V1\n\n[SCENE:2]\nprompt: 画面。\n"
    result = parse_batch_text(text)
    assert not result.ok
    assert any("[SCENE:2]" in e and "speech" in e for e in result.errors)


def test_invalid_global_params():
    text = (
        "POEM_VIDEO_BATCH_V1\n\n[GLOBAL]\nwidth: abc\nheight: -5\nfps: 0\nnum_frames: 3.5\n\n"
        "[SCENE:1]\nspeech: 一句。\nprompt: 画面。\n"
    )
    result = parse_batch_text(text)
    assert not result.ok
    assert len(result.errors) == 4, result.errors


def test_wrong_version_header():
    result = parse_batch_text("POEM_VIDEO_BATCH_V2\n\n[SCENE:1]\nspeech: a。\nprompt: b。\n")
    assert not result.ok
    assert any("POEM_VIDEO_BATCH_V1" in e for e in result.errors)


def test_empty_text():
    result = parse_batch_text("   \n\n")
    assert not result.ok
    assert any("为空" in e for e in result.errors)


def test_empty_batch_no_scenes():
    result = parse_batch_text("POEM_VIDEO_BATCH_V1\n\ntitle: 无场景\n")
    assert not result.ok
    assert any("空批次" in e for e in result.errors)


def test_global_optional_defaults():
    text = "POEM_VIDEO_BATCH_V1\n\n[SCENE:1]\nspeech: 一句。\nprompt: 画面。\n"
    result = parse_batch_text(text)
    assert result.ok
    assert result.global_config.width is None  # 缺省由配置默认值兜底


def test_speech_prompt_not_rewritten(sample_batch_text):
    result = parse_batch_text(sample_batch_text)
    scene1 = result.scenes[1]
    assert scene1.speech == "移舟,泊烟渚。"
    assert scene1.prompt.startswith("一叶扁舟缓缓停靠烟雾迷蒙的小洲")


def test_template_is_parseable():
    """页面下载的模板必须始终可被解析器接受,防止模板与解析规则脱节。"""
    from app.services.batch_parser import BATCH_TEXT_TEMPLATE

    result = parse_batch_text(BATCH_TEXT_TEMPLATE)
    assert result.ok, result.errors
    assert not result.errors
    assert [s.scene_key for s in result.scenes] == ["cover", "1", "2"]
    assert result.metadata.title == "宿建德江"
    assert result.global_config.width == 768
    assert result.global_config.negative_prompt.startswith("模糊")
