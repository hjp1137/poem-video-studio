"""开机自动应用 Power Limit(oneshot CLI):

    python -m app.apply_power

由 poem-video-gpu-power.service(Type=oneshot)在 NVIDIA 驱动可用后调用;
读取 gpu-power.json 逐卡应用,单卡失败记录该 index 并以非 0 退出码上报,
但不阻断系统启动(systemd unit 不设 Required)。
"""
from __future__ import annotations

import json
import logging
import sys

from app.services import power

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("poem.agent.apply_power")


def main() -> int:
    try:
        result = power.apply_config()
    except power.PowerConfigError as exc:
        # 非法 JSON 不能让服务静默失败:显式记录并以失败退出
        logger.error("gpu-power.json 配置错误:%s", exc)
        print(json.dumps({"error": str(exc), "failed": [], "applied": []}, ensure_ascii=False))
        return 2
    logger.info(
        "开机功耗应用完成 applied=%s failed=%s skipped=%s",
        result["applied"], result["failed"], result["skipped"],
    )
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
