"""LLM 语义打分：两个维度，各 1-10 分，各带一条或多条依据。

和隔壁的 :mod:`~job_agent.core.matching.scorer`（关键词打分）**完全并列**，
不合成总分：一个是几毫秒能重跑一遍的确定性分诊，一个是按条计费、读得懂
「JD 要 50 人管理经验」的语义判断。谁重要由看的人决定，代码不替他定权重。

两个维度是刻意分开的，因为它们回答的是两个不相干的问题：

- **appeal（岗位吸引力）**：从求职者一侧看，这份工作本身值多少分。
  以 ``preferences.md`` 写下来的求职期望为决定性标准，薪资与平台只在方向对上
  之后才起作用——方向不对的高薪岗给高分，等于把不该投的机会推到人眼前。
- **fit（胜任匹配度）**：从招聘方一侧看，这个人拿到它的概率有多大。

合成一个「推荐度」会把两者搅在一起——「够不着的好岗」和「够得着的烂岗」
算出来一样高，而这两种情况该做的事完全不同。

成本约束贯穿整个模块：**必须显式指定打哪些**（没有「默认全打」）、
口径没变的默认跳过、一条一条落库（中断也保住已完成的部分）。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from job_agent.config import Settings
from job_agent.core.dataset import jd_text, load_rows
from job_agent.core.llm import (
    ScoreCandidate,
    ScorePrompts,
    bind_schema,
    build_llm,
    load_score_prompts,
    schema_instruction,
    score_system_message,
    score_user_message,
)
from job_agent.core.matching.scorer import ScoredJob, score_all
from job_agent.core.profile import load_profile
from job_agent.core.services.progress import Progress, ProgressHook
from job_agent.core.storage import Database, LlmScoreEntry, LlmScoreRepository
from job_agent.errors import JobAgentError
from job_agent.log import get_logger

logger = get_logger(__name__)

#: 这条路线的用途标签，进 API key 缺失时的报错文案
PURPOSE = "LLM 打分"


class LlmVerdict(BaseModel):
    """模型对一条 JD 的结构化裁决。字段固定、带校验，两次运行**结构可比**。

    ``extra="forbid"`` 是 strict json_schema 模式的要求；每个字段的 description
    会进 JSON Schema 发给模型，所以它们本身就是 prompt 的一部分。
    """

    model_config = ConfigDict(extra="forbid")

    appeal_score: int = Field(
        ge=1, le=10, description="岗位吸引力，1-10 的整数：从求职者角度，这份工作本身值多少分"
    )
    appeal_reasons: list[str] = Field(
        default_factory=list,
        description="支撑 appeal_score 的依据，一条或多条，每条一句具体事实，不写空话",
    )
    fit_score: int = Field(
        ge=1, le=10, description="胜任匹配度，1-10 的整数：从招聘方角度，这个人拿到它的概率"
    )
    fit_reasons: list[str] = Field(
        default_factory=list,
        description="支撑 fit_score 的依据，一条或多条；硬门槛不满足的必须点名是哪一条",
    )


class LlmScoreResult(BaseModel):
    """一条打完的结果，给 CLI 表格与任务结果用。"""

    model_config = ConfigDict(extra="forbid")

    jobId: int
    title: str = ""
    company: str = ""
    salaryLow: float | None = None
    salaryHigh: float | None = None
    appeal: int
    fit: int
    appealReasons: list[str] = Field(default_factory=list)
    fitReasons: list[str] = Field(default_factory=list)


class LlmScoreSummary(BaseModel):
    """一次批量打分的账单。四个计数加起来 = ``requested``。"""

    model_config = ConfigDict(extra="forbid")

    #: 这次要求打的条数
    requested: int = 0
    #: 真的调了模型并落库的条数
    scored: int = 0
    #: 口径没变、已经打过，因此没花钱的条数
    skipped: int = 0
    #: 调用失败的条数（**不落库**：表里有行就等于有一份有效分数）
    failed: int = 0
    #: 被取消、根本没轮到的条数
    cancelled: int = 0
    errors: list[str] = Field(default_factory=list)
    provider: str = ""
    model: str = ""
    fingerprint: str = ""
    results: list[LlmScoreResult] = Field(default_factory=list)


def build_candidates(
    db: Database, settings: Settings, job_ids: Sequence[int]
) -> list[ScoreCandidate]:
    """把要打分的 jobId 变成送模型的载荷。

    只有抓到 JD 的职位进得来（``load_rows`` 已经过滤 ``status == "ok"`` 与
    正文长度）——没有 JD 就没什么可判的，送过去只会得到一份编出来的分数。

    顺带附上关键词打分的命中项作为**参考信号**。它在内存里现算，不落库：
    库里的名次什么时候变该由 ``job score`` 说了算，打个分顺手重写全库排名
    是个意外的副作用。
    """
    wanted = set(job_ids)
    if not wanted:
        return []
    by_id = {job.job_id: job for job in score_all(db, settings).jobs}
    out: list[ScoreCandidate] = []
    for row in load_rows(db, dedupe=False):
        if row.jobId not in wanted:
            continue
        scored: ScoredJob | None = by_id.get(row.jobId)
        out.append(
            ScoreCandidate(
                row=row,
                keyword_score=scored.score if scored else None,
                keyword_hits=scored.reasons() if scored else "",
                keyword_concerns=scored.concerns() if scored else "",
                jd=jd_text(row),
            )
        )
    return out


class LlmScorer:
    """批量调模型打分。``llm`` 由调用方注入，测试里传替身即可。

    并发在这里而不是交给某个框架：CLI、Web、将来别的入口要跑的是同一份
    并发与落库逻辑，抄两遍就会出现「命令行能取消、网页上取消不了」这种差异。
    """

    def __init__(
        self,
        settings: Settings,
        db: Database,
        repo: LlmScoreRepository,
        llm: Any,
        prompts: ScorePrompts,
        resume: str,
        preferences: str,
        on_progress: ProgressHook | None = None,
    ) -> None:
        self.settings = settings
        self.db = db
        self.repo = repo
        self.llm = llm
        self.prompts = prompts
        self.progress = Progress(on_progress, "matching.llm")
        self.provider = settings.llm_score_provider_name
        self.model = settings.llm_score_active.model
        self.fingerprint = prompts.fingerprint
        self._system = score_system_message(
            prompts,
            resume,
            preferences,
            schema_instruction(LlmVerdict, settings.llm_score_active.structured_output),
        )

    def run(
        self,
        job_ids: Sequence[int],
        force: bool = False,
        concurrency: int | None = None,
        stop_check: Callable[[], bool] | None = None,
    ) -> LlmScoreSummary:
        """给 ``job_ids`` 打分，返回这一批的账单。

        ``force=False``（默认）时跳过「同模型 + 同提示词已经打过」的那些——
        口径没变的重打只是白花钱；换了模型或改了提示词就该重打，
        因为旧分数和新的不可比。
        """
        summary = LlmScoreSummary(
            requested=len(job_ids),
            provider=self.provider,
            model=self.model,
            fingerprint=self.fingerprint,
        )
        candidates = build_candidates(self.db, self.settings, job_ids)
        missing = len(job_ids) - len(candidates)
        if missing > 0:
            # 传了但库里没有（或没抓到 JD）的，算作跳过并说出来——静默少打几条
            # 会让人以为全打过了
            summary.skipped += missing
            self.progress.emit(f"{missing} 条没有可用的 JD，跳过", level="warn")

        if not force:
            done = self.repo.current_ids(self.provider, self.model, self.fingerprint)
            before = len(candidates)
            candidates = [c for c in candidates if c.job_id not in done]
            summary.skipped += before - len(candidates)

        total = len(candidates)
        if not total:
            self.progress.emit(f"没有需要打分的职位（跳过 {summary.skipped} 条）")
            return summary

        self.progress.emit(
            f"开始 LLM 打分：{total} 条，模型 {self.provider} / {self.model}，"
            f"并发 {concurrency or self.settings.llm_score.concurrency}",
            current=0,
            total=total,
        )
        workers = concurrency or self.settings.llm_score.concurrency
        done_count = 0
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="llm-score") as pool:
            futures = [pool.submit(self._judge, c, stop_check) for c in candidates]
            # 谁先回来先落库：分数写在主线程（SQLite 不适合并发写），
            # 逐条 upsert 意味着取消 / 崩溃时已完成的部分都还在
            for future in as_completed(futures):
                candidate, verdict, error = future.result()
                done_count += 1
                if verdict is None and error is None:
                    summary.cancelled += 1
                    continue
                if verdict is None:
                    summary.failed += 1
                    summary.errors.append(f"{candidate.job_id}：{error}")
                    self.progress.emit(
                        f"[{done_count}/{total}] {candidate.row.jobName} 打分失败：{error}",
                        current=done_count,
                        total=total,
                        level="warn",
                    )
                    continue
                self._save(candidate, verdict, summary)
                self.progress.emit(
                    f"[{done_count}/{total}] {candidate.row.jobName} "
                    f"→ 吸引力 {verdict.appeal_score} / 胜任度 {verdict.fit_score}",
                    current=done_count,
                    total=total,
                )

        self.progress.emit(
            f"打分完成：新打 {summary.scored} 条，跳过 {summary.skipped} 条，"
            f"失败 {summary.failed} 条，取消 {summary.cancelled} 条"
        )
        return summary

    # ------------------------------------------------------------------ 内部

    def _judge(
        self, candidate: ScoreCandidate, stop_check: Callable[[], bool] | None
    ) -> tuple[ScoreCandidate, LlmVerdict | None, str | None]:
        """判一条。三元组的第二三位都为 None 表示「已取消、没调模型」。

        取消检查放在 worker 开头而不是提交前：任务全部提交后，剩下的会一个个
        空转返回，取消因此是秒响应的，而不是等几百条排完。
        """
        if stop_check is not None and stop_check():
            return candidate, None, None
        try:
            verdict = self.llm.invoke(
                [("system", self._system), ("user", score_user_message(candidate))]
            )
        except JobAgentError:
            # 配置类错误（缺 key、装错包）是整批都跑不动的，不该被降级成一条失败
            raise
        except Exception as exc:  # 单条失败不该拖垮整批
            logger.warning("职位 %s 打分失败：%s", candidate.job_id, exc)
            return candidate, None, f"{type(exc).__name__}: {exc}"
        return candidate, verdict, None

    def _save(
        self, candidate: ScoreCandidate, verdict: LlmVerdict, summary: LlmScoreSummary
    ) -> None:
        row = candidate.row
        self.repo.upsert_many(
            [
                LlmScoreEntry(
                    jobId=candidate.job_id,
                    appealScore=verdict.appeal_score,
                    fitScore=verdict.fit_score,
                    appealReasons=verdict.appeal_reasons,
                    fitReasons=verdict.fit_reasons,
                )
            ],
            self.provider,
            self.model,
            self.fingerprint,
        )
        summary.scored += 1
        summary.results.append(
            LlmScoreResult(
                jobId=candidate.job_id,
                title=row.jobName,
                company=row.company,
                salaryLow=row.salaryLow,
                salaryHigh=row.salaryHigh,
                appeal=verdict.appeal_score,
                fit=verdict.fit_score,
                appealReasons=verdict.appeal_reasons,
                fitReasons=verdict.fit_reasons,
            )
        )


def build_scorer(
    settings: Settings,
    db: Database,
    repo: LlmScoreRepository,
    on_progress: ProgressHook | None = None,
    llm: Any | None = None,
) -> LlmScorer:
    """按当前配置装好一个打分器：模型客户端 + 提示词 + 档案。

    CLI 与 Web 都走它，所以两个入口的口径必然一致。``llm`` 只在测试里显式传。
    """
    prompts = load_score_prompts(settings)
    resume, preferences = load_profile(settings)
    provider = settings.llm_score_active
    if llm is None:
        client = build_llm(provider, settings.llm_score_provider_name, PURPOSE)
        llm = bind_schema(client, LlmVerdict, provider.structured_output)
    return LlmScorer(settings, db, repo, llm, prompts, resume, preferences, on_progress)
