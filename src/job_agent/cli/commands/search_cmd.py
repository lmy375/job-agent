"""``job search``：批量搜索职位入库，紧接着抓详情页解析 JD。

两步合成一条命令：搜索给出「有哪些岗」，详情页给出「这岗在干什么」——
后者是打分与判断的唯一依据，光有列表没有 JD 的库是没用的。

两步都**可重跑**：搜索按 jobId 去重，详情按已抓状态跳过。所以详情被限流打断后
直接重跑这条命令即可，已完成的不会重抓。只想刷一遍列表就加 ``--no-detail``。
"""

from __future__ import annotations

from typing import Annotated

import typer

from job_agent.cli.state import CliState, echo_ok, echo_warn
from job_agent.core.services import DetailService, SearchService


def search(
    ctx: typer.Context,
    keyword: Annotated[
        list[str] | None,
        typer.Option("--keyword", "-k", help="只搜这些关键词（可多次传入），默认用配置里的全部。"),
    ] = None,
    pages: Annotated[
        int | None, typer.Option("--pages", help="每个关键词最多翻几页，默认取配置值（上限 6）。")
    ] = None,
    limit: Annotated[
        int | None, typer.Option("--limit", "-n", help="这一轮最多抓多少条 JD，便于试跑。")
    ] = None,
    retry_failed: Annotated[
        bool, typer.Option("--retry-failed", help="把之前抓取失败的 JD 也重新抓一遍。")
    ] = False,
    no_detail: Annotated[
        bool, typer.Option("--no-detail", help="只搜列表，不抓 JD。")
    ] = False,
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

    if no_detail:
        typer.echo("\n已跳过 JD 抓取（--no-detail）。不抓 JD 就没法打分，记得回头补上。")
        return

    _fetch_details(state, limit=limit, retry_failed=retry_failed)


def _fetch_details(state: CliState, limit: int | None, retry_failed: bool) -> None:
    """抓详情页解析 JD。

    慢是正常的（服务端实测约 10 次 / 60s 滑动窗口），进度直接落库，
    中断后重跑自动跳过已完成项。
    """
    context = state.context()
    typer.secho("\n开始抓 JD（串行 + 随机休眠，急不得，中断后重跑会接着抓）", bold=True)

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
