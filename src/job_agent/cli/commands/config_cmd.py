"""``job config``：初始化、查看、校验**全局**配置。

per-profile 的那一半（简历、偏好、关键词、信号表）归 ``job profile``——
这里只管 ``config/config.toml``：猎聘账号密钥、限速、模型接入点、Web、日志。
``show`` / ``path`` / ``validate`` 看的是「全局 + 当前 profile」合起来的结果。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.config import default_config_path, example_config_path, find_project_root
from job_agent.core.matching import load_rules
from job_agent.errors import ConfigError

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("init", help="从模板生成全局 config/config.toml。")
def init(
    force: Annotated[bool, typer.Option("--force", help="已存在时也覆盖。")] = False,
) -> None:
    """只生成全局配置的骨架；简历、关键词那些跟着 profile 走，归 `job profile new`。

    里面填什么由 `/job-init` skill 引导（或自己照注释改）。
    """
    root = find_project_root()
    source = example_config_path(root)
    target = default_config_path(root)
    if not source.is_file():
        raise ConfigError(f"缺少配置模板：{source}")

    if target.exists() and not force:
        echo_warn(f"{_rel(target, root)} 已存在，跳过（加 --force 覆盖）")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        echo_ok(f"已生成 {_rel(target, root)}（猎聘账号密钥、限速、模型接入点、Web、日志）")

    typer.echo(
        "\n下一步：\n"
        "  1. `job profile new <名字>` 建一个 profile——一个 profile 就是一个人 / "
        "一种求职场景，简历、关键词、数据库都在它自己的目录里\n"
        "  2. 让 Claude 跑 `/job-init` 把 token、简历与求职偏好填完，"
        "或自己照文件里的注释改；填好后 job config validate 自检\n"
        "密钥（猎聘 token、模型 key）都写在 config/config.toml 里——它不进版本库，"
        "跟人无关的东西只有这一处落盘。"
    )


def _rel(path: Path, root: Path) -> str:
    """尽量用相对路径展示，输出短一点。"""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


@app.command("show", help="打印当前生效的配置（密钥已打码）。")
def show(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    state: CliState = ctx.obj
    settings = state.context().settings
    # 密钥字段是 SecretStr，序列化成 JSON 时自动变 ``**********``，不需要额外脱敏
    if as_json:
        typer.echo(settings.model_dump_json(indent=2))
        return

    typer.secho(f"profile：{settings.profile_name}（{settings.profile_dir}）", bold=True)
    typer.echo(f"全局配置：{settings.config_file or '（未找到，使用内置默认值）'}")
    typer.echo(f"profile 配置：{settings.profile_file or '（缺 profile.toml，全用默认值）'}")
    typer.echo(f"项目根目录：{settings.root}")
    token_state = "已配置" if settings.account.user_token else "未配置（无法访问接口）"
    typer.echo(f"猎聘账号：{settings.profile.account}（token {token_state}）")
    for section in (
        "profiles", "profile", "search", "liepin", "detail", "storage",
        "match", "agent", "report", "web", "logging",
    ):
        block = getattr(settings, section)
        typer.secho(f"\n[{section}]", fg=typer.colors.CYAN)
        for key, value in block.model_dump(mode="json").items():
            if key == "providers":
                # 接入点按模型读；标出选中的那个，密钥只报「填了没」
                for name, provider in block.providers.items():
                    mark = "→" if name == block.provider else " "
                    state_text = "key 已填" if provider.api_key else "key 未填"
                    extra = f"  base_url={provider.base_url}" if provider.base_url else ""
                    typer.echo(
                        f"  {mark} {name:<12}{provider.api:<10}{provider.model:<24} "
                        f"{state_text}  {provider.structured_output}{extra}"
                    )
                continue
            if key == "accounts":
                # 账号按模型读；标出当前 profile 选中的那个，token 只报「填了没」
                for name, account in block.accounts.items():
                    mark = "→" if name == settings.profile.account else " "
                    filled = "token 已填" if account.user_token else "token 未填"
                    typer.echo(f"  {mark} {name:<12}{filled}")
                continue
            if key == "groups":
                # 关键词分组按模型读，字段名有 schema 兜着
                for group in block.groups:
                    flag = "" if group.enabled else "（已禁用）"
                    typer.echo(f"  {group.track:<6}{flag} {'、'.join(group.keywords)}")
                continue
            typer.echo(f"  {key:<20}{value}")


@app.command("path", help="打印当前 profile 的配置与数据文件路径。")
def path(
    ctx: typer.Context,
    as_json: Annotated[bool, typer.Option("--json", help="输出 JSON。")] = False,
) -> None:
    """``--json`` 是给 skill 用的：它们要写简历、读 JD，不该再硬编码
    ``config/resume.md`` 这类路径——路径随 profile 变，问这里要。
    输出与 Web 的 ``/api/config`` 里的 ``paths`` 同构。
    """
    state: CliState = ctx.obj
    settings = state.context().settings
    if as_json:
        typer.echo(settings.paths().model_dump_json(indent=2))
        return

    typer.echo(f"profile      {settings.profile_name}")
    typer.echo(f"root         {settings.root}")
    typer.echo(f"config       {settings.config_file}")
    typer.echo(f"profileDir   {settings.profile_dir}")
    typer.echo(f"profileFile  {settings.profile_file}")
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

    if settings.profile_file is None:
        problems.append(
            f"缺 profile.toml：{settings.profile_dir / 'profile.toml'}"
            "（搜索条件与关键词全走默认值；跑 job profile new 重建，或从 config/templates/ 拷一份）"
        )
    if not settings.account.user_token:
        problems.append(
            f"猎聘账号 {settings.profile.account} 没配 user_token"
            "（config/config.toml 的 [liepin.accounts.*]），无法搜索或投递"
        )
    if not settings.search.keywords:
        problems.append("[[search.groups]] 里没有启用任何关键词，job search 无事可做")
    if not settings.profile.resume.is_file():
        problems.append(f"简历文件不存在：{settings.profile.resume}（跑 /job-init）")
    if not settings.profile.preferences.is_file():
        problems.append(f"求职偏好文件不存在：{settings.profile.preferences}（跑 /job-init）")
    if not settings.match.rules.is_file():
        problems.append(
            f"匹配信号表不存在：{settings.match.rules}"
            "（跑 /job-init；缺它 job match / job shortlist 跑不了）"
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
