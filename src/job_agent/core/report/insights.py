"""载入 ``config/insights`` 下人工撰写的定性结论。

这部分刻意做成「用户自己的素材」而不是代码里的字符串常量：
它是对某一批数据的解读，会随数据版本重写，属于内容而非逻辑。
素材缺失不会让报告失败——定量部分照样出，只是少了文字解读。
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from job_agent.log import get_logger
from job_agent.tracks import AI, BACKEND, SEC, WEB3, Track

logger = get_logger(__name__)

#: 赛道 -> 文件名
TRACK_FILES: dict[Track, str] = {
    AI: "ai.html",
    WEB3: "web3.html",
    SEC: "security.html",
    BACKEND: "backend.html",
}
ADVICE_FILE = "advice.html"
MATRIX_FILE = "match-matrix.toml"
#: advice.html 里的占位符，渲染时替换成匹配矩阵表格
MATCH_TABLE_PLACEHOLDER = "{{match_table}}"

#: 匹配矩阵的判定等级 -> (展示文案, CSS 类名)
LEVELS: dict[str, tuple[str, str]] = {
    "strong": ("优势", "p-strong"),
    "mid": ("有但没讲透", "p-mid"),
    "gap": ("缺口", "p-gap"),
}


@dataclass(slots=True)
class MatchRow:
    """能力项 × 市场需求 × 简历现状的一行。"""

    capability: str
    level: str
    demand: str
    resume: str


@dataclass(slots=True)
class Insights:
    tracks: dict[Track, str] = field(default_factory=dict)
    advice: str = ""
    match_rows: list[MatchRow] = field(default_factory=list)
    #: 加载过程中的问题，报告页脚会提示
    warnings: list[str] = field(default_factory=list)

    def for_track(self, track: Track) -> str:
        return self.tracks.get(track, "")


def load_insights(insights_dir: Path) -> Insights:
    """从目录读取全部素材。目录或文件不存在时只记警告，不抛异常。"""
    insights = Insights()
    if not insights_dir.is_dir():
        message = f"未找到 insights 目录：{insights_dir}，报告将只包含定量部分"
        logger.warning(message)
        insights.warnings.append(message)
        return insights

    for track, filename in TRACK_FILES.items():
        path = insights_dir / filename
        if path.is_file():
            insights.tracks[track] = path.read_text(encoding="utf-8").strip()
        else:
            insights.warnings.append(f"缺少 {filename}（{track} 赛道无文字解读）")

    advice_path = insights_dir / ADVICE_FILE
    if advice_path.is_file():
        insights.advice = advice_path.read_text(encoding="utf-8").strip()
    else:
        insights.warnings.append(f"缺少 {ADVICE_FILE}（报告没有「给我的建议」章节）")

    matrix_path = insights_dir / MATRIX_FILE
    if matrix_path.is_file():
        insights.match_rows = _load_matrix(matrix_path, insights.warnings)

    return insights


def _load_matrix(path: Path, warnings: list[str]) -> list[MatchRow]:
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (tomllib.TOMLDecodeError, OSError) as exc:
        warnings.append(f"{path.name} 解析失败：{exc}")
        return []

    rows: list[MatchRow] = []
    for raw in data.get("row", []):
        level = str(raw.get("level", "")).strip()
        if level not in LEVELS:
            warnings.append(
                f"{path.name} 有一行的 level={level!r} 不合法（应为 {'/'.join(LEVELS)}），已跳过"
            )
            continue
        rows.append(
            MatchRow(
                capability=str(raw.get("capability", "")),
                level=level,
                demand=str(raw.get("demand", "")),
                resume=str(raw.get("resume", "")),
            )
        )
    return rows
