// ============================================================================
// CineMatch — ui/card.js
// Movie cards, the Netflix-style hover preview, and "Not for me" (dismiss).
//
//   posterCard(movie, opts)   poster only (carousel rows)
//   captionCard(movie, opts)  poster + title, meta, reason, member scores (grids)
//
// Hovering a card (mouse only) tints the ambient background straight away and,
// after a short pause, pops out a larger preview with quick actions.
// ============================================================================

import { api } from "../api.js";
import { emit, rememberMovies, languageName } from "../state.js";
import { artHTML } from "../posters.js";
import { paletteNow, withAlpha } from "../palette.js";
import { previewMovie, releasePreview } from "../ambient.js";
import { canHover, el, esc, formatRuntime, initials, hashString } from "../utils.js";
import { icon } from "./icons.js";
import { ratingControl } from "./rating.js";
import { toast, toastError } from "./toast.js";
import { openDetails } from "./modal.js";
import { openPlayer } from "./player.js";

const MOOD_LABEL = (t) => t.replace(/-/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function matchText(movie) {
  return typeof movie.score === "number" ? `${Math.round(Math.min(0.99, movie.score) * 100)}% match` : "";
}

/** Small meta pieces shared by preview, hero and modal. */
export function metaBits(movie, { withLanguage = false, withMatch = true } = {}) {
  const bits = [];
  const match = withMatch ? matchText(movie) : "";
  if (match) bits.push(`<span class="match">${match}</span>`);
  if (movie.year) bits.push(`<span>${movie.year}</span>`);
  if (movie.content_type === "series") bits.push(`<span>${movie.seasons ? `${movie.seasons} seasons` : "Series"}</span>`);
  else if (movie.runtime) bits.push(`<span>${formatRuntime(movie.runtime)}</span>`);
  if (movie.age_rating) bits.push(`<span class="badge">${esc(movie.age_rating)}</span>`);
  if (withLanguage && movie.language) bits.push(`<span>${esc(languageName(movie.language))}</span>`);
  return bits.join("");
}

function ariaLabel(movie) {
  return `${movie.title}${movie.year ? `, ${movie.year}` : ""}${movie.content_type === "series" ? ", series" : ""}`;
}

function wire(node, movie, source) {
  const hit = node.querySelector(".card__hit");
  // cards inside the details modal keep the modal's colours and get no pop-out
  const inOverlay = () => !!node.closest(".modal, .drawer");
  hit.addEventListener("click", () => {
    hidePreviewNow();
    openDetails(movie, source);
  });
  hit.addEventListener("focus", () => { if (!inOverlay()) previewMovie(movie, 60); });
  hit.addEventListener("blur", () => { if (!inOverlay()) releasePreview(); });
  if (canHover()) {
    hit.addEventListener("mouseenter", () => {
      if (inOverlay()) return;
      previewMovie(movie);
      schedulePreview(node, movie, source);
    });
    hit.addEventListener("mouseleave", () => {
      cancelScheduled();
      if (inOverlay()) return;
      if (previewOpenFor(movie)) {
        // close unless the pointer moves onto the pop-out (its mouseenter cancels this)
        clearTimeout(hideTimer);
        hideTimer = setTimeout(() => { hidePreviewNow(); releasePreview(); }, 160);
      } else releasePreview();
    });
  }
}

/** Poster-only card for carousel rows. opts: { source, progress (0–1) } */
export function posterCard(movie, { source = null, progress = null } = {}) {
  rememberMovies([movie]);
  const node = el(`
    <article class="card" data-mid="${movie.movie_id}">
      <button type="button" class="card__hit" aria-label="${esc(ariaLabel(movie))}">
        <div class="poster">${artHTML(movie, "poster", { alt: "" })}</div>
      </button>
      ${progress != null ? `<div class="card__progress" aria-label="${Math.round(progress * 100)}% watched"><span style="width:${Math.round(progress * 100)}%"></span></div>` : ""}
    </article>`);
  wire(node, movie, source);
  return node;
}

/** Card with caption (grids). opts: { source, showReason, showMembers } */
export function captionCard(movie, { source = null, showReason = true } = {}) {
  rememberMovies([movie]);
  const genres = (movie.genres || []).slice(0, 2).join(", ");
  const avg = movie.avg_rating != null ? `<span class="stars">★ ${Number(movie.avg_rating).toFixed(1)}</span>` : "";
  const members = movie.member_scores
    ? `<div class="member-scores" aria-label="Predicted stars per member">${Object.entries(movie.member_scores).map(([name, s]) => {
      const h = hashString(name);
      return `<span class="mscore ${s < 3 ? "mscore--low" : ""}"><span class="avatar" style="--a1:hsl(${h % 360} 65% 55%);--a2:hsl(${(h >> 8) % 360} 70% 45%)">${esc(initials(name)[0])}</span>${esc(name)} <b>${Number(s).toFixed(1)}</b></span>`;
    }).join("")}</div>`
    : "";
  const node = el(`
    <article class="card card--caption" data-mid="${movie.movie_id}">
      <button type="button" class="card__hit" aria-label="${esc(ariaLabel(movie))}">
        <div class="poster">${artHTML(movie, "poster", { alt: "" })}</div>
      </button>
      <div class="card__caption">
        <h3 class="card__title">${esc(movie.title)}</h3>
        <p class="card__meta">${movie.year ? `<span>${movie.year}</span>` : ""}${genres ? `<span>${esc(genres)}</span>` : ""}${avg}</p>
        ${showReason && movie.reason ? `<p class="reason-badge">${icon("sparkle")}<span>${esc(movie.reason)}</span></p>` : ""}
        ${members}
      </div>
    </article>`);
  wire(node, movie, source);
  return node;
}

// ---- Hover preview (one shared element) ----------------------------------------------------
let pv = null;
let pvMovie = null;
let showTimer = null;
let hideTimer = null;

function ensurePreview() {
  if (pv) return pv;
  pv = el('<div class="preview" role="dialog" aria-label="Quick preview"></div>');
  pv.addEventListener("mouseenter", () => clearTimeout(hideTimer));
  pv.addEventListener("mouseleave", () => {
    hideTimer = setTimeout(hidePreviewNow, 120);
    releasePreview();
  });
  document.getElementById("overlay-root").appendChild(pv);
  // scrolling moves the card away from the pop-out, so close it (a pending one re-checks hover)
  const hideOpen = () => { if (pv.classList.contains("is-open")) { pv.classList.remove("is-open"); pvMovie = null; } };
  addEventListener("scroll", hideOpen, { passive: true });
  addEventListener("resize", hidePreviewNow);
  return pv;
}

const previewOpenFor = (movie) => pv?.classList.contains("is-open") && pvMovie?.movie_id === movie.movie_id;

function cancelScheduled() {
  clearTimeout(showTimer);
}

function schedulePreview(node, movie, source) {
  clearTimeout(showTimer);
  clearTimeout(hideTimer);
  showTimer = setTimeout(() => showPreview(node, movie, source), 430);
}

export function hidePreviewNow() {
  clearTimeout(showTimer);
  if (!pv) return;
  pv.classList.remove("is-open");
  pvMovie = null;
}

function showPreview(cardNode, movie, source) {
  if (!cardNode.isConnected || cardNode.closest(".is-dragging")) return;
  if (!cardNode.querySelector(".card__hit").matches(":hover")) return; // pointer already moved on
  const poster = cardNode.querySelector(".poster");
  const rect = poster.getBoundingClientRect();
  if (!rect.width || rect.bottom < 0 || rect.top > innerHeight) return;
  ensurePreview();

  const p = paletteNow(movie);
  const tags = (movie.mood_tags || []).slice(0, 3).map((t) => `<span class="tag">${esc(MOOD_LABEL(t))}</span>`).join("");
  pv.innerHTML = `
    <div class="preview__art" data-act="open">
      ${artHTML(movie, "backdrop")}
      <h3 class="preview__title">${esc(movie.title)}</h3>
    </div>
    <div class="preview__body">
      <div class="preview__actions">
        <button type="button" class="icon-btn icon-btn--solid" data-act="play" aria-label="Play ${esc(movie.title)}">${icon("play")}</button>
        <span data-slot="rating"></span>
        <span class="spacer"></span>
        <button type="button" class="icon-btn" data-act="dismiss" aria-label="Not for me" title="Not for me">${icon("thumbsDown")}</button>
        <button type="button" class="icon-btn" data-act="open" aria-label="More info about ${esc(movie.title)}" title="More info">${icon("chevronDown")}</button>
      </div>
      <div class="meta-row">${metaBits(movie)}</div>
      ${tags ? `<div class="preview__tags">${tags}</div>` : ""}
      ${movie.reason ? `<p class="preview__reason">${icon("sparkle")}<span>${esc(movie.reason)}</span></p>` : ""}
    </div>`;
  pv.querySelector('[data-slot="rating"]').replaceWith(ratingControl(movie, { size: "sm", showValue: true }));
  pv.querySelectorAll('[data-act="open"]').forEach((b) => b.addEventListener("click", () => { hidePreviewNow(); openDetails(movie, source); }));
  pv.querySelector('[data-act="play"]').addEventListener("click", () => { hidePreviewNow(); openPlayer(movie, { source }); });
  pv.querySelector('[data-act="dismiss"]').addEventListener("click", () => dismissMovie(movie));

  // size + position: grows out of the card, stays inside the viewport
  const width = Math.round(Math.min(380, Math.max(300, rect.width * 1.7)));
  pv.style.setProperty("--pv-w", `${width}px`);
  pv.style.setProperty("--pv-deep", p.deep);
  pv.style.setProperty("--pv-glow", withAlpha(p.c1, 0.55));
  const height = pv.offsetHeight || width * 1.05;
  const artH = (width * 9) / 16;
  const navH = 72;
  let left = rect.left + rect.width / 2 - width / 2;
  left = Math.max(12, Math.min(innerWidth - width - 12, left));
  let top = rect.top + rect.height / 2 - artH / 2 - 10;
  top = Math.max(navH, Math.min(innerHeight - height - 12, top));
  pv.style.left = `${Math.round(left)}px`;
  pv.style.top = `${Math.round(top)}px`;
  pv.style.setProperty("--pv-ox", `${Math.round(rect.left + rect.width / 2 - left)}px`);
  pv.style.setProperty("--pv-oy", `${Math.round(rect.top + rect.height / 2 - top)}px`);
  pv.style.setProperty("--pv-from", (rect.width / width).toFixed(3));
  pv.classList.remove("is-open");
  void pv.offsetWidth; // restart the grow-in transition
  pvMovie = movie;
  pv.classList.add("is-open");
}

// ---- "Not for me" (FR-4.5) -------------------------------------------------------------
/**
 * Dismiss a film: every card for it on the page animates out, the backend
 * remembers it so it never comes back, and a toast offers Undo.
 */
export async function dismissMovie(movie) {
  hidePreviewNow();
  const id = movie.movie_id;
  const removed = Array.from(document.querySelectorAll(`#main .card[data-mid="${id}"]`)).map((card) => {
    const item = card.closest(".row__item") || card;
    return { item, parent: item.parentNode, next: item.nextSibling };
  });
  removed.forEach(({ item }) => item.classList.add("is-leaving"));
  try {
    await api.post(`/api/recommendations/${id}/dismiss`);
    setTimeout(() => removed.forEach(({ item }) => item.remove()), 500);
    emit("movie:dismissed", id);
    toast(`${movie.title} won't be recommended again.`, {
      action: {
        label: "Undo",
        onClick: async () => {
          try {
            await api.del(`/api/recommendations/${id}/dismiss`);
            removed.forEach(({ item, parent, next }) => {
              item.classList.remove("is-leaving");
              if (parent?.isConnected) parent.insertBefore(item, next && next.parentNode === parent ? next : null);
            });
            emit("movie:restored", id);
            toast(`${movie.title} is back in your picks.`, { type: "success" });
          } catch (err) { toastError(err); }
        },
      },
    });
  } catch (err) {
    removed.forEach(({ item }) => item.classList.remove("is-leaving"));
    toastError(err);
  }
}
