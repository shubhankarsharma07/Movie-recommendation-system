// ============================================================================
// CineMatch — ui/modal.js
// The film details modal. It is deep-linkable: opening a film changes the URL
// to #/movie/<id>, so the link can be shared and the Back button closes it.
// While it's open, the film's palette "takes over" the ambient background.
// ============================================================================

import { api } from "../api.js";
import { state, rememberMovies, languageName } from "../state.js";
import { artHTML } from "../posters.js";
import { paletteNow, withAlpha } from "../palette.js";
import { showMovie as ambientShow, setAmbientMode, getAmbientMode, releasePreview } from "../ambient.js";
import { track, trackSelect, makeSource, markListShown } from "../tracking.js";
import { el, esc, formatNumber, trapFocus, lockScroll, unlockScroll } from "../utils.js";
import { icon } from "./icons.js";
import { captionCard, metaBits, dismissMovie } from "./card.js";
import { ratingControl } from "./rating.js";
import { arcSVG, arcCaption } from "./emotion.js";
import { openPlayer } from "./player.js";
import { openMixer } from "./mixer.js";
import { toast, toastError } from "./toast.js";

let scrim = null;
let modal = null;
let untrap = null;
let lastFocus = null;
let openedInApp = false;
let previousMode = "";
let currentId = null;
let loadSeq = 0;

export const isModalOpen = () => !!scrim;

/** Open a film's details. source = where the click came from (for browse-to-select). */
export function openDetails(movie, source = null) {
  rememberMovies([movie]);
  state.pendingSource = source;
  const target = `#/movie/${movie.movie_id}`;
  if (location.hash === target) return;
  if (isModalOpen()) {
    location.replace(target); // film → film inside the modal doesn't stack history
  } else {
    openedInApp = true;
    location.hash = target;
  }
}

/** Called by the router when the URL is #/movie/:id */
export async function showMovieModal(id) {
  id = Number(id);
  const source = state.pendingSource;
  state.pendingSource = null;
  if (!scrim) mount();
  if (currentId === id && modal.dataset.loaded === "1") return;
  currentId = id;
  modal.dataset.loaded = "0";

  const known = state.movies.get(id);
  if (known) render(known, { partial: true });
  else renderLoading();
  scrim.scrollTop = 0;

  track("details_open", { movie_id: id, request_id: source?.request_id, row_id: source?.row_id });
  trackSelect(source, id);

  const seq = ++loadSeq;
  try {
    const movie = await api.get(`/api/movies/${id}`);
    if (seq !== loadSeq || !scrim) return;
    // keep the list's reason / score if the details endpoint doesn't send them
    const merged = { ...(known || {}), ...movie, reason: movie.reason || known?.reason, score: movie.score ?? known?.score };
    rememberMovies([merged]);
    if (movie.user_rating != null) state.ratings.set(id, movie.user_rating);
    render(merged, { source });
    modal.dataset.loaded = "1";
  } catch (err) {
    if (seq !== loadSeq || !scrim) return;
    if (err.status === 404) renderNotFound();
    else { toastError(err); if (!known) renderNotFound(err.detail); }
  }
}

function mount() {
  lastFocus = document.activeElement;
  previousMode = getAmbientMode();
  scrim = el(`
    <div class="modal-scrim">
      <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" tabindex="-1"></div>
    </div>`);
  modal = scrim.querySelector(".modal");
  scrim.addEventListener("click", (e) => { if (e.target === scrim) closeModal(); });
  scrim.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); closeModal(); } });
  document.getElementById("overlay-root").appendChild(scrim);
  lockScroll();
  untrap = trapFocus(scrim);
  setAmbientMode("takeover");
  requestAnimationFrame(() => {
    scrim.classList.add("is-open");
    modal.focus({ preventScroll: true });
  });
}

/**
 * Close the modal.
 *  fromRouter = true when the URL already changed (Back button / navigation),
 *  otherwise we update the URL ourselves.
 */
export function closeModal({ fromRouter = false } = {}) {
  if (!scrim) return;
  const node = scrim;
  scrim = null;
  modal = null;
  currentId = null;
  loadSeq++;
  untrap?.();
  node.classList.remove("is-open");
  setTimeout(() => node.remove(), 320);
  unlockScroll();
  setAmbientMode(previousMode);
  releasePreview(0);
  if (lastFocus?.isConnected) lastFocus.focus({ preventScroll: true });

  if (!fromRouter) {
    if (openedInApp) history.back();
    else location.replace(state.lastPageHash || "#/");
  }
  openedInApp = false;
}

function renderLoading() {
  modal.innerHTML = `
    <button type="button" class="icon-btn modal__close" aria-label="Close details">${icon("x")}</button>
    <div class="modal__art skel" style="border-radius:0"></div>
    <div class="modal__body"><div class="modal__main">
      <div class="skel skel--title" style="width:60%"></div>
      <div class="skel skel--line" style="width:90%"></div><div class="skel skel--line" style="width:75%"></div>
    </div></div>`;
  modal.querySelector(".modal__close").addEventListener("click", () => closeModal());
}

function renderNotFound(message) {
  modal.innerHTML = `
    <button type="button" class="icon-btn modal__close" aria-label="Close details">${icon("x")}</button>
    <div class="empty">
      <h2 class="empty__title" id="modal-title">We couldn't find that title</h2>
      <p class="empty__text">${esc(message || "It may have been removed from the catalogue. Try searching for it instead.")}</p>
      <button type="button" class="btn btn--glass" data-close>Back to browsing</button>
    </div>`;
  modal.querySelectorAll(".modal__close, [data-close]").forEach((b) => b.addEventListener("click", () => closeModal()));
}

function scoreRing(score) {
  const r = 26;
  const c = 2 * Math.PI * r;
  const v = Math.max(0, Math.min(100, score));
  return `<svg class="score__ring" viewBox="0 0 64 64" aria-hidden="true">
      <circle cx="32" cy="32" r="${r}" fill="none" stroke="rgba(244,239,232,.12)" stroke-width="5"/>
      <circle cx="32" cy="32" r="${r}" fill="none" stroke="var(--m-accent)" stroke-width="5" stroke-linecap="round"
              stroke-dasharray="${((c * v) / 100).toFixed(1)} ${c.toFixed(1)}" transform="rotate(-90 32 32)"/>
      <text x="32" y="37.5" text-anchor="middle" font-size="17" font-weight="700" fill="#f4efe8" font-family="Hanken Grotesk, sans-serif">${Math.round(v)}</text>
    </svg>`;
}

function people(list, role) {
  return (list || []).map((name) =>
    `<button type="button" class="person-link" data-person="${esc(name)}" data-role="${role}" title="Find more ${role === "director" ? "by" : "with"} ${esc(name)}">${esc(name)}</button>`
  ).join(", ");
}

function render(movie, { partial = false, source = null } = {}) {
  const p = paletteNow(movie);
  modal.style.setProperty("--m-deep", p.deep);
  modal.style.setProperty("--m-accent", p.accent);
  modal.style.setProperty("--m-glow", withAlpha(p.c1, 0.6));
  ambientShow(movie);

  const longTitle = movie.title.length > 30;
  const isSeries = movie.content_type === "series";
  const dismissed = !!movie.dismissed;
  const tags = (movie.mood_tags || []).map((t) => `<span class="tag">${esc(t.replace(/-/g, " ").replace(/^\w/, (c) => c.toUpperCase()))}</span>`).join("");
  const facts = [
    movie.directors?.length ? [isSeries ? "Created by" : (movie.directors.length > 1 ? "Directors" : "Director"), people(movie.directors, "director")] : null,
    movie.cast?.length ? ["Cast", people(movie.cast, "actor")] : null,
    movie.genres?.length ? ["Genres", esc(movie.genres.join(", "))] : null,
    movie.collection_name ? ["Franchise", esc(movie.collection_name)] : null,
    movie.language ? ["Language", esc(languageName(movie.language))] : null,
  ].filter(Boolean);

  modal.innerHTML = `
    <button type="button" class="icon-btn modal__close" aria-label="Close details">${icon("x")}</button>
    <div class="modal__art">
      ${artHTML(movie, "backdrop", { eager: true })}
      <div class="modal__hero">
        <h2 class="modal__title ${longTitle ? "is-long" : ""}" id="modal-title">${esc(movie.title)}</h2>
        <div class="modal__actions">
          <button type="button" class="btn btn--play btn--lg" data-act="play">${icon("play")} ${isSeries ? "Play episode 1" : "Play"}</button>
          ${movie.trailer_key ? `<button type="button" class="btn btn--glass btn--lg" data-act="trailer">${icon("trailer")} Trailer</button>` : ""}
          <button type="button" class="icon-btn" data-act="dismiss" aria-pressed="${dismissed}" aria-label="${dismissed ? "Hidden from your picks. Show it again" : "Not for me"}" title="${dismissed ? "Hidden from your picks. Click to undo" : "Not for me"}">${icon("thumbsDown")}</button>
        </div>
      </div>
    </div>
    <div class="modal__body">
      <div class="modal__main">
        <div class="meta-row">${metaBits(movie, { withLanguage: false })}</div>
        ${movie.reason ? `<p class="hero__reason">${icon("sparkle")}<span>${esc(movie.reason)}</span></p>` : ""}
        ${movie.overview ? `<p class="modal__overview">${esc(movie.overview)}</p>` : ""}
        <div class="modal__rate">
          <span class="modal__rate-label">Your rating</span>
          <span data-slot="rating"></span>
          <span class="hint">Half stars count. Use the arrow keys too.</span>
        </div>
        ${movie.start_emotion || movie.end_emotion ? `
          <figure class="arc-figure">
            <figcaption class="small dim">Emotional journey</figcaption>
            <div class="emo-arc">${arcSVG(movie.start_emotion, movie.end_emotion, movie.emotion_arc, { id: `m${movie.movie_id}` })}
              <p class="emo-arc__caption">${esc(arcCaption(movie.start_emotion, movie.end_emotion))}</p></div>
          </figure>` : ""}
        ${tags ? `<div class="preview__tags" aria-label="Mood">${tags}</div>` : ""}
      </div>
      <aside class="modal__side" aria-label="Details">
        <div class="scores">
          ${movie.critic_score != null ? `<div class="score">${scoreRing(movie.critic_score)}<div><div class="score__value">Critics</div><div class="score__label">Unified critic score<br>out of 100</div></div></div>` : ""}
          ${movie.avg_rating != null ? `<div class="score"><div><div class="score__value" style="color:var(--gold)">★ ${Number(movie.avg_rating).toFixed(1)}</div><div class="score__label">Average from<br>${formatNumber(movie.rating_count || 0)} ratings</div></div></div>` : ""}
          ${movie.imdb_rating ? `<div class="score"><div><div class="score__value">${Number(movie.imdb_rating).toFixed(1)}</div><div class="score__label">IMDb</div></div></div>` : ""}
        </div>
        <dl class="facts">${facts.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("")}</dl>
      </aside>
    </div>
    ${partial ? `<section class="modal__section"><div class="skel skel--line" style="width:160px;height:18px"></div></section>` : ""}
    ${!partial && movie.similar?.length ? `
      <section class="modal__section" aria-labelledby="similar-title">
        <h3 class="section-title" id="similar-title">More like this</h3>
        <div class="grid grid--compact" data-slot="similar"></div>
      </section>` : ""}`;

  modal.querySelector('[data-slot="rating"]').replaceWith(ratingControl(movie, { size: "lg" }));
  modal.querySelector(".modal__close").addEventListener("click", () => closeModal());
  modal.querySelector('[data-act="play"]').addEventListener("click", () => openPlayer(movie, { source }));
  modal.querySelector('[data-act="trailer"]')?.addEventListener("click", () => {
    track("trailer_open", { movie_id: movie.movie_id, request_id: source?.request_id, row_id: source?.row_id });
    openPlayer(movie, { source, mode: "trailer" });
  });

  const dismissBtn = modal.querySelector('[data-act="dismiss"]');
  dismissBtn.addEventListener("click", async () => {
    if (dismissBtn.getAttribute("aria-pressed") === "true") {
      try {
        await api.del(`/api/recommendations/${movie.movie_id}/dismiss`);
        dismissBtn.setAttribute("aria-pressed", "false");
        dismissBtn.setAttribute("aria-label", "Not for me");
        dismissBtn.title = "Not for me";
        toast(`${movie.title} can be recommended again.`, { type: "success" });
      } catch (err) { toastError(err); }
      return;
    }
    await dismissMovie(movie);
    dismissBtn.setAttribute("aria-pressed", "true");
    dismissBtn.setAttribute("aria-label", "Hidden from your picks. Show it again");
    dismissBtn.title = "Hidden from your picks. Click to undo";
  });

  modal.querySelectorAll("[data-person]").forEach((btn) => btn.addEventListener("click", () => {
    const name = btn.dataset.person;
    const preset = btn.dataset.role === "director" ? { directors: [name] } : { actors: [name] };
    closeModal();
    setTimeout(() => openMixer(preset, { fromRow: name }), 60);
  }));

  const grid = modal.querySelector('[data-slot="similar"]');
  if (grid) {
    const simSource = makeSource("similar", source?.request_id || null);
    movie.similar.slice(0, 12).forEach((m) => grid.appendChild(captionCard(m, { source: simSource, showReason: false })));
    markListShown(simSource);
  }
}
