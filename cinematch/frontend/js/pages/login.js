// ============================================================================
// CineMatch — pages/login.js  (#/login and #/register)
// Sign in / create account over a slowly drifting mosaic of generated posters.
// The JWT is stored by auth.js; passwords are only ever sent to the backend.
// ============================================================================

import { api } from "../api.js";
import { setSession } from "../auth.js";
import { MOCK } from "../config.js";
import { state } from "../state.js";
import { artHTML } from "../posters.js";
import { cycleMovies, stopCycle, setAmbientMode } from "../ambient.js";
import { navigate } from "../router.js";
import { prefersReducedMotion } from "../utils.js";

// A built-in shelf of classics for the mosaic (no API call needed before sign-in).
const SHELF = [
  ["Casablanca", 1942, "Romance|Drama", "romantic|melancholic", "sadness"], ["Vertigo", 1958, "Mystery|Thriller", "mind-bending|dark", "fear"],
  ["Seven Samurai", 1954, "Action|Drama", "epic", "sadness"], ["Sholay", 1975, "Action|Adventure", "epic|action-packed", "joy"],
  ["Pather Panchali", 1955, "Drama", "melancholic|slow-burn", "sadness"], ["Mughal-E-Azam", 1960, "Romance|Drama|Musical", "romantic|epic", "sadness"],
  ["2001: A Space Odyssey", 1968, "Sci-Fi", "mind-bending|slow-burn", "surprise"], ["Psycho", 1960, "Horror|Thriller", "scary|dark", "fear"],
  ["Rashomon", 1950, "Crime|Mystery", "mind-bending", "neutral"], ["Singin' in the Rain", 1952, "Comedy|Musical|Romance", "feel-good|funny", "joy"],
  ["Jaws", 1975, "Thriller|Adventure", "thrilling|scary", "joy"], ["Alien", 1979, "Horror|Sci-Fi", "scary|dark", "fear"],
  ["My Neighbor Totoro", 1988, "Animation|Children|Fantasy", "cozy|family", "joy"], ["Amadeus", 1984, "Drama|Musical", "epic|melancholic", "sadness"],
  ["Blade Runner", 1982, "Sci-Fi|Thriller", "mind-bending|dark", "sadness"], ["Do the Right Thing", 1989, "Drama|Comedy", "thrilling", "anger"],
  ["Goodfellas", 1990, "Crime|Drama", "dark|thrilling", "fear"], ["Fargo", 1996, "Crime|Thriller|Comedy", "dark|funny", "neutral"],
  ["Chungking Express", 1994, "Romance|Drama", "romantic|light", "joy"], ["In the Mood for Love", 2000, "Romance|Drama", "romantic|melancholic", "sadness"],
  ["City of God", 2002, "Crime|Drama", "dark|thrilling", "surprise"], ["Moonlight", 2016, "Drama", "melancholic|heartwarming", "joy"],
  ["Roma", 2018, "Drama", "slow-burn|melancholic", "joy"], ["Gully Boy", 2019, "Drama|Musical", "inspiring", "joy"],
  ["Drishyam", 2013, "Crime|Thriller", "thrilling|mind-bending", "surprise"], ["The Lunchbox", 2013, "Romance|Drama", "cozy|romantic", "joy"],
  ["Swades", 2004, "Drama", "inspiring|heartwarming", "joy"], ["Rang De Basanti", 2006, "Drama", "inspiring|epic", "sadness"],
  ["Amores Perros", 2000, "Drama|Thriller", "dark", "sadness"], ["Spirited Away", 2001, "Animation|Fantasy", "family|epic", "joy"],
  ["Coco", 2017, "Animation|Musical", "heartwarming|family", "joy"], ["Mad Max", 1979, "Action|Sci-Fi", "action-packed", "anger"],
  ["Life of Pi", 2012, "Adventure|Drama", "inspiring|epic", "surprise"], ["Lagaan", 2001, "Drama|Musical", "inspiring|epic", "joy"],
  ["Her", 2013, "Romance|Sci-Fi", "romantic|melancholic", "sadness"], ["The Good, the Bad and the Ugly", 1966, "Western", "epic", "surprise"],
].map(([title, year, genres, moods, end], i) => ({
  movie_id: 900000 + i, title, year, genres: genres.split("|"), mood_tags: moods.split("|"),
  start_emotion: "neutral", end_emotion: end, content_type: "movie", poster_url: null, backdrop_url: null,
}));

function mosaicHTML() {
  const cols = 7;
  const perCol = 5;
  let html = "";
  for (let c = 0; c < cols; c++) {
    const items = Array.from({ length: perCol }, (_, i) => SHELF[(c * perCol + i * 3 + c) % SHELF.length]);
    const posters = items.map((m) => `<div class="poster">${artHTML(m, "poster")}</div>`).join("");
    // the column is rendered twice so the upward drift can loop seamlessly
    html += `<div class="mosaic__col" style="--speed:${70 + ((c * 17) % 40)}s">${posters}${posters}</div>`;
  }
  return html;
}

export async function render(main, { props }) {
  let mode = props.mode; // "login" | "register"
  setAmbientMode("auth");

  main.innerHTML = `
    <div class="auth">
      <div class="mosaic" aria-hidden="true"><div class="mosaic__tilt">${mosaicHTML()}</div></div>
      <div class="auth__scrim"></div>
      <div class="auth__wrap">
        <div class="auth__intro">
          <span class="brand brand--lg"><span class="brand__mark" aria-hidden="true"></span><span class="brand__word">CineMatch</span></span>
          <h1 class="auth__headline">Films that fit the evening you're having.</h1>
          <p class="auth__lede">Rate what you've seen, tell us the weather, the company and the mood, and we'll find tonight's film.</p>
        </div>
        <div class="auth__panel">
          <div class="seg" role="tablist" aria-label="Sign in or create an account" style="width:100%;margin-bottom:22px">
            <button type="button" class="seg__opt" role="tab" data-mode="login" style="flex:1">Sign in</button>
            <button type="button" class="seg__opt" role="tab" data-mode="register" style="flex:1">Create account</button>
          </div>
          <form class="auth__form" novalidate style="display:grid;gap:16px">
            <div class="field" data-only="register">
              <label class="field__label" for="auth-name">Your name</label>
              <input class="input" id="auth-name" name="display_name" autocomplete="nickname" maxlength="60">
            </div>
            <div class="field">
              <label class="field__label" for="auth-email">Email</label>
              <input class="input" id="auth-email" name="email" type="email" autocomplete="email" inputmode="email" required>
            </div>
            <div class="field">
              <label class="field__label" for="auth-password">Password</label>
              <input class="input" id="auth-password" name="password" type="password" required minlength="6">
              <span class="hint" data-only="register">At least 6 characters.</span>
            </div>
            <p class="form-error" role="alert"></p>
            <button type="submit" class="btn btn--play btn--lg btn--block"></button>
            ${MOCK ? `<p class="hint" style="text-align:center">Demo mode. Sign in as <strong>demo@cinematch.app</strong> with <strong>demo1234</strong>, or create an account.</p>` : ""}
          </form>
        </div>
      </div>
    </div>`;

  const form = main.querySelector(".auth__form");
  const errorEl = form.querySelector(".form-error");
  const submit = form.querySelector('button[type="submit"]');
  const tabs = main.querySelectorAll("[data-mode]");

  function applyMode() {
    tabs.forEach((t) => {
      t.setAttribute("aria-checked", String(t.dataset.mode === mode));
      t.setAttribute("aria-selected", String(t.dataset.mode === mode));
    });
    form.querySelectorAll('[data-only="register"]').forEach((n) => { n.hidden = mode !== "register"; });
    form.querySelector("#auth-password").autocomplete = mode === "register" ? "new-password" : "current-password";
    submit.textContent = mode === "register" ? "Create account" : "Sign in";
    errorEl.textContent = "";
  }
  tabs.forEach((t) => t.addEventListener("click", () => {
    mode = t.dataset.mode;
    history.replaceState(null, "", `#/${mode}`); // swap the URL without re-rendering the page
    applyMode();
  }));
  applyMode();

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form));
    const email = String(data.email || "").trim();
    const password = String(data.password || "");
    if (mode === "register" && !String(data.display_name || "").trim()) return showError("Tell us your name so we know what to call you.", "#auth-name");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return showError("Enter a valid email address, like you@example.com.", "#auth-email");
    if (password.length < 6) return showError("Your password needs at least 6 characters.", "#auth-password");

    submit.disabled = true;
    submit.textContent = mode === "register" ? "Creating your account…" : "Signing in…";
    errorEl.textContent = "";
    try {
      const res = mode === "register"
        ? await api.post("/api/auth/register", { email, password, display_name: String(data.display_name).trim() })
        : await api.post("/api/auth/login", { email, password });
      setSession(res);
      const next = state.afterLogin;
      state.afterLogin = null;
      navigate(mode === "register" || (res.user?.rating_count ?? 5) < 5 ? "#/onboarding" : next || "#/");
    } catch (err) {
      submit.disabled = false;
      applyMode();
      if (err.status === 401) showError("That email and password don't match. Check them and try again.", "#auth-password");
      else showError(err.detail || "Couldn't reach CineMatch. Try again in a moment.");
    }
  });

  function showError(message, focusSel) {
    errorEl.textContent = message;
    if (focusSel) form.querySelector(focusSel)?.focus();
  }

  // gently cycle the background through a few of the mosaic's palettes
  const stop = prefersReducedMotion() ? (cycleMovies([SHELF[3]], 999999), stopCycle) : cycleMovies([SHELF[3], SHELF[6], SHELF[9], SHELF[12], SHELF[18], SHELF[23]], 7000);

  // start waking the (possibly sleeping) server while the user types
  api.get("/api/health", null, { wake: false, timeout: 60000 }).catch(() => {});

  setTimeout(() => form.querySelector(mode === "register" ? "#auth-name" : "#auth-email")?.focus({ preventScroll: true }), 50);

  return () => {
    stop();
    setAmbientMode("");
  };
}

