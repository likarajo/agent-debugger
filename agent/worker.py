from __future__ import annotations

import json
import os
import time

import httpx
import redis

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
API_URL = os.environ.get("API_INTERNAL_URL", "http://localhost:8000")
RUNS_QUEUE = "runs:queue"


def get_redis() -> redis.Redis:
    return redis.Redis.from_url(REDIS_URL, decode_responses=True)


def post_event(client: httpx.Client, run_id: str, event: dict) -> dict:
    resp = client.post(f"{API_URL}/runs/{run_id}/events", json=event, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def wait_decision(client: httpx.Client, run_id: str) -> dict:
    resp = client.get(
        f"{API_URL}/runs/{run_id}/wait-decision",
        params={"timeout": 600},
        timeout=610.0,
    )
    resp.raise_for_status()
    return resp.json()


def run_outreach(client: httpx.Client, run_id: str) -> None:
    from scenarios.outreach import STEPS

    post_event(
        client,
        run_id,
        {
            "type": "run.started",
            "message": "Outreach agent started",
        },
    )

    approved_send = False

    for step in STEPS:
        if step.get("after_approve_only") and not approved_send:
            continue

        delay = float(step.get("delay", 0.5))
        time.sleep(delay)

        event = {
            "type": step["type"],
            "message": step.get("message"),
            "tool": step.get("tool"),
            "payload": step.get("payload"),
        }
        result = post_event(client, run_id, event)

        if step.get("gated") or result.get("gated"):
            print(f"[agent] paused on {step.get('tool')} — waiting for human decision", flush=True)
            decision = wait_decision(client, run_id)
            print(f"[agent] decision={decision.get('decision')}", flush=True)
            if decision.get("decision") == "deny":
                print("[agent] denied — stopping", flush=True)
                return
            approved_send = True

    print("[agent] scenario complete", flush=True)


def main() -> None:
    r = get_redis()
    print(f"[agent] listening on {RUNS_QUEUE}", flush=True)
    with httpx.Client() as client:
        # Wait for API health
        for _ in range(60):
            try:
                h = client.get(f"{API_URL}/health", timeout=2.0)
                if h.status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise SystemExit("API never became healthy")

        while True:
            item = r.brpop(RUNS_QUEUE, timeout=5)
            if not item:
                continue
            _, run_id = item
            print(f"[agent] picked run {run_id}", flush=True)
            try:
                # Load scenario from run record via API
                run = client.get(f"{API_URL}/runs/{run_id}", timeout=10.0).json()
                scenario = run.get("scenario", "outreach_almost_sends_email")
                if scenario == "outreach_almost_sends_email":
                    run_outreach(client, run_id)
                else:
                    post_event(
                        client,
                        run_id,
                        {
                            "type": "run.aborted",
                            "message": f"Unknown scenario: {scenario}",
                        },
                    )
            except Exception as exc:  # noqa: BLE001
                print(f"[agent] error on {run_id}: {exc}", flush=True)
                try:
                    post_event(
                        client,
                        run_id,
                        {
                            "type": "run.aborted",
                            "message": f"Agent error: {exc}",
                        },
                    )
                except Exception:
                    pass


if __name__ == "__main__":
    main()
