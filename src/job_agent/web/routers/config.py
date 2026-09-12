"""配置：读与改。**页面上能改的就是全部配置项**。

Web 端是这个求职系统的完整入口——一条 ``job web`` 起来之后，从填 token、
配搜索条件，到调打分口径、改简历与提示词，再到投递，全程不必回终端。
所以这里不设「只读的那一半」：凡是配置文件里有的，页面上都能改。

改法有两种，覆盖面不同：

- ``/sections/{段名}`` 按段改，字段有模型校验，前端渲染成表单。
  段名表由 :func:`~job_agent.config.config_sections` 遍历配置模型得出，
  加一个段不需要来这里补路由；
- ``/files/{global|profile}`` 整份文本改，给「高级」页。
  落盘前先 parse + 按模型校验，坏内容进不了文件。

还有两类不是 TOML 的：``/docs`` 是简历与求职偏好（自由 Markdown），
``/prompts`` 是 LLM 打分两个维度的方法论覆盖（空 = 回到内置默认）。

**密钥给明文**。服务只监听本机、单人使用，「打得开这个页面」与
「``cat`` 得到这个文件」是同一份权限；打码只会让人没法在页面上填 token。
明文仍然是**要主动写出来**的动作（``context={REVEAL_SECRETS: True}``），
所以日志、``job config show --json`` 这些顺手序列化的地方照旧不漏。

**改的仍然是文件**：写回那两个 ``*.toml``（或 profile 目录下的 md），再
``reload_settings()`` 重新读一遍。生效的永远是文件里那份，所以 CLI、Web、
agent 三条路读到的是同一套——不存在「网页上改了但 CLI 跑的是另一套」。
按键定点替换、不重排注释与对齐，见 :mod:`job_agent.config.writer`。
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from job_agent.config import (
    PROFILE_NAME,
    REVEAL_SECRETS,
    ConfigScope,
    SectionTarget,
    Settings,
    config_sections,
    default_config_path,
    read_section,
    read_text,
    section_target,
    write_prompt,
    write_raw,
    write_score,
    write_search,
    write_section,
)
from job_agent.context import AppContext
from job_agent.core.llm import APPEAL_SYSTEM, FIT_SYSTEM, load_score_prompts
from job_agent.errors import ConfigError
from job_agent.web.deps import ContextDep
from job_agent.web.schemas import (
    ConfigFilesResponse,
    ConfigFileUpdate,
    ConfigFileView,
    ConfigResponse,
    DocKind,
    DocsResponse,
    DocUpdate,
    DocView,
    PromptsResponse,
    PromptsUpdate,
    PromptView,
    SectionsResponse,
    SectionUpdate,
    SectionView,
)

router = APIRouter(prefix="/config", tags=["config"])


@router.get("", response_model=ConfigResponse, summary="当前生效的配置（含密钥明文）")
def get_config(context: ContextDep) -> JSONResponse:
    """整棵配置树，路径已解析成绝对路径。

    **要改某一段请用** ``/sections``：这里的路径是解析后的绝对路径，
    照它写回去会把 ``data/jobs.db`` 变成某台机器上的绝对路径。
    """
    return _config_response(context)


@router.get("/sections", response_model=SectionsResponse, summary="每个配置段在文件里的值")
def get_sections(context: ContextDep) -> SectionsResponse:
    """所有可写的段，一次全给。

    值从**文件**里读（不是从生效的配置树），所以相对路径还是相对路径，
    原样发回来保存不会把它换成绝对路径。
    """
    settings = context.settings
    return SectionsResponse(
        sections=[
            SectionView(
                name=name,
                scope=target.scope,
                file=str(_section_file(settings, target)),
                values=read_section(_section_file(settings, target), name).model_dump(
                    mode="json", context={REVEAL_SECRETS: True}
                ),
            )
            for name, target in sorted(config_sections().items())
        ]
    )


@router.put("/sections/{section}", response_model=ConfigResponse, summary="改写一整段")
def update_section(context: ContextDep, section: str, payload: SectionUpdate) -> JSONResponse:
    """校验、写回、重新加载，返回改完之后生效的整棵配置树。

    ``[search]`` 与 ``[score]`` 走各自的写法：前者要保住关键词数组里注释掉的
    候选词，后者是数组表、按键对不齐只能整段重写。别的段按键定点替换。

    分数**不会**跟着变：``[score]`` 一改，指纹就和 ``job_scores`` 里存的那份
    对不上，``/api/stats`` 的 ``score.stale`` 立刻为真，页面据此提示「该重新打分了」。
    这里刻意不顺手替用户重打一遍——分数是整表重写，什么时候重算得由人说，
    保存一个权重就静默动全库排名，回看时分不清名次为什么变了。
    """
    settings = context.settings
    target = section_target(section)
    path = _section_file(settings, target)
    model = _validate(target, payload.values)

    if section == "search":
        write_search(path, model)  # type: ignore[arg-type]
    elif section == "score":
        write_score(path, model)  # type: ignore[arg-type]
    else:
        write_section(path, section, model)
    context.reload_settings()
    return _config_response(context)


@router.get("/files", response_model=ConfigFilesResponse, summary="两个配置文件的原文")
def get_files(context: ContextDep) -> ConfigFilesResponse:
    """给「高级」页的文本编辑器。含密钥明文，含全部注释。

    文件不存在也返回一条（``text`` 为空、``exists`` 为假）：
    profile.toml 缺失是合法状态，页面上要能直接新建它。
    """
    return ConfigFilesResponse(
        files=[_file_view(context.settings, scope) for scope in ConfigScope]
    )


@router.put("/files/{scope}", response_model=ConfigResponse, summary="整份替换一个配置文件")
def update_file(context: ContextDep, scope: ConfigScope, payload: ConfigFileUpdate) -> JSONResponse:
    """**先校验再落盘**：parse 不过或字段不合法就原地拒绝，文件一个字节不动。

    校验走的就是平时加载配置的那两个模型，所以「页面上保存成功」
    等价于「下次 CLI 起得来」——否则一次手滑就能把配置写成读不出来的样子，
    而下一个读它的可能是明早无人值守跑的 ``job agent``。

    只有一种情况是「写进去了但这次没生效」：把 ``[storage].database``
    改成了别的库。仓储握着旧库的连接，换设置不换连接会变成「设置说 A、
    读写落在 B」，所以那时报错要人重启——错误信息里会说清文件已经改了。
    """
    settings = context.settings
    write_raw(_config_file(settings, scope), scope, payload.text, root=settings.root)
    context.reload_settings()
    return _config_response(context)


@router.get("/docs", response_model=DocsResponse, summary="简历与求职偏好")
def get_docs(context: ContextDep) -> DocsResponse:
    """profile 目录下的两份自由 Markdown。

    它们是 LLM 打分的**判断依据**：``preferences.md`` 里的求职期望决定岗位
    吸引力的分数区间，``resume.md`` 决定胜任匹配度。改完库里已有的 LLM 分数
    就不可比了，所以 ``/api/stats`` 会照提示词指纹那套报 stale。
    """
    settings = context.settings
    return DocsResponse(docs=[_doc_view(settings, kind) for kind in DocKind])


@router.put("/docs/{kind}", response_model=DocsResponse, summary="改写简历或求职偏好")
def update_doc(context: ContextDep, kind: DocKind, payload: DocUpdate) -> DocsResponse:
    """整份替换。空内容也照写——简历写了一半存一下是正常操作。

    和提示词不同：那两份「空 = 删掉覆盖文件、回到内置默认」，
    这两份没有内置默认可回，本来就该是用户自己的东西。
    """
    settings = context.settings
    path = _doc_path(settings, kind)
    text = payload.content
    _write_doc(path, text if text.endswith("\n") or not text else text + "\n")
    return DocsResponse(docs=[_doc_view(settings, item) for item in DocKind])


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


# ------------------------------------------------------------------ 内部


def _validate(target: SectionTarget, values: dict[str, object]) -> BaseModel:
    """按段名对应的模型校验前端发来的那份。

    ``extra="forbid"`` 会挡下拼错的字段名——静默忽略是配置系统最容易埋的坑，
    在页面上更甚：表单看着保存成功了，值却没生效。
    """
    try:
        return target.model.model_validate(values)
    except ValidationError as exc:
        raise ConfigError(f"[{target.name}] 校验不过：{exc}") from exc


def _section_file(settings: Settings, target: SectionTarget) -> Path:
    return _config_file(settings, target.scope)


def _config_file(settings: Settings, scope: ConfigScope) -> Path:
    """一个 scope 写回哪个文件。

    全局配置文件可能还不存在（跑在默认值上），这时用它**应该在**的位置——
    页面上保存就等于顺手把它建出来。
    """
    if scope is ConfigScope.PROFILE:
        return settings.profile_dir / PROFILE_NAME
    return settings.config_file or default_config_path(settings.root)


def _file_view(settings: Settings, scope: ConfigScope) -> ConfigFileView:
    path = _config_file(settings, scope)
    return ConfigFileView(
        scope=scope, path=str(path), text=read_text(path), exists=path.is_file()
    )


def _doc_path(settings: Settings, kind: DocKind) -> Path:
    return (
        settings.profile.resume if kind is DocKind.RESUME else settings.profile.preferences
    )


def _doc_view(settings: Settings, kind: DocKind) -> DocView:
    path = _doc_path(settings, kind)
    return DocView(kind=kind, path=str(path), content=read_text(path), exists=path.is_file())


def _write_doc(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f"{path.name}.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
    except OSError as exc:
        raise ConfigError(f"写入失败（{path}）：{exc}") from exc


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


def _config_response(context: AppContext) -> JSONResponse:
    """整棵配置树，密钥给明文。

    手写 :class:`JSONResponse` 而不是靠 ``response_model``：明文要靠序列化
    上下文打开（见 :data:`~job_agent.config.REVEAL_SECRETS`），
    而 FastAPI 自己那次序列化传不了上下文。
    """
    settings = context.settings
    payload = ConfigResponse(settings=settings, paths=settings.paths())
    return JSONResponse(payload.model_dump(mode="json", context={REVEAL_SECRETS: True}))
