from app.config import LOW_CONFIDENCE_THRESHOLD, SOURCE_WEIGHTS
from app.llm import llm_enabled, reason_root_cause

DESCRIPTIONS = {
    "bad_deployment": "A recent release introduced a regression in the service.",
    "db_pool_exhaustion": "The service ran out of database connections, so requests queued and timed out.",
    "cache_degradation": "The cache ran out of memory, causing evictions and slow or failing commands.",
    "upstream_dependency": "An external dependency is slow or failing, causing timeouts in this service.",
    "certificate_expiry": "The TLS certificate expired, so secure connections cannot be established.",
}


def correlate(evidence: list) -> list:
    """Deterministic correlation: weighted sum of each agent's category votes."""
    scores = {}
    for e in evidence:
        w = SOURCE_WEIGHTS[e["id"]]
        for cat, strength in e["votes"].items():
            entry = scores.setdefault(cat, {"category": cat, "score": 0.0, "contributions": {}})
            entry["score"] += w * strength
            entry["contributions"][e["id"]] = round(w * strength, 3)
    ranked = sorted(scores.values(), key=lambda h: h["score"], reverse=True)
    for h in ranked:
        h["score"] = round(min(1.0, h["score"]), 3)
    return ranked


async def rca_agent(incident: dict, evidence: list, hypotheses: list) -> dict:
    top = hypotheses[0]
    confidence = top["score"]
    llm = await reason_root_cause(incident, evidence, hypotheses) if llm_enabled() else None
    factors = []
    dep = next((e for e in evidence if e["id"] == "deployments"), None)
    if dep and dep["details"]["suspect_deployments"] and top["category"] != "bad_deployment":
        s = dep["details"]["suspect_deployments"][0]
        factors.append(f"Deployment {s['version']} shortly before the incident may be a contributing factor.")
    if llm:
        agrees = llm["category"] == top["category"]
        if not agrees:
            confidence = round(confidence * 0.85, 3)  # disagreement lowers confidence; evidence-based category wins
        return {"category": top["category"], "summary": llm["summary"],
                "contributing_factors": llm["contributing_factors"] or factors,
                "cited_evidence": llm["cited_evidence"], "llm_used": True,
                "llm_category": llm["category"], "llm_agrees": agrees, "confidence": confidence}
    cited = [e["id"] for e in evidence if top["category"] in e["votes"]]
    summary = DESCRIPTIONS[top["category"]] + " Evidence: " + " ".join(
        e["summary"] for e in evidence if e["id"] in cited)
    return {"category": top["category"], "summary": summary, "contributing_factors": factors,
            "cited_evidence": cited, "llm_used": False, "llm_category": None,
            "llm_agrees": None, "confidence": confidence}


def needs_ack(confidence: float) -> bool:
    return confidence < LOW_CONFIDENCE_THRESHOLD
