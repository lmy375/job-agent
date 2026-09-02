"""组图。

固定边为主：采集 → 分诊 → 审读 → 计划的顺序本来就是确定的，
不做「让模型自己决定下一步」的自由 agent——那只会引入不可复现性。
LLM 的活全部在节点内部（见 nodes.py）。

```
START → profile → collect → triage ─┬─(Send 扇出)→ review ─┐
                                    └─（shortlist 为空）────┼→ plan ─┬→ confirm → apply → END
                                                            │        └→ END（默认：不投递）
```
"""

from __future__ import annotations

from typing import Any, cast

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from job_agent.agent.nodes import GraphNodes
from job_agent.agent.state import AgentState, ReviewInput
from job_agent.context import AppContext


def state_serde() -> JsonPlusSerializer:
    """checkpoint 序列化器：显式注册 state.py 里的全部 pydantic 模型。

    langgraph 未来版本会拒绝反序列化未注册的自定义类型；
    自动收集整个模块，新增模型不会被漏掉。
    """
    from job_agent.agent import state as state_module

    allowed = [
        (state_module.__name__, name)
        for name, obj in vars(state_module).items()
        if isinstance(obj, type)
        and issubclass(obj, BaseModel)
        and obj.__module__ == state_module.__name__
    ]
    return JsonPlusSerializer(allowed_msgpack_modules=allowed)


def build_graph(ctx: AppContext, llm: Any, checkpointer: Any = None) -> Any:
    """编译图。``llm`` 与 ``checkpointer`` 由入口注入，方便测试替身。"""
    nodes = GraphNodes(ctx, llm)
    graph = StateGraph(AgentState)

    graph.add_node("profile", nodes.profile)
    graph.add_node("collect", nodes.collect)
    graph.add_node("triage", nodes.triage)
    # Send 扇出节点的输入是 ReviewInput 而非主状态，显式声明让 langgraph 校验载荷
    graph.add_node("review", cast(Any, nodes.review), input_schema=ReviewInput)
    graph.add_node("plan", nodes.plan)
    graph.add_node("confirm", nodes.confirm)
    graph.add_node("apply", nodes.apply)

    graph.add_edge(START, "profile")
    graph.add_edge("profile", "collect")
    graph.add_edge("collect", "triage")
    graph.add_conditional_edges("triage", nodes.dispatch, ["review", "plan"])
    graph.add_edge("review", "plan")
    graph.add_conditional_edges("plan", nodes.apply_gate, {"confirm": "confirm", END: END})
    graph.add_edge("confirm", "apply")
    graph.add_edge("apply", END)

    return graph.compile(checkpointer=checkpointer)
