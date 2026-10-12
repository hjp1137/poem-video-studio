"""GPU 工作负载检测/停止测试(mock nvidia-smi、/proc、docker ps)。"""
from __future__ import annotations

import pytest

from app.services import workloads

DOCKER_PS_OUTPUT = (
    "a1b2c3d4e5f6\tmagic-pdf-server\n"
    "f6e5d4c3b2a1\tbge-m3-server\n"
    "0123456789ab\tollama-server\n"
)


def _install_proc_mock(monkeypatch, cgroups: dict[int, str], cmdlines: dict[int, str] | None = None):
    cmdlines = cmdlines or {}

    def fake_cgroup(pid):
        return cgroups.get(pid, "")

    def fake_cmdline(pid):
        return cmdlines.get(pid, f"/usr/bin/app-{pid}")

    monkeypatch.setattr(workloads, "_read_cgroup", fake_cgroup)
    monkeypatch.setattr(workloads, "_read_cmdline", fake_cmdline)


def _install_gpu_mock(monkeypatch, processes: list[dict]):
    gpus = [
        {"index": 0, "uuid": "GPU-wl-0", "processes": []},
        {"index": 1, "uuid": "GPU-wl-1", "processes": []},
    ]
    monkeypatch.setattr(workloads.nvidia, "list_gpus", lambda: gpus)
    monkeypatch.setattr(workloads.nvidia, "list_compute_processes", lambda: processes)


def _install_docker_ps(monkeypatch, output: str = DOCKER_PS_OUTPUT):
    monkeypatch.setattr(
        workloads,
        "_docker_ps_mapping",
        lambda: dict(line.split("\t", 1) for line in output.splitlines() if "\t" in line),
    )


FULL_ID_MAGIC = "a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"
FULL_ID_BGE = "f6e5d4c3b2a109182736455463728192f6e5d4c3b2a109182736455463728192"


def test_detect_groups_docker_systemd_process(monkeypatch):
    _install_gpu_mock(monkeypatch, [
        {"pid": 100, "gpu_uuid": "GPU-wl-0", "used_gpu_memory_mib": 11190, "process_name": "VLLM::EngineCore"},
        {"pid": 101, "gpu_uuid": "GPU-wl-0", "used_gpu_memory_mib": 512, "process_name": "python"},  # 同容器另一进程
        {"pid": 200, "gpu_uuid": "GPU-wl-1", "used_gpu_memory_mib": 3724, "process_name": "python"},
        {"pid": 300, "gpu_uuid": "GPU-wl-1", "used_gpu_memory_mib": 800, "process_name": "ollama"},
    ])
    _install_proc_mock(monkeypatch, {
        100: f"0::/system.slice/docker-{FULL_ID_MAGIC}.scope\n",
        101: f"0::/system.slice/docker-{FULL_ID_MAGIC}.scope\n",
        200: f"0::/system.slice/docker-{FULL_ID_BGE}.scope\n",
        300: "0::/system.slice/ollama.service\n",
    })
    _install_docker_ps(monkeypatch)

    items = workloads.detect_gpu_workloads()
    # 按显存降序:magic-pdf(11702) > bge(3724) > ollama systemd(800)
    assert [i["name"] for i in items] == ["magic-pdf-server", "bge-m3-server", "ollama.service"]
    magic = items[0]
    assert magic["kind"] == "docker" and magic["stoppable"] is True
    assert magic["pids"] == [100, 101]
    assert magic["used_memory_mib"] == 11702
    assert magic["gpu_indices"] == [0]
    ollama = items[2]
    assert ollama["kind"] == "systemd" and ollama["stoppable"] is False


def test_detect_bare_process_readonly(monkeypatch):
    _install_gpu_mock(monkeypatch, [
        {"pid": 999, "gpu_uuid": "GPU-wl-0", "used_gpu_memory_mib": 1024, "process_name": "python"},
    ])
    _install_proc_mock(monkeypatch, {999: "0::/user.slice/user-1000.slice/session-3.scope\n"}, {999: "python train.py"})
    items = workloads.detect_gpu_workloads()
    assert items[0]["kind"] == "process" and items[0]["stoppable"] is False
    assert items[0]["name"] == "pid-999"


def test_stop_allows_only_current_gpu_containers(monkeypatch):
    _install_gpu_mock(monkeypatch, [
        {"pid": 100, "gpu_uuid": "GPU-wl-0", "used_gpu_memory_mib": 11190, "process_name": "VLLM"},
    ])
    _install_proc_mock(monkeypatch, {100: f"0::/system.slice/docker-{FULL_ID_MAGIC}.scope\n"})
    _install_docker_ps(monkeypatch)

    stopped = {}

    def fake_run(argv, **kwargs):
        stopped["argv"] = argv
        return type("P", (), {"returncode": 0, "stdout": "magic-pdf-server\n", "stderr": ""})()

    monkeypatch.setattr(workloads, "run", fake_run)

    result = workloads.stop_docker_workload("magic-pdf-server")
    assert result == {"stopped": "magic-pdf-server", "freed_memory_mib": 11190}
    assert stopped["argv"] == ["docker", "stop", "-t", "30", "magic-pdf-server"]

    # 未占用 GPU 的容器被拒绝(哪怕它真实存在,如 redis-server)
    with pytest.raises(workloads.WorkloadError, match="未占用 GPU"):
        workloads.stop_docker_workload("redis-server")
    # 非法容器名被拒绝
    with pytest.raises(workloads.WorkloadError, match="非法字符"):
        workloads.stop_docker_workload("x; rm -rf /")
    # systemd 归属的负载不能通过 docker stop 路径停止
    with pytest.raises(workloads.WorkloadError, match="未占用 GPU"):
        workloads.stop_docker_workload("ollama.service")


def test_detect_docker_ps_failure_degrades(monkeypatch):
    _install_gpu_mock(monkeypatch, [
        {"pid": 100, "gpu_uuid": "GPU-wl-0", "used_gpu_memory_mib": 11190, "process_name": "VLLM"},
    ])
    _install_proc_mock(monkeypatch, {100: f"0::/system.slice/docker-{FULL_ID_MAGIC}.scope\n"})

    def boom():
        raise workloads.WorkloadError("docker ps 查询失败:命令不存在:docker")

    monkeypatch.setattr(workloads, "_docker_ps_mapping", boom)
    items = workloads.detect_gpu_workloads()
    # docker ps 失败时按容器短 ID 展示,不整体失败
    assert items[0]["name"] == FULL_ID_MAGIC[:12]
