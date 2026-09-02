"""CLI 全局状态与输出工具。

上下文按需构造（``--config`` 解析完之后），这样 ``job --help`` / ``job config init``
在还没有可用配置、甚至没有数据库文件时也能跑。
"""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import BaseModel, ConfigDict, PrivateAttr

from job_agent.context import AppContext
from job_agent.core.services import ProgressEvent

#: 进度级别 -> 终端颜色
_COLORS = {"info": None, "warn": typer.colors.YELLOW, "error": typer.colors.RED}
_ICONS = {"info": "·", "warn": "!", "error": "×"}


class CliState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: str | None = None
    config_file: Path | None = None
    log_level: str | None = None
    quiet: bool = False
    #: 惰性构造的上下文。PrivateAttr 而不是字段：它不是命令行传进来的状态，
    #: 也不该出现在 repr / model_dump 里
    _context: AppContext | None = PrivateAttr(default=None)

    def context(self) -> AppContext:
        """惰性构造上下文，同一次命令内复用。"""
        if self._context is None:
            # 终端默认只显示 WARNING：INFO 级进度已经由命令本身打印了
            self._context = AppContext.create(
                self.profile, self.config_file, self.log_level, console_level="WARNING"
            )
        return self._context

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._context = None

    def progress(self) -> ProgressPrinter:
        return ProgressPrinter(quiet=self.quiet)


class ProgressPrinter:
    """把服务层的进度事件打到终端。"""

    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet

    def __call__(self, event: ProgressEvent) -> None:
        if self.quiet and event.level == "info":
            return
        prefix = _ICONS[event.level]
        percent = f"[{event.percent:.0f}%] " if event.percent is not None else ""
        typer.secho(f"{prefix} {percent}{event.message}", fg=_COLORS[event.level])


def echo_ok(message: str) -> None:
    typer.secho(f"✓ {message}", fg=typer.colors.GREEN)


def echo_warn(message: str) -> None:
    typer.secho(f"! {message}", fg=typer.colors.YELLOW)


def echo_error(message: str) -> None:
    typer.secho(f"× {message}", fg=typer.colors.RED, err=True)
