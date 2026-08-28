# config/

用户自己的东西都在这里，代码不硬编码任何个人信息。

| 文件 | 作用 | 进版本库 |
| --- | --- | --- |
| `config.example.toml` | 配置模板，带完整注释 | ✅ |
| `config.toml` | 你的实际配置（`job config init` 从模板生成） | ❌ |
| `.env.example` | 密钥模板 | ✅ |
| `.env` | 猎聘 token | ❌ |
| `resume.example.md` | 简历模板（带「怎么写才对得上市场词汇」的提示） | ✅ |
| `resume.md` | 你的简历，报告的「简历建议」章节据此撰写 | ❌ |
| `preferences.example.md` | 求职偏好模板 | ✅ |
| `preferences.md` | 求职偏好：base 地、期望薪资与构成、不看的岗位、面试口径 | ❌ |
| `match.example.toml` | 匹配信号表模板（带完整注释与权重取法） | ✅ |
| `match.toml` | 你的信号表：决定 `job match` 的排序。正则用**单引号** | ❌ |
| `insights.example/` | 报告文案模板（`job config init` 从这里复制） | ✅ |
| `insights/*.html` | 报告里各赛道的定性结论（人工撰写的 HTML 片段） | ❌ |
| `insights/match-matrix.toml` | 能力项 × 市场需求 × 简历现状的匹配矩阵 | ❌ |

配置文件的查找顺序：

1. `--config` 命令行参数
2. `JOB_AGENT_CONFIG` 环境变量
3. `<项目根>/config/config.toml`
4. `<项目根>/config/config.example.toml`（未初始化时的兜底，保证开箱可跑）

项目根目录从当前工作目录逐级向上查找 `config/` 得到，也可以用 `JOB_AGENT_HOME` 指定。

不知道该填什么？在 Claude Code 里跑 `/job-init`，它会挨个问你并写进对应文件；
`job config init` 只负责从 `*.example.*` 生成骨架。
