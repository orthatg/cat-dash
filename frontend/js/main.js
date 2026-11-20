import { api, subscribe } from "./api.js";
import { errorsBanner, feederCard, litterCard } from "./cards.js";
import { chartCard, columnChart, lineChart } from "./charts.js";
import { longDateTime, number, parseDay, shortDay } from "./format.js";

// Colors follow the entity (fixed slot per feeder / cat), never its rank.
const SLOTS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];
const HISTORY_REFRESH_MS = 10 * 60_000;

const state = {
  status: null,
  days: loadDays(),
  drawer: {}, // litter box id -> /drawer response
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

// ---------- cards ----------

function renderCards() {
  const status = state.status;
  if (!status) return;
  errorsBanner($("errors"), status);
  const cards = [
    ...status.litter_boxes.slice().sort(byName).map((box) => litterCard(box, state.drawer[box.device_id])),
    ...status.feeders.slice().sort(byName).map((feeder) => feederCard(feeder)),
  ];
  $("cards").replaceChildren(...(cards.length ? cards : [document.createTextNode("No devices yet.")]));
}

// Reload history when something that changes it happens (a cycle, an empty, a feed).
function historyKey(status) {
  return JSON.stringify([
    status.litter_boxes.map((b) => [b.last_clean_cycle_at, b.last_emptied_at]),
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
  const charts = $("charts");
  charts.classList.add("loading"); // hold the previous render, no skeleton flash
  const run = (async () => {
    const boxes = status.litter_boxes.slice().sort(byName);
    const feeders = status.feeders.slice().sort(byName);
    const [litter, feeds] = await Promise.all([
      Promise.all(boxes.map(async (box) => ({
        box,
        daily: await api.litterDaily(box.device_id, days),
        drawer: await api.litterDrawer(box.device_id, days),
      }))),
      Promise.all(feeders.map(async (feeder) => ({
        feeder,
        daily: await api.feederDaily(feeder.device_id, days),
        visits: await api.feederVisitsDaily(feeder.device_id, days),
      }))),
    ]);
    return { litter, feeds };
  })();
  loading = run;
  try {
    const data = await run;
    if (loading !== run) return; // a newer load superseded this one
    for (const { box, drawer } of data.litter) state.drawer[box.device_id] = drawer;
    renderCards();
    renderCharts(data, days);
  } catch (err) {
    console.error(err);
  } finally {
    if (loading === run) charts.classList.remove("loading");
  }
}

function renderCharts({ litter, feeds }, days) {
  const container = $("charts");
  for (const old of container.children) old.dispose?.();
  const cards = [];
  const daysList = dayList(days);
  const labels = daysList.map(shortDay);
  const titles = daysList.map((d) => parseDay(d).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }));
  const domain = [new Date(Date.now() - days * 86_400_000), new Date()];

  for (const { box, daily, drawer } of litter) {
    const name = litter.length > 1 ? `${box.name}: ` : "";
    const byDay = Object.fromEntries(daily.map((d) => [d.date, d]));

    // 1. Clean cycles per day
    const cycles = daysList.map((d) => byDay[d]?.clean_cycles ?? 0);
    const avg = cycles.reduce((a, b) => a + b, 0) / Math.max(1, cycles.length);
    cards.push(chartCard({
      title: `${name}Clean cycles per day`,
      sub: `${box.name} · average ${number(avg, 1)} a day`,
      draw: (el) => columnChart(el, {
        categories: daysList, labels, titles, ariaLabel: "Clean cycles per day",
        series: [{ name: "Clean cycles", color: SLOTS[0], values: cycles }],
        format: (v) => number(v),
      }),
      table: { columns: ["Date", "Clean cycles"], rows: daysList.map((d, i) => [titles[i], cycles[i]]) },
    }));

    // 2. Waste drawer level, with each inferred empty marked
    const levels = drawer.levels.map((l) => ({ t: new Date(l.timestamp), v: l.percent }));
    const empties = drawer.emptied.map((e) => ({
      t: new Date(e.timestamp), v: 0, color: SLOTS[0],
      note: `Emptied (was ${number(e.level_before_percent)}%${e.clean_cycles != null ? `, ${e.clean_cycles} cycles` : ""})`,
    }));
    const every = drawer.average_days_between_empties
      ? `Emptied every ~${number(drawer.average_days_between_empties, 1)} days (~${number(drawer.average_cycles_between_empties)} cycles)`
      : "Dots mark when the drawer was emptied";
    cards.push(chartCard({
      title: `${name}Waste drawer level`,
      sub: `${every} · dots mark empties`,
      draw: (el) => lineChart(el, {
        series: [{ name: "Drawer", color: SLOTS[0], points: levels }],
        markers: empties, domain, yMin: 0, yMax: 100, ariaLabel: "Waste drawer level",
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

    // 3. Cat weight (median of each day's readings)
    const weights = daily.filter((d) => d.cat_weight_lbs != null)
      .map((d) => ({ t: noon(d.date), v: d.cat_weight_lbs, date: d.date, extra: `${d.weight_readings} readings` }));
    cards.push(chartCard({
      title: `${name}Cat weight`,
      sub: `${box.name} · median of each day's readings (lb)`,
      draw: (el) => lineChart(el, {
        series: [{ name: "Weight", color: SLOTS[0], points: weights }],
        domain, ariaLabel: "Cat weight",
        yMin: Math.floor(Math.min(...weights.map((w) => w.v), 99) - 1),
        format: (v) => `${number(v, 1)} lb`, titleFormat: (t) => shortDay(t),
      }),
      table: {
        columns: ["Date", "Median weight (lb)", "Readings"],
        rows: weights.slice().reverse().map((w) => [shortDay(w.date), number(w.v, 2), w.extra.split(" ")[0]]),
      },
    }));
  }

  if (feeds.length) {
    // 4. Food dispensed per day, one series per feeder
    const series = feeds.map(({ feeder, daily }, i) => {
      const byDay = Object.fromEntries(daily.map((d) => [d.date, d.portions]));
      return { name: feeder.name, color: SLOTS[i % SLOTS.length], values: daysList.map((d) => byDay[d] ?? 0) };
    });
    cards.push(chartCard({
      title: "Food dispensed per day",
      sub: "Portions (1 portion = 1/12 cup)",
      legend: series.map((ser) => ({ name: ser.name, color: ser.color, kind: "rect" })),
      draw: (el) => columnChart(el, {
        categories: daysList, labels, titles, series, ariaLabel: "Food dispensed per day",
        format: (v) => number(v),
      }),
      table: {
        columns: ["Date", ...series.map((ser) => ser.name)],
        rows: daysList.map((d, i) => [titles[i], ...series.map((ser) => ser.values[i])]).reverse(),
      },
    }));

    // 5. Time eating per cat per day (RFID). Cats are ordered by feeder then name, so
    // with one cat per feeder each cat shares its feeder's color.
    const catSeries = [];
    feeds.forEach(({ feeder, visits }, i) => {
      const cats = [...new Set(visits.map((v) => v.pet_name))].sort();
      for (const cat of cats) {
        const rows = visits.filter((v) => v.pet_name === cat);
        catSeries.push({
          name: cats.length > 1 || feeds.length > 1 ? `${cat} (${feeder.name})` : cat,
          color: SLOTS[catSeries.length % SLOTS.length],
          points: rows.map((r) => ({ t: noon(r.date), v: r.eating_seconds / 60, extra: `${r.visits} visits`, date: r.date })),
        });
      }
    });
    cards.push(chartCard({
      title: "Time eating per day",
      sub: "Minutes at the feeder, by cat (RFID)",
      legend: catSeries.map((ser) => ({ name: ser.name, color: ser.color, kind: "line" })),
      draw: (el) => lineChart(el, {
        series: catSeries, domain, yMin: 0, endLabels: catSeries.length <= 4,
        ariaLabel: "Time eating per day", format: (v) => `${number(v)} min`, titleFormat: (t) => shortDay(t),
      }),
      table: {
        columns: ["Date", "Cat", "Minutes", "Visits"],
        rows: catSeries.flatMap((ser) => ser.points.map((p) => [p.date, ser.name, number(p.v, 1), p.extra.split(" ")[0]]))
          .sort((a, b) => b[0].localeCompare(a[0]))
          .map(([date, ...rest]) => [shortDay(date), ...rest]),
      },
    }));
  }

  container.replaceChildren(...cards);
}

// ---------- range filter ----------

function setupRange() {
  const buttons = [...document.querySelectorAll(".range button")];
  const sync = () => buttons.forEach((b) => b.setAttribute("aria-checked", String(Number(b.dataset.days) === state.days)));
  sync();
  for (const button of buttons) {
    button.addEventListener("click", () => {
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
    stateName === "live" ? "Live" : stateName === "down" ? "Disconnected" : "Connecting…";
}

setupRange();
subscribe(onStatus, setLive);
setInterval(renderCards, 30_000); // keep "x min ago" fresh
setInterval(loadHistory, HISTORY_REFRESH_MS);
