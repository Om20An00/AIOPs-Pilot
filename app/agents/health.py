from app.rules import HEALTH_RULES, is_breached, severity


def evaluate_health(metrics: dict) -> list:
    """Return anomalies: metrics breaching their threshold."""
    out = []
    for name, value in metrics.items():
        rule = HEALTH_RULES.get(name)
        if rule and is_breached(value, rule[0], rule[1]):
            out.append({"metric": name, "value": value, "threshold": rule[1],
                        "category": rule[2], "severity": round(severity(value, rule[0], rule[1]), 3)})
    return out


async def health_agent(incident: dict, tools) -> dict:
    data = await tools.call("service_health", service=incident["service"], phase="current")
    anomalies = evaluate_health(data["metrics"])
    votes = {}
    for a in anomalies:
        if a["category"]:
            strength = round(0.6 + 0.4 * a["severity"], 3)
            votes[a["category"]] = max(votes.get(a["category"], 0), strength)
    names = ", ".join(f"{a['metric']}={a['value']}" for a in anomalies) or "none"
    return {"id": "health", "source": "service_health", "summary": f"Anomalous metrics: {names}.",
            "votes": votes, "details": {"anomalies": anomalies, "metrics": data["metrics"]}}
