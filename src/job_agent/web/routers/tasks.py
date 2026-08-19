"""后台采集任务的提交与查询。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException

from job_agent.context import AppContext
from job_agent.core.analysis import analyze
from job_agent.core.report import build, load_insights
from job_agent.core.services import DetailService, SearchService
from job_agent.web.deps import ContextDep, TasksDep
from job_agent.web.schemas import CreateTaskRequest, TaskListResponse, TaskResponse
from job_agent.web.tasks import Task, TaskKind, TaskManager

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskListResponse, summary="任务列表")
def list_tasks(tasks: TasksDep) -> TaskListResponse:
    running = tasks.running()
    return TaskListResponse(
        tasks=[task.as_dict(with_logs=False) for task in tasks.list()],
        running=running.id if running else None,
    )


@router.get("/{task_id}", response_model=TaskResponse, summary="任务详情（含日志）")
def get_task(tasks: TasksDep, task_id: str) -> TaskResponse:
    task = tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return TaskResponse(task=task.as_dict())


@router.post("", response_model=TaskResponse, status_code=202, summary="提交任务")
def create_task(
    payload: CreateTaskRequest, context: ContextDep, tasks: TasksDep
) -> TaskResponse:
    """任务排队执行（只有一个 worker）：猎聘限流按 token 记账，并行只会更快被封。"""
    if payload.kind in (TaskKind.SEARCH, TaskKind.DETAIL) and not context.settings.token:
        raise HTTPException(
            status_code=400, detail="未配置 LIEPIN_USER_TOKEN，无法执行采集任务"
        )

    runner = _RUNNERS[payload.kind](payload, context, tasks)
    params = payload.model_dump(exclude_none=True, exclude={"kind"})
    task = tasks.submit(payload.kind, runner, **params)
    return TaskResponse(task=task.as_dict())


@router.post("/{task_id}/cancel", response_model=TaskResponse, summary="请求取消任务")
def cancel_task(tasks: TasksDep, task_id: str) -> TaskResponse:
    """协作式取消：服务会在当前条目结束后停下，已完成的进度都已落库。"""
    task = tasks.cancel(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return TaskResponse(task=task.as_dict())


# ------------------------------------------------------------------ runners


def _search_runner(
    payload: CreateTaskRequest, context: AppContext, manager: TaskManager
) -> Callable[[Task], dict[str, Any]]:
    def run(task: Task) -> dict[str, Any]:
        with context.client() as client:
            service = SearchService(
                context.settings, client, context.jobs, manager.progress_hook(task)
            )
            summary = service.run(
                keywords=payload.keywords,
                max_pages=payload.pages,
                stop_check=lambda: task.cancel_requested,
            )
        if summary.aborted and not task.cancel_requested:
            raise RuntimeError(summary.aborted_reason or "搜索中止")
        return {
            "totalFound": summary.total_found,
            "totalNew": summary.total_new,
            "keywords": [
                {"keyword": r.keyword, "found": r.found, "new": r.new,
                 "truncated": r.truncated, "error": r.error}
                for r in summary.results
            ],
            "remaining": summary.remaining,
        }

    return run


def _detail_runner(
    payload: CreateTaskRequest, context: AppContext, manager: TaskManager
) -> Callable[[Task], dict[str, Any]]:
    def run(task: Task) -> dict[str, Any]:
        service = DetailService(
            context.settings,
            context.jobs,
            context.details,
            on_progress=manager.progress_hook(task),
        )
        try:
            summary = service.run(
                limit=payload.limit,
                retry_failed=payload.retry_failed,
                stop_check=lambda: task.cancel_requested,
            )
        finally:
            service.close()
        return {
            "total": summary.total,
            "fetched": summary.fetched,
            "statuses": dict(summary.statuses),
            "elapsedSeconds": round(summary.elapsed, 1),
            "abortedReason": summary.aborted_reason,
        }

    return run


def _report_runner(
    payload: CreateTaskRequest, context: AppContext, manager: TaskManager
) -> Callable[[Task], dict[str, Any]]:
    def run(task: Task) -> dict[str, Any]:
        hook = manager.progress_hook(task)
        from job_agent.core.services import ProgressEvent

        hook(ProgressEvent("正在统计 JD……"))
        data = analyze(context.db, context.settings, dedupe=payload.dedupe)
        if not data["total"]:
            raise RuntimeError("没有可用的 JD，请先执行搜索与详情抓取")
        insights = load_insights(context.settings.report.insights_dir)
        hook(ProgressEvent(f"正在渲染报告（{data['total']} 份有效 JD）……"))
        path = build(data, context.settings, insights=insights)
        hook(ProgressEvent(f"报告已生成：{path}"))
        return {
            "path": str(path),
            "total": data["total"],
            "tracks": dict(data["trackCounts"]),
            "warnings": insights.warnings,
        }

    return run


_RUNNERS = {
    TaskKind.SEARCH: _search_runner,
    TaskKind.DETAIL: _detail_runner,
    TaskKind.REPORT: _report_runner,
}
