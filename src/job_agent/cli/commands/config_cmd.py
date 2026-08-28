"""``job config``：初始化、查看、校验配置。"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.config import default_config_path, example_config_path, find_project_root
from job_agent.config.loader import CONFIG_DIR_NAME, env_file_path
from job_agent.core.matching import load_rules
from job_agent.errors import ConfigError

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("init", help="从模板生成 config/ 下缺失的文件。")
def init(
    force: Annotated[bool, typer.Option("--force", help="已存在时也覆盖。")] = False,
) -> None:
    """按「模板 → 目标」逐个补齐，已存在的默认不动。

    只生成骨架；里面填什么由 `/job-init` skill 引导（或自己照注释改）。
    """
    root = find_project_root()
    config_dir = root / CONFIG_DIR_NAME
    if not example_config_path(root).is_file():
        raise ConfigError(f"缺少配置模板：{example_config_path(root)}")

    items: list[tuple[Path, Path, str]] = [
        (example_config_path(root), default_config_path(root), "搜索条件与关键词"),
        (config_dir / ".env.example", env_file_path(root), "填入 LIEPIN_USER_TOKEN"),
        (config_dir / "resume.example.md", config_dir / "resume.md", "你的简历"),
        (config_dir / "preferences.example.md", config_dir / "preferences.md", "你的求职偏好"),
        (config_dir / "match.example.toml", config_dir / "match.toml", "岗位匹配信号表"),
        (config_dir / "insights.example", config_dir / "insights", "报告里的文字素材"),
    ]

    for source, target, note in items:
        if not source.exists():
            continue
        if target.exists() and not force:
            echo_warn(f"{_rel(target, root)} 已存在，跳过（加 --force 覆盖）")
            continue
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            shutil.copyfile(source, target)
        echo_ok(f"已生成 {_rel(target, root)}（{note}）")

    typer.echo(
        "\n下一步：让 Claude 跑 `/job-init` 带你把 token、简历与求职偏好填完，"
        "或自己按文件里的注释改；填好后 job config validate 自检。"
    )


def _rel(path: Path, root: Path) -> str:
    """尽量用相对路径展示，输出短一点。"""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


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
    for section in (
        "profile", "search", "liepin", "detail", "storage",
        "match", "report", "web", "logging",
    ):
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
    typer.echo(f"preferences  {settings.profile.preferences}")
    typer.echo(f"match        {settings.match.rules}")
    typer.echo(f"shortlist    {settings.match.shortlist_output}")
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
        problems.append(
            f"简历文件不存在：{settings.profile.resume}（跑 /job-init 或 job config init）"
        )
    if not settings.profile.preferences.is_file():
        problems.append(
            f"求职偏好文件不存在：{settings.profile.preferences}（跑 /job-init 或 job config init）"
        )
    if not settings.match.rules.is_file():
        problems.append(
            f"匹配信号表不存在：{settings.match.rules}"
            "（跑 /job-init 或 job config init；缺它 job match / job shortlist 跑不了）"
        )
    else:
        # 存在就顺手解析一遍：正则写错、权重写成字符串这类问题要在这里暴露，
        # 而不是等 job match 跑到一半才炸
        try:
            load_rules(settings.match.rules)
        except ConfigError as exc:
            problems.append(str(exc))
    if not settings.report.insights_dir.is_dir():
        problems.append(
            f"insights 目录不存在：{settings.report.insights_dir}（报告将只有定量部分）"
        )

    for problem in problems:
        echo_warn(problem)
    if problems:
        raise typer.Exit(code=2)
    echo_ok("配置检查通过")
