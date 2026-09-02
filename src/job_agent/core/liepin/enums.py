"""搜索参数的枚举取值。

传枚举外的字符串会被服务端当作「不限」静默忽略（不报错，只是不过滤），
所以这里用枚举把取值钉死，配置写错时在本地就报错。
"""

from __future__ import annotations

from enum import StrEnum


class EduLevel(StrEnum):
    """学历要求。经实测为服务端强过滤：命中后结果学历完全一致。"""

    JUNIOR = "初中及以下"
    SECONDARY = "中专/中技"
    HIGH = "高中"
    COLLEGE = "大专"
    BACHELOR = "本科"
    MASTER = "硕士"
    DOCTOR = "博士"
    MBA = "MBA/EMBA"


class WorkExperience(StrEnum):
    """工作经验要求。实测为服务端过滤，取值为猎聘标准档位。"""

    FRESH = "应届毕业生"
    LT_1Y = "1年以内"
    Y1_3 = "1-3年"
    Y3_5 = "3-5年"
    Y5_10 = "5-10年"
    GT_10Y = "10年以上"


class SalaryKind(StrEnum):
    """薪资类型。仅在同时提供 salaryFloor / salaryCap 时才对薪资区间生效。"""

    MONTHLY = "月薪"
    YEARLY = "年薪"


class JobKind(StrEnum):
    """职位类型：搜索响应里的 ``jobType``，投递时原样作为 ``jobKind``。

    区别是**谁在招**：``HR`` 是企业自己挂的岗（详情页链接形如 ``/job/``），
    ``HEADHUNTER`` 是猎头代招（链接形如 ``/a/``）。同一个岗常被几家猎头
    重复挂出、还各挂各的标价，所以打分那边要按 JD 正文去重。

    与其他几个枚举不同，这个**不是搜索参数**——接口不支持按它过滤，
    只能采回来之后在本地筛（``JobQuery.job_type``）。
    """

    HEADHUNTER = "1"
    HR = "2"
