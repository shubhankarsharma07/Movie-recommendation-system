// ============================================================================
// CineMatch — ui/rating.js
// Half-star rating control (0.5 – 5.0, FR-1.1).
//   * mouse/touch: hover to preview, click/tap to rate (left half of a star = .5)
//   * keyboard: it's an ARIA slider — arrows change by 0.5, Home/End, Delete clears
//   * saves with POST /api/ratings; if the server rejects the value (400) we
//     show the server's message and put the old value back (FR-1.2)
// Every control for the same film stays in sync through the "rating:changed" event.
// ============================================================================

import { api } from "../api.js";
import { state, emit, on } from "../state.js";
import { el, esc, debounce } from "../utils.js";
import { toastError } from "./toast.js";

const STAR = "M12 2.6l2.95 5.98 6.6.96-4.78 4.65 1.13 6.57L12 17.66l-5.9 3.1 1.13-6.57L2.45 9.54l6.6-.96z";
const STARS_SVG = `<svg viewBox="0 0 120 24" aria-hidden="true" focusable="false">${
  [0, 1, 2, 3, 4].map((i) => `<path transform="translate(${i * 24} 0)" d="${STAR}" fill="currentColor"/>`).join("")
}</svg>`;

const fmt = (v) => (v == null ? "" : Number(v).toFixed(1).replace(".0", ""));

/**
 * ratingControl(movie, { size: "sm" | "md" | "lg", label, onSaved })
 * Returns a DOM element.
 */
export function ratingControl(movie, { size = "md", label, onSaved, showValue = true } = {}) {
  const id = movie.movie_id;
  let value = state.ratings.has(id) ? state.ratings.get(id) : movie.user_rating ?? null;

  const node = el(`
    <div class="rating rating--${size}" role="slider" tabindex="0"
         aria-label="${esc(label || `Your rating for ${movie.title}`)}"
         aria-valuemin="0.5" aria-valuemax="5">
      <span class="rating__stars">
        <span class="rating__base">${STARS_SVG}</span>
        <span class="rating__fill">${STARS_SVG}</span>
      </span>
      ${showValue ? '<span class="rating__value tabular"></span>' : ""}
      <span class="rating__error" hidden></span>
    </div>`);
  const stars = node.querySelector(".rating__stars");
  const valueEl = node.querySelector(".rating__value");
  const errorEl = node.querySelector(".rating__error");

  function render(v, preview = false) {
    node.style.setProperty("--fill", `${((v || 0) / 5) * 100}%`);
    node.classList.toggle("is-preview", preview);
    if (valueEl) valueEl.textContent = fmt(v);
    if (!preview) {
      if (value == null) {
        node.removeAttribute("aria-valuenow");
        node.setAttribute("aria-valuetext", "Not rated");
      } else {
        node.setAttribute("aria-valuenow", String(value));
        node.setAttribute("aria-valuetext", `${fmt(value)} out of 5 stars`);
      }
    }
  }

  function valueFromPointer(e) {
    const rect = stars.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    return Math.min(5, Math.max(0.5, Math.ceil(ratio * 10) / 2));
  }

  function showError(message) {
    errorEl.textContent = message;
    errorEl.hidden = !message;
  }

  async function save(next) {
    const previous = value;
    value = next;
    render(value);
    showError("");
    try {
      if (next == null) {
        await api.del(`/api/ratings/${id}`);
        state.ratings.delete(id);
      } else {
        const res = await api.post("/api/ratings", { movie_id: id, rating: next });
        state.ratings.set(id, res?.rating ?? next);
      }
      if (state.user && previous == null && next != null) state.user.rating_count = (state.user.rating_count || 0) + 1;
      node.classList.remove("is-saved");
      void node.offsetWidth; // restart the little "pop" animation
      node.classList.add("is-saved");
      emit("rating:changed", { movie_id: id, rating: next, source: node });
      onSaved?.(next);
    } catch (err) {
      value = previous;
      render(value);
      if (err.status === 400) showError(err.detail); // e.g. "Rating must be between 0.5 and 5.0 in steps of 0.5"
      toastError(err);
    }
  }
  const saveSoon = debounce(save, 550); // keyboard: wait until the user stops pressing arrows

  // pointer: preview on hover, commit on click
  stars.addEventListener("pointermove", (e) => {
    if (e.pointerType === "mouse") render(valueFromPointer(e), true);
  });
  stars.addEventListener("pointerleave", () => render(value));
  stars.addEventListener("click", (e) => {
    e.stopPropagation();
    save(valueFromPointer(e));
  });

  // keyboard
  node.addEventListener("keydown", (e) => {
    let next = value ?? 0;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") next = Math.min(5, next + 0.5);
    else if (e.key === "ArrowLeft" || e.key === "ArrowDown") next = Math.max(0.5, (next || 1) - 0.5);
    else if (e.key === "Home") next = 0.5;
    else if (e.key === "End") next = 5;
    else if ((e.key === "Delete" || e.key === "Backspace") && value != null) { e.preventDefault(); save(null); return; }
    else return;
    e.preventDefault();
    e.stopPropagation();
    value = next;
    render(value);
    saveSoon(next);
  });
  node.addEventListener("click", (e) => e.stopPropagation());

  // stay in sync with other controls for the same film
  const off = on("rating:changed", ({ movie_id, rating, source }) => {
    if (!node.isConnected) { off(); return; }
    if (movie_id === id && source !== node) { value = rating; render(value); }
  });

  render(value);
  return node;
}

/** Load my existing ratings once so every control starts with the right value. */
export async function loadMyRatings() {
  try {
    const res = await api.get("/api/ratings/me", null, { wake: false });
    state.ratings.clear();
    for (const r of res.items || []) state.ratings.set(r.movie?.movie_id ?? r.movie_id, r.rating);
  } catch { /* not critical */ }
}
