# job-agent

猎聘职位工具链：批量搜索 → 抓取详情页 JD → 赛道 / 技能统计 → 生成 HTML 市场报告 → 投递，
数据全部落在本地 SQLite。提供 **CLI** 与 **Web 管理台**两套入口，配置与个人资料全部在 `config/`。

```bash
uv sync --extra dev          # 安装依赖
uv run job config init       # 从模板生成 config/ 下缺失的文件
uv run job search            # 采集职位
uv run job detail            # 抓 JD
uv run job report            # 出报告
uv run job web               # 打开 Web 管理台
```

配置怎么填？**在 Claude Code 里跑 `/job-init`**，它会问你需要的信息并写进对应位置
（token、城市与薪资门槛、关键词分组、简历、求职偏好）。想手填就照 `config/` 下
各文件的注释改，填完 `uv run job config validate` 自检。

## 目录结构

```
config/                用户自己的东西（配置、token、简历、报告文案），不进版本库
  config.example.toml  配置模板（进版本库）
  config.toml          你的配置
  .env                 猎聘 token
  resume.md            你的简历
  preferences.md       求职偏好（base 地 / 期望薪资 / 不看的岗位 / 面试口径）
  *.example.*          上面每份文件的模板（进版本库）
  insights/            报告里的定性结论（HTML 片段 + 匹配矩阵）
src/job_agent/
  config/              配置加载与校验（TOML + .env → 校验过的 Settings）
  core/                核心能力，不依赖 CLI / Web
    liepin/            猎聘接口客户端（限速、错误码翻译、请求模型）
    storage/           SQLite：ORM 模型、仓储、轻量迁移
    services/          用例编排：search / detail / apply（带进度回调与取消）
    analysis/          赛道分类、技能词典、统计聚合
    report/            HTML 报告渲染 + insights 素材加载
    jd_parser.py       详情页 → 结构化 JD（纯函数）
    salary.py          薪资文本 → 年薪区间（万元）
  cli/                 typer 子命令
  web/                 FastAPI 管理后端 + 后台任务
frontend/              React（Vite）管理台，构建到 frontend/dist 由后端托管
scripts/               一次性分析脚本（改分类规则时用来核对）
tests/                 pytest（不碰真实库、不发网络请求）
data/                  jobs.db 与生成的报告
.claude/skills/
  job-init/            `/job-init`：交互式收集信息并填好 config/
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
job apply <jobId>... [--job-kind 1|2] [--yes]
job report [-o 输出路径] [--no-dedupe]
job stats [--tracks]
job web [--host H] [--port P] [--no-browser] [--skip-build]
job config init|show|path|validate
job db info|migrate|vacuum
```

全局选项：`--config` 指定配置文件、`--log-level`、`--quiet`、`--version`。

退出码：`2` 配置/鉴权问题、`3` 存储、`4` 报告、`5` 接口错误、`6` 触发限流。
脚本里可以据此判断「今天别再投了」。

`job apply` 默认会列出待投职位并要求确认（`--yes` 跳过）。投递结果（含「已投递过」
「职位已结束」）都会记进本地 `applications` 表——**猎聘没有查询投递记录的接口**，
这张表是唯一的账本。

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
