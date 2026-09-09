"""读求职者档案原文：简历 + 求职偏好。

两条执行路线都要把这两份 Markdown 原样喂给模型（agent 路线的审读节点、
CLI / Web 的 LLM 打分），所以它在共享内核里，而不是某一条路线自己的目录下。

**只读文件，不解析内容**：里面写什么、怎么组织，是用户自己的事——
程序一解析就等于给它定了格式，「换个人只改 profile」这条承诺就守不住了。
"""

from __future__ import annotations

from job_agent.config import Settings
from job_agent.errors import ConfigError


def load_profile(settings: Settings) -> tuple[str, str]:
    """读简历与求职偏好原文。缺文件直接报错——没有档案的判断毫无意义。"""
    texts: list[str] = []
    for label, path in (
        ("简历", settings.profile.resume),
        ("求职偏好", settings.profile.preferences),
    ):
        if not path.is_file():
            raise ConfigError(
                f"{label}文件不存在：{path}\n  先在 Claude Code 里跑 `/job-init` 生成，"
                "或手工按 config/templates/ 下的模板填写。"
            )
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise ConfigError(f"{label}文件是空的：{path}")
        texts.append(content)
    return texts[0], texts[1]
