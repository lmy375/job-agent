"""``job detail``：抓取职位详情页并解析 JD。"""

from __future__ import annotations

from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok
from job_agent.core.services import DetailService


def detail(
    ctx: typer.Context,
    limit: Annotated[
        int | None, typer.Option("--limit", "-n", help="本次最多抓多少条，便于试跑。")
    ] = None,
    retry_failed: Annotated[
        bool, typer.Option("--retry-failed", help="把之前抓取失败的也重新抓一遍。")
    ] = False,
) -> None:
    state: CliState = ctx.obj
    context = state.context()
    service = DetailService(
        context.settings, context.jobs, context.details, on_progress=state.progress()
    )
    try:
        summary = service.run(limit=limit, retry_failed=retry_failed)
    finally:
        service.close()

    if summary.total:
        echo_ok(
            f"完成 {summary.fetched}/{summary.total} 条，成功 {summary.ok} 条，"
            f"耗时 {summary.elapsed / 60:.1f} 分钟"
        )
