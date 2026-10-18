// ============================================================================
// CineMatch — utils.js
// Small helpers used everywhere: DOM building, escaping, formatting.
// ============================================================================

/** Shorthand for querySelector / querySelectorAll */
export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

/** Escape text before putting it inside an HTML template string (prevents XSS). */
export function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/** Turn an HTML string into a real DOM element (the first element in it). */
export function el(html) {
  const tpl = document.createElement("template");
  tpl.innerHTML = html.trim();
  return tpl.content.firstElementChild;
}

export function debounce(fn, ms = 250) {
  let timer;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped;
}

export const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
export const clamp = (v, min, max) => Math.min(max, Math.max(min, v));

export const prefersReducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
/** True on devices with a real mouse (hover previews only make sense there). */
export const canHover = () => matchMedia("(hover: hover) and (pointer: fine)").matches;

/** 148 -> "2h 28m" */
export function formatRuntime(minutes) {
  if (!minutes) return "";
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (!h) return `${m}m`;
  return m ? `${h}h ${m}m` : `${h}h`;
}

/** 3725 -> "1:02:05" */
export function formatClock(seconds) {
  const s = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

/** 4210 -> "4.2 s", 75000 -> "1 min 15 s" */
export function formatMs(ms) {
  if (ms == null || Number.isNaN(ms)) return "–";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s % 60)} s`;
}

/** 0.784 -> "78%" */
export function formatPercent(x, digits = 0) {
  if (x == null || Number.isNaN(x)) return "–";
  return `${(x * 100).toFixed(digits)}%`;
}

export function formatNumber(n) {
  if (n == null) return "–";
  return new Intl.NumberFormat("en-IN").format(n);
}

/** Same rule as the backend (CONTRACT section 4): 5–11, 12–16, 17–20, 21–23, 0–4 */
export function timeOfDayFromHour(hour) {
  if (hour >= 5 && hour <= 11) return "morning";
  if (hour >= 12 && hour <= 16) return "afternoon";
  if (hour >= 17 && hour <= 20) return "evening";
  if (hour >= 21 && hour <= 23) return "night";
  return "late_night";
}

/** "Christopher Nolan" -> "CN" */
export function initials(name = "") {
  const parts = String(name).trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

/** Stable integer hash of a string (used to seed colours for names). */
export function hashString(str = "") {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** Deterministic random numbers: the same seed always gives the same sequence. */
export function seededRandom(seed) {
  let a = (seed >>> 0) || 1;
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Context objects travel in the URL (#/results?c=...) so results are shareable. */
export function encodeCtx(obj) {
  const json = JSON.stringify(obj);
  const bytes = new TextEncoder().encode(json);
  let bin = "";
  bytes.forEach((b) => { bin += String.fromCharCode(b); });
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
export function decodeCtx(str) {
  try {
    const b64 = str.replace(/-/g, "+").replace(/_/g, "/");
    const bin = atob(b64);
    const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return {};
  }
}

/** Remove empty / default values so the context only carries real choices. */
export function cleanContext(ctx = {}) {
  const out = {};
  for (const [key, value] of Object.entries(ctx)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value) && value.length === 0) continue;
    if ((key === "franchise_mode" || key === "content_type") && value === "any") continue;
    out[key] = value;
  }
  return out;
}

/** How many filters the user actually chose (hour is automatic, so it doesn't count). */
export function countFilters(ctx = {}) {
  return Object.keys(cleanContext(ctx)).filter((k) => k !== "hour").length;
}

/** ["a","b","c"] -> "a, b and c" */
export function listToText(items) {
  const list = items.filter(Boolean);
  if (list.length <= 1) return list.join("");
  return `${list.slice(0, -1).join(", ")} and ${list[list.length - 1]}`;
}

export function plural(n, word, pluralWord = `${word}s`) {
  return `${n} ${n === 1 ? word : pluralWord}`;
}

/** Wait for the next animation frame (lets the browser paint before animating). */
export const nextFrame = () => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));

/** Trap keyboard focus inside a dialog. Returns a function that removes the trap. */
export function trapFocus(container) {
  const selector = 'a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';
  function onKey(e) {
    if (e.key !== "Tab") return;
    const items = $$(selector, container).filter((n) => n.offsetParent !== null || n === document.activeElement);
    if (!items.length) return;
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
  container.addEventListener("keydown", onKey);
  return () => container.removeEventListener("keydown", onKey);
}

/** Lock / unlock page scrolling behind overlays (counts nested overlays). */
let scrollLocks = 0;
export function lockScroll() {
  scrollLocks++;
  if (scrollLocks === 1) {
    const bar = window.innerWidth - document.documentElement.clientWidth;
    document.body.style.paddingRight = bar ? `${bar}px` : "";
    document.body.style.overflow = "hidden";
  }
}
export function unlockScroll() {
  scrollLocks = Math.max(0, scrollLocks - 1);
  if (scrollLocks === 0) {
    document.body.style.overflow = "";
    document.body.style.paddingRight = "";
  }
}
