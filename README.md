# job-agent

> **产品核心定位：这是一个求职系统。**
>
> 不是爬虫，也不是数据分析工具库。它的目标是端到端支撑一个人完成一次求职：
> 从「我是谁、我想要什么」开始，到「该投哪几个岗、为什么、怎么谈」结束。
>
> 由此确定分工——**CLI 负责确定性，skill 负责判断**：
>
> - **CLI**（本仓库代码）承担一切可重跑、可测试、结果可比的环节：
>   采集、限流退避、去重、JD 解析、薪资换算、按规则打分排序、生成报告。
>   同样的库跑两次，结论必须一样。
> - **Skill**（`.claude/skills/`）承担需要语言理解、代码穷举不出来的环节：
>   读 JD 判断硬门槛冲突、比对简历措辞与市场词汇、排投递优先级、准备面试口径。
> - **`config/`** 承担一切因人而异的东西：简历、求职偏好、搜索关键词、
>   匹配信号表。**换一个用户，只应该换 `config/`，不该改代码。**
>
> 判断一个新功能该不该加、加在哪，就用这三条对照：
> 结论必须稳定复现的 → CLI；需要读懂文字才能下判断的 → skill；随人而变的 → config。

猎聘职位工具链：批量搜索 → 抓取详情页 JD → 赛道 / 技能统计 → 生成 HTML 市场报告 → 投递，
数据全部落在本地 SQLite。提供 **CLI** 与 **Web 管理台**两套入口，配置与个人资料全部在 `config/`。

```bash
uv sync --extra dev          # 安装依赖
uv run job config init       # 从模板生成 config/ 下缺失的文件
uv run job search            # 采集职位
uv run job detail            # 抓 JD
uv run job match             # 按信号表给职位打分排序（分诊）
uv run job shortlist         # 生成候选清单骨架
uv run job report            # 出报告
uv run job web               # 打开 Web 管理台
```

配置怎么填？**在 Claude Code 里跑 `/job-init`**，它会问你需要的信息并写进对应位置
（token、城市与薪资门槛、关键词分组、简历、求职偏好、匹配信号表）。想手填就照
`config/` 下各文件的注释改，填完 `uv run job config validate` 自检。

采完数据之后**跑 `/job-match`**：它读 JD、比硬门槛、排投递优先级、写投递口径，
把 `job shortlist` 留白的判断部分填掉。完整流程：

```
job search → job detail → job match → job shortlist → /job-match → job apply
                       ↘ job report / job web （看市场大盘）
```

## 目录结构

```
config/                用户自己的东西（配置、token、简历、报告文案），不进版本库
  config.example.toml  配置模板（进版本库）
  config.toml          你的配置
  .env                 猎聘 token
  resume.md            你的简历
  preferences.md       求职偏好（base 地 / 期望薪资 / 不看的岗位 / 面试口径）
  match.toml           匹配信号表：正负信号 + 权重（决定 job match 的排序）
  *.example.*          上面每份文件的模板（进版本库）
  insights/            报告里的定性结论（HTML 片段 + 匹配矩阵）
src/job_agent/
  config/              配置加载与校验（TOML + .env → 校验过的 Settings）
  core/                核心能力，不依赖 CLI / Web
    liepin/            猎聘接口客户端（限速、错误码翻译、请求模型）
    storage/           SQLite：ORM 模型、仓储、轻量迁移
    services/          用例编排：search / detail / apply（带进度回调与取消）
    analysis/          赛道分类、技能词典、统计聚合
    matching/          按信号表打分排序 + 候选清单骨架（只分诊，不下结论）
    resume/            PDF / DOCX / TXT 简历 → 纯文本
    report/            HTML 报告渲染 + insights 素材加载
    jd_parser.py       详情页 → 结构化 JD（纯函数）
    salary.py          薪资文本 → 年薪区间（万元，税前）
  cli/                 typer 子命令
  web/                 FastAPI 管理后端 + 后台任务
frontend/              React（Vite）管理台，构建到 frontend/dist 由后端托管
scripts/               一次性分析脚本（改分类规则时用来核对）
tests/                 pytest（不碰真实库、不发网络请求）
data/                  jobs.db、生成的报告
  shortlist.md         job shortlist 的产物：候选清单（判断部分留白给 skill 填）
.claude/skills/
  job-init/            `/job-init`：交互式收集信息并填好 config/
  job-match/           `/job-match`：读 JD、比硬门槛、排投递优先级、写投递口径
```

依赖方向单向：`cli` / `web` → `core` → `config`。反向依赖一律禁止。

## 配置

所有个人化的东西都在 `config/`，代码里不硬编码任何个人信息。

- `config/config.toml`：搜索条件、关键词分组、限速、路径、Web 端口、日志级别。
  每一项都有注释，见 `config/config.example.toml`。
- `config/.env`：`LIEPIN_USER_TOKEN`（前往 <https://www.liepin.com/mcp/auth> 生成）。
- `config/resume.md`、`config/preferences.md`：你的简历与求职偏好。程序不解析它们，
  刻意保持自由格式 Markdown——它们是写报告「给我的建议」章节、挑岗位、
  准备面试问答时的输入。`/job-init` 会带你写；模板见同目录的 `*.example.md`。
- `config/insights/`：报告里的文字结论，`job config init` 会从 `insights.example/`
  生成一份模板。素材缺失不会让报告失败——定量部分照样出，只是少了文字解读。
- 环境变量可覆盖：`JOB_AGENT_CONFIG`、`JOB_AGENT_HOME`、`JOB_AGENT_DB`、
  `JOB_AGENT_LOG_LEVEL`、`JOB_AGENT_WEB_HOST/PORT`、`LIEPIN_*`。

配置项**拼错会直接报错**（`extra="forbid"`），不会被静默忽略——
静默忽略是配置系统最容易埋的坑（把 `salary_floor` 写成 `salaryFloor`，
结果搜出一堆不达标的岗位却毫无提示）。

关键词按数组顺序（= 优先级）搜索。因为按 jobId 去重且先搜高优先级方向，
每条职位记录到的 `searchKeyword` 就是「最先命中它的方向」，它同时是分类兜底的依据。
不再搜索但库里有存量数据的关键词，请保留在配置里并设 `enabled = false`：
**否则这些职位会因为查不到赛道而整片掉进「其他」**。

## 初始化：`/job-init`

`.claude/skills/job-init/` 是一个 Claude Code skill。在仓库里对 Claude 说
`/job-init`（或「帮我初始化 job-agent」），它会按 **token → 搜索条件 → 简历 → 求职偏好**
四步访谈，把答案写进 `config/` 对应文件，最后跑 `job config validate` 与
`job search --dry-run` 自检。

几个刻意的设计：token 只写进 `config/.env`、不回显、不进对话；已有文件先读再改，
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
job report [-o 输出路径] [--no-dedupe]
job stats [--tracks]
job web [--host H] [--port P] [--no-browser] [--skip-build]
job config init|show|path|validate
job db info|migrate|vacuum
```

全局选项：`--config` 指定配置文件、`--log-level`、`--quiet`、`--version`。

退出码：`2` 配置/鉴权问题、`3` 存储、`4` 报告、`5` 接口错误或简历抽取失败、`6` 触发限流。
脚本里可以据此判断「今天别再投了」。

`job apply` 默认会列出待投职位并要求确认（`--yes` 跳过）。投递结果（含「已投递过」
「职位已结束」）都会记进本地 `applications` 表——**猎聘没有查询投递记录的接口**，
这张表是唯一的账本。

## 挑岗位：`job match` / `job shortlist` / `/job-match`

采集解决「有哪些岗」，这三样解决「该投哪几个」。分界线是**确定性 vs 判断**：

```bash
uv run job match --top 30 --why       # 打分排序，--why 展开命中与扣分理由
uv run job match --json               # 给脚本用
uv run job shortlist --limit 12       # 写出 data/shortlist.md（判断部分留白）
```

`job match` 的排序来自 `config/match.toml` 的信号表，**它是配置不是代码**——
编码的是「你想要什么」，换个人应当整份重写：

```toml
[require]                     # 职位名与 JD 都不含这些词 = 连赛道都不对，压到末尾
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

## 导入简历：`job resume import`

```bash
uv run job resume import ~/Downloads/我的简历.pdf     # 打到 stdout
uv run job resume import 简历.docx -o /tmp/resume.txt
```

支持 `.pdf`（pypdf）、`.docx`（直接解 zip 里的 XML，不引 lxml）、`.md` / `.txt`。
`.doc` 不支持，另存为 `.docx` 或导出 PDF。

**它只抽纯文本，不写 `config/resume.md`**——抽出来的是没有结构的文字，
直接覆盖会把排版和数字弄丢。整理成结构化 Markdown 是 `/job-init` 的工作：
它会保留全部事实与数字、对齐市场词汇、缺信息时留 `<待补>`。
（真要覆盖得加 `--force`，命令会先拦你一次。）

## Web 管理台

`job web` 启动后（默认 <http://127.0.0.1:18000>）提供三个页面：

- **职位**：分页、按方向/薪资/是否有 JD/是否投递筛选、展开看 JD 全文、一键投递（有二次确认）
- **采集任务**：在页面上发起搜索 / 抓详情 / 生成报告，实时看进度与日志，可取消
- **数据概览**：库内统计、赛道分布（结果缓存）、当前配置与路径

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

## 分析口径（几个必须知道的坑）

- **猎聘的薪资筛选是「区间重叠」而不是「下限 ≥ 100 万」**，还会漏进明显不达标的条目
  （样本里出现过实习生岗）。当前样本只有 84% 的结果薪资上限真正够到 100 万，
  各赛道差异很大（安全 95%、AI 86%、后端 73%）。统计里单独用 `meets100` 暴露这个比例，
  报告里的总比例是实算的、不写死。
- **同一份 JD 常被多家猎头重复挂出**：正文一字不差，但职位名和标价各挂各的
  （实测有一份被挂了 8 次，同一岗位标价能差 2–3 倍）。
  `load_rows()` 默认按 **JD 正文**去重并保留标价最高的那条——
  用「职位名 + 正文」做键会漏掉大部分重复。
- **「安全」是中文歧义词**：车规功能安全（ISO 26262 / SOTIF / ASIL）、
  毒理 / 医学总监、食品安全都会混进来，且与信息安全零交集，必须先剔除。
- **技能词典里不能用过于宽泛的词**：只写「合规」会把命中率虚高到 30%+，
  只写「对齐」会命中「对齐业务预期」，`Go` 直接用 `\bgo\b` 会命中英文动词。
  这几处都限定了上下文。
- 兜底分类要求 JD 正文出现足够多的赛道信号词，否则归入「其他」——
  否则按「区块链」关键词返回的 CMO、大客户总监会被整片算成 Web3 技术岗。
- **同样的「正则太宽」问题也会出在职位名规则里，而且更隐蔽**：
  `APT` 不加词边界会命中「C**apt**ion」（实测把 5 个标注岗算成了攻防岗），
  `Web\s?3` 不排除会命中「**Web 3D**」。英文缩写一律加 `\b`，短前缀要排除更长的真词。
  赛道样本越小，单条误匹配的破坏力越大——**改完 `core/analysis/rules.py` 一定要跑**：

  ```bash
  uv run python scripts/audit_classification.py --track 安全
  ```

  `tests/test_classify.py` 把上面每个坑都钉成了回归用例。

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
uv run pytest tests/test_classify.py -v
```

测试不碰真实的 `data/jobs.db`，也不发任何网络请求：每个用例在临时目录里搭一套
完整的 `config/` + `data/`，顺便验证了「换一个项目根目录也能跑」。

数据库升级由 `core/storage/migrations.py` 处理（加列 + 回填，幂等），
`job db migrate` 可手动触发。
