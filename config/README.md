# config/

**跟人无关**的那一半配置。随人而变的东西（简历、关键词、信号表、数据库）
不在这里，在 `profiles/<名字>/`——见仓库根的 README 与 CLAUDE.md。

| 文件 | 作用 | 进版本库 |
| --- | --- | --- |
| `config.example.toml` | 全局配置模板，带完整注释 | ✅ |
| `config.toml` | 你的全局配置（`job config init` 从模板生成）**，密钥也在里面** | ❌ |
| `templates/` | 新建 profile 的模板，`job profile new` 整份拷成 `profiles/<名字>/` | ✅ |
| `templates/profile.toml` | 搜索条件、搜索关键词、匹配门槛 | ✅ |
| `templates/resume.md` | 简历模板（带「怎么写才对得上市场词汇」的提示） | ✅ |
| `templates/preferences.md` | 求职偏好模板 | ✅ |

## 两个文件，段名不重叠

| 文件 | 段 |
| --- | --- |
| `config/config.toml` | `[profiles]`、`[liepin]`（含 `[liepin.accounts.*]`）、`[detail]`、`[agent]`（含 `.providers.*` / `.langsmith`）、`[web]`、`[logging]` |
| `profiles/<名>/profile.toml` | `[profile]`、`[search]`、`[storage]`、`[score]` |

段放错文件会**当场报错**，并直接告诉你它该在哪个文件里。不重叠是刻意的：
同一个段要是能出现在两处，下场一定是「改了一个忘了另一个」。

## 查找顺序

全局配置文件：

1. `--config` 命令行参数
2. `JOB_AGENT_CONFIG` 环境变量
3. `<项目根>/config/config.toml`
4. `<项目根>/config/config.example.toml`（未初始化时的兜底，保证开箱可跑）

用哪个 profile：

1. `--profile` / `-p` 命令行参数（带路径分隔符时当目录用）
2. `JOB_AGENT_PROFILE_NAME` 环境变量
   （**不是** `JOB_AGENT_PROFILE`——那个名字会被 pydantic-settings
   当成给 `[profile]` 整段赋 JSON 值，所以专门拦下来报错提示）
3. `config.toml` 里的 `[profiles].default`
4. `profiles/` 下**恰好**只有一个时就用它
5. 都不满足就报错列出候选。有多个又没说用哪个时绝不猜——猜错就是往别人的库里写数据

项目根目录从当前工作目录逐级向上查找 `config/` 得到，也可以用 `JOB_AGENT_HOME` 指定。

## 密钥

密钥（猎聘 token、模型 API key、LangSmith key）只写在 `config.toml` 里——
它整份不进版本库，没有 `.env`，profile 那一半也不存密钥。
字段的类型是 `SecretStr`，`job config show` 与 Web 的 `/api/config`
返回的都是 `**********`。

猎聘 token 放在 `[liepin.accounts.<账号名>]` 下，profile 用 `[profile].account`
指一个。几个人的账号可以长期并存，换人跑不用来回重贴 token：

```toml
# config/config.toml
[liepin.accounts.me]
user_token = "…"
[liepin.accounts.partner]
user_token = "…"
```

```toml
# profiles/web3/profile.toml
[profile]
account = "partner"
```

不想落盘的话，任意一项都能用 `JOB_AGENT_<节>__<字段>` 环境变量覆盖
（如 `JOB_AGENT_LIEPIN__ACCOUNTS__ME__USER_TOKEN=…`），环境变量优先级高于 TOML。
两个文件的段不重叠，所以一个变量只会落到其中一边。

不知道该填什么？在 Claude Code 里跑 `/job-init`，它会挨个问你并写进对应文件；
`job config init` 只生成全局骨架，`job profile new <名字>` 生成 profile 骨架。
