import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel, Field

from app import store
from app.config import DATA_DIR
from app.graph import build_investigation_graph, new_trace_id
from app.llm import llm_enabled
from app.mcp_client import MCPTools
from app.remediation import build_remediation_graph

log = logging.getLogger("opspilot")
INCIDENTS = {i["id"]: i for i in json.loads((DATA_DIR / "incidents.json").read_text())}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await asyncio.to_thread(store.init)
    # The MCP server runs as a child process over stdio; agents reach every tool through this session.
    params = StdioServerParameters(command=sys.executable, args=["-m", "mcp_server.server"],
                                  env=dict(os.environ))  # SDK default env is stripped; pass DB url etc.
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = MCPTools(session)
            app.state.investigate = build_investigation_graph(tools)
            app.state.remediate = build_remediation_graph(tools)
            app.state.tool_names = [t.name for t in (await session.list_tools()).tools]
            log.info("MCP tools ready: %s", app.state.tool_names)
            yield


app = FastAPI(title="OpsPilot V2", lifespan=lifespan)


class Approval(BaseModel):
    approved: bool
    approver: str = Field(min_length=1)
    comment: str = ""
    acknowledge_low_confidence: bool = False


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def ready():
    return {"status": "ready", "mcp_tools": app.state.tool_names, "llm_enabled": llm_enabled()}


@app.get("/api/incidents")
async def list_incidents():
    statuses = await asyncio.to_thread(store.statuses)
    return [{**i, "investigation_status": statuses.get(i["id"], "not_investigated")} for i in INCIDENTS.values()]


@app.post("/api/incidents/{incident_id}/investigate")
async def investigate(incident_id: str):
    incident = INCIDENTS.get(incident_id)
    if not incident:
        raise HTTPException(404, "Unknown incident")
    state = await app.state.investigate.ainvoke({"incident": incident, "trace_id": new_trace_id(), "evidence": []})
    await asyncio.to_thread(store.save, incident_id, state["status"], state)
    return state


@app.get("/api/incidents/{incident_id}/investigation")
async def get_investigation(incident_id: str):
    result = await asyncio.to_thread(store.get, incident_id)
    if not result:
        raise HTTPException(404, "Not investigated yet")
    return result


@app.post("/api/incidents/{incident_id}/approve")
async def approve(incident_id: str, body: Approval):
    inv = await asyncio.to_thread(store.get, incident_id)
    if not inv:
        raise HTTPException(404, "Not investigated yet")
    if inv["status"] != "awaiting_approval":
        raise HTTPException(409, f"Incident is '{inv['status']}', not awaiting approval")
    inv["approval"] = body.model_dump()
    if not body.approved:
        inv["status"] = "rejected"
        await asyncio.to_thread(store.save, incident_id, "rejected", inv)
        return inv
    if inv["low_confidence"] and not body.acknowledge_low_confidence:
        raise HTTPException(409, "Low-confidence root cause: set acknowledge_low_confidence=true to approve anyway")
    out = await app.state.remediate.ainvoke({"investigation": inv, "approval": body.model_dump()})
    inv["pre_checks"] = out["pre_checks"]
    inv["status"] = out["status"]
    if out["status"] != "blocked":
        inv["remediation"] = out["execution"]
        inv["post_checks"] = out["post_checks"]
    await asyncio.to_thread(store.save, incident_id, inv["status"], inv)
    return inv


app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "static", html=True), name="ui")
