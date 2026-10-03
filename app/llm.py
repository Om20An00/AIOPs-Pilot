"""Groq LLM call used ONLY by the RCA agent (the one step that needs reasoning).

Guardrails against hallucination:
  * temperature 0, JSON-only output
  * the model may only choose a category from the candidate list and cite known evidence ids
  * any invalid output -> returns None and the caller falls back to deterministic text
"""
import json
import logging

from app.config import GROQ_API_KEY, GROQ_MODEL

log = logging.getLogger("opspilot.llm")

SYSTEM = (
    "You are an SRE assistant doing root cause analysis. Use ONLY the evidence provided. "
    "Do not invent facts, metrics, versions or services. Choose root_cause_category from the "
    "candidate list. Respond with JSON: {\"root_cause_category\": str, \"summary\": str (max 3 sentences), "
    "\"contributing_factors\": [str], \"cited_evidence\": [evidence ids you relied on]}."
)


def llm_enabled() -> bool:
    return bool(GROQ_API_KEY)


async def reason_root_cause(incident: dict, evidence: list, hypotheses: list):
    if not llm_enabled():
        return None
    candidates = [h["category"] for h in hypotheses[:3]]
    known_ids = {e["id"] for e in evidence}
    payload = {
        "incident": {k: incident[k] for k in ("id", "title", "service", "description", "started_at")},
        "candidate_categories": candidates,
        "evidence": [{"id": e["id"], "source": e["source"], "summary": e["summary"],
                      "details": e["details"]} for e in evidence],
    }
    try:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=GROQ_API_KEY)
        resp = await client.chat.completions.create(
            model=GROQ_MODEL, temperature=0, response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": json.dumps(payload)}])
        data = json.loads(resp.choices[0].message.content)
        if data.get("root_cause_category") not in candidates:
            raise ValueError("category not in candidates")
        cited = [c for c in data.get("cited_evidence", []) if c in known_ids]
        return {"category": data["root_cause_category"], "summary": str(data["summary"]),
                "contributing_factors": [str(x) for x in data.get("contributing_factors", [])][:5],
                "cited_evidence": cited}
    except Exception as exc:  # network error, bad JSON, validation failure...
        log.warning("LLM reasoning failed, using deterministic fallback: %s", exc)
        return None
