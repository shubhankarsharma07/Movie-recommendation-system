// ============================================================================
// CineMatch — tracking.js
// Behaviour logging (SRS Module 3). Events are queued and sent in batches to
// POST /api/events every few seconds and when the page is hidden/closed.
//
// What we log here:
//   impression   — a row/list scrolled into view (once per row per load)
//   select       — first details-open or play from a list; value = browse-to-
//                  select time in ms (FR-3.3), measured from when that list was
//                  first shown
//   details_open, trailer_open, search, filter_apply, binge_next
// (dismiss is logged by the backend inside POST /recommendations/{id}/dismiss,
//  and playback events go to the /api/playback/* endpoints.)
// ============================================================================

import { api } from "./api.js";
import { isLoggedIn } from "./auth.js";
import { EVENT_FLUSH_MS } from "./config.js";

const queue = [];
const shownAt = new Map();   // list key -> performance.now() when first shown
const selected = new Set();  // list keys that already produced a "select"
const impressed = new Set(); // list keys that already produced an "impression"
let observer = null;
let localCounter = 0;

/**
 * A "source" describes where a card was shown:
 *   { row_id: "for_you", request_id: "uuid" }
 * Lists without a server request id (search, browse) get a local key so each
 * time the list is shown counts separately.
 */
export function makeSource(row_id, request_id = null) {
  return { row_id, request_id, key: `${request_id || `local${++localCounter}`}:${row_id}`, createdAt: performance.now() };
}

export function track(type, fields = {}) {
  const event = { type };
  for (const k of ["movie_id", "request_id", "row_id", "value", "position_sec"]) {
    if (fields[k] !== undefined && fields[k] !== null) event[k] = fields[k];
  }
  queue.push(event);
  if (queue.length >= 40) flush();
}

export function flush({ keepalive = false } = {}) {
  if (!queue.length || !isLoggedIn()) return;
  const events = queue.splice(0, queue.length);
  api.post("/api/events", { events }, { wake: false, keepalive }).catch(() => {
    // put them back once if the server is unreachable; they'll go with the next batch
    if (!keepalive && queue.length < 200) queue.unshift(...events);
  });
}

setInterval(flush, EVENT_FLUSH_MS);
addEventListener("pagehide", () => flush({ keepalive: true }));
addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") flush({ keepalive: true });
});

/** A grid/list was rendered and is visible right away (results, search, browse). */
export function markListShown(source) {
  if (source && !shownAt.has(source.key)) shownAt.set(source.key, performance.now());
}

/** Watch a carousel row: log an impression and start its browse-to-select clock when it scrolls into view. */
export function observeRow(element, source) {
  if (!("IntersectionObserver" in window)) {
    markListShown(source);
    return;
  }
  if (!observer) {
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const src = entry.target._cmSource;
        if (!src) continue;
        markListShown(src); // the browse-to-select clock starts as soon as any of the row is visible
        if (entry.intersectionRatio < 0.35 || impressed.has(src.key)) continue;
        impressed.add(src.key);
        observer.unobserve(entry.target);
        track("impression", { row_id: src.row_id, request_id: src.request_id });
      }
    }, { threshold: [0, 0.35] });
  }
  element._cmSource = source;
  observer.observe(element);
}

/** First details-open / play on an item from a list → "select" with browse-to-select ms. */
export function trackSelect(source, movieId) {
  if (!source?.key || selected.has(source.key)) return;
  const t0 = shownAt.get(source.key) ?? source.createdAt; // fallback: when the list was built
  if (t0 == null) return;
  selected.add(source.key);
  track("select", { movie_id: movieId, row_id: source.row_id, request_id: source.request_id, value: Math.round(performance.now() - t0) });
}
