// Roomba status as a data source for the Cleaning card and the alert list. The robot allows
// one local connection and answers slowly, so this is NOT on the SSE stream: fetch on load,
// refresh gently while the tab is visible, and report every change through `onChange`.

import { api } from "./api.js";

const REFRESH_MS = 60_000;

/** Plain-language state: the words the Cleaning card shows for what the robot is doing. */
export function roombaState(s) {
  switch (s?.state) {
    case "stuck": return { word: "Stuck", tone: "critical" };
    case "error": return { word: "Needs attention", tone: "critical" };
    case "cleaning": return { word: "Cleaning now", tone: "info" };
    case "paused": return { word: "Paused", tone: "info" };
    case "returning": return { word: "Heading home", tone: "info" };
    case "charging": return { word: "Docked", tone: "ok" };
    case "docked": return { word: "Docked", tone: "ok" };
    case "idle": return { word: "Off the dock", tone: "info" };
    default: return { word: "Status unknown", tone: "info" };
  }
}

/**
 * Watch the Roomba. `onChange({ phase, data, failure })` runs after every fetch:
 * phase "loading" | "ok" | "error" | "unconfigured"; `data` is the last good status (kept
 * while the robot can't be reached, so the card can still say when it last ran).
 */
export function watchRoomba(onChange) {
  const model = { phase: "loading", data: null, failure: null };
  let inFlight = null;

  async function load({ force = false } = {}) {
    if (inFlight || (model.phase === "unconfigured" && !force)) return inFlight;
    inFlight = (async () => {
      try {
        model.data = await api.roombaStatus(force);
        model.failure = null;
        model.phase = "ok";
      } catch (err) {
        if (err.status === 503) { model.phase = "unconfigured"; model.data = null; model.failure = null; }
        else { model.failure = { status: err.status, detail: err.detail }; if (model.phase !== "ok") model.phase = "error"; }
        if (![502, 503, 504].includes(err.status) && err.name !== "AbortError") console.warn("Roomba:", err);
      } finally {
        inFlight = null;
        onChange({ ...model });
      }
    })();
    return inFlight;
  }

  let timer = null;
  const start = () => { if (!timer && model.phase !== "unconfigured") timer = setInterval(() => load(), REFRESH_MS); };
  const stop = () => { clearInterval(timer); timer = null; };
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return stop();
    const age = model.data ? Date.now() - Date.parse(model.data.fetched_at) : Infinity;
    if (age > REFRESH_MS || model.failure) load();
    start();
  });
  onChange({ ...model });
  load().then(() => { if (!document.hidden) start(); });
  return { refresh: () => load({ force: true }) };
}
