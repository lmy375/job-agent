# job-agent

猎聘职位工具链：**批量搜索 → 抓取 JD → 打分分诊 → LLM 读 JD 打分 → 投递**，
数据全部落在本地 SQLite。三个入口共享同一份配置与数据库：

| 入口 | 命令 | 适用 |
| --- | --- | --- |
| CLI | `job …` | 采集、打分、投递，可脚本化 |
| Web 管理台 | `job web` | 翻 JD、改配置、点投递，鼠标全程可达 |
| 无人值守 agent | `job agent` | 一条命令跑完 采集 → 分诊 → 审读 → 投递计划 |

另有三个 Claude Code skill：`/job-init`（初始化）、`/job-align`（校准信号表）、
`/job-analysis`（就业市场分析）。

## 功能

- **采集**：按关键词批量搜索职位，接着抓详情页解析 JD（薪资、行业、经验学历要求）。
  串行限速 + 退避，中断后重跑自动跳过已完成项。
- **关键词分诊**（`job score`）：按你自己写的 `[score]` 信号表给全库打分排序并落库，
  几百条砍到几十条。本地计算，毫秒级。
- **LLM 打分**（`job llm-score`）：让模型读 JD 与你的简历，打两个维度的分——
  **岗位吸引力**（这份工作值不值）与**胜任匹配度**（你够不够格），各 1-10 分附依据。
  两个维度并列落库，不合成总分。
- **信号表校准**（`job align` + `/job-align`）：拿 LLM 分当参照给关键词信号表体检——
  秩相关、窗口召回、逐条信号命中均分、漏网与误报、候选正则探针。
- **投递**（`job apply` / Web 上点）：结果记进本地 `applications` 表
  （猎聘没有查询投递记录的接口，这是唯一的账本）。**不可撤销。**
- **profile 隔离**：一个 profile = 一个人 / 一种求职场景，简历、关键词、信号表、
  数据库、产物全在它自己的目录里，互不可见。

## 安装

```bash
make install          # uv sync --extra dev + pnpm install（前端）
```

只用 CLI 不用 Web 的话 `uv sync` 即可。

## 快速开始

```bash
uv run job config init       # 生成全局配置 config/config.toml（密钥填这里）
uv run job profile new me    # 建一个 profile
uv run job config validate   # 自检：token、简历、关键词是否就位
uv run job search            # 采集职位（搜完自动抓 JD）
uv run job score -n 30 --why # 关键词分诊，展开命中理由
uv run job llm-score --top 30        # 让模型给前 30 条打两个维度的分
uv run job web               # 打开 Web 管理台翻 JD、点投递
```

配置怎么填最省事：在 Claude Code 里跑 **`/job-init`**，它按
token → 搜索条件 → 简历 → 求职偏好四步访谈，把答案写进对应文件。
也可以直接跑 `job web`——缺配置会自动生成，token、关键词、简历、信号表都能在页面上填。

## profile

```bash
uv run job profile list      # 有哪些 profile、哪个是默认、各自多少条数据
uv run job profile new web3  # 新建（从 config/templates/ 拷模板）
uv run job profile use web3  # 设为默认
uv run job -p web3 search    # 任何命令都能 -p 指定
```

有两个及以上 profile 又没指定用哪个时会报错，不会猜。
Web 顶栏那颗 profile 徽章也能切换与新建。

定位顺序：`--profile` → `JOB_AGENT_PROFILE_NAME` → `[profiles].default`
→ 只有一个 profile 时就是它。

## 配置

配置只有两个文件，段名互不重叠，放错了会当场报错并告诉你该放哪：

| 文件 | 管什么 | 段 |
| --- | --- | --- |
| `config/config.toml` | 怎么连（全局共享一份，**密钥都在这**） | `[profiles]` `[liepin]` `[detail]` `[agent]` `[llm_score]` `[web]` `[logging]` |
| `profiles/<名>/profile.toml` | 找什么（一个 profile 一份） | `[profile]` `[search]` `[storage]` `[score]` |

profile 目录里还有几份 Markdown：

- `resume.md`、`preferences.md`——简历与求职偏好（自由格式，发给模型当输入）
- `score_appeal.md`、`score_fit.md`——LLM 打分两个维度的提示词**覆盖**，
  默认不存在（= 用内置方法论），想改就建同名文件或在 Web 配置页里改
- `data/`——`jobs.db`、`shortlist.md`、`agent-plan.md`

几个要点：

- **猎聘 token** 填在 `[liepin.accounts.<账号名>].user_token`，前往
  <https://www.liepin.com/mcp/auth> 生成；profile 用 `[profile].account` 指一个。
- **模型接入点**是 `[agent.providers.*]`，一张表一个接入点，`[agent].provider`
  与 `[llm_score].provider` 指哪个用哪个。客户端只有 `api = "anthropic"` 与
  `api = "openai"` 两类——DeepSeek、Kimi、通义、GLM、OpenRouter、本地 vLLM
  都走后者，区别只是 `base_url`。
- **环境变量可覆盖任意配置项**：`JOB_AGENT_<节>__<字段>`，如
  `JOB_AGENT_WEB__PORT=19999`、
  `JOB_AGENT_AGENT__PROVIDERS__DEEPSEEK__API_KEY=…`（密钥不想落盘时用）。
- **配置项拼错会直接报错**，不会被静默忽略。
- `job config path --json` 打印当前 profile 解析好的全部路径，供脚本与 skill 定位文件。

### `[score]` 信号表

`job score` 的排序来自这张表，它是**配置**——编码的是「你想要什么」，换个人整份重写：

```toml
[score.require]               # 职位名与 JD 都不含这些词 = 方向都不对，压到末尾
pattern = '\bagent\b|智能体|大模型'
penalty = -20.0

[[score.signals]]
name = "AI Agent / 智能体"
weight = 10                   # 正数加分，负数即「不想要的方向」
pattern = '\bagent\b|智能体|agentic'
```

**正则一律用单引号**（TOML 字面量字符串）——双引号里 `\b` 是退格符转义，
会静默变成匹配不上任何东西的正则；`job config validate` 会拦下来。
英文缩写记得加 `\b`：`APT` 不加会命中 "C**apt**ion"。

## 命令

```bash
job search [-k 关键词]... [--pages N] [-n N] [--retry-failed] [--no-detail] [--dry-run]
job score [--floor 万] [-n N] [--why] [--json] [-o 路径] [--no-dedupe]
job llm-score [jobId...] [--top N] [--all] [--floor 万] [--force] [-j N]
              [--provider P] [--model M] [--why] [--json] [-o 路径] [--yes]
job align [--top N] [--split] [--probe 正则] [--context] [--why] [--json] [-o 路径]
job apply <jobId>... [--job-kind 1|2] [--yes]
job agent [--collect] [--apply] [-n N] [--provider P] [--model M] [--thread ID]
job web [--host H] [--port P] [--no-browser] [--skip-build]
job stats
job resume import <文件> [-o 输出路径] [--force]
job profile list | new <名> | use <名> | path
job config init | show [--json] | path [--json] | validate
job db info | vacuum | reset [--yes]
```

全局选项：`-p/--profile`、`-c/--config`、`--log-level`、`-q/--quiet`、`-V/--version`。

退出码：`2` 配置/鉴权、`3` 存储、`5` 接口错误或简历抽取失败、`6` 触发限流。

几条用法上的口径：

- `job score` 是**刷新**不是查询：每次按当前 `[score]` 把全库重算一遍、整表重写。
  `--floor` / `-n` 只影响这次看什么，不影响写进库的全库排名。
  改过信号表或采了新数据，`job stats` 与 Web 库存卡会提示分数已过期。
- `job llm-score` 按条计费，所以**必须**用 jobId / `--top` / `--all` 说清楚打哪些，
  不给范围直接退出。同模型 + 同提示词已经打过的默认跳过，`--force` 才重打。
- `job apply` 默认列出待投职位要求确认（`--yes` 跳过）。

## Web 管理台

`job web` 启动后默认 <http://127.0.0.1:18000>，API 文档在 `/docs`。三个页面：

- **职位**：顶部库存一览（职位数、JD 数、薪资水位、分数新鲜度、LLM 覆盖率、投递数），
  下面是列表——不分页一次全给、点表头排序，按关键词 / 薪资 / 岗位来源（HR or 猎头）/
  是否有 JD / 是否投递 / 是否 LLM 打过分筛选。点行在右侧抽屉里看 JD 全文、
  分诊依据与两维裁决，一键投递。可以「重新打分」，也可以勾一批送 LLM 打分。
- **采集任务**：发起搜索 / 抓详情 / LLM 打分，实时看日志与进度，可取消。
- **配置**：分四页，**全部配置项都能改**——职位采集、职位评分、提示词（简历、
  求职偏好、两段打分方法论）、高级（两个 toml 的全文编辑）。

保存 = 写回文件再重新加载，CLI / Web / agent 读到的永远是同一份。
写回是定点替换：原样保存一遍文件逐字节不变，`[score]` 里那些注释不会被冲掉。
后台任务只有一个 worker（猎聘限流按 token 记账，并行只会更快被封），取消是协作式的。

前端开发：`cd frontend && pnpm dev`（5173 端口，`/api` 自动代理到 18000）。

## 无人值守：`job agent`

同一条流程的无人值守版，LangGraph 固定管线，共享同一个数据库与配置：

```bash
uv run job agent                      # 用库内已有数据：分诊 → 审读 → data/agent-plan.md
uv run job agent --collect            # 先采集再走上面的流程
uv run job agent --apply              # 出完计划后进入投递确认（终端里逐条拍板）
uv run job agent --thread run-x       # 中断后用同一 thread 从 checkpoint 续跑
uv run job agent --provider deepseek  # 换模型：用 [agent.providers.deepseek]
```

前置是在 `[agent.providers.*]` 里填 `api_key`。每步 checkpoint 到
`<profile>/data/agent-checkpoint.db`；模型标识写进投递计划头部。
`[agent.langsmith]` 填 `api_key` 即开启运行追踪，留空则完全不上报。

换兼容端点时唯一要留意的是 `structured_output`：官方端点留 `"auto"`，
兼容端点报「不支持 json_schema」就依次试 `"function_calling"` 和 `"json_mode"`。

## Claude Code skills

| skill | 做什么 |
| --- | --- |
| `/job-init` | 访谈式初始化：选/建 profile，填 token、搜索条件、简历、求职偏好，最后自检 |
| `/job-align` | 读 `job align` 的统计校准 `[score]` 信号表：砍误报词、调权重、复测 |
| `/job-analysis` | 用采到的 JD 现场分析就业市场：规模、价格分位、方向分布、简历差距 |

## 注意事项

- **薪资只有一种口径：税前**，单位是万元/年。门槛比的是区间**上限**
  （代表「这家最多能给到多少」），按下限过滤会误杀「50-80k·20薪」这类岗位。
- **猎聘的薪资筛选是「区间重叠」**而不是「下限 ≥ 门槛」，还会漏进明显不达标的条目。
  `job stats` 会单独报「上限真正 ≥ 门槛」的比例。
- **同一份 JD 常被多家猎头重复挂出**（实测有一份挂了 8 次，标价差 2-3 倍）。
  打分默认按 **JD 正文**去重并保留标价最高的那条，`--no-dedupe` 关掉。
- **接口限速**实测约 10 次 / 60s 滑动窗口（不是 60 次/分钟），触发后冷却 20 分钟以上，
  期间静默失败。限流按 token 记账，换 IP 无效。客户端默认限到 8 次/分钟。
  触发限流会中止整批采集并写明未完成的关键词。
- 注意区分：`code=429001` 是真限流；`code=-1`（「你查询过多，等会再查吧」）
  其实只是分页越界，是正常的翻页终止条件。
- **数据库不做迁移，接口不做向后兼容**：库结构变了就 `job db reset` 删库重采。
  注意 reset 会连投递记录一起删（所以它默认要确认一次）。
- `config/config.toml` 与整个 `profiles/` 都不进版本库，密钥直接填在里面是安全的。

## 目录结构

```
config/
  config.example.toml  全局配置模板（进版本库）
  config.toml          全局配置：密钥、限速、模型接入点、Web、日志（不进版本库）
  templates/           新建 profile 的模板
profiles/<名字>/        一个 profile，自包含（整个目录不进版本库）
  profile.toml  resume.md  preferences.md  score_*.md  data/
src/job_agent/
  config/              配置加载、校验与定点写回
  core/                内核：liepin 客户端 / storage / services / matching / llm / resume
  cli/  web/  agent/   三个入口
frontend/              React + TypeScript（Vite / pnpm），构建产物由后端托管
scripts/  tests/
.claude/skills/        job-init / job-align / job-analysis
```

## 开发

```bash
make install       # uv sync --extra dev + pnpm install
make lint          # ruff + mypy
make typecheck-web # 前端 tsc
make test          # pytest
make check         # 提交前跑这个：以上全部
```

前端源码一律 TypeScript，包管理器一律 pnpm。接口字段抄在 `frontend/src/types.ts`，
一一对应 `web/schemas.py` 与 `core/storage/rows.py`——后端改了字段这里得跟着改，
`tsc` 会指到真正用它的那一行。

测试不碰真实的 `jobs.db`，也不发任何网络请求。
