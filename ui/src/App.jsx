import { useEffect, useMemo, useRef, useState } from "react";
import { createRun, getAudit, getRun, submitDecision, subscribe } from "./api.js";

function formatTime(ts) {
  if (!ts) return "";
  return new Date(ts * 1000).toLocaleTimeString();
}

function EventCard({ event }) {
  const gated = Boolean(event.gated) || event.tool === "email.send";
  return (
    <div className={`event ${gated && event.type === "tool.call" ? "gated" : ""}`}>
      <div className="meta">
        <span className="type">{event.type}{event.tool ? ` · ${event.tool}` : ""}</span>
        <span>{formatTime(event.ts)}</span>
      </div>
      <div className="msg">{event.message || "—"}</div>
      {event.payload != null && (
        <pre className="payload">{JSON.stringify(event.payload, null, 2)}</pre>
      )}
    </div>
  );
}

export default function App() {
  const [run, setRun] = useState(null);
  const [events, setEvents] = useState([]);
  const [audit, setAudit] = useState([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const unsubRef = useRef(null);

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

  async function startDemo() {
    setError("");
    setBusy(true);
    try {
      if (unsubRef.current) unsubRef.current();
      setEvents([]);
      setAudit([]);
      const created = await createRun();
      setRun(created);

      unsubRef.current = subscribe(created.id, async (event) => {
        setEvents((prev) => {
          if (prev.some((p) => p.id === event.id)) return prev;
          return [...prev, event];
        });
        if (["decision", "run.completed", "run.aborted", "tool.result"].includes(event.type)) {
          refreshAudit(created.id);
        }
        if (["run.completed", "run.aborted", "tool.call", "decision"].includes(event.type)) {
          try {
            const latest = await getRun(created.id);
            setRun(latest);
          } catch {
            /* ignore */
          }
        }
      });
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setBusy(false);
    }
  }

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
            Scripted outreach agent · gates <code>email.send</code> until you approve or deny
          </p>
        </div>
        <div style={{ textAlign: "right" }}>
          <button className="btn btn-primary" onClick={startDemo} disabled={busy}>
            {busy && !run ? "Starting…" : "Run demo: Outreach Agent"}
          </button>
          {run && (
            <div style={{ marginTop: 10 }}>
              <span className={`status-pill status-${run.status}`}>{run.status}</span>
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
              <div className="empty">Start the demo to stream tool calls here.</div>
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
              {audit.length === 0 && <div className="empty">Decisions and outcomes appear here.</div>}
              {audit.map((e) => (
                <EventCard key={e.id} event={e} />
              ))}
            </div>
          </section>
        </div>
      </div>

      <p className="footer">
        Local Docker demo · API {run ? run.id.slice(0, 8) : "—"} · no real email is ever sent
      </p>
    </div>
  );
}
