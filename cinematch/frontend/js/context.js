// ============================================================================
// CineMatch — context.js
// Detects "where and when" for FR-2.2 / FR-2.4:
//   * asks the browser for location (rounded to ~1 km for privacy),
//   * sends lat/lon + the local hour to GET /api/context,
//   * if location is denied we never send coordinates, so the backend skips
//     the weather lookup and we fall back to time of day only.
// ============================================================================

import { api } from "./api.js";
import { GEO_TIMEOUT_MS } from "./config.js";
import { state, emit, effectiveContext } from "./state.js";

let geoPromise = null;
const round = (n) => Math.round(n * 100) / 100;

/**
 * Resolves to { lat, lon } or null. Never rejects.
 * If the user answers the permission prompt after our timeout, we still pick
 * the answer up later and emit "geo:changed".
 */
export function getCoords() {
  if (geoPromise) return geoPromise;
  geoPromise = new Promise((resolve) => {
    if (!("geolocation" in navigator)) {
      state.geo = { status: "unavailable", coords: null };
      resolve(null);
      return;
    }
    let settled = false;
    const finish = (coords) => { if (!settled) { settled = true; resolve(coords); } };
    const timer = setTimeout(() => finish(null), GEO_TIMEOUT_MS);

    const ask = () => navigator.geolocation.getCurrentPosition(
      (pos) => {
        clearTimeout(timer);
        const coords = { lat: round(pos.coords.latitude), lon: round(pos.coords.longitude) };
        const late = settled;
        state.geo = { status: "granted", coords };
        finish(coords);
        if (late) emit("geo:changed", state.geo);
      },
      (err) => {
        clearTimeout(timer);
        state.geo = { status: err.code === 1 ? "denied" : "unavailable", coords: null };
        finish(null);
        emit("geo:changed", state.geo);
      },
      { enableHighAccuracy: false, timeout: GEO_TIMEOUT_MS, maximumAge: 15 * 60 * 1000 }
    );

    // If permission is already denied, don't even try (and don't wait)
    if (navigator.permissions?.query) {
      navigator.permissions.query({ name: "geolocation" }).then((p) => {
        if (p.state === "denied") {
          clearTimeout(timer);
          state.geo = { status: "denied", coords: null };
          finish(null);
        } else ask();
      }).catch(ask);
    } else ask();
  });
  return geoPromise;
}

/** Ask again (e.g. the user pressed "Turn on location"). */
export function retryLocation() {
  geoPromise = null;
  return getCoords().then(() => refreshContext());
}

/** Store a /api/context-shaped object and tell everyone. */
export function setContext(ctx) {
  if (!ctx) return;
  state.context = ctx;
  emit("context:changed", effectiveContext());
}

/** GET /api/context with whatever we know. Quiet: never shows errors. */
export async function refreshContext() {
  const coords = state.geo.coords;
  try {
    const ctx = await api.get("/api/context", { lat: coords?.lat, lon: coords?.lon, hour: new Date().getHours() }, { wake: false });
    setContext(ctx);
  } catch { /* the chip keeps showing time of day */ }
}
