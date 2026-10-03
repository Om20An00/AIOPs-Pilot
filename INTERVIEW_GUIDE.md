# Interview guide — defend every resume bullet

Be upfront: *"It's a personal project with synthetic incident data and simulated remediations — I built it to learn agentic workflows, RAG and MCP end to end."* Recruiters respect that; don't claim production users.

| Resume bullet | Where it is true | 20-second demo |
|---|---|---|
| Built an Agentic AI incident platform using Python, FastAPI, LangGraph, RAG, pgvector | `app/main.py` (FastAPI), `app/graph.py` (LangGraph), `mcp_server/server.py` (pgvector) | Open `/docs`, run `/investigate` |
| Orchestrated a multi-agent workflow with specialized agents for logs, deployments, and RAG evidence | `app/agents/logs.py`, `deployments.py`, `rag.py` (+ `health.py`); parallel fan-out in `graph.py` | Show the graph diagram in README; the 4 evidence cards in the UI |
| Automated root-cause analysis by correlating logs, service health, deployments, and operational evidence | `correlate()` in `agents/rca.py` + `rca_agent` | Show `hypotheses[].contributions` in the response |
| Implemented semantic RAG using Sentence Transformers and pgvector for historical incident retrieval | `init_vector_store()` and `search_similar_incidents()` in `mcp_server/server.py` | `docker compose exec db psql -U postgres opspilot -c "select id,category from past_incidents"`; show the `<=>` query |
| Developed human-in-the-loop remediation with approval gates, confidence scoring, and automated checks | `approval_gate` in `graph.py`; `/approve` in `main.py`; `pre_checks`/`verify` in `remediation.py` | Try approving with empty approver (422), approve (checks pass), approve again (409) |
| Containerized with Docker Compose and integrated MCP for agent-tool execution | `Dockerfile`, `docker-compose.yml` (app + pgvector db); `app/mcp_client.py` + `mcp_server/` | `/ready` lists the 4 MCP tools |

## Questions you should expect
* **Why LangGraph?** Parallel fan-out/fan-in with a typed shared state, and conditional routing (blocked vs execute) without hand-written orchestration.
* **Why MCP instead of calling functions?** Tools are decoupled from agents and reusable by any MCP client; the agents only know tool names + schemas.
* **Where do you use the LLM and why only there?** Only RCA: it needs to synthesise heterogeneous evidence into an explanation. Log parsing, threshold checks, vector search and scoring are deterministic — cheaper, testable, no hallucination.
* **How do you stop hallucination?** Temperature 0, JSON-only, constrained to candidate categories, citations must be real evidence ids, validation + deterministic fallback, evidence-based category wins on disagreement.
* **How is confidence computed? Is it calibrated?** Weighted vote sum — a transparent heuristic, **not** a calibrated probability. With real data you'd calibrate against labelled outcomes.
* **Why cosine similarity / normalised embeddings / HNSW?** MiniLM embeddings are normalised, cosine is the standard; HNSW gives approximate nearest-neighbour at scale (overkill for 10 rows, shows the production pattern).
* **What would you do for production?** Real log/metric sources (Loki/Prometheus), auth/RBAC on `/approve`, audit log, queue for long investigations, LangGraph checkpointer for resumable runs, eval set for RCA accuracy, real remediation adapters with dry-run.
* **Known limitations (say them yourself):** synthetic data; 5 incident types; RAG vote thresholds are heuristics tuned for MiniLM; MCP server is stdio child process (fine for a demo, you'd run it as a service in production).
