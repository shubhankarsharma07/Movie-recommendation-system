// ============================================================================
// CineMatch — ui/hero.js
// The home billboard: big art, title, meta, reason, Play / More info and a
// quick half-star rating. Its film becomes the ambient "base" colours.
// ============================================================================

import { artHTML } from "../posters.js";
import { setBaseMovie } from "../ambient.js";
import { rememberMovies } from "../state.js";
import { el, esc } from "../utils.js";
import { makeSource, markListShown } from "../tracking.js";
import { icon } from "./icons.js";
import { metaBits } from "./card.js";
import { ratingControl } from "./rating.js";
import { openDetails } from "./modal.js";
import { openPlayer } from "./player.js";

export function renderHero(movie, { request_id = null } = {}) {
  rememberMovies([movie]);
  const source = makeSource("hero", request_id);
  // long titles step down in size so the billboard never runs into the nav
  const sizeClass = movie.title.length > 42 ? "is-xlong" : movie.title.length > 24 ? "is-long" : "";

  const node = el(`
    <section class="hero" aria-labelledby="hero-title">
      <div class="hero__art">${artHTML(movie, "backdrop", { eager: true })}</div>
      <div class="hero__scrim"></div>
      <div class="hero__content">
        <h1 class="hero__title ${sizeClass}" id="hero-title">${esc(movie.title)}</h1>
        <div class="meta-row">${metaBits(movie, { withLanguage: true })}</div>
        ${movie.reason ? `<p class="hero__reason">${icon("sparkle")}<span>${esc(movie.reason)}</span></p>` : ""}
        ${movie.overview ? `<p class="hero__overview">${esc(movie.overview)}</p>` : ""}
        <div class="hero__actions">
          <button type="button" class="btn btn--play btn--lg" data-act="play">${icon("play")} Play</button>
          <button type="button" class="btn btn--glass btn--lg" data-act="info">${icon("info")} More info</button>
          <div class="hero__rate"><span class="small dim">Rate it</span><span data-slot="rating"></span></div>
        </div>
      </div>
    </section>`);

  node.querySelector('[data-slot="rating"]').replaceWith(ratingControl(movie, { size: "md" }));
  node.querySelector('[data-act="play"]').addEventListener("click", () => openPlayer(movie, { source }));
  node.querySelector('[data-act="info"]').addEventListener("click", () => openDetails(movie, source));

  markListShown(source);
  setBaseMovie(movie);
  return node;
}

export function heroSkeleton() {
  return el(`
    <div class="skel-hero" aria-hidden="true">
      <div class="skel-hero__content">
        <div class="skel skel--title"></div>
        <div class="skel skel--line" style="width:55%"></div>
        <div class="skel skel--line" style="width:85%"></div>
        <div class="skel skel--line" style="width:70%"></div>
        <div style="display:flex;gap:12px;margin-top:8px"><div class="skel" style="width:130px;height:52px;border-radius:10px"></div><div class="skel" style="width:150px;height:52px;border-radius:10px"></div></div>
      </div>
    </div>`);
}
