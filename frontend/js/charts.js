// Dependency-free SVG charts following the data-viz mark specs:
// columns <= 24px with 4px rounded data-ends and 2px gaps, 2px lines, >= 8px markers
// with a 2px surface ring, hairline solid grid, one y-axis, hover + keyboard tooltips,
// and a table view for every chart.

import { h } from "./cards.js";

const NS = "http://www.w3.org/2000/svg";
const PLOT_H = 180;
const AXIS_H = 22;
const TOP = 10;

function s(tag, attrs = {}, ...children) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    // CSS variables don't resolve in presentation attributes; use style for colors.
    if ((k === "fill" || k === "stroke") && String(v).startsWith("var(")) el.style.setProperty(k, v);
    else el.setAttribute(k, v);
  }
  for (const c of children) if (c) el.append(c);
  return el;
}

function text(x, y, value, attrs = {}) {
  const t = s("text", { x, y, ...attrs });
  t.textContent = value;
  return t;
}

// ---------- tooltip (shared, built with textContent) ----------

const tooltip = () => document.getElementById("tooltip");

function showTooltip(clientX, clientY, title, rows, notes = []) {
  const tip = tooltip();
  tip.replaceChildren(h("div", { class: "tt-title", text: title }));
  for (const row of rows) {
    const key = h("span", { class: "tt-key" });
    key.style.background = row.color;
    tip.append(h("div", { class: "tt-row" }, key,
      h("span", { class: "tt-value", text: row.value }),
      h("span", { class: "tt-name", text: row.name })));
  }
  for (const note of notes) tip.append(h("div", { class: "tt-name", text: note }));
  tip.hidden = false;
  const { width, height } = tip.getBoundingClientRect();
  const x = Math.min(clientX + 14, window.innerWidth - width - 8);
  const y = clientY - height - 12 < 8 ? clientY + 16 : clientY - height - 12;
  tip.style.left = `${Math.max(8, x)}px`;
  tip.style.top = `${y}px`;
}

function hideTooltip() {
  const tip = tooltip();
  if (tip) tip.hidden = true;
}

// ---------- scales ----------

export function niceScale(min, max, ticks = 4) {
  if (!(max > min)) max = min + 1;
  const rough = (max - min) / ticks;
  const mag = 10 ** Math.floor(Math.log10(rough));
  const norm = rough / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const values = [];
  for (let v = lo; v <= hi + step / 2; v += step) values.push(Math.round(v * 1e6) / 1e6);
  return { min: lo, max: hi, ticks: values };
}

function yAxis(svg, scale, left, width, y, format) {
  for (const v of scale.ticks) {
    const py = y(v);
    svg.append(s("line", { class: v === scale.min ? "baseline" : "grid", x1: left, x2: left + width, y1: py, y2: py }));
    svg.append(text(left - 6, py + 4, format(v), { "text-anchor": "end" }));
  }
}

function leftMargin(scale, format) {
  const longest = Math.max(...scale.ticks.map((v) => format(v).length));
  return Math.max(28, longest * 6.5 + 12);
}

function roundedTop(x, y, w, hgt) {
  const r = Math.min(4, w / 2, hgt);
  return `M${x},${y + hgt}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + hgt}Z`;
}

// ---------- column chart (daily values, 1-4 series) ----------

/**
 * opts: { categories: string[], labels: string[] (x labels), titles: string[] (tooltip),
 *         series: [{ name, color, values: number[] }], format: v => string }
 */
export function columnChart(el, opts) {
  const { categories, series } = opts;
  const format = opts.format || ((v) => String(v));
  el.replaceChildren();
  if (!categories.length) {
    el.append(h("div", { class: "chart-empty", text: "No data in this range yet." }));
    return;
  }
  const width = Math.max(240, el.clientWidth || 400);
  const maxV = Math.max(0, ...series.flatMap((ser) => ser.values.map((v) => v ?? 0)));
  const scale = niceScale(0, maxV || 1);
  const left = leftMargin(scale, format);
  const plotW = width - left - 8;
  const y = (v) => TOP + PLOT_H - ((v - scale.min) / (scale.max - scale.min)) * PLOT_H;
  const svg = s("svg", { viewBox: `0 0 ${width} ${TOP + PLOT_H + AXIS_H}`, role: "img",
    "aria-label": opts.ariaLabel || "Column chart" });
  yAxis(svg, scale, left, plotW, y, format);

  const n = categories.length;
  const band = plotW / n;
  const ns = series.length;
  const barW = Math.max(2, Math.min(24, (band * 0.72 - (ns - 1) * 2) / ns));
  const groupW = ns * barW + (ns - 1) * 2;
  const labelEvery = Math.ceil(n / Math.max(2, Math.floor(plotW / 58)));

  categories.forEach((cat, i) => {
    const gx = left + i * band + (band - groupW) / 2;
    const bars = series.map((ser, j) => {
      const v = ser.values[i] ?? 0;
      const top = y(v);
      const hgt = y(scale.min) - top;
      if (hgt <= 0) return null;
      const bar = s("path", { class: "bar", d: roundedTop(gx + j * (barW + 2), top, barW, hgt), fill: ser.color });
      svg.append(bar);
      return bar;
    });
    // Label every k-th day counting back from the last, so the newest day is labeled.
    if ((n - 1 - i) % labelEvery === 0) {
      svg.append(text(left + i * band + band / 2, TOP + PLOT_H + 15, opts.labels[i], { "text-anchor": "middle" }));
    }
    const hit = s("rect", { class: "hit", x: left + i * band, y: TOP, width: band, height: PLOT_H, tabindex: "0",
      "aria-label": `${opts.titles[i]}: ${series.map((ser) => `${ser.name} ${format(ser.values[i] ?? 0)}`).join(", ")}` });
    const rows = () => series.map((ser) => ({ name: ser.name, color: ser.color, value: format(ser.values[i] ?? 0) }));
    const enter = (cx, cy) => {
      bars.forEach((b) => b && b.setAttribute("opacity", "0.75"));
      showTooltip(cx, cy, opts.titles[i], rows(), opts.notes?.[i] || []);
    };
    const leave = () => { bars.forEach((b) => b && b.removeAttribute("opacity")); hideTooltip(); };
    hit.addEventListener("pointermove", (e) => enter(e.clientX, e.clientY));
    hit.addEventListener("pointerleave", leave);
    hit.addEventListener("focus", () => { const r = hit.getBoundingClientRect(); enter(r.left + r.width / 2, r.top + 40); });
    hit.addEventListener("blur", leave);
    svg.append(hit);
  });
  el.append(svg);
}

// ---------- line chart (time series, 1-4 series, optional event markers) ----------

/**
 * opts: { series: [{ name, color, points: [{ t: Date, v: number }] }],
 *         domain: [Date, Date], yMin?, yMax?, format, titleFormat: Date => string,
 *         markers?: [{ t: Date, v: number, color, note: string }], endLabels?: bool,
 *         tolerance?: ms (how close a series point must be to the hovered x) }
 */
export function lineChart(el, opts) {
  const format = opts.format || ((v) => String(v));
  el.replaceChildren();
  const all = opts.series.flatMap((ser) => ser.points);
  if (!all.length) {
    el.append(h("div", { class: "chart-empty", text: "No data in this range yet." }));
    return;
  }
  const width = Math.max(240, el.clientWidth || 400);
  const values = all.map((p) => p.v);
  const scale = niceScale(opts.yMin ?? Math.min(...values), Math.max(opts.yMax ?? -Infinity, ...values));
  const left = leftMargin(scale, format);
  const right = opts.endLabels ? 64 : 10;
  const plotW = width - left - right;
  const [d0, d1] = opts.domain.map((d) => d.getTime());
  const x = (t) => left + ((t.getTime() - d0) / Math.max(1, d1 - d0)) * plotW;
  const y = (v) => TOP + PLOT_H - ((v - scale.min) / (scale.max - scale.min)) * PLOT_H;
  const svg = s("svg", { viewBox: `0 0 ${width} ${TOP + PLOT_H + AXIS_H}`, role: "img",
    "aria-label": opts.ariaLabel || "Line chart" });
  yAxis(svg, scale, left, plotW, y, format);

  // x ticks at local midnights
  const spanDays = (d1 - d0) / 86_400_000;
  const stepDays = Math.max(1, Math.ceil(spanDays / Math.max(2, Math.floor(plotW / 64))));
  const first = new Date(d0);
  first.setHours(0, 0, 0, 0);
  first.setDate(first.getDate() + 1);
  for (let t = new Date(first); t.getTime() <= d1; t.setDate(t.getDate() + stepDays)) {
    if (x(t) - left < 22 || left + plotW - x(t) < 18) continue; // keep clear of the y labels / edge
    svg.append(text(x(t), TOP + PLOT_H + 15, t.toLocaleDateString([], { month: "short", day: "numeric" }),
      { "text-anchor": "middle" }));
  }

  for (const ser of opts.series) {
    if (!ser.points.length) continue;
    const d = ser.points.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
    svg.append(s("path", { d, fill: "none", stroke: ser.color, "stroke-width": 2,
      "stroke-linejoin": "round", "stroke-linecap": "round" }));
    if (ser.points.length === 1) {
      const p = ser.points[0];
      svg.append(s("circle", { cx: x(p.t), cy: y(p.v), r: 4, fill: ser.color }));
    }
  }

  // End labels only when they won't collide (otherwise the legend + tooltip carry it).
  if (opts.endLabels) {
    const ends = opts.series.filter((ser) => ser.points.length)
      .map((ser) => ({ ser, p: ser.points[ser.points.length - 1] }))
      .map((e) => ({ ...e, py: y(e.p.v) }))
      .sort((a, b) => a.py - b.py);
    const clear = ends.every((e, i) => i === 0 || e.py - ends[i - 1].py >= 14);
    if (clear) {
      for (const { ser, p, py } of ends) {
        svg.append(text(x(p.t) + 8, py + 4, ser.name, { class: "label" }));
      }
    }
  }

  for (const m of opts.markers || []) {
    svg.append(s("circle", { cx: x(m.t), cy: y(m.v), r: 4.5, fill: m.color,
      stroke: "var(--surface-1)", "stroke-width": 2 }));
  }

  // Crosshair + tooltip, snapping to the nearest data time.
  const times = [...new Set(all.map((p) => p.t.getTime()))].sort((a, b) => a - b);
  const tolerance = opts.tolerance ?? 12 * 3_600_000;
  const cross = s("line", { class: "crosshair", y1: TOP, y2: TOP + PLOT_H, visibility: "hidden" });
  svg.append(cross);
  const dots = opts.series.map((ser) => {
    const c = s("circle", { r: 4, fill: ser.color, stroke: "var(--surface-1)", "stroke-width": 2, visibility: "hidden" });
    svg.append(c);
    return c;
  });
  const overlay = s("rect", { class: "hit", x: left, y: TOP, width: plotW, height: PLOT_H, tabindex: "0",
    "aria-label": `${opts.ariaLabel || "Chart"}. Use arrow keys to read values.` });
  svg.append(overlay);
  let index = times.length - 1;

  const nearestPoint = (points, t) => {
    let best = null;
    for (const p of points) {
      const dt = Math.abs(p.t.getTime() - t);
      if (dt <= tolerance && (!best || dt < best.dt)) best = { p, dt };
    }
    return best?.p;
  };

  const showAt = (i, clientX, clientY) => {
    index = Math.max(0, Math.min(times.length - 1, i));
    const t = times[index];
    const px = x(new Date(t));
    cross.setAttribute("x1", px);
    cross.setAttribute("x2", px);
    cross.setAttribute("visibility", "visible");
    const rows = [];
    opts.series.forEach((ser, j) => {
      const p = nearestPoint(ser.points, t);
      if (p) {
        dots[j].setAttribute("cx", x(p.t));
        dots[j].setAttribute("cy", y(p.v));
        dots[j].setAttribute("visibility", "visible");
        rows.push({ name: ser.name, color: ser.color, value: format(p.v) + (p.extra ? ` · ${p.extra}` : "") });
      } else {
        dots[j].setAttribute("visibility", "hidden");
      }
    });
    const notes = (opts.markers || []).filter((m) => Math.abs(m.t.getTime() - t) <= tolerance).map((m) => m.note);
    const rect = svg.getBoundingClientRect();
    const scaleX = rect.width / width;
    showTooltip(clientX ?? rect.left + px * scaleX, clientY ?? rect.top + 30, opts.titleFormat(new Date(t)), rows, notes);
  };
  const hide = () => {
    cross.setAttribute("visibility", "hidden");
    dots.forEach((d) => d.setAttribute("visibility", "hidden"));
    hideTooltip();
  };
  overlay.addEventListener("pointermove", (e) => {
    const rect = svg.getBoundingClientRect();
    const svgX = ((e.clientX - rect.left) / rect.width) * width;
    const t = d0 + ((svgX - left) / plotW) * (d1 - d0);
    let lo = 0;
    let hi = times.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (times[mid] < t) lo = mid; else hi = mid;
    }
    showAt(Math.abs(times[lo] - t) <= Math.abs(times[hi] - t) ? lo : hi, e.clientX, e.clientY);
  });
  overlay.addEventListener("pointerleave", hide);
  overlay.addEventListener("focus", () => showAt(index));
  overlay.addEventListener("blur", hide);
  overlay.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
      e.preventDefault();
      showAt(index + (e.key === "ArrowLeft" ? -1 : 1));
    }
  });
  el.append(svg);
}

// ---------- card wrapper: title, legend, chart/table toggle, resize ----------

/**
 * { title, sub, legend?: [{ name, color, kind: "rect" | "line" }], draw(el),
 *   table: { columns: string[], rows: (string|number)[][] } }
 */
export function chartCard(spec) {
  const body = h("div", { class: "chart-body" });
  const tableWrap = h("div", { class: "table-wrap", hidden: true });
  const toggle = h("button", { type: "button", class: "chart-toggle", "aria-pressed": "false", text: "Table" });
  const legend = spec.legend && spec.legend.length > 1
    ? h("ul", { class: "legend" }, spec.legend.map((item) => {
      const key = h("span", { class: item.kind === "line" ? "key-line" : "key-rect" });
      key.style.background = item.color;
      return h("li", {}, key, h("span", { text: item.name }));
    }))
    : null;
  const card = h("section", { class: "chart-card", "aria-label": spec.title },
    h("div", { class: "chart-head" },
      h("div", {}, h("h3", { class: "chart-title", text: spec.title }),
        spec.sub ? h("p", { class: "chart-sub", text: spec.sub }) : null),
      toggle),
    legend, body, tableWrap);

  const table = h("table", { class: "data-table" },
    h("thead", {}, h("tr", {}, spec.table.columns.map((c) => h("th", { scope: "col", text: c })))),
    h("tbody", {}, spec.table.rows.map((row) => h("tr", {}, row.map((cell) => h("td", { text: String(cell) }))))));
  tableWrap.append(table);
  toggle.addEventListener("click", () => {
    const showTable = tableWrap.hidden;
    tableWrap.hidden = !showTable;
    body.hidden = showTable;
    toggle.setAttribute("aria-pressed", String(showTable));
    toggle.textContent = showTable ? "Chart" : "Table";
  });

  let lastWidth = 0;
  const observer = new ResizeObserver(() => {
    const w = body.clientWidth;
    if (w && Math.abs(w - lastWidth) > 4) {
      lastWidth = w;
      spec.draw(body);
    }
  });
  observer.observe(body);
  card.dispose = () => observer.disconnect();
  return card;
}
