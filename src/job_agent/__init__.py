"""job-agent：猎聘职位采集、分析、投递与市场报告。

分层：

- ``job_agent.config``  配置加载（config/*.toml + config/.env），不依赖其它层
- ``job_agent.core``    核心能力：猎聘客户端、存储、采集服务、分析、报告渲染
- ``job_agent.cli``     命令行封装
- ``job_agent.web``     FastAPI 管理后端（数据查看 + 采集任务 + 投递）

上层依赖下层，反向依赖一律禁止。
"""

from __future__ import annotations

__version__ = "1.0.0"

__all__ = ["__version__"]
