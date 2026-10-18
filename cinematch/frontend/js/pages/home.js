// ============================================================================
// CineMatch — pages/home.js  (#/)
// Billboard + personalised rows from GET /api/home. Every row carries a
// filter preset; "See all" opens the Mood Mixer with it.
// If the user overrides the weather / time of day (context chip), the weather
// row is rebuilt with POST /api/recommendations for the chosen context.
// ============================================================================

import { api } from "../api.js";
import { state, on, effectiveContext, hasOverrides, labelFor } from "../state.js";
import { getCoords, setContext } from "../context.js";
import { clearBaseMovie } from "../ambient.js";
import { navigate } from "../router.js";
import { el, esc, debounce } from "../utils.js";
import { renderHero, heroSkeleton } from "../ui/hero.js";
import { createRow, skeletonRow } from "../ui/carousel.js";
import { toastError } from "../ui/toast.js";

export async function render(main, { alive }) {
  const page = el('<div class="home"></div>');
  const heroSlot = heroSkeleton();
  const rowsEl = el('<div class="rows"></div>');
  [0, 1, 2].forEach(() => rowsEl.appendChild(skeletonRow()));
  page.append(heroSlot, rowsEl);
  main.appendChild(page);

  const coords = await getCoords();
  if (!alive()) return;

  let data;
  try {
    data = await api.get("/api/home", { lat: coords?.lat, lon: coords?.lon, hour: new Date().getHours() });
  } catch (err) {
    if (!alive()) return;
    if (err.status === 401) return;
    main.innerHTML = "";
    const node = el(`
      <div class="page"><div class="empty">
        <h1 class="empty__title">Your picks didn't load</h1>
        <p class="empty__text">${esc(err.detail || "Something went wrong.")} Your ratings are safe.</p>
        <button type="button" class="btn btn--glass">Try again</button>
      </div></div>`);
    node.querySelector("button").addEventListener("click", () => navigate("#/"));
    main.appendChild(node);
    toastError(err);
    return;
  }
  if (!alive()) return;

  let skipped = false;
  try { skipped = sessionStorage.getItem("cinematch_skip_onboarding") === "1"; } catch { /* ignore */ }
  if (data.needs_onboarding && !skipped) {
    navigate("#/onboarding", { replace: true });
    return;
  }
  if (data.context) setContext(data.context);

  // progress bars for "Continue watching"
  let progress = null;
  if (data.rows?.some((r) => r.id === "continue_watching")) {
    try {
      const sessions = await api.get("/api/playback/me", null, { wake: false });
      progress = new Map();
      for (const s of sessions.items || []) {
        const id = s.movie?.movie_id;
        if (id != null && !progress.has(id) && s.duration_sec) progress.set(id, Math.min(1, (s.drop_off_sec || 0) / s.duration_sec));
      }
    } catch { /* bars are optional */ }
    if (!alive()) return;
  }

  // billboard
  if (data.hero) heroSlot.replaceWith(renderHero(data.hero, { request_id: data.request_id }));
  else heroSlot.remove();

  // rows
  rowsEl.innerHTML = "";
  for (const row of data.rows || []) {
    if (!row.items?.length) continue;
    rowsEl.appendChild(createRow(row, { request_id: data.request_id, progress: row.id === "continue_watching" ? progress : null }));
  }
  if (!rowsEl.children.length) {
    rowsEl.appendChild(el(`<div class="page" style="padding-top:0"><div class="empty">
      <p class="empty__title">Nothing to show yet</p>
      <p class="empty__text">Rate a few films and your rows will appear here.</p>
      <a class="btn btn--glass" href="#/onboarding">Rate some films</a></div></div>`));
  }

  // FR-2.3: user changed the weather / time of day → rebuild the weather row
  let shownKey = `${data.context?.weather?.id || ""}|${data.context?.time_of_day || ""}`;
  async function refreshWeatherRow() {
    const eff = effectiveContext();
    const key = `${eff.weather || ""}|${eff.time_of_day}`;
    if (!eff.weather || key === shownKey) return;
    shownKey = key;
    const filter = { weather: eff.weather, time_of_day: eff.time_of_day, hour: eff.hour };
    try {
      const res = await api.post("/api/recommendations", { context: filter, limit: 16 });
      if (!alive()) return;
      const tod = labelFor("time_of_day", eff.time_of_day).toLowerCase();
      const row = {
        id: "weather",
        title: `Perfect for this ${labelFor("weather", eff.weather).toLowerCase()} ${tod}`,
        subtitle: hasOverrides() ? "Based on the weather and time you chose" : state.context?.weather?.city || "",
        filter,
        fallback: res.fallback,
        items: res.items || [],
      };
      if (row.items.length < 4) return;
      const node = createRow(row, { request_id: res.request_id });
      const existing = rowsEl.querySelector('[data-row-id="weather"]');
      if (existing) existing.replaceWith(node);
      else {
        const anchor = rowsEl.querySelector('[data-row-id="for_you"]') || rowsEl.firstElementChild;
        anchor ? anchor.after(node) : rowsEl.appendChild(node);
      }
    } catch { /* keep the old row */ }
  }
  if (hasOverrides()) refreshWeatherRow();
  const off = on("context:changed", debounce(refreshWeatherRow, 300));

  return () => {
    off();
    clearBaseMovie();
  };
}
