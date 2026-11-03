from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import runs
from app.policy import GATED_TOOLS
from app.redis_client import get_redis

app = FastAPI(title="Agent Debugger API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateRunBody(BaseModel):
    scenario: str = Field(default=runs.SCENARIO_OUTREACH)
    enqueue: bool = Field(
        default=True,
        description="If false, do not push to the worker queue (external drivers)",
    )


class AgentEventBody(BaseModel):
    type: str
    message: str | None = None
    tool: str | None = None
    payload: Any | None = None


class DecisionBody(BaseModel):
    decision: str
    note: str | None = None


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        pong = get_redis().ping()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"redis unavailable: {exc}") from exc
    return {"ok": True, "redis": bool(pong), "gated_tools": sorted(GATED_TOOLS)}


@app.post("/runs")
def create_run(body: CreateRunBody) -> dict[str, Any]:
    return runs.create_run(scenario=body.scenario, enqueue=body.enqueue)


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = runs.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@app.get("/runs/{run_id}/events")
def get_events(run_id: str) -> dict[str, Any]:
    if not runs.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return {"events": runs.list_events(run_id)}


@app.get("/runs/{run_id}/audit")
def get_audit(run_id: str) -> dict[str, Any]:
    if not runs.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    return {"audit": runs.list_audit(run_id)}


@app.post("/runs/{run_id}/events")
def post_event(run_id: str, body: AgentEventBody) -> dict[str, Any]:
    if not runs.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    try:
        event = runs.append_event(
            run_id,
            {
                "type": body.type,
                "message": body.message,
                "tool": body.tool,
                "payload": body.payload,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return event


@app.post("/runs/{run_id}/decision")
def post_decision(run_id: str, body: DecisionBody) -> dict[str, Any]:
    try:
        return runs.submit_decision(run_id, body.decision, body.note)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/runs/{run_id}/wait-decision")
def wait_decision(run_id: str, timeout: int = 600) -> dict[str, Any]:
    """Used by the agent worker to block until approve/deny."""
    if not runs.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    decision = runs.wait_for_decision(run_id, timeout=timeout)
    if not decision:
        raise HTTPException(status_code=408, detail="timed out waiting for decision")
    return decision


@app.get("/runs/{run_id}/stream")
async def stream_events(run_id: str) -> StreamingResponse:
    if not runs.get_run(run_id):
        raise HTTPException(status_code=404, detail="run not found")

    async def event_generator():
        r = get_redis()
        pubsub = r.pubsub()
        channel = runs.stream_channel(run_id)
        pubsub.subscribe(channel)

        # Replay existing events first
        for existing in runs.list_events(run_id):
            yield f"data: {json.dumps(existing)}\n\n"

        try:
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    data = message["data"]
                    yield f"data: {data}\n\n"
                    try:
                        parsed = json.loads(data)
                        if parsed.get("type") in {"run.completed", "run.aborted"}:
                            break
                    except json.JSONDecodeError:
                        pass
                await asyncio.sleep(0.05)
        finally:
            pubsub.unsubscribe(channel)
            pubsub.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
