"""LLM 打分的提示词。

**内置的两段只写方法论**——「怎么判断一个岗位好不好」「怎么判断一个人够不够格」
是通用手艺，换谁来都一样。个人取向（想去什么方向、不看什么、薪资底线）
全部来自运行时注入的 ``resume.md`` 与 ``preferences.md``，
「换用户只改 profile」这条承诺对这条路线同样成立。

用户想改方法论本身时，在 profile 目录下建 ``score_appeal.md`` / ``score_fit.md``，
**整段替换**对应维度的内置文本。不存在或空文件就用默认。
输出要求与 JSON Schema 那一截永远由代码拼，用户改不坏结构化输出。

一次调用出两个分数，不是两次：输入 token（简历 + 偏好 + JD，几千字）是成本大头，
拆成两次调用等于把最贵的那部分付两遍，而两段提示词各自可覆盖的诉求，
用 system 里两个二级标题就满足了。

简历与偏好放 **system**、单个岗位放 **user**：整批打分里 system 逐字相同，
各家的前缀缓存都能命中；塞进 user 等于每条职位都重付一遍简历的输入 token。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from job_agent.config import Settings
from job_agent.core.dataset import JobFacts

APPEAL_SYSTEM = """\
站在**求职者**一侧看这个岗位本身值不值得投。与「这个人能不能拿到」无关——
就算他一定拿不到，符合他期望的好岗位也该给高分。

**最关键的一条：这个岗位符不符合他写下来的求职期望。**
不是四条并列的其中一条，是决定分数区间的那一条——方向不对的岗位，
薪资再高、公司再大也只是「不该投的好机会」，给高分等于把它推到他眼前。

判断顺序：

### 第一步：对着求职偏好定分数区间（决定性）

以 `## 求职偏好` 里写的**优先方向、也可以考虑的方向、明确不看的岗位、
硬约束（Base 地、远程、出差、公司阶段与规模、管理岗还是纯技术岗）**为准，
先定这条岗位落在哪个区间：

- 命中「明确不看的岗位」或违反任一硬约束 → **1-2 分**，到此为止，
  后面几步不再往上抬。
- 方向既不在优先方向里、也不在「也可以考虑」里 → **最高 4 分**。
- 属于「也可以考虑」的次优方向 → **最高 7 分**。
- 属于「优先方向」→ 区间是 **5-10 分**，再走第二步决定具体给几分。

偏好里没写明的维度按「没有要求」处理，不要替他补一条；
偏好整体写得含糊时，以简历主线所在的方向为准，并在依据里点明
「求职偏好未写明方向，按简历主线判断」。

### 第二步：在区间内，按下面三样定具体分数

1. **报酬**：薪资区间在同类岗位里的水位；有没有交代构成（期权、几薪、绩效）。
   薪资一律按税前理解；JD 没标就当「未标」，不要按公司名猜一个。
   低于偏好里写的薪资底线要明显减分。
2. **平台**：公司体量、融资阶段、在行业里的位置。头部与大厂加分，但小而稳的
   细分龙头不该因为名气小被压分；主体业务都说不清、来路不明的要减分。
3. **JD 质量与业务靠谱程度**：职责与要求是否具体、看不看得出团队在做什么、
   技术栈写没写清。通篇套话、职责与职级明显对不上、像猎头拼凑出来的要减分——
   JD 写得糊涂，通常说明招聘方自己没想清楚要什么。

这三样只在区间**内部**移动分数，**不能把分数抬出第一步定下的上限**。

分数锚点：
- 9-10：正中优先方向，报酬与平台也都对，看到就想投
- 7-8：优先方向，但报酬、平台或 JD 质量有一两处明显瑕疵
- 5-6：优先方向但多处不理想，或次优方向里条件很好的那种
- 3-4：方向不在他的期望里，只有报酬或平台还行
- 1-2：明确排除的方向、违反硬约束，或 JD 根本看不出在招什么

**每条依据都要说清是哪一步的判断**：先写方向契合（命中/偏离了偏好里的哪一条），
再写报酬、平台、JD 质量。只夸薪资高却不说方向对不对的依据没有意义。"""

FIT_SYSTEM = """\
站在**招聘方**一侧看：这个人投了，拿到这份工作的概率有多大。
与「岗位好不好」无关——再普通的岗位，只要他明显够格，也该给高分。

看四件事：

1. **硬门槛**：JD **明确写出**的条件——学历、经验年限、管理规模、语言、驻地、
   行业背景、特定资质。逐条与简历比对。**任何一条明确不满足，分数不得高于 4**；
   JD 没写明的按「未设门槛」处理，不要替它补一个。
2. **核心经历**：简历主线与岗位职责的重合度。做过同类事、规模可比的加分；
   只是技术栈沾边、没做过这类业务的减分。
3. **技术栈**：JD 点名的栈简历里有没有；相邻可迁移的算部分命中。
4. **职级与规模**：岗位职级、汇报线、团队规模与候选人当前位置的落差。
   跨一档还够得着，跨两档以上要减分。

分数锚点：
- 9-10：硬门槛全过，核心经历高度对口，是招聘方会主动捞的简历
- 7-8：硬门槛全过，主要要求命中，有一两项要靠说服
- 5-6：硬门槛没有明确冲突，但经历只对上一半，进面看运气
- 3-4：有明确不满足的硬门槛，或核心经历基本不搭
- 1-2：完全不是一个方向

简历里没写的一律按「没有」算，不要替候选人补经历。"""

_SHELL = """\
你是候选人的求职参谋。对下面这条职位 JD 打两个分，每个都是 1-10 的整数，
并各给出一条或多条**具体**的打分依据。

通用规则：
1. 只依据给你的简历、求职偏好与 JD 文本判断，不引入外部信息，不编造。
2. 两个维度**互相独立**：一个看岗位本身好不好，一个看这个人够不够格。
   不要因为岗位好就抬高匹配分，也不要因为够不着就压低岗位分。
3. 依据要落到具体事实（「JD 要求 8 年经验，简历 6 年」「C 轮、团队 200 人」），
   一条一句；不写「比较合适」这类没有信息量的话。
4. 参考信号里的规则打分只是线索，以 JD 原文为准。"""


class ScorePrompts(BaseModel):
    """这次打分实际用的两段方法论，以及它们是不是用户覆盖的。

    ``fingerprint`` 只认**最终文本**：换了模型、改了提示词，落库的分数就该算过期。
    """

    model_config = ConfigDict(extra="forbid")

    appeal: str
    fit: str
    appeal_custom: bool = False
    fit_custom: bool = False

    @property
    def fingerprint(self) -> str:
        payload = f"{self.appeal}\n\x00\n{self.fit}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def read_prompt_file(path: Path) -> str:
    """读一份覆盖用的提示词文件；不存在或空文件返回空串。"""
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()


def load_score_prompts(settings: Settings) -> ScorePrompts:
    """按当前 profile 取两段方法论：有覆盖文件就用它，否则用内置默认。"""
    appeal = read_prompt_file(settings.profile.score_appeal_prompt)
    fit = read_prompt_file(settings.profile.score_fit_prompt)
    return ScorePrompts(
        appeal=appeal or APPEAL_SYSTEM,
        fit=fit or FIT_SYSTEM,
        appeal_custom=bool(appeal),
        fit_custom=bool(fit),
    )


def score_system_message(
    prompts: ScorePrompts, resume: str, preferences: str, schema_note: str = ""
) -> str:
    """整批打分共用的 system prompt——逐字相同才吃得到前缀缓存。

    ``schema_note`` 是 ``json_mode`` 下要自己附的输出要求
    （见 :func:`~job_agent.core.llm.client.schema_instruction`），其余方式传空串。
    """
    parts = [
        _SHELL,
        f"## 维度一：岗位吸引力（appeal_score）\n\n{prompts.appeal}",
        f"## 维度二：胜任匹配度（fit_score）\n\n{prompts.fit}",
        f"## 候选人简历\n\n{resume}",
        f"## 求职偏好（含硬约束）\n\n{preferences}",
    ]
    if schema_note:
        parts.append(schema_note)
    return "\n\n".join(parts)


class ScoreCandidate(BaseModel):
    """送模型打分的单条载荷：事实（:class:`JobFacts`）+ 规则打分给的参考信号。"""

    model_config = ConfigDict(extra="forbid")

    row: JobFacts
    #: 关键词打分的分数与命中，只作线索
    keyword_score: float | None = None
    keyword_hits: str = ""
    keyword_concerns: str = ""
    #: JD 正文（已合并三段并截断，见 core.dataset.jd_text）
    jd: str

    @property
    def job_id(self) -> int:
        return self.row.jobId


def score_user_message(candidate: ScoreCandidate) -> str:
    """单个岗位的输入。放在 user 里——system 那半整批复用，这半每条都不同。"""
    row = candidate.row
    signal = "未打分"
    if candidate.keyword_score is not None:
        hits = candidate.keyword_hits or "无"
        concerns = candidate.keyword_concerns or "无"
        signal = f"{candidate.keyword_score:.0f}（命中：{hits}；扣分：{concerns}）"
    return f"""\
## 待打分岗位

- 职位：{row.jobName}
- 公司：{row.company}
- 薪资（税前）：{_salary_text(row)}
- 城市：{row.location or '未标'}　行业：{row.industry or '未标'}
- 公司规模：{row.companySize or '未标'}　融资阶段：{row.financingStage or '未标'}
- JD 学历要求：{row.education or '未标'}　经验要求：{row.workYears or '未标'}
- 参考信号（规则打分）：{signal}

### JD 原文

{candidate.jd}"""


def _salary_text(row: JobFacts) -> str:
    if row.salaryLow is None and row.salaryHigh is None:
        return f"{row.salary or 'JD 未标'}（未能解析成年薪区间）"
    return f"{row.salaryLow or '?'}-{row.salaryHigh or '?'} 万/年（原文：{row.salary}）"
