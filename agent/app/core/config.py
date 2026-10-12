"""Agent 全局配置:全部来自环境变量,便于 systemd EnvironmentFile 与测试覆盖。"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=".env", env_file_encoding="utf-8", extra="ignore")

    host: str = "127.0.0.1"
    port: int = 8300
    # 可选 Bearer Token;为空表示不校验(仅依赖 localhost 绑定)
    token: str = ""

    # 宿主机配置目录:生产 /etc/poem-video-agent,测试用环境变量指向临时目录
    config_dir: Path = Path("/etc/poem-video-agent")

    # 高权限命令是否经 sudo -n 执行(读查询不需要,变更动作按需)
    use_sudo: bool = True
    nvidia_smi: str = "nvidia-smi"
    systemctl: str = "systemctl"
    journalctl: str = "journalctl"
    docker: str = "docker"
    command_timeout: float = 15.0

    @property
    def gpu_power_config(self) -> Path:
        return self.config_dir / "gpu-power.json"

    @property
    def services_config(self) -> Path:
        return self.config_dir / "services.yaml"


agent_settings = AgentSettings()
