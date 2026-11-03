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
- Demo scenario: `outreach_almost_sends_email` (default — unchanged for the breakpoint video)
- Approve simulates success; Deny aborts — nothing is actually sent

## Use with a real agent

Pair this Debugger with [likarajo/ai-agent-stack](https://github.com/likarajo/ai-agent-stack) to stream a live question’s full observability trace (plugins → skills → RAG → MCP → tools → APIs → LLM → answer).

1. Start Agent Debugger (`docker compose up --build`, or run `api` + `redis` + `ui` natively).
2. In **ai-agent-stack**, point the chat at this API:

   ```bash
   export AGENT_DEBUGGER_URL=http://127.0.0.1:8000
   make chat
   ```

3. Ask a suggested question in the stack chat. Copy the printed `run_id`, or open  
   `http://localhost:3000/?run_id=<uuid>`.
4. In the Debugger UI click **Watch run** (or use the deep link) to attach the timeline + audit log.

External drivers create runs with `enqueue: false` (or a scenario name starting with `ai_agent_stack` / `external`) so the scripted outreach worker never races the real agent. Events include timed `tool.call` / `tool.result` pairs (`plugin.load`, `skill.select`, `rag.retrieve`, `mcp.*`, `api.*`, `llm.chat`, …) plus `user.message` and `agent.answer`.

See also: [ai-agent-stack docs/AGENT_DEBUGGER.md](https://github.com/likarajo/ai-agent-stack/blob/main/docs/AGENT_DEBUGGER.md).
