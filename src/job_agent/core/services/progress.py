"""进度上报。

服务层不许直接 ``print``：同一个用例要能在 CLI 里打到终端、在 Web 里进任务日志。
所以统一发 :class:`ProgressEvent`，由调用方决定怎么呈现；同时无条件写一份日志。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from job_agent.log import get_logger

Level = Literal["info", "warn", "error"]


class ProgressEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    current: int | None = None
    total: int | None = None
    level: Level = "info"

    @property
    def percent(self) -> float | None:
        if self.current is None or not self.total:
            return None
        return round(min(self.current / self.total, 1.0) * 100, 1)


ProgressHook = Callable[[ProgressEvent], None]


class Progress:
    """把事件同时送到 hook 与日志。hook 为空时只写日志。"""

    def __init__(self, hook: ProgressHook | None = None, logger_name: str = "progress") -> None:
        self._hook = hook
        self._logger = get_logger(logger_name)

    def emit(
        self,
        message: str,
        current: int | None = None,
        total: int | None = None,
        level: Level = "info",
    ) -> None:
        event = ProgressEvent(message=message, current=current, total=total, level=level)
        log = {"info": self._logger.info, "warn": self._logger.warning, "error": self._logger.error}
        log[level](message)
        if self._hook is not None:
            try:
                self._hook(event)
            except Exception:
                self._logger.exception("进度回调失败，已忽略")
