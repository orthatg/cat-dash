// Thin client for the Cat Dash backend. Same origin by default; set
// window.CAT_DASH_API (e.g. "http://localhost:8000") to point an embedded copy elsewhere.

const BASE = (window.CAT_DASH_API || "").replace(/\/$/, "");

async function get(path) {
  const response = await fetch(`${BASE}${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return response.json();
}

const enc = encodeURIComponent;

export const api = {
  status: () => get("/api/status"),
  litterDaily: (id, days) => get(`/api/litterbox/${enc(id)}/daily?days=${days}`),
  litterDrawer: (id, days) => get(`/api/litterbox/${enc(id)}/drawer?days=${days}`),
  feederDaily: (id, days) => get(`/api/feeder/${enc(id)}/daily?days=${days}`),
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
