"""审读节点用的模型客户端。

**客户端只有两类**：Anthropic 原生协议，以及 OpenAI 协议。
ChatGPT、DeepSeek、Kimi、通义、GLM、本地 vLLM/Ollama 全都兼容 OpenAI 协议，
所以它们不需要各自的适配代码——加一家新模型是在 ``config/config.toml`` 里
加一段 ``[agent.providers.xxx]``，不是改这里。

真正的差异不在「怎么连上」，而在**结构化输出**：审读裁决必须符合
:class:`~job_agent.agent.state.JDVerdict` 的 schema，而 Anthropic 走 tool
calling、OpenAI 官方端点走 strict json_schema、兼容端点往往只吃
function_calling 或 json_mode。这个支持度会随版本变，所以它是配置项
（``structured_output``），不在代码里按 provider 名硬猜。

langchain 的 import 全部延后到函数内：没装 agent extra 时本模块也要能导入
（``bind_review_schema`` 是纯适配逻辑，边界测试与单测都不需要 extra）。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, SecretStr

from job_agent.config import Settings
from job_agent.errors import ConfigError


def require_api_key(settings: Settings) -> SecretStr:
    """取选中 provider 的 API key。缺了直接报错——没有它整条路线跑不动。"""
    name = settings.agent.provider
    provider = settings.agent.active
    if provider.api_key is None:
        raise ConfigError(
            f"缺少 API key：agent 路线的审读节点要调 {settings.agent.model_label}。\n"
            f'  在 config/config.toml 的 [agent.providers.{name}] 下填 api_key = "…"，\n'
            f"  或临时用环境变量覆盖（不落盘）："
            f"JOB_AGENT_AGENT__PROVIDERS__{name.upper()}__API_KEY=…"
        )
    return provider.api_key


#: api -> 提供客户端的包名（缺了要装哪个）
_PACKAGES = {"anthropic": "langchain-anthropic", "openai": "langchain-openai"}


def build_llm(settings: Settings) -> Any:
    """按 ``[agent].provider`` 选中的接入点造模型客户端。"""
    provider = settings.agent.active
    api_key = require_api_key(settings)
    # model= / api_key= / base_url= 都是文档化用法；mypy 只认得 pydantic 的 alias 名
    try:
        if provider.api == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(  # type: ignore[call-arg]
                model=provider.model,
                api_key=api_key,
                base_url=provider.base_url,
                max_tokens=provider.max_tokens,
                temperature=provider.temperature,
            )

        from langchain_openai import ChatOpenAI

        return ChatOpenAI(  # type: ignore[call-arg]
            model=provider.model,
            api_key=api_key,
            base_url=provider.base_url,
            max_tokens=provider.max_tokens,
            temperature=provider.temperature,
        )
    except ImportError as exc:
        package = _PACKAGES[provider.api]
        raise ConfigError(
            f"{settings.agent.model_label} 走 {provider.api} 协议，"
            f"需要 {package}（缺 {exc.name}）。\n"
            f"  uv sync    # 重新装齐依赖；或 pip install {package}"
        ) from exc


def bind_review_schema(llm: Any, schema: type[BaseModel], method: str) -> Any:
    """把裁决 schema 绑到模型上。

    ``auto`` 不传 ``method``，让 langchain 按 provider 选它自己的默认实现；
    其余取值原样传下去——兼容端点（DeepSeek 之类）常常得显式指定。
    """
    if method == "auto":
        return llm.with_structured_output(schema)
    return llm.with_structured_output(schema, method=method)
