// ============================================================================
// CineMatch — api.js
// Every call to the backend goes through request() so that we handle, in one
// place:
//   * the JWT "Authorization: Bearer ..." header
//   * timeouts and the Render cold start ("Waking up the server…")
//   * 401 → back to the sign-in page
//   * turning {"detail": "..."} errors into readable messages
//   * mock mode (?mock=1) — requests are answered by js/mock.js instead
// ============================================================================

import { API_BASE, MOCK, REQUEST_TIMEOUT_MS } from "./config.js";
import { getToken, clearSession } from "./auth.js";
import { emit } from "./state.js";
import { runWakeLoader, holdLoader } from "./ui/loader.js";

export class ApiError extends Error {
  constructor(status, detail, data = null) {
    super(detail);
    this.name = "ApiError";
    this.status = status;   // HTTP status (0 = network error)
    this.detail = detail;   // human-readable message
    this.data = data;       // raw response body
  }
}

// ---- Mock mode --------------------------------------------------------------------
let mockModule = null;
async function callMock(method, url, body) {
  if (!mockModule) mockModule = await import("./mock.js");
  return mockModule.handle(method, url, body, getToken());
}

function buildUrl(path, query) {
  if (!query) return path;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === "") continue;
    params.set(key, value);
  }
  const qs = params.toString();
  return qs ? `${path}?${qs}` : path;
}

/** One HTTP round trip. Throws on network failure / timeout. */
async function send(method, url, body, { timeout, keepalive }) {
  if (MOCK) return callMock(method, url, body);

  const headers = { Accept: "application/json" };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const res = await fetch(API_BASE + url, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: keepalive ? undefined : controller.signal,
      keepalive, // lets "stop playback" / events finish even while the page is closing
    });
    let data = null;
    if (res.status !== 204) {
      const text = await res.text();
      if (text) {
        try { data = JSON.parse(text); } catch { data = { detail: text.slice(0, 300) }; }
      }
    }
    return { status: res.status, data };
  } finally {
    clearTimeout(timer);
  }
}

function detailOf(data, status) {
  const d = data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => x?.msg || String(x)).join("; "); // FastAPI 422 format
  if (status === 403) return "You don't have access to that.";
  if (status === 404) return "We couldn't find that.";
  if (status >= 500) return "The server hit a problem. Please try again in a moment.";
  return `Request failed (${status}).`;
}

// ---- Cold start: poll /api/health until the server answers --------------------------
let waking = null;
function wakeServer() {
  if (!waking) {
    waking = runWakeLoader(async () => {
      try {
        const res = await send("GET", "/api/health", undefined, { timeout: 20000, keepalive: false });
        return res.status === 200;
      } catch {
        return false;
      }
    }).finally(() => { waking = null; });
  }
  return waking;
}

const AUTH_PATHS = ["/api/auth/login", "/api/auth/register"];
const SLOW_MS = 4500; // after this long, show the "waking up" screen while we keep waiting

/**
 * request("POST", "/api/ratings", { body: {...} })
 * Options:
 *   query     object of query-string values (empty ones are skipped)
 *   body      JSON body
 *   wake      false = never show the wake-up screen (background calls)
 *   keepalive true = survives page unload (used on pagehide)
 *   timeout   ms before we treat the server as asleep
 */
export async function request(method, path, { query, body, wake = true, keepalive = false, timeout = REQUEST_TIMEOUT_MS } = {}) {
  const url = buildUrl(path, query);

  for (let attempt = 0; ; attempt++) {
    let res;
    const release = wake && !MOCK ? delayedHold() : null;
    try {
      res = await send(method, url, body, { timeout, keepalive });
    } catch {
      release?.();
      // Network error or timeout → the free server is probably asleep
      if (wake && attempt < 2) { await wakeServer(); continue; }
      throw new ApiError(0, "Can't reach the server. Check your connection and try again.");
    }
    release?.();

    // Render answers 502/503 while the instance is still booting
    if ([502, 503, 504].includes(res.status) && wake && attempt < 2) { await wakeServer(); continue; }

    const isAuthCall = AUTH_PATHS.includes(path);
    const lostIdentity = res.status === 401 ||
      (res.status === 400 && res.data?.detail === "User could not be identified");
    if (lostIdentity && !isAuthCall) {
      clearSession();
      emit("auth:expired");
      throw new ApiError(401, "Please sign in again.", res.data);
    }

    if (res.status >= 400) throw new ApiError(res.status, detailOf(res.data, res.status), res.data);
    return res.data;
  }
}

/** Show the wake-up screen only if a request takes longer than SLOW_MS. */
function delayedHold() {
  let release = null;
  const timer = setTimeout(() => { release = holdLoader(); }, SLOW_MS);
  return () => { clearTimeout(timer); release?.(); };
}

export const api = {
  get: (path, query, opts = {}) => request("GET", path, { ...opts, query }),
  post: (path, body, opts = {}) => request("POST", path, { ...opts, body: body ?? {} }),
  del: (path, opts = {}) => request("DELETE", path, opts),
};
