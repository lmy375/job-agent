"""``job`` 命令。

    job search                 搜索职位入库，接着抓详情页解析 JD
    job score                  按信号表打分排序；--shortlist 写候选清单骨架
    job apply <jobId>...       投递职位
    job agent                  LangGraph 路线：无人值守跑完整条流程
    job stats                  在终端看一眼库里现在有什么
    job web                    启动 Web 管理服务
    job reset                  删库重建（结构变了就重来，不做迁移）
    job config init|show|path  管理配置
    job db info|vacuum         数据库维护
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer
from typer.core import TyperGroup

from job_agent import __version__
from job_agent.cli import commands
from job_agent.cli.state import CliState, echo_error
from job_agent.errors import JobAgentError


class JobAgentGroup(TyperGroup):
    """把预期内的异常收敛成「一行错误 + 明确退出码」。

    放在 group 层而不是入口函数里，是为了让所有调用方式（包括测试里的 CliRunner、
    被别的脚本 import 后调用）都得到同样的行为。退出码见 :mod:`job_agent.errors`。
    """

    # ctx 标成 Any：typer 用的 Context 类型在私有模块 typer._click.core 里，
    # 从公开路径拿不到，写死会在 typer 升级时炸
    def invoke(self, ctx: Any) -> Any:
        try:
            return super().invoke(ctx)
        except JobAgentError as exc:
            echo_error(str(exc))
            raise typer.Exit(code=exc.exit_code) from exc


app = typer.Typer(
    cls=JobAgentGroup,
    add_completion=False,
    # 关掉 rich markup：帮助文本里全是 [agent.providers.*] 这样的 TOML 段名，
    # 开着的话方括号会被当成标记语言吃掉（"默认取 [profiles].default" 显示成 ".default"）
    rich_markup_mode=None,
    no_args_is_help=True,
    help="猎聘职位采集、分诊打分与投递。",
    context_settings={"help_option_names": ["-h", "--help"]},
)
commands.register(app)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"job-agent {__version__}")
        raise typer.Exit


@app.callback()
def main_callback(
    ctx: typer.Context,
    profile: Annotated[
        str | None,
        typer.Option(
            "--profile",
            "-p",
            help="用哪个 profile（profiles/ 下的目录名）。默认取 [profiles].default。",
        ),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="全局配置文件路径，默认 config/config.toml。"),
    ] = None,
    log_level: Annotated[
        str | None,
        typer.Option("--log-level", help="日志级别：DEBUG / INFO / WARNING / ERROR。"),
    ] = None,
    quiet: Annotated[bool, typer.Option("--quiet", "-q", help="只输出警告与错误。")] = False,
    _version: Annotated[
        bool,
        typer.Option("--version", "-V", callback=_version_callback, is_eager=True,
                     help="打印版本后退出。"),
    ] = False,
) -> None:
    """全局选项。子命令通过 ``ctx.obj`` 拿到状态。"""
    ctx.obj = CliState(
        profile=profile, config_file=config, log_level=log_level, quiet=quiet
    )
    ctx.call_on_close(ctx.obj.close)


def main() -> None:
    """``job`` 命令的入口点。异常处理在 :class:`JobAgentGroup` 里。"""
    app()


if __name__ == "__main__":
    main()
