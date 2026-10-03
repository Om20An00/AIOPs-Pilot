"""Unit/integration tests that need NO database, model or API key.
MCP tools are replaced by a fake that reads the same JSON data; the RAG tool returns canned matches.
Run: pytest -q
"""
import asyncio
import json

import pytest

from app import llm
from app.agents import rca
from app.agents.health import evaluate_health
from app.config import DATA_DIR
from app.graph import build_investigation_graph
from app.remediation import build_remediation_graph
from app.rules import classify_log_line

INCIDENTS = {i["id"]: i for i in json.loads((DATA_DIR / "incidents.json").read_text())}
LOGS = json.loads((DATA_DIR / "logs.json").read_text())
HEALTH = json.loads((DATA_DIR / "health.json").read_text())
DEPLOYS = json.loads((DATA_DIR / "deployments.json").read_text())
EXPECTED = {"INC-1001": "db_pool_exhaustion", "INC-1002": "bad_deployment", "INC-1003": "cache_degradation",
            "INC-1004": "upstream_dependency", "INC-1005": "certificate_expiry"}


class FakeTools:
    def __init__(self, rag_category="db_pool_exhaustion", rag_similarity=0.6):
        self.rag = {"matches": [{"id": "PI-X", "title": "t", "category": rag_category, "root_cause": "",
                                 "resolution": "", "action": "", "similarity": rag_similarity}]}

    async def call(self, name, **kw):
        if name == "search_logs":
            return {"lines": [l for l in LOGS[kw["incident_id"]] if l["level"] in ("WARN", "ERROR")]}
        if name == "service_health":
            m = HEALTH.get(kw["service"], {}).get(kw.get("phase", "current"))
            return {"found": m is not None, "metrics": m or {}}
        if name == "recent_deployments":
            from datetime import datetime, timedelta
            end = datetime.fromisoformat(kw["before"].replace("Z", "+00:00"))
            ds = [d for d in DEPLOYS.get(kw["service"], [])
                  if end - timedelta(hours=kw["hours"]) <= datetime.fromisoformat(d["deployed_at"].replace("Z", "+00:00")) <= end]
            return {"deployments": ds, "all_versions": [d["version"] for d in DEPLOYS.get(kw["service"], [])]}
        if name == "search_similar_incidents":
            return self.rag
        raise KeyError(name)


def investigate(incident_id, tools=None, cat=None):
    graph = build_investigation_graph(tools or FakeTools(cat or EXPECTED[incident_id]))
    return asyncio.run(graph.ainvoke({"incident": INCIDENTS[incident_id], "trace_id": "t", "evidence": []}))


def test_log_classification():
    assert classify_log_line("HikariPool-1 - Connection is not available") == "db_pool_exhaustion"
    assert classify_log_line("java.lang.NullPointerException at X") == "bad_deployment"
    assert classify_log_line("SSL handshake failed: certificate has expired") == "certificate_expiry"
    assert classify_log_line("Redis command timed out") == "cache_degradation"   # not misread as upstream
    assert classify_log_line("all good") is None


def test_health_anomalies():
    names = {a["metric"] for a in evaluate_health(HEALTH["order-service"]["current"])}
    assert "db_pool_utilization_pct" in names
    assert evaluate_health(HEALTH["order-service"]["post_remediation"]) == []


@pytest.mark.parametrize("incident_id,expected", EXPECTED.items())
def test_root_cause_per_incident(incident_id, expected):
    s = investigate(incident_id)
    assert s["root_cause"]["category"] == expected
    assert {e["id"] for e in s["evidence"]} == {"logs", "health", "deployments", "rag"}
    assert s["status"] == "awaiting_approval"          # approval gate: never auto-executes
    assert 0 < s["confidence"] <= 1


def test_deployment_correlation_and_rollback_target():
    s = investigate("INC-1002")
    assert s["remediation_plan"]["action"] == "rollback_deployment"
    assert s["remediation_plan"]["rollback_to"] == "v3.2.0"
    # deployment is flagged as contributing factor for pool exhaustion after a release
    assert "v2.14.0" in investigate("INC-1001")["root_cause"]["contributing_factors"][0]


def test_confidence_drops_when_rag_disagrees_and_flags_low_confidence():
    strong = investigate("INC-1004")["confidence"]
    weak_tools = FakeTools(rag_category="bad_deployment", rag_similarity=0.25)
    weak = investigate("INC-1004", tools=weak_tools)
    assert weak["confidence"] < strong


def test_llm_disagreement_lowers_confidence_but_keeps_evidence_based_category(monkeypatch):
    async def fake_reason(incident, evidence, hypotheses):
        return {"category": "bad_deployment", "summary": "x", "contributing_factors": [], "cited_evidence": ["logs"]}
    monkeypatch.setattr(rca, "llm_enabled", lambda: True)
    monkeypatch.setattr(rca, "reason_root_cause", fake_reason)
    s = investigate("INC-1003")
    assert s["root_cause"]["llm_used"] and s["root_cause"]["llm_agrees"] is False
    assert s["root_cause"]["category"] == "cache_degradation"


def test_llm_output_validation(monkeypatch):
    """Invalid LLM output (category outside candidates) must be rejected -> None -> deterministic fallback."""
    import types, sys
    class Msg: content = json.dumps({"root_cause_category": "made_up", "summary": "s", "cited_evidence": []})
    class Resp: choices = [types.SimpleNamespace(message=Msg)]
    class FakeGroq:
        def __init__(self, api_key): 
            self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))
        async def _create(self, **kw): return Resp
    monkeypatch.setitem(sys.modules, "groq", types.SimpleNamespace(AsyncGroq=FakeGroq))
    monkeypatch.setattr(llm, "GROQ_API_KEY", "test")
    ev = [{"id": "logs", "source": "logs", "summary": "s", "details": {}, "votes": {}}]
    hyp = [{"category": "db_pool_exhaustion"}, {"category": "bad_deployment"}]
    out = asyncio.run(llm.reason_root_cause(INCIDENTS["INC-1001"], ev, hyp))
    assert out is None


def remediate(incident_id, approved=True, ack=False, inv_mutator=None):
    inv = investigate(incident_id)
    if inv_mutator:
        inv_mutator(inv)
    graph = build_remediation_graph(FakeTools())
    appr = {"approved": approved, "approver": "om" if approved else "", "acknowledge_low_confidence": ack}
    return asyncio.run(graph.ainvoke({"investigation": inv, "approval": appr}))


def test_remediation_runs_checks_and_verifies():
    out = remediate("INC-1002")
    assert out["status"] == "resolved"
    assert all(c["passed"] for c in out["pre_checks"] + out["post_checks"])
    assert out["execution"]["simulated"] is True


def test_remediation_blocked_without_approval_or_ack():
    assert remediate("INC-1002", approved=False)["status"] == "blocked"
    blocked = remediate("INC-1002", inv_mutator=lambda inv: inv.update(confidence=0.3))
    assert blocked["status"] == "blocked" and "execution" not in blocked
    ok = remediate("INC-1002", ack=True, inv_mutator=lambda inv: inv.update(confidence=0.3))
    assert ok["status"] == "resolved"
