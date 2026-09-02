# scripts/

一次性的分析与维护脚本。它们**不属于产品功能**：产品功能在 `job` 命令与 Web 管理台里，
这里放的是「改分类规则时用来核对」「临时想看某个切片」这类工作用具。

跑法（都从项目根目录执行）：

```bash
uv run python scripts/audit_classification.py --track 安全
uv run python scripts/track_stats.py
uv run python scripts/salary_percentiles.py
uv run python scripts/keyword_coverage.py
uv run python scripts/export_jobs.py --format csv -o jobs.csv
```

每个脚本都接 `--profile / -p <名字>` 指定看哪个 profile 的库，不带就是默认那个
（`job profile list` 看有哪些）。

| 脚本 | 用途 |
| --- | --- |
| `keyword_coverage.py` | 每个搜索关键词的产出、去重损耗、是否撞到 120 条上限 |
| `export_jobs.py` | 导出 CSV / JSON（丢给 Excel 或别的工具用） |

写新脚本时的约定：只调 `job_agent.core` 的公开接口，不要重复实现统计逻辑——
一旦口径分叉，两边的数字就再也对不上了。
