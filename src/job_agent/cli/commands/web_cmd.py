"""``job web``：启动 Web 管理服务。"""

from __future__ import annotations

import subprocess
import threading
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_error, echo_warn
from job_agent.log import get_logger

logger = get_logger(__name__)

#: 前端源码目录（与 config/ 同级）
FRONTEND_DIR_NAME = "frontend"
BROWSER_DELAY = 1.0


def web(
    ctx: typer.Context,
    host: Annotated[str | None, typer.Option("--host", help="监听地址，默认取配置。")] = None,
    port: Annotated[int | None, typer.Option("--port", help="端口，默认取配置。")] = None,
    no_browser: Annotated[bool, typer.Option("--no-browser", help="不自动打开浏览器。")] = False,
    skip_build: Annotated[
        bool, typer.Option("--skip-build", help="跳过前端构建检查（只提供 API）。")
    ] = False,
) -> None:
    import uvicorn

    from job_agent.web import create_app

    state: CliState = ctx.obj
    context = state.context()
    settings = context.settings
    bind_host = host or settings.web.host
    bind_port = port or settings.web.port

    if not skip_build:
        _ensure_frontend(settings.root / FRONTEND_DIR_NAME, settings.web.frontend_dist)

    url = f"http://{'127.0.0.1' if bind_host == '0.0.0.0' else bind_host}:{bind_port}"
    if not no_browser and settings.web.open_browser:
        threading.Timer(BROWSER_DELAY, lambda: webbrowser.open(url)).start()

    typer.secho(f"Web 服务已启动：{url}（Ctrl+C 退出）", fg=typer.colors.GREEN)
    typer.echo(f"  API 文档：{url}/docs")
    uvicorn.run(
        create_app(settings=settings, context=context),
        host=bind_host,
        port=bind_port,
        log_level=settings.logging.level.lower(),
    )


def _ensure_frontend(source_dir: Path, dist_dir: Path) -> None:
    """前端没构建过就构建一次。构建失败不阻塞——退化成只提供 API。"""
    if dist_dir.is_dir() and any(dist_dir.iterdir()):
        return
    if not (source_dir / "package.json").is_file():
        echo_warn(f"未找到前端工程（{source_dir}），只提供 API。")
        return

    typer.echo("前端尚未构建，正在构建（首次较慢）……")
    try:
        if not (source_dir / "node_modules").is_dir():
            subprocess.run(["npm", "install"], cwd=source_dir, check=True)
        subprocess.run(["npm", "run", "build"], cwd=source_dir, check=True)
    except FileNotFoundError:
        echo_warn("没有 npm，跳过前端构建，只提供 API。")
    except subprocess.CalledProcessError as exc:
        echo_error(f"前端构建失败（退出码 {exc.returncode}），只提供 API。")
