"""``job profile``：管理 profile——一个用户或一种求职场景。

真正干活的在共享内核（``core/profile.py``）：列表、新建、设默认三件事
Web 的配置页也要做，两边各写一遍的下场是「命令行切了、网页上没切」。
这里只负责把结果排版成终端能看的样子。

刻意不提供 ``rm``：删一个 profile 就是删它的文件夹，那一下会连着简历和
几百条采集记录一起没，交给用户自己动手更诚实。
"""

from __future__ import annotations

from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.config import (
    default_config_path,
    find_project_root,
    list_profiles,
    load_global_settings,
    profiles_root,
)
from job_agent.core.profile import (
    ProfileSummary,
    create_profile,
    set_default_profile,
    summarize_profiles,
)
from job_agent.errors import ConfigError

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("list", help="列出所有 profile。")
def list_cmd() -> None:
    settings = load_global_settings(find_project_root())
    rows = summarize_profiles(settings)
    if not rows:
        echo_warn(f"还没有任何 profile（{profiles_root(settings.root, settings)}）")
        typer.echo("跑 `job profile new <名字>` 建一个。")
        return

    typer.echo(f"{profiles_root(settings.root, settings)}\n")
    typer.secho(f"{'':<2}{'名字':<16}{'职位':>8}{'已投':>6}  简历  偏好  信号", bold=True)
    for row in rows:
        typer.echo(
            f"{'→' if row.isDefault else ' '} {row.name:<16}"
            f"{_count(row.jobs):>8}{_count(row.applied):>6}"
            f"  {_flag(row.hasResume)}    {_flag(row.hasPreferences)}   {_signals(row):>3}"
        )
    if settings.profiles.default is None and len(rows) > 1:
        typer.echo(
            "\n没有设默认 profile：每条命令都得带 --profile，"
            "或跑 `job profile use <名字>`。"
        )


def _flag(present: bool) -> str:
    return "✓" if present else "×"


def _count(value: int | None) -> str:
    """库还没建（或配置坏了）显示 ``-``，别拿 0 冒充「采过但一条都没有」。"""
    return "-" if value is None else str(value)


def _signals(row: ProfileSummary) -> str:
    return "×" if not row.signals else str(row.signals)


@app.command("new", help="新建一个 profile（从 config/templates/ 拷模板）。")
def new(
    name: Annotated[str, typer.Argument(help="profile 名字，同时是目录名。")],
    force: Annotated[bool, typer.Option("--force", help="目录已存在时也往里补文件。")] = False,
) -> None:
    settings = load_global_settings(find_project_root())
    target = create_profile(settings, name, force=force)
    echo_ok(f"已创建 profile：{target}")

    if settings.profiles.default is None:
        set_default_profile(settings, name)
        echo_ok(f'已设为默认 profile（[profiles].default = "{name}"）')

    typer.echo(
        f"\n下一步：让 Claude 跑 `/job-init` 带你把简历、求职偏好与关键词填完"
        f"（会写进 {target}），或自己照文件里的注释改；"
        f"填好后 `job -p {name} config validate` 自检。\n"
        "猎聘 token 与模型 key 不在这里——它们跟人无关，住全局 config/config.toml。"
    )


@app.command("use", help="把某个 profile 设为默认（不带 --profile 时用它）。")
def use(name: Annotated[str, typer.Argument(help="profile 名字。")]) -> None:
    settings = load_global_settings(find_project_root())
    if name not in list_profiles(profiles_root(settings.root, settings)):
        known = "、".join(list_profiles(profiles_root(settings.root, settings))) or "（一个都没有）"
        raise ConfigError(
            f"profile 不存在：{profiles_root(settings.root, settings) / name}\n  已有的：{known}"
        )
    written = set_default_profile(settings, name)
    echo_ok(f"默认 profile 已设为 {name}（{written or default_config_path(settings.root)}）")


@app.command("path", help="打印当前（或指定）profile 的目录。")
def path_cmd(ctx: typer.Context) -> None:
    state: CliState = ctx.obj
    typer.echo(state.context().settings.profile_dir)
