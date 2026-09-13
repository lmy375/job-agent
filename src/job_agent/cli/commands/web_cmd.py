"""``job web``：启动 Web 管理服务。

**一条命令就该能用起来**：管理台是这个系统的完整入口，从填 token、配关键词
到投递全在页面上。所以新克隆下来第一次跑 ``job web``，不该先被一句
「还没有任何 profile」挡在门外，再去翻文档找该跑哪两条命令——
缺全局配置就照模板生成一份，一个 profile 都没有就建一个 ``default``。
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_error, echo_ok, echo_warn
from job_agent.config import (
    default_config_path,
    example_config_path,
    find_project_root,
    list_profiles,
    load_global_settings,
    profiles_root,
)
from job_agent.core.profile import create_profile, set_default_profile
from job_agent.log import get_logger

logger = get_logger(__name__)

#: 前端源码目录（与 config/ 同级）
FRONTEND_DIR_NAME = "frontend"
BROWSER_DELAY = 1.0
#: 一个 profile 都没有时自建的那个名字
BOOTSTRAP_PROFILE = "default"


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

    _bootstrap()
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


def _bootstrap() -> None:
    """没有全局配置就生成一份，一个 profile 都没有就建一个。

    自建是安全的：它只是把 ``config/`` 下的模板拷过去，里面全是待填的空壳，
    **不含任何判断口径**——简历、求职偏好、关键词要填什么，仍然得人自己说。
    刻意只在「一个都没有」时做：有两个及以上却没指定用哪个时绝不猜，
    猜错就是往别人的库里写数据。
    """
    root = find_project_root()
    target = default_config_path(root)
    if not target.is_file() and example_config_path(root).is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(example_config_path(root), target)
        echo_ok(f"已生成全局配置 {target}（猎聘 token 等会儿在页面上填）")

    settings = load_global_settings(root)
    if list_profiles(profiles_root(settings.root, settings)):
        return
    directory = create_profile(settings, BOOTSTRAP_PROFILE)
    set_default_profile(settings, BOOTSTRAP_PROFILE)
    echo_ok(f"还没有 profile，已建一个：{directory}")
    typer.echo(
        "  它现在是一份空模板。打开页面后先去「配置 → 提示词」把简历与求职偏好填了"
        "，再到「职位采集」填 token 与关键词。"
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
            subprocess.run(["pnpm", "install"], cwd=source_dir, check=True)
        # build 里带 tsc：类型不过就不出产物，别让坏页面悄悄发布
        subprocess.run(["pnpm", "build"], cwd=source_dir, check=True)
    except FileNotFoundError:
        echo_warn("没有 pnpm（npm i -g pnpm），跳过前端构建，只提供 API。")
    except subprocess.CalledProcessError as exc:
        echo_error(f"前端构建失败（退出码 {exc.returncode}），只提供 API。")
