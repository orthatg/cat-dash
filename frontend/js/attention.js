// What needs a person? Pure rules (no DOM) that turn device status into a short list of
// problems, worst first, plus the attention bar that shows them.

import { h, pictogram } from "./dom.js";
import { dayClock, number } from "./format.js";

const MIN = 60_000;
/** The box waits this long after the last visit before it cleans. */
export const CLEAN_WAIT_MIN = 10;
/** A clean should have started by now; if not, something is wrong. */
export const CLEAN_OVERDUE_MIN = 20;
export const DRAWER_FULL_PERCENT = 95;

// Status codes where the box can't work until someone steps in.
const FAULTS = {
  BR: ["Bonnet removed", "Put the bonnet back on."],
  CSF: ["Cat sensor fault", "Wipe the sensor and restart the box."],
  SCF: ["Cat sensor fault at startup", "Wipe the sensor and restart the box."],
  DHF: ["Dump and home position fault", "Check the globe for clumps, then power-cycle it."],
  DPF: ["Dump position fault", "Check the globe for clumps, then power-cycle it."],
  HPF: ["Home position fault", "Check the globe for clumps, then power-cycle it."],
  OTF: ["Globe is jammed", "Clear anything stuck in the globe."],
  PD: ["Pinch detected", "Check the globe opening is clear."],
  SPF: ["Pinch detected at startup", "Check the globe opening is clear."],
};

const minutesSince = (iso, now) => (iso ? Math.max(0, Math.round((now - Date.parse(iso)) / MIN)) : null);

export function agoText(minutes) {
  if (minutes == null) return "never";
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 48 * 60) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} days ago`;
}

/**
 * Where the clean cycle is relative to the last visit.
 * kind: "clean" (cleaned since the last visit) | "running" | "waiting" | "overdue" | "unknown"
 */
export function cycleState(box, now = Date.now()) {
  const visit = box.last_cat_detected_at ? Date.parse(box.last_cat_detected_at) : null;
  const clean = box.last_clean_cycle_at ? Date.parse(box.last_clean_cycle_at) : null;
  const sinceVisit = visit ? Math.round((now - visit) / MIN) : null;
  const sinceClean = clean ? Math.round((now - clean) / MIN) : null;
  if (box.status_code === "CCP" || box.status_code === "EC") return { kind: "running", sinceVisit, sinceClean };
  if (visit == null || (clean != null && clean >= visit)) return { kind: visit == null && clean == null ? "unknown" : "clean", sinceVisit, sinceClean };
  if (box.status_code === "CD") return { kind: "waiting", sinceVisit, sinceClean, minutesLeft: CLEAN_WAIT_MIN };
  if (sinceVisit < CLEAN_WAIT_MIN) return { kind: "waiting", sinceVisit, sinceClean, minutesLeft: CLEAN_WAIT_MIN - sinceVisit };
  if (sinceVisit <= CLEAN_OVERDUE_MIN) return { kind: "waiting", sinceVisit, sinceClean, minutesLeft: 0 };
  return { kind: "overdue", sinceVisit, sinceClean };
}

/** The drawer is the box's own concern: full, almost full, or past its usual empty date. */
export function drawerLevel(box, now = Date.now()) {
  const pct = box.waste_drawer_percent ?? 0;
  const due = box.drawer_needs_emptying_at ? Date.parse(box.drawer_needs_emptying_at) : null;
  if (box.waste_drawer_full || box.waste_drawer_state === "full" || pct >= DRAWER_FULL_PERCENT) return "full";
  if ((due && due <= now) || (box.drawer_usual_empty_percent && pct >= box.drawer_usual_empty_percent)) return "due";
  return "ok";
}

export function litterWords(state) {
  return { OPTIMAL: "Good", OVERFILL: "Overfilled", REFILL: "Refill soon", LOW: "Low", EMPTY: "Empty" }[state] || null;
}

/** Problems with one litter box. */
export function litterProblems(box, now = Date.now()) {
  const out = [];
  const add = (level, icon, title, hint) => out.push({ level, icon, title, hint, source: "litter" });
  const code = box.status_code;

  if (box.online === false || code === "OFFLINE") {
    add("critical", "wifi", "Litter box is offline", "Check its power and Wi-Fi.");
    return out; // nothing else about it can be trusted
  }
  if (box.powered_on === false || code === "OFF") add("critical", "alert", "Litter box is switched off", "Turn it on at the box or in the Whisker app.");

  if (FAULTS[code]) add("critical", "alert", FAULTS[code][0], FAULTS[code][1]);
  else if (code === "P") add("warning", "pause", "Clean cycle is paused", "A cat may be in the way. It should resume on its own.");

  const cycle = cycleState(box, now);
  const drawer = drawerLevel(box, now);
  const pct = box.waste_drawer_percent ?? 0;
  if (drawer === "full" || code === "DFS" || code === "SDF") {
    const visited = cycle.kind !== "clean" && cycle.sinceVisit != null;
    add("critical", "drawer", `Waste drawer is full (${number(pct)}%)`,
      visited ? "A cat has visited since the last clean, and the box won't clean until you empty the drawer."
        : "The box won't clean until you empty the drawer.");
  } else if (code === "DF1" || code === "DF2") {
    add("warning", "drawer", "Waste drawer is almost full", "Empty it before the next few cycles.");
  } else if (drawer === "due") {
    add("warning", "drawer", "Time to empty the waste drawer",
      box.drawer_needs_emptying_at ? `It was due ${dayClock(box.drawer_needs_emptying_at)}.` : `It's at ${number(pct)}%.`);
  }

  // A full drawer already explains a missed clean, so don't list both.
  if (cycle.kind === "overdue" && drawer !== "full" && !FAULTS[code] && !box.sleeping) {
    add("critical", "broom", "Clean cycle didn't run",
      `Last visit was ${cycle.sinceVisit} min ago. It should start ${CLEAN_WAIT_MIN} min after a visit.`);
  }

  if (box.litter_level_state === "EMPTY") add("critical", "litter", "Out of litter", "Refill the box.");
  else if (box.litter_level_state === "REFILL" || box.litter_level_state === "LOW") {
    add("warning", "litter", "Litter is running low", `It's at ${number(box.litter_level_percent ?? 0)}%.`);
  }
  return out;
}

export function feederProblems(feeder) {
  const out = [];
  const add = (level, icon, title, hint) => out.push({ level, icon, title, hint, source: "feeder" });
  if (feeder.online === false) add("warning", "wifi", `${feeder.name} feeder is offline`, "Check its power and Wi-Fi.");
  if (feeder.food_low) add("warning", "bowlEmpty", `${feeder.name} feeder is low on food`, "Top up the hopper.");
  for (const p of feeder.problems || []) add("warning", "alert", `${feeder.name} feeder: ${String(p).replace(/_/g, " ").toLowerCase()}`, "");
  return out;
}

/** Roomba problems, from the status the roomba tile fetched. */
export function roombaProblems(s) {
  if (!s) return [];
  const out = [];
  const add = (level, icon, title, hint) => out.push({ level, icon, title, hint, source: "roomba" });
  if (s.state === "stuck") add("critical", "robot", "Roomba is stuck", s.error_text && s.error_text !== "Error" ? s.error_text : "Check under it and around the wheels.");
  else if (s.state === "error") add("critical", "robot", "Roomba needs attention", s.error_text && s.error_text !== "Error" ? s.error_text : "It reported a problem.");
  if (s.bin_full) add("warning", "bin", "Roomba's bin is full", "Empty it so the next run can finish.");
  else if (s.bin_present === false) add("warning", "bin", "Roomba's bin is missing", "Put it back before the next run.");
  return out;
}

export function collectProblems({ status, roomba }, now = Date.now()) {
  const all = [
    ...(status?.litter_boxes || []).flatMap((b) => litterProblems(b, now)),
    ...(status?.feeders || []).flatMap(feederProblems),
    ...roombaProblems(roomba),
  ];
  const rank = { critical: 0, warning: 1 };
  return all.sort((a, b) => rank[a.level] - rank[b.level]);
}

// ---------- the bar ----------

/** One line when all is well: what's coming up next. */
function calmLine(status) {
  const box = status?.litter_boxes?.[0];
  if (box?.drawer_needs_emptying_at) return `Empty the drawer by ${dayClock(box.drawer_needs_emptying_at)}.`;
  return "Nothing needs you right now.";
}

export function renderAttention(container, problems, status) {
  const worst = problems[0]?.level;
  container.dataset.level = worst || "ok";
  if (!problems.length) {
    container.replaceChildren(h("div", { class: "att-calm" }, pictogram("check", { size: 28 }),
      h("p", { class: "att-calm-text" }, h("strong", { text: "All clear. " }), h("span", { text: calmLine(status) }))));
  } else {
    container.replaceChildren(h("ul", { class: "att-list" }, problems.map((p) =>
      h("li", { class: "att-item", "data-level": p.level },
        pictogram(p.icon, { size: 32 }),
        h("div", { class: "att-body" },
          h("p", { class: "att-title", text: p.title }),
          p.hint ? h("p", { class: "att-hint", text: p.hint }) : null)))));
  }
  const n = problems.length;
  document.title = n ? `(${n}) Cat Dash` : "Cat Dash";
}

