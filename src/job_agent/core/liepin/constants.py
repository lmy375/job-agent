"""猎聘接口的协议常量（全部为实测值，改动前先看注释）。"""

from __future__ import annotations

from job_agent.core.liepin.enums import JobKind

DEFAULT_BASE_URL = "https://open-agent.liepin.com"
DEFAULT_TIMEOUT = 30.0

# 服务端限流实测值（2026-07-30）：约 10 次 / 60s 滑动窗口，**不是** 60 次/分钟。
# 实测在 20 次/分钟下，第 10 个请求（28s 处）即返回 429001。
# 触发后冷却 20 分钟以上，期间连单个请求也被拒，所以默认取 8 留足余量。
DEFAULT_RATE_LIMIT_PER_MIN = 8

# 业务错误码
CODE_OK = 0
CODE_RATE_LIMITED = 429001  # 请求过于频繁（真限流）
CODE_PAGE_LIMIT = -1  # 「你查询过多，等会再查吧」——实为分页越界（page>=6），与限流无关

MAX_PAGE = 6  # page 取值 0..5，单个查询最多 6 页 × 20 条 = 120 条（服务端硬上限）
PAGE_SIZE = 20  # 每页固定 20 条，实测无任何参数可调整

#: 取值只有两个，定义在 enums.JobKind（同一份取值要给筛选器与投递共用一处）
#: 猎头职位（详情页链接形如 /a/）
JOB_KIND_HEADHUNTER = JobKind.HEADHUNTER.value
#: 普通职位，企业 HR 直招（详情页链接形如 /job/）
JOB_KIND_NORMAL = JobKind.HR.value
JOB_KINDS = tuple(kind.value for kind in JobKind)

TOKEN_HELP_URL = "https://www.liepin.com/mcp/auth"
