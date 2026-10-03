"""Remediation catalog + the post-approval LangGraph (pre-checks -> execute -> verify). All actions are SIMULATED."""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.health import evaluate_health
from app.config import LOW_CONFIDENCE_THRESHOLD

ACTIONS = {
    "rollback_deployment": {"risk": "medium", "steps": ["Identify previous stable version", "Roll back deployment", "Wait for pods ready"]},
    "increase_db_pool_and_restart": {"risk": "medium", "steps": ["Raise connection pool size", "Rolling restart of pods", "Wait for pods ready"]},
    "scale_cache_and_flush": {"risk": "high", "steps": ["Flush stale/oversized keys", "Scale cache memory", "Warm critical keys"]},
    "enable_circuit_breaker": {"risk": "low", "steps": ["Enable circuit breaker for the dependency", "Serve cached fallback", "Lower client timeouts"]},
    "rotate_certificate": {"risk": "medium", "steps": ["Issue new certificate", "Install certificate on endpoint", "Reload TLS config"]},
}
CATEGORY_ACTION = {
    "bad_deployment": "rollback_deployment",
    "db_pool_exhaustion": "increase_db_pool_and_restart",
    "cache_degradation": "scale_cache_and_flush",
    "upstream_dependency": "enable_circuit_breaker",
    "certificate_expiry": "rotate_certificate",
}


def plan_remediation(incident: dict, category: str, evidence: list) -> dict:
    action = CATEGORY_ACTION[category]
    plan = {"action": action, "risk": ACTIONS[action]["risk"], "target_service": incident["service"],
            "steps": ACTIONS[action]["steps"], "simulated": True}
    if action == "rollback_deployment":
        dep = next(e for e in evidence if e["id"] == "deployments")["details"]["suspect_deployments"]
        plan["rollback_to"] = dep[0]["previous_version"] if dep else None
    return plan


class RemState(TypedDict, total=False):
    investigation: dict
    approval: dict
    pre_checks: list
    execution: dict
    post_checks: list
    status: str


def build_remediation_graph(tools):
    async def pre_checks(state: RemState):
        inv, appr = state["investigation"], state["approval"]
        plan = inv["remediation_plan"]
        health = await tools.call("service_health", service=plan["target_service"], phase="current")
        checks = [
            {"name": "approval_recorded", "passed": bool(appr.get("approved") and appr.get("approver")),
             "detail": f"approved by {appr.get('approver')}"},
            {"name": "action_in_allowlist", "passed": plan["action"] in ACTIONS, "detail": plan["action"]},
            {"name": "service_known", "passed": health["found"], "detail": plan["target_service"]},
            {"name": "confidence_ok_or_acknowledged",
             "passed": inv["confidence"] >= LOW_CONFIDENCE_THRESHOLD or appr.get("acknowledge_low_confidence", False),
             "detail": f"confidence={inv['confidence']}"},
            {"name": "not_already_executed", "passed": not inv.get("remediation"), "detail": "no previous execution"},
        ]
        return {"pre_checks": checks}

    def route(state: RemState):
        return "execute" if all(c["passed"] for c in state["pre_checks"]) else "blocked"

    async def blocked(state: RemState):
        return {"status": "blocked"}

    async def execute(state: RemState):
        plan = state["investigation"]["remediation_plan"]
        return {"execution": {"simulated": True, "action": plan["action"],
                              "target_service": plan["target_service"], "steps_executed": plan["steps"]}}

    async def verify(state: RemState):
        plan = state["investigation"]["remediation_plan"]
        data = await tools.call("service_health", service=plan["target_service"], phase="post_remediation")
        m = data["metrics"]
        anomalies = evaluate_health(m)
        checks = [
            {"name": "no_active_anomalies", "passed": not anomalies,
             "detail": ", ".join(a["metric"] for a in anomalies) or "all metrics within thresholds"},
            {"name": "error_rate_below_1pct", "passed": m.get("error_rate_pct", 100) < 1, "detail": f"{m.get('error_rate_pct')}%"},
            {"name": "p95_latency_below_500ms", "passed": m.get("p95_latency_ms", 1e9) < 500, "detail": f"{m.get('p95_latency_ms')}ms"},
        ]
        ok = all(c["passed"] for c in checks)
        return {"post_checks": checks, "status": "resolved" if ok else "verification_failed"}

    g = StateGraph(RemState)
    g.add_node("pre_checks", pre_checks)
    g.add_node("execute", execute)
    g.add_node("verify", verify)
    g.add_node("blocked", blocked)
    g.add_edge(START, "pre_checks")
    g.add_conditional_edges("pre_checks", route, {"execute": "execute", "blocked": "blocked"})
    g.add_edge("execute", "verify")
    g.add_edge("verify", END)
    g.add_edge("blocked", END)
    return g.compile()
