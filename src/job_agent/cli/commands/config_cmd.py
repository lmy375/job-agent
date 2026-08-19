"""``job config``：初始化、查看、校验配置。"""

from __future__ import annotations

import json
import shutil
from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.config import default_config_path, example_config_path, find_project_root
from job_agent.config.loader import env_file_path
from job_agent.errors import ConfigError

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("init", help="从模板生成 config/config.toml 与 config/.env。")
def init(
    force: Annotated[bool, typer.Option("--force", help="已存在时也覆盖。")] = False,
) -> None:
    root = find_project_root()
    example = example_config_path(root)
    target = default_config_path(root)
    if not example.is_file():
        raise ConfigError(f"缺少配置模板：{example}")

    if target.is_file() and not force:
        echo_warn(f"{target} 已存在（加 --force 覆盖）")
    else:
        shutil.copyfile(example, target)
        echo_ok(f"已生成 {target}")

    env_target = env_file_path(root)
    env_example = env_target.parent / ".env.example"
    if env_target.is_file() and not force:
        echo_warn(f"{env_target} 已存在（加 --force 覆盖）")
    elif env_example.is_file():
        shutil.copyfile(env_example, env_target)
        echo_ok(f"已生成 {env_target}，请填入 LIEPIN_USER_TOKEN")

    insights_target = root / "config" / "insights"
    insights_example = root / "config" / "insights.example"
    if insights_target.is_dir() and not force:
        echo_warn(f"{insights_target} 已存在（加 --force 覆盖）")
    elif insights_example.is_dir():
        shutil.copytree(insights_example, insights_target, dirs_exist_ok=True)
        echo_ok(f"已生成 {insights_target}（报告里的文字素材，按需改写）")

    typer.echo("\n下一步：填好 token 与搜索关键词后执行 job search")


@app.command("show", help="打印当前生效的配置（token 已脱敏）。")
def show(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    state: CliState = ctx.obj
    settings = state.context().settings
    data = settings.redacted()
    if as_json:
        typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return

    typer.secho(f"配置文件：{settings.config_file or '（未找到，使用内置默认值）'}", bold=True)
    typer.echo(f"项目根目录：{settings.root}")
    typer.echo(f"token：{'已配置' if settings.token else '未配置（无法访问接口）'}")
    for section in ("profile", "search", "liepin", "detail", "storage", "report", "web", "logging"):
        typer.secho(f"\n[{section}]", fg=typer.colors.CYAN)
        for key, value in data[section].items():
            if key == "groups":
                for group in value:
                    flag = "" if group["enabled"] else "（已禁用）"
                    typer.echo(f"  {group['track']:<6}{flag} {'、'.join(group['keywords'])}")
                continue
            typer.echo(f"  {key:<16}{value}")


@app.command("path", help="打印配置与数据文件路径。")
def path(ctx: typer.Context) -> None:
    state: CliState = ctx.obj
    settings = state.context().settings
    typer.echo(f"root         {settings.root}")
    typer.echo(f"config       {settings.config_file}")
    typer.echo(f"env          {env_file_path(settings.root)}")
    typer.echo(f"database     {settings.storage.database}")
    typer.echo(f"resume       {settings.profile.resume}")
    typer.echo(f"insights     {settings.report.insights_dir}")
    typer.echo(f"report       {settings.report.output}")


@app.command("validate", help="校验配置是否可用（含 token、简历、素材是否就位）。")
def validate(ctx: typer.Context) -> None:
    state: CliState = ctx.obj
    settings = state.context().settings
    problems: list[str] = []

    if not settings.token:
        problems.append("未配置 LIEPIN_USER_TOKEN（config/.env），无法搜索或投递")
    if not settings.search.keywords:
        problems.append("[[search.groups]] 里没有启用任何关键词，job search 无事可做")
    if not settings.profile.resume.is_file():
        problems.append(f"简历文件不存在：{settings.profile.resume}")
    if not settings.report.insights_dir.is_dir():
        problems.append(
            f"insights 目录不存在：{settings.report.insights_dir}（报告将只有定量部分）"
        )

    for problem in problems:
        echo_warn(problem)
    if problems:
        raise typer.Exit(code=2)
    echo_ok("配置检查通过")
