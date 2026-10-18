// ============================================================================
// CineMatch — ui/carousel.js
// A horizontal row of posters ("carousel"), like Netflix:
//   * native smooth scrolling with snap points (touch swipe works for free)
//   * arrow buttons that page through the row
//   * click-and-drag with the mouse
//   * keyboard: Left/Right arrows move between cards
//   * "See all" opens the Mood Mixer pre-filled with the row's filter preset
//   * impressions + browse-to-select timing via tracking.observeRow
// ============================================================================

import { el, esc, prefersReducedMotion } from "../utils.js";
import { icon } from "./icons.js";
import { posterCard, hidePreviewNow } from "./card.js";
import { observeRow, makeSource } from "../tracking.js";
import { openMixer } from "./mixer.js";

let rowCounter = 0;

/** Small "i" bubble used when a list is the popularity fallback (FR-4.4). */
export function fallbackTip() {
  return `<span class="info-tip" tabindex="0" aria-label="About this list">${icon("info")}
    <span class="info-tip__bubble" role="tooltip">We couldn't personalise this list yet, so these are the most popular titles that still match your filters. Rate a few more films and it will start to feel like yours.</span>
  </span>`;
}

/**
 * createRow(row, { request_id, progress })
 *   row: { id, title, subtitle, filter, items, fallback? } from GET /api/home
 *   progress: Map(movie_id -> 0..1) for "Continue watching"
 */
export function createRow(row, { request_id = null, progress = null } = {}) {
  const source = makeSource(row.id, request_id);
  const titleId = `row-title-${++rowCounter}`;
  const canSeeAll = row.id !== "continue_watching" && row.filter;

  const section = el(`
    <section class="row" data-row-id="${esc(row.id)}" aria-labelledby="${titleId}">
      <div class="row__head">
        <h2 class="row__title" id="${titleId}">${esc(row.title)}</h2>
        ${row.fallback ? fallbackTip() : ""}
        ${row.subtitle ? `<p class="row__sub">${esc(row.subtitle)}</p>` : ""}
        ${canSeeAll ? `<button type="button" class="link-btn row__all">See all</button>` : ""}
      </div>
      <div class="row__viewport">
        <button type="button" class="row__arrow row__arrow--prev" aria-label="Scroll ${esc(row.title)} left" disabled>${icon("chevronLeft")}</button>
        <ul class="row__track" role="list"></ul>
        <button type="button" class="row__arrow row__arrow--next" aria-label="Scroll ${esc(row.title)} right">${icon("chevronRight")}</button>
      </div>
    </section>`);

  const track = section.querySelector(".row__track");
  const prev = section.querySelector(".row__arrow--prev");
  const next = section.querySelector(".row__arrow--next");

  for (const movie of row.items || []) {
    const li = el('<li class="row__item"></li>');
    li.appendChild(posterCard(movie, { source, progress: progress?.get(movie.movie_id) ?? null }));
    track.appendChild(li);
  }

  if (canSeeAll) {
    section.querySelector(".row__all").addEventListener("click", () => openMixer(row.filter || {}, { fromRow: row.title }));
  }

  // ---- arrows ----
  const behavior = () => (prefersReducedMotion() ? "auto" : "smooth");
  const page = (dir) => {
    hidePreviewNow();
    track.scrollBy({ left: dir * track.clientWidth * 0.86, behavior: behavior() });
  };
  prev.addEventListener("click", () => page(-1));
  next.addEventListener("click", () => page(1));

  let ticking = false;
  const updateArrows = () => {
    ticking = false;
    const max = track.scrollWidth - track.clientWidth - 4;
    prev.disabled = track.scrollLeft <= 4;
    next.disabled = track.scrollLeft >= max;
  };
  track.addEventListener("scroll", () => {
    if (!ticking) { ticking = true; requestAnimationFrame(updateArrows); }
  }, { passive: true });
  requestAnimationFrame(updateArrows);
  new ResizeObserver(updateArrows).observe(track);

  // ---- mouse drag to scroll ----
  let startX = 0;
  let startScroll = 0;
  let dragging = false;
  let pressed = false;
  track.addEventListener("pointerdown", (e) => {
    if (e.pointerType !== "mouse" || e.button !== 0) return;
    pressed = true;
    dragging = false;
    startX = e.clientX;
    startScroll = track.scrollLeft;
  });
  track.addEventListener("pointermove", (e) => {
    if (!pressed) return;
    const dx = e.clientX - startX;
    if (!dragging && Math.abs(dx) > 6) {
      dragging = true;
      track.setPointerCapture(e.pointerId); // keep receiving moves even outside the row
      track.classList.add("is-dragging");
      hidePreviewNow();
    }
    if (dragging) track.scrollLeft = startScroll - dx;
  });
  const endDrag = () => {
    if (!pressed) return;
    pressed = false;
    if (dragging) {
      // swallow the click that follows a drag so we don't open a film by accident
      const swallow = (ev) => { ev.stopPropagation(); ev.preventDefault(); };
      track.addEventListener("click", swallow, { capture: true, once: true });
      setTimeout(() => {
        track.classList.remove("is-dragging");
        track.removeEventListener("click", swallow, { capture: true });
      }, 0);
    }
  };
  track.addEventListener("pointerup", endDrag);
  track.addEventListener("pointercancel", endDrag);
  track.addEventListener("lostpointercapture", endDrag);

  // ---- keyboard: move between cards with arrow keys ----
  track.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const current = e.target.closest(".row__item");
    if (!current || !e.target.classList.contains("card__hit")) return;
    const target = e.key === "ArrowRight" ? current.nextElementSibling : current.previousElementSibling;
    if (!target) return;
    e.preventDefault();
    const hit = target.querySelector(".card__hit");
    hit.focus({ preventScroll: true });
    target.scrollIntoView({ behavior: behavior(), block: "nearest", inline: "nearest" });
  });

  observeRow(section, source);
  return section;
}

export function skeletonRow(count = 8) {
  return el(`
    <section class="row" aria-hidden="true">
      <div class="row__head"><div class="skel skel--line" style="width:220px;height:20px"></div></div>
      <div class="row__viewport"><ul class="row__track" style="overflow:hidden">
        ${Array.from({ length: count }, () => '<li class="row__item"><div class="skel skel--poster"></div></li>').join("")}
      </ul></div>
    </section>`);
}
