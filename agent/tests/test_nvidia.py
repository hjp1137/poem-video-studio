"""nvidia-smi 采集解析测试(mock runner.run,不依赖真实 GPU)。"""
from __future__ import annotations

from app.services import nvidia
from app.services.runner import CommandError


def _gpu_csv_rows(with_limits: bool) -> str:
    """与 --format=csv,noheader,nounits 对应:基础 11 列,可选追加功耗区间 2 列。"""
    rows = [
        "0, GPU-aaaa-bbbb-0000, NVIDIA GeForce RTX 4090, 66, 82, 21340, 24564, 266, 280, P2, 43",
        "1, GPU-aaaa-bbbb-0001, NVIDIA GeForce RTX 4090, 61, 0, 1024, 24564, 88, 280, P8, 35",
    ]
    suffix = ", 100, 450" if with_limits else ""
    return "\n".join(row + suffix for row in rows) + "\n"


def test_list_gpus_parses_csv(monkeypatch):
    monkeypatch.setattr(nvidia, "run", lambda argv, **kw: type("P", (), {
        "returncode": 0, "stdout": _gpu_csv_rows(True), "stderr": "",
    })())
    gpus = nvidia.list_gpus()
    assert len(gpus) == 2
    g0 = gpus[0]
    assert g0["index"] == 0 and g0["name"] == "NVIDIA GeForce RTX 4090"
    assert g0["temperature_c"] == 66 and g0["utilization_gpu_percent"] == 82
    assert g0["memory_used_mib"] == 21340 and g0["memory_total_mib"] == 24564
    assert g0["power_draw_w"] == 266 and g0["power_limit_w"] == 280
    assert g0["min_power_limit_w"] == 100 and g0["max_power_limit_w"] == 450
    assert g0["pstate"] == "P2" and g0["fan_speed_percent"] == 43
    assert g0["processes"] == []


def test_list_gpus_fallback_without_limit_fields(monkeypatch):
    """旧驱动不认识 power.min_limit/max_limit:应降级重试,区间字段为 null。"""
    state = {"calls": 0}

    def fake_run(argv, **kwargs):
        state["calls"] += 1
        has_limits = "power.min_limit" in argv[1]
        if has_limits and state["calls"] == 1:
            raise CommandError(argv, "退出码 1:Field \"power.min_limit\" is not a valid field")
        return type("P", (), {
            "returncode": 0, "stdout": _gpu_csv_rows(has_limits), "stderr": "",
        })()

    monkeypatch.setattr(nvidia, "run", fake_run)
    gpus = nvidia.list_gpus()
    assert state["calls"] == 2
    assert gpus[0]["min_power_limit_w"] is None and gpus[0]["max_power_limit_w"] is None
    assert gpus[0]["power_limit_w"] == 280  # 基础字段仍可用


def test_na_values_return_none(monkeypatch):
    def fake_run(argv, **kwargs):
        class P:
            returncode = 0
            stdout = "0, GPU-x, RTX 4090, [N/A], 0, 1024, 24564, [N/A], 280, P8, [N/A]\n"
            stderr = ""
        return P()

    monkeypatch.setattr(nvidia, "run", fake_run)
    g0 = nvidia.list_gpus()[0]
    assert g0["temperature_c"] is None and g0["power_draw_w"] is None
    assert g0["fan_speed_percent"] is None


def test_compute_processes_attach_by_uuid(monkeypatch):
    def fake_query_gpus(fields):
        class P:
            returncode = 0
            stdout = "0, GPU-aaaa-bbbb-0000, RTX 4090, 66, 82, 21340, 24564, 266, 280, P2, 43\n"
            stderr = ""
        return P()

    def fake_run(argv, **kwargs):
        if "--query-compute-apps" in argv[1]:
            class P:
                returncode = 0
                stdout = "GPU-aaaa-bbbb-0000, 12345, python, 20134\nGPU-aaaa-bbbb-0000, 12346, \"python,comm\", 512\n"
                stderr = ""
            return P()
        return fake_query_gpus(None)

    monkeypatch.setattr(nvidia, "run", fake_run)
    gpus = nvidia.gpus_with_processes()
    assert len(gpus[0]["processes"]) == 2
    p0 = gpus[0]["processes"][0]
    assert p0["pid"] == 12345 and p0["used_gpu_memory_mib"] == 20134
    # 含逗号的进程名走 CSV 引号,不应被切断
    assert gpus[0]["processes"][1]["process_name"] == "python,comm"


def test_no_running_processes_returns_empty(monkeypatch):
    def fake_run(argv, **kwargs):
        raise CommandError(argv, "退出码 6:No running processes found")

    monkeypatch.setattr(nvidia, "run", fake_run)
    assert nvidia.list_compute_processes() == []


def test_nvidia_failure_raises(monkeypatch):
    def fake_run(argv, **kwargs):
        raise CommandError(argv, "超时(15s)")

    monkeypatch.setattr(nvidia, "run", fake_run)
    try:
        nvidia.list_gpus()
        raise AssertionError("应当抛出 NvidiaError")
    except nvidia.NvidiaError as exc:
        assert "超时" in str(exc)
