"""FastAPI 依赖：从 ``app.state`` 取出应用级对象。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from job_agent.config import Settings
from job_agent.context import AppContext
from job_agent.web.tasks import TaskManager


def get_context(request: Request) -> AppContext:
    return request.app.state.context  # type: ignore[no-any-return]


def get_settings(request: Request) -> Settings:
    return request.app.state.context.settings  # type: ignore[no-any-return]


def get_tasks(request: Request) -> TaskManager:
    return request.app.state.tasks  # type: ignore[no-any-return]


ContextDep = Annotated[AppContext, Depends(get_context)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
TasksDep = Annotated[TaskManager, Depends(get_tasks)]
