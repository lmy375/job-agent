"""``job align``：拿 LLM 分给信号表体检。

测的是统计对不对、边界稳不稳：命中均分与差值的方向、子模式拆分、探针的标题 / 正文
分家、漏网与误报的判定、没有 LLM 分时的退出码。**不测**「这条信号该不该删」——
那是判断，代码不回答。
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from conftest import PROFILE, make_detail, make_job
from job_agent.cli import app
from job_agent.core.matching import AlignThresholds, align
from job_agent.core.matching.align import spearman, split_alternatives
from job_agent.core.storage import LlmScoreEntry

runner = CliRunner()

#: 六条岗位：三条 Agent 工程岗（模型认可）、两条训练岗（模型不看）、一条没打 LLM 分。
#: JD 各不相同，免得被按正文去重合掉。
#: JD 要够长才算有效（见 dataset.MIN_DESCRIPTION_LEN），所以各拼一段职责文字。
_PAD = "岗位职责：与产品、设计协作，负责需求评审、方案设计、代码实现与线上运维保障。"
JOBS = [
    (1, "Agent 平台工程师", "负责 Agent 平台与工具调用，Python 后端。" + _PAD, 9, 8),
    (2, "智能体研发", "构建智能体工作流，熟悉 Python 与 RAG 检索。" + _PAD, 8, 7),
    (3, "AI Agent 后端", "大模型 Agent 应用落地，FastAPI 服务开发。" + _PAD, 7, 6),
    (4, "大模型算法工程师", "负责大模型预训练与强化学习算法研究。" + _PAD, 2, 3),
    (5, "训练框架研发", "分布式模型训练框架，大模型算子性能优化。" + _PAD, 3, 2),
    (6, "Agent 前端", "智能体产品的前端页面与交互组件开发。" + _PAD, None, None),
]


def seed(context, salary: str = "80-100k·20薪") -> None:
    context.jobs.upsert_many(
        [make_job(i, jobName=title, salary=salary) for i, title, *_ in JOBS], keyword="AI Agent"
    )
    for i, _title, jd, *_ in JOBS:
        context.details.upsert(make_detail(i, description=jd))
    entries = [
        LlmScoreEntry(jobId=i, appealScore=ap, fitScore=fit, appealReasons=[f"依据 {i}"])
        for i, _t, _jd, ap, fit in JOBS
        if ap is not None
    ]
    context.llm_scores.upsert_many(entries, provider="p", model="m", fingerprint="f")


def run(config_path, *args: str):
    return runner.invoke(app, ["--profile", PROFILE, "--config", str(config_path), *args])


@pytest.fixture
def config_path(project_root):
    return project_root / "config" / "config.toml"


# ---------------------------------------------------------------- 纯函数


def test_spearman_perfect_and_inverse():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_handles_ties_and_degenerate_input():
    assert spearman([1, 1, 2, 3], [1, 2, 2, 3]) == pytest.approx(0.8333, abs=1e-3)
    assert spearman([1, 2], [1, 2]) is None
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def test_split_alternatives_respects_groups_classes_and_escapes():
    pattern = r"(?a:\brag\b|\bllm\b)|知识库|[a|b]c|向量(检索|数据库)|转义\|不拆"
    assert split_alternatives(pattern) == [
        r"(?a:\brag\b|\bllm\b)",
        "知识库",
        "[a|b]c",
        "向量(检索|数据库)",
        r"转义\|不拆",
    ]
    assert split_alternatives("单个") == ["单个"]


# ---------------------------------------------------------------- 报告


def test_align_report_statistics(context):
    seed(context)
    report = align(context.db, context.settings, split=True, probes=[r"\bpython\b", "智能体"])

    assert report.viewSize == 6
    assert report.scored == 5  # 6 号没打 LLM 分，不进统计
    assert report.approvedInView == 3
    assert report.verdictLabels == ["p / m / f"]
    assert not report.mixed_verdicts
    assert report.spearmanAppeal is not None and report.spearmanAppeal > 0.8

    by_name = {s.name: s for s in report.signals}
    agent = by_name["Agent"]
    assert agent.hits.hits == 3 and agent.titleHits == 3
    assert agent.deltaAppeal is not None and agent.deltaAppeal > 0
    assert agent.hits.approvedRate == 1.0 and agent.hits.lowRate == 0.0

    training = by_name["算法训练岗"]
    assert training.hits.hits == 2
    assert training.deltaAppeal is not None and training.deltaAppeal < 0
    assert training.hits.lowRate == 1.0
    subs = {s.pattern: s.stat.hits for s in training.subPatterns}
    assert subs == {"预训练": 1, "强化学习": 1, "模型训练": 1}

    # 关键词把认可的三条都排在前面：窗口 100 全收，没有漏网；
    # 两条训练岗也在窗口里（总共只有 5 条），它们就是「进了窗口但模型不看」的误报
    assert report.recall[-1].approved == 3
    assert report.missed == []
    assert {j.jobId for j in report.falsePositives} == {4, 5}

    python, agentic = report.probes
    assert python.title.hits == 0 and python.body.hits == 2  # 1 号、2 号正文提到 Python
    assert agentic.title.hits == 1 and agentic.body.hits == 0  # 2 号标题；6 号没 LLM 分不计


def test_align_missed_and_false_positive_follow_thresholds(context):
    seed(context)
    tight = AlignThresholds(top=1)
    report = align(context.db, context.settings, thresholds=tight)
    # 窗口只有 1 名，另外两条认可的就成了漏网
    assert [j.jobId for j in report.missed] == [2, 3] or len(report.missed) == 2
    assert all(j.viewRank > 1 for j in report.missed)

    loose = AlignThresholds(top=100, low_ceiling=9)
    report = align(context.db, context.settings, thresholds=loose)
    # 把「明确不看」的线抬到 9，认可里吸引力 ≤9 的都算误报
    assert {j.jobId for j in report.falsePositives} >= {1, 2, 3, 4, 5}


def test_align_flags_mixed_verdicts(context):
    seed(context)
    context.llm_scores.upsert_many(
        [LlmScoreEntry(jobId=3, appealScore=7, fitScore=6)],
        provider="p", model="other-model", fingerprint="f",
    )
    report = align(context.db, context.settings)
    assert report.mixed_verdicts and len(report.verdictLabels) == 2


def test_align_snippets_only_when_asked(context):
    seed(context)
    quiet = align(context.db, context.settings, probes=["python"])
    assert quiet.probes[0].snippets == []
    loud = align(context.db, context.settings, probes=["python"], snippets=True)
    assert len(loud.probes[0].snippets) == 2
    assert all("Python" in s.text for s in loud.probes[0].snippets)


# ---------------------------------------------------------------- CLI


def test_cli_align_without_llm_scores_exits_1(config_path, context):
    context.jobs.upsert_many([make_job(1)], keyword="AI Agent")
    context.details.upsert(make_detail(1, description="Agent 平台，Python 后端。" + _PAD))
    result = run(config_path, "align")
    assert result.exit_code == 1
    assert "llm-score" in result.stdout


def test_cli_align_prints_report(config_path, context):
    seed(context)
    result = run(config_path, "align", "--split", "--probe", "python", "--context", "--why")
    assert result.exit_code == 0, result.stdout + result.stderr
    out = result.stdout
    assert "有 LLM 分 5 条" in out
    assert "算法训练岗" in out and "预训练" in out  # --split 拆出了子模式
    assert "探针" in out and "python" in out
    assert "漏网" in out and "误报" in out


def test_cli_align_json_contract(config_path, context, tmp_path):
    seed(context)
    result = run(config_path, "align", "--json", "--top", "2")
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["thresholds"]["top"] == 2
    assert payload["scored"] == 5
    assert {s["name"] for s in payload["signals"]} == {"Agent", "Python", "算法训练岗"}
    assert len(payload["missed"]) == 1  # 前 2 名之外还有一条认可的

    target = tmp_path / "align.json"
    assert run(config_path, "align", "-o", str(target)).exit_code == 0
    assert json.loads(target.read_text(encoding="utf-8"))["scored"] == 5


def test_cli_align_help_listed():
    assert "align" in runner.invoke(app, ["--help"]).stdout
