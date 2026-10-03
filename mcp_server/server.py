"""MCP server: read-only tools the agents call over the Model Context Protocol (stdio).

Tools: search_logs, service_health, recent_deployments, search_similar_incidents.
The last one does semantic search: Sentence Transformers embedding + pgvector cosine similarity.
IMPORTANT: stdio transport -> never print to stdout in this process (use stderr / logging).
"""
import json
import logging
import sys
from datetime import datetime, timedelta

import numpy as np
import psycopg
from pgvector.psycopg import register_vector
from mcp.server.fastmcp import FastMCP

from app.config import DATA_DIR, DATABASE_URL, EMBEDDING_MODEL

logging.basicConfig(stream=sys.stderr, level=logging.INFO)
log = logging.getLogger("opspilot.mcp")

mcp = FastMCP("opspilot-tools")


def _load(name):
    return json.loads((DATA_DIR / name).read_text())


LOGS = _load("logs.json")
HEALTH = _load("health.json")
DEPLOYS = _load("deployments.json")
INCIDENTS = {i["id"]: i for i in _load("incidents.json")}
_model = None


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def embed(text: str) -> np.ndarray:
    return np.asarray(get_model().encode(text, normalize_embeddings=True), dtype=np.float32)


def connect():
    conn = psycopg.connect(DATABASE_URL, autocommit=True)
    register_vector(conn)
    return conn


def init_vector_store():
    """Create the pgvector table and embed + insert historical incidents (idempotent)."""
    with psycopg.connect(DATABASE_URL, autocommit=True) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
    with connect() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS past_incidents (
            id TEXT PRIMARY KEY, title TEXT, description TEXT, category TEXT,
            root_cause TEXT, resolution TEXT, action TEXT, embedding vector(384))""")
        conn.execute("CREATE INDEX IF NOT EXISTS past_incidents_emb_idx ON past_incidents "
                     "USING hnsw (embedding vector_cosine_ops)")
        count = conn.execute("SELECT count(*) FROM past_incidents").fetchone()[0]
        if count:
            return
        for p in _load("past_incidents.json"):
            vec = embed(f"{p['title']}. {p['description']}")
            conn.execute(
                "INSERT INTO past_incidents VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (p["id"], p["title"], p["description"], p["category"], p["root_cause"],
                 p["resolution"], p["action"], vec))
        log.info("Seeded historical incidents into pgvector")


@mcp.tool()
def search_logs(incident_id: str, min_level: str = "WARN") -> dict:
    """Return log lines for an incident at or above min_level (INFO/WARN/ERROR)."""
    order = {"INFO": 0, "WARN": 1, "ERROR": 2}
    lines = [l for l in LOGS.get(incident_id, []) if order.get(l["level"], 0) >= order.get(min_level, 1)]
    return {"incident_id": incident_id, "lines": lines}


@mcp.tool()
def service_health(service: str, phase: str = "current") -> dict:
    """Health metrics for a service. phase = 'current' or 'post_remediation' (simulated data)."""
    metrics = HEALTH.get(service, {}).get(phase)
    if metrics is None:
        return {"service": service, "found": False, "metrics": {}}
    return {"service": service, "phase": phase, "found": True, "metrics": metrics}


@mcp.tool()
def recent_deployments(service: str, before: str, hours: int = 24) -> dict:
    """Deployments of a service within `hours` before the ISO timestamp `before`."""
    end = datetime.fromisoformat(before.replace("Z", "+00:00"))
    start = end - timedelta(hours=hours)
    found = []
    for d in DEPLOYS.get(service, []):
        t = datetime.fromisoformat(d["deployed_at"].replace("Z", "+00:00"))
        if start <= t <= end:
            found.append(d)
    return {"service": service, "deployments": found,
            "all_versions": [d["version"] for d in DEPLOYS.get(service, [])]}


@mcp.tool()
def search_similar_incidents(query: str, top_k: int = 3) -> dict:
    """Semantic search over historical incidents (pgvector cosine similarity)."""
    vec = embed(query)
    with connect() as conn:
        rows = conn.execute(
            """SELECT id, title, category, root_cause, resolution, action,
                      1 - (embedding <=> %s) AS similarity
               FROM past_incidents ORDER BY embedding <=> %s LIMIT %s""",
            (vec, vec, top_k)).fetchall()
    return {"matches": [
        {"id": r[0], "title": r[1], "category": r[2], "root_cause": r[3],
         "resolution": r[4], "action": r[5], "similarity": round(float(r[6]), 4)} for r in rows]}


if __name__ == "__main__":
    init_vector_store()
    mcp.run(transport="stdio")
