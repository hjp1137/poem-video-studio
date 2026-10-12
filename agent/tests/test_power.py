"""Power Limit 校验、执行与 gpu-power.json 配置测试。"""
from __future__ import annotations

import json

from app.services import power


def test_set_power_limit_success(monkeypatch, fake_gpus):
    state = {"query": 0, "set_argv": None}

    def fake_list_gpus():
        state["query"] += 1
        return fake_gpus(power_limit=300 if state["query"] == 1 else 280)

    monkeypatch.setattr(power.nvidia, "list_gpus", fake_list_gpus)

    def fake_run(argv, **kwargs):
        state["set_argv"] = argv
        assert kwargs.get("sudo") is False  # 测试环境 AGENT_USE_SUDO=0
        class P:
            returncode = 0
            stdout = "Power limit for GPU 2 was set to 280 W"
            stderr = ""
        return P()

    monkeypatch.setattr(power, "run", fake_run)
    result = power.set_power_limit(2, 280)
    assert result["before_watts"] == 300
    assert result["requested_watts"] == 280
    assert result["after_watts"] == 280
    # 受控命令:nvidia-smi -i 2 -pl 280,参数数组、无 shell
    assert state["set_argv"] == ["nvidia-smi", "-i", "2", "-pl", "280"]


def test_set_power_limit_below_min(monkeypatch, fake_gpus):
    monkeypatch.setattr(power.nvidia, "list_gpus", lambda: fake_gpus())
    try:
        power.set_power_limit(0, 50)
        raise AssertionError("应当拒绝低于 min")
    except power.PowerError as exc:
        assert "超出驱动允许区间 [100W, 450W]" in str(exc)


def test_set_power_limit_above_max(monkeypatch, fake_gpus):
    monkeypatch.setattr(power.nvidia, "list_gpus", lambda: fake_gpus())
    try:
        power.set_power_limit(0, 500)
        raise AssertionError("应当拒绝高于 max")
    except power.PowerError as exc:
        assert "500W 超出" in str(exc)


def test_set_power_limit_invalid_index(monkeypatch, fake_gpus):
    monkeypatch.setattr(power.nvidia, "list_gpus", lambda: fake_gpus())
    try:
        power.set_power_limit(9, 280)
        raise AssertionError("应当拒绝非法 index")
    except power.PowerError as exc:
        assert "GPU index 9 不存在" in str(exc)


def test_set_power_limit_no_range_reported(monkeypatch, fake_gpus):
    gpus = fake_gpus()
    for g in gpus:
        g["min_power_limit_w"] = None
        g["max_power_limit_w"] = None
    monkeypatch.setattr(power.nvidia, "list_gpus", lambda: gpus)
    try:
        power.set_power_limit(0, 280)
        raise AssertionError("驱动未上报区间时必须拒绝盲设")
    except power.PowerError as exc:
        assert "未上报功耗区间" in str(exc)


def test_config_roundtrip_atomic(config_dir):
    path = config_dir / "gpu-power.json"
    power.save_config(power.GpuPowerConfig(enabled=True, default_power_limit=280, per_gpu={"3": 250}), path)
    loaded = power.load_config(path)
    assert loaded.to_dict() == {"enabled": True, "default_power_limit": 280, "per_gpu": {"3": 250}}
    # 原子写入不留临时文件
    assert [p.name for p in config_dir.iterdir()] == ["gpu-power.json"]


def test_config_corrupt_json_raises_not_crash(config_dir):
    path = config_dir / "gpu-power.json"
    path.write_text("{ not valid json", encoding="utf-8")
    try:
        power.load_config(path)
        raise AssertionError("非法 JSON 必须报配置错误")
    except power.PowerConfigError as exc:
        assert "解析失败" in str(exc)


def test_config_invalid_schema(config_dir):
    path = config_dir / "gpu-power.json"
    path.write_text(json.dumps({"enabled": "yes", "default_power_limit": -5}), encoding="utf-8")
    try:
        power.load_config(path)
        raise AssertionError("非法字段必须报配置错误")
    except power.PowerConfigError:
        pass


def test_apply_config_per_gpu_and_partial_failure(monkeypatch, fake_gpus, tmp_path):
    calls = []

    def fake_list_gpus():
        # GPU1 已是目标值 250;其余当前 300 需要设置
        gpus = fake_gpus(power_limit=300)
        gpus[1]["power_limit_w"] = 250
        return gpus

    monkeypatch.setattr(power.nvidia, "list_gpus", fake_list_gpus)

    def fake_set(index, watts):
        calls.append((index, watts))
        if index == 3:  # 模拟最后一张卡设置失败
            raise power.PowerError(f"GPU {index} 功耗 250W 超出驱动允许区间 [100W, 450W]")
        return {"index": index, "before_watts": 280, "requested_watts": watts, "after_watts": watts}

    monkeypatch.setattr(power, "set_power_limit", fake_set)
    cfg_path = tmp_path / "gpu-power.json"
    cfg_path.write_text(json.dumps({
        "enabled": True, "default_power_limit": 280, "per_gpu": {"1": 250, "3": 250},
    }), encoding="utf-8")
    outcome = power.apply_config(cfg_path)
    # GPU0/2 走默认 280;GPU1 已是 250 → already;GPU3 设置失败被记录
    assert {a["index"] for a in outcome["applied"]} == {0, 1, 2}
    already = {a["index"]: a["already"] for a in outcome["applied"]}
    assert already == {0: False, 1: True, 2: False}
    assert calls == [(0, 280), (2, 280), (3, 250)]  # 已正确的 GPU1 不重设;GPU3 尝试后失败
    assert [f["index"] for f in outcome["failed"]] == [3]


def test_apply_config_disabled_is_noop(tmp_path):
    cfg_path = tmp_path / "gpu-power.json"
    cfg_path.write_text(json.dumps({"enabled": False, "default_power_limit": 280}), encoding="utf-8")
    outcome = power.apply_config(cfg_path)
    assert outcome["applied"] == [] and outcome["failed"] == []
