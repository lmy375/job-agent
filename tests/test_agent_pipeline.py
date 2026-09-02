"""agent 路线的确定性部分（pipeline.py / llm.py 的纯适配逻辑）。

刻意不测 LLM 节点与组图——那需要 agent extra 和网络。
这里只验证：档案缺失报错、分诊载荷、计划渲染、多 provider 配置的解析、
结构化输出方式的绑定与密钥/追踪配置的读取。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from conftest import PROFILE, make_detail, make_job
from job_agent.agent.llm import bind_review_schema, require_api_key
from job_agent.agent.pipeline import (
    JD_CHAR_LIMIT,
    build_shortlist,
    load_profile,
    render_plan,
)
from job_agent.agent.prompts import REVIEW_SYSTEM, review_system_message
from job_agent.agent.state import JDVerdict, ShortlistJob
from job_agent.config import Settings, load_settings
from job_agent.context import AppContext
from job_agent.errors import ConfigError


def _seed(ctx: AppContext, job_id: int = 1, description: str | None = None) -> None:
    ctx.jobs.upsert_many([make_job(job_id)], keyword="AI Agent")
    ctx.details.upsert(
        make_detail(
            job_id,
            description=description
            or ("岗位职责：负责 AI Agent 平台建设，熟悉 Python 与大模型应用。" * 3),
            responsibilities="负责 Agent 平台建设",
            requirements="熟悉 Python 与大模型",
        )
    )


def _verdict(job_id: int, **overrides: Any) -> JDVerdict:
    data: dict[str, Any] = {
        "job_id": job_id,
        "hard_gate_pass": True,
        "gate_reasons": ["经验年限：JD 要 5 年，简历 8 年，通过"],
        "priority": 3,
        "pitch": "有直接对口的平台建设经历",
        "risks": [],
    }
    data.update(overrides)
    return JDVerdict.model_validate(data)


def _shortlist_job(job_id: int, title: str, salary_high: float) -> ShortlistJob:
    return ShortlistJob(
        job_id=job_id,
        title=title,
        company="某公司",
        salary_high=salary_high,
        score=10.0,
        reasons="Agent",
        concerns="",
        jd="负责 Agent 平台",
    )


def test_load_profile_missing_file(settings: Settings) -> None:
    settings.profile.resume.unlink()
    with pytest.raises(ConfigError, match="简历文件不存在"):
        load_profile(settings)


def test_build_shortlist_payload(context: AppContext) -> None:
    _seed(context)
    payload = build_shortlist(context, top_n=10)
    assert len(payload) == 1
    job = payload[0]
    assert job.job_id == 1
    assert job.title == "AI Agent 工程师"
    assert job.salary_high is not None
    assert "Agent（标题）" in job.reasons
    assert "职责" in job.jd


def test_build_shortlist_truncates_jd(context: AppContext) -> None:
    _seed(context, description="AI Agent 大模型。" + "细节" * JD_CHAR_LIMIT)
    (job,) = build_shortlist(context, top_n=5)
    assert len(job.jd) <= JD_CHAR_LIMIT + 20
    assert job.jd.endswith("……（超长截断）")


def test_render_plan_orders_and_sections() -> None:
    shortlist = [
        _shortlist_job(1, "岗 A", 90),
        _shortlist_job(2, "岗 B", 120),
        _shortlist_job(3, "岗 C", 70),
    ]
    verdicts = [
        _verdict(1, priority=3),
        _verdict(2, priority=5, risks=["管理规模可能被追问"]),
        _verdict(3, hard_gate_pass=False, priority=1, gate_reasons=["要求博士，简历本科，不过"]),
    ]
    plan = render_plan(shortlist, verdicts, "deepseek / deepseek-chat")

    assert "建议投递 2 个，暂缓 1 个" in plan
    # 换了模型裁决口径就变了，计划里必须记下是谁判的，否则事后无从分辨
    assert "审读模型：deepseek / deepseek-chat" in plan
    # 通过者按优先级排：岗 B（5）在岗 A（3）前；不过者只出现在暂缓区
    assert plan.index("岗 B") < plan.index("岗 A") < plan.index("岗 C")
    assert plan.index("## 暂缓") < plan.index("岗 C")
    assert "要求博士" in plan
    assert "管理规模可能被追问" in plan
    assert "税前" in plan


def _load(project_root: Path, name: str, body: str) -> Settings:
    """按一段 TOML 片段单独加载一份全局配置（[agent] 整张表都住全局那一半）。"""
    path = project_root / "config" / name
    path.write_text(body, encoding="utf-8")
    return load_settings(PROFILE, path)


#: 三家并存的接入点：Claude 走原生协议，ChatGPT 与 DeepSeek 共用 OpenAI 协议
_PROVIDERS_TOML = """\
[agent]
provider = "deepseek"

[agent.providers.anthropic]
api = "anthropic"
model = "claude-opus-5"
api_key = "sk-ant-test"

[agent.providers.openai]
api = "openai"
model = "gpt-5"
api_key = "sk-openai-test"

[agent.providers.deepseek]
api = "openai"
model = "deepseek-chat"
api_key = "sk-deepseek-test"
base_url = "https://api.deepseek.com/v1"
structured_output = "function_calling"
"""


def test_require_api_key_from_toml(project_root: Path) -> None:
    settings = _load(
        project_root,
        "with-key.toml",
        '[agent.providers.anthropic]\napi = "anthropic"\n'
        'model = "claude-opus-5"\napi_key = "sk-ant-test"\n',
    )
    assert require_api_key(settings).get_secret_value() == "sk-ant-test"


def test_require_api_key_missing(settings: Settings) -> None:
    """报错要指到具体是哪张表缺 key——三家并存时「缺 key」本身不够定位。"""
    with pytest.raises(ConfigError, match=r"\[agent\.providers\.anthropic\]"):
        require_api_key(settings)


def test_active_provider_selected_by_name(project_root: Path) -> None:
    """换模型只改 [agent].provider 一行，几家的 key 长期并存。"""
    settings = _load(project_root, "providers.toml", _PROVIDERS_TOML)
    active = settings.agent.active
    assert active.api == "openai"  # DeepSeek 兼容 OpenAI 协议，共用一个客户端
    assert active.model == "deepseek-chat"
    assert active.base_url == "https://api.deepseek.com/v1"
    assert require_api_key(settings).get_secret_value() == "sk-deepseek-test"
    # 没选中的接入点照样留在配置里，不用来回粘贴密钥
    assert settings.agent.providers["anthropic"].api == "anthropic"
    assert settings.agent.model_label == "deepseek / deepseek-chat"


def test_unknown_provider_rejected_at_load(project_root: Path) -> None:
    """provider 指向不存在的表要在加载期就炸，而不是跑到审读节点才失败。"""
    with pytest.raises(ConfigError, match="没有对应的"):
        _load(
            project_root,
            "bad-provider.toml",
            '[agent]\nprovider = "kimi"\n'
            '[agent.providers.anthropic]\napi = "anthropic"\nmodel = "claude-opus-5"\n',
        )


def test_provider_key_overridable_by_env(
    project_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """密钥不想落盘时用环境变量覆盖——报错信息里就是这么说的，得真的成立。"""
    monkeypatch.setenv("JOB_AGENT_AGENT__PROVIDERS__DEEPSEEK__API_KEY", "sk-from-env")
    settings = _load(project_root, "providers-env.toml", _PROVIDERS_TOML)
    assert require_api_key(settings).get_secret_value() == "sk-from-env"
    # 覆盖单个字段不会把同表其它接入点冲掉
    assert sorted(settings.agent.providers) == ["anthropic", "deepseek", "openai"]


def test_missing_api_field_rejected(project_root: Path) -> None:
    """api 必填：表名推断不出协议，漏填要在加载期报，不能默默按某家连。"""
    with pytest.raises(ConfigError, match="api"):
        _load(
            project_root,
            "no-api.toml",
            '[agent.providers.anthropic]\nmodel = "claude-opus-5"\n',
        )


def test_default_provider_is_claude(settings: Settings) -> None:
    """一个 provider 都不配时也要能加载：默认一个 Claude 接入点（key 留空）。"""
    assert settings.agent.provider == "anthropic"
    assert settings.agent.active.api == "anthropic"
    assert settings.agent.active.structured_output == "auto"
    assert settings.agent.active.temperature == 0.0


class _FakeLLM:
    """记录 with_structured_output 收到的参数，验证 method 有没有传下去。"""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def with_structured_output(self, schema: Any, **kwargs: Any) -> str:
        self.calls.append({"schema": schema, **kwargs})
        return "bound"


def test_auto_structured_output_leaves_method_to_langchain() -> None:
    """auto 不传 method：官方端点各有各的默认实现，交给 langchain 选。"""
    llm = _FakeLLM()
    assert bind_review_schema(llm, JDVerdict, "auto") == "bound"
    assert llm.calls == [{"schema": JDVerdict}]


def test_explicit_structured_output_passes_method_through() -> None:
    """兼容端点常常只吃 function_calling / json_mode，得原样传下去。"""
    llm = _FakeLLM()
    bind_review_schema(llm, JDVerdict, "function_calling")
    assert llm.calls == [{"schema": JDVerdict, "method": "function_calling"}]


def test_json_mode_carries_schema_in_prompt() -> None:
    """json_mode 下 langchain 不发 schema，得由 prompt 带过去，否则字段全靠猜。"""
    assert review_system_message("auto") == REVIEW_SYSTEM
    assert review_system_message("function_calling") == REVIEW_SYSTEM
    prompt = review_system_message("json_mode")
    assert prompt.startswith(REVIEW_SYSTEM)
    for field in ("hard_gate_pass", "gate_reasons", "priority", "pitch"):
        assert field in prompt


def test_langsmith_off_by_default(settings: Settings) -> None:
    """不填 api_key 就完全不上报——追踪是可选项，不是默认项。"""
    assert settings.agent.langsmith.api_key is None
    assert settings.agent.langsmith.enabled is False


def test_langsmith_enabled_by_api_key(project_root: Path) -> None:
    """只有一个必填项：填了就启用，不存在「配了一半、SDK 静默不上报」的中间态。"""
    settings = _load(
        project_root,
        "with-langsmith.toml",
        '[agent.langsmith]\napi_key = "lsv2-test"\n'
        'project = "job-agent-test"\nendpoint = "https://langsmith.example.com"\n',
    )
    tracing = settings.agent.langsmith
    assert tracing.enabled
    assert tracing.api_key is not None
    assert tracing.api_key.get_secret_value() == "lsv2-test"
    assert tracing.project == "job-agent-test"
    assert tracing.endpoint == "https://langsmith.example.com"


def test_agent_paths_resolved_against_profile(project_root: Path, profile_dir: Path) -> None:
    """[agent] 的两个路径写在全局文件里，但按 **profile 目录** 解析。

    它们是每次运行的产物：几个 profile 共用一个全局 [agent] 表，
    但各写各的计划与 checkpoint，否则后跑的会盖掉先跑的。
    """
    settings = load_settings(PROFILE, project_root / "config" / "config.toml")
    assert settings.agent.checkpoint.is_absolute()
    assert settings.agent.checkpoint == profile_dir / "data" / "agent-checkpoint.db"
    assert settings.agent.plan_output == profile_dir / "data" / "agent-plan.md"
