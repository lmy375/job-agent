---
name: job-init
description: 交互式初始化 job-agent 的某个 profile——选定或新建 profile，收集猎聘 token、搜索条件与关键词分组，并引导用户写出简历与求职偏好。当用户说「初始化 job-agent」「配置 job-agent」「帮我填简历 / 求职偏好」「新建一个 profile」「job-init」，或在这个仓库里第一次准备采集职位、`job config validate` 报缺文件时使用。
---

# job-init

把一个空的 profile 变成能跑起来的配置。六件事，按顺序做：
**选 profile → token → 搜索条件 → 简历 → 求职偏好 → 匹配信号表**。

前三件决定「能不能采到数据」，后三件决定「采到的数据有没有用」——
报告的「给我的建议」章节、`job match` 的排序、准备面试问答，
全部以简历、偏好与信号表为输入。所以**不要只填 token 就收工**。

## 配置在哪：两个文件，别放错

| 写什么 | 写进哪 |
| --- | --- |
| 猎聘 token、模型 key、限速、Web 端口 | 全局 `config/config.toml`（跟人无关，所有 profile 共享） |
| 简历、求职偏好、搜索条件、关键词、信号表 | 当前 profile 的目录（随人而变） |

段名不重叠，放错了会当场报错。**路径一律问 CLI，不要按记忆拼**：

```bash
uv run job -p <名字> config path --json
```

它输出 `profileDir` / `resume` / `preferences` / `match` / `database` 等绝对路径。
后面每一步要写文件时都用这里给出的路径。

## 开场：先确定用哪个 profile

一个 profile = **一个人，或者一种求职场景**（「AI 应用工程」和「Web3 安全」
可以是两个 profile）。简历、关键词、信号表、数据库全在它自己的目录里，互不可见。

```bash
uv run job profile list      # 已有哪些、哪个是默认、各自多少条数据
```

- **一个都没有** → 问用户这次求职的方向 / 是给谁用的，用那个起名，
  `uv run job profile new <名字>`（名字只能用字母、数字、`-`、`_`）。
  第一个 profile 会自动成为默认。
- **已有 profile** → 问用户是接着完善哪一个，还是**另开一个新方向**。
  别默认往已有的里面写：那可能是别人的、或者另一条线的配置。

选定之后，**后面所有命令都带上 `-p <名字>`**，别依赖默认值。

```bash
uv run job -p <名字> config path --json   # 各个文件在哪
uv run job -p <名字> config validate      # 缺什么
```

已经存在的文件**一律先 Read 再改**，用 Edit 精确改动对应字段，不要整份重写——
用户可能已经手写过内容。全程用中文与用户交流。

## 第 1 步：生成骨架

```bash
uv run job config init            # 全局配置（只在第一次需要）
uv run job profile new <名字>      # profile 骨架：profile.toml、resume.md、
                                  # preferences.md、match.toml、insights/、data/
```

两个命令都不会覆盖已存在的东西。

## 第 2 步：猎聘 token（全局 `config/config.toml` 的 `[liepin.accounts.*]`）

告诉用户去 <https://www.liepin.com/mcp/auth> 生成，然后填进
`config/config.toml` 里 `[liepin.accounts.<账号名>]` 下的 `user_token = ""`。
**密钥只有这一处落盘**——它整份不进版本库，没有 `.env`，profile 目录里也不存密钥。

账号名自己起。如果这个 profile 是**另一个人**，就新加一段
`[liepin.accounts.<那个人>]`，再把 profile 的 `[profile].account` 改成指向它——
几个人的 token 可以长期并存，不用每次换人重贴。同一个人的不同方向共用一个账号即可。

**你自己不要接手 token**：不要让用户把 token 贴进对话，不要用 Bash 回显它
（`job config show` 打出来的是 `**********`，不是明文）。用户填完让他说一声，
你跑 `uv run job -p <名字> config validate` 确认。

如果用户坚持贴给你，直接用 Edit 写进 `config/config.toml` 并提醒他这条消息里有明文 token。

## 第 3 步：搜索条件（profile 的 `profile.toml` 的 `[search]`）

用 AskUserQuestion 一次问清四件事（选项见 `references/interview.md`）：

1. **城市**（`address`）
2. **薪资门槛**（`salary_kind` + `salary_floor`，单位是**元**，年薪 100 万 = `1000000`）
3. **学历 / 经验**要不要过滤（`edu_level` / `work_experience`，多数人留空）
4. **每个关键词翻几页**（`max_pages`，服务端硬上限 6 页 = 120 条）

**薪资门槛必须比目标包裹低一档**（低 20–30%）。原因：猎聘按薪资**区间重叠**过滤，
门槛设成目标值会把大量实际能谈到位的岗位挡在外面。
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

## 第 5 步：简历（profile 目录下的 `resume.md`）

先问来源，三种都要支持：

- **已有文件**：让用户给路径，然后用内置命令抽文本（PDF / DOCX / TXT 都支持）：

  ```bash
  uv run job resume import ~/Downloads/我的简历.pdf
  ```

  它只抽纯文本、不写文件——整理成结构化 Markdown 是你的工作。
  报「扫描件」之类的错就改用 pdf skill 先 OCR。
- **直接粘贴**：用户贴进对话，你整理成 Markdown。
- **从零访谈**：按 `references/interview.md` 的简历问题清单一段段问。

统一整理成 profile 目录下的 `resume.md`（路径见 `config path --json` 的 `resume`），
结构照 `config/templates/resume.md`。整理时：

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

## 第 6 步：求职偏好（profile 目录下的 `preferences.md`）

按 `references/interview.md` 的偏好问题清单问，**分 3–4 批**，别一次抛十几个问题。
模板见 `config/templates/preferences.md`，覆盖：

硬约束（base 地、不看的岗位）· 期望岗位 · 期望薪资与构成 ·
看机会原因 · 职级与带人 · 绩效 · 到岗时间 · 基本信息（出生年月 / 性别 / 婚育）· 面试口径

问到敏感项（绩效、婚育、薪资构成）时，先说明用途：**只存在本地、不进版本库**，
用于生成报告建议和准备面试问答。用户不想答就写「未填」，**不要追问**。

薪资那一栏**统一按税前填写**（JD 标的就是税前，本项目不做税后换算）。
用户如果报的是税后数字，让他换成税前再填，别替他换算。另外问清现金与期权的构成。

## 第 7 步：匹配信号表（profile 目录下的 `match.toml`）

**这一步别跳过。** 缺了它 `job match` / `job shortlist` 跑不了，
用户就只能停在「一堆数据」而到不了「该投哪几个岗」。

模板里那份是给「AI 应用 / Agent 工程方向」写的。**先判断它对不对得上这个用户**——
方向不同就整份重写，不要微调。原料其实已经在前两步里了：

| 信号表里的 | 从哪来 |
| --- | --- |
| `[require].pattern` | 用户说的目标方向（第 4 步的关键词分组） |
| 正信号（weight > 0） | `resume.md` 里真实做过的技术栈 + 想做的方向 |
| 负信号（weight < 0） | `preferences.md` 的「不看的岗位」 |

三条硬规则：

- **正则一律用单引号**（TOML 字面量字符串）：`pattern = '\bagent\b'`。
  双引号里 `\b` 是 TOML 的「退格符」转义，会静默变成 `<退格>agent<退格>`——
  正则编译得过、一条也匹配不上、排名看着正常但全错。
  （`job config validate` 会拦，但别依赖它。）
- **负信号要显式写**，不能指望 `[require]` 兜。不想要的方向往往同时带强正信号
  （「大模型预训练」里有「大模型」），不扣分会排到很前面。
- **权重标准**：命中这条我会不会想点开看看。10 = 看到就想投，
  6–8 = 明显加分，3–5 = 技术栈对得上，1–2 = 有点关系。

顺手把 `[match]` 的 `salary_floor_wan` 定下来（万元/年，**税前**）：
它比目标包裹低一档，理由同第 3 步。

写完验证一遍——这一步能立刻看出信号表准不准：

```bash
uv run job -p <名字> config validate
uv run job -p <名字> match --top 15 --why      # 库里已有数据时
```

## 第 8 步：自检并交代下一步

```bash
uv run job -p <名字> config validate                    # 应当全部通过
uv run job -p <名字> search -k "<某个关键词>" --pages 1   # 真实请求验证 token（可选，建议做）
```

然后告诉用户完整流程：

```
job search → job detail → job match → job shortlist → /job-match → job apply
                       ↘ job report / job web （看市场大盘）
```

前四步是确定性的（可重跑、两次一样），`/job-match` 那一步是判断（读 JD 挑岗位）。
每条命令都能加 `-p <名字>`；这个 profile 是默认的话可以省。

并提醒：`config/config.toml` 与整个 `profiles/` 都不进版本库（`.gitignore` 已配好），
所以简历和 token 不会被误提交；想再开一条求职线就是 `job profile new <另一个名字>`。

## 边界

- **绝不**把 token 写进 `config.toml`、回显到终端或写进提交。
- **绝不**替用户编造简历事实或求职偏好；不确定就问，或留空标注。
- 不要动 profile 里的 `data/`（那是他攒下来的职位库），不要跑 `job apply`（投递不可撤销）。
- **只改当前 profile 目录下的文件，外加全局 `config/config.toml` 的密钥段。**
  别去动别的 profile——那可能是另一个人的东西。
  要改代码或搜索逻辑，那是另一件事，先问用户。
- 信号表里**不要替用户塞他没说过的取向**。他没提「不看外包」就不要加这条负信号。
