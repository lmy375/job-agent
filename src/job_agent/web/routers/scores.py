"""重新打分。

页面上的「重新打分」按钮 = 命令行的 ``job score``：走的是同一个
:func:`~job_agent.core.matching.refresh`，读当前 profile 的 ``[score]``
**现在的样子**，把全库重算一遍、整表重写 ``job_scores``。
所以两条入口算出来的分数与全库排名永远一样——打分是确定性的那一半，
不因为「从哪儿点的」而变。

刻意**不进后台任务队列**：打分不发网络请求、不受猎聘限流约束，几千条也就一两秒。
排队反而让人不知道该等谁，而队列存在的理由（限流按 token 记账、串行才安全）
对打分根本不成立。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from job_agent.core.matching import refresh
from job_agent.web.deps import ContextDep
from job_agent.web.schemas import ScoreRefreshResponse

router = APIRouter(prefix="/scores", tags=["score"])


@router.post("/refresh", response_model=ScoreRefreshResponse, summary="按当前 [score] 重新打分")
def refresh_scores(context: ContextDep) -> ScoreRefreshResponse:
    """整表重写：分数之间有关系（``rank`` 是全库排名），改一条权重会牵动别人的名次。

    落库的是**全量、未过滤**的分数与排名——``[score].salary_floor_wan`` 那类门槛
    是「这次看什么」，不该影响写进库里的名次。
    """
    settings = context.settings
    if not settings.score.signals:
        raise HTTPException(
            status_code=400,
            detail=(
                f"当前 profile 的 [score] 段里没有任何 [[score.signals]]"
                f"（{settings.profile_file or settings.profile_dir}）："
                "所有岗位都会是 0 分，排序没有意义。先在「配置」页填信号表。"
            ),
        )

    result = refresh(context.db, settings)
    if not result.jobs:
        raise HTTPException(
            status_code=400,
            detail="库里没有带 JD 的职位，打不了分。先在「采集任务」里跑一次搜索。",
        )
    return ScoreRefreshResponse(
        scored=len(result.jobs),
        unique=len(result.unique_ids),
        offTrack=sum(1 for job in result.jobs if job.off_track),
        fingerprint=result.fingerprint,
        status=context.scores.status(settings.score.fingerprint),
    )
