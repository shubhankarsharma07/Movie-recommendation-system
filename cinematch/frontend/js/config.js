// ============================================================================
// CineMatch — config.js
// Everything you might want to change when deploying lives here.
// ============================================================================

// Where the FastAPI backend lives.
//   ""  = same origin. For local dev the backend serves this folder at
//         http://localhost:8000/, so nothing needs changing.
//   In production put your Render URL here, e.g. "https://cinematch-api.onrender.com"
export const API_BASE = "";

// Mock mode runs the whole UI on fake data from js/mock.js (no backend needed).
// Turn it on by setting MOCK_DEFAULT = true, or by opening the site with ?mock=1
// (remembered for the browser tab; ?mock=0 turns it off again).
const MOCK_DEFAULT = false;

function readMockFlag() {
  const params = new URLSearchParams(location.search);
  if (params.has("mock")) {
    const on = params.get("mock") !== "0";
    try { sessionStorage.setItem("cinematch_mock", on ? "1" : "0"); } catch { /* private mode */ }
    return on;
  }
  try {
    const saved = sessionStorage.getItem("cinematch_mock");
    if (saved !== null) return saved === "1";
  } catch { /* ignore */ }
  return MOCK_DEFAULT;
}

export const MOCK = readMockFlag();

// TMDB image sizes used by the backend's poster_url / backdrop_url
export const TMDB_IMG = "https://image.tmdb.org/t/p/";

// A request slower than this is treated as "the server is probably asleep"
export const REQUEST_TIMEOUT_MS = 15000;

// Behaviour events are batched and sent this often
export const EVENT_FLUSH_MS = 4000;

// The simulated player plays this many times faster than real time,
// so a 2-hour film can be "watched" in 2 minutes during a demo.
export const SIM_SPEED = 60;

// How long to wait for the browser's location permission before carrying on
export const GEO_TIMEOUT_MS = 7000;
