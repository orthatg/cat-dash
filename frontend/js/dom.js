// DOM helpers + pictograms. Device and cat names are data: always set via textContent.

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat(Infinity)) {
    if (child == null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const SVG_NS = "http://www.w3.org/2000/svg";

// 24px line pictograms (stroke = currentColor).
const ICONS = {
  paw: '<circle cx="7" cy="9" r="1.8"/><circle cx="11" cy="6" r="1.8"/><circle cx="15" cy="6.5" r="1.8"/><circle cx="18" cy="10" r="1.6"/><path d="M8.5 17.5c0-2.6 1.9-5 4-5s4.5 2.6 4.5 5c0 1.6-1.4 2.2-2.6 1.8-1.1-.4-2.1-.4-3.2 0-1.3.4-2.7-.2-2.7-1.8Z"/>',
  sparkle: '<path d="M12 3.5 13.6 9l5.4 1.6-5.4 1.6L12 17.7l-1.6-5.5L5 10.6 10.4 9 12 3.5Z"/><path d="M18.5 16v4M16.5 18h4"/>',
  litter: '<path d="M4 11h16l-1.4 7.2a2 2 0 0 1-2 1.8H7.4a2 2 0 0 1-2-1.8L4 11Z"/><path d="M7.5 8.2h.01M10.5 7h.01M13.5 8h.01M16.5 7.2h.01M9 14.5h.01M12 15.5h.01M15 14.5h.01"/>',
  calendar: '<rect x="4" y="5.5" width="16" height="14.5" rx="2.5"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>',
  bowl: '<path d="M3.5 11.5h17a8.5 8.5 0 0 1-17 0Z"/><path d="M8 8.5c.7-.8 1.8-.8 2.5 0M13.5 8.5c.7-.8 1.8-.8 2.5 0"/>',
  bowlEmpty: '<path d="M3.5 11.5h17a8.5 8.5 0 0 1-17 0Z"/>',
  cycle: '<path d="M19 12a7 7 0 1 1-2.1-5"/><path d="M19.5 4.5v4h-4"/>',
  scale: '<rect x="4" y="4" width="16" height="16" rx="4"/><path d="M8.5 9.5a4.5 4.5 0 0 1 7 0L12 12"/>',
  alert: '<path d="M12 4.5 21 19.5H3L12 4.5Z"/><path d="M12 10v4M12 16.8h.01"/>',
  check: '<circle cx="12" cy="12" r="8"/><path d="m8.5 12.2 2.4 2.4 4.6-5"/>',
  x: '<circle cx="12" cy="12" r="8"/><path d="m9.2 9.2 5.6 5.6M14.8 9.2l-5.6 5.6"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  arrowUp: '<path d="M12 19V5M6.5 10.5 12 5l5.5 5.5"/>',
  arrowDown: '<path d="M12 5v14M6.5 13.5 12 19l5.5-5.5"/>',
};

export function pictogram(name, { size = 20, label } = {}) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", size);
  svg.setAttribute("height", size);
  svg.setAttribute("class", `picto picto-${name}`);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  if (label) {
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", label);
  } else {
    svg.setAttribute("aria-hidden", "true");
  }
  svg.innerHTML = ICONS[name] || ""; // static, trusted markup only
  return svg;
}

export function errorsBanner(container, status) {
  container.replaceChildren();
  const messages = [];
  const label = (name) => (name === "litterrobot" ? "Litter-Robot" : name === "petlibro" ? "Petlibro" : name);
  for (const [name, message] of Object.entries(status.errors || {})) messages.push(`${label(name)}: ${message}`);
  for (const [name, ok] of Object.entries(status.configured || {})) {
    if (!ok) messages.push(`${label(name)} isn't configured (see backend/README.md).`);
  }
  container.hidden = messages.length === 0;
  for (const message of messages) container.append(h("p", {}, pictogram("alert", { size: 16 }), h("span", { text: message })));
}

// Cat portraits live in assets/cats/<name>.jpg (lower-case). Missing file -> colored dot.
export function catAvatar(name, color, size = 32) {
  const wrap = h("span", { class: "avatar", "aria-hidden": "true" });
  wrap.style.setProperty("--ring", color || "var(--ink-3)");
  wrap.style.width = wrap.style.height = `${size}px`;
  if (!name) return wrap;
  const img = h("img", { src: `assets/cats/${encodeURIComponent(name.toLowerCase())}.jpg`, alt: "", loading: "lazy", decoding: "async" });
  img.addEventListener("error", () => img.remove(), { once: true });
  wrap.append(img);
  return wrap;
}
