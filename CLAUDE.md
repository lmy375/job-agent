# CLAUDE.md

## 产品核心定位：这是一个求职系统

不是爬虫，不是数据分析工具库。目标是端到端支撑一个人完成一次求职：
从「我是谁、我想要什么」开始，到「该投哪几个岗、为什么、怎么谈」结束。

**每次决定要不要加一个功能、加在哪，先用下面这张表对照。**

| 环节性质 | 归属 | 判据 |
| --- | --- | --- |
| 结论必须可重跑、可测试、两次一样 | **CLI**（`src/job_agent/`） | 采集、限流退避、去重、JD 解析、薪资换算、规则打分与落库、排序 |
| 需要读懂文字，但每条独立、结果要**存下来复用** | **CLI 里的判断层** | `job llm-score`：读 JD 比硬门槛、给两个维度打分并落库 |
| 需要读懂数据、边看边改配置 | **Skill**（`.claude/skills/`） | `/job-init` 访谈生成 profile；`/job-align` 对照 LLM 分校准信号表 |
| 随人而变 | **Profile**（`profiles/<名字>/`） | 简历、求职偏好、搜索关键词、匹配信号表、打分提示词 |

第二行是后加的一档，边界要说清楚：**LLM 打分进代码，不是因为它确定性
（它不是），而是因为它「一条一判、结果要存」。** 判断本身交给模型，但「打哪些、
并发多少、已经打过的跳不跳、结果存哪、什么时候算过期」全是确定性的编排，
每一条都有唯一正确答案。而 `/job-align` 那种「这条信号为什么乱命中、砍哪个词、
权重调到几」要同时看全部统计、还要跟人来回改配置，存不下来，所以留在 skill——
但它读的统计（`job align`）又是确定性的，进 CLI。同一件事按这条线切成两半。

推论，违反了就是设计错误：

- **换一个用户，只应该换一个 profile，不该改代码。** 任何「AI Agent 是好岗位」
  这类个人取向，一旦出现在 `src/` 里就是 bug——它属于配置。
- **不要把判断写成代码。** 「这个岗要 50 人管理经验而候选人带 5 人」是判断，
  不许写成正则或阈值；它要么交给 skill，要么**交给模型**（`job llm-score`），
  但两种情况下代码本身都不含任何取向。「按薪资上限降序排」是规则，归 CLI。
  关键词打分只负责**分诊**（把几百条砍到几十条），不负责下结论。
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
| 按 `[score]` 信号表打分排序（信号表是**用户的**配置） | 「JD 里提到哪些技能、占比多少」 |

判据很简单：**结论会不会因为换个人就该重写？** 会 → 不进 `src/`。
（打分排序看似是分析，但它读的是用户自己写的 `[score]` 信号表，
代码里只有「按正则命中加权重、按分数排序」这一条通用规则，没有任何取向。）

顺带一条：`salary_summary()` 这类统计**不许写死门槛**。「多少算达标」由调用方
从 profile 传进来（`[score].salary_floor_wan`），没配就不报达标比例——
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
| LangGraph 独立执行 | `job agent`（`src/job_agent/agent/`） | 无人值守：一条命令跑完 采集→分诊→审读→投递计划，投递前 interrupt 等人确认 |

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
- **模型客户端住共享内核**（`core/llm/`），不住任何一条路线里。现在调模型的地方
  有两处：agent 的审读节点，和 CLI/Web 的 `job llm-score`。边界规则不许 `cli/`
  `web/` import `agent/`，所以客户端只能在 `core/`——照「可复用的一律下沉」办。
  它因此**不收 `Settings`**，只收一个 `ModelProvider`：哪个段选中了哪个接入点，
  是调用方的事，客户端不该知道有 `[agent]` 还是 `[llm_score]` 这回事。
- **prompt 只写方法论**（`agent/prompts.py`、`core/llm/prompts.py`）。个人取向
  仍然全部来自 `config/`，「换用户只改 config」对两条路线同时成立。
  LLM 打分的两段方法论还额外允许用户整段替换（profile 里的两个 md），
  但输出要求与 JSON Schema 那一截永远由代码拼——用户改不坏结构化输出。
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
  并写进投递计划头部；LLM 打分则**逐行**存进 `llm_scores`——裁决口径随模型变，
  事后回看得能分清「优先级变了」是 JD 变了还是换了模型。
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
    profile.toml       # 搜索条件与关键词、[score] 打分门槛与信号表
    resume.md  preferences.md
    data/              # jobs.db、shortlist.md、agent-plan.md
  web3/
    ...
```

**配置分两个文件，段名完全不重叠**：

| 文件 | 段 | 一句话 |
| --- | --- | --- |
| `config/config.toml` | `[profiles]`、`[liepin]`（含 `[liepin.accounts.*]`）、`[detail]`、`[agent]`（含 `.providers.*` / `.langsmith`）、`[llm_score]`、`[web]`、`[logging]` | 管**怎么连**，跟人无关 |
| `profiles/<名>/profile.toml` | `[profile]`、`[search]`、`[storage]`、`[score]` | 管**找什么**，随人而变 |

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
- **profile 内部按格式分文件，不按话题分。** 信号表、搜索关键词、门槛都在
  `profile.toml` 的段里；`resume.md` / `preferences.md` 是自由 Markdown。
  分界是**格式**（结构化 TOML vs 自由 Markdown），不是话题——
  加一项结构化配置就加个段，不要为它单开一个文件。
  LLM 打分的两段提示词（`score_appeal.md` / `score_fit.md`）按这条规矩归 Markdown：
  它们是几百字的自由文本，塞进 TOML 多行字符串只会让缩进和转义变成新的坑。
  它们和前两个 md 还有一点不同——**默认不存在**。默认值在 `src/` 里
  （方法论，与人无关），profile 里的文件只是**覆盖**。所以
  `config/templates/` 刻意不铺这两个文件：铺了每个新 profile 一出生就处在
  「覆盖态」，以后改进内置方法论一份也传不下去。
- **Web 端能改全部配置项，但改的仍然是文件。** `job web` 是这个系统的完整入口：
  一条命令起来之后，从填 token、配搜索条件，到调打分口径、改简历与提示词，
  再到投递，全程不必回终端。所以配置页没有「只读的那一半」。
  页面分四块，按**求职流程**排而不是按文件排（一件事常常横跨两个文件，
  按文件分会把它拆到两页去）：

  | 页 | 管什么 | 落在哪 |
  | --- | --- | --- |
  | 职位采集 | 搜什么词、从哪搜、以什么节奏搜 | `[search]` + `[liepin]` + `[detail]` |
  | 职位评分 | 关键词分诊 + LLM 打分的参数 | `[score]` + `[llm_score]` |
  | 提示词 | 简历、求职偏好、两段打分方法论 | profile 目录下的 4 份 md |
  | 高级 | 其余一切（接入点、端口、日志…） | 两个 toml 的全文编辑 |

  前两块是表单（字段有模型校验），「高级」是文本编辑器——与其为模型接入点、
  LangSmith、日志各做一个做完没人点第二次的表单，不如把文件本身交出来。
  段名表由 `config_sections()` **遍历 `GlobalSettings` / `ProfileSettings` 得出**，
  加一个配置段，页面立刻能改它，不必在路由、schema、前端各补一遍。

  保存 = 写回文件再 `reload_settings()`，**不在内存里攒一份改动**：
  生效的永远是文件里那份，CLI、Web、agent 读同一份，「网页上改了但 CLI
  跑的是另一套」从根上不成立。全文编辑**落盘前先 parse + 按模型校验**，
  坏内容一个字节都进不去——下一个读它的可能是明早无人值守跑的 `job agent`。

- **写回一律定点替换，注释是用户唯一的说明书**（`config/writer.py`）。
  判据不是文本而是**模型层的值**：读一遍文件现在解析出来的那份，
  只改真正变了的键。所以原样保存一遍文件**逐字节不变**，
  引号风格、小数点、手工对齐的空格、行尾注释所在的列全都留着。
  三处需要按「身份」对齐，因为它们是数组：
  `[[score.signals]]` 按 `name` 认（`[score]` 段里有上百行注释解释「这条为什么是
  -14」，整段重写一次就全没了），`keywords` 按词认（数组里的注释是**分组说明**，
  被冲到末尾就看不出它说的是哪几个词），子表按表名认（`[liepin.accounts.*]`）。
  真换了关键词顺序才退回整份重排——顺序就是优先级，那时只能重排。
  刻意不引 TOML 写库（那会把全文重排一遍），同 `job profile use` 的做法。
  提示词是整份 md，直接原子替换；**内容为空或与内置默认逐字相同就删文件**——
  存一份空提示词会让模型收到一段没有方法论的 system，存一份和默认一样的
  会让以后改进默认时传不下去。

- **密钥在 Web 上给明文，在别处一律打码。** 服务只监听本机、单人使用，
  「打得开配置页」与「`cat` 得到 `config/config.toml`」是同一份权限，
  打码只会让人没法在页面上填 token。但明文是个**要主动写出来**的动作
  （`model_dump(context={REVEAL_SECRETS: True})`），全仓库只有 `GET /api/config`
  和 `/api/config/sections` 这么做；默认那一侧堵住了所有「顺手序列化」的出口
  ——日志、`job config show --json`、出错时打印整棵配置树，
  那些地方谁也不会记得单独脱敏，所以默认值必须是安全的那个。
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

**这三件事在 Web 顶栏也能做**（点 profile 那颗徽章）。干活的是同一份内核
（`core/profile.py`），CLI 与 Web 各写一遍的下场是「命令行切了、网页上没切」。
Web 上切换有两处和 CLI 不同，都是因为它是个**活着的服务**：

- **切换 = 换掉整个 `AppContext`**，不只是改 `settings`。仓储握的是旧库的
  连接，只换设置不换连接就成了「设置说 A、读写落在 B」。前端随即整页重载——
  所有视图的数据都换了，挨个刷新既容易漏，又会出现「列表已经是新 profile 的、
  抽屉里还开着旧 profile 那条」这种半新半旧的状态。
- **有后台任务在跑就拒绝切换**。任务在提交那一刻就把当时的 `AppContext`
  捕获进了闭包，切换会把它脚下的连接抽走。让人等几十秒，比让一次采集
  写进半个库强。

切换同时写 `[profiles].default`：「切换」该是整个系统切过去，不只是那个页面——
下一条 `job search` 也得落在同一个库里，否则两边看到的不是一回事。

**`job web` 会自建**：缺全局配置就照 `config.example.toml` 生成一份，
一个 profile 都没有就建一个 `default`。管理台是完整入口，新克隆下来第一次跑
不该先被一句「还没有任何 profile」挡在门外。只在「一个都没有」时做——
有两个及以上却没指定用哪个时仍然绝不猜。

删一个 profile 就是删它的文件夹——刻意不提供 `job profile rm`，Web 上也没有：
那一下会连着简历和几百条采集记录一起没，交给用户自己动手更诚实。

## 端到端的流程

```
job profile new <名字> → /job-init          # 一次性：建 profile、填简历与关键词
job search → job score → job llm-score --top 30 → job web 翻 JD、点投递 → job apply
          ↘ job align → /job-align   （有了 LLM 分之后：对照它校准 [score] 信号表）
          ↘ job score -o data/shortlist.md （候选清单骨架，判断部分留白给人填）
          ↘ job web （翻 JD、看库存、点投递、改关键词/打分逻辑/提示词、批量打分）

job [-p <名字>] agent [--collect] [--apply]   # 同一条流程的无人值守版，
                                              # 与 CLI 共享同一个 profile 目录
```

上面每条命令都接 `-p <名字>`；不带就是默认 profile。

`job search` 与 `job score` 是**确定性**的（可重跑、两次结果一样），`job llm-score` 是**判断**
（读 JD 比硬门槛、判方向），但编排是确定性的。这条分界线就是上面那张表的落地。

### 校准信号表（`job align` + `/job-align`）：统计进代码，判断留给 skill

两套分数都在库里时，「关键词分诊把模型认可的岗位送进视野了没有」是个有唯一答案的
问题：秩相关、窗口召回、每条信号命中的岗位模型平均给几分、每条信号按顶层 `|` 拆开
哪个子模式在乱命中、哪些模型认可的岗位被漏在窗口外、候选正则在标题 / 正文命中的
岗位均分。这些全在 `job align` 里，**不写库**（挑窗口用 `score_all` 内存现算），
`--json` 给脚本。「认可」「明确不看」的分数线是参数，默认对齐内置提示词的锚点——
不是代码替用户定的取向。

「这条信号为什么乱命中、砍哪个词、权重调到几、要不要加一条头衔信号」是判断，
归 `/job-align` skill：读统计、看命中快照、改 profile.toml 的 `[score]`、复测、
把偏好里没写全的地方（模型因此判错的那类岗位）交还给用户。skill 对任何 profile
都成立——它不含任何方向的取向，取向只从这个 profile 的 `preferences.md` 与
`[score]` 注释里读。

`job align` 里**不许**出现「Δ 小于多少就该删」这类建议：那已经是判断。它只报数字。

**`job score` 是「刷新」不是「查询」**：每次都按 `[score]` 现在的样子把全库重算一遍，
整表重写 `job_scores`。分数与全库排名落库是为了让 Web 端能直接排序，
代价是它会**过期**——所以：

- 落库的是**全量、未过滤**的分数与全库排名。`--floor` / `-n` / 去重都是
  「这次看什么」，不许影响写进库里的名次；否则带一次 `--floor` 就会把全库排名弄脏。
- **整表重写，没有按条更新。** `rank` 是全库排名，改一条的权重会牵动别人的名次，
  半张表新半张表旧的排名是错的，而且错得看不出来。
- **过期必须能看出来。** 每行存一份 `[score]` 配置的指纹（`ScoreConfig.fingerprint`，
  只算真正参与打分的字段，不含 `salary_floor_wan`）；`job stats` 与职位页顶部的库存卡
  拿它和当前配置一比，改过规则或采了新数据都会提示重新打分
  （命令行跑 `job score`，或点页面上的「重新打分」）。
  存了分数又不报过期，等于让人把旧结论当成现在的——比不存更糟。

`job score` 在 Web 端有个等价入口：职位列表 / 配置页上的「重新打分」按钮
（`POST /api/scores/refresh`）。它走**同一个** `core.matching.refresh`，
所以两个入口算出来的分数与全库排名必然一样——差一点点就等于两套口径。
它刻意不进后台任务队列：队列存在的理由（猎聘限流按 token 记账、串行才安全）
对打分不成立，打分不发请求、几千条一两秒。

### LLM 打分（`job llm-score`）：判断进代码，但编排仍然是确定性的

关键词打分读不出「JD 说要 50 人管理经验」，所以有第二层：让模型读 JD 与简历，
打**两个维度**的分，各 1-10 分并附一条或多条依据。落 `llm_scores` 表。

**两个维度并列，绝不合成总分**（`appeal` 岗位吸引力 / `fit` 胜任匹配度）。
`appeal` 的内置方法论以 `preferences.md` 里的求职期望为**决定性**标准：
先按方向定分数区间，薪资与平台只在区间内移动分数、抬不出上限。
这仍然是方法论而不是取向——「哪些方向算优先」全部来自用户的 `preferences.md`，
prompt 里一个具体方向都没有。
它们回答的是两个不相干的问题：一个是「这份工作值不值」，一个是「你够不够格」。
合成之后「够不着的好岗」和「够得着的烂岗」算出来一样高，而这两种情况该做的事
完全相反。真要合成，权重多少也是取向，写进 `src/` 就是 bug。

和 `job score` 的分工是**刷新语义**上的，两张表不能合并：

| | `job_scores` | `llm_scores` |
| --- | --- | --- |
| 写法 | 整表重写 | 按条 upsert |
| 存排名 | 存（`rank` 是全库名次） | **不存**——表天然残缺，名次是「全量重算」才有的概念 |
| 默认范围 | 全库 | **必须显式指定**，没有「不传就全打」 |
| 过期判据 | `[score]` 指纹 | 提示词指纹 + `provider` + `model` |

几条不许改的：

- **「必须显式指定」在每个入口都成立。** CLI 不给 jobId / `--top` / `--all` 就
  退出 2；`POST /api/tasks` 的 `llm_score` 没有 `job_ids` 就 400。按条计费的事，
  「忘了带参数」不该能触发。
- **口径没变的默认跳过**（同 provider + 同 model + 同提示词指纹），`--force` 才重打。
  换了任意一样就不跳过——旧分数和新的不可比。
- **单条失败不落库、也不拖垮整批**；只有 `JobAgentError`（缺 key、装错包这类
  整批都跑不动的）才往上抛。表里有行就等于有一份有效分数，不必再判 status 列。
- **打分不许顺手重写 `job_scores`。** 挑「前 N 条」用的是 `score_all()`（内存里
  现算、不落库），库里的名次什么时候变由 `job score` 说了算。
- **`job stats` / 职位页库存卡不把「还没打的」报成待办。** 按条计费，覆盖不全是常态，
  天天喊「还差 3000 条」只会让人学会忽略它。要报的是 `stale`：库里混着别的模型
  或旧提示词判出来的分数，那些和现在这批没法比。
- **Web 端它进后台任务队列，而 `job score` 不进。** 判据是「会不会发请求」，
  不是「慢不慢」。

对应的配置：

| 文件 | 管什么 | 谁生成 |
| --- | --- | --- |
| `config/config.toml` | 猎聘账号密钥、限速、模型接入点、Web、日志 | `job config init` + `/job-init` |
| `profiles/<名>/profile.toml` | 搜索条件、搜索关键词、`[score]` 打分门槛与匹配信号表 | `job profile new` + `/job-init` |
| `profiles/<名>/resume.md` | 简历（`job resume import` 抽文本，skill 整理） | `/job-init` |
| `profiles/<名>/preferences.md` | 硬约束、薪资口径与底线、面试口径 | `/job-init` |
| `profiles/<名>/score_appeal.md`、`score_fit.md` | LLM 打分两个维度的方法论**覆盖**（可选，不存在就用 `src/` 里的内置默认） | Web 配置页 / 手写 |

`profile.toml` 的 `[score]` 段是「换用户只改配置」这条承诺的关键：
它编码的是个人取向（对做应用工程的人「预训练」是 −12，对做算法的人是 +12），
所以绝不能进 `src/`，而且每个 profile 各一份。里面的正则**一律用 TOML
字面量字符串（单引号）**——
双引号里 `\b` 是「退格符」转义，会静默变成匹配不上任何东西的正则
（`config/models.py` 的 `_check_pattern` 会拦下来）。

它曾经是独立的 `profiles/<名>/match.toml`，已经合进 `profile.toml`。
拆成两个文件唯一的效果是多一处要同步、多一条要解析的路径，
而「换个人整份重写」的粒度本来就是**整个 profile**，不是单个文件。
`[score]` 的产物路径也一并删了（原 `shortlist_output`）——写哪儿是每次调用的事，
由 `job score -o` 说，不该固化成配置。

## 还没做的

- 投递之后的事：面试进度、offer 对比、复盘，目前都在系统外
- `job score` 的信号是关键词命中，读不出「JD 说要 50 人管理经验」这类语义门槛
  ——这是刻意的，那部分归 `job llm-score`（每条独立、结果落库）。
  信号表读不出的东西有多少，`job align` 会量出来
- 「这八条里先投哪三个」这种跨岗位权衡目前没有 skill 承担：曾经有 `/job-match`，
  已删——它做的事（读 JD 比硬门槛、写投递口径）大半被 `job llm-score` 落库了，
  剩下的排优先级在 `job web` 里按两个分数翻着看就够

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
- **Web 端不分页。** 本地单人用、职位数有限（一次采集几百到几千条），
  `/api/jobs` 一次全给，排序在浏览器里做（点表头即时重排）。`limit` 只是
  「别让一次响应大到离谱」的兜底，真截断了响应里 `total > len(jobs)`，
  前端必须把这件事显示出来——静默截断会让人以为看到的就是全部。
- **前端一律 TypeScript，包管理器一律 pnpm。** `frontend/` 下不许出现 `.js` /
  `.jsx`（构建产物 `dist/` 除外）——组件是 `.tsx`，其余是 `.ts`，连
  `vite.config.ts` 也是。装包只用 pnpm（`pnpm-lock.yaml` 进版本库，
  没有 `package-lock.json`）；`job web` 与 Makefile 调的都是 `pnpm`。
  接口字段抄在 `frontend/src/types.ts` 里，一一对应 `web/schemas.py` 与
  `core/storage/rows.py` 的 pydantic 模型：后端可空（`| None`）的字段在那边
  就是 `| null`，`tsc` 会逼着判一次。这是「接口不做向后兼容」的配套——
  字段改了必须有人在编译期喊，靠人肉搜前端引用一定会漏。
  `pnpm build` 里带 `tsc`：类型不过就不出产物。
- **筛选条件是取数，不是分析。** 「只看 HR 岗位 / 只看猎头岗位」这种按库里字段
  （`jobType`）过滤的开关随便加——它是事实，换个人也一样。
  「这条属于哪个赛道」那种要先判断再分组的，仍然不进 `src/`（见上面那一节）。
- **不做向后兼容——数据库与接口都不做。**
  库结构变了就 `job db reset` 删库重建（不写迁移、不补列、不回填、不容忍 NULL 老列）；
  接口字段改了就同步改前端，不留兼容分支。
  这是个单人使用的求职工具，数据随时可以重新采集，
  为「万一有老库 / 老客户端」写的兼容代码只会一直留在仓库里没人敢删。
- **配置只有两个文件，段名不重叠：全局 `config/config.toml`（密钥在这）+ 当前
  profile 的 `profile.toml`。** 没有 `.env`，没有第三处落盘。分界见上面的
  profile 一节——「改了一个忘了另一个」是**重叠**的段造成的，不重叠的两个文件不会。
  它们都不进版本库（`.gitignore` 已配），所以密钥直接填在里面是安全的。
  密钥字段一律用 `Secret`（= `SecretStr`，见 `config/models.py`）：
  序列化成 JSON 时**默认**变 `**********`，只有显式传 `context={REVEAL_SECRETS: True}`
  才吐明文（只有 Web 配置页这么做，理由见上面 profile 一节）——
  **防泄漏靠类型，不靠记得在某处补脱敏**。加新密钥就加个 `Secret` 字段，
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
make install       # uv sync --extra dev + pnpm install（前端）
make lint          # ruff + mypy
make typecheck-web # 前端 tsc
make test          # pytest
make check         # 提交前跑这个：以上全部
uv run job --help
```
