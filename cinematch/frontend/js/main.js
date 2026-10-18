// ============================================================================
// CineMatch — main.js (entry point)
// Boots the app: ambient layer, film grain, session check, nav, router.
// ============================================================================

import { initAmbient } from "./ambient.js";
import { initGrain } from "./posters.js";
import { startRouter, onLayoutChange, navigate } from "./router.js";
import { renderNav, showNav } from "./ui/nav.js";
import { api } from "./api.js";
import { isLoggedIn, getCachedUser, updateUser } from "./auth.js";
import { state, on } from "./state.js";
import { loadMyRatings } from "./ui/rating.js";
import { getCoords, refreshContext } from "./context.js";
import { toast } from "./ui/toast.js";

initGrain();
initAmbient();

let sessionStarted = false;

/** Things to do once per signed-in session. */
function startSession() {
  if (sessionStarted || !state.user) return;
  sessionStarted = true;
  renderNav();
  loadMyRatings();
  // location + weather in the background; the chip updates when it arrives
  getCoords().then(() => { if (!state.context) refreshContext(); });
}

on("auth:changed", (user) => {
  if (user) startSession();
  else sessionStarted = false;
});

on("auth:expired", () => {
  toast("Your session has ended. Please sign in again.", { type: "error" });
  navigate("#/login");
});

onLayoutChange((bare) => showNav(!bare && isLoggedIn()));

async function boot() {
  if (isLoggedIn()) {
    state.user = getCachedUser();
    try {
      updateUser(await api.get("/api/auth/me")); // also wakes a sleeping server
    } catch (err) {
      if (err.status !== 401 && state.user) {
        // offline or server trouble: carry on with the cached user
      }
    }
    if (isLoggedIn()) startSession();
  }
  startRouter();
}

boot();
