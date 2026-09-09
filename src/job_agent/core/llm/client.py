"""模型客户端：两条执行路线共用的唯一接入点。

**客户端只有两类**：Anthropic 原生协议，以及 OpenAI 协议。
ChatGPT、DeepSeek、Kimi、通义、GLM、本地 vLLM/Ollama 全都兼容 OpenAI 协议，
所以它们不需要各自的适配代码——加一家新模型是在 ``config/config.toml`` 里
加一段 ``[agent.providers.xxx]``，不是改这里。

真正的差异不在「怎么连上」，而在**结构化输出**：裁决必须符合某个 pydantic
schema，而 Anthropic 走 tool calling、OpenAI 官方端点走 strict json_schema、
兼容端点往往只吃 function_calling 或 json_mode。这个支持度会随版本变，
所以它是配置项（``structured_output``），不在代码里按 provider 名硬猜。

**为什么住在 core/ 而不是 agent/**：调模型的地方现在有两处——agent 路线的审读
节点，以及 CLI / Web 的 LLM 打分。边界规则禁止 ``cli`` / ``web`` import
``job_agent.agent``，可复用的东西一律下沉到共享内核，所以它在这里。
函数因此**不收 Settings**，只收一个 :class:`~job_agent.config.ModelProvider`：
哪个段选中了哪个接入点，是调用方的事。

langchain 的 import 全部延后到函数内：``bind_schema`` 是纯适配逻辑，
边界测试与单测都不需要真的装上模型 SDK。
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, SecretStr

from job_agent.config import ModelProvider
from job_agent.errors import ConfigError


def require_api_key(provider: ModelProvider, name: str, purpose: str) -> SecretStr:
    """取接入点的 API key。缺了直接报错——没有它这条路线跑不动。

    ``name`` 是 ``[agent.providers.*]`` 里的表名，``purpose`` 是「谁要用」，
    两个都进错误信息：报错要能直接照着改，而不是让人回去翻文档。
    """
    if provider.api_key is None:
        raise ConfigError(
            f"缺少 API key：{purpose}要调 {name} / {provider.model}。\n"
            f'  在 config/config.toml 的 [agent.providers.{name}] 下填 api_key = "…"，\n'
            f"  或临时用环境变量覆盖（不落盘）："
            f"JOB_AGENT_AGENT__PROVIDERS__{name.upper()}__API_KEY=…"
        )
    return provider.api_key


#: api -> 提供客户端的包名（缺了要装哪个）
_PACKAGES = {"anthropic": "langchain-anthropic", "openai": "langchain-openai"}


def build_llm(provider: ModelProvider, name: str, purpose: str) -> Any:
    """按接入点造模型客户端。"""
    api_key = require_api_key(provider, name, purpose)
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
            f"{name} / {provider.model} 走 {provider.api} 协议，"
            f"需要 {package}（缺 {exc.name}）。\n"
            f"  uv sync    # 重新装齐依赖；或 pip install {package}"
        ) from exc


def bind_schema(llm: Any, schema: type[BaseModel], method: str) -> Any:
    """把结构化输出 schema 绑到模型上。

    ``auto`` 不传 ``method``，让 langchain 按 provider 选它自己的默认实现；
    其余取值原样传下去——兼容端点（DeepSeek 之类）常常得显式指定。
    """
    if method == "auto":
        return llm.with_structured_output(schema)
    return llm.with_structured_output(schema, method=method)


def schema_instruction(schema: type[BaseModel], method: str) -> str:
    """``json_mode`` 下要自己附给模型的输出要求；其余方式返回空串。

    langchain 只在 json_schema / function_calling 两种方式下把 schema 发出去，
    ``json_mode`` 下它只说「输出 JSON」。走兼容端点时常常只能用 json_mode，
    这段就是为它们准备的。
    """
    if method != "json_mode":
        return ""
    body = json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)
    return (
        "输出要求：只输出一个 JSON 对象，符合下面的 JSON Schema，"
        f"不要包代码块、不要写任何解释文字。\n{body}"
    )
