"""服务注册表:services.yaml 解析,只允许控制已登记服务。

非法配置不得导致 Agent 崩溃:加载失败抛 RegistryError,由健康接口与
服务 API 转成明确错误;Web 侧不允许动态新增 systemd unit。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import yaml

from app.core.config import agent_settings

logger = logging.getLogger("poem.agent.registry")

SUPPORTED_MANAGERS = ("systemd",)


class RegistryError(Exception):
    """注册表缺失或非法。"""


@dataclass
class HealthCheckDef:
    type: str = "none"
    url: str = ""
    timeout: float = 3.0


@dataclass
class ServiceDef:
    name: str
    display_name: str
    manager: str
    unit: str
    health: HealthCheckDef
    gpu_profile: str = ""
    description: str = ""


def _parse_service(name: str, body: dict) -> ServiceDef:
    if not isinstance(body, dict):
        raise RegistryError(f"服务 {name} 配置必须是对象")
    unit = str(body.get("unit", "")).strip()
    if not unit:
        raise RegistryError(f"服务 {name} 缺少 unit")
    # unit 名只允许安全字符,防止注册表本身注入 systemctl 参数
    if not all(c.isalnum() or c in ".-_@\\" for c in unit):
        raise RegistryError(f"服务 {name} 的 unit 含非法字符:{unit}")
    manager = str(body.get("manager", "systemd")).strip()
    if manager not in SUPPORTED_MANAGERS:
        raise RegistryError(f"服务 {name} 的 manager={manager} 暂不支持(V1.1 仅 systemd)")
    health_body = body.get("health") or {}
    if not isinstance(health_body, dict):
        raise RegistryError(f"服务 {name} 的 health 必须是对象")
    health = HealthCheckDef(
        type=str(health_body.get("type", "none")),
        url=str(health_body.get("url", "")),
        timeout=float(health_body.get("timeout", 3.0)),
    )
    if health.type == "http" and not health.url.startswith(("http://", "https://")):
        raise RegistryError(f"服务 {name} 的 health.url 非法:{health.url}")
    return ServiceDef(
        name=name,
        display_name=str(body.get("display_name", name)),
        manager=manager,
        unit=unit,
        health=health,
        gpu_profile=str(body.get("gpu_profile", "")),
        description=str(body.get("description", "")),
    )


def load_services() -> dict[str, ServiceDef]:
    """读取并校验 services.yaml;文件不存在视为空注册表。"""
    path = agent_settings.services_config
    if not path.is_file():
        raise RegistryError(f"服务注册表不存在:{path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RegistryError(f"服务注册表解析失败({path}):{exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not isinstance(raw.get("services", {}), dict):
        raise RegistryError(f"服务注册表结构非法(services 映射缺失):{path}")
    services: dict[str, ServiceDef] = {}
    for name, body in (raw.get("services") or {}).items():
        key = str(name)
        if not key.replace("_", "").isalnum() or not key.islower():
            raise RegistryError(f"服务名 {key} 非法(仅小写字母/数字/下划线)")
        services[key] = _parse_service(key, body)
    return services


def resolve(name: str) -> ServiceDef:
    """把 API 的服务名解析为注册表定义;未登记直接拒绝。"""
    services = load_services()
    service = services.get(name)
    if service is None:
        raise RegistryError(f"服务 {name} 未在注册表登记,拒绝操作")
    return service
