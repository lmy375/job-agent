"""LangGraph 独立执行路线。

仓库有两条执行路线，代码互不依赖（入口都是 ``job``，代码不是同一份）：

- ``cli/`` + ``web/``：交互式。CLI 由人或 skill（Claude Code）驱动，逐步跑、边看边判断。
- ``agent/``（本包）：无人值守。一条 ``job agent`` 命令跑完
  采集 → 分诊 → 逐条审读 JD → 出投递计划，投递前 interrupt 等人确认。

两条路线共享同一个确定性内核（``core/`` 与 ``config/``）：
采集、去重、打分、排序都是同一份代码，跑同一份数据得到同一个 shortlist。
LLM 只出现在判断节点里（读 JD 比硬门槛、写投递口径）。

langgraph 那几个依赖跟着主依赖一起装（``uv sync`` 就有，不是可选 extra）。
但本模块与 ``runner`` 都刻意不在顶层 import 它们：加载不快，而
``job search`` / ``job score`` 用不到——不该让每次敲 ``job`` 都等它们。
"""
