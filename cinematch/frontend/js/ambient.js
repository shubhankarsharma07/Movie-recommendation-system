// ============================================================================
// CineMatch — ambient.js
// Controls the fixed background layer (#ambient in index.html).
//
// The idea: the page always "glows" with the colours of the film you are
// looking at. The hero film sets the base colours; hovering or focusing a
// card shifts them; opening a film floods the screen with its palette.
// We only change CSS custom properties here — the colour fades themselves
// are CSS transitions (see css/ambient.css), so this stays cheap.
// ============================================================================

import { moviePalette, paletteNow, defaultPalette } from "./palette.js";
import { artHTML } from "./posters.js";

let root = null;
let layers = [];
let activeLayer = 0;
let baseMovie = null;     // the page's "resting" film (usually the hero)
let currentId = null;     // film whose colours are showing now
let seq = 0;              // ignores stale async palette results
let hoverTimer = null;
let releaseTimer = null;
let cycleTimer = null;

export function initAmbient() {
  root = document.getElementById("ambient");
  layers = Array.from(root.querySelectorAll(".amb-layer"));
  applyPalette(defaultPalette());
}

/** Write a palette into the CSS variables (colours fade via CSS transitions). */
export function applyPalette(p) {
  const style = document.documentElement.style;
  style.setProperty("--amb-1", p.c1);
  style.setProperty("--amb-2", p.c2);
  style.setProperty("--amb-3", p.c3);
  style.setProperty("--amb-4", p.c4);
  style.setProperty("--amb-deep", p.deep);
  style.setProperty("--accent", p.accent);
  document.querySelector('meta[name="theme-color"]')?.setAttribute("content", p.deep);
}

/** Cross-fade the blurred backdrop to this film's art. */
function setBackdrop(movie) {
  if (!layers.length) return;
  const next = layers[1 - activeLayer];
  const prev = layers[activeLayer];
  next.innerHTML = movie ? artHTML(movie, "backdrop") : "";
  requestAnimationFrame(() => {
    next.classList.add("is-on");
    prev.classList.remove("is-on");
  });
  activeLayer = 1 - activeLayer;
}

/** Show a film's colours now. */
export async function showMovie(movie) {
  if (!root || !movie) return;
  clearTimeout(releaseTimer);
  if (movie.movie_id === currentId) return;
  const token = ++seq;
  currentId = movie.movie_id;
  setBackdrop(movie);
  const hasImage = !!(movie.backdrop_url || movie.poster_url);
  if (!hasImage) {
    applyPalette(paletteNow(movie)); // generated art: palette is known instantly
    return;
  }
  const palette = await moviePalette(movie); // reads the image colours (cached after the first time)
  if (token === seq) applyPalette(palette);
}

/** The page's resting film (e.g. the home hero). */
export function setBaseMovie(movie) {
  baseMovie = movie;
  showMovie(movie);
}
export function clearBaseMovie() {
  baseMovie = null;
}

/** Hover / focus: wait a moment so sweeping the mouse across a row doesn't flicker. */
export function previewMovie(movie, delay = 140) {
  clearTimeout(hoverTimer);
  clearTimeout(releaseTimer);
  hoverTimer = setTimeout(() => showMovie(movie), delay);
}

/** Pointer left the cards: drift back to the base film after a pause. */
export function releasePreview(delay = 2600) {
  clearTimeout(hoverTimer);
  clearTimeout(releaseTimer);
  releaseTimer = setTimeout(() => {
    if (baseMovie) showMovie(baseMovie);
  }, delay);
}

/** normal | takeover (details open) | player | auth | quiet */
export function setAmbientMode(mode = "") {
  if (root) root.dataset.mode = mode;
}
export const getAmbientMode = () => root?.dataset.mode || "";

/** Slowly rotate through a list of films (used on the sign-in screen). */
export function cycleMovies(movies, every = 6500) {
  stopCycle();
  if (!movies.length) return stopCycle;
  let i = 0;
  showMovie(movies[0]);
  cycleTimer = setInterval(() => {
    i = (i + 1) % movies.length;
    showMovie(movies[i]);
  }, every);
  return stopCycle;
}
export function stopCycle() {
  clearInterval(cycleTimer);
  cycleTimer = null;
}

/** Back to neutral colours (e.g. after sign-out). */
export function resetAmbient() {
  baseMovie = null;
  currentId = null;
  seq++;
  applyPalette(defaultPalette());
  setBackdrop(null);
}
