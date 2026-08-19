"""搜索方向（searchKeyword）统计。"""

from __future__ import annotations

from fastapi import APIRouter

from job_agent.web.deps import ContextDep
from job_agent.web.schemas import KeywordsResponse

router = APIRouter(tags=["jobs"])


@router.get("/keywords", response_model=KeywordsResponse, summary="各方向的职位数")
def keywords(context: ContextDep) -> KeywordsResponse:
    rows = context.jobs.keyword_counts()
    for row in rows:
        row["track"] = context.settings.search.track_for_keyword(row["keyword"])
    return KeywordsResponse(keywords=rows)
