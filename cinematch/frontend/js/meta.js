// ============================================================================
// CineMatch — meta.js
// Loads GET /api/meta/filters once (genres, languages, vocabularies…) and
// normalises it so the UI can rely on one shape. If the call fails we fall
// back to the built-in vocabulary from CONTRACT.md (state.VOCAB).
// ============================================================================

import { api } from "./api.js";
import { state, VOCAB } from "./state.js";

let pending = null;

const toList = (value, fallbackMap) => {
  if (Array.isArray(value) && value.length) {
    return value.map((x) => (typeof x === "object" ? { ...x, id: x.id ?? x.code } : { id: x, label: fallbackMap?.[x] || String(x) }));
  }
  return Object.entries(fallbackMap || {}).map(([id, label]) => ({ id, label }));
};

function normalise(m = {}) {
  return {
    genres: m.genres?.length ? m.genres : VOCAB.genres,
    languages: (m.languages?.length ? m.languages : Object.entries(VOCAB.languages).map(([code, name]) => ({ code, name })))
      .map((l) => (typeof l === "object" ? { code: l.code, name: l.name || l.code } : { code: l, name: VOCAB.languages[l] || l })),
    age_ratings: m.age_ratings?.length ? m.age_ratings : VOCAB.age_ratings,
    decades: (m.decades?.length ? m.decades : VOCAB.decades).map(Number).sort((a, b) => a - b),
    weather: toList(m.weather, VOCAB.weather),
    time_of_day: toList(m.time_of_day, VOCAB.time_of_day).map((t) => ({ ...t, label: VOCAB.time_of_day[t.id] || t.label })),
    time_available: m.time_available?.length ? m.time_available : VOCAB.time_available,
    occasions: toList(m.occasions, VOCAB.occasions),
    festivals: toList(m.festivals, VOCAB.festivals),
    emotions: toList(m.emotions, VOCAB.emotions),
    franchises: m.franchises || [],
    directors: m.directors || [],
    actors: m.actors || [],
    content_types: m.content_types || ["any", "movie", "series"],
  };
}

/** Resolves to the normalised filter metadata (cached after the first success). */
export function getMeta() {
  if (state.meta) return Promise.resolve(state.meta);
  if (!pending) {
    pending = api.get("/api/meta/filters")
      .then((m) => (state.meta = normalise(m)))
      .catch(() => normalise({})) // don't cache the fallback, try again next time
      .finally(() => { pending = null; });
  }
  return pending;
}
