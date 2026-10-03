# OpsPilot V2 — Agentic AI Incident Investigation & Remediation Platform

**Python · FastAPI · LangGraph · RAG · Sentence Transformers · pgvector · MCP · Groq LLM · Docker Compose**

A small portfolio project (synthetic data, no real infrastructure — every remediation is **simulated**).
Given an incident, specialised agents gather evidence, a correlation step scores root-cause hypotheses,
an LLM agent explains the result, and a **human must approve** before any (simulated) remediation runs.

## Run it
```bash
cp .env.example .env        # optional: put GROQ_API_KEY=... in it
docker compose up --build   # first build downloads torch + the embedding model (a few minutes)
```
Open http://localhost:8000 (UI) or http://localhost:8000/docs (Swagger). Readiness: `/ready` lists the MCP tools and whether the LLM is enabled.

```bash
curl -X POST localhost:8000/api/incidents/INC-1002/investigate
curl -X POST localhost:8000/api/incidents/INC-1002/approve \
     -H 'Content-Type: application/json' -d '{"approved": true, "approver": "om"}'
```
If an investigation is flagged `low_confidence`, approval needs `"acknowledge_low_confidence": true`.

Tests (no DB/model/API key needed): `pip install -r requirements.txt && pytest -q`

## How it works
```
POST /investigate
  LangGraph:  START ─┬─ logs_agent ──────┐
                     ├─ health_agent ────┤
                     ├─ deployment_agent ┼─> correlate ─> rca_agent (Groq) ─> plan_remediation ─> approval_gate ─> END
                     └─ rag_agent ───────┘                                                     (status: awaiting_approval)
POST /approve  (human)
  LangGraph:  pre_checks ─> execute (simulated) ─> verify (post-remediation checks) ─> resolved | verification_failed
                   └─ any check fails ─> blocked
```
* **MCP**: `mcp_server/server.py` is a real MCP server (stdio). The API starts it as a subprocess and **every agent calls its tools through an MCP `ClientSession`**: `search_logs`, `service_health`, `recent_deployments`, `search_similar_incidents`.
* **RAG**: 10 historical incidents are embedded with `all-MiniLM-L6-v2` (384-dim) and stored in a pgvector `vector(384)` column (HNSW index). The RAG agent embeds the new incident and retrieves nearest neighbours by cosine distance (`<=>`).
* **Confidence scoring**: each agent votes for root-cause categories (0–1); votes are weighted (logs .30, health .25, deployments .20, RAG .25) and summed. Fully deterministic and explainable (`hypotheses[].contributions`).
* **LLM only where reasoning is needed**: just the RCA agent calls Groq. It may only pick from the top candidate categories and cite known evidence ids; invalid output → rule-based fallback. If the LLM disagrees with the evidence, the evidence-based category is kept and confidence is reduced ×0.85. No key → still works (`llm_used: false`).
* **Human-in-the-loop**: the investigation graph ends at an approval gate; nothing runs until `/approve`. Pre-execution checks (approval recorded, action allow-listed, service known, confidence OK/acknowledged, not already executed) and post-remediation verification (no anomalies, error rate < 1%, p95 < 500 ms) are automated.

## Layout
`app/` FastAPI + LangGraph + agents · `mcp_server/` MCP tools + pgvector search · `data/` synthetic incidents, logs, metrics, deployments, history · `static/` tiny UI · `tests/`
