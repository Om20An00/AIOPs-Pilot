from collections import Counter

from app.rules import classify_log_line, normalize_signature


async def logs_agent(incident: dict, tools) -> dict:
    data = await tools.call("search_logs", incident_id=incident["id"], min_level="WARN")
    errors = [l for l in data["lines"] if l["level"] == "ERROR"]
    cats = Counter(c for c in (classify_log_line(l["message"]) for l in errors) if c)
    total = len(errors) or 1
    votes = {c: round(n / total, 3) for c, n in cats.items()}
    sigs = Counter(normalize_signature(l["message"]) for l in errors).most_common(3)
    dominant = cats.most_common(1)[0][0] if cats else None
    summary = (f"{len(errors)} ERROR lines; dominant pattern: {dominant} "
               f"({votes.get(dominant, 0):.0%} of errors)." if dominant
               else f"{len(errors)} ERROR lines; no known pattern matched.")
    return {"id": "logs", "source": "logs", "summary": summary, "votes": votes,
            "details": {"error_count": len(errors), "category_counts": dict(cats),
                        "top_signatures": [{"signature": s, "count": n} for s, n in sigs]}}
