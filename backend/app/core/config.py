"""PoemVideo Studio 全局配置。

所有可变参数(数据目录、ComfyUI 地址、Workflow 模板路径、默认生成参数、
上传限制)集中于此,不允许在业务代码中散落硬编码。
"""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# 本仓库根目录(backend/ 的上一级)
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # 数据根目录:默认开发环境使用仓库内 ./data,生产通过 .env 指向 /data/poem-video-studio
    data_root: Path = REPO_ROOT / "data" / "poem-video-studio"

    # H3 原生视频 API（与 ComfyUI 8188 独立，不修改现有 H3 模型服务）
    h3_api_base_url: str = "http://host.docker.internal:8000"
    h3_turbo_lora_path: str = ("/data/AI_Models/MiniMax-H3/Turbo/"
                              "minimax_h3_fl2v_turbo_8step_v1.0_768p_bf16.safetensors")

    # ComfyUI
    comfyui_base_url: str = "http://127.0.0.1:8188"
    comfyui_ws_url: str = "ws://127.0.0.1:8188/ws"
    comfyui_client_id: str = "poem-video-studio"
    comfyui_connect_timeout: float = 5.0
    comfyui_request_timeout: float = 30.0

    # HTTP 对账兜底周期(秒);E2E 环境可调小加速用例
    reconcile_interval_seconds: float = 30.0

    # Workflow 模板与节点映射(旧单文件路径,已被模板管理/DATA_ROOT/workflows 取代,保留兼容)
    workflow_template: Path = REPO_ROOT / "workflows" / "minimax_h3_poem_v1.json"
    workflow_map: Path = REPO_ROOT / "workflows" / "workflow-map.yaml"

    # ComfyUI 用户工作流目录(容器内挂载宿主 ComfyUI user 目录,用于导入真实工作流)
    comfyui_user_workflows_dir: Path = Path("/comfyui-user/default/workflows")

    # 默认生成参数(允许通过 .env 覆盖,不散落硬编码)
    default_width: int = 768
    default_height: int = 1024
    default_fps: int = 24
    default_num_frames: int = 121

    # 上传限制
    upload_allowed_extensions: str = "png,jpg,jpeg,webp"
    upload_max_size_mb: int = 20

    # 服务器控制中心(任务04/05):Web API 不直接执行宿主机命令,一律经 Agent
    agent_base_url: str = "http://127.0.0.1:8300"
    agent_token: str = ""
    agent_connect_timeout: float = 3.0
    agent_request_timeout: float = 20.0
    # 一键环境 Profile(容器内由 compose 挂载 ./server 到 /app/server)
    server_profiles_file: Path = REPO_ROOT / "server" / "profiles.yaml"
    # 环境准备轮询间隔(测试可调小)
    prepare_poll_interval: float = 2.0

    @property
    def uploads_dir(self) -> Path:
        return self.data_root / "uploads"

    @property
    def outputs_dir(self) -> Path:
        return self.data_root / "outputs"

    @property
    def database_dir(self) -> Path:
        return self.data_root / "database"

    @property
    def logs_dir(self) -> Path:
        return self.data_root / "logs"

    @property
    def database_url(self) -> str:
        return f"sqlite:///{(self.database_dir / 'poem_video_studio.db').as_posix()}"

    def ensure_dirs(self) -> None:
        for d in (self.uploads_dir, self.outputs_dir, self.database_dir, self.logs_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def allowed_extensions(self) -> set[str]:
        return {ext.strip().lower() for ext in self.upload_allowed_extensions.split(",") if ext.strip()}


settings = Settings()
