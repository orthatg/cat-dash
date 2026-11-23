// Glanceable tiles: big numbers, pictograms instead of sentences, details on hover.

import { columnChart } from "./charts.js";
import { catAvatar, h, pictogram } from "./dom.js";
import { clock, dayPart, number, shortAgo, shortDate, shortIn, titleCase, weekdayTime } from "./format.js";

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

// ---------- litter box ----------

function drawerStatus(box, now = Date.now()) {
  const pct = box.waste_drawer_percent ?? 0;
  const due = box.drawer_needs_emptying_at ? Date.parse(box.drawer_needs_emptying_at) : null;
  if (box.waste_drawer_full || box.waste_drawer_state === "full" || pct >= 100) return "critical";
  if ((due && due <= now) || (box.drawer_usual_empty_percent && pct >= box.drawer_usual_empty_percent)) return "warning";
  return "ok";
}

/** The drawer: a bin that fills, a notch where it's usually emptied, the % and the date. */
export function drawerTile(box) {
  const pct = Math.max(0, box.waste_drawer_percent ?? 0);
  const usual = box.drawer_usual_empty_percent;
  const status = drawerStatus(box);
  const fill = h("div", { class: "bin-fill" });
  fill.style.height = `${Math.min(pct, 100)}%`;
  const usualLine = usual ? h("div", { class: "bin-usual" }) : null;
  if (usualLine) usualLine.style.bottom = `${Math.min(usual, 100)}%`;
  const bin = h("div", {
    class: "bin", role: "meter", "aria-label": "Waste drawer",
    "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(pct)),
    "aria-valuetext": `${number(pct)}% full${usual ? `, usually emptied at ${number(usual)}%` : ""}`,
  }, h("div", { class: "bin-body" }, fill), usualLine, levelArrow("up", pct, "Fills up as it's used"));

  const dueText = box.drawer_needs_emptying_at
    ? `Empty it by ${dayPart(box.drawer_needs_emptying_at)} (around ${number(usual)}%). Full around ${dayPart(box.drawer_full_at)}.`
    : "Not enough history to forecast yet.";
  let when;
  if (status === "critical") when = h("span", { class: "when", title: "Drawer is full" }, pictogram("x", { label: "Full" }), h("span", { text: "Now" }));
  else if (status === "warning") when = h("span", { class: "when", title: dueText }, pictogram("alert", { label: "Due" }), h("span", { text: "Today" }));
  else if (box.drawer_needs_emptying_at) {
    when = h("span", { class: "when", title: dueText }, pictogram("calendar", { label: "Empty by" }),
      h("span", { text: shortDate(box.drawer_needs_emptying_at) }));
  }

  return h("article", { class: "tile tile-drawer", "data-status": status, "aria-label": `Waste drawer: ${dueText}` },
    bin,
    h("div", { class: "drawer-read" },
      h("div", { class: "big" }, h("span", { text: number(pct) }), h("span", { class: "unit", text: "%" })),
      when,
      forecastDetail(box, status)));
}

/** The numbers behind the date: "in 22h · at 82% · full Wed 9am". */
function forecastDetail(box, status) {
  if (!box.drawer_needs_emptying_at) return null;
  const parts = [];
  if (status === "ok") {
    parts.push(`in ${shortIn(box.drawer_needs_emptying_at)}`);
    if (box.drawer_usual_empty_percent) parts.push(`at ${number(box.drawer_usual_empty_percent)}%`);
  }
  if (box.drawer_full_at && status !== "critical") {
    parts.push(`full ${weekdayTime(box.drawer_full_at)}`);
  }
  if (box.drawer_fill_rate_per_day) parts.push(`+${number(box.drawer_fill_rate_per_day)}%/day`);
  // Each item stays whole; the line only breaks between items.
  return parts.length
    ? h("div", { class: "when-detail" }, parts.map((part, i) => [i ? " · " : null, h("span", { text: part })]))
    : null;
}

/** A small arrow beside a gauge, at its level: which way the level moves with use. */
function levelArrow(direction, percent, title) {
  const arrow = h("span", { class: `level-arrow ${direction}`, title },
    pictogram(direction === "up" ? "arrowUp" : "arrowDown", { size: 20, label: title }));
  // Inside the container, right at the level: "up" sits on the fill's surface,
  // "down" hangs just under it. Clamped so it never leaves the container.
  const level = Math.max(0, Math.min(100, percent));
  arrow.style.bottom = direction === "up"
    ? `min(calc(${level}% + 4px), calc(100% - 26px))`
    : `max(calc(${level}% - 26px), 4px)`;
  return arrow;
}

/** Last visit (who + how long ago) and time since the last clean, in one tile. */
function activityTile(box, catColors) {
  const ago = splitAgo(box.last_cat_detected_at);
  const clean = splitAgo(box.last_clean_cycle_at);
  const issues = [];
  if (!box.online) issues.push("Offline");
  else if (!box.powered_on) issues.push("Off");
  if (box.sleeping) issues.push("Sleep mode");
  const who = box.last_cat;
  return h("article", { class: "tile tile-activity",
    "aria-label": `Last visit ${shortAgo(box.last_cat_detected_at)} ago${who ? ` by ${who}` : ""}; cleaned ${shortAgo(box.last_clean_cycle_at)} ago` },
    h("div", { class: "act-main" },
      who ? catAvatar(who, catColors[who], { size: 80, image: 68 }) : h("span", { class: "act-icon" }, pictogram("paw", { size: 28 })),
      h("div", {},
        h("div", { class: "big" }, h("span", { text: ago.value }), h("span", { class: "unit", text: ago.unit })),
        h("div", { class: "caption act-caption" }, pictogram("paw", { size: 14 }),
          h("span", { text: who ? `${who} visited` : "last visit" })))),
    h("div", { class: "act-clean" }, pictogram("sparkle", { size: 18 }),
      h("span", { class: "mid" }, h("strong", { text: clean.value }), h("span", { text: clean.unit })),
      h("span", { class: "caption", text: "since clean" })),
    issues.length ? h("div", { class: "who warn" }, pictogram("alert", { size: 14 }), h("span", { text: issues.join(" · ") })) : null);
}

/** Litter: a tub filled with litter to the current level; the level drains with use. */
function litterTile(box) {
  const pct = Math.max(0, Math.min(100, box.litter_level_percent ?? 0));
  const fill = h("div", { class: "tub-fill" });
  fill.style.height = `${pct}%`;
  const state = box.litter_level_state ? titleCase(box.litter_level_state) : null;
  const low = box.litter_level_state && box.litter_level_state !== "OPTIMAL";
  return h("article", { class: "tile tile-litter", "data-status": low ? "warning" : "ok" },
    h("div", { class: "tile-top" }, pictogram("litter"), h("span", { class: "caption", text: "litter" })),
    h("div", { class: "litter-viz" },
      h("div", { class: "tub", role: "meter", "aria-label": "Litter level",
        "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(pct)),
        "aria-valuetext": `${number(pct)}% litter${state ? `, ${state}` : ""}` },
      h("div", { class: "tub-body" }, fill), levelArrow("down", pct, "Goes down as it's used")),
      h("div", { class: "big", title: state }, h("span", { text: number(pct) }), h("span", { class: "unit", text: "%" }))));
}

export function litterTiles(box, catColors) {
  return [drawerTile(box), activityTile(box, catColors), litterTile(box)];
}

// ---------- feeders ----------

export function feederTile(feeder, cats, catColors) {
  const low = feeder.food_low === true;
  const problems = [...(feeder.problems || [])].map(titleCase);
  if (feeder.online === false) problems.unshift("Offline");
  const warnings = [];
  if (feeder.desiccant_days_left != null && feeder.desiccant_days_left < 0) {
    warnings.push(`Desiccant overdue by ${number(-feeder.desiccant_days_left)} days`);
  }
  const name = cats?.length
    ? h("div", { class: "who big-who" }, cats.map((cat) => [catAvatar(cat, catColors[cat], { size: 56, image: 48 }), h("span", { text: cat })]))
    : h("div", { class: "who big-who" }, h("span", { text: feeder.name }));
  const food = h("span", {
    class: "food", "data-status": problems.length ? "critical" : low ? "warning" : "ok",
    title: problems.length ? problems.join(", ") : low ? "Food low" : "Food OK",
  }, pictogram(low ? "bowlEmpty" : "bowl", { label: low ? "Food low" : "Food OK" }));
  return h("article", { class: "tile tile-feeder", "aria-label": `${cats?.join(" and ") || feeder.name}'s feeder (${feeder.name})` },
    h("div", { class: "tile-top" }, name, food),
    h("div", { class: "big" }, h("span", { text: number(feeder.today_dispensed_portions ?? 0) }),
      h("span", { class: "unit", text: feeder.today_dispensed_portions === 1 ? " portion" : " portions" })),
    h("div", { class: "feeder-foot" },
      h("span", { class: "foot-item", title: "Next feed" }, pictogram("clock", { size: 16, label: "Next feed" }),
        h("span", { text: feeder.next_feed_at ? clock(feeder.next_feed_at) : "—" })),
      h("span", { class: "foot-item", title: "Feeder visits today" }, pictogram("paw", { size: 16, label: "Visits today" }),
        h("span", { text: number(feeder.today_eat_count ?? 0) })),
      warnings.length || problems.length
        ? h("span", { class: "foot-item warn", title: [...problems, ...warnings].join(". ") },
          pictogram("alert", { size: 16, label: "Needs attention" }), h("span", { text: String(problems.length + warnings.length) }))
        : null,
      h("span", { class: "foot-item muted", text: feeder.name })));
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
  return h("article", { class: "tile tile-insight" },
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
  return h("article", { class: "tile tile-insight" },
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

function splitAgo(value) {
  const text = shortAgo(value); // "35m", "2h", "3d"
  const match = /^(\d+)(\D+)$/.exec(text);
  return match ? { value: match[1], unit: match[2] } : { value: text, unit: "" };
}
