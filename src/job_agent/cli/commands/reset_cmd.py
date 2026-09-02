"""``job reset``：删掉数据库文件并重建空库。

仓库不做向后兼容：库结构一变就重建，不写迁移、不补列、不回填
（见 CLAUDE.md 的硬规则）。数据随时可以用 `job search` + `job detail` 重新采集。

**投递记录会一起没**——猎聘没有查询投递记录的接口，本地这张表是唯一的账本，
所以默认要确认一次，并且单独把已有的投递条数报出来。

删的是**当前 profile** 的库，所以确认提示里必须先报出 profile 名：
不带 --profile 时用的是默认 profile，删错人的库是没法撤销的。
"""

from __future__ import annotations

from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok, echo_warn


def reset(
    ctx: typer.Context,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过确认。")] = False,
) -> None:
    state: CliState = ctx.obj
    context = state.context()
    settings = context.settings
    path = settings.storage.database

    jobs = context.jobs.count()
    applications = sum(context.applications.status_counts().values())

    typer.secho(f"即将删除 profile「{settings.profile_name}」的数据库：{path}", bold=True)
    typer.echo(f"  职位 {jobs} 条，投递记录 {applications} 条")
    if applications:
        echo_warn("投递记录删掉就找不回来了——猎聘没有查询投递记录的接口，这张表是唯一的账本")
    if not yes:
        typer.confirm(f"确认删掉 {settings.profile_name} 的库并重建？", abort=True)

    removed = context.db.drop()
    # 重新建一套空表，后续命令不需要再想「库还在不在」
    context.db.setup()
    for item in removed:
        typer.echo(f"  · 已删除 {item.name}")
    echo_ok(f"已重建空库：{path}")
    # 删的是文件：别的进程握着的是被删掉的 inode，还会读到旧数据
    typer.echo("\n如果 `job web` 正在跑，重启它——老连接指向的还是删掉的那个文件。")
    typer.echo("下一步：job search 重新采集，再跑 job detail 抓 JD。")
