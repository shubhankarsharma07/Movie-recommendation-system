// ============================================================================
// CineMatch — pages/results.js  (#/results?c=<encoded context>)
// Shows POST /api/recommendations for a Mood Mixer context: the label, the
// active filters as removable chips, and a grid of cards with reasons.
// The context lives in the URL, so results can be bookmarked and shared.
// ============================================================================

import { api } from "../api.js";
import { state, rememberMovies } from "../state.js";
import { setBaseMovie, clearBaseMovie } from "../ambient.js";
import { track, makeSource, markListShown } from "../tracking.js";
import { navigate } from "../router.js";
import { el, esc, decodeCtx, encodeCtx, countFilters, cleanContext } from "../utils.js";
import { icon } from "../ui/icons.js";
import { captionCard } from "../ui/card.js";
import { fallbackTip } from "../ui/carousel.js";
import { openMixer, describeContext, baseContext } from "../ui/mixer.js";
import { toastError } from "../ui/toast.js";

const RELAX_LABELS = {
  language: "language", max_age_rating: "age rating", content_type: "movie or series", genres: "genres",
  time_available_min: "time available", franchise_mode: "franchise", nostalgia_decade: "decade",
  directors: "directors", actors: "actors", reference_movie_ids: "reference films",
};

let page = null;
let aliveFn = () => false;
let seq = 0;

export async function render(main, { query, alive }) {
  aliveFn = alive;
  page = el(`
    <div class="page results">
      <header class="results__head">
        <div class="results__title-row"><h1 class="page-title" data-title><span class="skel skel--line" style="display:block;width:min(520px,70vw);height:52px"></span></h1></div>
        <div class="chips" data-chips aria-label="Active filters"></div>
        <p class="small dim" data-relaxed hidden></p>
        <div class="results__tools">
          <button type="button" class="btn btn--glass btn--sm" data-act="edit">${icon("sliders")} Edit mix</button>
          <button type="button" class="link-btn" data-act="clear" hidden>Clear all filters</button>
        </div>
      </header>
      <div class="grid" data-grid aria-live="polite"></div>
    </div>`);
  main.appendChild(page);
  await load(query);
  return () => { page = null; clearBaseMovie(); };
}

export function update({ query }) {
  if (page) load(query);
}

function contextFromQuery(query) {
  const c = query.get("c");
  return c ? decodeCtx(c) : baseContext();
}

function go(ctx) {
  state.pendingApply = true; // removing a filter is applying a new one
  state.lastMix = cleanContext(ctx);
  navigate(`#/results?c=${encodeCtx(cleanContext(ctx))}`, { replace: true });
}

async function load(query) {
  const mine = ++seq;
  const ctx = contextFromQuery(query);
  const grid = page.querySelector("[data-grid]");
  const title = page.querySelector("[data-title]");
  grid.innerHTML = Array.from({ length: 12 }, () => '<div><div class="skel skel--poster"></div><div class="skel skel--line" style="margin-top:12px;width:80%"></div></div>').join("");

  page.querySelector('[data-act="edit"]').onclick = () => openMixer(ctx);
  page.querySelector('[data-act="clear"]').onclick = () => go({ hour: new Date().getHours() });
  renderChips(ctx);

  // make sure "Like <film>" chips have titles
  const missing = (ctx.reference_movie_ids || []).filter((id) => !state.movies.has(id));
  if (missing.length) {
    Promise.all(missing.map((id) => api.get(`/api/movies/${id}`, null, { wake: false }).catch(() => null)))
      .then((found) => { rememberMovies(found.filter(Boolean)); if (mine === seq && page) renderChips(ctx); });
  }

  let res;
  try {
    res = await api.post("/api/recommendations", { context: { ...ctx, hour: ctx.hour ?? new Date().getHours() }, limit: 20 });
  } catch (err) {
    if (mine !== seq || !aliveFn() || err.status === 401) return;
    title.textContent = "Your mix didn't load";
    grid.innerHTML = "";
    grid.appendChild(el(`<div class="empty" style="grid-column:1/-1"><p class="empty__text">${esc(err.detail || "Something went wrong.")}</p><button type="button" class="btn btn--glass">Try again</button></div>`));
    grid.querySelector("button").addEventListener("click", () => load(query));
    toastError(err);
    return;
  }
  if (mine !== seq || !aliveFn()) return;

  const items = res.items || [];
  const relaxed = page.querySelector("[data-relaxed]");
  const loosened = (res.relaxed_filters || []).map((k) => RELAX_LABELS[k] || String(k).replace(/_/g, " "));
  relaxed.hidden = !loosened.length;
  relaxed.textContent = loosened.length ? `Nothing matched every filter, so we loosened: ${loosened.join(", ")}.` : "";
  title.innerHTML = `${esc(res.fallback ? "Trending now" : res.label || "Your mix")}${res.fallback ? ` ${fallbackTip()}` : ""}`;
  document.title = `${res.fallback ? "Trending now" : res.label || "Your mix"} | CineMatch`;

  if (state.pendingApply) {
    state.pendingApply = false;
    track("filter_apply", { request_id: res.request_id, value: countFilters(ctx) });
  }

  grid.innerHTML = "";
  if (!items.length) {
    grid.appendChild(el(`<div class="empty" style="grid-column:1/-1">
      <p class="empty__title">Nothing fits all of that</p>
      <p class="empty__text">Try removing a filter or two above.</p></div>`));
    return;
  }
  const source = makeSource(res.fallback ? "trending_fallback" : "mix", res.request_id);
  items.forEach((m) => grid.appendChild(captionCard(m, { source })));
  markListShown(source);
  setBaseMovie(items[0]);
}

function renderChips(ctx) {
  const wrap = page.querySelector("[data-chips]");
  const chips = describeContext(ctx).filter((c) => c.key !== "hour");
  page.querySelector('[data-act="clear"]').hidden = chips.length < 2;
  wrap.innerHTML = chips.length
    ? chips.map((c, i) => `<span class="chip chip--active"><span>${esc(c.label)}</span><button type="button" class="chip__x" data-i="${i}" aria-label="Remove ${esc(c.label)}">${icon("x")}</button></span>`).join("")
    : `<span class="small faint">No filters. These are your overall top picks.</span>`;
  wrap.querySelectorAll(".chip__x").forEach((b) => b.addEventListener("click", () => go(chips[Number(b.dataset.i)].remove(ctx))));
}
