// ============================================================================
// CineMatch — ui/toast.js
// Short messages at the bottom of the screen, optionally with one action
// (e.g. "Removed from your picks — Undo").
// ============================================================================

import { el, esc } from "../utils.js";
import { icon } from "./icons.js";

const MAX_TOASTS = 3;

/**
 * toast("Rating saved", { type: "success" })
 * toast("Removed", { action: { label: "Undo", onClick: () => {...} } })
 */
export function toast(message, { type = "info", action = null, duration } = {}) {
  const root = document.getElementById("toasts");
  if (!root) return;
  const iconName = type === "error" ? "alert" : type === "success" ? "check" : "info";
  const node = el(`
    <div class="toast toast--${type}" role="${type === "error" ? "alert" : "status"}">
      ${icon(iconName)}
      <p class="toast__msg">${esc(message)}</p>
      ${action ? `<button type="button" class="toast__action">${esc(action.label)}</button>` : ""}
      <button type="button" class="icon-btn icon-btn--plain icon-btn--sm" aria-label="Dismiss message">${icon("x")}</button>
    </div>`);

  let timer;
  const close = () => {
    clearTimeout(timer);
    if (!node.isConnected) return;
    node.classList.add("is-leaving");
    setTimeout(() => node.remove(), 260);
  };
  node.querySelector(".icon-btn").addEventListener("click", close);
  if (action) {
    node.querySelector(".toast__action").addEventListener("click", () => {
      close();
      action.onClick?.();
    });
  }

  root.appendChild(node);
  // keep the stack short
  while (root.children.length > MAX_TOASTS) root.firstElementChild.remove();
  timer = setTimeout(close, duration ?? (action ? 7000 : type === "error" ? 6000 : 3500));
  return close;
}

/** Show an ApiError (or any error) as a red toast. */
export function toastError(err, fallback = "Something went wrong. Please try again.") {
  if (err?.status === 401) return; // the router already sends the user to sign in
  toast(err?.detail || err?.message || fallback, { type: "error" });
}
