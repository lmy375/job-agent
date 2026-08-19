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
