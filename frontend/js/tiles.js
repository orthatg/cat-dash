// The live panels: waste drawer (the hero), litter level, last visit and clean cycle, feeders.
// Insight tiles (patterns) live at the bottom and sit behind "History".

import { columnChart } from "./charts.js";
import { agoText, cycleState, drawerLevel, litterWords } from "./attention.js";
import { catAvatar, h, pictogram } from "./dom.js";
import { dayClock, number } from "./format.js";

/** Redraw a chart whenever its box changes width. */
function responsive(el, draw) {
  let last = 0;
  new ResizeObserver(() => {
    const w = el.clientWidth;
    if (w && Math.abs(w - last) > 4) {
      last = w;
      draw(el);
    }
  }).observe(el);
  return el;
}

function panelHead(icon, label, aside) {
  return h("header", { class: "panel-head" }, pictogram(icon, { size: 22 }), h("h2", { text: label }), aside || null);
}

/** A vertical gauge: a filled column, with an optional mark (the usual level) across it. */
function gauge({ kind, percent, label, valuetext, mark }) {
  const level = Math.max(0, Math.min(100, percent ?? 0));
  const fill = h("div", { class: "gauge-fill" });
  fill.style.height = `${level}%`;
  const body = h("div", { class: "gauge-body" }, fill);
  const node = h("div", {
    class: `gauge gauge-${kind}`, role: "meter", "aria-label": label,
    "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(level)), "aria-valuetext": valuetext,
  }, body);
  if (mark) {
    const line = h("div", { class: "gauge-mark" }, h("span", { text: `${number(mark)}%` }));
    line.style.bottom = `${Math.min(100, mark)}%`;
    node.append(line);
  }
  return node;
}

// ---------- litter box ----------

/** The shared shape of the three main panes: header, a graphic, then a small label over one big value. */
function pane({ cls, level, aria, icon, title, graphic, label, value, valueIcon, quiet, note }) {
  return h("article", { class: `panel pane ${cls}`, "data-level": level, "aria-label": aria },
    panelHead(icon, title),
    h("div", { class: "pane-graphic" }, graphic),
    h("p", { class: "pane-read" },
      h("span", { class: "pane-label", text: label }),
      h("span", { class: `pane-value${quiet ? " quiet" : ""}` }, valueIcon || null, h("span", { text: value }))),
    note ? h("p", { class: "pane-note", text: note }) : null);
}

/** The waste drawer: a ring for how full, and the one thing to act on, when to empty it. */
export function drawerPanel(box, now = Date.now()) {
  const pct = Math.max(0, box.waste_drawer_percent ?? 0);
  const usual = box.drawer_usual_empty_percent;
  const level = drawerLevel(box, now);
  const due = box.drawer_needs_emptying_at;
  let when;
  if (level === "full") when = { label: "Empty it", value: "Now" };
  else if (level === "due") when = { label: "Empty it", value: "Today" };
  else if (due) when = { label: "Empty by", value: dayClock(due) };
  else when = { label: "Empty by", value: "Not enough history yet", quiet: true };
  return pane({
    cls: "pane-drawer", level, icon: "drawer", title: "Waste drawer",
    aria: `Waste drawer ${number(pct)}% full. ${when.label} ${when.value}.`,
    graphic: ring({ percent: pct, label: "Waste drawer", mark: usual,
      markTitle: usual ? `Usually emptied at ${number(usual)}%` : null,
      valuetext: `${number(pct)}% full${usual ? `, usually emptied at ${number(usual)}%` : ""}` }),
    ...when,
  });
}

/** A ring that fills clockwise from 12 o'clock, with an optional tick at `mark` percent. */
function ring({ percent, label, valuetext, mark, markTitle }) {
  const NS = "http://www.w3.org/2000/svg";
  const level = Math.max(0, Math.min(100, percent ?? 0));
  const el = (tag, attrs) => {
    const node = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    return node;
  };
  const svg = el("svg", {
    viewBox: "0 0 140 140", class: "ring", role: "meter", "aria-label": label, "aria-valuemin": "0", "aria-valuemax": "100",
    "aria-valuenow": String(Math.round(level)), "aria-valuetext": valuetext,
  });
  const arc = (cls) => el("circle", { class: cls, cx: "70", cy: "70", r: "56", pathLength: "100", transform: "rotate(-90 70 70)" });
  const fill = arc("ring-fill");
  // Round caps stick out half a stroke past each end of the dash, so pull the dash in by that
  // much on both ends: the visible fill then spans exactly 0 to `level`.
  const cap = (7.5 / (2 * Math.PI * 56)) * 100;
  fill.setAttribute("stroke-dasharray", `${Math.max(0, level - 2 * cap)} 100`);
  fill.setAttribute("stroke-dashoffset", String(-cap));
  if (level <= 0) fill.setAttribute("visibility", "hidden");
  const text = el("text", { class: "ring-num", x: "70", y: "70", "text-anchor": "middle", "dominant-baseline": "central" });
  const unit = el("tspan", { class: "ring-unit" });
  unit.textContent = "%";
  text.append(document.createTextNode(number(level)), unit);
  svg.append(arc("ring-track"), fill);
  if (mark) {
    const tick = el("line", { class: "ring-mark", x1: "70", y1: "7.5", x2: "70", y2: "20.5", transform: `rotate(${Math.min(100, mark) * 3.6} 70 70)` });
    if (markTitle) {
      const tip = el("title", {});
      tip.textContent = markTitle;
      tick.append(tip);
    }
    svg.append(tick);
  }
  svg.append(text);
  return svg;
}

/** The litter itself: a tray of sand at its level, and a plain-words state. */
export function sandPanel(box) {
  const pct = Math.max(0, Math.min(100, box.litter_level_percent ?? 0));
  const state = box.litter_level_state;
  const words = litterWords(state) || `${number(pct)}%`;
  const level = state === "EMPTY" ? "critical" : state === "LOW" || state === "REFILL" ? "warning" : "ok";
  return pane({
    cls: "pane-sand", level, icon: "litter", title: "Litter", aria: `Litter ${words}, ${number(pct)}%`,
    graphic: gauge({ kind: "sand", percent: pct, label: "Litter level", valuetext: `${number(pct)}%, ${words}` }),
    label: `${number(pct)}%`, value: words,
    valueIcon: level === "ok" ? null : pictogram("alert", { size: 28 }),
  });
}

/** Last cat visit and the clean cycle that should follow it. */
export function cyclePanel(box, catColors, now = Date.now()) {
  const cycle = cycleState(box, now);
  const who = box.last_cat;
  const status = {
    clean: { icon: "check", value: cycle.sinceClean != null ? `Cleaned ${agoText(cycle.sinceClean)}` : "Cleaned", level: "ok" },
    running: { icon: "cycle", value: "Cleaning now", level: "info" },
    waiting: { icon: "clock", value: cycle.minutesLeft > 0 ? `Cleans in ${cycle.minutesLeft} min` : "Cleans any moment", level: "info" },
    overdue: { icon: "alert", value: "Hasn't cleaned", level: "critical" },
    unknown: { icon: "help", value: "No cycles yet", level: "info" },
  }[cycle.kind];
  const visit = cycle.sinceVisit == null ? "No visits yet" : `${who ? `${who} visited` : "Visited"} ${agoText(cycle.sinceVisit)}`;
  const portrait = h("span", { class: "portrait" },
    who ? catAvatar(who, catColors[who], { size: 160, image: 136 }) : h("span", { class: "portrait-empty" }, pictogram("cat", { size: 64 })),
    h("span", { class: "portrait-badge", "data-level": status.level }, pictogram(status.icon, { size: 28 })));
  return pane({
    cls: "pane-cycle", level: status.level, icon: "broom", title: "Cleaning",
    aria: `${visit}. ${status.value}.`,
    graphic: portrait, label: visit, value: status.value,
    note: box.sleeping ? "Sleep mode is on" : null,
  });
}

export function litterTiles(box, catColors) {
  return [drawerPanel(box), sandPanel(box), cyclePanel(box, catColors)];
}

// ---------- feeders ----------

/** One compact row per feeder: who it feeds, whether it's stocked, when it feeds next. */
export function feedersPanel(feeders, feederCats, catColors) {
  const rows = feeders.map((feeder) => {
    const cats = feederCats[feeder.device_id] || [];
    const low = feeder.food_low === true;
    const offline = feeder.online === false;
    const stock = offline ? { icon: "wifi", text: "Offline", level: "warning" }
      : low ? { icon: "bowlEmpty", text: "Low on food", level: "warning" }
        : { icon: "bowl", text: "Food OK", level: "ok" };
    return h("li", { class: "strip-row", "data-level": stock.level },
      h("span", { class: "strip-who" },
        cats.map((cat) => catAvatar(cat, catColors[cat], { size: 36, image: 30 })),
        h("span", { class: "strip-name" }, h("strong", { text: cats.length ? cats.join(" & ") : feeder.name }),
          cats.length ? h("span", { class: "note", text: feeder.name }) : null)),
      h("span", { class: "strip-stat" }, pictogram(stock.icon, { size: 20 }), h("span", { text: stock.text })),
      h("span", { class: "strip-stat quiet", title: "Next feeding" }, pictogram("clock", { size: 20 }),
        h("span", { text: feeder.next_feed_at ? `Next ${dayClock(feeder.next_feed_at)}` : "No feeding planned" })));
  });
  return h("article", { class: "panel panel-strip", "aria-label": "Feeders" },
    panelHead("bowl", "Feeders"), h("ul", { class: "strip-list" }, rows));
}

// ---------- insights ----------

function insightBlock(cat, color, headline, sub, draw) {
  const chart = h("div", { class: "mini-chart" });
  responsive(chart, draw);
  return h("div", { class: "insight" },
    h("div", { class: "insight-head" },
      h("div", { class: "who" }, catAvatar(cat, color, { size: 40, image: 35 }), h("span", { text: cat })),
      h("div", { class: "insight-num" }, headline),
      h("div", { class: "insight-sub", text: sub })),
    chart);
}

function gapLabel(bin) {
  return bin.to_hours == null ? `${bin.from_hours}h+` : `${bin.from_hours}`;
}

export function gapsTile(cats, catColors) {
  const blocks = cats.filter((c) => c.litter_gaps).map((c) => {
    const g = c.litter_gaps;
    const total = g.histogram.reduce((a, b) => a + b.count, 0) || 1;
    const shares = g.histogram.map((b) => (b.count / total) * 100);
    const color = catColors[c.name];
    const headline = [h("span", { text: hours(g.median_hours) })];
    return insightBlock(c.name, color, headline, `usually ${hours(g.p25_hours)}–${hours(g.p75_hours)}`, (el) =>
      columnChart(el, {
        height: 84,
        categories: g.histogram.map(gapLabel),
        labels: g.histogram.map(gapLabel),
        titles: g.histogram.map((b) => (b.to_hours == null ? `${b.from_hours} h or more` : `${b.from_hours}–${b.to_hours} h apart`)),
        series: [{ name: c.name, color, values: shares }],
        format: (v) => `${number(v)}%`,
        ariaLabel: `${c.name}: time between litter box visits`,
      }));
  });
  return h("article", { class: "panel tile-insight" },
    h("h2", { class: "tile-title" }, pictogram("clock"), h("span", { text: "Between litter visits" })),
    h("p", { class: "tile-note", text: "Hours between visits, share of all gaps" }),
    blocks.length ? blocks : h("p", { class: "muted", text: "Not enough visits yet." }));
}

export function mealsTile(cats, catColors) {
  const blocks = cats.filter((c) => c.meal_timing).map((c) => {
    const m = c.meal_timing;
    const w15 = m.after_meal.find((a) => a.within_minutes === 15);
    const ratio = w15 && w15.chance ? w15.share / w15.chance : null;
    const color = catColors[c.name];
    const bins = m.offsets.bins;
    const expected = m.offsets.expected_per_bin || 1;
    const values = bins.map((b) => b.count / expected);
    const label = (b) => (b.from_minutes === 0 ? "meal" : `${b.from_minutes > 0 ? "+" : "−"}${Math.abs(b.from_minutes) / 60}h`);
    const headline = [h("span", { text: ratio ? number(ratio, 1) : "—" }), h("span", { class: "unit", text: "×" })];
    const sub = w15 ? `${number(w15.share * 100)}% within 15 min of eating · chance ${number(w15.chance * 100)}%` : "";
    return insightBlock(c.name, color, headline, sub, (el) =>
      columnChart(el, {
        height: 84,
        categories: bins.map((b) => String(b.from_minutes)),
        labels: bins.map(label),
        labelFilter: (i) => bins[i].from_minutes % 60 === 0,
        titles: bins.map((b) => {
          const a = b.from_minutes;
          const z = a + m.offsets.bin_minutes;
          return a >= 0 ? `${a}–${z} min after a meal` : `${-z}–${-a} min before a meal`;
        }),
        series: [{ name: c.name, color, values }],
        reference: { value: 1, label: "" },
        format: (v) => `${number(v, 1)}×`,
        ariaLabel: `${c.name}: litter box visits around meals, relative to chance`,
      }));
  });
  return h("article", { class: "panel tile-insight" },
    h("h2", { class: "tile-title" }, pictogram("bowl"), pictogram("chevron", { size: 14 }), pictogram("litter"),
      h("span", { text: "Litter after meals" })),
    h("p", { class: "tile-note", text: "Litter box visits before and after each meal. Line = chance (1×)." }),
    blocks.length ? blocks : h("p", { class: "muted", text: "Not enough overlap yet." }));
}

// ---------- helpers ----------

function hours(value) {
  if (value == null) return "—";
  return value < 1 ? `${Math.round(value * 60)}m` : `${number(value, value < 10 ? 1 : 0)}h`;
}
