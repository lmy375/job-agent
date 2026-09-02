# job-agent

> **产品核心定位：这是一个求职系统。**
>
> 不是爬虫，也不是数据分析工具库。它的目标是端到端支撑一个人完成一次求职：
> 从「我是谁、我想要什么」开始，到「该投哪几个岗、为什么、怎么谈」结束。
>
> 由此确定分工——**CLI 负责确定性，skill 负责判断**：
>
> - **CLI**（本仓库代码）承担一切可重跑、可测试、结果可比的环节：
>   采集、限流退避、去重、JD 解析、薪资换算、按规则打分排序。
>   同样的库跑两次，结论必须一样。
> - **Skill**（`.claude/skills/`）承担需要语言理解、代码穷举不出来的环节：
>   读 JD 判断硬门槛冲突、比对简历措辞与市场词汇、排投递优先级、准备面试口径。
> - **`config/`** 承担一切因人而异的东西：简历、求职偏好、搜索关键词、
>   匹配信号表。**换一个用户，只应该换 `config/`，不该改代码。**
>
> 判断一个新功能该不该加、加在哪，就用这三条对照：
> 结论必须稳定复现的 → CLI；需要读懂文字才能下判断的 → skill；随人而变的 → profile。

猎聘职位工具链：批量搜索 → 抓取详情页 JD → 按你自己的信号表打分分诊 → 投递，
数据全部落在本地 SQLite。提供 **CLI** 与 **Web 管理台**两套入口。

**它不做市场分析。** 「这个方向在招什么、要什么技能」不是这个仓库的功能——
那件事太因人而异，固定的切法只对写它的人有用（详见 CLAUDE.md「不承担市场分析」）。
仓库只负责把事实准备好：去重、薪资换算、按你的 `match.toml` 排序。

运行按 **profile** 隔离：**一个 profile = 一个人，或者一种求职场景**
（「AI 应用工程」和「Web3 安全」可以是两个 profile）。每个 profile 是一个自包含的目录，
简历、关键词、信号表、数据库、产物全在里面，`profiles/a` 与 `profiles/b` 互不可见；
跟人无关的东西（猎聘账号密钥、模型接入点、限速、Web 端口）仍然全局共享一份。

```bash
uv sync --extra dev          # 安装依赖
uv run job config init       # 生成全局配置 config/config.toml（密钥填这里）
uv run job profile new me    # 建一个 profile（简历、关键词、数据库都在它自己的目录里）
uv run job search            # 采集职位
uv run job detail            # 抓 JD
uv run job match             # 按信号表给职位打分排序（分诊）
uv run job shortlist         # 生成候选清单骨架
uv run job web               # 打开 Web 管理台
```

有多个 profile 时，每条命令都能用 `-p <名字>` 指定；不带就用默认的那个：

```bash
uv run job profile list      # 有哪些 profile、哪个是默认、各自多少条数据
uv run job profile new web3  # 再开一条线
uv run job -p web3 search    # 只往 web3 这个 profile 的库里写
uv run job profile use web3  # 把它设成默认，之后不用每次带 -p
```

配置怎么填？**在 Claude Code 里跑 `/job-init`**，它会问你需要的信息并写进对应位置
（token、城市与薪资门槛、关键词分组、简历、求职偏好、匹配信号表）。想手填就照
两份配置文件里的注释改，填完 `uv run job config validate` 自检。

采完数据之后**跑 `/job-match`**：它读 JD、比硬门槛、排投递优先级、写投递口径，
把 `job shortlist` 留白的判断部分填掉。完整流程：

```
job profile new <名字> → /job-init          # 一次性：建 profile、填简历与关键词
job search → job detail → job match → job shortlist → /job-match → job apply
                       ↘ job web （翻 JD、看库存、点投递）
```

## 目录结构

```
config/                跟人无关的那一半
  config.example.toml  全局配置模板（进版本库）
  config.toml          全局配置：猎聘账号密钥、模型接入点、限速、Web、日志（不进版本库）
  templates/           新建 profile 的模板，整份拷成一个新 profile（进版本库）
profiles/              随人而变的那一半，整个目录不进版本库
  <名字>/               一个 profile = 一个人 / 一种求职场景，自包含
    profile.toml       搜索条件、关键词分组、匹配门槛
    resume.md          你的简历
    preferences.md     求职偏好（base 地 / 期望薪资 / 不看的岗位 / 面试口径）
    match.toml         匹配信号表：正负信号 + 权重（决定 job match 的排序）
    data/              jobs.db、shortlist.md、agent-plan.md
src/job_agent/
  config/              配置加载与校验（TOML → 校验过的 Settings，密钥是 SecretStr）
  core/                核心能力，不依赖 CLI / Web
    liepin/            猎聘接口客户端（限速、错误码翻译、请求模型）
    storage/           SQLite：ORM 模型、仓储、轻量迁移
    services/          用例编排：search / detail / apply（带进度回调与取消）
    matching/          按信号表打分排序 + 候选清单骨架（只分诊，不下结论）
    resume/            PDF / DOCX / TXT 简历 → 纯文本
    dataset.py         jobs × job_details → 打分用的行集合（去重、薪资换算）
    jd_parser.py       详情页 → 结构化 JD（纯函数）
    salary.py          薪资文本 → 年薪区间（万元，税前）
  cli/                 typer 子命令（执行路线一：人或 skill 驱动）
  web/                 FastAPI 管理后端 + 后台任务
  agent/               LangGraph 独立执行（执行路线二，装 --extra agent 才可用）
frontend/              React（Vite）管理台，构建到 frontend/dist 由后端托管
scripts/               一次性脚本（导出、关键词覆盖率核对）
tests/                 pytest（不碰真实库、不发网络请求）
  shortlist.md         job shortlist 的产物：候选清单（判断部分留白给 skill 填）
.claude/skills/
  job-init/            `/job-init`：交互式收集信息并填好 config/
  job-match/           `/job-match`：读 JD、比硬门槛、排投递优先级、写投递口径
```

依赖方向单向：`cli` / `web` → `core` → `config`，`agent` → `core` → `config`。
反向依赖一律禁止；两条执行路线（`cli`+`web` 与 `agent`）互不 import，
共享的确定性内核只有 `core/` 与 `config/`（`tests/test_boundaries.py` 强制这条边界）。

## 配置

所有个人化的东西都在 profile 目录里，代码里不硬编码任何个人信息。
配置**只有两个文件，段名完全不重叠**——放错了会当场报错并告诉你该放哪：

| 文件 | 管什么 | 段 |
| --- | --- | --- |
| `config/config.toml` | **怎么连**，跟人无关，全局一份 | `[profiles]`、`[liepin]`、`[detail]`、`[agent]`、`[web]`、`[logging]` |
| `profiles/<名>/profile.toml` | **找什么**，随人而变，一个 profile 一份 | `[profile]`、`[search]`、`[storage]`、`[match]` |

- `config/config.toml`：全部密钥都在这（猎聘 token、模型 API key、LangSmith key）。
  它不进版本库，所以密钥直接填在里面；每一项都有注释，见 `config/config.example.toml`。
  猎聘 token 填在 `[liepin.accounts.<账号名>].user_token`，前往
  <https://www.liepin.com/mcp/auth> 生成。可以同时放几个人的账号，
  profile 用 `[profile].account` 指一个——换人不用来回重贴 token。
- `profiles/<名>/profile.toml`：搜索条件、关键词分组、匹配门槛。
  里面的相对路径都相对于**这个 profile 的目录**，所以两个 profile 的
  `data/jobs.db` 是两个库。
- `profiles/<名>/resume.md`、`preferences.md`：你的简历与求职偏好。程序不解析它们，
  刻意保持自由格式 Markdown——它们是挑岗位、准备面试问答时的输入。
  `/job-init` 会带你写；模板见 `config/templates/`。
- 用哪个 profile：`--profile` → `JOB_AGENT_PROFILE_NAME` → `[profiles].default`
  → 只有一个 profile 时就是它 → 报错列出候选。有两个及以上又没说用哪个时**绝不猜**。
  （环境变量刻意不叫 `JOB_AGENT_PROFILE`：那个名字会被 pydantic-settings
  当成给 `[profile]` 整段赋 JSON 值。）
- 环境变量可覆盖：`JOB_AGENT_CONFIG` / `JOB_AGENT_HOME` 指定全局配置文件与项目根；
  任意配置项可用 `JOB_AGENT_<节>__<字段>` 覆盖（如 `JOB_AGENT_WEB__PORT=19999`、
  `JOB_AGENT_SEARCH__ADDRESS=上海`），**密钥也不例外**
  （`JOB_AGENT_LIEPIN__ACCOUNTS__DEFAULT__USER_TOKEN=…`、
  `JOB_AGENT_AGENT__PROVIDERS__DEEPSEEK__API_KEY=…`），适合不想落盘的场景。
  两个文件的段不重叠，所以一个变量只可能落到其中一边，没有歧义。
  分层由 pydantic-settings 完成：环境变量 > TOML。
- 密钥字段的类型是 `SecretStr`：`job config show --json` 与 Web 的 `/api/config`
  返回的是 `**********`。防泄漏靠类型，而不是靠「记得在某处补一段脱敏逻辑」。

配置项**拼错会直接报错**（`extra="forbid"`），不会被静默忽略——
静默忽略是配置系统最容易埋的坑（把 `salary_floor` 写成 `salaryFloor`，
结果搜出一堆不达标的岗位却毫无提示）。

关键词按数组顺序（= 优先级）搜索。因为按 jobId 去重且先搜高优先级方向，
每条职位记录到的 `searchKeyword` 就是「最先命中它的方向」。
不想再搜某个方向时，把那组设 `enabled = false` 即可（比删掉好：留着能看出
库里存量数据是怎么来的）。`[[search.groups]].track` 只是分组标签，
写「前端」「数据」还是「量子计算」都行——程序不拿它做任何判断。

## 初始化：`/job-init`

`.claude/skills/job-init/` 是一个 Claude Code skill。在仓库里对 Claude 说
`/job-init`（或「帮我初始化 job-agent」），它会先确认用哪个 profile（没有就建一个），
再按 **token → 搜索条件 → 简历 → 求职偏好**四步访谈，把答案写进对应文件，
最后跑 `job config validate` 与 `job search --dry-run` 自检。

几个刻意的设计：token 只写进全局 `config/config.toml`、不回显、不进对话；已有文件先读再改，
不整份重写；简历支持粘贴 / 指向已有文件（PDF 自动转文本）/ 从零访谈三种来源；
问到绩效、婚育这类敏感项会先说明「只存本地、不进版本库」，不答就留空。

## 命令

```bash
job search [-k 关键词]... [--pages N] [--dry-run]
job detail [--limit N] [--retry-failed]
job match [--floor 万] [--top N] [--why] [--json] [--no-dedupe]
job shortlist [-o 输出路径] [--limit N] [--floor 万]
job resume import <文件> [-o 输出路径] [--force]
job apply <jobId>... [--job-kind 1|2] [--yes]
job stats [--tracks]
job web [--host H] [--port P] [--no-browser] [--skip-build]
job profile list|new|use|path
job config init|show|path [--json]|validate
job reset [--yes]
job db info|vacuum
```

全局选项：`--profile/-p` 指定 profile、`--config` 指定全局配置文件、
`--log-level`、`--quiet`、`--version`。

`job config path --json` 打印当前 profile 解析好的全部路径（简历、信号表、数据库…），
skill 与外部脚本靠它定位文件——路径随 profile 变，不该在别处硬编码。

退出码：`2` 配置/鉴权问题、`3` 存储、`5` 接口错误或简历抽取失败、`6` 触发限流。
脚本里可以据此判断「今天别再投了」。

`job apply` 默认会列出待投职位并要求确认（`--yes` 跳过）。投递结果（含「已投递过」
「职位已结束」）都会记进本地 `applications` 表——**猎聘没有查询投递记录的接口**，
这张表是唯一的账本。

## 挑岗位：`job match` / `job shortlist` / `/job-match`

采集解决「有哪些岗」，这三样解决「该投哪几个」。分界线是**确定性 vs 判断**：

```bash
uv run job match --top 30 --why       # 打分排序，--why 展开命中与扣分理由
uv run job match --json               # 给脚本用
uv run job shortlist --limit 12       # 写出 <profile>/data/shortlist.md（判断部分留白）
```

`job match` 的排序来自当前 profile 的 `match.toml` 信号表，**它是配置不是代码**——
编码的是「你想要什么」，换个人应当整份重写：

```toml
[require]                     # 职位名与 JD 都不含这些词 = 连方向都不对，压到末尾
pattern = '\bagent\b|智能体|大模型'
penalty = -20.0

[[signals]]
name = "AI Agent / 智能体"
weight = 10                   # 正数加分，负数即「不想要的方向」
pattern = '\bagent\b|智能体|agentic'

[[signals]]
name = "算法训练岗"
weight = -12                  # 做算法的人把这条改成 +12 就行
pattern = '预训练|后训练|强化学习|模型训练'
```

三个必须知道的口径：

- **正则一律用单引号**（TOML 字面量字符串）。双引号里 `\b` 是 TOML 的「退格符」
  转义，`"\bagent\b"` 会静默变成 `<退格>agent<退格>`——正则编译得过、
  一条也匹配不上、排名看着正常但结论全错。`job config validate` 会拦下来。
- **薪资门槛过滤的是「上限」不是「下限」**。JD 区间的上限才代表「这家最多给到多少」；
  按下限过滤会误杀「50-80k·20薪」这类实际能谈上去的岗位。
- **分数只做分诊，不代表结论。** 它把几百条砍到几十条；
  「这个岗要 50 人管理经验而你带 5 人」这种判断要读 JD，是 `/job-match` 的事。
  第 1 名可能有硬门槛冲突，第 8 名可能才是最该投的。

`job shortlist` 产出的 Markdown 里，每条岗位有三处 `<待 /job-match 填写>`：
**硬门槛核对**、**投不投**、**投递口径**。代码刻意不填——填了模板话术，
人会以为已经分析过了，比留空更糟。

## 无人值守：`job-agent`（LangGraph 路线）

`/job-match` 是交互式的：你和 Claude 一起读 JD、改口径。`job-agent` 是同一条流程的
无人值守版——LangGraph 组的固定管线，一条命令跑完 **分诊 → 逐岗审读 → 投递计划**，
共享同一个数据库、同一份 `config/`：

```bash
uv sync --extra agent                 # 依赖是可选的，不装不影响 job / job web
# config/config.toml 的 [agent.providers.*] 里填 api_key（审读节点要调模型 API）

uv run job-agent                      # 用库内已有数据：分诊 → 审读 → <profile>/data/agent-plan.md
uv run job-agent --collect            # 先采集（search + detail）再走上面的流程
uv run job-agent --apply              # 出完计划后进入投递确认（终端里逐条拍板）
uv run job-agent --thread run-x       # 中断后用同一 thread 从 checkpoint 续跑
uv run job-agent --provider deepseek  # 换模型：用 [agent.providers.deepseek]
```

### 审读用哪家模型

模型是**配置**，不是代码。一张 `[agent.providers.*]` 表就是一个接入点，
`[agent].provider`（或 `--provider`）指哪个用哪个；几家的 key 长期并存，
换模型不用来回粘贴密钥：

```toml
[agent]
provider = "deepseek"

[agent.providers.anthropic]
api = "anthropic"                     # Claude 原生协议
model = "claude-opus-5"
api_key = "sk-ant-…"

[agent.providers.deepseek]
api = "openai"                        # DeepSeek 兼容 OpenAI 协议
model = "deepseek-chat"
api_key = "sk-…"
base_url = "https://api.deepseek.com/v1"
structured_output = "function_calling"
```

客户端只有两类：`api = "anthropic"` 和 `api = "openai"`。ChatGPT、DeepSeek、
Kimi、通义、GLM、OpenRouter、自建网关（LiteLLM、one-api）、本地 vLLM/Ollama
全都兼容 OpenAI 协议，区别只是
`base_url`——加一家新模型是抄一段配置，不用改代码。密钥不想落盘就用
`JOB_AGENT_AGENT__PROVIDERS__<表名大写>__API_KEY` 覆盖。

走 OpenRouter 这类网关时，`model` 填网关的 slug：

```toml
[agent.providers.openrouter]
api = "openai"
model = "z-ai/glm-5.2:free"           # 或 anthropic/claude-sonnet-5、deepseek/deepseek-chat
api_key = "sk-or-v1-…"
base_url = "https://openrouter.ai/api/v1"
structured_output = "function_calling"
```

带 `:free` 后缀的 slug 不花钱，代价是每日调用上限，跑之前用 `--top` 控量。
另有一个特例 `openrouter/free`，它是**免费模型路由器**：每次调用从当前可用的
免费模型里随机挑一个，更省事，但同一批岗位可能由不同模型判、快慢差别很大，
裁决口径不可比——想要可比的结论就填具体 slug。

**唯一要留意的坑是 `structured_output`。** 审读裁决必须是固定 schema 的 JSON
（`JDVerdict`），而各家实现方式不同：官方端点留 `"auto"`，让 langchain 自己选
（Claude 走 tool calling、OpenAI 走 strict json_schema）；兼容端点如果报
「不支持 json_schema / response_format」，依次试 `"function_calling"` 和
`"json_mode"`——`json_mode` 下 langchain 不会把 schema 发出去，由 prompt 带过去。

几条设计约束（和 CLAUDE.md 的表一致）：

- **LLM 只出现在审读节点**（读 JD 比硬门槛、写投递口径，产出固定 schema 的裁决）。
  采集、去重、打分、排序、计划渲染全部是共享内核里的确定性代码——
  `job match` 和 `job-agent` 对同一份数据给出同一个 shortlist。
- **投递前必经 interrupt。** `--apply` 只是打开闸门，真正投哪几个要在终端里
  逐条确认；不传 `--apply` 时流程在写出计划后就结束。
- **换了模型，产出看得出来**：模型标识（`provider / model`）写进投递计划头部，
  也进 checkpoint。裁决口径随模型变，事后回看才分得清「优先级变了」是 JD 变了
  还是换了模型。
- 每一步 checkpoint 到 `<profile>/data/agent-checkpoint.db`，中断续跑、事后回放
  「当时为什么这么排」都靠它。
- **LangSmith 追踪（可选）**：`config/config.toml` 的 `[agent.langsmith]` 下填
  `api_key` 即启用（`project` 决定归到哪个 project，自托管再填 `endpoint`），
  每次运行的全部 LLM 调用按 `thread_id` 归成一条 thread；留空则完全不上报。
  追踪是 langchain-core 内建的，靠环境变量开关，不需要挂 callback handler。

## 导入简历：`job resume import`

```bash
uv run job resume import ~/Downloads/我的简历.pdf     # 打到 stdout
uv run job resume import 简历.docx -o /tmp/resume.txt
```

支持 `.pdf`（pypdf）、`.docx`（直接解 zip 里的 XML，不引 lxml）、`.md` / `.txt`。
`.doc` 不支持，另存为 `.docx` 或导出 PDF。

**它只抽纯文本，不写 profile 里的 `resume.md`**——抽出来的是没有结构的文字，
直接覆盖会把排版和数字弄丢。整理成结构化 Markdown 是 `/job-init` 的工作：
它会保留全部事实与数字、对齐市场词汇、缺信息时留 `<待补>`。
（真要覆盖得加 `--force`，命令会先拦你一次。）

## Web 管理台

`job web` 启动后（默认 <http://127.0.0.1:18000>）提供三个页面：

- **职位**：分页、按关键词/薪资/是否有 JD/是否投递筛选、展开看 JD 全文、一键投递（有二次确认）
- **采集任务**：在页面上发起搜索 / 抓详情，实时看进度与日志，可取消
- **数据概览**：库存计数、薪资水位、当前配置与路径

API 文档在 `/docs`。后台任务**只有一个 worker**：猎聘限流按 token 记账，
并行只会更快被封；SQLite 的写也不适合并发。取消是协作式的——
线程不能安全地被杀，服务会在当前条目结束后停下，已完成的进度都已落库。

配置在 Web 端**只读**：配置是文件，改文件比在网页上改更可靠、可进版本库，
也不会出现「网页上改了但下次 CLI 跑的是另一套」。

前端开发：`cd frontend && npm run dev`（5173 端口，`/api` 自动代理到 18000）。

## 详情页抓取

JD 来自详情页里的 `<script type="application/ld+json">` **JobPosting** 块——
猎聘为 SEO 输出的结构化数据，含完整 JD、行业、经验与学历要求，比解析 DOM 稳定得多。
解析失败时回退到 `data-selector="job-intro-content"`。

限流策略：**串行**请求 + 请求间随机休眠 1.2–2.5s，遇 403/429 退避 5 分钟。
单请求本身耗时 2–4s，天然限速到约 15 次/分钟。累计 2000+ 条实测全程无限流；
失败的基本是已下线职位，记为 `no_jd`。进度直接落库，中断后重跑自动跳过已完成项。

## 取数口径（几个必须知道的坑）

这一节只剩「取数」——赛道分类、技能词典那些**分析**口径已经随
`core/analysis/` 一起删除了（理由见 CLAUDE.md「不承担市场分析」）。

- **猎聘的薪资筛选是「区间重叠」而不是「下限 ≥ 门槛」**，还会漏进明显不达标的条目
  （样本里出现过实习生岗）。所以 `job stats` 会单独报「薪资上限真正 ≥ 门槛」的比例，
  提醒你搜回来的不都是达标岗。门槛取自 profile 的 `[match].salary_floor_wan`，
  **没配就不报这个比例**——不假装存在一条客观的达标线。
- **同一份 JD 常被多家猎头重复挂出**：正文一字不差，但职位名和标价各挂各的
  （实测有一份被挂了 8 次，同一岗位标价能差 2–3 倍）。
  `load_rows()` 默认按 **JD 正文**去重并保留标价最高的那条——
  用「职位名 + 正文」做键会漏掉大部分重复。
- **薪资门槛比的是区间上限，不是下限。** 上限才代表「这家最多能给到多少」，
  按下限过滤会误杀「50-80k·20薪」这类实际能谈上去的岗位。
- **写 `match.toml` 的正则时，英文缩写一定要加 `\b`。** 这是踩过的坑：
  `APT` 不加词边界会命中「C**apt**ion」，`Web\s?3` 会命中「**Web 3D**」。
  信号表是你自己的配置，没有人替你复核——`job match --why` 打出命中理由就是
  给你自查用的。

## 接口限速

服务端实测约 **10 次 / 60s 滑动窗口**（不是 60 次/分钟），触发后冷却 20 分钟以上，
期间任何请求都被拒，且失败是静默的。客户端默认限到 8 次/分钟，调大有风险。

限流按 token 记账（鉴权在网关层、业务层之前），换 IP 无效。
触发限流会**中止整批采集**并写明未完成的关键词：继续往下跑只会让剩余关键词全部失败，
看起来像「这些方向没有职位」。

注意区分两个长得很像的错误：`code=429001` 是真限流（`LiepinRateLimited`），
`code=-1`（文案「你查询过多，等会再查吧」）其实只是分页越界（`LiepinPageLimit`），
是正常的翻页终止条件。

## 开发

```bash
make check      # ruff + mypy + pytest
make test
uv run pytest tests/test_matching.py -v
```

测试不碰真实的 `jobs.db`，也不发任何网络请求：每个用例在临时目录里搭一套
完整的 `config/` + `data/`，顺便验证了「换一个项目根目录也能跑」。

**数据库不做迁移，接口不做向后兼容**（见 CLAUDE.md 硬规则）：库结构改了就
`job reset` 删库重建，再 `job search` + `job detail` 重采一遍；接口字段改了就同步改
`frontend/`。这是个单人工具，数据随时能重新采集，为「万一有老库」写的兼容代码
只会一直留在仓库里没人敢删。

`job reset` 会把投递记录一并删掉——猎聘没有查询投递记录的接口，那张表是唯一的账本，
所以它默认要确认一次。
