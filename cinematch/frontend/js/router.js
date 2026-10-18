// ============================================================================
// CineMatch — router.js
// Hash routing (#/movies, #/movie/123 …) so the site works on any static host
// with no server-side rewrites. Each page lives in js/pages/<name>.js and
// exports render(main, ctx) → optional cleanup function, and optionally
// update(ctx) for query-string changes on the same page (search, filters).
// #/movie/:id is an overlay: the details modal opens over the current page.
// ============================================================================

import { isLoggedIn } from "./auth.js";
import { state, emit } from "./state.js";
import { showMovieModal, closeModal, isModalOpen } from "./ui/modal.js";
import { hidePreviewNow } from "./ui/card.js";
import { closeMixer } from "./ui/mixer.js";
import { el, esc } from "./utils.js";

const ROUTES = [
  { name: "home", pattern: /^$/, load: () => import("./pages/home.js") },
  { name: "movies", pattern: /^movies$/, load: () => import("./pages/browse.js"), props: { contentType: "movie" } },
  { name: "series", pattern: /^series$/, load: () => import("./pages/browse.js"), props: { contentType: "series" } },
  { name: "search", pattern: /^search$/, load: () => import("./pages/search.js") },
  { name: "results", pattern: /^results$/, load: () => import("./pages/results.js") },
  { name: "party", pattern: /^party$/, load: () => import("./pages/party.js") },
  { name: "party-room", pattern: /^party\/([A-Za-z0-9]+)$/, keys: ["code"], load: () => import("./pages/party.js") },
  { name: "profile", pattern: /^profile$/, load: () => import("./pages/profile.js") },
  { name: "admin", pattern: /^admin$/, load: () => import("./pages/admin.js"), admin: true },
  { name: "login", pattern: /^login$/, load: () => import("./pages/login.js"), public: true, bare: true, props: { mode: "login" } },
  { name: "register", pattern: /^register$/, load: () => import("./pages/login.js"), public: true, bare: true, props: { mode: "register" } },
  { name: "onboarding", pattern: /^onboarding$/, load: () => import("./pages/onboarding.js"), bare: true },
  { name: "movie", pattern: /^movie\/(\d+)$/, keys: ["id"], overlay: true },
];

let current = null;     // { key, route, module, params, query, cleanup }
let renderSeq = 0;
let layoutListener = () => {};

/** main.js uses this to hide the nav on "bare" pages (sign-in, onboarding). */
export function onLayoutChange(fn) { layoutListener = fn; }

export const currentRoute = () => (current ? { name: current.route.name, params: current.params, query: current.query } : null);

function parse() {
  const raw = location.hash.replace(/^#\/?/, "");
  const [path, qs = ""] = raw.split("?");
  return { path: decodeURIComponent(path).replace(/\/$/, ""), query: new URLSearchParams(qs) };
}

function match(path) {
  for (const route of ROUTES) {
    const m = path.match(route.pattern);
    if (m) {
      const params = {};
      (route.keys || []).forEach((k, i) => { params[k] = m[i + 1]; });
      return { route, params };
    }
  }
  return null;
}

async function handle() {
  const { path, query } = parse();
  const found = match(path);
  if (!found) { location.replace("#/"); return; }
  const { route, params } = found;

  if (!route.public && !isLoggedIn()) {
    if (route.name !== "home") state.afterLogin = location.hash;
    location.replace("#/login");
    return;
  }
  if (route.public && isLoggedIn()) { location.replace("#/"); return; }
  if (route.admin && !state.user?.is_admin) { location.replace("#/"); return; }

  hidePreviewNow();

  // Details modal opens on top of whatever page is showing (home for deep links)
  if (route.overlay) {
    if (!current) await render(ROUTES[0], {}, new URLSearchParams(), "home{}");
    showMovieModal(params.id);
    return;
  }
  if (isModalOpen()) closeModal({ fromRouter: true });
  closeMixer();
  state.lastPageHash = location.hash || "#/";

  const key = route.name + JSON.stringify(params);
  if (current && current.key === key) {
    current.query = query;
    if (current.module.update) current.module.update({ params, query, props: route.props || {} });
    emit("route", currentRoute());
    return;
  }
  await render(route, params, query, key);
}

async function render(route, params, query, key) {
  const token = ++renderSeq;
  const main = document.getElementById("main");
  try { current?.cleanup?.(); } catch (err) { console.warn("[router] cleanup failed", err); }
  current = null;
  layoutListener(!!route.bare);
  document.body.dataset.page = route.name;

  let module;
  try {
    module = await route.load();
  } catch (err) {
    console.error(err);
    main.replaceChildren(errorView("This page didn't load. Check your connection and try again."));
    return;
  }
  if (token !== renderSeq) return;
  main.innerHTML = "";
  current = { key, route, module, params, query, cleanup: null };
  window.scrollTo(0, 0);
  emit("route", currentRoute());

  const alive = () => token === renderSeq;
  try {
    const cleanup = await module.render(main, { params, query, props: route.props || {}, alive });
    if (alive()) current.cleanup = typeof cleanup === "function" ? cleanup : null;
    else if (typeof cleanup === "function") cleanup();
  } catch (err) {
    console.error(err);
    if (alive()) main.replaceChildren(errorView(err?.detail || "Something went wrong while loading this page."));
  }
  if (alive() && !main.contains(document.activeElement) && !document.getElementById("overlay-root").contains(document.activeElement)) {
    main.focus({ preventScroll: true });
  }
}

function errorView(message) {
  const node = el(`
    <div class="page"><div class="empty">
      <h1 class="empty__title">This page didn't load</h1>
      <p class="empty__text">${esc(message)}</p>
      <button type="button" class="btn btn--glass">Try again</button>
    </div></div>`);
  node.querySelector("button").addEventListener("click", () => { current = null; handle(); });
  return node;
}

/** Go somewhere. replace = true swaps the history entry (no new Back step). */
export function navigate(hash, { replace = false } = {}) {
  if (replace) {
    history.replaceState(null, "", hash);
    handle();
  } else if (location.hash === hash) {
    handle();
  } else {
    location.hash = hash;
  }
}

export function startRouter() {
  addEventListener("hashchange", handle);
  handle();
}
