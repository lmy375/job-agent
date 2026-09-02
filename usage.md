# usage：四条使用路径怎么选、怎么用

这个仓库有四个入口——**skill、CLI、agent、Web**。它们不是四个功能，
而是同一套内核的四种驱动方式：数据库是同一个，配置是同一份，
`job match` 和 `job-agent` 对同一批岗位给出同一个排序。

区别只在**谁来做判断、判断发生在什么时候**：

| 路径 | 谁在开车 | 判断发生在 | 一句话 |
| --- | --- | --- | --- |
| **CLI** `job …` | 你（或 skill / 脚本） | 不判断，只出确定性结果 | 骨架。所有别的路径都在调它或它调的东西 |
| **skill** `/job-init`、`/job-match` | Claude 和你一起 | **对话里**，你能当场反驳 | 要深聊、要改口径时用这条 |
| **agent** `job-agent` | LangGraph 管线 | **跑的过程中**，事后看 `agent-plan.md` | 一条命令跑完，无人值守 |
| **Web** `job web` | 你点鼠标 | 不判断，只看和投 | 看大盘、翻 JD、点投递 |

> **先记住一件事**：所有路径都按 **profile** 隔离，一个 profile = 一个人 / 一种求职场景。
> 有两个及以上 profile 时，每条命令都带 `-p <名字>`，别依赖默认值——
> 挑错 profile 就是拿 A 的简历去比 B 的岗位。
>
> ```bash
> uv run job profile list
> ```

---

## 我该用哪条路

按你现在处于求职的哪一步选：

```
还没配置过                    → /job-init（skill）
想采数据 / 重跑一遍           → job search、job detail（CLI）
采完了，想知道该投哪几个       → /job-match（skill）  ← 首选
    ├ 想让它自己跑完不用陪    → job-agent（agent）
    └ 想自己一条条翻着看      → job web（Web）
想看这个方向的市场大盘         → job report / job web（CLI / Web）
真要投了                      → job apply（CLI）或 Web 上点，或 job-agent --apply
```

一句话版本：**配置和挑岗位走 skill，采集和投递走 CLI，浏览走 Web，
不想陪着的时候走 agent。**

---

## 路径一：CLI（`job …`）——一切的骨架

### 它负责什么

**只负责有唯一正确答案的事**：采集、限流退避、去重、JD 解析、薪资换算、
按信号表打分排序、渲染报告。同一个库跑两次，结论必须一模一样。

反过来说，**CLI 刻意不下结论**。`job shortlist` 生成的清单里，
「硬门槛核对 / 投不投 / 投递口径」三处留白写着 `<待 /job-match 填写>`——
不是没做完，是故意的：填一段模板话术，人会误以为已经分析过了，比留空更糟。

### 推荐用法

日常就这一条链：

```bash
uv run job search        # 按 profile.toml 的关键词批量搜，按 jobId 去重
uv run job detail        # 抓详情页 JD（串行 + 随机休眠，急不得）
uv run job match --top 30 --why    # 打分排序，--why 展开命中与扣分理由
uv run job shortlist --limit 12    # 写出候选清单骨架
```

首次使用多两步：

```bash
uv run job config init         # 生成全局 config/config.toml（密钥填这里）
uv run job profile new me      # 建 profile（简历、关键词、库都在它自己的目录）
```

### 几条实践建议

- **`job detail` 慢是正常的，别调快。** 服务端实测约 10 次 / 60s 滑动窗口，
  触发后冷却 20 分钟以上且失败是静默的。限流按 token 记账，换 IP 无效。
  进度直接落库，中断后重跑自动跳过已完成项——所以放着跑就行。
- **`job match --why` 是用来体检信号表的，不是用来看排名的。**
  扫一遍命中理由：该进的没进 → 缺正信号；不该进的排很高 → 缺负信号。
  发现问题**改 profile 的 `match.toml` 再重跑**，别在脑子里手工纠偏——
  手工纠偏这次能用，下次跑又是老样子。
- **`match.toml` 里的正则一律用单引号**（TOML 字面量字符串）。
  双引号里 `\b` 是退格符转义，`"\bagent\b"` 会静默变成匹配不上任何东西的正则。
  `job config validate` 会拦，但别指望它。
- **别在别处硬编码路径。** 路径随 profile 变，一律问：

  ```bash
  uv run job config path --json    # 简历、信号表、数据库…的绝对路径
  ```

- **脚本里用退出码判断**：`2` 配置/鉴权、`3` 存储、`4` 报告、`5` 接口/简历抽取、
  `6` 触发限流。看到 `6` 就该今天收工了。

### 不要用 CLI 做的事

写一次性打分脚本。要改排序就改 `match.toml`——那才能跨会话复用；
脚本用完就丢，第二次跑得到的是一份不可比的新结论，等于没有系统。

---

## 路径二：skill（`/job-init`、`/job-match`）——需要读懂文字的那半

在 Claude Code 里对 Claude 说 `/job-init` 或 `/job-match` 即可触发。
这两个 skill 承担 CLI 穷举不出来的部分：**读懂文字之后才能下的判断**。

### `/job-init`：把空 profile 变成能跑起来的配置

推荐**所有人第一次都走这条**，不要手填。它按六步访谈：
选 profile → token → 搜索条件 → 简历 → 求职偏好 → 匹配信号表，
写完自己跑 `job config validate` + `job search --dry-run` 自检。

几个刻意的设计，用之前知道一下：

- **token 不进对话**。它会让你自己填进 `config/config.toml`，填完说一声，
  它跑 validate 确认。`job config show` 打出来的是 `**********`。
- **已有文件先读再改**，用 Edit 精确改字段，不整份重写——你手写过的内容不会丢。
- **简历三种来源**：粘贴 / 指向已有文件（PDF 自动转文本）/ 从零访谈。
- **不替你编造事实**。信息缺失就留 `<待补>` 并告诉你缺什么。

> 别只填 token 就收工。简历、偏好、信号表决定了「采到的数据有没有用」——
> `job match` 的排序、报告的建议章节、面试准备，全部以它们为输入。

### `/job-match`：挑出该投的几个岗

**采完数据之后的默认下一步**，也是四条路径里最该常用的一条。
它做 CLI 做不了的事：逐条读 JD 比硬门槛、判断投不投、排优先级、写投递口径，
把 `job shortlist` 留白的三处填掉。

典型对话：

```
你：/job-match
Claude：（确认 profile → 跑 match --why → 读简历与偏好 → 逐条读 JD → 填清单 → 给结论）
你：第 3 条那个管理规模的判断我不同意，我实线 5 人但虚线带过 20 人
Claude：（修正硬门槛核对，重排优先级）
```

**这条路径的价值就在这个来回。** 你能当场反驳它的判断，它能当场改；
换成 agent 路线，你只能事后看着 `agent-plan.md` 摇头。

用它的时候注意：

- **它不投递。** `job apply` 不可撤销，除非你明确要求，skill 绝不会跑。
- **它把判断写进 `data/shortlist.md`**，不碰 `resume.md` / `preferences.md` /
  `match.toml`——那三个是你的输入，不是它的产出。
- **一份健康的清单里「不投」应该占不小比例。** 12 条全判「投」说明它没在判断，
  这时候该追问它每条的理由。
- 排序不对就让它改 `match.toml`，别接受「我在分析里帮你调整了」这种回答。

---

## 路径三：agent（`job-agent`）——同一条流程的无人值守版

`/job-match` 是交互式的，你得陪着。`job-agent` 是 LangGraph 组的固定管线：
一条命令跑完 **采集 → 分诊 → 逐岗审读 → 投递计划**，共享同一个数据库和同一份配置。

### 前置

依赖是可选的，不装不影响 `job` 与 `job web`：

```bash
uv sync --extra agent
# 再在 config/config.toml 的 [agent.providers.*] 里填 api_key（审读节点要调模型）
```

### 推荐用法

```bash
uv run job-agent                      # 用库内已有数据：分诊 → 审读 → data/agent-plan.md
uv run job-agent --collect            # 连采集一起：search + detail 再走上面
uv run job-agent --top 15             # 送审岗位数上限（按条计费，这是成本闸门）
uv run job-agent --provider deepseek  # 换模型：用 [agent.providers.deepseek]
uv run job-agent --thread run-x       # 中断后用同一 thread 从 checkpoint 续跑
uv run job-agent --apply              # 出完计划后进入投递确认（终端里逐条拍板）
```

最典型的场景是**挂着跑**：晚上 `job-agent --collect`，第二天早上看
`<profile>/data/agent-plan.md`。

### 必须知道的四件事

- **投递前必经 interrupt。** `--apply` 只是打开闸门，真正投哪几个要在终端里
  逐条输入 job_id 确认；不传 `--apply` 时流程在写完计划后就结束。
- **LLM 只出现在审读节点。** 采集、去重、打分、排序、计划渲染全是共享内核里的
  确定性代码——所以 `job match` 和 `job-agent` 对同一份数据给出同一个 shortlist，
  两条路线的差异只在「读 JD 之后怎么判」。
- **模型是配置不是代码。** 一张 `[agent.providers.*]` 表就是一个接入点，
  客户端只有 `api = "anthropic"` 和 `api = "openai"` 两类；DeepSeek、Kimi、通义、
  GLM、OpenRouter、本地 vLLM 全兼容后者，区别只是 `base_url`。加一家是抄一段配置。
- **唯一的坑是 `structured_output`。** 审读裁决必须符合固定 schema，
  官方端点留 `"auto"`；兼容端点报「不支持 json_schema / response_format」时，
  依次试 `"function_calling"` 和 `"json_mode"`。

模型标识（`provider / model`）会写进计划头部——事后回看才分得清
「优先级变了」是 JD 变了还是换了模型。想要可比的结论就别用
`openrouter/free` 那种随机路由器。

### 什么时候别用 agent

**第一次挑岗位别用。** 头一轮你的 `match.toml` 和 `preferences.md` 大概率还不准，
需要在对话里来回校准——那是 `/job-match` 的主场。等口径稳定了、
你只是想定期扫一遍新岗位，再换到 agent。

---

## 路径四：Web（`job web`）——看和投

```bash
uv run job web                    # 默认 http://127.0.0.1:18000
uv run job web --no-browser --skip-build   # 只起 API（前端不构建）
```

三个页面：

- **职位**：分页、按方向 / 薪资 / 有无 JD / 是否投递筛选，展开看 JD 全文，
  一键投递（有二次确认）
- **采集任务**：页面上发起搜索 / 抓详情 / 生成报告，实时看进度与日志，可取消
- **数据概览**：库内统计、赛道分布、当前配置与路径

API 文档在 `/docs`。前端开发：`cd frontend && npm run dev`（5173，`/api` 自动代理）。

### 它最适合的两件事

1. **翻 JD**。终端里读长文本不舒服，网页上展开看快得多。
2. **看大盘**。「我这个方向占市场多少」这类事实决定了策略是精投还是海投，
   和 `job report` 生成的 HTML 报告配合看。

### 三条约束

- **后台任务只有一个 worker**，采集任务会排队。这是刻意的：猎聘限流按 token 记账，
  并行只会更快被封；SQLite 的写也不适合并发。
- **取消是协作式的**。服务在当前条目结束后才停，已完成的进度都已落库——
  点了取消不会立刻停，别连点。
- **配置在 Web 端只读**。改配置去改文件：文件能进版本库、能 diff，
  也不会出现「网页上改了但下次 CLI 跑的是另一套」。

---

## 四条路径怎么配合

一次完整的求职，推荐的走法：

```
第 1 天   /job-init                       建 profile、填简历与偏好与信号表
          job search → job detail         采一批数据（detail 慢，挂着跑）
          job report / job web            先看大盘，决定精投还是海投

第 2 天   /job-match                      逐条读 JD、排优先级、写口径
                                          ↑ 这一步会顺手校准 match.toml
          job apply <id>...               或在 Web 上点投递

之后      job-agent --collect             口径稳定后，定期无人值守扫新岗
          job web                         翻新出现的 JD
```

会重复的只有最后两行。**前两天的产出（`match.toml`、`resume.md`、
`preferences.md`）是可以跨会话复用的资产**——求职是低频行为，
如果每次都从零现算，第二次得到的是一份不可比的新结论，等于没有系统。

---

## 换个人 / 换个方向

同一台机器上同时跑「AI 应用工程」和「Web3 安全」，或者帮另一个人跑一遍：

```bash
uv run job profile new web3       # 从 config/templates/ 拷一份骨架
uv run job -p web3 search         # 只往 web3 的库里写
uv run job profile use web3       # 设为默认，之后不用每次带 -p
```

在 Claude Code 里跑 `/job-init` 时告诉它「新开一个 web3 方向」即可。

- **换人只需要换 profile，不该改代码。** 「AI Agent 是好岗位」这类个人取向
  一旦出现在 `src/` 里就是 bug——它属于 `match.toml`。
  做算法的人把「预训练」那条从 `-12` 改成 `+12` 就行。
- **猎聘 token 仍然只有全局一处落盘**：住 `[liepin.accounts.<名字>]`，
  profile 用 `[profile].account` 指一个。几个人的 token 可以长期并存。
- **删一个 profile 就是删它的文件夹**。刻意不提供 `job profile rm`——
  那一下会连着简历和几百条采集记录一起没。

---

## 常见问题

**采完了但 `job match` 一条都排不上来？**
多半是 `[require].pattern` 写窄了，或 `match.salary_floor_wan` 门槛太高。
跑 `job match --why` 看扣分理由。注意薪资门槛过滤的是 JD 区间的**上限**
（那才代表「这家最多给到多少」），不是下限。

**报告里一大片职位掉进「其他」？**
不再搜索的关键词请保留在 `profile.toml` 里并设 `enabled = false`，
别直接删——每条职位的赛道兜底依据就是「最先命中它的那个关键词」，
关键词没了这些存量数据就查不到赛道了。

**改了数据库结构 / 接口字段？**
`job reset` 删库重建，重采一遍。这个项目**不做迁移也不做向后兼容**：
单人工具，数据随时能重新采集，为「万一有老库」写的兼容代码只会一直留在仓库里没人敢删。

**想改配置但不想让密钥落盘？**
任意配置项都能用环境变量覆盖，密钥也不例外：

```bash
export JOB_AGENT_LIEPIN__ACCOUNTS__DEFAULT__USER_TOKEN=…
export JOB_AGENT_AGENT__PROVIDERS__DEEPSEEK__API_KEY=…
```

两个配置文件的段名不重叠，所以一个变量只可能落到其中一边，没有歧义。
（选 profile 的环境变量叫 `JOB_AGENT_PROFILE_NAME`，不是 `JOB_AGENT_PROFILE`——
后者会被 pydantic-settings 当成给 `[profile]` 整段赋 JSON 值。）
