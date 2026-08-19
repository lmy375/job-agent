---
name: job-init
description: 交互式初始化 job-agent 的用户配置——收集猎聘 token、搜索条件与关键词分组，并引导用户写出 config/resume.md（简历）与 config/preferences.md（求职偏好）。当用户说「初始化 job-agent」「配置 job-agent」「帮我填简历 / 求职偏好」「job-init」，或在这个仓库里第一次准备采集职位、`job config validate` 报缺文件时使用。
---

# job-init

把空的 `config/` 变成能跑起来的配置。四件事，按顺序做：**token → 搜索条件 → 简历 → 求职偏好**。

前两件决定「能不能采到数据」，后两件决定「采到的数据有没有用」——
报告的「给我的建议」章节、挑岗位、准备面试问答，全部以简历与偏好为输入。
所以**不要只填 token 就收工**。

## 开场：先看现状，再动手

```bash
uv run job config path       # 各个文件应该在哪
uv run job config validate   # 缺什么
```

已经存在的文件**一律先 Read 再改**，用 Edit 精确改动对应字段，不要整份重写——
用户可能已经手写过内容。全程用中文与用户交流。

## 第 1 步：生成骨架

```bash
uv run job config init
```

它会从 `*.example.*` 模板补齐 `config.toml`、`.env`、`resume.md`、
`preferences.md`、`insights/`，已存在的自动跳过。

## 第 2 步：猎聘 token（写进 `config/.env`）

告诉用户去 <https://www.liepin.com/mcp/auth> 生成，然后把它填进 `config/.env` 的
`LIEPIN_USER_TOKEN=`。

**你自己不要接手 token**：不要让用户把 token 贴进对话，不要用 Bash 回显它，
不要写进 `config.toml`（那是要进版本库的）。用户填完让他说一声，你跑
`uv run job config validate` 确认。

如果用户坚持贴给你，直接用 Edit 写进 `config/.env` 并提醒他这条消息里有明文 token。

## 第 3 步：搜索条件（`config/config.toml` 的 `[search]`）

用 AskUserQuestion 一次问清四件事（选项见 `references/interview.md`）：

1. **城市**（`address`）
2. **薪资门槛**（`salary_kind` + `salary_floor`，单位是**元**，年薪 100 万 = `1000000`）
3. **学历 / 经验**要不要过滤（`edu_level` / `work_experience`，多数人留空）
4. **每个关键词翻几页**（`max_pages`，服务端硬上限 6 页 = 120 条）

**薪资门槛必须比目标包裹低一档**（低 20–30%）。原因：猎聘按薪资**区间重叠**过滤，
JD 标的是税前月薪 × 月数；门槛设成目标值会把大量实际能谈到位的岗位挡在外面。
把这个理由讲给用户，别默默替他调。

## 第 4 步：关键词分组（`[[search.groups]]`）

问用户「想投什么方向」，然后按赛道（AI / Web3/ 安全 / 后端）生成分组，
候选关键词清单见 `references/interview.md`。三条硬规则：

- **数组顺序 = 优先级**。因为按 jobId 去重，每条职位记到的 `searchKeyword` 是
  「最先命中它的方向」，它同时是分类兜底的依据——最想要的方向放最前面。
- **暂时不搜的方向写 `enabled = false` 保留下来**，不要删。库里存量职位的
  `searchKeyword` 可能来自它们，删掉之后这些职位查不到赛道，会整片掉进「其他」。
- 关键词要**具体**（「AI Agent」「大模型」），别用「工程师」这种词——
  单个关键词最多返回 120 条，太宽等于只看一个随机切片。

写完让用户确认：

```bash
uv run job search --dry-run
```

## 第 5 步：简历（`config/resume.md`）

先问来源，三种都要支持：

- **已有文件**：让用户给路径。PDF 用 `pdftotext -layout <文件> -` 转文本
  （没有这个命令就用 pdf skill），DOCX 用 docx skill。
- **直接粘贴**：用户贴进对话，你整理成 Markdown。
- **从零访谈**：按 `references/interview.md` 的简历问题清单一段段问。

统一整理成 `config/resume.md`，结构照 `config/resume.example.md`。整理时：

- **保留全部事实与数字**（漏洞数量、奖金金额、TVL、团队人数、职级、获奖）——
  这些是简历里最值钱的部分，不要为了排版丢掉。
- **不要替用户编造或美化**任何经历。信息缺失就留 `<待补>` 并告诉他缺什么。
- 每段经历检查是否写了 scope（带几人 / 多大规模 / 什么结果）；没有就问。

整理完做一次**市场词汇体检**（库里已有数据时才有意义）：

```bash
uv run python scripts/track_stats.py --top 12
```

把目标赛道的高频技能词和简历措辞比一遍，指出「你有这个能力但简历里没用市场的词」的地方。
这一步的产出通常比补技能更值钱。

## 第 6 步：求职偏好（`config/preferences.md`）

按 `references/interview.md` 的偏好问题清单问，**分 3–4 批**，别一次抛十几个问题。
模板见 `config/preferences.example.md`，覆盖：

硬约束（base 地、不看的岗位）· 期望岗位 · 期望薪资与构成 ·
看机会原因 · 职级与带人 · 绩效 · 到岗时间 · 基本信息（出生年月 / 性别 / 婚育）· 面试口径

问到敏感项（绩效、婚育、薪资构成）时，先说明用途：**只存在本地、不进版本库**，
用于生成报告建议和准备面试问答。用户不想答就写「未填」，**不要追问**。

薪资那一栏一定要问清 **税前还是税后、现金还是含期权**——两边搞混会差出 50%，
后面所有薪资对比都会错。

## 第 7 步：自检并交代下一步

```bash
uv run job config validate                    # 应当全部通过
uv run job search -k "<某个关键词>" --pages 1   # 用一次真实请求验证 token（可选，建议做）
```

然后告诉用户完整流程：`job search` → `job detail` → `job report` → `job web`，
并提醒：`config/` 下除 `*.example.*` 外都不进版本库（`.gitignore` 已配好）。

## 边界

- **绝不**把 token 写进 `config.toml`、回显到终端或写进提交。
- **绝不**替用户编造简历事实或求职偏好；不确定就问，或留空标注。
- 不要动 `data/`（那是他攒下来的职位库），不要跑 `job apply`（投递不可撤销）。
- 只改 `config/` 下的文件；要改代码或搜索逻辑，那是另一件事，先问用户。
