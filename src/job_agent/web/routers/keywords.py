"""搜索关键词的职位数统计。

只数条数，不归类——「这个关键词属于哪条赛道」是分析，不在这个仓库里。
"""

from __future__ import annotations

from fastapi import APIRouter

from job_agent.web.deps import ContextDep
from job_agent.web.schemas import KeywordsResponse

router = APIRouter(tags=["jobs"])


@router.get("/keywords", response_model=KeywordsResponse, summary="各搜索关键词的职位数")
def keywords(context: ContextDep) -> KeywordsResponse:
    return KeywordsResponse(keywords=context.jobs.keyword_counts())
