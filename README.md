# Agent Debugger

Local Docker demo: a scripted AI outreach agent that **pauses on `email.send`** until you Approve or Deny. Built for live YouTube demos — no API keys, no real email.

## Quick start

```bash
docker compose up --build
```

Open **http://localhost:3000**

1. Click **Run demo: Outreach Agent**
2. Watch the timeline (`think` → `web.search` → `email.draft` → `email.send`)
3. When **PAUSED**, click **Deny** (or Approve)
4. Check the audit log

API health: http://localhost:8000/health

## Architecture

| Service | Port | Role |
|---------|------|------|
| `ui` | 3000 | Debugger console |
| `api` | 8000 | Runs, SSE, decisions, policy |
| `agent` | — | Scripted outreach worker |
| `redis` | 6379 | Queue, events, pub/sub |

## Make targets

- `make demo` / `make up` — `docker compose up --build`
- `make down` — stop stack
- `make logs` — follow logs

## Notes

- Gated tools: `email.send`, `shell.exec`, `file.delete`
- Demo scenario: `outreach_almost_sends_email`
- Approve simulates success; Deny aborts — nothing is actually sent
