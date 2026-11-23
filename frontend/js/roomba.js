// Roomba tile. The robot allows one local connection and answers slowly, so this is NOT on
// the SSE stream: fetch on load, refresh gently while the tab is visible, plus a button.
// The shell (header, status line, sections) is built once so focus and the open/closed
// "stats" disclosure survive every update, and the loading state has the final shape.

import { api } from "./api.js";
import { h, pictogram } from "./dom.js";
import { clock, dayClock, number, relTime, titleCase, toDate } from "./format.js";

const REFRESH_MS = 60_000;
const TICK_MS = 30_000; // keep "x min ago" fresh without refetching
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

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

function pathNum(obj, ...keys) {
  let v = obj;
  for (const k of keys) v = v && typeof v === "object" ? v[k] : undefined;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function wifiQuality(rssi) {
  if (rssi == null) return null;
  const label = rssi >= -55 ? "Excellent" : rssi >= -67 ? "Good" : rssi >= -75 ? "Fair" : "Weak";
  return label;
}

function runTime(hr, min) {
  if (hr == null) return null;
  return `${number(hr)} h${min ? ` ${min} m` : ""}`;
}

function minutesText(min) {
  if (min == null) return null;
  if (min < 60) return `${number(min)} min`;
  return `${Math.floor(min / 60)} h ${String(min % 60).padStart(2, "0")} m`;
}

/** [[label, value], ...] with only the values the robot actually reported. */
function statItems(s) {
  const sensors = s.sensors || {};
  const hr = pathNum(sensors, "bbrun", "hr");
  const total = s.missions_total ?? pathNum(sensors, "bbmssn", "nMssn");
  const ok = s.missions_ok;
  const items = [
    ["Runs completed", s.missions_ok],
    ["Runs cancelled", s.missions_cancelled],
    ["Runs failed", s.missions_failed],
    ["Success rate", total && ok != null ? `${number((ok / total) * 100)}%` : null],
    ["Total run time", runTime(hr, pathNum(sensors, "bbrun", "min"))],
    ["Area cleaned", pathNum(sensors, "bbrun", "sqft") != null ? `${number(pathNum(sensors, "bbrun", "sqft"))} sq ft` : null],
    ["Times stuck", pathNum(sensors, "bbrun", "nStuck")],
    ["Times docked", pathNum(sensors, "bbchg3", "nDocks")],
    ["Wi-Fi", wifiQuality(s.wifi_rssi)],
  ];
  return items.filter(([, v]) => v != null).map(([k, v]) => [k, typeof v === "number" ? number(v) : v]);
}

// ---------- small view pieces ----------

function fact(icon, label, value, sub, title) {
  return h("div", { class: "rb-fact", title },
    h("div", { class: "rb-fact-label" }, pictogram(icon, { size: 16 }), h("span", { text: label })),
    h("div", { class: `rb-fact-value${value ? "" : " is-empty"}`, text: value || "—" }),
    h("div", { class: "rb-fact-sub", text: sub || " " }));
}

function batteryBlock(s) {
  const pct = s ? s.battery_percent : null;
  const low = pct != null && pct < 20;
  const charging = s && s.state === "charging";
  const fill = h("div", { class: "rb-batt-fill" });
  fill.style.width = `${pct == null ? 0 : Math.max(0, Math.min(100, pct))}%`;
  const attrs = pct == null ? { role: "img", "aria-label": "Battery unknown" } : {
    role: "meter", "aria-label": "Battery", "aria-valuemin": "0", "aria-valuemax": "100",
    "aria-valuenow": String(pct), "aria-valuetext": `${pct}%${charging ? ", charging" : low ? ", low" : ""}`,
  };
  return h("div", { class: "rb-fact rb-battery", "data-low": low ? "true" : "false" },
    h("div", { class: "rb-fact-label" }, pictogram(charging ? "bolt" : "battery", { size: 16 }), h("span", { text: "Battery" })),
    h("div", { class: "rb-batt-row" },
      h("div", { class: "rb-fact-value big-num" }, h("span", { text: pct == null ? "—" : number(pct) }),
        pct == null ? null : h("span", { class: "unit", text: "%" })),
      h("div", { class: "rb-batt", ...attrs }, fill)),
    h("div", { class: "rb-fact-sub" },
      low ? [pictogram("alert", { size: 13 }), " Low"] : charging ? "Charging" : " "));
}

/** "10:30" over "am", from "HH:MM". */
function splitTime(hhmm) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm || "");
  if (!m) return null;
  const d = new Date(2000, 0, 1, Number(m[1]), Number(m[2]));
  const parts = new Intl.DateTimeFormat([], { hour: "numeric", minute: "2-digit" }).formatToParts(d);
  const get = (t) => parts.find((p) => p.type === t)?.value;
  const clockText = `${get("hour")}:${get("minute")}`;
  return { time: clockText, period: get("dayPeriod")?.toLowerCase().replace(/\./g, "") || "", full: clock(d) };
}

function scheduleStrip(s) {
  const entries = (s.schedule || []).filter((e) => e && e.weekday >= 0 && e.weekday <= 6);
  const today = (new Date().getDay() + 6) % 7; // JS Sunday=0 -> Monday=0
  const nextDay = s.next_scheduled_at ? (toDate(s.next_scheduled_at).getDay() + 6) % 7 : null;
  if (!entries.length) return h("p", { class: "rb-note muted", text: "No weekly schedule set on the robot." });
  const items = DAYS.map((name, i) => {
    const e = entries.find((x) => x.weekday === i && x.enabled) || entries.find((x) => x.weekday === i);
    const on = !!(e && e.enabled);
    const t = on ? splitTime(e.time) : null;
    const label = `${name}: ${on ? (t ? `cleans at ${t.full}` : "scheduled") : "off"}${i === today ? ", today" : ""}`;
    return h("li", { class: "rb-day", "data-on": on ? "true" : "false", "data-today": i === today ? "true" : "false",
      "aria-label": label, "aria-current": i === today ? "date" : null },
    h("span", { class: "rb-day-name", text: name.slice(0, 3), "aria-hidden": "true" }),
    on
      ? h("span", { class: "rb-day-time", "aria-hidden": "true" }, pictogram("check", { size: 14 }),
        h("span", { class: "rb-t", text: t ? t.time : "" }), h("span", { class: "rb-ap", text: t ? t.period : "" }))
      : h("span", { class: "rb-day-time off", "aria-hidden": "true" }, h("span", { class: "rb-t", text: "Off" })),
    nextDay === i && on ? h("span", { class: "rb-next-dot", "aria-hidden": "true", title: "Next run" }) : null);
  });
  return h("ol", { class: "rb-week", "aria-label": "Weekly cleaning schedule" }, items);
}

// ---------- controller ----------

export function mountRoomba(container) {
  const model = { data: null, fetchedAt: null, phase: "loading", failure: null, busy: false, liveKey: "" };

  const refreshBtn = h("button", { type: "button", class: "rb-refresh" },
    pictogram("cycle", { size: 16 }), h("span", { class: "rb-refresh-text", text: "Refresh" }));
  const updated = h("span", { class: "caption rb-updated" });
  const live = h("div", { class: "rb-status", role: "status", "aria-live": "polite", "aria-atomic": "true" });
  const stale = h("div", { class: "rb-stale", hidden: true });
  const facts = h("div", { class: "rb-facts" });
  const week = h("div", { class: "rb-week-wrap" });
  const statsGrid = h("dl", { class: "rb-stats-grid" });
  const stats = h("details", { class: "rb-stats", hidden: true },
    h("summary", {}, h("span", { class: "rb-stats-label", text: "Robot stats (for fun)" })), statsGrid);
  const title = h("h2", { class: "tile-title", id: "rb-title" }, pictogram("robot"), h("span", { text: "Roomba" }));
  const tile = h("article", { class: "tile tile-roomba", "aria-labelledby": "rb-title", "aria-busy": "true" },
    h("div", { class: "rb-head" }, title, h("div", { class: "rb-head-end" }, updated, refreshBtn)),
    live, stale, facts,
    h("div", { class: "rb-section" }, h("h3", { class: "rb-h", text: "Weekly schedule" }), week),
    stats);
  container.replaceChildren(tile);

  function setLive(key, node) {
    if (key === model.liveKey) return; // don't re-announce unchanged state
    model.liveKey = key;
    live.replaceChildren(node);
  }

  function skeleton() {
    live.dataset.tone = "info";
    setLive("loading", h("div", { class: "rb-headline" },
      h("span", { class: "rb-badge" }, pictogram("robot", { size: 22 })),
      h("div", {}, h("div", { class: "rb-title skeleton", text: "Checking the robot" }),
        h("div", { class: "rb-detail", text: "It can take a few seconds to answer." }))));
    facts.replaceChildren(batteryBlock(null), fact("clock", "Last run", null), fact("calendar", "Next run", null));
    week.replaceChildren(h("div", { class: "rb-week-skel skeleton" }));
    stats.hidden = true;
  }

  function unconfigured() {
    tile.dataset.tone = "info";
    live.dataset.tone = "info";
    setLive("unconfigured", h("div", { class: "rb-headline" },
      h("span", { class: "rb-badge" }, pictogram("robot", { size: 22 })),
      h("div", {}, h("div", { class: "rb-title", text: "Not set up yet" }),
        h("div", { class: "rb-detail", text: "Add the Roomba's address and password to the backend settings, then press Refresh." }))));
    facts.replaceChildren();
    week.parentElement.hidden = true;
    stats.hidden = true;
    stale.hidden = true;
    updated.textContent = "";
  }

  function unreachable() {
    live.dataset.tone = "warning";
    const creds = /credential|password/i.test(String(model.failure?.detail || ""));
    setLive("unreachable", h("div", { class: "rb-headline" },
      h("span", { class: "rb-badge" }, pictogram("alert", { size: 22 })),
      h("div", {}, h("div", { class: "rb-title", text: "Can't reach the robot" }),
        h("div", { class: "rb-detail", text: creds
          ? "The robot rejected the saved password."
          : "It may be asleep, off Wi-Fi, or connected to another app. Try again in a moment." }))));
    facts.replaceChildren();
    week.parentElement.hidden = true;
    stats.hidden = true;
  }

  function render() {
    const s = model.data;
    refreshBtn.disabled = model.busy;
    refreshBtn.setAttribute("aria-busy", String(model.busy));
    refreshBtn.dataset.busy = String(model.busy);
    refreshBtn.querySelector(".rb-refresh-text").textContent = model.busy ? "Refreshing" : "Refresh";
    tile.setAttribute("aria-busy", String(model.busy && !s));
    if (model.phase === "unconfigured") return unconfigured();
    week.parentElement.hidden = false;
    if (!s) {
      tile.dataset.tone = model.failure ? "warning" : "info";
      updated.textContent = "";
      stale.hidden = true;
      return model.failure ? unreachable() : skeleton();
    }

    const head = describe(s);
    const extra = notices(s, head);
    const tone = head.tone === "critical" ? "critical" : extra.length ? "warning" : head.tone;
    tile.dataset.tone = tone;
    live.dataset.tone = tone;
    const key = JSON.stringify([s.state, s.error_code, head.detail, extra.map((e) => e.text)]);
    setLive(key, h("div", {},
      h("div", { class: "rb-headline" },
        h("span", { class: "rb-badge" }, pictogram(head.icon, { size: 22 })),
        h("div", {}, h("div", { class: "rb-title", text: head.title }), h("div", { class: "rb-detail", text: head.detail }))),
      extra.length ? h("ul", { class: "rb-notices" }, extra.map((e) =>
        h("li", { "data-tone": e.tone }, pictogram(e.icon, { size: 16 }), h("span", { text: e.text })))) : null));

    // Stale: the last refresh failed but we still have good data
    stale.hidden = !model.failure;
    if (model.failure) {
      stale.replaceChildren(pictogram("alert", { size: 16 }),
        h("span", { text: `Can't reach the robot right now. Showing what it said ${relTime(s.fetched_at)}.` }));
    }
    updated.textContent = model.failure ? `Last update ${relTime(s.fetched_at)}` : `Updated ${relTime(s.fetched_at)}`;
    updated.dataset.stale = String(!!model.failure);

    // The robot reports when the last mission started; fall back to the last command time.
    const lastAt = toDate(s.last_mission_started_at) || toDate(s.last_command_at);
    const lastMeta = [s.last_mission_minutes != null ? minutesText(s.last_mission_minutes) : null,
      s.last_mission_sqft != null ? `${number(s.last_mission_sqft)} sq ft` : null].filter(Boolean).join(" · ");
    const initiator = s.last_command_initiator ? ` (${titleCase(s.last_command_initiator)})` : "";
    const lastTitle = s.last_mission_started_at ? "When the last cleaning mission started."
      : lastAt && s.last_command ? `Last command: ${s.last_command}${initiator}. No mission start time was reported, so this is when the robot last got a command.` : undefined;
    const next = toDate(s.next_scheduled_at);
    facts.replaceChildren(
      batteryBlock(s),
      fact("clock", "Last run", lastAt ? dayClock(lastAt) : null, lastMeta || (lastAt ? relTime(lastAt) : "No run recorded"), lastTitle),
      fact("calendar", "Next run", next ? dayClock(next) : null, next ? relTime(next) : "Nothing scheduled"));
    week.replaceChildren(scheduleStrip(s));

    const items = statItems(s);
    stats.hidden = items.length === 0;
    statsGrid.replaceChildren(...items.map(([k, v]) => h("div", { class: "rb-stat" }, h("dt", { text: k }), h("dd", { text: v }))));
  }

  let inFlight = null;
  async function load({ force = false } = {}) {
    if (inFlight || model.phase === "unconfigured" && !force) return inFlight;
    model.busy = true;
    render();
    inFlight = (async () => {
      try {
        const data = await api.roombaStatus(force);
        model.data = data;
        model.failure = null;
        model.phase = "ok";
      } catch (err) {
        if (err.status === 503) { model.phase = "unconfigured"; model.data = null; model.failure = null; }
        else { model.failure = { status: err.status, detail: err.detail }; if (model.phase !== "ok") model.phase = "error"; }
        if (err.status !== 503 && err.status !== 502 && err.status !== 504 && err.name !== "AbortError") console.warn("Roomba:", err);
      } finally {
        model.busy = false;
        inFlight = null;
        render();
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
