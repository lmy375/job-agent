"""匹配层：``[score]`` 信号表的校验、打分、清单渲染。

打分是**分诊**，测试关心的也只是分诊行为：
权重加没加对、标题有没有加倍、不对口的有没有被压下去、理由有没有留下来。
不测「排第一的是不是最该投的」——那不是代码能回答的问题。

信号表现在是 profile.toml 的一段（不再是独立的 match.toml），所以「写错了要报错」
这类用例一律走真实路径：改 profile.toml → load_settings → ConfigError。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import PROFILE, PROFILE_TOML, make_detail, make_job
from job_agent.config import ScoreConfig, load_settings
from job_agent.core.dataset import JobFacts
from job_agent.core.matching import rank, render_shortlist, score_row
from job_agent.core.matching.shortlist import TODO
from job_agent.errors import ConfigError

#: PROFILE_TOML 里 [score] 之前的那一半：拼一份只改信号表的 profile.toml 用
_PROFILE_HEAD = PROFILE_TOML[: PROFILE_TOML.index("[score]")]


def load_score(project_root: Path, score_toml: str) -> ScoreConfig:
    """把 ``score_toml`` 塞进当前 profile 的 profile.toml，再走完整的加载路径。"""
    profile_file = project_root / "profiles" / PROFILE / "profile.toml"
    profile_file.write_text(_PROFILE_HEAD + score_toml, encoding="utf-8")
    return load_settings(PROFILE, project_root / "config" / "config.toml").score


# ---------------------------------------------------------------- 加载与校验


def test_score_section_loads(settings):
    assert [s.name for s in settings.score.signals] == ["Agent", "Python", "算法训练岗"]
    assert settings.score.title_multiplier == 2.0
    assert settings.score.require.penalty == -20.0


def test_bad_regex_is_config_error(project_root):
    """正则写错必须在读配置时炸，而不是打到一半才炸。"""
    with pytest.raises(ConfigError):
        load_score(project_root, '[[score.signals]]\nname="x"\nweight=1\npattern="([unclosed"\n')


def test_unknown_key_rejected(project_root):
    """拼错的配置项要报错，不能静默忽略。"""
    with pytest.raises(ConfigError):
        load_score(
            project_root,
            '[[score.signals]]\nname="x"\nweight=1\npattern="a"\nwieght=9\n',
        )


def test_empty_signals_loads_but_scores_nothing(project_root):
    """空表本身不是配置错误，但它排出来的全是 0 分——由 job score 拦（见 test_cli）。"""
    score = load_score(project_root, "[score]\ntitle_multiplier = 2.0\n")
    assert score.signals == []


# ---------------------------------------------------------------- 打分


def rules_of(*signals: tuple[str, float, str], require: str | None = None) -> ScoreConfig:
    data: dict = {"signals": [
        {"name": n, "weight": w, "pattern": p} for n, w, p in signals
    ]}
    if require is not None:
        data["require"] = {"pattern": require, "penalty": -20.0}
    return ScoreConfig.model_validate(data)


def row(title: str = "工程师", description: str = "") -> JobFacts:
    return JobFacts(jobId=1, jobName=title, company="某公司", description=description)


def test_title_hit_is_doubled():
    rules = rules_of(("Agent", 10, "agent"))
    in_title = score_row(row("Agent 工程师"), rules)
    in_body = score_row(row("工程师", "负责 agent 开发"), rules)
    assert in_title.score == 20.0
    assert in_body.score == 10.0


def test_title_and_body_hit_counts_once():
    """同一条信号在标题和正文都出现时只算标题那份，不叠加。"""
    rules = rules_of(("Agent", 10, "agent"))
    scored = score_row(row("Agent 工程师", "agent agent agent"), rules)
    assert scored.score == 20.0


def test_negative_signal_lands_in_penalties():
    rules = rules_of(("Agent", 10, "agent"), ("算法训练", -12, "预训练"))
    scored = score_row(row("Agent 工程师", "负责模型预训练"), rules)
    assert scored.score == 20.0 - 12.0
    assert [h.name for h in scored.hits] == ["Agent"]
    assert [h.name for h in scored.penalties] == ["算法训练"]


def test_require_penalty_when_off_track():
    rules = rules_of(("Python", 5, "python"), require="agent|大模型")
    scored = score_row(row("后端工程师", "熟悉 python 与 mysql"), rules)
    assert scored.off_track is True
    assert scored.score == 5.0 - 20.0
    assert "不含目标赛道关键词" in scored.concerns()


def test_require_satisfied_no_penalty():
    rules = rules_of(("Python", 5, "python"), require="agent|大模型")
    scored = score_row(row("大模型应用工程师", "熟悉 python"), rules)
    assert scored.off_track is False
    assert scored.score == 5.0


def test_reasons_are_preserved():
    """理由比分数重要：分数不可信，理由才让人能复核排序。"""
    rules = rules_of(("Agent", 10, "agent"), ("Python", 5, "python"))
    scored = score_row(row("Agent 工程师", "python"), rules)
    assert scored.reasons() == "Agent（标题）、Python"


def test_hits_sorted_by_weight():
    rules = rules_of(("小", 1, "aaa"), ("大", 9, "bbb"))
    scored = score_row(row("工程师", "aaa bbb"), rules)
    assert [h.name for h in scored.hits] == ["大", "小"]


# ---------------------------------------------------------------- rank（读库）

AGENT_JD = "岗位职责：负责 Agent 平台建设\n任职要求：熟悉 Python 与大模型"
BACKEND_JD = "岗位职责：负责订单服务\n任职要求：熟悉 Java、MySQL 与分布式"


def test_rank_orders_by_score(context):
    context.jobs.upsert_many(
        [
            make_job(1, jobName="Agent 工程师", salary="80-100k·15薪"),
            make_job(2, jobName="后端开发", salary="80-100k·15薪"),
        ],
        keyword="AI Agent",
    )
    context.details.upsert(make_detail(1, description=AGENT_JD))
    context.details.upsert(make_detail(2, description=BACKEND_JD))

    ranked = rank(context.db, context.settings)
    assert [j.job_id for j in ranked] == [1, 2]
    assert ranked[0].score > ranked[1].score


def test_rank_attaches_salary_band(context):
    """薪资只有税前一种口径，直接来自 JD 文案的解析结果。"""
    context.jobs.upsert_many(
        [make_job(1, jobName="Agent 工程师", salary="80-100k·15薪")], keyword="AI Agent"
    )
    context.details.upsert(make_detail(1, description=AGENT_JD))

    job = rank(context.db, context.settings)[0]
    # 80-100k·15薪 = 120–150 万
    assert job.salary_low == pytest.approx(120.0)
    assert job.salary_high == pytest.approx(150.0)


def test_rank_filters_by_salary_ceiling(context):
    """门槛过滤的是**上限**：下限低但上限够高的岗位必须留下。"""
    context.jobs.upsert_many(
        [
            make_job(1, jobName="Agent 工程师", salary="50-80k·20薪"),  # 上限 160 万
            make_job(2, jobName="Agent 专家", salary="30-40k·12薪"),  # 上限 48 万
        ],
        keyword="AI Agent",
    )
    for job_id in (1, 2):
        context.details.upsert(make_detail(job_id, description=AGENT_JD))

    ranked = rank(context.db, context.settings, floor_wan=135.0)
    assert [j.job_id for j in ranked] == [1]


def test_rank_skips_jobs_without_jd(context):
    context.jobs.upsert_many([make_job(1, jobName="Agent 工程师")], keyword="AI Agent")
    context.details.upsert(make_detail(1, status="no_jd"))

    assert rank(context.db, context.settings) == []


# ---------------------------------------------------------------- 清单渲染


def test_shortlist_leaves_judgement_blank(context, settings):
    context.jobs.upsert_many(
        [make_job(1, jobName="Agent 工程师", salary="80-100k·15薪")], keyword="AI Agent"
    )
    context.details.upsert(make_detail(1, description=AGENT_JD))

    ranked = rank(context.db, context.settings)
    markdown = render_shortlist(ranked, settings, limit=5)

    # 确定性的部分必须在
    assert "Agent 工程师" in markdown
    assert "80-100k·15薪" in markdown
    # 判断的部分必须留白，一处不少：硬门槛 / 投不投 / 投递口径。
    # +1 是头部说明里也提到了这个标记（告诉读的人「哪三处要填」）
    assert markdown.count(TODO) == 1 + 3
    # 口径提醒必须在：薪资只有税前一种口径，且按上限过滤
    assert "薪资一律是税前" in markdown
    assert "薪资按上限过滤" in markdown


def test_shortlist_limit_is_respected(context, settings):
    jobs = [make_job(i, jobName=f"Agent 工程师 {i}", salary="80-100k·15薪") for i in range(1, 6)]
    context.jobs.upsert_many(jobs, keyword="AI Agent")
    for i in range(1, 6):
        # JD 各不相同，否则会被按正文去重
        context.details.upsert(make_detail(i, description=f"{AGENT_JD}\n项目编号 {i}"))

    ranked = rank(context.db, context.settings)
    assert len(ranked) == 5

    markdown = render_shortlist(ranked, settings, limit=2)
    assert markdown.count(TODO) == 1 + 2 * 3  # 头部说明 1 处 + 每条 3 处
    assert "共 5 条进入评分，取前 2 条" in markdown


# ---------------------------------------------------------------- TOML 转义守卫
#
# TOML 基本字符串里 `\b` 是合法的「退格符」转义。于是手写
# `pattern = "\bagent\b"` 会静默变成 <退格>agent<退格>：
# 正则编译得过、一条也匹配不上、排名看着正常但结论全错。
# 没有任何报错的 bug 最贵，所以必须在读配置时拦下来。


def test_toml_backspace_escape_is_rejected(project_root):
    with pytest.raises(ConfigError) as exc:
        load_score(
            project_root,
            '[[score.signals]]\nname = "Agent"\nweight = 10\npattern = "\\bagent\\b"\n',
        )
    assert "控制字符" in str(exc.value)
    assert "单引号" in str(exc.value), "报错必须给出可照做的修法"


def test_toml_literal_string_works(project_root):
    """单引号字面量字符串不处理转义，是模板推荐的写法。"""
    score = load_score(
        project_root,
        "[[score.signals]]\nname = 'Agent'\nweight = 10\npattern = '\\bagent\\b'\n",
    )
    assert score.signals[0].pattern == r"\bagent\b"
    assert score_row(row("Agent 工程师"), score).score == 20.0


def test_toml_double_escaped_also_works(project_root):
    score = load_score(
        project_root,
        '[[score.signals]]\nname = "Agent"\nweight = 10\npattern = "\\\\bagent\\\\b"\n',
    )
    assert score.signals[0].pattern == r"\bagent\b"


def test_require_pattern_escape_is_also_guarded(project_root):
    with pytest.raises(ConfigError, match="控制字符"):
        load_score(
            project_root,
            '[score.require]\npattern = "\\bagent\\b"\n\n'
            "[[score.signals]]\nname = 'x'\nweight = 1\npattern = 'a'\n",
        )


def test_shipped_template_is_valid():
    """仓库里的模板必须始终可解析——它是所有用户的起点。"""
    import tomllib

    from job_agent.config import find_project_root

    template = find_project_root() / "config" / "templates" / "profile.toml"
    with open(template, "rb") as fh:
        score = ScoreConfig.model_validate(tomllib.load(fh)["score"])

    assert len(score.signals) >= 20
    assert any(s.weight > 0 for s in score.signals)
    assert any(s.weight < 0 for s in score.signals)
    # 模板里的正则必须真的在工作，不能是一堆退格符
    scored = score_row(row("AI Agent 平台工程师", "熟悉 Python、MCP 协议"), score)
    assert scored.score > 0
    assert "AI Agent / 智能体" in scored.reasons()
