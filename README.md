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
仓库只负责把事实准备好：去重、薪资换算、按你的 `[score]` 信号表排序。

运行按 **profile** 隔离：**一个 profile = 一个人，或者一种求职场景**
（「AI 应用工程」和「Web3 安全」可以是两个 profile）。每个 profile 是一个自包含的目录，
简历、关键词、信号表、数据库、产物全在里面，`profiles/a` 与 `profiles/b` 互不可见；
跟人无关的东西（猎聘账号密钥、模型接入点、限速、Web 端口）仍然全局共享一份。

```bash
uv sync --extra dev          # 安装依赖
uv run job config init       # 生成全局配置 config/config.toml（密钥填这里）
uv run job profile new me    # 建一个 profile（简历、关键词、数据库都在它自己的目录里）
uv run job search            # 采集职位（搜完自动抓 JD）
uv run job score             # 按信号表重新打分、落库、排序（分诊）
uv run job llm-score --top 30           # 让模型给前 30 条打两个维度的分（要填 API key）
uv run job score -o data/shortlist.md   # 生成候选清单骨架
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
（token、城市与薪资门槛、搜索关键词、简历、求职偏好、匹配信号表）。想手填就照
两份配置文件里的注释改，填完 `uv run job config validate` 自检。
后续要调**搜索关键词**与**打分逻辑**，在 `job web` 的「配置」页改最省事——
它写回的就是 `profile.toml` 那两段（见「Web 管理台」）。

采完数据之后 `job score` 分诊、`job llm-score` 让模型读 JD 打分，在 `job web`
里按两个分数翻着看、点投递。打过几十条 LLM 分之后**跑 `/job-align`**：
它拿模型的分当参照，把关键词信号表校准一遍。完整流程：

```
job profile new <名字> → /job-init          # 一次性：建 profile、填简历与关键词
job search → job score → job llm-score --top 30 → job web 翻 JD、点投递 → job apply
          ↘ job align → /job-align   （有了 LLM 分之后：对照它校准 [score] 信号表）
          ↘ job score -o data/shortlist.md （候选清单骨架，判断部分留白）
          ↘ job web （翻 JD、看库存、点投递、改关键词与打分逻辑、批量 LLM 打分）
```

## 目录结构

```
config/                跟人无关的那一半
  config.example.toml  全局配置模板（进版本库）
  config.toml          全局配置：猎聘账号密钥、模型接入点、限速、Web、日志（不进版本库）
  templates/           新建 profile 的模板，整份拷成一个新 profile（进版本库）
profiles/              随人而变的那一半，整个目录不进版本库
  <名字>/               一个 profile = 一个人 / 一种求职场景，自包含
    profile.toml       搜索条件与关键词 + [score] 匹配信号表（正负信号 + 权重）
    resume.md          你的简历
    preferences.md     求职偏好（base 地 / 期望薪资 / 不看的岗位 / 面试口径）
    score_appeal.md    LLM 打分维度一的提示词（可选，不存在就用内置默认）
    score_fit.md       LLM 打分维度二的提示词（同上）
    data/              jobs.db（含 job_scores / llm_scores 两张表）、shortlist.md、agent-plan.md
src/job_agent/
  config/              配置加载与校验（TOML → 校验过的 Settings，密钥是 SecretStr）
  core/                核心能力，不依赖 CLI / Web
    liepin/            猎聘接口客户端（限速、错误码翻译、请求模型）
    storage/           SQLite：ORM 模型、仓储、轻量迁移
    services/          用例编排：search / detail / apply（带进度回调与取消）
    matching/          两套打分：按信号表分诊排序（scorer）+ LLM 语义打分（llm_scorer）
    llm/               模型客户端与结构化输出适配 + LLM 打分的方法论提示词
    resume/            PDF / DOCX / TXT 简历 → 纯文本
    dataset.py         jobs × job_details → 打分用的行集合（去重、薪资换算）
    jd_parser.py       详情页 → 结构化 JD（纯函数）
    salary.py          薪资文本 → 年薪区间（万元，税前）
  cli/                 typer 子命令（执行路线一：人或 skill 驱动）
  web/                 FastAPI 管理后端 + 后台任务
  agent/               LangGraph 独立执行（执行路线二）
frontend/              React + TypeScript（Vite / pnpm）管理台，构建到 frontend/dist 由后端托管
scripts/               一次性脚本（导出、关键词覆盖率核对）
tests/                 pytest（不碰真实库、不发网络请求）
.claude/skills/
  job-init/            `/job-init`：交互式收集信息并填好 config/
  job-align/           `/job-align`：对照 LLM 分校准 [score] 信号表（驱动 job align）
```

依赖方向单向：`cli` / `web` → `core` → `config`，`agent` → `core` → `config`。
反向依赖一律禁止；两条执行路线（`cli`+`web` 与 `agent`）互不 import，
共享的确定性内核只有 `core/` 与 `config/`（`tests/test_boundaries.py` 强制这条边界）。
唯一的豁免是 `cli/commands/agent_cmd.py`——`job agent` 的入口壳子，只 import
`agent/runner.py`、只翻选项不写流程；测试按文件名 + 模块名 + 行数上限钉死它。

## 配置

所有个人化的东西都在 profile 目录里，代码里不硬编码任何个人信息。
配置**只有两个文件，段名完全不重叠**——放错了会当场报错并告诉你该放哪：

| 文件 | 管什么 | 段 |
| --- | --- | --- |
| `config/config.toml` | **怎么连**，跟人无关，全局一份 | `[profiles]`、`[liepin]`、`[detail]`、`[agent]`、`[llm_score]`、`[web]`、`[logging]` |
| `profiles/<名>/profile.toml` | **找什么**，随人而变，一个 profile 一份 | `[profile]`、`[search]`、`[storage]`、`[score]` |

- `config/config.toml`：全部密钥都在这（猎聘 token、模型 API key、LangSmith key）。
  它不进版本库，所以密钥直接填在里面；每一项都有注释，见 `config/config.example.toml`。
  猎聘 token 填在 `[liepin.accounts.<账号名>].user_token`，前往
  <https://www.liepin.com/mcp/auth> 生成。可以同时放几个人的账号，
  profile 用 `[profile].account` 指一个——换人不用来回重贴 token。
- `profiles/<名>/profile.toml`：搜索条件、搜索关键词、`[score]` 打分门槛与匹配信号表。
  里面的相对路径都相对于**这个 profile 的目录**，所以两个 profile 的
  `data/jobs.db` 是两个库。
- `profiles/<名>/resume.md`、`preferences.md`：你的简历与求职偏好。程序不解析它们，
  刻意保持自由格式 Markdown——它们是挑岗位、准备面试问答时的输入。
  `/job-init` 会带你写；模板见 `config/templates/`。
- `profiles/<名>/score_appeal.md`、`score_fit.md`：LLM 打分两个维度的提示词。
  **这两个文件默认不存在**——那表示用 `src/` 里的内置方法论。想改就建同名文件
  （或在 Web 的「配置」页里改），内容整段替换默认，输出格式那一截仍由代码拼。
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

`[search].keywords` 是一个**扁平数组，顺序即优先级**。因为按 jobId 去重且先搜
高优先级的词，每条职位记录到的 `searchKeyword` 就是「最先命中它的那个词」。

刻意不按方向分组——**一个 profile 就是一个方向 / 一个人**，组内再分组是把
profile 这一层重复了一遍。想同时跑两条线就开两个 profile
（`job profile new web3`）。临时只搜某几个词用 `job search -k`；
不想再搜的词在 TOML 里注释掉即可，留着能看出库里存量数据是怎么来的。

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
job search [-k 关键词]... [--pages N] [--limit N] [--retry-failed] [--no-detail] [--dry-run]
job score [--floor 万] [-n N] [--why] [--json] [-o 路径] [--no-dedupe]
           # 每次都是「按最新 [score] 重新打分并写进库」，不是只读
           # -o 的相对路径按 profile 目录解析；配 --json 就是把 JSON 写进文件
job llm-score [jobId...] [--top N] [--all] [--floor 万] [--force] [-j N]
           [--provider P] [--model M] [--why] [--json] [-o 路径] [--yes]
           # 让模型打两个维度的分（吸引力 / 胜任度，各 1-10 + 依据）
           # 按条计费，所以**必须**用 jobId / --top / --all 说清楚打哪些
job resume import <文件> [-o 输出路径] [--force]
job apply <jobId>... [--job-kind 1|2] [--yes]
job agent [--collect] [--apply] [-n N] [--provider P] [--model M] [--thread ID]
job stats
job web [--host H] [--port P] [--no-browser] [--skip-build]
job profile list|new|use|path
job config init|show|path [--json]|validate
job db info|vacuum|reset [--yes]
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

## 挑岗位：`job score` / `job llm-score`

采集解决「有哪些岗」，这两样解决「该投哪几个」。分界线是**确定性 vs 判断**：

```bash
uv run job score -n 30 --why          # 打分排序，--why 展开命中与扣分理由
uv run job score --json               # 给脚本用
uv run job score -n 12 -o data/shortlist.md   # 写出候选清单骨架（判断部分留白）
uv run job score --json -o out.json   # -o 决定写文件，--json 决定格式，两者正交
```

`job score` 的排序来自当前 profile 的 `[score]` 信号表（在 `profile.toml` 里），
**它是配置不是代码**——
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
  「这个岗要 50 人管理经验而你带 5 人」这种判断要读 JD，是 `job llm-score` 的事。
  第 1 名可能有硬门槛冲突，第 8 名可能才是最该投的。

### 两种打分的分工

`job score` 之外还有一层 `job llm-score`：让模型读 JD 与你的简历，打**两个维度**的分，
各 1-10 分并附一条或多条依据。

| | `job score` | `job llm-score` |
| --- | --- | --- |
| 依据 | `[score]` 关键词命中 | 读 JD 与简历的语义判断 |
| 成本 | 本地几毫秒 | 每条一次模型调用，按条计费 |
| 刷新 | 整表重写全库排名 | 按条 upsert，已打的留着 |
| 默认范围 | 全库 | **必须显式指定** |

两个维度回答的是两个不相干的问题，所以**并列落库、不合成总分**：

- **岗位吸引力（appeal）**——从求职者一侧，**以你写下来的求职期望为决定性标准**：
  先按 `preferences.md` 里的优先方向 / 也可以考虑 / 明确不看 / 硬约束定一个分数区间
  （方向不在期望里的最高 4 分，明确排除或违反硬约束的 1-2 分），
  再在区间内看薪资水位、公司体量与阶段、JD 专不专业、业务靠不靠谱。
  薪资再高、公司再大也抬不出区间上限——方向不对的好机会仍然不该投。
- **胜任匹配度（fit）**——从招聘方一侧：硬门槛过不过、核心经历贴不贴、
  技术栈与职级差多少，也就是你拿到这份工作的概率。

合成一个「推荐度」会把两者搅在一起：「够不着的好岗」和「够得着的烂岗」算出来一样高，
而这两种情况该做的事完全不同（前者去准备说服，后者去想想要不要投）。

```bash
uv run job llm-score --top 30 --why      # 按关键词分数取前 30 条，展开依据
uv run job llm-score 1234 5678           # 指定 jobId
uv run job llm-score --all --yes         # 全库（默认要确认）
uv run job llm-score --top 30 --force -j 8   # 重打 + 并发 8
uv run job llm-score --top 30 --provider deepseek   # 临时换个便宜模型
```

三个要知道的口径：

- **不给范围就报错退出。** 一条命令顺手花掉几千次调用的钱，不该是「忘了带参数」
  就能触发的。
- **同模型 + 同提示词已经打过的默认跳过**，`--force` 才重打。换了模型或改了提示词
  就不跳过——旧分数和新的不可比。`job stats` 会报出库里混着几条旧口径的分数。
- **判断方法论可以改。** 两段提示词的默认值在 `src/` 里（只写方法论），
  想改就在 profile 目录下建 `score_appeal.md` / `score_fit.md`，或者在
  `job web` 的「配置」页里改。「你想去什么方向」不用写进提示词——
  简历与 `preferences.md` 会一起发给模型。

配 API key：`config/config.toml` 的 `[agent.providers.*]` 填 `api_key`；
`[llm_score].provider` 指其中一个（留空 = 跟随 `[agent].provider`），
`[llm_score].concurrency` 控并发（默认 4）。

`-o` 产出的 Markdown 里，每条岗位有三处 `<待读 JD 后填写>`：
**硬门槛核对**、**投不投**、**投递口径**。代码刻意不填——填了模板话术，
人会以为已经分析过了，比留空更糟。

### 校准信号表：`job align` / `/job-align`

信号表第一版是访谈拍出来的。打过一批 LLM 分之后，两套分数就能互相对照：
**关键词分诊有没有把模型认可的岗位送进视野？**

```bash
uv run job align                      # 秩相关、窗口召回、逐条信号命中均分、漏网与误报
uv run job align --split              # 每条信号按顶层 | 拆成子模式，看哪个词在乱命中
uv run job align --probe 'agent\s*infra' --context   # 试一条候选正则，附命中快照
uv run job align --top 60 --appeal-floor 8            # 窗口与分数线都是参数
uv run job align --json -o data/align.json
```

它只算统计、不写库、不给建议。「认可」（吸引力 ≥7 且匹配 ≥5）与「明确不看」
（吸引力 ≤4）的分数线默认对齐内置提示词的锚点，改过提示词就一起改参数。
「砍哪个词、权重调到几、要不要加一条头衔信号」是判断——在 Claude Code 里跑
`/job-align`，它读统计、看快照、改 `[score]`、复测，并把偏好里没写全的地方
（模型因此判错的那类岗位）交还给你。skill 对任何 profile 都成立：它不含方向取向，
只从这个 profile 的 `preferences.md` 与 `[score]` 注释里读。

三个要知道的口径：

- **样本要够、要覆盖到关键词排名靠后的岗位。** 只打了前 30 条 LLM 分，
  永远看不到「关键词排 200 名但模型认可」的漏网。
- **口径要统一。** 库里混着换过模型或改过提示词的分数时 `job align` 会警告，
  它们互相不可比。
- **模型也会错。** 它照 `preferences.md` 判，偏好没写全的地方它就会判错——
  那是偏好的问题，不是信号表的问题，也不要为了迎合它删负信号。

## 无人值守：`job agent`（LangGraph 路线）

CLI + Web 是交互式的：你翻 JD、看两套分数、点投递。`job agent` 是同一条流程的
无人值守版——LangGraph 组的固定管线，一条命令跑完 **分诊 → 逐岗审读 → 投递计划**，
共享同一个数据库、同一份 `config/`：

依赖跟着 `uv sync` 一起装；唯一的前置是在 `config/config.toml` 的
`[agent.providers.*]` 里填 `api_key`（审读节点要调模型 API）。

```bash
uv run job agent                      # 用库内已有数据：分诊 → 审读 → <profile>/data/agent-plan.md
uv run job agent --collect            # 先采集（搜索 + 抓 JD）再走上面的流程
uv run job agent --apply              # 出完计划后进入投递确认（终端里逐条拍板）
uv run job agent --thread run-x       # 中断后用同一 thread 从 checkpoint 续跑
uv run job agent --provider deepseek  # 换模型：用 [agent.providers.deepseek]
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

带 `:free` 后缀的 slug 不花钱，代价是每日调用上限，跑之前用 `-n` 控量。
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
  `job score` 和 `job agent` 对同一份数据给出同一个 shortlist。
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

- **职位**：顶部一排**库存一览**（职位数、JD 数、薪资水位、分数新鲜度、LLM 打分
  覆盖率、投递数），下面是操作区（**重新打分**、LLM 打分当前筛选结果、**批量选择**
  一批送 LLM 打分）与列表。列表不分页一次全给、点表头排序，按关键词 / 薪资 /
  **岗位来源**（HR 岗位 or 猎头岗位）/ 是否有 JD / 是否投递 / **是否 LLM 打过分**
  筛选；每行可单独送 LLM 打分；点行在右侧抽屉里看 JD 全文、关键词分诊依据与
  两维裁决，一键投递（有二次确认）
- **采集任务**：在页面上发起搜索 / 抓详情、看 LLM 打分进度，实时看日志，可取消
- **配置**：分四页，**全部配置项都能改**——「职位采集」（搜索条件与关键词、
  猎聘 token 与限速、详情页抓取节奏）、「职位评分」（`[score]` 信号表、
  LLM 打分参数）、「提示词」（简历、求职偏好、两段打分方法论）、
  「高级」（两个配置文件的全文编辑）

API 文档在 `/docs`。后台任务**只有一个 worker**：猎聘限流按 token 记账，
并行只会更快被封；SQLite 的写也不适合并发。取消是协作式的——
线程不能安全地被杀，服务会在当前条目结束后停下，已完成的进度都已落库。

**岗位来源**是猎聘的 `jobType`：`2` 是企业 HR 自己挂的岗（详情页 `/job/`），
`1` 是猎头代招（`/a/`）。接口不支持按它过滤，所以是采回来之后在本地筛。
同一个岗常被几家猎头重复挂出、标价还各挂各的，所以打分那边按 JD 正文去重。

**重新打分**（`POST /api/scores/refresh`）就是页面上的 `job score`：同一个
`core.matching.refresh`，读当前 `[score]` 把全库重算一遍、整表重写 `job_scores`。
它不进后台任务队列——打分不发请求、不受限流约束，几千条一两秒就完了。

**LLM 打分**在页面上是勾选式的：职位表每行前面一个复选框，选好之后点
「给选中的 LLM 打分」（或「打分当前 N 条」打完整个筛选结果），二次确认后排进
后台任务队列，进度、日志与取消都在「采集任务」页。它**进队列**而重新打分不进，
判据是「会不会发请求」：打分是本地计算、几千条一两秒；LLM 打分按条调 API、
按条计费、跑几分钟，正是队列存在的理由。换筛选条件会清空勾选——
勾了 30 条、一改关键词只剩 3 条在屏幕上，然后点打分，花的是那 30 条的钱。

**配置页能改全部配置项**。`job web` 是这个系统的完整入口：一条命令起来之后，
从填 token、配搜索条件，到调打分口径、改简历与提示词，再到投递，全程不必回终端。
页面按**求职流程**分四块而不是按文件分——一件事常常横跨两个配置文件
（采集就同时用到 profile.toml 的 `[search]` 和全局的 `[liepin]`），
按文件分会把「做一件事」拆到两页去。前三块是表单，「高级」是两个文件的文本
编辑器：与其给模型接入点、LangSmith、日志各做一个做完没人点第二次的表单，
不如把文件本身交出来。

**密钥给明文**：服务只监听本机、单人使用，「打得开这个页面」与
「`cat` 得到 `config/config.toml`」是同一份权限，打码只会让人没法在页面上填
token。别处（日志、`job config show --json`）仍然一律打码。

**改的仍然是文件**：保存 = 写回那两个 `*.toml`（或 profile 目录下的 md）
再重新加载，所以 CLI、Web、`job agent` 读到的永远是同一份，不存在
「网页上改了但下次 CLI 跑的是另一套」。全文编辑**落盘前先 parse 再按模型校验**，
坏内容一个字节都进不去。

**写回一律定点替换**（`config/writer.py`），比的是模型层的值而不是文本：
原样保存一遍文件**逐字节不变**，引号风格、小数点、手工对齐的空格、
行尾注释所在的列全都留着。信号表按 `name` 对齐、关键词按词对齐——
`[score]` 段里那上百行「这条为什么是 -14」的注释、关键词数组里的分组说明，
都不会因为点了一次保存就被冲掉。改完 `[score]` 库里的分数就过期了
（指纹一比就知道），页面会提示，点「重新打分」才会按新规则重算全库排名。

前端开发：`cd frontend && pnpm dev`（5173 端口，`/api` 自动代理到 18000）。
包管理器是 **pnpm**，源码**一律 TypeScript**——接口字段抄在 `src/types.ts`，
后端改了字段 `pnpm typecheck` 会指到真正用它的那一行（见「开发」一节）。

## 详情页抓取

`job search` 搜完列表就接着抓详情页（`--no-detail` 可以只搜不抓）。
两半都可重跑：搜索按 jobId 去重，详情按已抓状态跳过，所以被限流打断后直接重跑即可。

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
  提醒你搜回来的不都是达标岗。门槛取自 profile 的 `[score].salary_floor_wan`，
  **没配就不报这个比例**——不假装存在一条客观的达标线。
- **同一份 JD 常被多家猎头重复挂出**：正文一字不差，但职位名和标价各挂各的
  （实测有一份被挂了 8 次，同一岗位标价能差 2–3 倍）。
  `load_rows()` 默认按 **JD 正文**去重并保留标价最高的那条——
  用「职位名 + 正文」做键会漏掉大部分重复。
- **薪资门槛比的是区间上限，不是下限。** 上限才代表「这家最多能给到多少」，
  按下限过滤会误杀「50-80k·20薪」这类实际能谈上去的岗位。
- **写 `[score]` 里的正则时，英文缩写一定要加 `\b`。** 这是踩过的坑：
  `APT` 不加词边界会命中「C**apt**ion」，`Web\s?3` 会命中「**Web 3D**」。
  信号表是你自己的配置，没有人替你复核——`job score --why` 打出命中理由就是
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
make install    # uv sync + pnpm install（前端用 pnpm，不用 npm）
make check      # ruff + mypy + tsc + pytest
make test
uv run pytest tests/test_matching.py -v
```

前端源码**全是 TypeScript**（`.ts` / `.tsx`，没有 `.js`）。接口字段抄在
`frontend/src/types.ts` 里，一一对应 `web/schemas.py` 与 `core/storage/rows.py`
的 pydantic 模型——**后端改了字段这里就得跟着改**，`make check` 里的 `tsc`
会把报错落在真正用到它的那一行，而不是等页面上渲染出空白。

测试不碰真实的 `jobs.db`，也不发任何网络请求：每个用例在临时目录里搭一套
完整的 `config/` + `data/`，顺便验证了「换一个项目根目录也能跑」。

**数据库不做迁移，接口不做向后兼容**（见 CLAUDE.md 硬规则）：库结构改了就
`job db reset` 删库重建，再 `job search` 重采一遍；接口字段改了就同步改
`frontend/`。这是个单人工具，数据随时能重新采集，为「万一有老库」写的兼容代码
只会一直留在仓库里没人敢删。

`job db reset` 会把投递记录一并删掉——猎聘没有查询投递记录的接口，那张表是唯一的账本，
所以它默认要确认一次。
