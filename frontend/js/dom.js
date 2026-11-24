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

// 24px duotone pictograms: a 1.8px outline in currentColor over a light fill of the same color.
const ICONS = {
  cat: '<path fill="currentColor" fill-opacity=".16" d="M4.8 10V4.6l3.7 2.5a8.4 8.4 0 0 1 7 0l3.7-2.5V10c.9 1.2 1.4 2.6 1.4 4.1 0 3.7-3.6 6.4-8.6 6.4s-8.6-2.7-8.6-6.4c0-1.5.5-2.9 1.4-4.1Z"/><path d="M9 13.2h.01M15 13.2h.01" stroke-width="2.6"/><path d="M10.7 16.3c.4.4.8.6 1.3.6s.9-.2 1.3-.6"/>',
  paw: '<path fill="currentColor" fill-opacity=".16" d="M8.4 17.6c0-2.7 1.8-5.2 3.6-5.2s3.6 2.5 3.6 5.2c0 1.5-1.2 2.1-2.4 1.7-.8-.3-1.6-.3-2.4 0-1.2.4-2.4-.2-2.4-1.7Z"/><circle cx="6.6" cy="10" r="1.7"/><circle cx="10.2" cy="6.6" r="1.7"/><circle cx="14.2" cy="6.6" r="1.7"/><circle cx="17.6" cy="10" r="1.7"/>',
  drawer: '<rect fill="currentColor" fill-opacity=".16" x="3.5" y="8" width="17" height="11.5" rx="1.5"/><path d="M5.5 8V5.5h13V8M3.5 12.5h17M10 16h4"/>',
  bin: '<path fill="currentColor" fill-opacity=".16" d="M6 7.5h12l-1 12a1.6 1.6 0 0 1-1.6 1.5H8.6A1.6 1.6 0 0 1 7 19.5L6 7.5Z"/><path d="M4 7.5h16M9.5 7.5V4.5h5v3M10 11.5v6M14 11.5v6"/>',
  litter: '<path fill="currentColor" fill-opacity=".16" d="M3.5 10.5h17l-1.5 8a2 2 0 0 1-2 1.6H7a2 2 0 0 1-2-1.6l-1.5-8Z"/><path d="M7 15c1.7-1.5 3.3-1.5 5 0s3.3 1.5 5 0"/><path d="M8 7.5c1-1.5 2.5-1.5 3.5 0M13 6.5c1-1.5 2.5-1.5 3.5 0"/>',
  broom: '<path fill="currentColor" fill-opacity=".16" d="m13 11.5 5.5 5.5-2 3.5-9-9 2-3.5L13 11.5Z"/><path d="M13 11.5 19.5 5M7 11.5l-3.5 3.5M9.5 14l-3 3"/>',
  sparkle: '<path fill="currentColor" fill-opacity=".16" d="M12 3.5c.6 4.3 1.8 5.5 6.1 6.1-4.3.6-5.5 1.8-6.1 6.1-.6-4.3-1.8-5.5-6.1-6.1 4.3-.6 5.5-1.8 6.1-6.1Z"/><path d="M18.5 16.5V20M16.75 18.25h3.5"/>',
  calendar: '<rect fill="currentColor" fill-opacity=".16" x="4" y="5.5" width="16" height="14.5" rx="2"/><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4"/>',
  clock: '<circle fill="currentColor" fill-opacity=".16" cx="12" cy="12" r="8.5"/><path d="M12 7v5.2l3.2 1.8"/>',
  bowl: '<path fill="currentColor" fill-opacity=".16" d="M3.5 11.5h17a8.5 8.5 0 0 1-17 0Z"/><path d="M8.5 8h.01M12 6.5h.01M15.5 8h.01" stroke-width="2.4"/>',
  bowlEmpty: '<path fill="currentColor" fill-opacity=".16" d="M3.5 11.5h17a8.5 8.5 0 0 1-17 0Z"/><path d="M9 7.5h6" stroke-dasharray="1 3"/>',
  cycle: '<path d="M19 12a7 7 0 1 1-2.1-5"/><path d="M19.5 4.5v4h-4"/>',
  scale: '<rect fill="currentColor" fill-opacity=".16" x="4" y="4" width="16" height="16" rx="3"/><path d="M8.5 9.5a4.5 4.5 0 0 1 7 0L12 12"/>',
  alert: '<path fill="currentColor" fill-opacity=".16" d="M12 4 21.5 20h-19L12 4Z"/><path d="M12 10v4.5M12 17.2h.01" stroke-width="2.2"/>',
  check: '<circle fill="currentColor" fill-opacity=".16" cx="12" cy="12" r="8.5"/><path d="m8.3 12.3 2.5 2.5 4.9-5.2" stroke-width="2.2"/>',
  x: '<circle fill="currentColor" fill-opacity=".16" cx="12" cy="12" r="8.5"/><path d="m9 9 6 6M15 9l-6 6" stroke-width="2.2"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  arrowUp: '<path d="M12 19V5M6.5 10.5 12 5l5.5 5.5"/>',
  arrowDown: '<path d="M12 5v14M6.5 13.5 12 19l5.5-5.5"/>',
  robot: '<circle fill="currentColor" fill-opacity=".16" cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="2.6"/><path d="M6.2 6.8a8.5 8.5 0 0 1 11.6 0"/>',
  battery: '<rect fill="currentColor" fill-opacity=".16" x="3" y="7.5" width="16" height="9.5" rx="2"/><path d="M21.5 10.8v2.8"/>',
  bolt: '<path fill="currentColor" fill-opacity=".16" d="M13 3.5 6.5 13.5H12l-1 7 6.5-10H12l1-7Z"/>',
  dock: '<path fill="currentColor" fill-opacity=".16" d="M6.5 10v9.5h11V10l-5.5-5-5.5 5Z"/><path d="m3.5 11.5 8.5-7.5 8.5 7.5"/>',
  pause: '<rect fill="currentColor" fill-opacity=".16" x="6.5" y="5.5" width="4" height="13" rx="1"/><rect fill="currentColor" fill-opacity=".16" x="13.5" y="5.5" width="4" height="13" rx="1"/>',
  help: '<circle fill="currentColor" fill-opacity=".16" cx="12" cy="12" r="8.5"/><path d="M9.8 9.7a2.3 2.3 0 0 1 4.4.8c0 1.5-2.2 1.7-2.2 3.2M12 16.7h.01" stroke-width="2"/>',
  wifi: '<path d="M3.5 9.5a12.5 12.5 0 0 1 17 0M6.5 13a8 8 0 0 1 11 0M9.5 16.4a3.5 3.5 0 0 1 5 0"/><path d="M12 19.7h.01" stroke-width="2.6"/>',
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
    if (!ok && name !== "roomba") // the Roomba tile has its own calm "not set up yet" state
      messages.push(`${label(name)} isn't configured (see backend/README.md).`);
  }
  container.hidden = messages.length === 0;
  for (const message of messages) container.append(h("p", {}, pictogram("alert", { size: 16 }), h("span", { text: message })));
}

// Cat portraits live in assets/cats/<name>.jpg (lower-case). Missing file -> colored disc.
// `size` is the whole circle; `image` is the picture inside it. Growing the circle twice as
// fast as the picture leaves a white margin, so the drawing sits inside the ring.
export function catAvatar(name, color, { size = 32, image = size } = {}) {
  const wrap = h("span", { class: "avatar", "aria-hidden": "true" });
  wrap.style.setProperty("--ring", color || "var(--ink-3)");
  wrap.style.width = wrap.style.height = `${size}px`;
  if (!name) return wrap;
  const img = h("img", { src: `assets/cats/${encodeURIComponent(name.toLowerCase())}.jpg`, alt: "", loading: "lazy", decoding: "async" });
  img.style.width = img.style.height = `${image}px`;
  img.addEventListener("error", () => { img.remove(); wrap.classList.add("no-photo"); }, { once: true });
  wrap.append(img);
  return wrap;
}
