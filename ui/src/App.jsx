import { useEffect, useMemo, useRef, useState } from "react";
import {
  createRun,
  getAudit,
  getEvents,
  getRun,
  submitDecision,
  subscribe,
  watchRun,
} from "./api.js";

function formatTime(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleTimeString();
}

/** Map event type / tool name to a short observability step label. */
function stepKind(event) {
  const type = event.type || "";
  const tool = event.tool || "";

  if (type === "user.message") return "user";
  if (type === "agent.answer" || type === "answer") return "answer";
  if (type === "think") return "think";
  if (type === "decision") return "decision";
  if (type.startsWith("run.")) return type;

  const name = tool || type;
  if (name.startsWith("plugin") || type === "plugin") return "plugin";
  if (name.startsWith("skill") || type === "skill") return "skill";
  if (name.startsWith("rag") || type === "rag.retrieve") return "rag.retrieve";
  if (name.startsWith("mcp") || type === "mcp.call") return "mcp.call";
  if (name.startsWith("api") || type === "api.call") return "api.call";
  if (name.startsWith("llm") || type === "llm.call" || type === "llm.chat") return "llm.call";
  if (type === "tool.call" || type === "tool.result") return "tool.call";
  return type;
}

function durationMs(payload) {
  if (!payload || typeof payload !== "object") return null;
  const value = payload.duration_ms;
  return typeof value === "number" ? value : null;
}

function extractIO(payload) {
  if (!payload || typeof payload !== "object") return { input: null, output: null };
  const input =
    "input" in payload
      ? payload.input
      : payload.query != null
        ? { query: payload.query, k: payload.k }
        : null;
  const output =
    "output" in payload
      ? payload.output
      : "content" in payload
        ? payload.content
        : null;
  return { input, output };
}

function EventCard({ event }) {
  const gated = Boolean(event.gated) || event.tool === "email.send";
  const kind = stepKind(event);
  const ms = durationMs(event.payload);
  const { input, output } = extractIO(event.payload);
  const showStructured =
    event.payload != null &&
    typeof event.payload === "object" &&
    (input != null || output != null || ms != null);

  return (
    <div className={`event ${gated && event.type === "tool.call" ? "gated" : ""} kind-${kind.replace(".", "-")}`}>
      <div className="meta">
        <span className="type">
          <span className="kind-badge">{kind}</span>
          {event.type}
          {event.tool ? ` · ${event.tool}` : ""}
        </span>
        <span className="meta-right">
          {ms != null && <span className="duration">{ms} ms</span>}
          <span>{formatTime(event.ts)}</span>
        </span>
      </div>
      <div className="msg">{event.message || "—"}</div>
      {showStructured ? (
        <div className="io">
          {input != null && (
            <div className="io-block">
              <div className="io-label">input</div>
              <pre className="payload">{JSON.stringify(input, null, 2)}</pre>
            </div>
          )}
          {output != null && (
            <div className="io-block">
              <div className="io-label">output</div>
              <pre className="payload">{typeof output === "string" ? output : JSON.stringify(output, null, 2)}</pre>
            </div>
          )}
          {input == null && output == null && (
            <pre className="payload">{JSON.stringify(event.payload, null, 2)}</pre>
          )}
        </div>
      ) : (
        event.payload != null && (
          <pre className="payload">{JSON.stringify(event.payload, null, 2)}</pre>
        )
      )}
    </div>
  );
}

const AUDIT_REFRESH_TYPES = new Set([
  "decision",
  "run.completed",
  "run.aborted",
  "tool.result",
  "user.message",
  "agent.answer",
  "answer",
  "llm.chat",
  "llm.call",
  "plugin",
  "skill",
  "rag.retrieve",
  "mcp.call",
  "api.call",
]);

export default function App() {
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [audit, setAudit] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [watchId, setWatchId] = useState("");
  const unsubRef = useRef(null);
  const autoWatchDone = useRef(false);

  const paused = run?.status === "paused";
  const pausedEvent = useMemo(
    () =>
      [...events]
        .reverse()
        .find((e) => e.type === "tool.call" && (e.gated || e.tool === "email.send")),
    [events]
  );

  useEffect(() => {
    return () => {
      if (unsubRef.current) unsubRef.current();
    };
  }, []);

  async function refreshAudit(runId) {
    try {
      const data = await getAudit(runId);
      setAudit(data.audit || []);
    } catch {
      /* ignore */
    }
  }

  function attachStream(runId) {
    if (unsubRef.current) unsubRef.current();
    unsubRef.current = subscribe(runId, async (event) => {
      setEvents((prev) => {
        if (prev.some((p) => p.id === event.id)) return prev;
        return [...prev, event];
      });
      if (AUDIT_REFRESH_TYPES.has(event.type)) {
        refreshAudit(runId);
      }
      if (["run.completed", "run.aborted", "tool.call", "decision", "run.started"].includes(event.type)) {
        try {
          const latest = await getRun(runId);
          setRun(latest);
        } catch {
          /* ignore */
        }
      }
    });
  }

  async function startDemo() {
    setError("");
    setBusy(true);
    try {
      if (unsubRef.current) unsubRef.current();
      setEvents([]);
      setAudit([]);
      const created = await createRun();
      setRun(created);
      attachStream(created.id);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  async function watchExisting(idOverride) {
    const id = (idOverride ?? watchId).trim();
    if (!id) return;
    setError("");
    setBusy(true);
    try {
      if (unsubRef.current) unsubRef.current();
      setEvents([]);
      setAudit([]);
      const existing = await watchRun(id);
      setRun(existing);
      setWatchId(id);
      const prior = await getEvents(existing.id);
      setEvents(prior.events || []);
      await refreshAudit(existing.id);
      attachStream(existing.id);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  // Deep link: /?run_id=<uuid> auto-attaches to an external run.
  useEffect(() => {
    if (autoWatchDone.current) return;
    const id = new URLSearchParams(window.location.search).get("run_id");
    if (id) {
      autoWatchDone.current = true;
      setWatchId(id);
      watchExisting(id);
    }
  }, []);

  async function decide(decision) {
    if (!run) return;
    setError("");
    setBusy(true);
    try {
      await submitDecision(run.id, decision);
      const latest = await getRun(run.id);
      setRun(latest);
      await refreshAudit(run.id);
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <p className="brand">Agent Debugger</p>
          <h1>Live breakpoint console</h1>
          <p className="sub">
            Scripted outreach agent · gates <code>email.send</code> until you approve or deny — or
            watch an external <code>ai-agent-stack</code> run
          </p>
        </div>
        <div className="header-actions">
          <button className="btn btn-primary" onClick={startDemo} disabled={busy}>
            {busy && !run ? "Starting…" : "Run demo: Outreach Agent"}
          </button>
          <div className="watch-row">
            <input
              className="watch-input"
              value={watchId}
              onChange={(e) => setWatchId(e.target.value)}
              placeholder="Paste external run id"
              aria-label="External run id"
            />
            <button
              className="btn"
              onClick={() => watchExisting()}
              disabled={busy || !watchId.trim()}
            >
              Watch run
            </button>
          </div>
          {run && (
            <div className="run-meta">
              <span className={`status-pill status-${run.status}`}>{run.status}</span>
              <code className="run-id" title={run.id}>
                {run.id}
              </code>
            </div>
          )}
        </div>
      </header>

      <div className={`paused-banner ${paused ? "visible" : ""}`}>
        <div>
          <h2>PAUSED</h2>
          <p>
            Breakpoint on <strong>{run?.paused_tool || "email.send"}</strong> — decide before the
            agent continues
          </p>
        </div>
        <div className="actions">
          <button className="btn btn-approve" disabled={busy || !paused} onClick={() => decide("approve")}>
            Approve
          </button>
          <button className="btn btn-deny" disabled={busy || !paused} onClick={() => decide("deny")}>
            Deny
          </button>
        </div>
      </div>

      {error && <div className="error">{error}</div>}

      <div className="grid">
        <section className="panel">
          <h3>Timeline</h3>
          <div className="timeline">
            {events.length === 0 && (
              <div className="empty">
                Start the outreach demo, or paste a run id and click Watch run.
              </div>
            )}
            {events.map((e) => (
              <EventCard key={e.id} event={e} />
            ))}
          </div>
        </section>

        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <section className={`panel breakpoint`}>
            <h3>Breakpoint</h3>
            {!paused && <div className="empty">No active breakpoint.</div>}
            {paused && pausedEvent && (
              <>
                <div className="msg" style={{ fontSize: 16, marginBottom: 8 }}>
                  {pausedEvent.message}
                </div>
                <pre className="payload">
                  {JSON.stringify(run?.paused_payload || pausedEvent.payload, null, 2)}
                </pre>
              </>
            )}
          </section>

          <section className="panel">
            <h3>Audit log</h3>
            <div className="timeline">
              {audit.length === 0 && (
                <div className="empty">Decisions, tool results, answers, and outcomes appear here.</div>
              )}
              {audit.map((e) => (
                <EventCard key={e.id} event={e} />
              ))}
            </div>
          </section>
        </div>
      </div>

      <p className="footer">
        Local Docker demo · API {run ? run.id.slice(0, 8) : "—"} · no real email is ever sent ·{" "}
        <a href="https://github.com/likarajo/ai-agent-stack" target="_blank" rel="noreferrer">
          Use with a real agent
        </a>
      </p>
    </div>
  );
}
