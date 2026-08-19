"""后台任务管理。

采集类任务（搜索 / 抓详情 / 生成报告）都是长任务，HTTP 请求里跑不完，
所以放到后台线程，前端轮询状态。

**只有一个 worker**，这是刻意的：猎聘的限流按 token 记账，两个采集任务并行
只会更快撞上限流；SQLite 的写也不适合并发。任务因此是排队执行的。
取消是协作式的——线程不能安全地被杀，只能让服务在条目边界自己停下。
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from job_agent.core.services import ProgressEvent
from job_agent.log import get_logger

logger = get_logger(__name__)

#: 每个任务最多保留多少条日志（内存里，够看进度就行）
MAX_LOGS = 400
#: 内存里最多保留多少个历史任务
MAX_TASKS = 50


class TaskKind(StrEnum):
    SEARCH = "search"
    DETAIL = "detail"
    REPORT = "report"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Task:
    id: str
    kind: TaskKind
    params: dict[str, Any] = field(default_factory=dict)
    status: TaskStatus = TaskStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    message: str = ""
    current: int | None = None
    total: int | None = None
    logs: deque[str] = field(default_factory=lambda: deque(maxlen=MAX_LOGS))
    result: dict[str, Any] | None = None
    error: str | None = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def cancel_requested(self) -> bool:
        return self._cancel.is_set()

    @property
    def percent(self) -> float | None:
        if self.current is None or not self.total:
            return None
        return round(min(self.current / self.total, 1.0) * 100, 1)

    @property
    def done(self) -> bool:
        return self.status in (TaskStatus.SUCCEEDED, TaskStatus.FAILED, TaskStatus.CANCELLED)

    def as_dict(self, with_logs: bool = True) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind.value,
            "status": self.status.value,
            "params": self.params,
            "message": self.message,
            "current": self.current,
            "total": self.total,
            "percent": self.percent,
            "createdAt": _iso(self.created_at),
            "startedAt": _iso(self.started_at),
            "finishedAt": _iso(self.finished_at),
            "cancelRequested": self.cancel_requested,
            "result": self.result,
            "error": self.error,
        }
        if with_logs:
            data["logs"] = list(self.logs)
        return data


class TaskManager:
    """单 worker 的任务队列。线程安全。"""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="job-task")
        self._tasks: dict[str, Task] = {}
        self._order: deque[str] = deque()
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 提交

    def submit(
        self, kind: TaskKind, runner: Callable[[Task], dict[str, Any]], **params: Any
    ) -> Task:
        """排入一个任务。``runner`` 在后台线程里执行，返回值作为 ``result``。"""
        task = Task(id=uuid.uuid4().hex[:12], kind=kind, params=params)
        with self._lock:
            self._tasks[task.id] = task
            self._order.append(task.id)
            self._evict_locked()
        logger.info("任务入队 %s（%s）params=%s", task.id, kind.value, params)
        future: Future[None] = self._executor.submit(self._run, task, runner)
        future.add_done_callback(lambda f: self._log_future_error(task, f))
        return task

    def _run(self, task: Task, runner: Callable[[Task], dict[str, Any]]) -> None:
        if task.cancel_requested:
            task.status = TaskStatus.CANCELLED
            task.finished_at = datetime.now()
            task.message = "任务在开始前被取消"
            return
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        try:
            task.result = runner(task)
            task.status = (
                TaskStatus.CANCELLED if task.cancel_requested else TaskStatus.SUCCEEDED
            )
        except Exception as exc:
            logger.exception("任务 %s 失败", task.id)
            task.status = TaskStatus.FAILED
            task.error = f"{type(exc).__name__}: {exc}"
            task.logs.append(f"{datetime.now():%H:%M:%S} [error] {task.error}")
        finally:
            task.finished_at = datetime.now()
            if task.error:
                task.message = task.error

    @staticmethod
    def _log_future_error(task: Task, future: Future[None]) -> None:
        exc = future.exception()
        if exc is not None:  # pragma: no cover - _run 已兜住异常，这里只是双保险
            logger.error("任务 %s 的 future 异常：%s", task.id, exc)

    # ------------------------------------------------------------------ 查询

    def get(self, task_id: str) -> Task | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list(self) -> list[Task]:
        """按创建时间倒序。"""
        with self._lock:
            return [self._tasks[tid] for tid in reversed(self._order) if tid in self._tasks]

    def running(self) -> Task | None:
        for task in self.list():
            if task.status in (TaskStatus.RUNNING, TaskStatus.PENDING):
                return task
        return None

    def cancel(self, task_id: str) -> Task | None:
        task = self.get(task_id)
        if task is None or task.done:
            return task
        task._cancel.set()
        task.message = "已请求取消，等当前条目结束后停止"
        logger.info("任务 %s 请求取消", task_id)
        return task

    def progress_hook(self, task: Task) -> Callable[[ProgressEvent], None]:
        """把服务层进度写进任务状态。"""

        def hook(event: ProgressEvent) -> None:
            task.message = event.message
            task.current = event.current
            task.total = event.total
            stamp = datetime.now().strftime("%H:%M:%S")
            task.logs.append(f"{stamp} [{event.level}] {event.message}")

        return hook

    def shutdown(self, wait: bool = False) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def _evict_locked(self) -> None:
        while len(self._order) > MAX_TASKS:
            oldest = self._order.popleft()
            task = self._tasks.get(oldest)
            if task is not None and not task.done:
                # 还没跑完的不能丢，放回队尾等下一轮
                self._order.append(oldest)
                return
            self._tasks.pop(oldest, None)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat(sep=" ", timespec="seconds") if value else None
