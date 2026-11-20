// Small formatting helpers. All times are shown in the viewer's local time.

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

export function toDate(value) {
  if (!value) return null;
  const d = value instanceof Date ? value : new Date(value);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "just now", "12 min ago", "3 h ago", "2 days ago", "in 4 h". */
export function relTime(value, now = Date.now()) {
  const d = toDate(value);
  if (!d) return "—";
  const diff = d.getTime() - now;
  const abs = Math.abs(diff);
  let text;
  if (abs < MIN) return diff > 0 ? "in under a minute" : "just now";
  if (abs < HOUR) text = `${Math.round(abs / MIN)} min`;
  else if (abs < DAY) text = `${Math.round(abs / HOUR)} h`;
  else {
    const days = Math.round(abs / DAY);
    text = `${days} day${days === 1 ? "" : "s"}`;
  }
  return diff > 0 ? `in ${text}` : `${text} ago`;
}

export function clock(value) {
  const d = toDate(value);
  return d ? d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "—";
}

/** "Today 7:00 PM", "Tomorrow 7:00 AM", or "Mon 7:00 AM". */
export function dayClock(value) {
  const d = toDate(value);
  if (!d) return "—";
  const today = new Date();
  const startOf = (x) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const dayDiff = Math.round((startOf(d) - startOf(today)) / DAY);
  const label =
    dayDiff === 0 ? "Today" : dayDiff === 1 ? "Tomorrow" : dayDiff === -1 ? "Yesterday"
      : d.toLocaleDateString([], { weekday: "short" });
  return `${label} ${clock(d)}`;
}

/** Local calendar date from "YYYY-MM-DD" (avoids the UTC-midnight shift). */
export function parseDay(isoDay) {
  const [y, m, d] = isoDay.split("-").map(Number);
  return new Date(y, m - 1, d);
}

export function shortDay(value) {
  const d = typeof value === "string" ? parseDay(value) : toDate(value);
  return d ? d.toLocaleDateString([], { month: "short", day: "numeric" }) : "—";
}

export function longDateTime(value) {
  const d = toDate(value);
  return d
    ? d.toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
    : "—";
}

export function duration(seconds) {
  if (seconds == null) return "—";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

export function number(value, digits = 0) {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString([], { maximumFractionDigits: digits, minimumFractionDigits: 0 });
}

/** Petlibro portions are 1/12 cup. */
export function portionsToCups(portions) {
  if (portions == null) return null;
  return portions / 12;
}

export function cups(portions) {
  const c = portionsToCups(portions);
  if (c == null) return "—";
  return `${number(c, 2)} cup${c === 1 ? "" : "s"}`;  // "0.33 cups"
}

export function titleCase(text) {
  if (!text) return "";
  return text.toLowerCase().replace(/(^|[\s_])([a-z])/g, (_, sep, ch) => `${sep === "_" ? " " : sep}${ch.toUpperCase()}`);
}

export function plural(count, word) {
  return `${number(count)} ${word}${count === 1 ? "" : "s"}`;
}

/** "Tue, Nov 24 · evening": a forecast is approximate, so name the part of the day. */
export function dayPart(value) {
  const d = toDate(value);
  return d ? `${shortDate(d)} · ${partOfDay(d).split(" ").pop()}` : "—";
}

/** "Tue, Nov 24" */
export function shortDate(value) {
  const d = toDate(value);
  return d ? d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" }) : "—";
}

/** "Tuesday evening" */
export function partOfDay(value) {
  const d = toDate(value);
  if (!d) return "—";
  const hour = d.getHours();
  const part = hour < 5 ? "night" : hour < 12 ? "morning" : hour < 17 ? "afternoon" : hour < 21 ? "evening" : "night";
  return `${d.toLocaleDateString([], { weekday: "long" })} ${part}`;
}
