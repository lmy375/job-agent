"""profile：列出、新建、切换。

一个 profile 是一个自包含的目录，**换 profile 等于换一整套数据**：库、简历、
关键词、信号表全换。所以这里不是「改一个设置」，而是把服务正在用的
:class:`~job_agent.context.AppContext` 整个换掉——仓储握着的是旧库的连接，
只改 ``settings`` 不换连接会变成「设置说 A、读写落在 B」。

真正干活的在共享内核（``core/profile.py``），和 ``job profile`` 用的是同一份：
两边各写一遍的下场是「命令行切了、网页上没切」。

**有任务在跑就拒绝切换**。后台任务在提交那一刻就把当时的 ``AppContext``
捕获进了闭包，切换会把它脚下的库连接抽走。让人等几十秒，比让一次采集
写进半个库强。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from job_agent.config import Settings, load_global_settings, load_settings, profiles_root
from job_agent.context import AppContext
from job_agent.core.profile import create_profile, set_default_profile, summarize_profiles
from job_agent.errors import ConfigError
from job_agent.web.deps import ContextDep, TasksDep
from job_agent.web.schemas import CreateProfileRequest, ProfilesResponse, SwitchProfileRequest
from job_agent.web.tasks import TaskManager

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("", response_model=ProfilesResponse, summary="所有 profile 及各自的进度")
def list_profiles_view(context: ContextDep) -> ProfilesResponse:
    """列表**不建库、不抛异常**：某个 profile 的配置写坏了，恰恰是你最想在
    列表里看见它的时候，所以读不出来的项留空，不让一个坏 profile 把整张表带崩。
    """
    return _response(context.settings)


@router.post("", response_model=ProfilesResponse, status_code=201, summary="新建一个 profile")
def create(
    request: Request, context: ContextDep, tasks: TasksDep, payload: CreateProfileRequest
) -> ProfilesResponse:
    """从 ``config/templates/`` 拷一份出来，默认**建完就切过去**。

    新 profile 一出生是空的：没有简历、没有求职偏好、关键词是模板里的示例。
    所以建完就该去「提示词」页把这两份填了，不然 LLM 打分没有判断依据。
    """
    settings = context.settings
    globals_ = load_global_settings(settings.root, settings.config_file)
    create_profile(globals_, payload.name)
    if payload.switch or globals_.profiles.default is None:
        return _switch(request, context, tasks, payload.name)
    return _response(settings)


@router.put("/current", response_model=ProfilesResponse, summary="切换当前 profile")
def switch(
    request: Request, context: ContextDep, tasks: TasksDep, payload: SwitchProfileRequest
) -> ProfilesResponse:
    """换一整套数据，并把它写成 ``[profiles].default``。

    写默认是刻意的：「切换」该是整个系统切过去，不只是这个页面——
    下一条 ``job search`` 也得落在同一个库里，否则两边看到的不是一回事。
    """
    return _switch(request, context, tasks, payload.name)


def _switch(
    request: Request, context: ContextDep, tasks: TaskManager, name: str
) -> ProfilesResponse:
    settings = context.settings
    if name == settings.profile_name:
        return _response(settings)

    running = tasks.running()
    if running is not None:
        raise ConfigError(
            f"有任务正在跑（{running.kind.value}，{running.status.value}），现在不能切 profile。"
            "\n  等它结束，或先到「采集任务」页取消它——切换会把它脚下的库连接抽走。"
        )

    globals_ = load_global_settings(settings.root, settings.config_file)
    set_default_profile(globals_, name)  # 名字不存在时在这里报错，此时还没动任何连接

    fresh = load_settings(profile=name, config_file=settings.config_file, root=settings.root)
    new_context = AppContext.from_settings(fresh)
    old = request.app.state.context
    request.app.state.context = new_context
    old.close()
    return _response(fresh)


def _response(settings: Settings) -> ProfilesResponse:
    globals_ = load_global_settings(settings.root, settings.config_file)
    return ProfilesResponse(
        profiles=summarize_profiles(globals_, current=settings.profile_name),
        current=settings.profile_name,
        profilesDir=str(profiles_root(settings.root, globals_)),
    )
