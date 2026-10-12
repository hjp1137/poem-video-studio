"""受控命令执行器:参数数组、shell=False、超时、stderr 捕获。

Agent 的全部主机动作都必须经过这里;调用方只允许传入代码内固定的
子命令与已经过校验的纯数字参数,禁止拼接任意字符串命令。
"""
from __future__ import annotations

import subprocess

from app.core.config import agent_settings


class CommandError(Exception):
    """命令执行失败:超时、退出码非 0 或无法启动。"""

    def __init__(self, argv: list[str], reason: str):
        self.argv = argv
        self.reason = reason
        super().__init__(f"命令失败({reason}):{' '.join(argv[:6])}")


def run(argv: list[str], *, timeout: float | None = None, sudo: bool = False) -> subprocess.CompletedProcess:
    """执行白名单命令并校验退出码。sudo=True 时以 sudo -n 前缀执行(变更类动作)。"""
    full_argv = (["sudo", "-n", *argv] if sudo else list(argv))
    try:
        proc = subprocess.run(  # noqa: S603 参数数组且子命令均来自代码内白名单
            full_argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout if timeout is not None else agent_settings.command_timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise CommandError(full_argv, f"超时({exc.timeout}s)") from exc
    except FileNotFoundError as exc:
        raise CommandError(full_argv, f"命令不存在:{argv[0]}") from exc
    except OSError as exc:
        raise CommandError(full_argv, f"无法执行:{exc}") from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()[:500]
        raise CommandError(full_argv, f"退出码 {proc.returncode}:{stderr}")
    return proc
