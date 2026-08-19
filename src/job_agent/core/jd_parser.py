"""详情页 HTML → 结构化 JD。纯函数，不碰网络也不碰数据库，便于单测。

数据源是详情页里的 ``<script type="application/ld+json">`` JobPosting 块——
猎聘为 SEO 输出的结构化数据，含完整 JD、行业、经验与学历要求，
比解析 HTML DOM 稳定得多；解析失败时回退到 ``data-selector="job-intro-content"``。
"""

from __future__ import annotations

import json
import re
from typing import Any

_LD_JSON_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)
_JOB_INTRO_RE = re.compile(r'data-selector="job-intro-content"[^>]*>(.*?)</dd>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")

# JD 里区分「职责」与「要求」的小标题。要求类放前面，匹配时取最靠前的一个。
REQ_HEADINGS = (
    "职位要求",
    "岗位要求",
    "任职要求",
    "任职资格",
    "任职条件",
    "职位资格",
    "岗位资格",
    "我们希望你",
    "我们期待你",
    "你需要具备",
    "技能要求",
    "能力要求",
    "人员要求",
    "基本要求",
    "应聘条件",
    "Requirements",
    "Qualifications",
)
RESP_HEADINGS = (
    "职位描述",
    "岗位描述",
    "职位职责",
    "岗位职责",
    "工作职责",
    "工作内容",
    "主要职责",
    "你将负责",
    "Responsibilities",
)

#: 解析结果的字段集合（不含 status）
FIELDS = (
    "title",
    "description",
    "responsibilities",
    "requirements",
    "industry",
    "experienceRequirements",
    "educationRequirements",
    "employmentType",
    "datePosted",
    "companyName",
    "companyUrl",
    "streetAddress",
)

EMPTY_DETAIL: dict[str, str] = dict.fromkeys(FIELDS, "")


def split_jd(text: str) -> tuple[str, str]:
    """按小标题把 JD 切成 ``(职责, 要求)``。切不出来时返回 ``("", "")``。"""
    best: int | None = None
    for heading in REQ_HEADINGS:
        idx = text.find(heading)
        if idx > 0 and (best is None or idx < best):
            best = idx
    if best is None:
        return "", ""
    head, tail = text[:best].strip(), text[best:].strip()
    # 去掉职责段开头的「岗位职责：」之类标题，正文本身更有分析价值
    for heading in RESP_HEADINGS:
        if head.startswith(heading):
            head = head[len(heading) :].lstrip("：:， \n")
            break
    return head, tail


def parse_detail(html: str) -> dict[str, str] | None:
    """从详情页 HTML 提取字段；页面既无 JobPosting 也无兜底节点时返回 ``None``。"""
    posting: dict[str, Any] | None = None
    for raw in _LD_JSON_RE.findall(html):
        try:
            # JD 字符串里含裸换行，标准 JSON 不允许，需 strict=False
            data = json.loads(raw, strict=False)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict) and data.get("@type") == "JobPosting":
            posting = data
            break

    if posting is None:
        match = _JOB_INTRO_RE.search(html)
        if not match:
            return None
        posting = {"description": _TAG_RE.sub("", match.group(1)).strip()}

    description = (posting.get("description") or "").strip()
    org = posting.get("hiringOrganization") or {}
    place = (posting.get("jobLocation") or {}).get("address") or {}
    responsibilities, requirements = split_jd(description)
    return {
        "title": posting.get("title") or "",
        "description": description,
        "responsibilities": responsibilities,
        "requirements": requirements,
        "industry": posting.get("industry") or "",
        "experienceRequirements": posting.get("experienceRequirements") or "",
        "educationRequirements": posting.get("educationRequirements") or "",
        "employmentType": posting.get("employmentType") or "",
        "datePosted": posting.get("datePosted") or "",
        "companyName": org.get("name") or "",
        "companyUrl": org.get("sameAs") or "",
        "streetAddress": place.get("streetAddress") or "",
    }
