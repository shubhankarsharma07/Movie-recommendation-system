// ============================================================================
// CineMatch — pages/onboarding.js  (#/onboarding)
// Cold start: new users rate at least 5 titles from GET /api/onboarding/movies
// so the recommender has something to work with.
// ============================================================================

import { api } from "../api.js";
import { state, on, rememberMovies } from "../state.js";
import { artHTML } from "../posters.js";
import { previewMovie, releasePreview, setBaseMovie, clearBaseMovie } from "../ambient.js";
import { navigate } from "../router.js";
import { el, esc } from "../utils.js";
import { ratingControl } from "../ui/rating.js";
import { toastError } from "../ui/toast.js";

const GOAL = 5;

export async function render(main, { alive }) {
  main.innerHTML = `
    <div class="page onb">
      <header class="onb__head">
        <span class="brand"><span class="brand__mark" aria-hidden="true"></span><span class="brand__word">CineMatch</span></span>
        <h1 class="page-title">Rate at least 5 to tune your taste</h1>
        <p class="page-sub">Rate films and series you've already seen. Half stars count. Skip anything you haven't watched.</p>
      </header>
      <ul class="onb__grid" aria-label="Titles to rate">
        ${Array.from({ length: 12 }, () => '<li class="onb-tile"><div class="skel skel--poster"></div><div class="skel skel--line" style="width:70%"></div></li>').join("")}
      </ul>
    </div>
    <div class="onb__bar">
      <div class="onb__progress">
        <p class="onb__count" aria-live="polite"></p>
        <div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="${GOAL}" aria-label="Ratings so far"><span></span></div>
      </div>
      <button type="button" class="link-btn" data-act="skip">Skip for now</button>
      <button type="button" class="btn btn--play" data-act="done" disabled>Show my recommendations</button>
    </div>`;

  const grid = main.querySelector(".onb__grid");
  const bar = main.querySelector(".onb__bar");
  const count = bar.querySelector(".onb__count");
  const progress = bar.querySelector(".progress");
  const done = bar.querySelector('[data-act="done"]');
  let items = [];

  function update() {
    const ratedHere = items.filter((m) => state.ratings.has(m.movie_id)).length;
    const total = Math.max(ratedHere, state.user?.rating_count || 0, state.ratings.size);
    const n = Math.min(GOAL, total);
    count.innerHTML = total >= GOAL
      ? `<strong>${total}</strong> rated. That's enough to get started, but more ratings make better picks.`
      : `<strong>${n}</strong> of ${GOAL} rated`;
    progress.style.setProperty("--p", `${(n / GOAL) * 100}%`);
    progress.setAttribute("aria-valuenow", String(n));
    done.disabled = total < GOAL;
    grid.querySelectorAll(".onb-tile").forEach((tile) => tile.classList.toggle("is-rated", state.ratings.has(Number(tile.dataset.mid))));
  }

  bar.querySelector('[data-act="skip"]').addEventListener("click", () => {
    try { sessionStorage.setItem("cinematch_skip_onboarding", "1"); } catch { /* ignore */ }
    navigate("#/");
  });
  done.addEventListener("click", () => navigate("#/"));

  try {
    const res = await api.get("/api/onboarding/movies");
    if (!alive()) return;
    items = res.items || [];
    rememberMovies(items);
    grid.innerHTML = "";
    items.forEach((movie) => {
      const tile = el(`
        <li class="onb-tile" data-mid="${movie.movie_id}">
          <div class="poster">${artHTML(movie, "poster")}</div>
          <div>
            <h3 class="onb-tile__title">${esc(movie.title)}</h3>
            <p class="onb-tile__year">${movie.year ? `<span>${movie.year}</span>` : ""}${movie.genres?.length ? `<span>${esc(movie.genres.slice(0, 2).join(", "))}</span>` : ""}</p>
          </div>
        </li>`);
      tile.appendChild(ratingControl(movie, { size: "md", label: `Rate ${movie.title}` }));
      tile.addEventListener("mouseenter", () => previewMovie(movie));
      tile.addEventListener("mouseleave", () => releasePreview(1800));
      tile.addEventListener("focusin", () => previewMovie(movie));
      grid.appendChild(tile);
    });
    if (items[0]) setBaseMovie(items[0]);
  } catch (err) {
    if (!alive()) return;
    grid.innerHTML = "";
    grid.appendChild(el(`<li class="empty"><p class="empty__title">We couldn't load titles to rate</p><p class="empty__text">${esc(err.detail || "")}</p></li>`));
    toastError(err);
  }

  const off = on("rating:changed", update);
  update();
  return () => { off(); clearBaseMovie(); };
}
