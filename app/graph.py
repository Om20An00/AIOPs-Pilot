"""LangGraph investigation workflow.

START -> [logs | health | deployments | rag] (parallel fan-out) -> correlate -> rca -> plan -> approval_gate -> END
Evidence from the four agents is merged with an additive reducer, then correlated deterministically.
"""
import operator
import uuid
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.deployments import deployment_agent
from app.agents.health import health_agent
from app.agents.logs import logs_agent
from app.agents.rag import rag_agent
from app.agents.rca import correlate, needs_ack, rca_agent
from app.remediation import plan_remediation


class InvState(TypedDict, total=False):
    incident: dict
    trace_id: str
    evidence: Annotated[list, operator.add]
    hypotheses: list
    root_cause: dict
    confidence: float
    remediation_plan: dict
    status: str
    low_confidence: bool


def build_investigation_graph(tools):
    def node(agent):
        async def run(state: InvState):
            return {"evidence": [await agent(state["incident"], tools)]}
        return run

    async def correlate_node(state: InvState):
        return {"hypotheses": correlate(state["evidence"])}

    async def rca_node(state: InvState):
        rc = await rca_agent(state["incident"], state["evidence"], state["hypotheses"])
        return {"root_cause": rc, "confidence": rc.pop("confidence")}

    async def plan_node(state: InvState):
        return {"remediation_plan": plan_remediation(
            state["incident"], state["root_cause"]["category"], state["evidence"])}

    async def gate_node(state: InvState):
        # Approval gate: nothing is ever executed here. A human must call /approve.
        return {"status": "awaiting_approval", "low_confidence": needs_ack(state["confidence"])}

    g = StateGraph(InvState)
    for name, agent in [("logs_agent", logs_agent), ("health_agent", health_agent),
                        ("deployment_agent", deployment_agent), ("rag_agent", rag_agent)]:
        g.add_node(name, node(agent))
        g.add_edge(START, name)
    g.add_node("correlate", correlate_node)
    g.add_node("rca_agent", rca_node)
    g.add_node("plan_remediation", plan_node)
    g.add_node("approval_gate", gate_node)
    g.add_edge(["logs_agent", "health_agent", "deployment_agent", "rag_agent"], "correlate")
    g.add_edge("correlate", "rca_agent")
    g.add_edge("rca_agent", "plan_remediation")
    g.add_edge("plan_remediation", "approval_gate")
    g.add_edge("approval_gate", END)
    return g.compile()


def new_trace_id() -> str:
    return str(uuid.uuid4())
