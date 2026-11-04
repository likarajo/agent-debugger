from __future__ import annotations

import json
import time
import uuid
from typing import Any

from app.policy import is_gated
from app.redis_client import get_redis

RUNS_QUEUE = "runs:queue"
SCENARIO_OUTREACH = "outreach_almost_sends_email"

# Timeline / audit types emitted by external drivers (e.g. ai-agent-stack).
AUDIT_TYPES = frozenset(
    {
        "decision",
        "tool.result",
        "run.completed",
        "run.aborted",
        "user.message",
        "agent.answer",
        "llm.chat",
        "llm.call",
        "plugin",
        "skill",
        "rag.retrieve",
        "mcp.call",
        "api.call",
        "answer",
    }
)

# Canonical decision values stored in payloads / wait-decision responses.
DECISION_APPROVE = "approve"
DECISION_DENY = "deny"

# Accept past-tense and the historical "denyd" typo on input so old clients/data keep working.
_DECISION_ALIASES = {
    "approve": DECISION_APPROVE,
    "approved": DECISION_APPROVE,
    "deny": DECISION_DENY,
    "denied": DECISION_DENY,
    "denyd": DECISION_DENY,  # legacy typo — still accepted on input
}

_DECISION_PAST_TENSE = {
    DECISION_APPROVE: "approved",
    DECISION_DENY: "denied",
}


def normalize_decision(decision: str) -> str:
    """Map approve/approved and deny/denied/denyd → canonical approve|deny."""
    key = (decision or "").strip().lower()
    if key not in _DECISION_ALIASES:
        raise ValueError("decision must be approve or deny")
    return _DECISION_ALIASES[key]


def decision_past_tense(decision: str) -> str:
    """Human-readable past tense for audit/timeline messages (never 'denyd')."""
    return _DECISION_PAST_TENSE[normalize_decision(decision)]


def _rewrite_legacy_denyd_message(event: dict[str, Any]) -> dict[str, Any]:
    """Normalize historical 'Human denyd …' audit strings when reading events."""
    msg = event.get("message")
    if isinstance(msg, str) and "Human denyd " in msg:
        return {**event, "message": msg.replace("Human denyd ", "Human denied ", 1)}
    return event


def is_external_scenario(scenario: str) -> bool:
    """Scenarios owned by an outside driver — never run by the scripted worker."""
    return scenario.startswith("external") or scenario.startswith("ai_agent_stack")


def _run_key(run_id: str) -> str:
    return f"run:{run_id}"


def _events_key(run_id: str) -> str:
    return f"run:{run_id}:events"


def _decision_key(run_id: str) -> str:
    return f"run:{run_id}:decision"


def _stream_channel(run_id: str) -> str:
    return f"run:{run_id}:stream"


def create_run(scenario: str = SCENARIO_OUTREACH, enqueue: bool = True) -> dict[str, Any]:
    r = get_redis()
    run_id = str(uuid.uuid4())
    now = time.time()
    # External drivers own the run; never hand them to the scripted outreach worker.
    should_enqueue = bool(enqueue) and not is_external_scenario(scenario)
    run = {
        "id": run_id,
        "scenario": scenario,
        "status": "queued" if should_enqueue else "created",
        "created_at": now,
        "updated_at": now,
        "paused_tool": None,
        "paused_payload": None,
        "enqueue": should_enqueue,
    }
    r.set(_run_key(run_id), json.dumps(run))
    r.delete(_events_key(run_id))
    r.delete(_decision_key(run_id))
    if should_enqueue:
        r.lpush(RUNS_QUEUE, run_id)
        # Keep the outreach demo event text/payload identical for filming.
        created_msg = f"Run queued for scenario '{scenario}'"
        created_payload = None
    else:
        created_msg = f"Run created for external scenario '{scenario}' (not enqueued)"
        created_payload = {"enqueue": False, "scenario": scenario}
    _append_event(
        run_id,
        {
            "type": "run.created",
            "message": created_msg,
            "tool": None,
            "payload": created_payload,
        },
    )
    return run


def get_run(run_id: str) -> dict[str, Any] | None:
    raw = get_redis().get(_run_key(run_id))
    if not raw:
        return None
    return json.loads(raw)


def list_events(run_id: str) -> list[dict[str, Any]]:
    raw_list = get_redis().lrange(_events_key(run_id), 0, -1)
    return [_rewrite_legacy_denyd_message(json.loads(x)) for x in raw_list]


def list_audit(run_id: str) -> list[dict[str, Any]]:
    return [e for e in list_events(run_id) if e.get("type") in AUDIT_TYPES]


def _save_run(run: dict[str, Any]) -> None:
    run["updated_at"] = time.time()
    get_redis().set(_run_key(run["id"]), json.dumps(run))


def _append_event(run_id: str, event: dict[str, Any]) -> dict[str, Any]:
    r = get_redis()
    event = {
        **event,
        "id": str(uuid.uuid4()),
        "run_id": run_id,
        "ts": time.time(),
    }
    r.rpush(_events_key(run_id), json.dumps(event))
    r.publish(_stream_channel(run_id), json.dumps(event))
    return event


def append_event(run_id: str, event: dict[str, Any]) -> dict[str, Any]:
    run = get_run(run_id)
    if not run:
        raise ValueError("run not found")
    if run["status"] in {"completed", "aborted"}:
        raise ValueError(f"run already {run['status']}")

    etype = event.get("type")
    if etype == "run.started":
        run["status"] = "running"
        _save_run(run)
    elif etype == "tool.call":
        tool = event.get("tool") or ""
        if is_gated(tool):
            run["status"] = "paused"
            run["paused_tool"] = tool
            run["paused_payload"] = event.get("payload")
            _save_run(run)
            event = {**event, "gated": True, "message": event.get("message") or f"Breakpoint: {tool}"}
        else:
            run["status"] = "running"
            run["paused_tool"] = None
            run["paused_payload"] = None
            _save_run(run)
            event = {**event, "gated": False}
    elif etype == "run.completed":
        run["status"] = "completed"
        run["paused_tool"] = None
        run["paused_payload"] = None
        _save_run(run)
    elif etype == "run.aborted":
        run["status"] = "aborted"
        run["paused_tool"] = None
        run["paused_payload"] = None
        _save_run(run)

    return _append_event(run_id, event)


def submit_decision(run_id: str, decision: str, note: str | None = None) -> dict[str, Any]:
    decision = normalize_decision(decision)
    run = get_run(run_id)
    if not run:
        raise ValueError("run not found")
    if run["status"] != "paused":
        raise ValueError("run is not paused")

    r = get_redis()
    payload = {
        "decision": decision,
        "note": note,
        "tool": run.get("paused_tool"),
        "ts": time.time(),
    }
    r.set(_decision_key(run_id), json.dumps(payload))
    # Wake any BLPOP waiters
    r.lpush(f"run:{run_id}:decision_wait", json.dumps(payload))

    event = _append_event(
        run_id,
        {
            "type": "decision",
            "message": f"Human {decision_past_tense(decision)} {run.get('paused_tool')}",
            "tool": run.get("paused_tool"),
            "payload": payload,
        },
    )

    if decision == DECISION_DENY:
        run["status"] = "aborted"
        run["paused_tool"] = None
        run["paused_payload"] = None
        _save_run(run)
        _append_event(
            run_id,
            {
                "type": "run.aborted",
                "message": "Run aborted after deny — email was not sent",
                "tool": None,
                "payload": None,
            },
        )
    else:
        run["status"] = "running"
        run["paused_tool"] = None
        run["paused_payload"] = None
        _save_run(run)
        _append_event(
            run_id,
            {
                "type": "tool.result",
                "message": "Approved — tool allowed to proceed (demo: no real send)",
                "tool": payload.get("tool"),
                "payload": {"ok": True, "simulated": True},
            },
        )

    return event


def wait_for_decision(run_id: str, timeout: int = 600) -> dict[str, Any] | None:
    r = get_redis()
    result = r.blpop(f"run:{run_id}:decision_wait", timeout=timeout)
    if not result:
        return None
    _, raw = result
    return json.loads(raw)


def stream_channel(run_id: str) -> str:
    return _stream_channel(run_id)
