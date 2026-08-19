"""日志配置。

只配置 ``job_agent`` 这一棵 logger，不动 root——否则会把 uvicorn 的日志格式一起改掉。
CLI 里给用户看的文字用 ``typer.echo``；日志是给排查问题用的，两者刻意分开。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%H:%M:%S"

_configured = False


def setup_logging(
    level: str = "INFO",
    file: Path | None = None,
    console_level: str | None = None,
    force: bool = False,
) -> None:
    """初始化 ``job_agent`` logger。重复调用默认是幂等的（``force=True`` 可重配）。

    ``console_level`` 单独控制终端：CLI 会把它抬到 WARNING，
    因为进度已经由命令自己打印了，日志再打一遍就是重影；
    落盘日志仍按 ``level`` 记全。
    """
    global _configured
    if _configured and not force:
        return

    logger = logging.getLogger("job_agent")
    logger.handlers.clear()
    effective_console = (console_level or level).upper()
    # logger 自身取两者中更详细的那个，否则文件里会缺日志
    logger.setLevel(min(_level_no(level), _level_no(effective_console)))
    logger.propagate = False

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(formatter)
    stderr.setLevel(effective_console)
    logger.addHandler(stderr)

    if file is not None:
        file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(file, encoding="utf-8")
        # 落盘日志带完整日期，终端不带
        file_handler.setFormatter(logging.Formatter(_FORMAT))
        file_handler.setLevel(level.upper())
        logger.addHandler(file_handler)

    _configured = True


def _level_no(level: str) -> int:
    return logging.getLevelNamesMapping().get(level.upper(), logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """取得子 logger，``name`` 传 ``__name__`` 即可。"""
    if not name.startswith("job_agent"):
        name = f"job_agent.{name}"
    return logging.getLogger(name)
