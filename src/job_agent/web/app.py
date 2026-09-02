"""FastAPI 应用工厂。

Web 端是**管理台**，不只是查看器：可以在页面上发起搜索 / 抓详情、
看任务日志、投递职位。真正会改外部状态的只有投递，前端必须先确认。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from job_agent import __version__
from job_agent.config import Settings, load_settings
from job_agent.context import AppContext
from job_agent.core.liepin.errors import LiepinAuthError, LiepinRateLimited
from job_agent.errors import ConfigError, JobAgentError, StorageError
from job_agent.log import get_logger
from job_agent.web.routers import api_router
from job_agent.web.tasks import TaskManager

logger = get_logger(__name__)

DESCRIPTION = """
猎聘职位数据管理台。

- `/api/jobs` 职位列表与详情、投递
- `/api/tasks` 后台采集任务（搜索 / 抓详情）
- `/api/scores/refresh` 按当前 `[score]` 重新打分（= `job score`）
- `/api/config` 当前配置；搜索关键词与 `[score]` 可改（写回 profile.toml）
- `/api/stats` 库内数据概览
"""


def create_app(settings: Settings | None = None, context: AppContext | None = None) -> FastAPI:
    """构造应用。传入 ``context`` 可复用 CLI 已建好的连接（测试里传临时库）。"""
    resolved = settings or (context.settings if context else load_settings())
    ctx = context or AppContext.from_settings(resolved)

    @asynccontextmanager
    async def lifespan(instance: FastAPI) -> AsyncIterator[None]:
        yield
        # 退出时停掉后台 worker，否则 Ctrl+C 之后进程会挂在未完成的任务上
        instance.state.tasks.shutdown()
        logger.info("Web 服务已停止")

    app = FastAPI(
        title="job-agent",
        version=__version__,
        description=DESCRIPTION,
        docs_url="/docs",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )
    app.state.context = ctx
    app.state.tasks = TaskManager()

    if resolved.web.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=resolved.web.cors_origins,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    _register_error_handlers(app)
    app.include_router(api_router)

    _mount_frontend(app, resolved)
    return app


def _register_error_handlers(app: FastAPI) -> None:
    """把内部异常翻译成合适的 HTTP 状态码，而不是一律 500。"""
    status_map: list[tuple[type[JobAgentError], int]] = [
        (LiepinAuthError, 401),
        (LiepinRateLimited, 429),
        (ConfigError, 400),
        (StorageError, 500),
    ]

    @app.exception_handler(JobAgentError)
    def handle_job_agent_error(_request: Request, exc: JobAgentError) -> JSONResponse:
        status = next((code for kind, code in status_map if isinstance(exc, kind)), 500)
        if status >= 500:
            logger.exception("请求处理失败：%s", exc)
        else:
            logger.warning("请求被拒：%s", exc)
        return JSONResponse(
            status_code=status, content={"detail": str(exc), "type": type(exc).__name__}
        )

    @app.exception_handler(Exception)
    def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        """兜底：非预期异常也返回 JSON。

        默认的 500 是 text/plain，前端 JSON.parse 会二次报错，
        真正的错误信息就被「Unexpected token」盖掉了。
        """
        logger.exception("未处理的异常")
        return JSONResponse(
            status_code=500,
            content={"detail": f"服务内部错误：{exc}", "type": type(exc).__name__},
        )


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    dist = settings.web.frontend_dist
    if dist.is_dir() and (dist / "index.html").is_file():
        # html=True：未命中的路径回落到 index.html，支持前端路由
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
        return

    @app.get("/", include_in_schema=False)
    def missing_frontend() -> JSONResponse:
        return JSONResponse(
            {
                "message": f"前端未构建（{dist}）。在 frontend/ 下执行 "
                "`pnpm install && pnpm build`，或直接用 `job web`（会自动构建）。",
                "api": "/docs",
            }
        )
