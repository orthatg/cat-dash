// Roomba panel: one slim row. The robot allows one local connection and answers slowly, so
// this is NOT on the SSE stream: fetch on load, refresh gently while the tab is visible,
// plus a button. Problems are announced to the attention bar through a "roomba:status" event.

import { api } from "./api.js";
import { h, pictogram } from "./dom.js";
import { dayClock, number, relTime, toDate } from "./format.js";

const REFRESH_MS = 60_000;
const TICK_MS = 30_000; // keep "x min ago" fresh without refetching

// ---------- interpretation (pure) ----------

/** Plain-language headline for the robot's state: icon, text, tone (ok | info | warning | critical). */
function describe(s) {
  const err = s.error_text && s.error_text !== "Error" ? s.error_text : null;
  switch (s.state) {
    case "stuck":
      return { icon: "alert", tone: "critical", title: "Stuck, needs a hand", detail: err || "It can't move on its own. Check under it and around the wheels." };
    case "error":
      return { icon: "alert", tone: "critical", title: "Needs attention", detail: err || (s.error_code ? `The robot reported error ${s.error_code}.` : "The robot reported a problem.") };
    case "cleaning":
      return { icon: "robot", tone: "info", title: "Cleaning", detail: "Out on a run." };
    case "paused":
      return { icon: "pause", tone: "info", title: "Paused", detail: "Stopped partway. Press Clean on the robot to continue." };
    case "returning":
      return { icon: "dock", tone: "info", title: "Heading home", detail: "Returning to its dock." };
    case "charging":
      return { icon: "bolt", tone: "ok", title: "Charging", detail: "Resting on the dock." };
    case "docked":
      return { icon: "dock", tone: "ok", title: "Docked", detail: "Ready for the next run." };
    case "idle":
      return { icon: "robot", tone: "info", title: "Idle", detail: "Not on the dock." };
    default:
      return { icon: "help", tone: "info", title: "Status unknown", detail: "The robot didn't say what it's doing." };
  }
}

/** Extra things worth knowing, each with a plain explanation. Never duplicates the headline. */
function notices(s, head) {
  const out = [];
  if (s.bin_full) out.push({ icon: "bin", tone: "warning", text: "Bin is full. Empty it so the next run can finish." });
  else if (s.bin_present === false) out.push({ icon: "bin", tone: "warning", text: "Bin is missing. Put it back before the next run." });
  const shown = new Set([head.detail, head.title].map((t) => t?.toLowerCase()));
  for (const problem of s.problems || []) {
    const lower = String(problem).toLowerCase();
    if (shown.has(lower) || /^bin (full|missing)/.test(lower) || /^error$/.test(lower)) continue;
    if (s.error_text && lower === s.error_text.toLowerCase()) continue;
    out.push({ icon: "alert", tone: "warning", text: String(problem) });
  }
  if (s.battery_percent != null && s.battery_percent < 20 && !["charging", "docked"].includes(s.state)) {
    out.push({ icon: "battery", tone: "warning", text: "Battery is low. It will need the dock soon." });
  }
  return out;
}


function minutesText(min) {
  if (min == null) return null;
  if (min < 60) return `${number(min)} min`;
  return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")} m`;
}

function batteryNode(s) {
  const pct = s ? s.battery_percent : null;
  if (pct == null) return null;
  const low = pct < 20;
  const charging = s.state === "charging";
  const fill = h("span", { class: "rb-batt-fill" });
  fill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  return h("span", { class: "rb-battery", "data-low": String(low) },
    pictogram(charging ? "bolt" : "battery", { size: 20 }),
    h("span", { class: "rb-batt", role: "meter", "aria-label": "Battery", "aria-valuemin": "0", "aria-valuemax": "100",
      "aria-valuenow": String(pct), "aria-valuetext": `${pct}%${charging ? ", charging" : low ? ", low" : ""}` }, fill),
    h("span", { text: `${number(pct)}%` }));
}

// ---------- controller ----------

export function mountRoomba(container) {
  const model = { data: null, phase: "loading", failure: null, busy: false };

  const refreshBtn = h("button", { type: "button", class: "rb-refresh" },
    pictogram("cycle", { size: 18 }), h("span", { class: "rb-refresh-text", text: "Refresh" }));
  const row = h("div", { class: "rb-row", role: "status", "aria-live": "polite" });
  const panel = h("article", { class: "panel panel-roomba", "aria-label": "Roomba" },
    h("header", { class: "panel-head" }, pictogram("robot", { size: 22 }), h("h2", { text: "Roomba" }), refreshBtn), row);
  container.replaceChildren(panel);

  const announce = () => window.dispatchEvent(new CustomEvent("roomba:status", { detail: { data: model.data } }));

  function line(icon, title, detail, level) {
    row.dataset.level = level;
    return h("div", { class: "rb-main" }, h("span", { class: "row-icon" }, pictogram(icon, { size: 24 })),
      h("div", {}, h("p", { class: "row-value", text: title }), detail ? h("p", { class: "note", text: detail }) : null));
  }

  function render() {
    const s = model.data;
    refreshBtn.disabled = model.busy;
    refreshBtn.dataset.busy = String(model.busy);
    refreshBtn.querySelector(".rb-refresh-text").textContent = model.busy ? "Refreshing" : "Refresh";
    if (model.phase === "unconfigured") {
      return row.replaceChildren(line("help", "Not set up yet", "Add the Roomba's address and password to the backend settings.", "info"));
    }
    if (!s) {
      if (model.failure) {
        const creds = /credential|password/i.test(String(model.failure.detail || ""));
        return row.replaceChildren(line("alert", "Can't reach the robot",
          creds ? "It rejected the saved password." : "It may be asleep or off Wi-Fi. Try Refresh in a moment.", "warning"));
      }
      return row.replaceChildren(line("robot", "Checking the robot…", "It can take a few seconds to answer.", "info"));
    }
    const head = describe(s);
    const extra = notices(s, head);
    const level = head.tone === "critical" ? "critical" : extra.length ? "warning" : head.tone;
    const lastAt = toDate(s.last_mission_started_at) || toDate(s.last_command_at);
    const lastMeta = [s.last_mission_minutes != null ? minutesText(s.last_mission_minutes) : null,
      s.last_mission_sqft != null ? `${number(s.last_mission_sqft)} sq ft` : null].filter(Boolean).join(" · ");
    row.replaceChildren(...[
      line(head.icon, head.title, extra.length ? extra[0].text : head.detail, level),
      batteryNode(s),
      h("div", { class: "rb-last" }, h("p", { class: "row-label", text: "Last run" }),
        h("p", { class: "row-value", text: lastAt ? dayClock(lastAt) : "None recorded" }),
        lastMeta ? h("p", { class: "note", text: lastMeta }) : null),
      model.failure ? h("p", { class: "note rb-stale", text: `Can't reach it now; showing ${relTime(s.fetched_at)}.` }) : null,
    ].filter(Boolean));
  }

  let inFlight = null;
  async function load({ force = false } = {}) {
    if (inFlight || (model.phase === "unconfigured" && !force)) return inFlight;
    model.busy = true;
    render();
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
        model.busy = false;
        inFlight = null;
        render();
        announce();
      }
    })();
    return inFlight;
  }

  refreshBtn.addEventListener("click", () => load({ force: true }));
  let timer = null;
  const start = () => { if (!timer && model.phase !== "unconfigured") timer = setInterval(() => load(), REFRESH_MS); };
  const stop = () => { clearInterval(timer); timer = null; };
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return stop();
    const age = model.data ? Date.now() - Date.parse(model.data.fetched_at) : Infinity;
    if (age > REFRESH_MS || model.failure) load();
    start();
  });
  setInterval(() => model.data && !document.hidden && render(), TICK_MS);
  render();
  load().then(() => { if (!document.hidden) start(); });
}
