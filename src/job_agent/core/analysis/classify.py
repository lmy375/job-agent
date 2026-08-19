"""把一条职位判定到 (赛道, 角色)，以及经验档位的归一。"""

from __future__ import annotations

import re

from job_agent.core.analysis.rules import (
    ROLE_RULES,
    SIGNAL_MIN,
    STRONG_SIGNAL,
    signal_count,
)
from job_agent.tracks import AI, BACKEND, OTHER, SEC, WEB3, Track

#: 只靠搜索关键词兜底时，各赛道给出的默认角色
FALLBACK_ROLES: dict[Track, str] = {
    AI: "AI 其他",
    WEB3: "Web3 后端 / 基础设施",
    SEC: "安全开发 / 安全架构",
    BACKEND: "后端 / 架构",
}


def classify(
    job_name: str, description: str, keyword_track: Track | None = None
) -> tuple[Track, str]:
    """判定 ``(赛道, 角色)``。

    优先按职位名匹配 :data:`ROLE_RULES`；职位名看不出赛道时（如「技术专家」
    「负责人」），才退回「最先命中它的搜索关键词所属赛道」（由配置给出），
    且要求 JD 正文有足够的赛道信号词，否则归入「其他」而不是硬塞进某条赛道。
    """
    for track, role, pattern in ROLE_RULES:
        if re.search(pattern, job_name, re.I):
            # 「后端工程师」「架构师」「CTO」这类通用职位名看不出赛道，
            # 若 JD 正文密集出现某赛道的术语，按正文归属更准。
            # 只对 BACKEND 生效：OTHER 下的规则是「明确排除」（功能安全、毒理、非技术岗），
            # 让正文信号改判会把它们又拉回安全 / AI 赛道。
            if track == BACKEND:
                for candidate in (WEB3, SEC, AI):
                    if signal_count(description, candidate) >= STRONG_SIGNAL:
                        return candidate, role
            return track, role

    if keyword_track is None or keyword_track == OTHER:
        return OTHER, "未分类"

    role = FALLBACK_ROLES.get(keyword_track, "未分类")
    if signal_count(description, keyword_track) >= SIGNAL_MIN:
        return keyword_track, role
    return OTHER, "未分类"


_YEARS_RE = re.compile(r"(\d+)")

#: 经验档位的固定顺序（报告里按它展示，才看得出梯度）
YEARS_ORDER = ["经验不限", "1-3 年", "3-5 年", "5-10 年", "10 年以上"]


def norm_years(text: str) -> str:
    """把「3年以上」「2-8年」「7年以上」等自由写法归到统一档位。

    猎聘的经验字段是自由文本，直接统计会散成十几个长尾取值，
    统一按「起始年限」落到 5 个档里才能看出分布。
    """
    if not text or "不限" in text:
        return "经验不限"
    match = _YEARS_RE.search(text)
    if not match:
        return "经验不限"
    years = int(match.group(1))
    if years < 3:
        return "1-3 年"
    if years < 5:
        return "3-5 年"
    if years < 10:
        return "5-10 年"
    return "10 年以上"
