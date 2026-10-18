// ============================================================================
// CineMatch — ui/loader.js
// The full-screen "Waking up the server…" state.
// The backend runs on Render's free plan, which sleeps after 15 minutes of
// no traffic and takes ~30–60 s to boot. Instead of an error we show this,
// poll /api/health with a growing delay (back-off), then carry on.
// ============================================================================

import { el } from "../utils.js";

let root = null;
let holds = 0;          // requests that are merely "slow" (show the screen while they finish)
let polling = false;    // true while we are actively polling /api/health
let wakeEarly = null;   // resolves the current wait when "Try now" is pressed

const REEL = `
  <svg viewBox="0 0 120 120" aria-hidden="true">
    <circle cx="60" cy="60" r="54" fill="none" stroke="currentColor" stroke-opacity=".9" stroke-width="2"/>
    <circle cx="60" cy="60" r="9" fill="none" stroke="currentColor" stroke-width="2"/>
    <circle cx="60" cy="27" r="13" fill="none" stroke="currentColor" stroke-opacity=".75" stroke-width="2"/>
    <circle cx="60" cy="93" r="13" fill="none" stroke="currentColor" stroke-opacity=".75" stroke-width="2"/>
    <circle cx="27" cy="60" r="13" fill="none" stroke="currentColor" stroke-opacity=".75" stroke-width="2"/>
    <circle cx="93" cy="60" r="13" fill="none" stroke="currentColor" stroke-opacity=".75" stroke-width="2"/>
    <circle cx="60" cy="60" r="54" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-dasharray="40 300" stroke-linecap="round"/>
  </svg>`;

function ensure() {
  if (root) return root;
  root = el(`
    <div class="wake" role="alertdialog" aria-modal="true" aria-labelledby="wake-title" aria-describedby="wake-text" hidden>
      <div class="wake__inner">
        <div class="wake__reel">${REEL}</div>
        <h2 class="wake__title" id="wake-title">Waking up the server…</h2>
        <p class="wake__text" id="wake-text">Free hosting sleeps after 15 minutes without visitors. It usually takes under a minute to start again, and you'll go straight back to where you were.</p>
        <p class="wake__status" aria-live="polite"></p>
        <div class="wake__actions"><button type="button" class="btn btn--glass btn--sm" data-try>Try now</button></div>
      </div>
    </div>`);
  root.querySelector("[data-try]").addEventListener("click", () => wakeEarly?.());
  document.body.appendChild(root);
  return root;
}

function show() {
  ensure();
  if (!root.hidden) return;
  root.hidden = false;
  requestAnimationFrame(() => root.classList.add("is-open"));
}

function hide() {
  if (!root || root.hidden) return;
  root.classList.remove("is-open");
  setTimeout(() => { if (!holds && !polling) root.hidden = true; }, 420);
}

function setStatus(text) {
  ensure().querySelector(".wake__status").textContent = text;
}

/** Show the screen while a slow request is still in flight. Returns release(). */
export function holdLoader() {
  holds++;
  show();
  if (!polling) setStatus("Connecting…");
  let released = false;
  return () => {
    if (released) return;
    released = true;
    holds = Math.max(0, holds - 1);
    if (!holds && !polling) hide();
  };
}

/** Wait `ms`, counting down in the status line; "Try now" cuts the wait short. */
function waitWithCountdown(ms, checks) {
  return new Promise((resolve) => {
    const end = Date.now() + ms;
    const tick = () => {
      const left = Math.max(0, Math.ceil((end - Date.now()) / 1000));
      setStatus(`Checked ${checks} ${checks === 1 ? "time" : "times"}. Next check in ${left} s.`);
    };
    tick();
    const interval = setInterval(tick, 500);
    const timer = setTimeout(done, ms);
    function done() { clearInterval(interval); clearTimeout(timer); wakeEarly = null; resolve(); }
    wakeEarly = done;
  });
}

/**
 * Poll the backend until it answers. Never gives up on its own — the user can
 * keep waiting or press "Try now". Resolves once checkHealth() returns true.
 */
export async function runWakeLoader(checkHealth) {
  polling = true;
  show();
  const delays = [1500, 2500, 4000, 6000, 8000, 10000];
  let checks = 0;
  try {
    for (;;) {
      setStatus("Checking…");
      checks++;
      if (await checkHealth()) {
        setStatus("Connected.");
        return true;
      }
      await waitWithCountdown(delays[Math.min(checks - 1, delays.length - 1)], checks);
    }
  } finally {
    polling = false;
    if (!holds) hide();
  }
}
