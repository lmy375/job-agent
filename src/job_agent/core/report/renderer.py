"""把统计结果渲染成一份自包含的 HTML 报告。

输入是 :func:`job_agent.core.analysis.analyze` 的输出 + profile 的 ``insights/`` 里的文字素材，
输出是一个不依赖任何外部资源的 HTML 文件（离线可看、可直接发人）。
"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any

from job_agent.config import Settings
from job_agent.core.analysis import Analysis, AnalysisRow, SkillStat, TrackStats
from job_agent.core.report.insights import (
    LEVELS,
    MATCH_TABLE_PLACEHOLDER,
    Insights,
    MatchRow,
    load_insights,
)
from job_agent.core.report.styles import CSS
from job_agent.errors import ReportError
from job_agent.log import get_logger
from job_agent.tracks import AI, BACKEND, SEC, WEB3

logger = get_logger(__name__)

TRACK_ORDER = [AI, WEB3, SEC, BACKEND]
# 跨赛道对比只放三条：分类色板前 3 槽位通过了 all-pairs 色觉分离校验，
# 且 Web3 只有个位数样本，放进来百分比没有意义，故用「后端」作为对照组。
CROSS_TRACKS = [AI, SEC, BACKEND]
TRACK_DESC = {
    AI: "大模型 / Agent / AI Infra / AI 平台",
    WEB3: "区块链、加密资产、钱包与交易基础设施",
    SEC: "安全研究、攻防、安全开发与 AI 安全",
    BACKEND: "通用后端、架构与技术管理",
}

def e(s: Any) -> str:
    return html.escape(str(s))


def bar_rows(
    items: list[SkillStat], top: int = 14, color_var: str = "--series-1"
) -> str:
    """横向条形：单序列，统一用一个颜色（分类数据不做值映射着色）。"""
    items = [i for i in items if i.count > 0][:top]
    if not items:
        return '<p class="empty">该赛道样本中未出现可统计的关键词。</p>'
    top_pct = max(i.pct for i in items) or 1
    out = ['<div class="bars">']
    for item in items:
        w = item.pct / top_pct * 100
        out.append(
            f'<div class="bar-row" title="{e(item.name)}：{item.count} 条 JD 提及'
            f'（{item.pct:.0f}%）">'
            f'<div class="bar-label">{e(item.name)}</div>'
            f'<div class="bar-track"><div class="bar-fill" '
            f'style="width:{w:.1f}%;background:var({color_var})"></div></div>'
            f'<div class="bar-val">{item.pct:.0f}<span class="pct">%</span></div>'
            f"</div>"
        )
    out.append("</div>")
    return "".join(out)


def count_bars(items: list[tuple[str, int]], top: int = 12) -> str:
    """把 ``(名称, 条数)`` 的长尾分布换算成占比后画成条形。"""
    total = sum(n for _, n in items) or 1
    return bar_rows(
        [SkillStat(name=k, count=n, pct=n / total * 100) for k, n in items[:top]], top=top
    )


def skill_table(skills: dict[str, list[SkillStat]], count: int) -> str:
    """技能出现率的表格视图（每张图都要有可读的表格孪生体）。"""
    rows = []
    for group, items in skills.items():
        for item in items:
            if item.count:
                rows.append((group, item.name, item.count, item.pct))
    rows.sort(key=lambda r: -r[3])
    body = "".join(
        f"<tr><td>{e(g)}</td><td>{e(n)}</td><td class='num'>{c}</td>"
        f"<td class='num'>{p:.1f}%</td></tr>"
        for g, n, c, p in rows
    )
    return (
        f"<details class='tbl'><summary>表格视图 · 全部技能词命中率"
        f"（样本 {count} 条）</summary>"
        f"<table><thead><tr><th>分类</th><th>技能 / 关键词</th>"
        f"<th class='num'>JD 数</th><th class='num'>占比</th></tr></thead>"
        f"<tbody>{body}</tbody></table></details>"
    )


def job_table(jobs: list[AnalysisRow], top: int = 25) -> str:
    body = "".join(
        f"<tr><td><a href='{e(j.url)}' target='_blank' rel='noopener'>"
        f"{e(j.jobName)}</a></td>"
        f"<td>{e(j.company)}</td><td>{e(j.salary)}</td>"
        f"<td>{e(j.workYears)}</td><td>{e(j.role)}</td></tr>"
        for j in jobs[:top]
    )
    return (
        f"<details class='tbl'><summary>薪资最高的 {min(top, len(jobs))} 个岗位</summary>"
        f"<table><thead><tr><th>职位</th><th>公司</th><th>薪资</th>"
        f"<th>经验</th><th>角色</th></tr></thead><tbody>{body}</tbody></table></details>"
    )


def stat(value: str, label: str, note: str = "") -> str:
    return (
        f"<div class='stat'><div class='stat-v'>{e(value)}</div>"
        f"<div class='stat-l'>{e(label)}</div>"
        f"{f'<div class=stat-n>{e(note)}</div>' if note else ''}</div>"
    )


def grouped_track_bars(data: Analysis, group: str, top: int = 10) -> str:
    """同一技能分类在各赛道的命中率并排对比，用于「跨赛道差异」。

    只对比用户关心的三条赛道：分类色板的前 3 个槽位在明暗两种模式下都通过了
    all-pairs 色觉分离校验，再多一个槽位（黄）会和橙撞车。
    """
    tracks = [t for t in CROSS_TRACKS if t in data.tracks]
    names: list[str] = []
    for t in tracks:
        for item in data.tracks[t].skills.get(group, []):
            if item.count and item.name not in names:
                names.append(item.name)
    # 按「在各赛道的最大命中率」排序，取前 top 个
    def peak(name: str) -> float:
        return max(
            (
                item.pct
                for t in tracks
                for item in data.tracks[t].skills.get(group, [])
                if item.name == name
            ),
            default=0.0,
        )

    names = sorted(names, key=lambda n: -peak(n))[:top]
    if not names:
        return ""
    # 条形按组内最大值等比放大（数值标签一直在，不会因此读错量级）
    scale = max((peak(n) for n in names), default=0.0) or 1.0
    legend = "".join(
        f"<span class='lg'><i style='background:var(--series-{i + 1})'></i>{e(t)}"
        f"<span class='lg-n'>n={data.tracks[t].count}</span></span>"
        for i, t in enumerate(tracks)
    )
    rows = []
    for name in names:
        cells = []
        for i, t in enumerate(tracks):
            pct = next(
                (
                    item.pct
                    for item in data.tracks[t].skills.get(group, [])
                    if item.name == name
                ),
                0.0,
            )
            cells.append(
                f"<div class='mini-row' title='{e(t)} · {e(name)}：{pct:.0f}%'>"
                f"<div class='mini'><div class='mini-fill' style='width:{pct / scale * 100:.1f}%;"
                f"background:var(--series-{i + 1})'></div></div>"
                f"<span class='mini-v'>{pct:.0f}%</span></div>"
            )
        rows.append(
            f"<div class='grp-row'><div class='bar-label'>{e(name)}</div>"
            f"<div class='grp-cells'>{''.join(cells)}</div></div>"
        )
    return f"<div class='legend'>{legend}</div><div class='grp'>{''.join(rows)}</div>"


SMALL_SAMPLE = 20  # 样本少于这个数就不画百分比图，只列原始职位


def small_sample_section(track: str, info: TrackStats, insight: str) -> str:
    """样本太小时的呈现：不画百分比条形图（7 条里的 1 条 = 14%，图会骗人），
    直接把职位逐条列出来，让读者自己判断。"""
    body = "".join(
        f"<tr><td><a href='{e(j.url)}' target='_blank' rel='noopener'>{e(j.jobName)}</a></td>"
        f"<td>{e(j.company)}</td><td>{e(j.salary)}</td>"
        f"<td>{e(j.workYears)}</td><td>{e(j.role)}</td></tr>"
        for j in info.jobs
    )
    return f"""
<section class="track" id="track-{e(track)}">
  <h2>{e(track)} 赛道<span class="sub">{e(TRACK_DESC.get(track, ''))}</span></h2>
  <div class="insight warn">
    <p><strong>样本仅 {info.count} 条，不足以做占比统计。</strong>
    这本身就是结论：在页首那组筛选条件下，{e(track)} 赛道的技术岗几乎不存在。
    占比图在这种样本量下会骗人（7 条里的 1 条就是 14%），
    所以下面直接列出全部原始职位。</p>
  </div>
  {insight}
  <div class="scroll"><table class="matrix"><thead><tr><th>职位</th><th>公司</th>
    <th>薪资</th><th>经验</th><th>角色</th></tr></thead><tbody>{body}</tbody></table></div>
</section>
"""


def track_section(track: str, info: TrackStats, insight: str) -> str:
    sal = ""
    if info.salaryMedianHigh and info.salaryMedianLow:
        sal = f"{info.salaryMedianLow:.0f}–{info.salaryMedianHigh:.0f} 万"
    # 「最主要角色」跳过「AI 其他」这类兜底桶，展示真正有信息量的角色
    named = [(r, n) for r, n in info.roles if "其他" not in r and "未分类" not in r]
    top_role = named[0] if named else (info.roles[0] if info.roles else ("—", 0))
    stats = (
        stat(str(info.count), "有效 JD 数")
        + stat(
            sal or "—",
            "年薪中位区间",
            f"90 分位 {info.salaryP90High:.0f} 万" if info.salaryP90High else "",
        )
        + stat(
            f"{info.meets100 / info.salaryParsed * 100:.0f}%" if info.salaryParsed else "—",
            "薪资上限真正 ≥100 万",
            f"{info.meets100}/{info.salaryParsed} 条",
        )
        + stat(top_role[0], "最主要角色", f"{top_role[1]} 条")
        + stat(
            f"{info.education[0][0]}" if info.education else "—",
            "最常见学历门槛",
            f"{info.education[0][1]} 条" if info.education else "",
        )
    )

    skill_blocks = []
    for group, items in info.skills.items():
        if not any(item.count for item in items):
            continue
        skill_blocks.append(
            f"<div class='card'><h4>{e(group)}</h4>{bar_rows(items)}</div>"
        )

    return f"""
<section class="track" id="track-{e(track)}">
  <h2>{e(track)} 赛道<span class="sub">{e(TRACK_DESC.get(track, ''))}</span></h2>
  <div class="stats">{stats}</div>
  <div class="insight">{insight}</div>
  <div class="card-grid g2">
    <div class="card"><h4>角色构成</h4>{count_bars(info.roles)}</div>
    <div class="card"><h4>经验要求</h4>{count_bars(info.workYears)}</div>
    <div class="card"><h4>所属行业</h4>{count_bars(info.industries, top=8)}</div>
    <div class="card"><h4>公司规模</h4>{count_bars(info.companySize, top=8)}</div>
  </div>
  <h3>技能与能力要求（各技能词在该赛道 JD 中的出现率）</h3>
  <div class="card-grid">{"".join(skill_blocks)}</div>
  {skill_table(info.skills, info.count)}
  {job_table(info.jobs)}
</section>
"""


def match_table(rows: list[MatchRow]) -> str:
    """能力项 × 市场需求 × 简历现状的矩阵表格。"""
    if not rows:
        return "<p class='empty'>未配置匹配矩阵（insights/match-matrix.toml）。</p>"
    body = []
    for row in rows:
        label, css_class = LEVELS[row.level]
        body.append(
            f"<tr><td>{row.capability}</td>"
            f"<td><span class='pill {css_class}'>{label}</span></td>"
            f"<td>{row.demand}</td><td>{row.resume}</td></tr>"
        )
    return (
        "<div class='scroll'><table class='matrix'><thead><tr>"
        "<th>能力项</th><th>判定</th><th>市场需求（本次样本实测）</th><th>简历现状</th>"
        f"</tr></thead><tbody>{''.join(body)}</tbody></table></div>"
    )


def _salary_label(settings: Settings) -> str:
    """把配置里的薪资门槛写成「年薪 100 万+」这样的人话。"""
    floor = settings.search.salary_floor
    if not floor:
        return "不限薪资"
    kind = settings.search.salary_kind or "年薪"
    return f"{kind} {floor / 10000:.0f} 万+"


def render(data: Analysis, insights: Insights, settings: Settings) -> str:
    """渲染完整 HTML。``data`` 来自 :func:`job_agent.core.analysis.analyze`。"""
    tracks = [t for t in TRACK_ORDER if t in data.tracks]
    total = data.total
    counts = data.trackCounts
    address = settings.search.address or "全国"
    salary_label = _salary_label(settings)
    who = settings.profile.name or "求职者"

    # 全样本里薪资上限真正达标的比例。写死过一次（60%），样本一变就过期，改成实算。
    caps = [row.salaryHigh for row in data.rows if row.salaryHigh]
    threshold = (settings.search.salary_floor or 0) / 10000
    meets_pct = (
        round(sum(1 for cap in caps if cap >= threshold) / len(caps) * 100)
        if caps and threshold
        else 0
    )

    overview_bars = count_bars([(t, counts[t]) for t in TRACK_ORDER if counts.get(t)], top=6)
    toc = "".join(f"<a href='#track-{e(t)}'>{e(t)} 赛道</a>" for t in tracks)
    toc += "<a href='#cross'>跨赛道对比</a>"
    if insights.advice:
        toc += "<a href='#advice'>给我的建议</a>"

    sections = "".join(
        (small_sample_section if data.tracks[t].count < SMALL_SAMPLE else track_section)(
            t, data.tracks[t], insights.for_track(t)
        )
        for t in tracks
    )

    cross = f"""
<section id="cross">
  <h2>跨赛道对比<span class="sub">同一能力在不同赛道里的权重差异（Web3 样本不足，用「后端」作对照组）</span></h2>
  <h3>编程语言</h3>{grouped_track_bars(data, "语言", top=9)}
  <h3>AI 技术方向</h3>{grouped_track_bars(data, "AI 技术方向", top=12)}
  <h3>工程与平台能力</h3>{grouped_track_bars(data, "工程与平台", top=10)}
  <h3>软素质与背景</h3>{grouped_track_bars(data, "软素质与背景", top=9)}
</section>
"""

    advice = insights.advice.replace(MATCH_TABLE_PLACEHOLDER, match_table(insights.match_rows))
    warning = ""
    if insights.warnings:
        warning = "<div class='meta'>素材提示：" + "；".join(e(w) for w in insights.warnings) + "</div>"

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(address)} {e(salary_label)} 技术岗市场分析 · AI / Web3 / 安全</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header class="hero">
  <h1>{e(address)} · {e(salary_label)} 技术岗市场分析</h1>
  <p>基于猎聘公开职位数据，抓取 {total} 份完整 JD 原文，按赛道拆解「在招什么岗位、
     要什么技能」，并对照{e(who)}的简历给出能力提升建议。</p>
  <div class="meta">数据源：猎聘（liepin.com）职位详情页结构化数据 ·
    筛选条件：工作地 {e(address)}、{e(salary_label)} · 生成时间：{datetime.now():%Y-%m-%d %H:%M}</div>
  {warning}
  <div class="toc">{toc}</div>
</header>

<section id="overview">
  <h2>样本概览<span class="sub">{total} 份有效 JD 的赛道分布</span></h2>
  <div class="card-grid">
    <div class="card"><h4>赛道分布</h4>{overview_bars}</div>
    <div class="card"><h4>关于这份数据</h4>
      <p style="font-size:13.5px;color:var(--text-secondary)">
      按 AI / 区块链 / 安全方向的关键词在猎聘检索「{e(address)} + {e(salary_label)}」，
      再逐条抓取详情页里的 JobPosting 结构化数据，得到 {total} 份含完整职责与
      要求正文的 JD。赛道与角色由职位名规则判定，技能占比是「该赛道内提及某关键词的
      JD 比例」。</p>
      <p style="font-size:13.5px;color:var(--muted)">
      两点必须说明：① 猎聘单个关键词最多返回 120 条，所以这是<strong>趋势样本而非全量普查</strong>，
      占比可横向比较赛道权重，绝对值不宜当作市场总量。
      ② 猎聘的薪资筛选是「<strong>区间重叠</strong>」而不是「下限 ≥ 门槛」，还会漏进明显不达标的条目
      （样本里甚至有实习生岗），实际只有 <strong>{meets_pct}%</strong> 的职位薪资上限真正够到门槛——
      各赛道的具体比例见下面每节的「薪资上限真正 ≥100 万」。</p>
    </div>
  </div>
</section>

{sections}
{cross}
{advice}

<footer>
  由 <code>job-agent</code> 生成 · 原始数据与 JD 全文存于
  <code>{e(settings.storage.database.name)}</code>
  （<code>jobs</code> / <code>job_details</code> 两张表）· 重新生成：<code>job report</code>
</footer>
</div>
</body>
</html>
"""


def build(
    data: Analysis,
    settings: Settings,
    output: Path | None = None,
    insights: Insights | None = None,
) -> Path:
    """渲染并写盘，返回报告路径。"""
    target = output or settings.report.output
    resolved = load_insights(settings.report.insights_dir) if insights is None else insights
    html_text = render(data, resolved, settings)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html_text, encoding="utf-8")
    except OSError as exc:
        raise ReportError(f"报告写入失败（{target}）：{exc}") from exc
    logger.info("报告已生成：%s（%.0f KB）", target, target.stat().st_size / 1024)
    return target
