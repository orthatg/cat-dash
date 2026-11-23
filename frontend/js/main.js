import { api, subscribe } from "./api.js";
import { chartCard, columnChart, lineChart } from "./charts.js";
import { errorsBanner, h } from "./dom.js";
import { dayPart, longDateTime, number, parseDay, shortDay } from "./format.js";
import { feederTile, gapsTile, litterTiles, mealsTile } from "./tiles.js";

// Identity colors (fixed slot per entity, never by rank). A cat keeps the same color in
// both sections; a feeder takes its cat's color when it serves one cat.
const SLOTS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
// The litter box's own data (cycles, drawer) is drawn in neutral ink: hue is reserved
// for the cats (validated pair, light and dark).
const LITTER = "var(--litter-mark)";
const HISTORY_REFRESH_MS = 10 * 60_000;

const state = {
  status: null,
  days: loadDays(),
  drawer: {}, // litter box id -> /drawer response
  catColors: {},
  feederColors: {},
  feederCats: {}, // feeder id -> cat names seen eating there (RFID)
  historyKey: "",
};

const $ = (id) => document.getElementById(id);

function loadDays() {
  try {
    const saved = Number(localStorage.getItem("catdash.days"));
    return [7, 30, 90].includes(saved) ? saved : 30;
  } catch {
    return 30;
  }
}

function saveDays(days) {
  try {
    localStorage.setItem("catdash.days", String(days));
  } catch {
    /* storage unavailable: keep the in-memory choice */
  }
}

const byName = (a, b) => a.name.localeCompare(b.name);

// ---------- colors ----------

/** Cats in a stable order: by feeder (sorted), then any litter-only cats by name. */
function assignColors(feederVisits, litterCats) {
  const catColors = {};
  const feederColors = {};
  let next = 0;
  const take = () => SLOTS[next++ % SLOTS.length];
  // A cat with its own --cat-<name> color in styles.css keeps it; others take a slot.
  const style = getComputedStyle(document.querySelector(".viz-root"));
  const named = (cat) => {
    const token = `--cat-${cat.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`;
    return style.getPropertyValue(token).trim() ? `var(${token})` : null;
  };
  const colorFor = (cat) => named(cat) || take();
  for (const { feeder, cats } of feederVisits) {
    for (const cat of cats) if (!catColors[cat]) catColors[cat] = colorFor(cat);
    feederColors[feeder.device_id] = cats.length === 1 ? catColors[cats[0]] : take();
    state.feederCats[feeder.device_id] = cats;
  }
  for (const cat of litterCats.slice().sort()) if (!catColors[cat]) catColors[cat] = colorFor(cat);
  state.catColors = catColors;
  state.feederColors = feederColors;
}

// ---------- tiles (live) ----------

function renderCards() {
  const status = state.status;
  if (!status) return;
  errorsBanner($("errors"), status);
  const boxes = status.litter_boxes.slice().sort(byName);
  const feeders = status.feeders.slice().sort(byName);
  $("litter-tiles").replaceChildren(...(boxes.length
    ? boxes.flatMap((box) => litterTiles(box, state.catColors))
    : [emptyNote("No litter box connected.")]));
  $("food-tiles").replaceChildren(...(feeders.length
    ? feeders.map((feeder) => feederTile(feeder, state.feederCats[feeder.device_id], state.catColors))
    : [emptyNote("No feeders connected.")]));
}

function emptyNote(text) {
  const p = document.createElement("p");
  p.className = "muted";
  p.textContent = text;
  return p;
}

// Reload history when something that changes it happens (a cycle, an empty, a feed).
function historyKey(status) {
  return JSON.stringify([
    status.litter_boxes.map((b) => [b.last_clean_cycle_at, b.last_emptied_at, b.last_cat_detected_at]),
    status.feeders.map((f) => [f.last_feed_at, f.today_eat_count]),
  ]);
}

function onStatus(status) {
  const first = !state.status;
  state.status = status;
  renderCards();
  const key = historyKey(status);
  if (first || key !== state.historyKey) {
    state.historyKey = key;
    loadHistory();
  }
}

// ---------- history ----------

/** The last `days` local calendar days, oldest first, as "YYYY-MM-DD". */
function dayList(days) {
  const out = [];
  const today = new Date();
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - i);
    out.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);
  }
  return out;
}

const noon = (isoDay) => {
  const d = parseDay(isoDay);
  d.setHours(12);
  return d;
};

let loading = null;

async function loadHistory() {
  const status = state.status;
  if (!status) return;
  const days = state.days;
  const containers = [$("insight-tiles"), $("more-charts")];
  containers.forEach((c) => c.classList.add("loading")); // hold the previous render
  const run = (async () => {
    const boxes = status.litter_boxes.slice().sort(byName);
    const feeders = status.feeders.slice().sort(byName);
    const [litter, feeds] = await Promise.all([
      Promise.all(boxes.map(async (box) => {
        const [daily, drawer, cats] = await Promise.all([
          api.litterDaily(box.device_id, days),
          api.litterDrawer(box.device_id, days),
          api.litterCatsDaily(box.device_id, days),
        ]);
        return { box, daily, drawer, cats };
      })),
      Promise.all(feeders.map(async (feeder) => {
        const [daily, visits] = await Promise.all([
          api.feederDaily(feeder.device_id, days),
          api.feederVisitsDaily(feeder.device_id, days),
        ]);
        return { feeder, daily, visits };
      })),
    ]);
    const insights = await api.insights(Math.max(days, 14));
    return { litter, feeds, insights };
  })();
  loading = run;
  try {
    const data = await run;
    if (loading !== run) return; // a newer load superseded this one
    for (const { box, drawer } of data.litter) state.drawer[box.device_id] = drawer;
    assignColors(
      data.feeds.map(({ feeder, visits }) => ({
        feeder, cats: [...new Set(visits.map((v) => v.pet_name).filter(Boolean))].sort(),
      })),
      data.litter.flatMap(({ box }) => (box.cats || []).map((c) => c.name)),
    );
    renderCards();
    const daysList = dayList(days);
    const ctx = {
      days,
      daysList,
      labels: daysList.map(shortDay),
      titles: daysList.map((d) => parseDay(d).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" })),
      domain: [new Date(Date.now() - days * 86_400_000), new Date()],
    };
    $("insight-tiles").replaceChildren(
      gapsTile(data.insights.cats, state.catColors),
      mealsTile(data.insights.cats, state.catColors),
    );
    renderMoreSummary(data, days);
    replaceCharts($("more-charts"), [
      ...data.litter.flatMap((entry) => litterCharts(entry, ctx, data.litter.length > 1)),
      ...(data.feeds.length ? foodCharts(data.feeds, ctx) : []),
    ]);
  } catch (err) {
    console.error(err);
  } finally {
    if (loading === run) containers.forEach((c) => c.classList.remove("loading"));
  }
}

function replaceCharts(container, cards) {
  for (const old of container.children) old.dispose?.();
  container.replaceChildren(...cards);
}

// ---------- "More": summary numbers, then the full charts when opened ----------

function renderMoreSummary({ litter, feeds }, days) {
  const chips = [];
  for (const { box, daily, drawer } of litter) {
    const cycles = daily.reduce((a, d) => a + d.clean_cycles, 0) / days;
    chips.push([number(cycles, 1), "cleans / day"]);
    if (drawer.average_days_between_empties) chips.push([`${number(drawer.average_days_between_empties, 1)} d`, "between empties"]);
    if (box.lifetime_cycles) chips.push([number(box.lifetime_cycles), "lifetime cycles"]);
  }
  const portions = feeds.reduce((a, f) => a + f.daily.reduce((x, d) => x + d.portions, 0), 0) / days;
  if (feeds.length) chips.push([number(portions, 1), "portions / day"]);
  const warnings = (state.status?.feeders || []).filter((f) => f.desiccant_days_left != null && f.desiccant_days_left < 0).length;
  if (warnings) chips.push([String(warnings), warnings === 1 ? "desiccant overdue" : "desiccants overdue"]);
  $("more-summary").replaceChildren(...chips.map(([value, label]) =>
    h("span", { class: "chip" }, h("strong", { text: value }), h("span", { text: label }))));
}

// ---------- litter box charts ----------

function litterCharts({ box, daily, drawer, cats }, ctx, multipleBoxes) {
  const prefix = multipleBoxes ? `${box.name}: ` : "";
  const { daysList, labels, titles, domain } = ctx;
  const cards = [];
  const byDay = Object.fromEntries(daily.map((d) => [d.date, d]));

  // Clean cycles per day
  const cycles = daysList.map((d) => byDay[d]?.clean_cycles ?? 0);
  const avg = cycles.reduce((a, b) => a + b, 0) / Math.max(1, cycles.length);
  cards.push(chartCard({
    title: `${prefix}Clean cycles per day`,
    sub: `Average ${number(avg, 1)} a day`,
    draw: (el) => columnChart(el, {
      categories: daysList, labels, titles, ariaLabel: "Clean cycles per day",
      series: [{ name: "Clean cycles", color: LITTER, values: cycles }],
      format: (v) => number(v),
    }),
    table: { columns: ["Date", "Clean cycles"], rows: daysList.map((d, i) => [titles[i], cycles[i]]).reverse() },
  }));

  // Litter box visits per day, by cat (matched by weight to Whisker pet profiles)
  const catNames = [...new Set(cats.map((r) => r.cat))].sort((a, b) =>
    (a === "Unknown") - (b === "Unknown") || a.localeCompare(b));
  if (catNames.length) {
    const series = catNames.map((cat) => {
      const byCatDay = Object.fromEntries(cats.filter((r) => r.cat === cat).map((r) => [r.date, r.visits]));
      return { name: cat, color: state.catColors[cat] || "var(--text-muted)", values: daysList.map((d) => byCatDay[d] ?? 0) };
    });
    cards.push(chartCard({
      title: `${prefix}Litter box visits per day`,
      sub: "By cat, matched by weight to the Whisker pet profiles",
      legend: series.map((s) => ({ name: s.name, color: s.color, kind: "rect" })),
      draw: (el) => columnChart(el, {
        categories: daysList, labels, titles, series, ariaLabel: "Litter box visits per day by cat",
        format: (v) => number(v),
      }),
      table: {
        columns: ["Date", ...series.map((s) => s.name)],
        rows: daysList.map((d, i) => [titles[i], ...series.map((s) => s.values[i])]).reverse(),
      },
    }));
  }

  // Waste drawer level, with each inferred empty marked
  const levels = drawer.levels.map((l) => ({ t: new Date(l.timestamp), v: l.percent }));
  const empties = drawer.emptied.map((e) => ({
    t: new Date(e.timestamp), v: 0, color: LITTER,
    note: `Emptied (was ${number(e.level_before_percent)}%${e.clean_cycles != null ? `, ${e.clean_cycles} cycles` : ""})`,
  }));
  const every = drawer.average_days_between_empties
    ? `Emptied every ~${number(drawer.average_days_between_empties, 1)} days (~${number(drawer.average_cycles_between_empties)} cycles)`
    : "No empties recorded in this range";
  // Forecast: dashed line from now to "empty it by" and "full", if within two weeks.
  const series = [{ name: "Drawer", color: LITTER, points: levels }];
  let chartDomain = domain;
  const fullAt = box.drawer_full_at ? new Date(box.drawer_full_at) : null;
  if (fullAt && box.drawer_needs_emptying_at && fullAt - Date.now() < 14 * 86_400_000) {
    const now = new Date();
    const dueAt = new Date(box.drawer_needs_emptying_at);
    series.push({
      name: "Forecast", color: LITTER, dashed: true,
      points: [
        { t: now, v: box.waste_drawer_percent },
        ...(dueAt > now ? [{ t: dueAt, v: box.drawer_usual_empty_percent, extra: "empty by" }] : []),
        ...(fullAt > now ? [{ t: fullAt, v: 100, extra: "full" }] : []),
      ],
    });
    chartDomain = [domain[0], new Date(Math.max(domain[1], fullAt) + 6 * 3_600_000)];
    if (dueAt > now) {
      empties.push({ t: dueAt, v: box.drawer_usual_empty_percent, color: LITTER,
        note: `Forecast: empty it by ${dayPart(dueAt)} (~${number(box.drawer_usual_empty_percent)}%)` });
    }
  }
  cards.push(chartCard({
    title: `${prefix}Waste drawer level`,
    sub: `${every} · dots mark empties · dashed line is the forecast`,
    draw: (el) => lineChart(el, {
      series,
      markers: empties, domain: chartDomain, yMin: 0, yMax: 100, ariaLabel: "Waste drawer level",
      format: (v) => `${number(v)}%`, titleFormat: longDateTime, tolerance: 45 * 60_000,
    }),
    table: {
      columns: ["Emptied", "Drawer before", "Cycles", "Days since previous"],
      rows: drawer.emptied.slice().reverse().map((e) => [
        longDateTime(e.timestamp), `${number(e.level_before_percent)}%`,
        e.clean_cycles ?? "—", e.days_since_previous != null ? number(e.days_since_previous, 1) : "—",
      ]),
    },
  }));

  // Weight: small multiples, one chart per cat (their scales differ ~3x)
  for (const cat of catNames.filter((c) => c !== "Unknown")) {
    const points = cats.filter((r) => r.cat === cat)
      .map((r) => ({ t: noon(r.date), v: r.weight_lbs, date: r.date, extra: `${r.visits} visits` }));
    const values = points.map((p) => p.v);
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    const pad = Math.max(0.5, (hi - lo) * 0.25);
    cards.push(chartCard({
      title: `${prefix}${cat}'s weight`,
      sub: `Median of each day's readings · latest ${number(values.at(-1), 2)} lb`,
      draw: (el) => lineChart(el, {
        series: [{ name: cat, color: state.catColors[cat] || LITTER, points }],
        domain, yMin: Math.max(0, lo - pad), yMax: hi + pad, ariaLabel: `${cat}'s weight`,
        format: (v) => `${number(v, 1)} lb`, titleFormat: (t) => shortDay(t),
      }),
      table: {
        columns: ["Date", "Median weight (lb)", "Visits"],
        rows: points.slice().reverse().map((p) => [shortDay(p.date), number(p.v, 2), p.extra.split(" ")[0]]),
      },
    }));
  }
  return cards;
}

// ---------- food charts ----------

function foodCharts(feeds, ctx) {
  const { daysList, labels, titles, domain } = ctx;
  const cards = [];

  // Food dispensed per day, one series per feeder
  const series = feeds.map(({ feeder, daily }) => {
    const byDay = Object.fromEntries(daily.map((d) => [d.date, d.portions]));
    const cats = state.feederCats[feeder.device_id] || [];
    return {
      name: cats.length ? `${cats.join(" & ")} (${feeder.name})` : feeder.name,
      color: state.feederColors[feeder.device_id] || SLOTS[0],
      values: daysList.map((d) => byDay[d] ?? 0),
    };
  });
  cards.push(chartCard({
    title: "Food dispensed per day",
    sub: "Portions (1 portion = 1/12 cup)",
    legend: series.map((s) => ({ name: s.name, color: s.color, kind: "rect" })),
    draw: (el) => columnChart(el, {
      categories: daysList, labels, titles, series, ariaLabel: "Food dispensed per day",
      format: (v) => number(v),
    }),
    table: {
      columns: ["Date", ...series.map((s) => s.name)],
      rows: daysList.map((d, i) => [titles[i], ...series.map((s) => s.values[i])]).reverse(),
    },
  }));

  // Time eating per cat per day (RFID)
  const catSeries = [];
  for (const { feeder, visits } of feeds) {
    const cats = [...new Set(visits.map((v) => v.pet_name))].sort();
    for (const cat of cats) {
      const rows = visits.filter((v) => v.pet_name === cat);
      catSeries.push({
        name: cats.length > 1 || feeds.length > 1 ? `${cat} (${feeder.name})` : cat,
        color: state.catColors[cat] || "var(--text-muted)",
        points: rows.map((r) => ({ t: noon(r.date), v: r.eating_seconds / 60, extra: `${r.visits} visits`, date: r.date })),
      });
    }
  }
  cards.push(chartCard({
    title: "Time eating per day",
    sub: "Minutes at the feeder, by cat (RFID)",
    legend: catSeries.map((s) => ({ name: s.name, color: s.color, kind: "line" })),
    draw: (el) => lineChart(el, {
      series: catSeries, domain, yMin: 0, endLabels: catSeries.length <= 4,
      ariaLabel: "Time eating per day", format: (v) => `${number(v)} min`, titleFormat: (t) => shortDay(t),
    }),
    table: {
      columns: ["Date", "Cat", "Minutes", "Visits"],
      rows: catSeries.flatMap((s) => s.points.map((p) => [p.date, s.name, number(p.v, 1), p.extra.split(" ")[0]]))
        .sort((a, b) => b[0].localeCompare(a[0]))
        .map(([date, ...rest]) => [shortDay(date), ...rest]),
    },
  }));
  return cards;
}

// ---------- range filter ----------

function setupRange() {
  const buttons = [...document.querySelectorAll(".range button")];
  const sync = () => buttons.forEach((b) => b.setAttribute("aria-checked", String(Number(b.dataset.days) === state.days)));
  sync();
  for (const button of buttons) {
    button.addEventListener("click", (event) => {
      event.preventDefault(); // the buttons sit in <summary>: don't toggle "More"
      state.days = Number(button.dataset.days);
      saveDays(state.days);
      sync();
      loadHistory();
    });
  }
}

// ---------- start ----------

function setLive(stateName) {
  const el = $("live");
  el.dataset.state = stateName;
  el.querySelector(".live-text").textContent =
    stateName === "live" ? "Live" : stateName === "down" ? "Disconnected" : "Connecting";
}

function renderToday() {
  $("today").textContent = new Date().toLocaleDateString([], {
    weekday: "long", day: "numeric", month: "long", year: "numeric",
  });
}

setupRange();
renderToday();
subscribe(onStatus, setLive);
setInterval(renderToday, 60_000);
setInterval(renderCards, 30_000); // keep "x min ago" fresh
setInterval(loadHistory, HISTORY_REFRESH_MS);
