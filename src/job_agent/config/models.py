"""配置模型。

配置分两个文件，**段名完全不重叠**：

- ``config/config.toml`` → :class:`GlobalSettings`，管「怎么连」：猎聘账号密钥、
  限速、模型接入点、Web 端口、日志。跟人无关，所有 profile 共享一份。
- ``profiles/<name>/profile.toml`` → :class:`ProfileSettings`，管「找什么」：
  简历、求职偏好、搜索条件与关键词、匹配门槛、报告。**随人而变**。

不重叠是刻意的：同一个段要是能出现在两个文件里，下场一定是「改了一个忘了另一个」。
放错文件时 ``extra="forbid"`` 会当场报错，loader 再按段名告诉你它该在哪个文件里。
段不重叠还顺带保证了环境变量覆盖没有歧义——``JOB_AGENT_<段>__<字段>``
只可能落到其中一个模型上。

两个半边在 loader 里组装成 :class:`Settings`（下游只认它，不关心字段来自哪个文件）。

所有模型都是 ``extra="forbid"``：配置项拼错时立刻报错，而不是被静默忽略
——静默忽略是配置系统最容易埋的坑（比如把 salary_floor 写成 salaryFloor，
结果搜出一堆不达标的岗位却毫无提示）。

密钥也住在这棵树里（``config/config.toml`` 整个文件都不进版本库），
每个密钥字段的类型都是 :data:`Secret`——序列化时自动打码，
防泄漏靠类型而不是靠「记得在某个 redacted() 里逐个加」。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from job_agent.core.liepin.constants import (
    DEFAULT_BASE_URL,
    DEFAULT_RATE_LIMIT_PER_MIN,
    DEFAULT_TIMEOUT,
    MAX_PAGE,
)
from job_agent.core.liepin.enums import EduLevel, SalaryKind, WorkExperience
from job_agent.errors import MissingTokenError


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", use_enum_values=True)


def _clean_secret(value: Any) -> Any:
    """``key = ""`` 这种空值视同没配，避免空字符串一路漏到请求头里。"""
    if isinstance(value, str):
        return value.strip() or None
    return value


#: 密钥字段。``SecretStr`` 在 ``model_dump(mode="json")`` 里自动变成
#: ``**********``，所以 ``job config show --json`` 与 Web 的 ``/api/config``
#: 天然不会漏密钥——新增一个密钥字段不需要再去别处补脱敏逻辑。
Secret = Annotated[SecretStr | None, BeforeValidator(_clean_secret)]


class ProfilesConfig(_Model):
    """profile 的存放位置与默认选谁（全局）。

    一个 profile = 一个用户或一种求职场景，输入、配置、产物、数据库全都在
    ``<dir>/<name>/`` 这一个自包含的目录里——复制文件夹就是复制 profile。
    """

    dir: Path = Path("profiles")
    #: 不带 ``--profile`` 时用哪个。留空且只有一个 profile 时自动用那个
    default: str | None = None


class ProfileConfig(_Model):
    """求职者信息（profile 文件）。

    ``resume`` 与 ``preferences`` 是写报告「给我的建议」章节时的输入，
    也是 ``job-init`` skill 访谈后落地的两个文件。程序不解析它们的内容——
    刻意保持自由格式的 Markdown，人和模型都好读好改。
    """

    name: str = ""
    #: 用全局 ``[liepin.accounts.*]`` 里的哪个账号搜索与投递。
    #: profile 换成另一个人时，换的是这一行
    account: str = "default"
    resume: Path = Path("resume.md")
    preferences: Path = Path("preferences.md")


class KeywordGroup(_Model):
    """一组搜索关键词。

    ``track`` 只是这组关键词的**标签**，给人看的（配置里分组、Web 上展示），
    程序不拿它做任何判断——赛道分类是分析，不在这个仓库里，见 CLAUDE.md
    「不承担市场分析」一节。所以它是自由文本：写「前端」「数据」「Web3」都行。
    """

    track: str = Field(min_length=1)
    keywords: list[str] = Field(min_length=1)
    enabled: bool = True

    @field_validator("keywords")
    @classmethod
    def _strip(cls, value: list[str]) -> list[str]:
        cleaned = [k.strip() for k in value if k.strip()]
        if not cleaned:
            raise ValueError("keywords 不能为空")
        return cleaned


class SearchConfig(_Model):
    """搜索条件。字段留空即不按该维度过滤。"""

    address: str | None = "北京"
    salary_kind: SalaryKind | None = None
    # 单位为「元」，按薪资区间**重叠**过滤（不是「下限 ≥ 该值」），
    # salaryKind=年薪 时把职位薪资年化后比较。数值过小（如 50）等同不过滤。
    salary_floor: int | None = Field(default=None, ge=0)
    salary_cap: int | None = Field(default=None, ge=0)
    edu_level: EduLevel | None = None
    work_experience: WorkExperience | None = None
    max_pages: int = Field(default=MAX_PAGE, ge=1, le=MAX_PAGE)
    groups: list[KeywordGroup] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_salary(self) -> SearchConfig:
        if (
            self.salary_cap is not None
            and self.salary_floor is not None
            and self.salary_cap < self.salary_floor
        ):
            raise ValueError("salary_cap 不能小于 salary_floor")
        if (self.salary_floor or self.salary_cap) and self.salary_kind is None:
            raise ValueError("配置了 salary_floor / salary_cap 时必须同时给出 salary_kind")
        return self

    @property
    def enabled_groups(self) -> list[KeywordGroup]:
        return [g for g in self.groups if g.enabled]

    @property
    def keywords(self) -> list[str]:
        """按配置顺序（= 优先级）展开的关键词，去重且保留首次出现的位置。"""
        seen: dict[str, None] = {}
        for group in self.enabled_groups:
            for keyword in group.keywords:
                seen.setdefault(keyword, None)
        return list(seen)


class LiepinAccount(_Model):
    """一个猎聘账号。

    ``token`` 是账号的全部内容，所以这是个只有一个字段的表——但仍然是个表：
    一个 profile 可能是「另一个人」，得能同时存着几个人的 token 而不用来回粘贴。
    照搬 ``[agent.providers.*]`` 的写法：加一个账号是抄一段配置，不是改代码。
    """

    #: 猎聘用户 token，前往 https://www.liepin.com/mcp/auth 生成。
    #: 没有它就搜不了也投不了
    user_token: Secret = None


def _default_accounts() -> dict[str, LiepinAccount]:
    """一个都没配时的默认：一个空账号，跑 ``/job-init`` 时再填 token。"""
    return {"default": LiepinAccount()}


class LiepinConfig(_Model):
    """猎聘 API 客户端参数（全局）。"""

    #: 全部账号，key 是自己起的名字；profile 的 ``[profile].account`` 指哪个用哪个。
    #: 用 ``JOB_AGENT_LIEPIN__ACCOUNTS__<名>__USER_TOKEN`` 可临时覆盖
    accounts: dict[str, LiepinAccount] = Field(default_factory=_default_accounts)
    base_url: str = DEFAULT_BASE_URL
    timeout: float = Field(default=DEFAULT_TIMEOUT, gt=0)
    # 调大有风险：服务端限流触发后冷却 20 分钟以上，期间任何请求都被拒
    rate_limit_per_min: int = Field(default=DEFAULT_RATE_LIMIT_PER_MIN, ge=1, le=60)


class DetailConfig(_Model):
    """详情页抓取参数。详情页是普通网页、不走 API，节奏得自己控。"""

    sleep_min: float = Field(default=1.2, ge=0)
    sleep_max: float = Field(default=2.5, ge=0)
    block_backoff: float = Field(default=300.0, ge=0)
    max_retries: int = Field(default=3, ge=1)
    timeout: float = Field(default=30.0, gt=0)
    user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    @model_validator(mode="after")
    def _check_sleep(self) -> DetailConfig:
        if self.sleep_max < self.sleep_min:
            raise ValueError("sleep_max 不能小于 sleep_min")
        return self


class StorageConfig(_Model):
    database: Path = Path("data/jobs.db")


class MatchConfig(_Model):
    """岗位匹配的输入与产物位置。

    真正的信号表在 ``rules`` 指向的独立文件里，不在这里——它是一张几十行的
    数据表，且**随人而变**：对一个做应用工程的人「算法训练岗」是负信号，
    对一个做算法的人就是正信号。所以它属于 ``config/``，绝不能进代码。
    """

    rules: Path = Path("match.toml")
    #: `job shortlist` 的默认输出位置
    shortlist_output: Path = Path("data/shortlist.md")
    #: 只看薪资上限不低于这个数的岗位（万元/年，税前口径）。留空表示不过滤
    salary_floor_wan: float | None = Field(default=None, ge=0)


class LangSmithConfig(_Model):
    """LangSmith 运行追踪（agent 路线可选）。

    填了 ``api_key`` 就启用，不填就完全不上报——只有一个必填项，
    不存在「配了一半，SDK 静默不上报」那种查不出原因的中间态。

    LangSmith 的追踪是 langchain-core 内建的，靠环境变量开关，
    不需要像别的追踪后端那样往 ``config["callbacks"]`` 里挂 handler。
    """

    api_key: Secret = None
    #: trace 归到哪个 project 下（LangSmith 里按它分组检索）
    project: str = "job-agent"
    #: 自托管才填；留空走 LangSmith 官方云
    endpoint: str | None = None

    @property
    def enabled(self) -> bool:
        return self.api_key is not None


#: ``with_structured_output`` 的实现方式。``auto`` = 交给 langchain 按 provider 选默认
StructuredMethod = Literal["auto", "json_schema", "function_calling", "json_mode"]


class ModelProvider(_Model):
    """一个模型接入点（审读节点用哪家的模型）。

    ``api`` 只有两个取值，因为客户端只需要两类：Anthropic 原生协议，
    以及 OpenAI 协议。ChatGPT、DeepSeek、Kimi、通义、GLM、本地 vLLM/Ollama
    全都兼容 OpenAI 协议——它们不需要各自的适配代码，只需要填自己的
    ``base_url``。加一家新模型是**加一段配置**，不是改代码。
    """

    #: 必填，不给默认：漏填时按哪家连都可能是错的，而错了只会在调用时报
    #: 一个看不懂的鉴权失败。表名（deepseek / kimi…）是自己起的，推断不出协议
    api: Literal["anthropic", "openai"]
    #: 模型 ID，按各家文档原样填（claude-opus-5 / gpt-5 / deepseek-chat…）
    model: str
    api_key: Secret = None
    #: 非官方端点才填（DeepSeek、Kimi、本地推理…）；留空走该 api 的官方地址
    base_url: str | None = None
    #: 审读裁决要求固定 schema，各家的结构化输出实现方式不同、支持度还会变，
    #: 所以是配置项而不是按 provider 名硬猜：Anthropic / OpenAI 官方端点留
    #: ``auto`` 即可，兼容端点通常要显式 ``function_calling`` 或 ``json_mode``
    structured_output: StructuredMethod = "auto"
    max_tokens: int = Field(default=4096, ge=256, le=65536)
    #: 审读要的是可复核的判断，默认 0；调高只会让两次运行更不可比
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


def _default_providers() -> dict[str, ModelProvider]:
    """一个都没配时的默认：一个 Claude 接入点（key 留空，要用时再填）。"""
    return {"anthropic": ModelProvider(api="anthropic", model="claude-opus-5")}


class AgentConfig(_Model):
    """LangGraph 独立执行路线（``src/job_agent/agent/``，装 ``agent`` extra 才可用）。

    这里只放**运行参数与密钥**（跟人无关，所以整张表都在全局
    ``config/config.toml`` 里）。判断的依据（简历、偏好、信号表）来自 profile
    文件的 ``profile`` 与 ``match``——两条执行路线共享同一份「这个人是谁」。

    例外要留意：``checkpoint`` 与 ``plan_output`` 虽然写在全局文件里，
    却按**当前 profile 的目录**解析（见 loader 的 ``_PROFILE_PATH_FIELDS``）——
    它们是每次运行的产物，必须跟着 profile 走，不能几个 profile 互相覆盖。
    """

    #: 选中 ``providers`` 里的哪一个。换模型只改这一行（或 ``--provider``）
    provider: str = "anthropic"
    #: 全部模型接入点，key 是自己起的名字。几家的 key 可以长期并存，
    #: 换模型不用来回粘贴密钥
    providers: dict[str, ModelProvider] = Field(default_factory=_default_providers)
    #: 规则分诊后送 LLM 审读的岗位数上限。审读是按条计费的，这是成本闸门
    top_n: int = Field(default=30, ge=1, le=200)
    #: 并行审读的上限，防 API 限流
    max_concurrency: int = Field(default=4, ge=1, le=16)
    #: LangGraph checkpoint 数据库（断点续跑与运行审计都靠它）
    checkpoint: Path = Path("data/agent-checkpoint.db")
    #: 投递计划的输出位置
    plan_output: Path = Path("data/agent-plan.md")
    langsmith: LangSmithConfig = Field(default_factory=LangSmithConfig)

    @model_validator(mode="after")
    def _provider_must_exist(self) -> AgentConfig:
        if self.provider not in self.providers:
            known = "、".join(sorted(self.providers)) or "（一个都没定义）"
            raise ValueError(
                f'provider = "{self.provider}" 没有对应的 '
                f"[agent.providers.{self.provider}] 表；已定义的有：{known}"
            )
        return self

    @property
    def active(self) -> ModelProvider:
        """当前选中的接入点。``provider`` 在校验期就保证指得到人。"""
        return self.providers[self.provider]

    @property
    def model_label(self) -> str:
        """写进投递计划与日志的模型标识：换了模型，产出要能看出来。"""
        return f"{self.provider} / {self.active.model}"


class WebConfig(_Model):
    host: str = "127.0.0.1"
    port: int = Field(default=18000, ge=1, le=65535)
    open_browser: bool = True
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    #: 前端构建产物目录；不存在时后端只提供 API
    frontend_dist: Path = Path("frontend/dist")


class LoggingConfig(_Model):
    level: str = "INFO"
    file: Path | None = None

    @field_validator("level")
    @classmethod
    def _upper(cls, value: str) -> str:
        level = value.upper()
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if level not in allowed:
            raise ValueError(f"level 只能是 {'/'.join(sorted(allowed))}")
        return level


class _FileSettings(BaseSettings):
    """两个配置文件模型的共同基类：同一套分层规则与环境变量语法。

    分层由 pydantic-settings 完成：**环境变量 > TOML**。任意配置项都可用
    ``JOB_AGENT_<节>__<字段>`` 覆盖（如 ``JOB_AGENT_WEB__PORT=19999``），
    密钥也不例外——因为两个文件的段名不重叠，一个环境变量只可能落到其中一边，
    不存在「该覆盖哪个文件」的歧义。
    """

    model_config = SettingsConfigDict(
        extra="forbid",
        use_enum_values=True,
        env_prefix="JOB_AGENT_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # init 里装的是 TOML 内容，环境变量要能覆盖 TOML，所以 env 排在前面。
        # dotenv / secrets 目录两个来源刻意不接：配置只有那两个 *.toml 落盘
        return (env_settings, init_settings)


class GlobalSettings(_FileSettings):
    """``config/config.toml``——管「怎么连」，所有 profile 共享一份。

    换账号、换模型、换机器改这里；换求职方向不该动它一个字。
    ``root`` / ``config_file`` 不来自 TOML，由 loader 注入。
    """

    root: Path
    config_file: Path | None = None

    profiles: ProfilesConfig = Field(default_factory=ProfilesConfig)
    liepin: LiepinConfig = Field(default_factory=LiepinConfig)
    detail: DetailConfig = Field(default_factory=DetailConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    web: WebConfig = Field(default_factory=WebConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


class ProfileSettings(_FileSettings):
    """``profiles/<name>/profile.toml``——管「找什么」，随人而变。

    一个 profile = 一个用户或一种求职场景。这里的每一项都是个人取向，
    所以它们在配置里而不在代码里：换个人跑只换这个目录，``src/`` 一行不改。
    """

    profile: ProfileConfig = Field(default_factory=ProfileConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    match: MatchConfig = Field(default_factory=MatchConfig)


class Settings(BaseModel):
    """两个半边组装成的完整配置树，下游只认它。

    刻意不是 ``BaseSettings``：环境变量已经在 :class:`GlobalSettings` 与
    :class:`ProfileSettings` 各自的构造里生效过了，这里再叠一层只会让
    「哪一层赢」变得难讲。

    所有路径字段在 loader 里已解析为绝对路径：profile 侧的相对 profile 目录，
    ``web`` / ``logging`` 侧的相对项目根。
    """

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    root: Path
    config_file: Path | None = None
    #: 当前 profile 的名字（= 目录名），会写进投递计划与 Web 界面
    profile_name: str
    profile_dir: Path
    profile_file: Path | None = None

    # ---- 来自 config/config.toml
    profiles: ProfilesConfig
    liepin: LiepinConfig
    detail: DetailConfig
    agent: AgentConfig
    web: WebConfig
    logging: LoggingConfig

    # ---- 来自 profiles/<name>/profile.toml
    profile: ProfileConfig
    search: SearchConfig
    storage: StorageConfig
    match: MatchConfig

    @model_validator(mode="after")
    def _account_must_exist(self) -> Settings:
        """跨文件校验只能放在组装完之后：profile 指的账号得在全局定义过。"""
        if self.profile.account not in self.liepin.accounts:
            known = "、".join(sorted(self.liepin.accounts)) or "（一个都没定义）"
            raise ValueError(
                f'[profile].account = "{self.profile.account}"（{self.profile_file}）'
                f" 没有对应的 [liepin.accounts.{self.profile.account}] 表"
                f"（{self.config_file}）；已定义的账号：{known}"
            )
        return self

    @property
    def account(self) -> LiepinAccount:
        """当前 profile 选中的猎聘账号。校验期已保证指得到人。"""
        return self.liepin.accounts[self.profile.account]

    def require_token(self) -> str:
        """取当前 profile 的猎聘 token，没有就抛 :class:`MissingTokenError`。

        这是**唯一**该把密钥取成明文的地方（构造 HTTP 请求头时）：
        其余代码一律拿 ``SecretStr``，打印和序列化都自动打码。
        """
        token = self.account.user_token
        if token is None:
            raise MissingTokenError
        return token.get_secret_value()

    def paths(self) -> ConfigPaths:
        """解析好的关键路径清单。"""
        return ConfigPaths(
            profile=self.profile_name,
            root=self.root,
            configFile=self.config_file,
            profileDir=self.profile_dir,
            profileFile=self.profile_file,
            database=self.storage.database,
            resume=self.profile.resume,
            preferences=self.profile.preferences,
            match=self.match.rules,
            shortlist=self.match.shortlist_output,
        )


class ConfigPaths(_Model):
    """当前生效的关键路径，都是绝对路径，便于排查「到底读的哪份文件」。

    住在配置层而不是 web 层：``job config path --json`` 与 ``/api/config``
    要给出同一份答案，两边各写一份的下场是加了字段只改一处。
    skill 靠它定位简历、信号表与数据库——路径随 profile 变，不该再硬编码。
    """

    #: 当前 profile 名。放第一个：看这份输出时第一个要确认的就是「这是谁的」
    profile: str
    root: Path
    configFile: Path | None = None
    profileDir: Path
    profileFile: Path | None = None
    database: Path
    resume: Path
    preferences: Path
    match: Path
    shortlist: Path
