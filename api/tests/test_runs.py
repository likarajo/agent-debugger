"""API tests for outreach demo + external (non-enqueued) observability runs."""

from __future__ import annotations

import os
import sys

import pytest
from fastapi.testclient import TestClient

# Allow `from app ...` when running from repo root or api/
API_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if API_ROOT not in sys.path:
    sys.path.insert(0, API_ROOT)

os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

from app import runs  # noqa: E402
from app.main import app  # noqa: E402
from app.redis_client import get_redis  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_redis():
    r = get_redis()
    r.flushdb()
    yield
    r.flushdb()


@pytest.fixture
def client():
    return TestClient(app)


def test_outreach_demo_still_enqueues_by_default(client):
    before = get_redis().llen(runs.RUNS_QUEUE)
    resp = client.post("/runs", json={"scenario": "outreach_almost_sends_email"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["scenario"] == "outreach_almost_sends_email"
    assert body["status"] == "queued"
    assert body.get("enqueue") is True
    assert get_redis().llen(runs.RUNS_QUEUE) == before + 1

    events = client.get(f"/runs/{body['id']}/events").json()["events"]
    assert events[0]["type"] == "run.created"
    assert events[0]["message"] == "Run queued for scenario 'outreach_almost_sends_email'"
    assert events[0]["payload"] is None


def test_enqueue_false_does_not_push_queue(client):
    before = get_redis().llen(runs.RUNS_QUEUE)
    resp = client.post(
        "/runs",
        json={"scenario": "external_observability", "enqueue": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "created"
    assert body.get("enqueue") is False
    assert get_redis().llen(runs.RUNS_QUEUE) == before


def test_ai_agent_stack_scenario_never_enqueued(client):
    """Companion may omit enqueue:false; still keep the outreach worker idle."""
    before = get_redis().llen(runs.RUNS_QUEUE)
    resp = client.post(
        "/runs",
        json={"scenario": "ai_agent_stack_issue_triage", "enqueue": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("enqueue") is False
    assert get_redis().llen(runs.RUNS_QUEUE) == before
    assert runs.is_external_scenario(body["scenario"])


def test_external_trace_audit_includes_observability_steps(client):
    created = client.post(
        "/runs",
        json={"scenario": "ai_agent_stack_issue_triage", "enqueue": False},
    ).json()
    run_id = created["id"]

    sequence = [
        {"type": "run.started", "message": "Integration agent started"},
        {
            "type": "user.message",
            "message": "Which open issues mention login?",
            "payload": {"role": "user", "content": "Which open issues mention login?"},
        },
        {
            "type": "tool.call",
            "tool": "plugin.load",
            "message": "Loading plugins",
            "payload": {"phase": "plugin.load", "input": {"manifest": "northwind"}},
        },
        {
            "type": "tool.result",
            "tool": "plugin.load",
            "message": "plugin.load completed in 12ms",
            "payload": {
                "phase": "plugin.load",
                "input": {"manifest": "northwind"},
                "output": {"installed": True},
                "duration_ms": 12.0,
            },
        },
        {
            "type": "tool.call",
            "tool": "skill.select",
            "message": "Selecting skill",
            "payload": {"phase": "skill.select", "input": {"catalog": ["issue-triage"]}},
        },
        {
            "type": "tool.result",
            "tool": "skill.select",
            "message": "skill.select completed in 4ms",
            "payload": {
                "phase": "skill.select",
                "input": {"catalog": ["issue-triage"]},
                "output": {"selected": "issue-triage"},
                "duration_ms": 4.0,
            },
        },
        {
            "type": "tool.call",
            "tool": "rag.retrieve",
            "message": "Retrieving docs",
            "payload": {"phase": "rag.retrieve", "input": {"query": "login", "k": 3}},
        },
        {
            "type": "tool.result",
            "tool": "rag.retrieve",
            "message": "rag.retrieve completed in 9ms",
            "payload": {
                "phase": "rag.retrieve",
                "input": {"query": "login", "k": 3},
                "output": {"chunks": [{"source": "login-timeout-runbook.md", "score": 0.9}]},
                "duration_ms": 9.0,
            },
        },
        {
            "type": "tool.call",
            "tool": "mcp.search_issues_tool",
            "message": "MCP search",
            "payload": {"phase": "mcp.call", "input": {"state": "open", "text": "login"}},
        },
        {
            "type": "tool.result",
            "tool": "mcp.search_issues_tool",
            "message": "mcp completed in 15ms",
            "payload": {
                "phase": "mcp.call",
                "input": {"state": "open", "text": "login"},
                "output": {"ids": [101, 102]},
                "duration_ms": 15.0,
            },
        },
        {
            "type": "tool.call",
            "tool": "api.get_issue",
            "message": "GET issue",
            "payload": {"phase": "api.call", "input": {"path": "/issues/101"}},
        },
        {
            "type": "tool.result",
            "tool": "api.get_issue",
            "message": "api completed in 6ms",
            "payload": {
                "phase": "api.call",
                "input": {"path": "/issues/101"},
                "output": {"id": 101, "title": "Login timeout"},
                "duration_ms": 6.0,
            },
        },
        {
            "type": "tool.call",
            "tool": "llm.chat",
            "message": "Composing answer",
            "payload": {"phase": "llm.call", "input": {"model": "scripted-fallback"}},
        },
        {
            "type": "tool.result",
            "tool": "llm.chat",
            "message": "llm.chat completed in 20ms",
            "payload": {
                "phase": "llm.call",
                "input": {"model": "scripted-fallback"},
                "output": {"tokens": 42},
                "duration_ms": 20.0,
            },
        },
        {
            "type": "agent.answer",
            "message": "Final answer ready",
            "payload": {"content": "Open login issues: #101, #102", "duration_ms": 80.0},
        },
        {"type": "run.completed", "message": "Run completed"},
    ]

    for event in sequence:
        r = client.post(f"/runs/{run_id}/events", json=event)
        assert r.status_code == 200, r.text

    run = client.get(f"/runs/{run_id}").json()
    assert run["status"] == "completed"

    events = client.get(f"/runs/{run_id}/events").json()["events"]
    types = [e["type"] for e in events]
    assert "user.message" in types
    assert "agent.answer" in types
    assert "tool.call" in types
    assert "tool.result" in types
    assert "run.completed" in types

    audit = client.get(f"/runs/{run_id}/audit").json()["audit"]
    audit_types = {e["type"] for e in audit}
    assert "user.message" in audit_types
    assert "agent.answer" in audit_types
    assert "tool.result" in audit_types
    assert "run.completed" in audit_types
    # think / tool.call stay on the timeline, not the audit summary
    assert "tool.call" not in audit_types

    answer = next(e for e in audit if e["type"] == "agent.answer")
    assert answer["payload"]["content"].startswith("Open login issues")
    assert answer["payload"]["duration_ms"] == 80.0

    results = [e for e in audit if e["type"] == "tool.result"]
    assert all("duration_ms" in (e.get("payload") or {}) for e in results)


def test_is_external_scenario_helper():
    assert runs.is_external_scenario("ai_agent_stack_issue_triage")
    assert runs.is_external_scenario("external_demo")
    assert not runs.is_external_scenario("outreach_almost_sends_email")
