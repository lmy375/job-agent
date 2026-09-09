"""当前配置：读（脱敏）+ 改三样随人而变的东西。

**能在页面上改的只有三处**：``[search].keywords``、``[score]``，
以及 **LLM 打分的两段提示词**——求职过程中真正需要反复调的就是
「搜什么词」「什么算对口」「怎么判断一个岗好不好、自己够不够格」，
让人为了改一个权重或一句话去翻文件，是把最高频的动作放到了最远的地方。

判据是「它是不是判断口径」：三样都是，改完就该重打分。其余配置仍然只读——
猎聘 token、模型接入点、并发、限速、日志属于「怎么连」，一次配好就不动，
而且密钥不该有回显它的接口。要加第四个可编辑项之前，先问它是不是也这么高频。

**改的仍然是文件**：写回 ``profiles/<名>/profile.toml``，再
``reload_settings()`` 重新读一遍。生效的永远是文件里那份，所以
CLI、Web、agent 三条路读到的是同一套——不存在「网页上改了但 CLI 跑的是另一套」。
定点替换、不重排注释，见 :mod:`job_agent.config.writer`。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from job_agent.config import (
    PROFILE_NAME,
    SearchConfig,
    Settings,
    write_keywords,
    write_prompt,
    write_score,
)
from job_agent.context import AppContext
from job_agent.core.llm import APPEAL_SYSTEM, FIT_SYSTEM, load_score_prompts
from job_agent.web.deps import ContextDep
from job_agent.web.schemas import (
    ConfigResponse,
    KeywordsUpdate,
    PromptsResponse,
    PromptsUpdate,
    PromptView,
    ScoreUpdate,
)

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ConfigResponse, summary="当前生效的配置（密钥已打码）")
def get_config(context: ContextDep) -> ConfigResponse:
    return _response(context)


@router.put("/keywords", response_model=ConfigResponse, summary="改写搜索关键词")
def update_keywords(context: ContextDep, payload: KeywordsUpdate) -> ConfigResponse:
    """写回 ``[search].keywords``（顺序即优先级），返回重新加载后的配置。

    先过一遍 :class:`~job_agent.config.SearchConfig` 再落盘：去空白、丢空串、
    去重且保留首次出现的位置——写进文件的就是会生效的那份，
    不让人看着文件里有 6 个词、实际搜的却是 5 个。
    """
    settings = context.settings
    cleaned = SearchConfig.model_validate(
        {**settings.search.model_dump(), "keywords": payload.keywords}
    )
    write_keywords(settings.profile_dir / PROFILE_NAME, cleaned.keywords)
    context.reload_settings()
    return _response(context)


@router.put("/score", response_model=ConfigResponse, summary="改写 [score] 打分逻辑")
def update_score(context: ContextDep, payload: ScoreUpdate) -> ConfigResponse:
    """写回整个 ``[score]`` 段，返回重新加载后的配置。

    落库的分数**不会**跟着变：``[score]`` 一改，指纹就与 ``job_scores`` 里存的那份
    不一致，``/api/stats`` 的 ``score.stale`` 立刻为真，页面据此提示「该重新打分了」。
    这里刻意不顺手替用户重打一遍——分数是整表重写，什么时候重算得由人说，
    保存一个权重就静默动全库排名，回看时分不清名次为什么变了。
    """
    write_score(context.settings.profile_dir / PROFILE_NAME, payload)
    context.reload_settings()
    return _response(context)


@router.get("/prompts", response_model=PromptsResponse, summary="LLM 打分的两段提示词")
def get_prompts(context: ContextDep) -> PromptsResponse:
    """返回当前生效的两段全文，以及它们是内置默认还是 profile 里的覆盖。

    内置默认也照样返回全文而不是空串：页面上要能直接看到、直接改——
    让人先去 GitHub 上找一遍默认提示词再粘回来，是最没必要的一步。
    """
    return _prompts(context.settings)


@router.put("/prompts", response_model=PromptsResponse, summary="改写 LLM 打分提示词")
def update_prompts(context: ContextDep, payload: PromptsUpdate) -> PromptsResponse:
    """写回 profile 目录下的两份 md，返回改完之后生效的那份。

    **和内置默认逐字相同的内容不落盘**：那不是「自定义」，存下来只会让以后
    改进默认方法论时传不到这个 profile。空串同理——直接删掉覆盖文件。

    改完库里已有的 LLM 分数就过期了（提示词指纹变了），``/api/stats`` 的
    ``llmScore.stale`` 会为真。这里刻意不顺手重打一遍：一次几百条的模型调用
    得由人按下按钮，不能是保存一句话的副作用。
    """
    settings = context.settings
    for content, default, path in (
        (payload.appeal, APPEAL_SYSTEM, settings.profile.score_appeal_prompt),
        (payload.fit, FIT_SYSTEM, settings.profile.score_fit_prompt),
    ):
        write_prompt(path, "" if content.strip() == default.strip() else content)
    return _prompts(settings)


def _prompts(settings: Settings) -> PromptsResponse:
    prompts = load_score_prompts(settings)
    return PromptsResponse(
        appeal=_prompt_view(
            prompts.appeal, prompts.appeal_custom, settings.profile.score_appeal_prompt
        ),
        fit=_prompt_view(prompts.fit, prompts.fit_custom, settings.profile.score_fit_prompt),
        fingerprint=prompts.fingerprint,
        modelLabel=settings.llm_score_model_label,
    )


def _prompt_view(content: str, custom: bool, path: Path) -> PromptView:
    return PromptView(content=content, isDefault=not custom, path=str(path))


def _response(context: AppContext) -> ConfigResponse:
    settings = context.settings
    return ConfigResponse(
        # 密钥字段是 SecretStr，序列化成 JSON 时自动变 ``**********``
        settings=settings,
        paths=settings.paths(),
    )
