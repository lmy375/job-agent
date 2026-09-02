# CLAUDE.md

## 产品核心定位：这是一个求职系统

不是爬虫，不是数据分析工具库。目标是端到端支撑一个人完成一次求职：
从「我是谁、我想要什么」开始，到「该投哪几个岗、为什么、怎么谈」结束。

**每次决定要不要加一个功能、加在哪，先用下面这张表对照。**

| 环节性质 | 归属 | 判据 |
| --- | --- | --- |
| 结论必须可重跑、可测试、两次一样 | **CLI**（`src/job_agent/`） | 采集、限流退避、去重、JD 解析、薪资换算、规则打分、排序 |
| 需要读懂文字才能下判断 | **Skill**（`.claude/skills/`） | 读 JD 比硬门槛、简历措辞体检、排投递优先级、写面试口径 |
| 随人而变 | **Profile**（`profiles/<名字>/`） | 简历、求职偏好、搜索关键词、匹配信号表 |

推论，违反了就是设计错误：

- **换一个用户，只应该换一个 profile，不该改代码。** 任何「AI Agent 是好岗位」
  这类个人取向，一旦出现在 `src/` 里就是 bug——它属于配置。
- **不要把判断写成代码。** 「这个岗要 50 人管理经验而候选人带 5 人」是判断，
  归 skill；「按薪资上限降序排」是规则，归 CLI。
  打分只负责**分诊**（把几百条砍到几十条），不负责下结论。
- **不要把确定性交给模型。** 去重、薪资解析、打分排序这类有唯一正确答案的事，
  必须是代码，不能让 Claude 每次现算——现算的结果不可比。
- **薪资只有一种口径：税前。** JD 标税前，配置里也一律填税前，不做税后换算——
  到手金额取决于社保基数、公积金比例、年终奖计税方式，算出来是假精确。
- **不承担市场分析，`src/` 里不许有任何固定的分析逻辑。** 见下面单独一节。

## 不承担市场分析

**「这个市场在招什么、要什么技能、我该看哪个方向」不是这个仓库的功能。**
曾经有过（`job report` + `core/analysis/`：四条写死的赛道、一份技能词典、
几百行职位名分类正则），已经整体删除。删掉的理由是它违反了上面第一条推论：

- 赛道 `("AI", "Web3", "安全", "后端")` 写死在 `src/tracks.py`，
  而且是 `Literal` 类型——做前端或数据的人**连搜索关键词都配不出来**，
  不是「报告不合口味」，是整条采集链路走不通。
- 技能词典、职位名正则、报告里「Web3 样本不足，用后端作对照组」这类文案，
  编码的全是某一个人某一次采集的判断。

分析这件事**太因人而异**：同一批 JD，做算法的人想看框架分布，做管理的人想看
汇报线与团队规模，换城市的人想看地域薪资差。任何一种固定切法都只对写它的人有用。
所以这一层交给 skill（读 JD 现场分析）或用户自己的脚本（`scripts/` 里的一次性工具），
仓库只负责把**事实**准备好。

具体边界：

| 是事实，留在仓库 | 是分析，不在仓库 |
| --- | --- |
| 按 JD 正文去重、保留标价最高的那条 | 「这条属于哪个赛道」 |
| 薪资文案 → 年薪区间（万元，税前） | 「这个赛道薪资中位数多少」 |
| 库存计数（多少职位、多少 JD、投了多少） | 「哪个方向在涨」 |
| 按 `match.toml` 信号表打分排序（信号表是**用户的**配置） | 「JD 里提到哪些技能、占比多少」 |

判据很简单：**结论会不会因为换个人就该重写？** 会 → 不进 `src/`。
（打分排序看似是分析，但它读的是用户自己写的 `match.toml`，
代码里只有「按正则命中加权重、按分数排序」这一条通用规则，没有任何取向。）

顺带一条：`salary_summary()` 这类统计**不许写死门槛**。「多少算达标」由调用方
从 profile 传进来（`[match].salary_floor_wan`），没配就不报达标比例——
不要假装有个客观的达标线。

## 为什么是 CLI + skill，不是 SDK

因为最贵的部分是**积累**。求职是低频行为（几个月一次），如果每次分析都要现写脚本，
脚本用完就丢，第二次跑得到的是一份不可比的新结论，等于没有系统。
CLI 把稳定的骨架固化下来，skill 把「怎么判断」的经验固化下来，
`config/` 把「这个人是谁」固化下来——三样都能跨会话复用，才叫系统。

判断新需求时的反问：**这件事下次还要做吗？做的时候希望结果和这次可比吗？**
两个都是「是」→ 进 CLI 或 skill，不要写一次性脚本。

## 两条执行路线

| 路线 | 入口 | 适用 |
| --- | --- | --- |
| skill + Claude Code | `job …` CLI + `.claude/skills/` | 交互式：深聊、改口径、边看边判断 |
| LangGraph 独立执行 | `job agent`（`src/job_agent/agent/`，装 `--extra agent`） | 无人值守：一条命令跑完 采集→分诊→审读→投递计划，投递前 interrupt 等人确认 |

**入口只有 `job` 一个**（曾经还有个独立的 `job-agent` 脚本，已并成 `job agent`）。
入口合并不等于代码合并——下面这条铁律照旧。

铁律，`tests/test_boundaries.py` 会强制执行：

- **两条路线代码互不依赖。** `cli/`+`web/` 与 `agent/` 谁也不 import 谁；
  可复用的逻辑一律下沉到共享内核（`core/`、`config/`、`context.py`）。
  **唯一的豁免是 `cli/commands/agent_cmd.py`**：`job agent` 这个入口总得有人把
  两边接起来。它只许 import `agent/runner.py` 一个模块，只做「把命令行选项翻成
  `AgentRunOptions` 再交出去」，一行流程逻辑都不写。豁免按**文件名 + 被 import
  的模块名**双重钉死，另有一条行数上限——防止它慢慢长成第二份 agent 实现。
  agent 那边仍然是单向的：`agent/` 永远不许 import `cli/` / `web/`。
- **agent 路线里 LLM 只出现在判断节点**（`agent/nodes.py` 的 review：读 JD 比
  硬门槛、写投递口径）。采集、分诊、排序、计划渲染全部复用内核或纯函数——
  两条路线跑同一份数据得到同一个 shortlist。
- **prompt 只写方法论**（`agent/prompts.py`）。个人取向仍然全部来自 `config/`，
  「换用户只改 config」对两条路线同时成立。
- **审读用哪家模型是配置，不是代码。** `[agent.providers.*]` 一张表一个接入点
  （Claude / ChatGPT / DeepSeek / Kimi…），`[agent].provider` 指哪个用哪个。
  客户端只有两类：`api = "anthropic"`（Claude 原生协议）与 `api = "openai"`
  （OpenAI 协议——DeepSeek、Kimi、通义、GLM、本地 vLLM 都兼容，区别只是
  `base_url`）。加一家新模型是抄一段配置，不许在 `src/` 里加 provider 分支。
- **结构化输出方式也是配置**（`structured_output`）。审读裁决必须符合
  `JDVerdict` 的 schema，而 Anthropic 走 tool calling、OpenAI 官方端点走 strict
  json_schema、兼容端点常常只吃 `function_calling` 或 `json_mode`——支持度随版本
  变，所以绝不按 provider 名在代码里硬猜。`json_mode` 下 langchain 不发 schema，
  由 `prompts.review_system_message()` 把 schema 附进 prompt。
- **换了模型，产出要能看出来。** 模型标识（`provider / model`）进 `AgentState`
  并写进投递计划头部——裁决口径随模型变，事后回看得能分清「优先级变了」是
  JD 变了还是换了模型。
- agent 路线的模型 API key 与 LangSmith key（可选的运行追踪）跟猎聘 token
  同规矩：都住 `config/config.toml`（`[agent.providers.*]` / `[agent.langsmith]`
  / `[liepin]`）。

## profile：一个人 / 一种求职场景

同一台机器上要能同时跑「AI 应用工程」和「Web3 安全」两条线，或者帮另一个人跑一遍。
所以运行按 **profile** 隔离：**一个 profile 是一个自包含的目录**，
输入、配置、产物、数据库全在里面，`profiles/a` 与 `profiles/b` 互不可见。

```
config/
  config.toml          # 全局：猎聘账号密钥、限速、模型接入点、Web、日志（不进版本库）
  config.example.toml  # 全局模板
  templates/           # 新建 profile 的模板，整份 copytree 过去
profiles/              # 整个目录不进版本库
  default/
    profile.toml       # 搜索条件与关键词、match 门槛
    resume.md  preferences.md  match.toml
    data/              # jobs.db、shortlist.md、agent-plan.md
  web3/
    ...
```

**配置分两个文件，段名完全不重叠**：

| 文件 | 段 | 一句话 |
| --- | --- | --- |
| `config/config.toml` | `[profiles]`、`[liepin]`（含 `[liepin.accounts.*]`）、`[detail]`、`[agent]`（含 `.providers.*` / `.langsmith`）、`[web]`、`[logging]` | 管**怎么连**，跟人无关 |
| `profiles/<名>/profile.toml` | `[profile]`、`[search]`、`[storage]`、`[match]` | 管**找什么**，随人而变 |

不重叠是刻意的，也是硬约束（`tests/test_boundaries.py` 会强制）：同一个段要是能出现在
两个文件里，下场一定是「改了一个忘了另一个」。放错文件时 `extra="forbid"` 会当场报错，
loader 再按段名告诉你它该在哪个文件里。段不重叠还保证了环境变量覆盖没有歧义——
`JOB_AGENT_<段>__<字段>` 只可能落到其中一边。

配套的规矩：

- **密钥仍然只有全局一处落盘。** 猎聘 token 住 `[liepin.accounts.<名>]`，
  profile 用 `[profile].account` 指一个——照搬 `[agent.providers.*]` + `[agent].provider`
  的写法：加一个账号是抄一段配置，不是改代码。几个人的 token 长期并存，换人不用重贴。
- **profile 侧的相对路径按 profile 目录解析**，`[web]` / `[logging]` 的按项目根。
  唯一的例外要记住：`[agent].checkpoint` 与 `plan_output` 写在全局文件里，
  但按 **profile 目录**解析——它们是每次运行的产物，必须跟着 profile 走。
- **定位顺序**：`--profile` → `JOB_AGENT_PROFILE_NAME` → `[profiles].default`
  → 只有一个 profile 时就是它 → 报错列出候选。有两个及以上又没说用哪个时**绝不猜**，
  猜错就是往别人的库里写数据。（环境变量刻意不叫 `JOB_AGENT_PROFILE`：
  那个名字会被 pydantic-settings 当成给 `[profile]` 整段赋 JSON。）
- **代码里不出现任何 profile 名字，也不拼 `data/jobs.db` 这类路径**——
  一律问 `settings`。skill 与外部脚本用 `job config path --json`。
- **profile 内部不要再按方向分层。** `[search].keywords` 是扁平数组，
  不是「按赛道分组的关键词表」——想同时跑两条线就开两个 profile。
  曾经有过 `[[search.groups]]`（带 `track` 标签与 `enabled` 开关），
  它存在的真正理由是给分类兜底供数；分类删掉之后它就只是把 profile
  这一层重复了一遍，已一并删除。同一个概念不要在两个粒度上各实现一次。

```bash
job profile list          # 有哪些 profile、哪个是默认、各自多少条数据
job profile new web3      # 从 config/templates/ 拷一份出来
job profile use web3      # 设为默认
job -p web3 search        # 任何命令都能 -p 指定
```

删一个 profile 就是删它的文件夹——刻意不提供 `job profile rm`：
那一下会连着简历和几百条采集记录一起没，交给用户自己动手更诚实。

## 端到端的流程

```
job profile new <名字> → /job-init          # 一次性：建 profile、填简历与关键词
job search → job score → job score --shortlist → /job-match → job apply
          ↘ job web （翻 JD、看库存、点投递）

job [-p <名字>] agent [--collect] [--apply]   # 同一条流程的无人值守版，
                                              # 与 CLI 共享同一个 profile 目录
```

上面每条命令都接 `-p <名字>`；不带就是默认 profile。

`job search` 与 `job score` 是**确定性**的（可重跑、两次结果一样），`/job-match` 那一步是**判断**
（读 JD 比硬门槛、排优先级、写投递口径）。这条分界线就是上面那张表的落地。

对应的配置：

| 文件 | 管什么 | 谁生成 |
| --- | --- | --- |
| `config/config.toml` | 猎聘账号密钥、限速、模型接入点、Web、日志 | `job config init` + `/job-init` |
| `profiles/<名>/profile.toml` | 搜索条件、搜索关键词、`[match]` 路径与薪资门槛 | `job profile new` + `/job-init` |
| `profiles/<名>/resume.md` | 简历（`job resume import` 抽文本，skill 整理） | `/job-init` |
| `profiles/<名>/preferences.md` | 硬约束、薪资口径与底线、面试口径 | `/job-init` |
| `profiles/<名>/match.toml` | **匹配信号表**——正负信号 + 权重 | `/job-init` |

`match.toml` 是「换用户只改配置」这条承诺的关键：
它编码的是个人取向（对做应用工程的人「预训练」是 −12，对做算法的人是 +12），
所以绝不能进 `src/`，而且每个 profile 各一份。里面的正则**一律用 TOML
字面量字符串（单引号）**——
双引号里 `\b` 是「退格符」转义，会静默变成匹配不上任何东西的正则
（`load_rules` 会拦下来，见 `core/matching/rules.py` 的 `_check_pattern`）。

## 还没做的

- 投递之后的事：面试进度、offer 对比、复盘，目前都在系统外
- `job score` 的信号是关键词命中，读不出「JD 说要 50 人管理经验」这类语义门槛
  ——这是刻意的，那部分归 `/job-match` skill

## 硬规则

- **配置一律走 pydantic-settings，对象一律 pydantic model，禁止裸 dict。**
  配置的分层（环境变量 > `config/config.toml`）由 pydantic-settings 完成，
  不自写解析逻辑（`Settings` 见 `config/models.py`）。
  跨函数、跨层传递的结构化数据必须定义 pydantic model——裸 dict 没有 schema，
  拼错字段静默漏过，是配置系统之外最容易埋的坑。仅有的豁免：
  ① 框架的调用契约——LangGraph 节点返回的状态更新 mapping、
  SQLAlchemy `insert().values()` 收的列 mapping；
  ② 解析外部原始数据（HTTP JSON、TOML、HTML 里的 ld+json）时那一层还没有 schema 的输入。
- **禁止 `@dataclass` 与 `NamedTuple`，一律 pydantic `BaseModel`。**
  两套结构体写法并存，看代码的人每次都要先分辨「这个能不能校验、怎么序列化」。
  统一到 pydantic 之后，校验、`model_dump`、FastAPI 响应模型是同一套机制。
  持有连接、线程原语这类非 pydantic 对象时用
  `model_config = ConfigDict(arbitrary_types_allowed=True)`，不要退回 dataclass。
  `tests/test_boundaries.py` 会扫描并强制这条。
- **ORM 记录转行模型只用 `model_validate`，不写 `to_row()` / `_text()` 这类手工转换。**
  行模型开 `from_attributes=True`，仓储里直接 `JobRow.model_validate(record)`；
  手抄一遍字段等于把字段表写两份，加列时必然漏改一处。
  同理，字段类型就写真实类型（`datetime` 就是 `datetime`），
  格式化是**展示层**的事，不要在模型里预先转成字符串。
- **不做向后兼容——数据库与接口都不做。**
  库结构变了就 `job reset` 删库重建（不写迁移、不补列、不回填、不容忍 NULL 老列）；
  接口字段改了就同步改前端，不留兼容分支。
  这是个单人使用的求职工具，数据随时可以重新采集，
  为「万一有老库 / 老客户端」写的兼容代码只会一直留在仓库里没人敢删。
- **配置只有两个文件，段名不重叠：全局 `config/config.toml`（密钥在这）+ 当前
  profile 的 `profile.toml`。** 没有 `.env`，没有第三处落盘。分界见上面的
  profile 一节——「改了一个忘了另一个」是**重叠**的段造成的，不重叠的两个文件不会。
  它们都不进版本库（`.gitignore` 已配），所以密钥直接填在里面是安全的。
  密钥字段一律用 `Secret`（= `SecretStr`，见 `config/models.py`）：
  序列化时自动变 `**********`，`job config show --json` 与 Web 的 `/api/config`
  天然不漏——**防泄漏靠类型，不靠记得在某处补脱敏**。加新密钥就加个 `Secret` 字段，
  别再写 `redacted()` 那类需要逐个维护的方法。取明文只在真正要用的那一处
  （`require_token()` 构造请求头、`require_api_key()` 给 SDK）。
  密钥不回显到终端，不写进提交；不想落盘就用 `JOB_AGENT_<节>__<字段>` 环境变量覆盖。
- **不替用户编造简历事实或求职偏好。** 信息缺失就留 `<待补>` 并说明缺什么。
- **`job apply` 是投递，不可撤销。** 除用户明确要求外不要跑。
- **`config/config.toml` 与整个 `profiles/` 不进版本库**（`.gitignore` 已配）；
  `config/config.example.toml` 与 `config/templates/` 进。
- **默认直接往 `main` 提交并推送，不建分支、不开 PR。** 除非用户明确要求走分支或 PR。
  这是个单人仓库，没有代码评审环节，分支只会多两次切换、留一堆没人合的残枝。
- 取数口径上的坑（薪资区间重叠过滤、JD 正文去重、接口限速实测值）见 README 的
  「取数口径」与「接口限速」两节，改相关代码前先读。

## 开发

```bash
uv sync --extra dev
make lint          # ruff + mypy
make test          # pytest
uv run job --help
```
