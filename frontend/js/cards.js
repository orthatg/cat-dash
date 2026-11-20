// "Right now" cards. Built with DOM APIs + textContent (device and cat names are data).

import { clock, cups, dayClock, duration, number, plural, relTime, titleCase } from "./format.js";

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const SVG_NS = "http://www.w3.org/2000/svg";
const ICONS = {
  good: "M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Zm3.1 4.6-3.6 4.5a.75.75 0 0 1-1.1.06L4.5 8.8a.75.75 0 1 1 1.06-1.06l1.3 1.3 3.06-3.83a.75.75 0 0 1 1.17.94Z",
  warning: "M8.9 2.1a1 1 0 0 0-1.8 0L1.2 12.6A1 1 0 0 0 2.1 14h11.8a1 1 0 0 0 .9-1.4L8.9 2.1ZM8 5.2a.75.75 0 0 1 .75.75v3.3a.75.75 0 0 1-1.5 0v-3.3A.75.75 0 0 1 8 5.2Zm0 6.9a.9.9 0 1 1 0-1.8.9.9 0 0 1 0 1.8Z",
  critical: "M5.3 1.5h5.4l3.8 3.8v5.4l-3.8 3.8H5.3l-3.8-3.8V5.3l3.8-3.8Zm.9 3.6a.75.75 0 0 0-1.06 1.06L6.94 8l-1.8 1.84a.75.75 0 1 0 1.06 1.06L8 9.06l1.84 1.84a.75.75 0 1 0 1.06-1.06L9.06 8l1.84-1.84a.75.75 0 0 0-1.06-1.06L8 6.94 6.2 5.1Z",
  neutral: "M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Zm0 3a.9.9 0 1 1 0 1.8.9.9 0 0 1 0-1.8Zm.75 6.75a.75.75 0 0 1-1.5 0V8a.75.75 0 0 1 1.5 0v3.25Z",
};

export function icon(status) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("class", "pill-icon");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", ICONS[status] || ICONS.neutral);
  path.setAttribute("fill", "currentColor");
  svg.append(path);
  return svg;
}

function pill(status, label) {
  return h("span", { class: "pill", "data-status": status }, icon(status), h("span", { text: label }));
}

function stat(label, value, sub) {
  return h("div", { class: "stat" },
    h("dt", { text: label }),
    h("dd", {}, value, sub ? h("span", { class: "sub", text: ` ${sub}` }) : null));
}

function meter(label, percent, valueText, status) {
  const clamped = Math.max(0, Math.min(100, percent ?? 0));
  return h("div", { class: "meter", "data-status": status || "normal" },
    h("div", { class: "meter-row" }, h("span", { text: label }), h("span", { text: valueText })),
    h("div", {
      class: "meter-track", role: "meter", "aria-label": label,
      "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(clamped)),
    }, h("div", { class: "meter-fill", style: `width:${clamped}%` })));
}

// --- Litter box ---

// pylitterbot status codes -> reserved status classes (always shown with icon + label).
const LITTER_GOOD = new Set(["RDY", "CCC"]);
const LITTER_BUSY = new Set(["CCP", "CD", "CST", "EC"]);
const LITTER_WARN = new Set(["DF1", "DF2", "DFS", "P", "CSI", "BR", "SDF", "DHF", "DPF"]);

function litterStatus(box) {
  if (!box.online) return ["critical", "Offline"];
  if (!box.powered_on) return ["critical", "Off"];
  const code = box.status_code;
  const label = box.status_text || titleCase(code || "Unknown");
  if (LITTER_GOOD.has(code)) return ["good", label];
  if (LITTER_BUSY.has(code)) return ["neutral", label];
  if (LITTER_WARN.has(code)) return ["warning", label];
  return ["critical", label];
}

function drawerStatus(box) {
  if (box.waste_drawer_full || box.waste_drawer_state === "full") return "critical";
  if (box.waste_drawer_percent >= 80) return "warning";
  return "normal";
}

export function litterCard(box, drawer, catColors = {}) {
  const [status, label] = litterStatus(box);
  const state = box.waste_drawer_state;
  const drawerHero = state === "empty" ? "Empty" : state === "full" ? "Full" : `${number(box.waste_drawer_percent)}%`;
  const emptiedLine = box.last_emptied_at
    ? `Emptied ${relTime(box.last_emptied_at)} · ${plural(box.cycles_since_emptied ?? 0, "cycle")} since`
    : "No empty recorded yet";
  const usual = drawer?.average_days_between_empties
    ? `every ~${number(drawer.average_days_between_empties, 1)} days`
    : null;

  const notes = [];
  if (box.sleeping) notes.push(["neutral", "Sleep mode: automatic cycles paused"]);
  if (box.litter_level_state && box.litter_level_state !== "OPTIMAL") {
    notes.push(["warning", `Litter level ${titleCase(box.litter_level_state)}`]);
  }

  return h("article", { class: "card", "aria-label": `${box.name} litter box` },
    h("div", { class: "card-head" },
      h("div", {}, h("h3", { class: "card-title", text: box.name }), h("p", { class: "card-sub", text: box.model })),
      pill(status, label)),
    h("div", {},
      h("div", { class: "hero" }, h("span", { class: "hero-value", text: drawerHero }),
        h("span", { class: "hero-label", text: "waste drawer" })),
      h("p", { class: "card-sub", text: emptiedLine })),
    meter("Waste drawer", box.waste_drawer_percent, `${number(box.waste_drawer_percent)}%`, drawerStatus(box)),
    h("dl", { class: "stats" },
      stat("Litter level", `${number(box.litter_level_percent)}%`, box.litter_level_state ? titleCase(box.litter_level_state) : null),
      stat("Last visit", box.last_cat || relTime(box.last_cat_detected_at),
        box.last_cat ? `${relTime(box.last_cat_detected_at)}, ${number(box.cat_weight_lbs, 2)} lb` : null),
      stat("Last clean cycle", relTime(box.last_clean_cycle_at)),
      stat("Drawer usually emptied", usual || "—"),
      stat("Lifetime cycles", number(box.lifetime_cycles))),
    box.cats?.length ? catList(box.cats, catColors) : null,
    notes.length ? notesList(notes) : null);
}

/** "● Zora 5.4 lb  ● Maui 14.7 lb": the cats Whisker tells apart by weight. */
function catList(cats, catColors) {
  return h("ul", { class: "cat-list", "aria-label": "Cats using this box" },
    cats.map((cat) => {
      const key = h("span", { class: "cat-key" });
      key.style.background = catColors[cat.name] || "var(--text-muted)";
      return h("li", {}, key, h("strong", { text: cat.name }), h("span", { text: `${number(cat.weight_lbs, 1)} lb` }));
    }));
}

// --- Feeder ---

function feederStatus(feeder) {
  if (feeder.online === false) return ["critical", "Offline"];
  if (feeder.problems?.length) return ["critical", "Needs attention"];
  if (feeder.food_low === true) return ["warning", "Food low"];
  if (feeder.food_low === false) return ["good", "Food OK"];
  return ["neutral", "Food unknown"];
}

const PROBLEM_TEXT = {
  lid_blocked: "Lid blocked",
  dispenser_blocked: "Dispenser blocked",
  stopped_working: "Stopped working",
  rotor_stuck: "Rotor stuck",
};

/** cats: names of the cats that eat here (RFID), shown as the card title. */
export function feederCard(feeder, cats = [], catColors = {}) {
  const [status, label] = feederStatus(feeder);
  const notes = (feeder.problems || []).map((p) => ["critical", PROBLEM_TEXT[p] || titleCase(p)]);
  if (feeder.desiccant_days_left != null && feeder.desiccant_days_left < 0) {
    notes.push(["warning", `Desiccant overdue by ${number(-feeder.desiccant_days_left)} days`]);
  } else if (feeder.desiccant_days_left != null && feeder.desiccant_days_left <= 3) {
    notes.push(["warning", `Replace desiccant in ${number(feeder.desiccant_days_left)} days`]);
  }
  if (feeder.battery_percent != null && feeder.battery_percent <= 20) {
    notes.push(["warning", `Battery ${number(feeder.battery_percent)}%`]);
  }

  const lastFeed = feeder.last_feed_at
    ? `${relTime(feeder.last_feed_at)}`
    : "—";
  const nextFeed = feeder.next_feed_at ? dayClock(feeder.next_feed_at) : "No schedule";

  const feederLine = `${feeder.name} · ${feeder.model || "Feeder"}`;
  const title = cats.length
    ? h("h3", { class: "card-title cat-title" }, cats.map((cat, i) => {
      const key = h("span", { class: "cat-key", "aria-hidden": "true" });
      key.style.background = catColors[cat] || "var(--text-muted)";
      return h("span", { class: "cat-name" }, i ? h("span", { class: "amp", text: "&" }) : null, key, h("span", { text: cat }));
    }))
    : h("h3", { class: "card-title", text: feeder.name });

  return h("article", { class: "card", "aria-label": `${cats.length ? `${cats.join(" and ")}'s feeder, ` : ""}${feeder.name}` },
    h("div", { class: "card-head" },
      h("div", {}, title, h("p", { class: "card-sub", text: cats.length ? feederLine : feeder.model || "Feeder" })),
      pill(status, label)),
    h("div", {},
      h("div", { class: "hero" },
        h("span", { class: "hero-value", text: number(feeder.today_dispensed_portions ?? 0) }),
        h("span", { class: "hero-label", text: `${feeder.today_dispensed_portions === 1 ? "portion" : "portions"} today` })),
      h("p", { class: "card-sub", text: `${cups(feeder.today_dispensed_portions ?? 0)} in ${plural(feeder.today_feed_count ?? 0, "feed")}` })),
    h("dl", { class: "stats" },
      stat("Last feed", lastFeed, feeder.last_feed_portions != null ? `(${plural(feeder.last_feed_portions, "portion")})` : null),
      stat("Next feed", nextFeed, feeder.next_feed_portions != null ? `(${plural(feeder.next_feed_portions, "portion")})` : null),
      stat("Cat visits today", number(feeder.today_eat_count ?? 0)),
      stat("Time eating today", duration(feeder.today_eat_seconds))),
    notes.length ? notesList(notes) : null);
}

function notesList(notes) {
  return h("ul", { class: "notes" },
    notes.map(([status, text]) => h("li", { "data-status": status }, icon(status), h("span", { text }))));
}

export function errorsBanner(container, status) {
  container.replaceChildren();
  const messages = [];
  for (const [name, message] of Object.entries(status.errors || {})) {
    messages.push(`${name === "litterrobot" ? "Litter-Robot" : name === "petlibro" ? "Petlibro" : name}: ${message}`);
  }
  for (const [name, ok] of Object.entries(status.configured || {})) {
    if (!ok) messages.push(`${name === "litterrobot" ? "Litter-Robot" : "Petlibro"} isn't configured (see backend/README.md).`);
  }
  container.hidden = messages.length === 0;
  for (const message of messages) container.append(h("p", { text: message }));
}

export { clock };
