"""后台采集任务的提交与查询。"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from job_agent.context import AppContext
from job_agent.core.services import DetailService, SearchService
from job_agent.web.deps import ContextDep, TasksDep
from job_agent.web.schemas import (
    CreateTaskRequest,
    DetailTaskResult,
    SearchKeywordResult,
    SearchTaskResult,
    TaskDetail,
    TaskKind,
    TaskListResponse,
    TaskResponse,
    TaskResult,
    TaskView,
)
from job_agent.web.tasks import Task, TaskManager

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.get("", response_model=TaskListResponse, summary="任务列表")
def list_tasks(tasks: TasksDep) -> TaskListResponse:
    running = tasks.running()
    return TaskListResponse(
        tasks=[TaskView.model_validate(task) for task in tasks.list()],
        running=running.id if running else None,
    )


@router.get("/{task_id}", response_model=TaskResponse, summary="任务详情（含日志）")
def get_task(tasks: TasksDep, task_id: str) -> TaskResponse:
    task = tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return TaskResponse(task=TaskDetail.model_validate(task))


@router.post("", response_model=TaskResponse, status_code=202, summary="提交任务")
def create_task(
    payload: CreateTaskRequest, context: ContextDep, tasks: TasksDep
) -> TaskResponse:
    """任务排队执行（只有一个 worker）：猎聘限流按 token 记账，并行只会更快被封。"""
    needs_token = payload.kind in (TaskKind.SEARCH, TaskKind.DETAIL)
    if needs_token and not context.settings.account.user_token:
        raise HTTPException(
            status_code=400,
            detail=(
                f"猎聘账号 {context.settings.profile.account} 没配 user_token"
                "（config/config.toml 的 [liepin.accounts.*]），无法执行采集任务"
            ),
        )

    runner = _RUNNERS[payload.kind](payload, context, tasks)
    task = tasks.submit(payload.kind, runner, payload.params)
    return TaskResponse(task=TaskDetail.model_validate(task))


@router.post("/{task_id}/cancel", response_model=TaskResponse, summary="请求取消任务")
def cancel_task(tasks: TasksDep, task_id: str) -> TaskResponse:
    """协作式取消：服务会在当前条目结束后停下，已完成的进度都已落库。"""
    task = tasks.cancel(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"任务 {task_id} 不存在")
    return TaskResponse(task=TaskDetail.model_validate(task))


# ------------------------------------------------------------------ runners


def _search_runner(
    payload: CreateTaskRequest, context: AppContext, manager: TaskManager
) -> Callable[[Task], TaskResult]:
    def run(task: Task) -> TaskResult:
        with context.client() as client:
            service = SearchService(
                context.settings, client, context.jobs, manager.progress_hook(task)
            )
            summary = service.run(
                keywords=payload.params.keywords,
                max_pages=payload.params.pages,
                stop_check=lambda: task.cancelRequested,
            )
        if summary.aborted and not task.cancelRequested:
            raise RuntimeError(summary.aborted_reason or "搜索中止")
        return SearchTaskResult(
            totalFound=summary.total_found,
            totalNew=summary.total_new,
            keywords=[SearchKeywordResult.model_validate(r) for r in summary.results],
            remaining=summary.remaining,
        )

    return run


def _detail_runner(
    payload: CreateTaskRequest, context: AppContext, manager: TaskManager
) -> Callable[[Task], TaskResult]:
    def run(task: Task) -> TaskResult:
        service = DetailService(
            context.settings,
            context.jobs,
            context.details,
            on_progress=manager.progress_hook(task),
        )
        try:
            summary = service.run(
                limit=payload.params.limit,
                retry_failed=payload.params.retry_failed,
                stop_check=lambda: task.cancelRequested,
            )
        finally:
            service.close()
        return DetailTaskResult(
            total=summary.total,
            fetched=summary.fetched,
            statuses=dict(summary.statuses),
            elapsedSeconds=round(summary.elapsed, 1),
            abortedReason=summary.aborted_reason,
        )

    return run


_RUNNERS = {
    TaskKind.SEARCH: _search_runner,
    TaskKind.DETAIL: _detail_runner,
}
