// ============================================================================
// CineMatch — pages/browse.js  (#/movies and #/series)
// The catalogue (FR-1.3 / FR-1.4): filter by genre, year range and language,
// sort, and keep scrolling to load more (GET /api/movies, 40 per page).
// Filters live in the URL query (#/movies?genre=Drama&sort=rating).
// ============================================================================

import { api } from "../api.js";
import { getMeta } from "../meta.js";
import { makeSource, markListShown } from "../tracking.js";
import { navigate } from "../router.js";
import { el, esc, debounce, formatNumber } from "../utils.js";
import { captionCard } from "../ui/card.js";
import { toastError } from "../ui/toast.js";

const PAGE_SIZE = 40;
const SORTS = [["popular", "Most popular"], ["rating", "Highest rated"], ["year", "Newest first"], ["title", "A to Z"]];

let view = null; // state for the current page instance

export async function render(main, { props, query, alive }) {
  const type = props.contentType; // "movie" | "series"
  const meta = await getMeta();
  if (!alive()) return;
  const thisYear = new Date().getFullYear();

  const node = el(`
    <div class="page">
      <header class="page-head">
        <h1 class="page-title">${type === "series" ? "Series" : "Movies"}</h1>
        <p class="page-sub" data-total>&nbsp;</p>
      </header>
      <form class="toolbar" aria-label="Filter the catalogue">
        <label class="field"><span class="field__label">Genre</span>
          <select class="select" name="genre"><option value="">All genres</option>${meta.genres.map((g) => `<option>${esc(g)}</option>`).join("")}</select></label>
        <label class="field field--narrow"><span class="field__label">From year</span>
          <input class="input" name="year_from" type="number" inputmode="numeric" min="1900" max="${thisYear}" placeholder="1900"></label>
        <label class="field field--narrow"><span class="field__label">To year</span>
          <input class="input" name="year_to" type="number" inputmode="numeric" min="1900" max="${thisYear + 1}" placeholder="${thisYear}"></label>
        <label class="field"><span class="field__label">Language</span>
          <select class="select" name="language"><option value="">Any language</option>${meta.languages.map((l) => `<option value="${esc(l.code)}">${esc(l.name)}</option>`).join("")}</select></label>
        <span class="toolbar__spacer"></span>
        <label class="field"><span class="field__label">Sort by</span>
          <select class="select" name="sort">${SORTS.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></label>
      </form>
      <div class="grid" data-grid></div>
      <div class="sentinel" aria-hidden="true"></div>
      <p class="end-note" data-end hidden></p>
    </div>`);
  main.appendChild(node);

  const form = node.querySelector("form");
  const pushFilters = () => {
    const params = new URLSearchParams();
    for (const [k, v] of new FormData(form)) if (v && !(k === "sort" && v === "popular")) params.set(k, v);
    const qs = params.toString();
    navigate(`#/${type === "series" ? "series" : "movies"}${qs ? `?${qs}` : ""}`, { replace: true });
  };
  form.addEventListener("change", pushFilters);
  form.addEventListener("input", debounce((e) => { if (e.target.type === "number") pushFilters(); }, 600));
  form.addEventListener("submit", (e) => e.preventDefault());

  view = { node, type, form, alive, page: 0, total: null, loading: false, seq: 0, observer: null };

  view.observer = new IntersectionObserver((entries) => {
    if (entries.some((e) => e.isIntersecting)) loadMore();
  }, { rootMargin: "900px 0px" });
  view.observer.observe(node.querySelector(".sentinel"));

  reset(query);
  return () => { view?.observer.disconnect(); view = null; };
}

export function update({ query }) {
  if (view) reset(query);
}

function reset(query) {
  const { form, node } = view;
  for (const name of ["genre", "year_from", "year_to", "language", "sort"]) {
    const field = form.elements[name];
    field.value = query.get(name) || (name === "sort" ? "popular" : "");
  }
  view.filters = Object.fromEntries(["genre", "year_from", "year_to", "language", "sort"].map((k) => [k, query.get(k) || ""]));
  view.page = 0;
  view.total = null;
  view.seq++;
  view.loading = false;
  view.failed = false;
  view.source = makeSource(`browse_${view.type}`);
  node.querySelector("[data-grid]").innerHTML = "";
  node.querySelector("[data-end]").hidden = true;
  loadMore();
}

async function loadMore() {
  if (!view || view.loading || view.failed) return;
  if (view.total != null && view.page * PAGE_SIZE >= view.total) return;
  const mine = view.seq;
  view.loading = true;
  const grid = view.node.querySelector("[data-grid]");
  const skeletons = Array.from({ length: view.page === 0 ? 12 : 6 }, () => el('<div aria-hidden="true"><div class="skel skel--poster"></div><div class="skel skel--line" style="margin-top:12px;width:75%"></div></div>'));
  skeletons.forEach((s) => grid.appendChild(s));
  try {
    const res = await api.get("/api/movies", { ...view.filters, sort: view.filters.sort || "popular", content_type: view.type, page: view.page + 1, page_size: PAGE_SIZE });
    if (!view || mine !== view.seq || !view.alive()) return;
    skeletons.forEach((s) => s.remove());
    view.page += 1;
    view.total = res.total ?? 0;
    view.node.querySelector("[data-total]").textContent = `${formatNumber(view.total)} ${view.type === "series" ? "series" : view.total === 1 ? "film" : "films"}`;
    (res.items || []).forEach((m) => grid.appendChild(captionCard(m, { source: view.source, showReason: false })));
    if (view.page === 1) markListShown(view.source);
    if (!view.total) {
      grid.appendChild(el(`<div class="empty" style="grid-column:1/-1"><p class="empty__title">No titles match these filters</p><p class="empty__text">Try a wider year range or another genre.</p></div>`));
    } else if (view.page * PAGE_SIZE >= view.total) {
      const end = view.node.querySelector("[data-end]");
      end.textContent = "That's everything for these filters.";
      end.hidden = view.total <= PAGE_SIZE;
    }
  } catch (err) {
    skeletons.forEach((s) => s.remove());
    if (view && mine === view.seq) { view.failed = true; toastError(err); }
  } finally {
    if (view && mine === view.seq) view.loading = false;
    if (view && mine === view.seq && !view.failed) {
      // if the sentinel is still on screen (short pages), keep loading
      requestAnimationFrame(() => {
        const s = view?.node.querySelector(".sentinel");
        if (s && s.getBoundingClientRect().top < innerHeight + 900) loadMore();
      });
    }
  }
}
