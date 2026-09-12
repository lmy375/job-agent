"""按信号表给职位打分排序，结果落库。

**打分只做分诊**：把几百条砍到几十条，交给人或 skill 去读 JD 下判断。
它不回答「该不该投」——「这个岗要 50 人管理经验而你带 5 人」这种判断
需要读懂文字，归 ``job llm-score``（模型读 JD）或人自己读 JD。

信号表准不准，拿 LLM 分当参照对一遍就知道：见 :mod:`~job_agent.core.matching.align`
与 ``/job-align`` skill。

因此这里刻意保留了每条命中/扣分的**理由**：排名本身不可信，
理由才是让人能快速复核「为什么它排第一」的东西。

分数与排名会写进 ``job_scores`` 表（:func:`refresh`），Web 端直接读库排序。
**落库的是全量、未过滤的结果**：``--floor`` / ``-n`` / 去重都是看的时候的
过滤条件，不该让同一条职位的名次随着看法变。所以
``rank`` 恒定是「全库按分数降序的第几名」，视图过滤交给 :meth:`ScoreRefresh.view`。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from job_agent.config import ScoreConfig, Settings
from job_agent.core.dataset import JobFacts, dedupe_rows, load_rows
from job_agent.core.storage import Database, ScoreEntry, ScoreRepository
from job_agent.log import get_logger

logger = get_logger(__name__)


class Hit(BaseModel):
    """一条命中的信号。``in_title`` 决定权重是否被 ``title_multiplier`` 放大。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    weight: float
    in_title: bool

    def label(self) -> str:
        return f"{self.name}（标题）" if self.in_title else self.name


class ScoredJob(BaseModel):
    """一条打完分的职位。``row`` 是 :func:`load_rows` 的原始行，字段见 :class:`JobFacts`。"""

    model_config = ConfigDict(extra="forbid")

    row: JobFacts
    score: float
    hits: list[Hit] = Field(default_factory=list)
    penalties: list[Hit] = Field(default_factory=list)
    #: 职位名与 JD 都没命中 require.pattern
    off_track: bool = False

    # 常用字段的直通访问，省得调用方到处写 job.row["..."]
    @property
    def job_id(self) -> int:
        return self.row.jobId

    @property
    def title(self) -> str:
        return self.row.jobName

    @property
    def company(self) -> str:
        return self.row.company

    @property
    def salary_low(self) -> float | None:
        return self.row.salaryLow

    @property
    def salary_high(self) -> float | None:
        return self.row.salaryHigh

    def reasons(self) -> str:
        return "、".join(h.label() for h in self.hits)

    def concerns(self) -> str:
        return "、".join(h.label() for h in self.penalties)


def body_text(row: JobFacts) -> str:
    """打分时当「JD 正文」搜的那段文本。``align`` 拆子模式时要用同一份定义。"""
    return " ".join((row.description, row.responsibilities, row.requirements))


def score_row(row: JobFacts, rules: ScoreConfig) -> ScoredJob:
    """给一行打分。同一条信号在标题和正文都命中时只算标题（取高的那份）。"""
    title = row.jobName
    haystack = f"{title}\n{body_text(row)}"

    scored = ScoredJob(row=row, score=0.0)
    for signal in rules.signals:
        regex = signal.regex
        in_title = bool(regex.search(title))
        if not in_title and not regex.search(haystack):
            continue
        weight = signal.weight * (rules.title_multiplier if in_title else 1.0)
        scored.score += weight
        hit = Hit(name=signal.name, weight=weight, in_title=in_title)
        (scored.hits if signal.weight > 0 else scored.penalties).append(hit)

    require = rules.require_regex
    if require is not None and not require.search(haystack):
        scored.off_track = True
        scored.score += rules.require.penalty
        scored.penalties.append(
            Hit(name="不含目标赛道关键词", weight=rules.require.penalty, in_title=False)
        )

    scored.hits.sort(key=lambda h: -h.weight)
    scored.penalties.sort(key=lambda h: h.weight)
    return scored


class ScoreRefresh(BaseModel):
    """一次刷新的结果：全库打完分、排好名、已落库。

    ``jobs`` 是**全量**（未去重、未按薪资过滤），按分数降序——``rank`` 就是下标 +1。
    要拿「该看的那批」调 :meth:`view`。
    """

    model_config = ConfigDict(extra="forbid")

    jobs: list[ScoredJob] = Field(default_factory=list)
    #: 按 JD 正文去重后留下的 jobId。去重在刷新时算一次，view() 只做过滤，
    #: 免得反复调 view() 把 dupes 越加越多
    unique_ids: set[int] = Field(default_factory=set)
    #: 这批分数用的 [score] 指纹
    fingerprint: str = ""

    def view(
        self, settings: Settings, floor_wan: float | None = None, dedupe: bool = True
    ) -> list[ScoredJob]:
        """按「看的时候的条件」过滤：去重 + 薪资上限门槛。顺序沿用分数降序。

        ``floor_wan`` 过滤的是**薪资上限**而不是下限：JD 标的区间上限才代表
        「这家最多能给到多少」，按下限过滤会把「50-80k·20薪」这种谈得上去的岗位误杀。
        """
        threshold = floor_wan if floor_wan is not None else settings.score.salary_floor_wan
        out = []
        for job in self.jobs:
            if dedupe and job.job_id not in self.unique_ids:
                continue
            high = job.salary_high
            if threshold is not None and (high is None or high < threshold):
                continue
            out.append(job)
        return out


def score_all(db: Database, settings: Settings) -> ScoreRefresh:
    """按当前 ``[score]`` 给全库打分排序，**不落库**。

    :func:`refresh` 在它之上加一步整表重写。分开是因为有人只想要排序结果
    （比如 LLM 打分要按分数挑前 N 条送模型），那种场景顺手改写 ``job_scores``
    是个意外的副作用——库里的名次什么时候变，该由 ``job score`` 说了算。
    """
    rules = settings.score
    rows = load_rows(db, dedupe=False)
    scored = [score_row(row, rules) for row in rows]
    scored.sort(key=lambda s: (-s.score, -(s.salary_high or 0.0)))

    # 去重放在打分之后：它就地给存活的行打上 dupes，所以 ScoredJob.row.dupes 跟着对
    unique = {row.jobId for row in dedupe_rows(rows)}
    return ScoreRefresh(jobs=scored, unique_ids=unique, fingerprint=rules.fingerprint)


def refresh(db: Database, settings: Settings) -> ScoreRefresh:
    """按当前 ``[score]`` 信号表给全库重新打分，写进 ``job_scores``。

    每次都是**整表重写**：分数之间有关系（``rank`` 是全库排名），
    只更新一部分留下的排名是错的，而且错得看不出来。
    """
    result = score_all(db, settings)
    scored = result.jobs
    ScoreRepository(db).replace_all(
        [
            ScoreEntry(
                jobId=job.job_id,
                score=round(job.score, 2),
                rank=index,
                offTrack=job.off_track,
                hits=[h.label() for h in job.hits],
                penalties=[h.label() for h in job.penalties],
            )
            for index, job in enumerate(scored, 1)
        ],
        result.fingerprint,
    )
    logger.debug("刷新 %d 条分数，去重后 %d 条", len(scored), len(result.unique_ids))
    return result
