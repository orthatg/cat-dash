// The dashboard's cards: waste drawer (ring), litter (good / needs refill), cleaning (litter box +
// Roomba), one card per cat (portrait + two rings), and the pattern charts inside History.

import { agoText, cycleState, drawerLevel, litterLevel } from "./attention.js";
import { columnChart } from "./charts.js";
import { catAvatar, h, pictogram } from "./dom.js";
import { clock, dayClock, number, shortIn, toDate } from "./format.js";
import { roombaState } from "./roomba.js";

const SVG = "http://www.w3.org/2000/svg";
const MIN = 60_000;

function svg(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  el.append(...children.filter(Boolean));
  return el;
}

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

function cardHead(icon, label) {
  return h("p", { class: "card-head" }, pictogram(icon, { size: 20 }), h("span", { text: label }));
}

/** A progress ring. `p` 0..1; `cls` styles the fill; `mark` (0..1) draws a notch across the ring. */
function ring({ size, r, width, p, cls, label, mark }) {
  const c = 2 * Math.PI * r;
  const mid = size / 2;
  const notch = mark == null ? null : (() => {
    const a = mark * 2 * Math.PI - Math.PI / 2;
    const at = (rad) => [mid + rad * Math.cos(a), mid + rad * Math.sin(a)];
    const [x1, y1] = at(r - width + 2);
    const [x2, y2] = at(r + width - 2);
    return svg("line", { class: "ring-notch", x1, y1, x2, y2 });
  })();
  return svg("svg", { class: `ring ${cls || ""}`, viewBox: `0 0 ${size} ${size}`, role: "img", "aria-label": label },
    svg("circle", { class: "ring-track", cx: mid, cy: mid, r, "stroke-width": width }),
    svg("circle", {
      class: "ring-fill", cx: mid, cy: mid, r, "stroke-width": width,
      "stroke-dasharray": `${(Math.max(0, Math.min(1, p)) * c).toFixed(1)} ${c.toFixed(1)}`,
      transform: `rotate(-90 ${mid} ${mid})`,
    }),
    notch);
}

// ---------- waste drawer ----------

export function drawerCard(box, now = Date.now()) {
  const pct = Math.max(0, box.waste_drawer_percent ?? 0);
  const usual = box.drawer_usual_empty_percent;
  const level = drawerLevel(box, now); // ok | due | full
  const due = toDate(box.drawer_needs_emptying_at);
  const full = toDate(box.drawer_full_at);
  const kicker = level === "full" ? "Drawer is full" : level === "due" ? `Usually emptied at ${number(usual)}%` : due ? "Empty by" : "Waste drawer";
  const when = level === "full" ? "Empty it now" : level === "due" ? "Empty it today" : due ? dayClock(due) : `${number(pct)}% full`;
  const sub = level === "full" ? "The box has stopped cleaning"
    : [full && level !== "full" ? `Full ${dayClock(full).replace(/^(Today|Tomorrow|Yesterday) /, (w) => w.toLowerCase())}` : null,
      box.drawer_fill_rate_per_day ? `fills ~${number(box.drawer_fill_rate_per_day)}% a day` : null].filter(Boolean).join(" · ");
  return h("section", { class: "card card-drawer", "data-level": level, "aria-label": "Waste drawer" },
    cardHead("drawer", "Waste drawer"),
    h("div", { class: "dial" },
      ring({ size: 200, r: 84, width: 16, p: pct / 100, cls: "ring-drawer", mark: usual ? usual / 100 : null,
        label: `Waste drawer ${number(pct)}% full${usual ? `; usually emptied at ${number(usual)}%` : ""}` }),
      h("div", { class: "dial-read" },
        h("p", { class: "dial-num" }, h("span", { text: number(pct) }), h("span", { class: "dial-unit", text: "%" })),
        h("p", { class: "dial-dir" }, pictogram("arrowUp", { size: 14 }), h("span", { text: "filling" })))),
    h("div", { class: "card-read" },
      h("p", { class: "card-kicker" }, pictogram("calendar", { size: 16 }), h("span", { text: kicker })),
      h("p", { class: "card-value", text: when }),
      sub ? h("p", { class: "card-sub", text: sub }) : null));
}

// ---------- litter ----------

export function litterCard(box) {
  const level = litterLevel(box); // good | refill | empty
  const low = level !== "good";
  const sand = low
    ? "M26.8 92h96.4l-2.2 14a10 10 0 0 1-10 8H39a10 10 0 0 1-10-8Z"
    : "M19 40h112l-10 66a10 10 0 0 1-10 8H39a10 10 0 0 1-10-8Z";
  const word = level === "empty" ? "Empty" : low ? "Needs refill" : "Good";
  const sub = level === "empty" ? "Refill the box" : low ? "Top it up, or check the hopper" : "The level sensor reads optimal";
  const tub = svg("svg", { class: "tub", viewBox: "0 0 150 120", role: "img", "aria-label": low ? "Litter is low and needs a refill" : "Litter level is good" },
    svg("rect", { class: "tub-rim", x: 6, y: 20, width: 138, height: 8, rx: 4 }),
    svg("path", { class: "tub-body", d: "M16 28h118l-12 78a10 10 0 0 1-10 8H38a10 10 0 0 1-10-8L16 28Z" }),
    svg("path", { class: "tub-sand", d: sand }),
    low ? null : svg("path", { class: "tub-grain", d: "M30 54h90M32 70h86M34 86h82M36 101h78" }));
  return h("section", { class: "card card-litter", "data-level": level, "aria-label": "Litter" },
    cardHead("litter", "Litter"),
    h("div", { class: "tub-disc" }, tub),
    h("div", { class: "card-read" },
      h("p", { class: "card-value" }, pictogram(low ? "alert" : "check", { size: 24 }), h("span", { text: word })),
      h("p", { class: "card-sub", text: sub })));
}

// ---------- cleaning: litter box + Roomba ----------

function badge(kind) {
  const icon = { ok: "check", critical: "x", info: "clock", warning: "alert" }[kind] || "clock";
  return h("span", { class: "badge", "data-kind": kind }, pictogram(icon, { size: 14 }));
}

function boxRow(box, catColors, now) {
  const cycle = cycleState(box, now);
  const drawer = drawerLevel(box, now);
  const cat = box.last_cat;
  const visited = cycle.sinceVisit != null ? `${cat || "A cat"} visited ${agoText(cycle.sinceVisit)}` : null;
  let title, sub, kind;
  if (drawer === "full") [title, sub, kind] = ["Not cleaning", ["Waiting for the drawer", visited].filter(Boolean).join(" · "), "critical"];
  else if (cycle.kind === "running") [title, sub, kind] = ["Cleaning now", visited, "info"];
  else if (cycle.kind === "waiting") [title, sub, kind] = [cycle.minutesLeft ? `Cleans in ${cycle.minutesLeft} min` : "Cleaning soon", visited, "info"];
  else if (cycle.kind === "overdue") [title, sub, kind] = ["Clean didn't run", visited, "critical"];
  else if (cycle.sinceClean != null) [title, sub, kind] = [`Cleaned ${agoText(cycle.sinceClean)}`, cat ? `After ${cat}'s visit` : visited, "ok"];
  else [title, sub, kind] = ["No clean yet", null, "info"];
  if (box.sleeping) sub = [sub, "sleep mode"].filter(Boolean).join(" · ");
  const pic = cat
    ? catAvatar(cat, catColors[cat], { size: 64, image: 56 })
    : h("span", { class: "row-pic" }, pictogram("broom", { size: 32 }));
  return h("div", { class: "clean-row", "data-kind": kind },
    h("div", { class: "row-pic-wrap" }, pic, badge(kind)),
    h("div", { class: "row-text" },
      h("p", { class: "row-label", text: "Litter box" }),
      h("p", { class: "row-title", text: title }),
      sub ? h("p", { class: "row-sub", text: sub }) : null));
}

function roombaRow(rb, now) {
  const s = rb?.data;
  let title, sub, kind;
  if (rb?.phase === "unconfigured") [title, sub, kind] = ["Not set up", "Add its address and password to the backend settings", "info"];
  else if (!s) [title, sub, kind] = rb?.phase === "error" ? ["Can't reach it", "It may be asleep or off Wi-Fi", "warning"] : ["Checking…", null, "info"];
  else {
    const st = roombaState(s);
    const last = toDate(s.last_mission_started_at) || toDate(s.last_command_at);
    if (s.state === "cleaning") title = "Cleaning now";
    else if (st.tone === "critical") title = st.word;
    else title = last ? `Ran ${agoText(Math.round((now - last) / MIN))}` : "No runs yet";
    const bits = [];
    if (last && s.state !== "cleaning") bits.push(sameDay(last, now) ? clock(last) : dayClock(last));
    if (s.state !== "cleaning" && st.tone !== "critical") bits.push(st.word.toLowerCase());
    if (s.battery_percent != null) bits.push(`${number(s.battery_percent)}%`);
    bits.push(s.bin_full ? "bin full" : s.bin_present === false ? "bin missing" : "bin OK");
    const next = toDate(s.next_scheduled_at);
    if (next && next > now) bits.push(`next in ${shortIn(next, now)}`);
    if (rb.failure) bits.push("can't reach it now");
    sub = bits.join(" · ");
    kind = st.tone === "critical" ? "critical" : s.bin_full || s.bin_present === false ? "warning" : s.state === "cleaning" ? "info" : "ok";
  }
  const name = s?.name ? `Roomba · ${s.name}` : "Roomba";
  return h("div", { class: "clean-row", "data-kind": kind },
    h("div", { class: "row-pic-wrap" }, h("span", { class: "row-pic" }, pictogram("robot", { size: 36 })), badge(kind)),
    h("div", { class: "row-text" },
      h("p", { class: "row-label", text: name }),
      h("p", { class: "row-title", text: title }),
      sub ? h("p", { class: "row-sub", text: sub }) : null));
}

function sameDay(a, b) {
  const x = new Date(a); const y = new Date(b);
  return x.getFullYear() === y.getFullYear() && x.getMonth() === y.getMonth() && x.getDate() === y.getDate();
}

export function cleaningCard(box, roomba, catColors, now = Date.now()) {
  return h("section", { class: "card card-cleaning", "aria-label": "Cleaning" },
    cardHead("sparkle", "Cleaning"),
    box ? boxRow(box, catColors, now) : null,
    roombaRow(roomba, now));
}

// ---------- cats ----------

const BOWL = ["M3.5 10h17a8.5 8.5 0 0 1-17 0Z", "M8.5 6.5h.01M12 5h.01M15.5 6.5h.01"];
const TUB = ["M3.5 7.5h17l-1.5 8a2 2 0 0 1-2 1.6H7a2 2 0 0 1-2-1.6l-1.5-8Z", "M7 12c1.7-1.5 3.3-1.5 5 0s3.3 1.5 5 0"];

function smallIcon([a, b]) {
  return svg("svg", { class: "cap-icon", viewBox: "0 0 24 24", "aria-hidden": "true" }, svg("path", { d: a }), svg("path", { d: b }));
}

/** A ring with the number and unit inside and a one-line caption under it. */
function statRing({ value, unit, caption, icon, p, label, color }) {
  const r = ring({ size: 92, r: 38, width: 8, p, cls: "ring-cat", label });
  r.style.setProperty("--ring", color);
  return h("div", { class: "stat" },
    h("div", { class: "stat-dial" }, r,
      h("p", { class: "stat-read" }, h("span", { class: "stat-num", text: value }), h("span", { class: "stat-unit", text: unit }))),
    h("p", { class: "stat-cap" }, smallIcon(icon), h("span", { text: caption })));
}

/**
 * One card per cat. `stats`: { eatMin, usualEatMin, litterToday, usualLitter } (any may be null);
 * `feeder`: the feeder this cat eats at (if any); `blocked`: that feeder can't dispense.
 */
export function catCard({ name, color, feeder, blocked, stats }) {
  const ratio = (v, usual) => (v == null ? 0 : usual ? v / usual : v > 0 ? 1 : 0);
  const img = h("img", { class: "cutout", src: `assets/cats/${encodeURIComponent(name.toLowerCase())}-cutout.png`, alt: `Drawing of ${name}`, loading: "lazy" });
  const art = h("div", { class: "cat-art" }, h("span", { class: "cat-halo" }), img);
  img.addEventListener("error", () => art.replaceChildren(catAvatar(name, color, { size: 140, image: 124 })), { once: true });
  art.style.setProperty("--ring", color);
  const eat = stats.eatMin;
  const litter = stats.litterToday;
  return h("section", { class: "card card-cat", "aria-label": name },
    art,
    h("div", { class: "cat-main" },
      h("div", { class: "cat-top" },
        h("div", {},
          h("h2", { class: "cat-name" }, h("span", { class: "cat-dot", style: `background:${color}` }), h("span", { text: name })),
          feeder ? h("p", { class: "card-sub", text: `${feeder.name} feeder` }) : null),
        blocked ? h("p", { class: "chip-warn" }, pictogram("alert", { size: 16 }), h("span", { text: "Feeder blocked" })) : null),
      h("div", { class: "stats" },
        statRing({
          value: eat == null ? "—" : number(eat), unit: "min", caption: "Eating today", icon: BOWL, color,
          p: ratio(eat, stats.usualEatMin),
          label: eat == null ? "No feeder data" : `${number(eat)} minutes eating today${stats.usualEatMin ? `, of about ${number(stats.usualEatMin)} usually` : ""}`,
        }),
        statRing({
          value: litter == null ? "—" : number(litter), unit: litter === 1 ? "visit" : "visits", caption: "Litter today", icon: TUB, color,
          p: ratio(litter, stats.usualLitter),
          label: litter == null ? "No litter data" : `${number(litter)} litter box visits today${stats.usualLitter ? `, of about ${number(stats.usualLitter, 1)} usually` : ""}`,
        })),
      feeder?.next_feed_at
        ? h("p", { class: "cat-next" }, pictogram("clock", { size: 18 }), h("span", { text: `Next meal ${clock(feeder.next_feed_at)}` }))
        : null));
}

// ---------- pattern charts (inside History) ----------

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
  return h("article", { class: "card tile-insight" },
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
  return h("article", { class: "card tile-insight" },
    h("h2", { class: "tile-title" }, pictogram("bowl"), pictogram("chevron", { size: 14 }), pictogram("litter"),
      h("span", { text: "Litter after meals" })),
    h("p", { class: "tile-note", text: "Litter box visits before and after each meal. Line = chance (1×)." }),
    blocks.length ? blocks : h("p", { class: "muted", text: "Not enough overlap yet." }));
}

export function hours(value) {
  if (value == null) return "—";
  return value < 1 ? `${Math.round(value * 60)}m` : `${number(value, value < 10 ? 1 : 0)}h`;
}
