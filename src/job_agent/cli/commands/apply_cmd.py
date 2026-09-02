"""``job apply``：投递职位。

投递是不可撤销的外部动作，所以默认要确认一次；``--yes`` 可跳过（脚本里用）。
"""

from __future__ import annotations

from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.core.liepin.constants import JOB_KINDS
from job_agent.core.services import ApplyService

_ICONS = {
    "ok": "✅",
    "already_applied": "↩️",
    "closed": "🚫",
    "failed": "❌",
    "error": "❌",
    "skipped": "⚠️",
}


def apply(
    ctx: typer.Context,
    job_ids: Annotated[list[int], typer.Argument(help="要投递的 jobId，可传多个。")],
    job_kind: Annotated[
        str | None,
        typer.Option(
            "--job-kind",
            help="手动指定职位类型（1 猎头 / 2 普通），用于数据库里没有的职位。",
        ),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="跳过确认。")] = False,
) -> None:
    state: CliState = ctx.obj
    context = state.context()

    if job_kind is not None and job_kind not in JOB_KINDS:
        raise typer.BadParameter("--job-kind 只能是 1（猎头）或 2（普通）")

    typer.echo(f"准备投递 {len(job_ids)} 个职位：")
    for job_id in job_ids:
        job = context.jobs.get(job_id)
        label = f"{job.jobName} @ {job.company}（{job.salary}）" if job else "不在数据库中"
        typer.echo(f"  · {job_id}  {label}")
    if not yes:
        typer.confirm("确认投递？", abort=True)

    with context.client() as client:
        service = ApplyService(client, context.jobs, context.applications, state.progress())
        summary = service.run(job_ids, job_kind)

    for outcome in summary.outcomes:
        icon = _ICONS.get(outcome.status, "?")
        typer.echo(f"{icon} [{outcome.jobId}] {outcome.message}  {outcome.label}")

    if summary.aborted:
        echo_warn(f"{summary.aborted_reason}")
        echo_warn(f"未投递：{summary.remaining}")
        raise typer.Exit(code=6)
    echo_ok(f"成功投递 {summary.succeeded}/{len(job_ids)} 个")
