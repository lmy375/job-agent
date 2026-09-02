"""当前配置：读（脱敏）+ 改两样随人而变的东西。

**能在页面上改的只有两处**：``[search].keywords`` 与 ``[score]``——
求职过程中真正需要反复调的就是「搜什么词」和「什么算对口」，
让人为了改一个权重去翻 TOML 是把最高频的动作放到了最远的地方。

其余配置仍然只读：猎聘 token、模型接入点、限速、日志属于「怎么连」，
一次配好就不动，而且密钥不该有回显它的接口。

**改的仍然是文件**：写回 ``profiles/<名>/profile.toml``，再
``reload_settings()`` 重新读一遍。生效的永远是文件里那份，所以
CLI、Web、agent 三条路读到的是同一套——不存在「网页上改了但 CLI 跑的是另一套」。
定点替换、不重排注释，见 :mod:`job_agent.config.writer`。
"""

from __future__ import annotations

from fastapi import APIRouter

from job_agent.config import PROFILE_NAME, SearchConfig, write_keywords, write_score
from job_agent.context import AppContext
from job_agent.web.deps import ContextDep
from job_agent.web.schemas import ConfigResponse, KeywordsUpdate, ScoreUpdate

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


def _response(context: AppContext) -> ConfigResponse:
    settings = context.settings
    return ConfigResponse(
        # 密钥字段是 SecretStr，序列化成 JSON 时自动变 ``**********``
        settings=settings,
        paths=settings.paths(),
    )
