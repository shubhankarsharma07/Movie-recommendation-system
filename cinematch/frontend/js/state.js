// ============================================================================
// CineMatch — state.js
// One small shared store + a tiny event bus, so modules can talk without
// importing each other in circles.
// ============================================================================

import { timeOfDayFromHour } from "./utils.js";

export const state = {
  user: null,               // { id, email, display_name, is_admin, created_at, rating_count }
  meta: null,               // GET /api/meta/filters (cached)
  context: null,            // last GET /api/context (or home.context) response
  geo: { status: "unknown", coords: null },  // status: granted | denied | unavailable | unknown
  overrides: loadOverrides(),                // user overrides for weather / time of day (FR-2.3)
  ratings: new Map(),       // movie_id -> my rating (kept in sync by the rating control)
  movies: new Map(),        // movie_id -> MovieCard we've seen (titles for chips etc.)
  lastPageHash: "#/",       // last non-overlay page (used when closing the details modal)
  pendingApply: false,      // true right after "Show my mix" → results logs filter_apply
};

// ---- Event bus ------------------------------------------------------------------
const listeners = new Map();
export function on(event, fn) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event).add(fn);
  return () => listeners.get(event)?.delete(fn);
}
export function emit(event, data) {
  listeners.get(event)?.forEach((fn) => {
    try { fn(data); } catch (err) { console.warn(`[state] listener for "${event}" failed`, err); }
  });
}

// ---- Remember every MovieCard we see (cheap lookups by id) -------------------------
export function rememberMovies(items = []) {
  for (const m of items) {
    if (m && m.movie_id != null) state.movies.set(m.movie_id, { ...(state.movies.get(m.movie_id) || {}), ...m });
  }
}

// ---- Weather / time-of-day overrides (FR-2.3) ----------------------------------------
function loadOverrides() {
  try { return JSON.parse(localStorage.getItem("cinematch_overrides")) || {}; } catch { return {}; }
}
export function setOverrides(next) {
  state.overrides = { ...next };
  try { localStorage.setItem("cinematch_overrides", JSON.stringify(state.overrides)); } catch { /* ignore */ }
  emit("context:changed", effectiveContext());
}

/** The weather / time of day the app should use right now (override > detected > clock). */
export function effectiveContext() {
  const hour = new Date().getHours();
  const detectedWeather = state.context?.weather?.id || null;
  const detectedTime = state.context?.time_of_day || timeOfDayFromHour(hour);
  return {
    weather: state.overrides.weather !== undefined ? state.overrides.weather : detectedWeather,
    time_of_day: state.overrides.time_of_day || detectedTime,
    hour,
  };
}
export const hasOverrides = () => state.overrides.weather !== undefined || !!state.overrides.time_of_day;

// ---- Fallback vocabulary (used until /api/meta/filters loads, or if it fails) ----------
export const VOCAB = {
  genres: ["Action", "Adventure", "Animation", "Children", "Comedy", "Crime", "Documentary", "Drama", "Fantasy",
    "Film-Noir", "Horror", "IMAX", "Musical", "Mystery", "Romance", "Sci-Fi", "Thriller", "War", "Western"],
  emotions: { joy: "Happy", sadness: "Sad", fear: "Tense", anger: "Angry", surprise: "Surprised", disgust: "Disturbed", neutral: "Calm" },
  weather: { sunny: "Sunny", cloudy: "Cloudy", rainy: "Rainy", stormy: "Stormy", snowy: "Snowy", foggy: "Foggy", hot: "Hot", cold: "Cold" },
  time_of_day: { morning: "Morning", afternoon: "Afternoon", evening: "Evening", night: "Night", late_night: "Late night" },
  time_available: [
    { minutes: 30, label: "30 min" }, { minutes: 60, label: "1 hr" }, { minutes: 90, label: "1½ hr" },
    { minutes: 120, label: "2 hr" }, { minutes: 150, label: "2½ hr" }, { minutes: 180, label: "3 hr+" },
    { minutes: null, label: "No limit" },
  ],
  occasions: {
    date_night: "Date night", family_night: "Family night", friends_hangout: "Friends hangout", solo_chill: "Solo chill",
    kids_time: "Kids time", late_night_thrills: "Late-night thrills", rainy_day_in: "Rainy day in", weekend_binge: "Weekend binge",
  },
  festivals: {
    diwali: "Diwali", holi: "Holi", navratri: "Navratri", eid: "Eid", christmas: "Christmas", new_year: "New Year",
    halloween: "Halloween", valentines: "Valentine's Day", raksha_bandhan: "Raksha Bandhan",
    independence_day: "Independence Day", onam: "Onam", pongal: "Pongal", thanksgiving: "Thanksgiving",
  },
  age_ratings: ["U", "UA 7+", "UA 13+", "UA 16+", "A"],
  decades: [1950, 1960, 1970, 1980, 1990, 2000, 2010, 2020],
  languages: { en: "English", hi: "Hindi", ta: "Tamil", te: "Telugu", ml: "Malayalam", kn: "Kannada", bn: "Bengali",
    ko: "Korean", ja: "Japanese", fr: "French", es: "Spanish", de: "German", it: "Italian", zh: "Chinese" },
};

/** Human label for a vocabulary value, using server labels when we have them. */
export function labelFor(kind, id) {
  if (id == null) return "";
  const meta = state.meta;
  if (meta) {
    const list = meta[kind];
    if (Array.isArray(list)) {
      const hit = list.find((x) => (typeof x === "object" ? (x.id ?? x.code) === id : x === id));
      if (hit && typeof hit === "object") return hit.label || hit.name || String(id);
    }
  }
  const fallback = VOCAB[kind];
  if (fallback && !Array.isArray(fallback) && fallback[id]) return fallback[id];
  return String(id).replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}
export const languageName = (code) => labelFor("languages", code) || (code || "").toUpperCase();
