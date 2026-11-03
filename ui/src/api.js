const API = import.meta.env.VITE_API_URL || "http://localhost:8000";

export async function createRun() {
  const res = await fetch(`${API}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario: "outreach_almost_sends_email", enqueue: true }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function watchRun(runId) {
  const res = await fetch(`${API}/runs/${runId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getRun(runId) {
  const res = await fetch(`${API}/runs/${runId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getEvents(runId) {
  const res = await fetch(`${API}/runs/${runId}/events`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function getAudit(runId) {
  const res = await fetch(`${API}/runs/${runId}/audit`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function submitDecision(runId, decision) {
  const res = await fetch(`${API}/runs/${runId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function subscribe(runId, onEvent) {
  const es = new EventSource(`${API}/runs/${runId}/stream`);
  es.onmessage = (msg) => {
    try {
      onEvent(JSON.parse(msg.data));
    } catch (e) {
      console.error(e);
    }
  };
  es.onerror = () => {
    // browser will retry; leave open until closed by caller
  };
  return () => es.close();
}

export { API };
