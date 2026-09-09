"""LLM 语义打分：并发、跳过、失败降级、取消、提示词覆盖与过期判定。

**一次模型请求都不发**：``build_scorer`` 允许注入 llm，测试传一个假客户端。
所以这里验证的全是编排逻辑——真正的判断质量没法用单测保证，
但「跳过规则错了会白花几百次调用的钱」这类事必须锁死。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from conftest import make_detail, make_job
from job_agent.config import Settings
from job_agent.context import AppContext
from job_agent.core.llm import APPEAL_SYSTEM, FIT_SYSTEM, load_score_prompts
from job_agent.core.matching import LlmVerdict, build_scorer
from job_agent.core.storage import JobQuery
from job_agent.errors import ConfigError


class FakeLLM:
    """记录每次 invoke 的消息，按 jobId 决定返回什么。

    ``fail_on`` 里的职位抛异常——单条失败不该拖垮整批，这是要锁死的行为之一。
    """

    def __init__(self, fail_on: set[int] | None = None) -> None:
        self.messages: list[list[tuple[str, str]]] = []
        self.fail_on = fail_on or set()
        self._lock = threading.Lock()

    def invoke(self, messages: list[tuple[str, str]]) -> LlmVerdict:
        with self._lock:
            self.messages.append(messages)
        user = messages[-1][1]
        if any(f"jobId {jid}" in user or f"职位：岗{jid}" in user for jid in self.fail_on):
            raise RuntimeError("模型抽风")
        return LlmVerdict(
            appeal_score=8,
            appeal_reasons=["C 轮、团队 200 人"],
            fit_score=6,
            fit_reasons=["JD 要求 8 年经验，简历 6 年"],
        )

    @property
    def systems(self) -> list[str]:
        return [m[0][1] for m in self.messages]

    @property
    def users(self) -> list[str]:
        return [m[-1][1] for m in self.messages]


def seed(ctx: AppContext, *job_ids: int, description: str = "") -> None:
    """塞几条带 JD 的职位。默认 JD 里带 Agent，免得被 [score.require] 压到末尾。"""
    body = description or "岗位职责：\n负责 Agent 平台建设\n任职要求：\n熟悉 Python 与 LLM"
    for job_id in job_ids:
        ctx.jobs.upsert_many([make_job(job_id, jobName=f"岗{job_id} AI Agent")], "AI Agent")
        ctx.details.upsert(make_detail(job_id, description=body))


def run(
    ctx: AppContext,
    job_ids: list[int],
    llm: FakeLLM | None = None,
    force: bool = False,
    stop_check: Callable[[], bool] | None = None,
) -> Any:
    client = llm or FakeLLM()
    scorer = build_scorer(ctx.settings, ctx.db, ctx.llm_scores, llm=client)
    return scorer.run(job_ids, force=force, stop_check=stop_check)


# ------------------------------------------------------------------ 基本流程


def test_scores_and_persists(context: AppContext) -> None:
    seed(context, 1, 2)
    summary = run(context, [1, 2])

    assert (summary.requested, summary.scored, summary.skipped, summary.failed) == (2, 2, 0, 0)
    assert summary.model == "claude-opus-5"
    assert {r.jobId for r in summary.results} == {1, 2}

    row = next(j for j in context.jobs.find(JobQuery()).items if j.jobId == 1)
    assert (row.llmAppeal, row.llmFit) == (8, 6)
    assert row.llmAppealReasons == ["C 轮、团队 200 人"]
    assert row.llmProvider == "anthropic"
    assert row.llmScoredAt is not None


def test_two_dimensions_stay_independent(context: AppContext) -> None:
    """两个分数并列落库，代码不合成总分——行模型里就该是两个独立字段。"""
    seed(context, 1)
    run(context, [1])
    bundle = context.jobs.get_with_detail(1)
    assert bundle is not None
    assert bundle.llmAppeal == 8
    assert bundle.llmFit == 6
    assert bundle.llmFitReasons == ["JD 要求 8 年经验，简历 6 年"]


def test_scoring_does_not_touch_keyword_scores(context: AppContext) -> None:
    """LLM 打分不许顺手重写 job_scores：库里的名次什么时候变由 job score 说了算。"""
    seed(context, 1)
    run(context, [1])
    assert context.scores.status(context.settings.score.fingerprint).scored == 0


# ------------------------------------------------------------------ 跳过规则


def test_skips_when_model_and_prompts_unchanged(context: AppContext) -> None:
    """口径没变的重打只是白花钱，默认跳过。"""
    seed(context, 1, 2)
    run(context, [1, 2])

    second = FakeLLM()
    summary = run(context, [1, 2], llm=second)
    assert (summary.scored, summary.skipped) == (0, 2)
    assert second.messages == []


def test_force_rescores(context: AppContext) -> None:
    seed(context, 1)
    run(context, [1])
    summary = run(context, [1], force=True)
    assert (summary.scored, summary.skipped) == (1, 0)


def test_model_change_invalidates_skip(context: AppContext) -> None:
    """换了模型旧分数就不可比，该重打——不能因为「打过了」就跳过。"""
    seed(context, 1)
    run(context, [1])
    context.settings.agent.providers["anthropic"].model = "claude-sonnet-5"
    summary = run(context, [1])
    assert (summary.scored, summary.skipped) == (1, 0)
    assert summary.model == "claude-sonnet-5"


def test_prompt_change_invalidates_skip(context: AppContext, profile_dir: Path) -> None:
    seed(context, 1)
    run(context, [1])
    (profile_dir / "score_appeal.md").write_text("只看薪资高不高。", encoding="utf-8")
    summary = run(context, [1])
    assert (summary.scored, summary.skipped) == (1, 0)


def test_missing_jd_counts_as_skipped(context: AppContext) -> None:
    """传了但库里没有（或没抓到 JD）的要说出来——静默少打几条会让人以为全打过了。"""
    seed(context, 1)
    summary = run(context, [1, 999])
    assert (summary.requested, summary.scored, summary.skipped) == (2, 1, 1)


# ------------------------------------------------------------------ 失败与取消


def test_single_failure_does_not_abort_batch(context: AppContext) -> None:
    seed(context, 1, 2, 3)
    summary = run(context, [1, 2, 3], llm=FakeLLM(fail_on={2}))

    assert (summary.scored, summary.failed) == (2, 1)
    assert summary.errors and "2：" in summary.errors[0]
    # 失败的不落库：表里有行就等于有一份有效分数，不必再判 status 列
    scored_ids = {j.jobId for j in context.jobs.find(JobQuery()).items if j.llmAppeal is not None}
    assert scored_ids == {1, 3}


def test_config_error_is_not_downgraded(context: AppContext) -> None:
    """缺 key、装错包这类问题是整批都跑不动的，不该被降级成「一条失败」。"""

    class Broken(FakeLLM):
        def invoke(self, messages: list[tuple[str, str]]) -> LlmVerdict:
            raise ConfigError("缺 API key")

    seed(context, 1)
    with pytest.raises(ConfigError):
        run(context, [1], llm=Broken())


def test_stop_check_skips_remaining(context: AppContext) -> None:
    """取消是秒响应的：已取消的条目直接空转返回，不再调模型。"""
    seed(context, 1, 2, 3)
    llm = FakeLLM()
    summary = run(context, [1, 2, 3], llm=llm, stop_check=lambda: True)

    assert (summary.scored, summary.cancelled) == (0, 3)
    assert llm.messages == []


# ------------------------------------------------------------------ 提示词


def test_system_prompt_is_identical_across_jobs(context: AppContext) -> None:
    """整批的 system 逐字相同才吃得到前缀缓存；每条不同的只有 user 那半。"""
    seed(context, 1, 2)
    llm = FakeLLM()
    run(context, [1, 2], llm=llm)

    assert len(set(llm.systems)) == 1
    assert len(set(llm.users)) == 2
    system = llm.systems[0]
    assert "# 测试简历" in system and "# 求职偏好" in system
    assert "岗位吸引力" in system and "胜任匹配度" in system
    # 简历放 system、岗位放 user——反过来每条都要重付一遍简历的输入 token
    assert "# 测试简历" not in llm.users[0]


def test_user_message_carries_facts_and_reference_signal(context: AppContext) -> None:
    seed(context, 1)
    llm = FakeLLM()
    run(context, [1], llm=llm)
    user = llm.users[0]
    assert "某公司" in user and "10000人以上" in user
    assert "负责 Agent 平台建设" in user
    # 关键词打分只作线索，得标明它是「参考信号」
    assert "参考信号" in user and "Agent" in user


def test_custom_prompt_replaces_default(context: AppContext, profile_dir: Path) -> None:
    """自定义是**整段替换**，不是追加——两份方法论叠在一起会互相打架。"""
    (profile_dir / "score_fit.md").write_text("只看学历。", encoding="utf-8")
    prompts = load_score_prompts(context.settings)

    assert prompts.fit == "只看学历。"
    assert prompts.fit_custom is True
    assert prompts.appeal == APPEAL_SYSTEM
    assert prompts.appeal_custom is False

    seed(context, 1)
    llm = FakeLLM()
    run(context, [1], llm=llm)
    system = llm.systems[0]
    assert "只看学历。" in system
    assert FIT_SYSTEM not in system


def test_empty_prompt_file_falls_back_to_default(
    context: AppContext, profile_dir: Path
) -> None:
    """空文件不算「自定义成空的」——那会让模型收到一段没有方法论的 system。"""
    (profile_dir / "score_appeal.md").write_text("   \n\n", encoding="utf-8")
    prompts = load_score_prompts(context.settings)
    assert prompts.appeal == APPEAL_SYSTEM
    assert prompts.appeal_custom is False


def test_fingerprint_follows_final_text(settings: Settings, profile_dir: Path) -> None:
    before = load_score_prompts(settings).fingerprint
    (profile_dir / "score_fit.md").write_text("只看学历。", encoding="utf-8")
    assert load_score_prompts(settings).fingerprint != before


# ------------------------------------------------------------------ 覆盖率


def test_status_reports_coverage_and_staleness(context: AppContext) -> None:
    settings = context.settings
    seed(context, 1, 2)

    def status() -> Any:
        return context.llm_scores.status(
            settings.llm_score_provider_name,
            settings.llm_score_active.model,
            load_score_prompts(settings).fingerprint,
        )

    assert status().scorable == 2
    assert status().scored == 0

    run(context, [1])
    fresh = status()
    assert (fresh.scored, fresh.current, fresh.stale) == (1, 1, False)

    settings.agent.providers["anthropic"].model = "claude-sonnet-5"
    stale = status()
    # 换了模型，那一条就成了「别的模型判的」——覆盖率没变，但口径不一致要报出来
    assert (stale.scored, stale.current, stale.stale) == (1, 0, True)


def test_llm_scored_filter(context: AppContext) -> None:
    seed(context, 1, 2)
    run(context, [1])
    assert [j.jobId for j in context.jobs.find(JobQuery(llm_scored=True)).items] == [1]
    assert [j.jobId for j in context.jobs.find(JobQuery(llm_scored=False)).items] == [2]
