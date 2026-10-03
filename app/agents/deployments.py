from datetime import datetime

from app.config import DEPLOY_WINDOW_MINUTES


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


async def deployment_agent(incident: dict, tools) -> dict:
    data = await tools.call("recent_deployments", service=incident["service"],
                            before=incident["started_at"], hours=24)
    started = _ts(incident["started_at"])
    suspects = []
    for d in data["deployments"]:
        mins = int((started - _ts(d["deployed_at"])).total_seconds() // 60)
        if mins <= DEPLOY_WINDOW_MINUTES:
            versions = data["all_versions"]
            idx = versions.index(d["version"])
            prev = versions[idx + 1] if idx + 1 < len(versions) else None
            suspects.append({**d, "minutes_before_incident": mins, "previous_version": prev})
    votes = {}
    if suspects:
        mins = min(s["minutes_before_incident"] for s in suspects)
        votes["bad_deployment"] = 1.0 if mins <= 30 else 0.7
        s = suspects[0]
        summary = f"{s['version']} deployed {s['minutes_before_incident']} min before the incident."
    else:
        summary = "No deployments in the 2 hours before the incident."
    return {"id": "deployments", "source": "deployment_history", "summary": summary,
            "votes": votes, "details": {"suspect_deployments": suspects}}
