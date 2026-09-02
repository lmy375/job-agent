"""``job search``：批量搜索职位入库。"""

from __future__ import annotations

from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.core.services import SearchService


def search(
    ctx: typer.Context,
    keyword: Annotated[
        list[str] | None,
        typer.Option("--keyword", "-k", help="只搜这些关键词（可多次传入），默认用配置里的全部。"),
    ] = None,
    pages: Annotated[
        int | None, typer.Option("--pages", help="每个关键词最多翻几页，默认取配置值（上限 6）。")
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="只打印将要搜索的关键词，不发请求。")
    ] = False,
) -> None:
    state: CliState = ctx.obj
    context = state.context()
    todo = list(keyword) if keyword else context.settings.search.keywords

    if dry_run:
        typer.echo(f"将搜索 {len(todo)} 个关键词，每个最多 "
                   f"{pages or context.settings.search.max_pages} 页：")
        for item in todo:
            typer.echo(f"  · {item}")
        return

    with context.client() as client:
        service = SearchService(context.settings, client, context.jobs, state.progress())
        summary = service.run(keywords=todo, max_pages=pages)

    if summary.aborted:
        echo_warn(f"整批中止：{summary.aborted_reason}")
        echo_warn(f"未完成的关键词：{'、'.join(summary.remaining)}")
        raise typer.Exit(code=6)

    failed = [r.keyword for r in summary.results if r.error]
    if failed:
        echo_warn(f"{len(failed)} 个关键词出错：{'、'.join(failed)}")
    echo_ok(f"命中 {summary.total_found} 条，新增 {summary.total_new} 条，库内共 "
            f"{context.jobs.count()} 条")
