"""后台任务的提交与查询。

队列里跑的都是**会发网络请求**的长活：采集（猎聘接口 / 详情页）与 LLM 打分
（按条调模型 API）。``[score]`` 重新打分刻意不进来——它不发请求、几千条一两秒，
排队只会让人多等一次轮询。
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, HTTPException

from job_agent.context import AppContext
from job_agent.core.matching import build_scorer
from job_agent.core.services import DetailService, SearchService
from job_agent.web.deps import ContextDep, TasksDep
from job_agent.web.schemas import (
    CreateTaskRequest,
    DetailTaskResult,
    LlmScoreTaskResult,
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
    """任务排队执行（只有一个 worker）：猎聘限流按 token 记账，并行只会更快被封。

    LLM 打分同样排队，但理由不同：它自己内部就按 ``[llm_score].concurrency``
    并发了，再让两个批次并行只会更快撞上各家的 RPM 限流，也让进度条读不懂。
    """
    _check_credentials(payload, context)
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


def _check_credentials(payload: CreateTaskRequest, context: AppContext) -> None:
    """提交前就把「跑不动」的情况挡掉：排进队列再失败，人得等一轮轮询才知道。"""
    settings = context.settings
    if payload.kind in (TaskKind.SEARCH, TaskKind.DETAIL):
        if not settings.account.user_token:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"猎聘账号 {settings.profile.account} 没配 user_token"
                    "（config/config.toml 的 [liepin.accounts.*]），无法执行采集任务"
                ),
            )
        return
    if payload.kind is TaskKind.LLM_SCORE:
        name = settings.llm_score_provider_name
        if settings.llm_score_active.api_key is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"接入点 {name} 没配 api_key（config/config.toml 的 "
                    f"[agent.providers.{name}]），无法调模型打分"
                ),
            )
        if not payload.params.job_ids:
            # 按条计费，「不传就全打」这种默认在任何入口都不该存在
            raise HTTPException(
                status_code=400, detail="LLM 打分必须指定 job_ids：按条计费，没有默认全打"
            )


# ------------------------------------------------------------------ runners


def _search_runner(
    payload: CreateTaskRequest, context: AppContext, manager: TaskManager
) -> Callable[[Task], TaskResult]:
    """搜索；``params.fetch_detail`` 为真（默认）时在同一个任务里接着抓 JD。

    合在一个任务里而不是自动排第二个任务：这样「搜完自动抓」是原子的——
    取消一次就全停，进度条也不会中途跳成另一条任务。
    """

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

        detail = None
        if payload.params.fetch_detail and not task.cancelRequested:
            detail = _fetch_details(payload, context, manager, task)

        return SearchTaskResult(
            totalFound=summary.total_found,
            totalNew=summary.total_new,
            keywords=[SearchKeywordResult.model_validate(r) for r in summary.results],
            remaining=summary.remaining,
            detail=detail,
        )

    return run


def _detail_runner(
    payload: CreateTaskRequest, context: AppContext, manager: TaskManager
) -> Callable[[Task], TaskResult]:
    def run(task: Task) -> TaskResult:
        return _fetch_details(payload, context, manager, task)

    return run


def _fetch_details(
    payload: CreateTaskRequest, context: AppContext, manager: TaskManager, task: Task
) -> DetailTaskResult:
    """抓 JD。search 与 detail 两种任务共用，保证两条路的行为完全一致。"""
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


def _llm_score_runner(
    payload: CreateTaskRequest, context: AppContext, manager: TaskManager
) -> Callable[[Task], TaskResult]:
    """LLM 打分：和 ``job llm-score`` 走同一个 :func:`build_scorer`。

    两个入口共用一份打分器，所以命令行和网页跑出来的分数必然是一套口径——
    各写一份的下场是「网页上 7 分、命令行 8 分」，而且查不出为什么。
    """

    def run(task: Task) -> TaskResult:
        scorer = build_scorer(
            context.settings, context.db, context.llm_scores, manager.progress_hook(task)
        )
        summary = scorer.run(
            payload.params.job_ids or [],
            force=payload.params.llm_force,
            concurrency=payload.params.llm_concurrency,
            stop_check=lambda: task.cancelRequested,
        )
        return LlmScoreTaskResult(
            requested=summary.requested,
            scored=summary.scored,
            skipped=summary.skipped,
            failed=summary.failed,
            cancelled=summary.cancelled,
            provider=summary.provider,
            model=summary.model,
            fingerprint=summary.fingerprint,
            errors=summary.errors,
        )

    return run


_RUNNERS = {
    TaskKind.SEARCH: _search_runner,
    TaskKind.DETAIL: _detail_runner,
    TaskKind.LLM_SCORE: _llm_score_runner,
}
