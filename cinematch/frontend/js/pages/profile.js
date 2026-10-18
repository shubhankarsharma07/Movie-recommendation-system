// ============================================================================
// CineMatch — pages/profile.js  (#/profile)
// Your taste in words and numbers (GET /api/profile/insights), what you were
// watching (GET /api/playback/me) and every rating you've given, editable.
// ============================================================================

import { api } from "../api.js";
import { state } from "../state.js";
import { GENRE_COLORS } from "../palette.js";
import { artHTML } from "../posters.js";
import { el, esc, initials, hashString, formatMs, formatPercent, plural } from "../utils.js";
import { icon } from "../ui/icons.js";
import { createRow } from "../ui/carousel.js";
import { ratingControl } from "../ui/rating.js";
import { openDetails } from "../ui/modal.js";
import { makeSource, markListShown } from "../tracking.js";
import { setBaseMovie, clearBaseMovie } from "../ambient.js";
import { toast, toastError } from "../ui/toast.js";

export async function render(main, { alive }) {
  const user = state.user || {};
  const h = hashString(user.display_name || user.email || "you");
  const since = user.created_at ? new Date(user.created_at).toLocaleDateString("en-IN", { month: "long", year: "numeric" }) : "";

  const node = el(`
    <div class="page">
      <header class="profile__head">
        <span class="avatar avatar--xl" style="--a1:hsl(${h % 360} 62% 56%);--a2:hsl(${(h >> 9) % 360} 70% 42%)" aria-hidden="true">${esc(initials(user.display_name || user.email))}</span>
        <div style="display:grid;gap:6px">
          <h1 class="profile__name">${esc(user.display_name || "Your profile")}</h1>
          <p class="dim small">${esc(user.email || "")}${since ? `<br>Member since ${esc(since)}` : ""}</p>
        </div>
      </header>
      <p class="taste-summary" data-summary><span class="skel skel--line" style="display:block;height:30px;width:80%"></span></p>
      <div class="profile__grid">
        <section aria-labelledby="genres-title">
          <h2 class="section-title" id="genres-title">Genres you gravitate to</h2>
          <p class="section-sub">Weighted by how highly you rate them.</p>
          <ul class="bars" data-bars style="margin-top:20px"></ul>
        </section>
        <section aria-labelledby="habits-title">
          <h2 class="section-title" id="habits-title">How you watch</h2>
          <p class="section-sub">From your playback and browsing.</p>
          <dl class="stats-list" data-stats style="margin-top:20px"></dl>
        </section>
      </div>
      <div class="section" data-continue style="margin-left:calc(-1 * var(--gutter));margin-right:calc(-1 * var(--gutter))"></div>
      <section class="section" aria-labelledby="ratings-title">
        <div class="section__head">
          <h2 class="section-title" id="ratings-title">Your ratings</h2>
          <p class="section-sub" data-rcount></p>
        </div>
        <div class="grid grid--compact" data-ratings></div>
      </section>
    </div>`);
  main.appendChild(node);

  const [insights, playback, ratings] = await Promise.allSettled([
    api.get("/api/profile/insights"),
    api.get("/api/playback/me", null, { wake: false }),
    api.get("/api/ratings/me"),
  ]);
  if (!alive()) return;

  // ---- insights ----
  if (insights.status === "fulfilled") {
    const ins = insights.value;
    node.querySelector("[data-summary]").textContent = ins.taste_summary || "Rate a few more films and we'll describe your taste here.";
    const bars = node.querySelector("[data-bars]");
    const top = (ins.top_genres || []).slice(0, 6);
    const max = Math.max(0.0001, ...top.map((g) => g.score));
    bars.innerHTML = top.length ? top.map((g) => {
      const [c1, c2] = GENRE_COLORS[g.genre] || ["#8a7cf0", "#4f6a8f"];
      return `<li class="bar"><span class="bar__label">${esc(g.genre)}</span>
        <span class="bar__track"><span class="bar__fill" style="--w:${Math.round((g.score / max) * 100)}%;--c1:${c1};--c2:${c2}"></span></span>
        <span class="bar__val">${Math.round((g.score / max) * 100)}</span></li>`;
    }).join("") : '<li class="dim small">No genre pattern yet. Rate a few films you love.</li>';

    const stats = [
      ["Finish rate", "Films you watch to the end", formatPercent(ins.completion_rate)],
      ["Time to pick", "From browsing to pressing play", formatMs(ins.avg_browse_to_select_ms)],
      ["Binge score", "How often one episode becomes three", ins.binge_score != null ? `${Math.round(ins.binge_score * 10)}/10` : "–"],
      ["Favourite decade", "Where your top ratings cluster", ins.favourite_decade ? `${ins.favourite_decade}s` : "–"],
      ["Rewatches", "Films you came back to", ins.rewatch_count ?? 0],
      ["Skipping ahead", "Sessions where you fast-forwarded", formatPercent(ins.seek_forward_rate)],
      ["Ratings", "", ins.ratings_count ?? 0],
      ["Watch sessions", "", ins.sessions_count ?? 0],
    ];
    node.querySelector("[data-stats]").innerHTML = stats.map(([k, sub, v]) => `<div><dt>${k}${sub ? `<small>${sub}</small>` : ""}</dt><dd>${esc(v)}</dd></div>`).join("");
  } else {
    node.querySelector("[data-summary]").textContent = "Your insights didn't load. Try again in a moment.";
  }

  // ---- continue watching ----
  if (playback.status === "fulfilled") {
    const seen = new Set();
    const items = [];
    const progress = new Map();
    for (const s of playback.value.items || []) {
      const id = s.movie?.movie_id;
      if (id == null || seen.has(id)) continue;
      seen.add(id);
      if (s.completed || !s.duration_sec) continue;
      const ratio = (s.drop_off_sec || 0) / s.duration_sec;
      if (ratio >= 0.9) continue;
      progress.set(id, ratio);
      items.push(s.movie);
    }
    if (items.length) {
      node.querySelector("[data-continue]").appendChild(createRow({ id: "continue_watching", title: "Continue watching", subtitle: plural(items.length, "title") + " in progress", items }, { progress }));
    }
  }

  // ---- ratings ----
  const grid = node.querySelector("[data-ratings]");
  const countEl = node.querySelector("[data-rcount]");
  if (ratings.status === "fulfilled") {
    const items = ratings.value.items || [];
    const setCount = () => { countEl.textContent = plural(grid.querySelectorAll(".card").length, "rating"); };
    const source = makeSource("my_ratings");
    if (!items.length) {
      grid.innerHTML = `<div class="empty" style="grid-column:1/-1"><p class="empty__title">No ratings yet</p><p class="empty__text">Rate films from any page and they'll show up here.</p><a class="btn btn--glass" href="#/onboarding">Rate some films</a></div>`;
    }
    items.forEach(({ movie, rating }) => {
      state.ratings.set(movie.movie_id, rating);
      const card = el(`
        <article class="card card--caption" data-mid="${movie.movie_id}">
          <button type="button" class="card__hit" aria-label="${esc(movie.title)}"><div class="poster">${artHTML(movie, "poster")}</div></button>
          <div class="card__caption">
            <h3 class="card__title">${esc(movie.title)}</h3>
            <div style="display:flex;align-items:center;justify-content:space-between;gap:6px;margin-top:4px">
              <span data-slot></span>
              <button type="button" class="icon-btn icon-btn--plain icon-btn--sm" aria-label="Remove your rating for ${esc(movie.title)}" title="Remove rating">${icon("trash")}</button>
            </div>
          </div>
        </article>`);
      card.querySelector("[data-slot]").replaceWith(ratingControl(movie, { size: "sm" }));
      card.querySelector(".card__hit").addEventListener("click", () => openDetails(movie, source));
      card.querySelector(".icon-btn").addEventListener("click", async () => {
        try {
          await api.del(`/api/ratings/${movie.movie_id}`);
          state.ratings.delete(movie.movie_id);
          if (state.user) state.user.rating_count = Math.max(0, (state.user.rating_count || 1) - 1);
          card.classList.add("is-leaving");
          setTimeout(() => { card.remove(); setCount(); }, 480);
          toast(`Removed your rating for ${movie.title}.`);
        } catch (err) { toastError(err); }
      });
      grid.appendChild(card);
    });
    if (items.length) setCount();
    markListShown(source);
    // the page glows with the colours of your highest-rated film
    const favourite = [...items].sort((a, b) => b.rating - a.rating)[0];
    if (favourite) setBaseMovie(favourite.movie);
  } else {
    toastError(ratings.reason);
  }
  return () => clearBaseMovie();
}
