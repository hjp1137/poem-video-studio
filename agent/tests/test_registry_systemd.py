"""服务注册表与 systemd 封装测试。"""
from __future__ import annotations

import textwrap

import pytest

from app.services import registry, systemd


def _write_services(config_dir, content: str):
    (config_dir / "services.yaml").write_text(textwrap.dedent(content), encoding="utf-8")


VALID_SERVICES = """\
    services:
      minimax_h3:
        display_name: MiniMax H3
        manager: systemd
        unit: minimax-h3.service
        health:
          type: http
          url: http://127.0.0.1:8001/v1/models
          timeout: 3
      comfyui:
        display_name: ComfyUI
        manager: systemd
        unit: comfyui.service
        health:
          type: http
          url: http://127.0.0.1:8188/system_stats
    """


def test_registry_parse(config_dir):
    _write_services(config_dir, VALID_SERVICES)
    services = registry.load_services()
    assert set(services) == {"minimax_h3", "comfyui"}
    assert services["minimax_h3"].unit == "minimax-h3.service"
    assert services["comfyui"].health.timeout == 3.0


def test_registry_missing_file(config_dir):
    with pytest.raises(registry.RegistryError):
        registry.load_services()


def test_registry_rejects_unknown_service(config_dir):
    _write_services(config_dir, VALID_SERVICES)
    with pytest.raises(registry.RegistryError, match="未在注册表登记"):
        registry.resolve("nginx")


def test_registry_rejects_bad_unit_chars(config_dir):
    _write_services(config_dir, """\
        services:
          evil:
            display_name: x
            manager: systemd
            unit: "a.service; rm -rf /"
            health: {type: none}
        """)
    with pytest.raises(registry.RegistryError, match="非法字符"):
        registry.load_services()


def test_registry_rejects_unsupported_manager(config_dir):
    _write_services(config_dir, """\
        services:
          x:
            display_name: x
            manager: docker
            unit: some-container
            health: {type: none}
        """)
    with pytest.raises(registry.RegistryError, match="暂不支持"):
        registry.load_services()


def _show_output(active="active", sub="running", load="loaded", pid="12345", msec="1700000000000"):
    return (
        f"LoadState={load}\nActiveState={active}\nSubState={sub}\n"
        f"MainPID={pid}\nExecMainStartTimestampMsec={msec}\n"
    )


@pytest.mark.parametrize(
    "active,sub,expected",
    [
        ("active", "running", "running"),
        ("active", "auto-restart", "activating"),
        ("activating", "start", "activating"),
        ("deactivating", "stop", "deactivating"),
        ("inactive", "dead", "stopped"),
        ("failed", "failed", "failed"),
        ("active", "dead", "unknown"),
    ],
)
def test_process_state_mapping(monkeypatch, active, sub, expected):
    def fake_run(argv, **kwargs):
        class P:
            returncode = 0
            stdout = _show_output(active=active, sub=sub)
            stderr = ""
        return P()

    monkeypatch.setattr(systemd, "run", fake_run)
    assert systemd.process_state("minimax-h3.service") == expected


def test_process_state_unit_not_found(monkeypatch):
    def fake_run(argv, **kwargs):
        class P:
            returncode = 0
            stdout = _show_output(load="not-found")
            stderr = ""
        return P()

    monkeypatch.setattr(systemd, "run", fake_run)
    assert systemd.process_state("nope.service") == "unknown"


def test_service_action_fixed_argv(monkeypatch):
    argv_seen = {}

    def fake_run(argv, **kwargs):
        argv_seen["argv"] = argv
        argv_seen["sudo"] = kwargs.get("sudo")
        class P:
            returncode = 0
            stdout = ""
            stderr = ""
        return P()

    monkeypatch.setattr(systemd, "run", fake_run)
    systemd.service_action("minimax-h3.service", "restart")
    assert argv_seen["argv"] == ["systemctl", "restart", "minimax-h3.service"]
    assert argv_seen["sudo"] is False  # AGENT_USE_SUDO=0


def test_service_action_rejects_bad_verb():
    with pytest.raises(systemd.SystemdError, match="非法动词"):
        systemd.service_action("minimax-h3.service", "mask")


def test_logs_clamp_lines(monkeypatch):
    argv_seen = {}

    def fake_run(argv, **kwargs):
        argv_seen["argv"] = argv
        class P:
            returncode = 0
            stdout = "\n".join(f"line {i}" for i in range(1000))
            stderr = ""
        return P()

    monkeypatch.setattr(systemd, "run", fake_run)
    logs = systemd.service_logs("comfyui.service", 999999)  # 超上限被收敛到 1000
    assert argv_seen["argv"] == [
        "journalctl", "-u", "comfyui.service", "-n", "1000", "--no-pager", "-o", "short-iso",
    ]
    assert len(logs) == 1000


class _FakeHttpxClient:
    """health 检查用的假 httpx.Client。"""

    status_code = 200

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        class R:
            status_code = _FakeHttpxClient.status_code
        return R()


def test_health_state_layers(monkeypatch, config_dir):
    _write_services(config_dir, VALID_SERVICES)
    service = registry.resolve("minimax_h3")
    monkeypatch.setattr(systemd.httpx, "Client", _FakeHttpxClient)

    assert systemd.health_state(service, "running") == "healthy"
    assert systemd.health_state(service, "activating") == "starting"
    assert systemd.health_state(service, "stopped") == "unknown"

    _FakeHttpxClient.status_code = 503
    assert systemd.health_state(service, "running") == "unhealthy"  # active 不等于 Ready

    import httpx as real_httpx

    class _DeadClient:
        def __init__(self, *a, **k):
            raise real_httpx.ConnectError("refused")

    monkeypatch.setattr(systemd.httpx, "Client", _DeadClient)
    assert systemd.health_state(service, "running") == "unhealthy"
