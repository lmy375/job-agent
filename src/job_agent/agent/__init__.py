"""LangGraph 独立执行路线。

仓库有两条执行路线，代码互不依赖：

- ``cli/`` + ``web/``：交互式。CLI 由人或 skill（Claude Code）驱动，逐步跑、边看边判断。
- ``agent/``（本包）：无人值守。一条 ``job-agent`` 命令跑完
  采集 → 分诊 → 逐条审读 JD → 出投递计划，投递前 interrupt 等人确认。

两条路线共享同一个确定性内核（``core/`` 与 ``config/``）：
采集、去重、打分、排序都是同一份代码，跑同一份数据得到同一个 shortlist。
LLM 只出现在判断节点里（读 JD 比硬门槛、写投递口径）。

依赖上，本包需要 ``agent`` extra（``uv sync --extra agent``）。
本模块刻意不在顶层 import langgraph——没装 extra 时，
``import job_agent.agent`` 也不能炸（比如边界测试要扫这个包）。
"""
