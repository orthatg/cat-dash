// Thin client for the Cat Dash backend. Same origin by default; set
// window.CAT_DASH_API (e.g. "http://localhost:8000") to point an embedded copy elsewhere.

const BASE = (window.CAT_DASH_API || "").replace(/\/$/, "");

async function get(path, { timeoutMs } = {}) {
  const controller = timeoutMs ? new AbortController() : null;
  const timer = controller && setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${BASE}${path}`, { headers: { Accept: "application/json" }, signal: controller?.signal });
    if (!response.ok) {
      const err = new Error(`${path}: HTTP ${response.status}`);
      err.status = response.status;
      err.detail = await response.json().then((body) => body?.detail, () => undefined);
      throw err;
    }
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

const enc = encodeURIComponent;

export const api = {
  status: () => get("/api/status"),
  litterDaily: (id, days) => get(`/api/litterbox/${enc(id)}/daily?days=${days}`),
  litterDrawer: (id, days) => get(`/api/litterbox/${enc(id)}/drawer?days=${days}`),
  litterCatsDaily: (id, days) => get(`/api/litterbox/${enc(id)}/cats/daily?days=${days}`),
  feederDaily: (id, days) => get(`/api/feeder/${enc(id)}/daily?days=${days}`),
  insights: (days) => get(`/api/insights?days=${days}`),
  // The robot allows one local connection and answers slowly (up to ~15 s): not on the SSE stream.
  roombaStatus: (refresh = false) => get(`/api/roomba/status${refresh ? "?refresh=true" : ""}`, { timeoutMs: 25_000 }),
  feederVisitsDaily: (id, days) => get(`/api/feeder/${enc(id)}/visits/daily?days=${days}`),
};

/**
 * Live status over server-sent events. Calls onStatus(status) on connect and on every
 * change; onState("live" | "connecting" | "down"). EventSource reconnects by itself.
 */
export function subscribe(onStatus, onState) {
  const source = new EventSource(`${BASE}/api/stream`);
  onState("connecting");
  source.onopen = () => onState("live");
  source.onerror = () => onState(source.readyState === EventSource.CLOSED ? "down" : "connecting");
  source.onmessage = (event) => {
    try {
      onStatus(JSON.parse(event.data));
      onState("live");
    } catch (err) {
      console.error("Bad status message", err);
    }
  };
  return () => source.close();
}
