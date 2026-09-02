"""审读节点的 prompt。

**这里只写方法论，不写任何个人取向。** 「这个人在乎什么」全部来自
``config/``（resume.md、preferences.md、match.toml），运行时注入——
「换用户只改 config」这条承诺对 agent 路线同样成立。
"""

from __future__ import annotations

import json

from job_agent.agent.state import JDVerdict, ShortlistJob

REVIEW_SYSTEM = """\
你是候选人的求职参谋，任务是审读一条职位 JD，判断值不值得投。

规则：
1. 只依据给你的简历、求职偏好与 JD 文本判断，不引入外部信息，不编造候选人没写的经历。
2. 硬门槛指 JD **明确写出**的条件：学历、经验年限、管理规模、语言、驻地/出差、
   行业背景等。逐条与简历比对，全部满足才算通过；JD 没写明的条目在结论里
   标注「JD 未说明」，不要按想象补全。
3. 求职偏好里写的硬约束（如通勤范围、薪资底线）与 JD 冲突时，视同硬门槛不过。
4. 优先级打分看三样：硬门槛通过情况、岗位与候选人核心经历的贴合度、
   偏好里写的加分方向。硬门槛不过的一律给 1。
5. 投递口径写给招聘方看：两三句话，具体到候选人的哪段经历对上岗位的哪个要求，
   不写空话。
6. 参考信号（规则打分的命中项）只是线索，你的判断以 JD 原文为准。"""


def review_system_message(structured_output: str) -> str:
    """审读节点的 system prompt。

    ``json_mode`` 下 langchain 只会要求「输出 JSON」、**不会**把 schema 发给
    模型（json_schema / function_calling 两种方式才会），所以这里得自己附上。
    走兼容端点（DeepSeek 之类）时常常只能用 json_mode，这段就是为它们准备的。
    """
    if structured_output != "json_mode":
        return REVIEW_SYSTEM
    schema = json.dumps(JDVerdict.model_json_schema(), ensure_ascii=False, indent=2)
    return (
        f"{REVIEW_SYSTEM}\n\n"
        "输出要求：只输出一个 JSON 对象，符合下面的 JSON Schema，"
        f"不要包代码块、不要写任何解释文字。\n{schema}"
    )


def review_user_message(resume: str, preferences: str, job: ShortlistJob) -> str:
    """拼装单个岗位的审读输入。``job`` 是 pipeline.build_shortlist 产出的载荷。"""
    salary = _salary_text(job)
    return f"""\
## 候选人简历

{resume}

## 求职偏好（含硬约束）

{preferences}

## 待审读岗位

- job_id：{job.job_id}（裁决里原样带回这个数字）
- 职位：{job.title}
- 公司：{job.company}
- 薪资（税前）：{salary}
- 规则打分：{job.score}；命中：{job.reasons or "无"}；扣分：{job.concerns or "无"}

### JD 原文

{job.jd}"""


def _salary_text(job: ShortlistJob) -> str:
    if job.salary_low is None and job.salary_high is None:
        return "JD 未标"
    return f"{job.salary_low or '?'}-{job.salary_high or '?'} 万/年"
