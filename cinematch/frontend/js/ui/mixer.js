// ============================================================================
// CineMatch — ui/mixer.js
// The Mood Mixer: a side drawer with every filter from the CONTRACT Context
// object. "Show my mix" sends you to #/results?c=<context> which calls
// POST /api/recommendations.
//
// The form is built by buildMixerForm() so the Watch Party page can reuse a
// smaller version of it.
// ============================================================================

import { api } from "../api.js";
import { state, effectiveContext, labelFor, languageName, rememberMovies } from "../state.js";
import { getMeta } from "../meta.js";
import { artHTML } from "../posters.js";
import { el, esc, cleanContext, countFilters, encodeCtx, trapFocus, lockScroll, unlockScroll, plural } from "../utils.js";
import { icon, hasIcon } from "./icons.js";
import { autocomplete } from "./autocomplete.js";
import { EMOTIONS, emotionColor, emotionLabel, arcSVG, updateArc, arcCaption } from "./emotion.js";

const VALENCE = { joy: 1, surprise: 1, neutral: 0, sadness: -1, fear: -1, anger: -1, disgust: -1 };
const arcFor = (s, e) => {
  if (!s || !e) return "steady";
  const d = (VALENCE[e] ?? 0) - (VALENCE[s] ?? 0);
  return d > 0 ? "rise" : d < 0 ? "fall" : "steady";
};

/** Weather + time of day the mixer starts from (detected or overridden). */
export function baseContext() {
  const eff = effectiveContext();
  return cleanContext({ weather: eff.weather, time_of_day: eff.time_of_day, hour: eff.hour });
}

// ---- Small form widgets -------------------------------------------------------------------

/** A row of toggle chips where at most one (or many, if multi) can be on. */
function chipGroup({ label, options, get, set, multi = false }) {
  const wrap = el(`<div class="chips" role="group" aria-label="${esc(label)}"></div>`);
  const buttons = options.map((o) => {
    const b = el(`<button type="button" class="chip" aria-pressed="false" data-v="${esc(String(o.id))}">
      ${o.iconHTML || ""}<span>${esc(o.label)}</span>${o.note ? `<span class="chip__note">${esc(o.note)}</span>` : ""}</button>`);
    b.addEventListener("click", () => {
      if (multi) {
        const current = new Set(get() || []);
        current.has(o.id) ? current.delete(o.id) : current.add(o.id);
        set([...current]);
      } else {
        set(String(get()) === String(o.id) ? null : o.id);
      }
      sync();
    });
    wrap.appendChild(b);
    return { b, o };
  });
  function sync() {
    const v = get();
    buttons.forEach(({ b, o }) => {
      const on = multi ? (v || []).includes(o.id) : String(v) === String(o.id);
      b.setAttribute("aria-pressed", String(on));
    });
  }
  sync();
  wrap.sync = sync;
  return wrap;
}

/** Segmented control (exactly one option is always selected). */
function segmented({ label, options, get, set }) {
  const wrap = el(`<div class="seg" role="radiogroup" aria-label="${esc(label)}"></div>`);
  const buttons = options.map((o) => {
    const b = el(`<button type="button" class="seg__opt" role="radio" aria-checked="false">${esc(o.label)}</button>`);
    b.addEventListener("click", () => { set(o.id); sync(); });
    wrap.appendChild(b);
    return { b, o };
  });
  function sync() {
    const v = get() ?? options[0].id;
    buttons.forEach(({ b, o }) => b.setAttribute("aria-checked", String(String(v) === String(o.id))));
  }
  wrap.addEventListener("keydown", (e) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const i = buttons.findIndex(({ b }) => b === document.activeElement);
    if (i < 0) return;
    e.preventDefault();
    const next = buttons[(i + (e.key === "ArrowRight" ? 1 : buttons.length - 1)) % buttons.length];
    next.b.focus();
    next.b.click();
  });
  sync();
  return wrap;
}

function field(labelText, control, { output } = {}) {
  const f = el(`<div class="mx-field"><div class="mx-label"><span>${esc(labelText)}</span>${output ? "<output></output>" : ""}</div></div>`);
  f.appendChild(control);
  return f;
}

function section(title, hint) {
  return el(`<section class="mx-sec"><h3 class="mx-sec__title">${esc(title)}</h3>${hint ? `<p class="mx-sec__hint">${esc(hint)}</p>` : ""}</section>`);
}

const miniPoster = (m) => `<span class="token__thumb">${artHTML(m, "poster")}</span>`;

/**
 * Build the mixer form.
 *   ctx      the context object to edit (mutated in place)
 *   meta     normalised /api/meta/filters
 *   sections which groups to include (default: all)
 *   onChange called after any change
 */
export function buildMixerForm(ctx, meta, { sections = ["now", "occasion", "feel", "like", "rules"], onChange = () => {} } = {}) {
  const form = el('<div class="mx-form"></div>');
  const setter = (key) => (v) => {
    if (v === null || v === undefined || (Array.isArray(v) && !v.length)) delete ctx[key];
    else ctx[key] = v;
    onChange(ctx);
  };
  const getter = (key) => () => ctx[key];

  if (sections.includes("now")) {
    const s = section("Right now", "Detected for you. Change anything that's off.");
    s.appendChild(field("Weather", chipGroup({
      label: "Weather",
      options: meta.weather.map((w) => ({ id: w.id, label: w.label, iconHTML: hasIcon(w.id) ? icon(w.id) : "" })),
      get: getter("weather"), set: setter("weather"),
    })));
    s.appendChild(field("Time of day", chipGroup({
      label: "Time of day",
      options: meta.time_of_day.map((t) => ({ id: t.id, label: t.label, iconHTML: hasIcon(t.id) ? icon(t.id) : "" })),
      get: getter("time_of_day"), set: setter("time_of_day"),
    })));
    s.appendChild(field("Time you have", chipGroup({
      label: "Time you have",
      options: meta.time_available.map((t) => ({ id: t.minutes ?? "none", label: t.label })),
      get: () => ctx.time_available_min ?? "none",
      set: (v) => setter("time_available_min")(v === "none" || v === null ? null : Number(v)),
    })));
    form.appendChild(s);
  }

  if (sections.includes("occasion")) {
    const s = section("The occasion");
    s.appendChild(field("What's the plan?", chipGroup({
      label: "Occasion",
      options: meta.occasions.map((o) => ({ id: o.id, label: o.label, iconHTML: hasIcon(o.id) ? icon(o.id) : "" })),
      get: getter("occasion"), set: setter("occasion"),
    })));
    const upcoming = state.context?.upcoming_festival;
    const festivals = [...meta.festivals].sort((a, b) => (b.id === upcoming?.id) - (a.id === upcoming?.id));
    s.appendChild(field("Festival", chipGroup({
      label: "Festival",
      options: festivals.map((f) => ({
        id: f.id, label: f.label,
        iconHTML: f.icon ? `<span class="chip__emoji" aria-hidden="true">${esc(f.icon)}</span>` : "",
        note: f.id === upcoming?.id ? (upcoming.days_away === 0 ? "today" : `in ${upcoming.days_away} days`) : "",
      })),
      get: getter("festival"), set: setter("festival"),
    })));
    form.appendChild(s);
  }

  if (sections.includes("feel")) {
    const s = section("How do you want to feel?", "Choose where the story starts and where you'd like it to leave you.");
    const emotionOptions = (meta.emotions.length ? meta.emotions.map((e) => e.id) : EMOTIONS)
      .map((id) => ({ id, label: labelFor("emotions", id) || emotionLabel(id), iconHTML: `<span class="chip__dot" style="--c:${emotionColor(id)}"></span>` }));
    const arcBox = el(`<div class="emo-arc">${arcSVG(ctx.start_emotion, ctx.end_emotion, arcFor(ctx.start_emotion, ctx.end_emotion), { id: `mx${Math.random().toString(36).slice(2, 7)}` })}<p class="emo-arc__caption"></p></div>`);
    const refreshArc = () => {
      updateArc(arcBox.querySelector("svg"), ctx.start_emotion, ctx.end_emotion, arcFor(ctx.start_emotion, ctx.end_emotion));
      arcBox.querySelector(".emo-arc__caption").textContent = arcCaption(ctx.start_emotion, ctx.end_emotion);
    };
    const withArc = (key) => (v) => { setter(key)(v); refreshArc(); };
    s.appendChild(field("At the start", chipGroup({ label: "Starting feeling", options: emotionOptions, get: getter("start_emotion"), set: withArc("start_emotion") })));
    s.appendChild(field("By the end", chipGroup({ label: "Ending feeling", options: emotionOptions, get: getter("end_emotion"), set: withArc("end_emotion") })));
    const preview = el('<div class="mx-field"></div>');
    preview.appendChild(arcBox);
    s.appendChild(preview);
    refreshArc();
    form.appendChild(s);
  }

  if (sections.includes("like")) {
    const s = section("More like these", "Pick films, directors or actors you're in the mood for.");
    const refMovies = (ctx.reference_movie_ids || []).map((id) => state.movies.get(id) || { movie_id: id, title: `Title #${id}`, genres: [] });
    const refs = autocomplete({
      label: "Reference films", placeholder: "Search a film you love",
      search: async (q) => { const r = await api.get("/api/movies/search", { q, limit: 8 }, { wake: false }); rememberMovies(r.items); return r.items; },
      optionHTML: (m) => `<span class="ac__thumb poster">${artHTML(m, "poster")}</span><span><span class="ac__opt-title">${esc(m.title)}</span><br><span class="ac__opt-sub">${m.year || ""} ${esc((m.genres || []).slice(0, 2).join(", "))}</span></span>`,
      tokenHTML: (m) => `${miniPoster(m)}<span>${esc(m.title)}</span>`,
      keyOf: (m) => String(m.movie_id),
      values: refMovies, max: 5,
      onChange: (list) => setter("reference_movie_ids")(list.map((m) => m.movie_id)),
    });
    s.appendChild(field("Films", refs));
    // fill in real titles for ids that came from a URL
    const missing = refMovies.filter((m) => m.title.startsWith("Title #"));
    if (missing.length) {
      Promise.all(missing.map((m) => api.get(`/api/movies/${m.movie_id}`, null, { wake: false }).catch(() => null))).then((found) => {
        found.filter(Boolean).forEach((m) => rememberMovies([m]));
        refs.setValues((ctx.reference_movie_ids || []).map((id) => state.movies.get(id) || { movie_id: id, title: `Title #${id}`, genres: [] }));
      });
    }
    const people = (role, key, label, placeholder) => autocomplete({
      label, placeholder,
      search: async (q) => (await api.get("/api/meta/people", { role, q, limit: 8 }, { wake: false })).items,
      optionHTML: (name) => `<span class="ac__opt-title">${esc(name)}</span>`,
      tokenHTML: (name) => `<span>${esc(name)}</span>`,
      tokenClass: "token--text",
      keyOf: (name) => name,
      values: ctx[key] || [], max: 5,
      onChange: (list) => setter(key)(list),
    });
    const two = el('<div class="mx-two"></div>');
    two.appendChild(field("Directors", people("director", "directors", "Directors", "e.g. Christopher Nolan")));
    two.appendChild(field("Actors", people("actor", "actors", "Actors", "e.g. Aamir Khan")));
    s.appendChild(two);
    form.appendChild(s);
  }

  if (sections.includes("rules")) {
    const s = section("Ground rules");
    s.appendChild(field("Genres", chipGroup({
      label: "Genres", multi: true,
      options: meta.genres.filter((g) => g !== "IMAX").map((g) => ({ id: g, label: g })),
      get: getter("genres"), set: setter("genres"),
    })));
    s.appendChild(field("Type", segmented({
      label: "Content type",
      options: [{ id: "any", label: "Anything" }, { id: "movie", label: "Movies" }, { id: "series", label: "Series" }],
      get: () => ctx.content_type || "any", set: (v) => setter("content_type")(v === "any" ? null : v),
    })));
    s.appendChild(field("Suitable for", segmented({
      label: "Maximum age rating",
      options: [{ id: "any", label: "Anyone" }, ...meta.age_ratings.map((a) => ({ id: a, label: a }))],
      get: () => ctx.max_age_rating || "any", set: (v) => setter("max_age_rating")(v === "any" ? null : v),
    })));
    s.appendChild(field("Franchise", segmented({
      label: "Franchise",
      options: [{ id: "any", label: "Either" }, { id: "only", label: "Only franchises" }, { id: "exclude", label: "No franchises" }],
      get: () => ctx.franchise_mode || "any", set: (v) => setter("franchise_mode")(v === "any" ? null : v),
    })));

    const two = el('<div class="mx-two"></div>');
    const lang = el(`<select class="select" aria-label="Language"><option value="">Any language</option>${
      meta.languages.map((l) => `<option value="${esc(l.code)}">${esc(l.name)}</option>`).join("")}</select>`);
    lang.value = ctx.language || "";
    lang.addEventListener("change", () => setter("language")(lang.value || null));
    two.appendChild(field("Language", lang));

    const decades = meta.decades;
    const idx = ctx.nostalgia_decade ? Math.max(0, decades.indexOf(Number(ctx.nostalgia_decade))) + 1 : 0;
    const slider = el(`<input type="range" class="range" min="0" max="${decades.length}" step="1" value="${idx}" aria-label="Nostalgia decade">`);
    const nostalgia = field("Nostalgia", slider, { output: true });
    const out = nostalgia.querySelector("output");
    const syncSlider = () => {
      const i = Number(slider.value);
      out.textContent = i ? `${decades[i - 1]}s` : "Off";
      slider.style.setProperty("--p", `${(i / decades.length) * 100}%`);
      slider.setAttribute("aria-valuetext", out.textContent);
    };
    slider.addEventListener("input", () => {
      const i = Number(slider.value);
      setter("nostalgia_decade")(i ? decades[i - 1] : null);
      syncSlider();
    });
    syncSlider();
    two.appendChild(nostalgia);
    s.appendChild(two);
    form.appendChild(s);
  }

  return form;
}

/** Chips describing a context (results page "active filters"). Each can remove itself. */
export function describeContext(ctx) {
  const chips = [];
  const drop = (key) => (c) => { const n = { ...c }; delete n[key]; return n; };
  const dropFrom = (key, value) => (c) => ({ ...c, [key]: (c[key] || []).filter((x) => x !== value) });
  const add = (key, label, remove = drop(key)) => chips.push({ key, label, remove });
  const minutes = (m) => {
    if (m < 60) return `${m} minutes`;
    const h = Math.floor(m / 60);
    const half = m % 60 >= 30 ? "½" : "";
    return `${h}${half} ${h === 1 && !half ? "hour" : "hours"}`;
  };

  // some home rows carry a backend preset (e.g. {"preset": "trending"}) so "See all" returns the same list
  const PRESETS = { trending: "Trending", acclaimed: "Critically acclaimed", hidden_gems: "Hidden gems", mind_bending: "Mind-bending" };
  if (ctx.preset) add("preset", PRESETS[ctx.preset] || String(ctx.preset).replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()));
  if (ctx.weather) add("weather", labelFor("weather", ctx.weather));
  if (ctx.time_of_day) add("time_of_day", labelFor("time_of_day", ctx.time_of_day));
  if (ctx.time_available_min) add("time_available_min", `Under ${minutes(ctx.time_available_min)}`);
  if (ctx.occasion) add("occasion", labelFor("occasions", ctx.occasion));
  if (ctx.festival) add("festival", labelFor("festivals", ctx.festival));
  if (ctx.start_emotion) add("start_emotion", `Starts ${emotionLabel(ctx.start_emotion).toLowerCase()}`);
  if (ctx.end_emotion) add("end_emotion", `Ends ${emotionLabel(ctx.end_emotion).toLowerCase()}`);
  (ctx.reference_movie_ids || []).forEach((id) => add(`ref:${id}`, `Like ${state.movies.get(id)?.title || "a film you picked"}`, dropFrom("reference_movie_ids", id)));
  (ctx.directors || []).forEach((n) => add(`dir:${n}`, `By ${n}`, dropFrom("directors", n)));
  (ctx.actors || []).forEach((n) => add(`act:${n}`, `With ${n}`, dropFrom("actors", n)));
  (ctx.genres || []).forEach((g) => add(`genre:${g}`, g, dropFrom("genres", g)));
  if (ctx.language) add("language", languageName(ctx.language));
  if (ctx.max_age_rating) add("max_age_rating", `Up to ${ctx.max_age_rating}`);
  if (ctx.franchise_mode === "only") add("franchise_mode", "Franchises only");
  if (ctx.franchise_mode === "exclude") add("franchise_mode", "No franchises");
  if (ctx.nostalgia_decade) add("nostalgia_decade", `${ctx.nostalgia_decade}s`);
  if (ctx.content_type === "movie") add("content_type", "Movies only");
  if (ctx.content_type === "series") add("content_type", "Series only");
  return chips;
}

// ---- The drawer ------------------------------------------------------------------------------
let drawer = null;

export async function openMixer(preset = null, { fromRow = null } = {}) {
  const meta = await getMeta();
  if (drawer) closeMixer({ instant: true });

  let ctx = preset ? { ...baseContext(), ...structuredClone(preset) } : structuredClone(state.lastMix || baseContext());
  const lastFocus = document.activeElement;

  const scrim = el('<div class="scrim"></div>');
  const node = el(`
    <aside class="drawer" role="dialog" aria-modal="true" aria-labelledby="mixer-title">
      <header class="drawer__head">
        <h2 class="drawer__title" id="mixer-title">Mood Mixer</h2>
        <p class="drawer__lede">${fromRow ? `Starting from <strong>${esc(fromRow)}</strong>. Adjust anything, then show your mix.` : "Tell us about tonight. Everything here is optional."}</p>
        <button type="button" class="icon-btn icon-btn--plain drawer__close" aria-label="Close Mood Mixer">${icon("x")}</button>
      </header>
      <div class="drawer__body"></div>
      <footer class="drawer__foot">
        <button type="button" class="btn btn--ghost btn--sm" data-act="reset">Reset</button>
        <span class="count" aria-live="polite"></span>
        <button type="button" class="btn btn--play" data-act="apply">${icon("sparkle")} Show my mix</button>
      </footer>
    </aside>`);
  const body = node.querySelector(".drawer__body");
  const count = node.querySelector(".count");
  const updateCount = () => { const n = countFilters(ctx); count.textContent = n ? plural(n, "filter") : "No filters yet"; };
  const renderForm = () => {
    body.innerHTML = "";
    body.appendChild(buildMixerForm(ctx, meta, { onChange: updateCount }));
    updateCount();
  };
  renderForm();

  const root = document.getElementById("overlay-root");
  root.appendChild(scrim);
  root.appendChild(node);
  lockScroll();
  const untrap = trapFocus(node);

  const close = () => closeMixer();
  scrim.addEventListener("click", close);
  node.querySelector(".drawer__close").addEventListener("click", close);
  node.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.preventDefault(); close(); } });
  node.querySelector('[data-act="reset"]').addEventListener("click", () => { ctx = baseContext(); renderForm(); });
  node.querySelector('[data-act="apply"]').addEventListener("click", () => {
    const clean = cleanContext(ctx);
    state.lastMix = clean;
    state.pendingApply = true;
    closeMixer();
    location.hash = `#/results?c=${encodeCtx(clean)}`;
  });

  drawer = { scrim, node, untrap, lastFocus };
  requestAnimationFrame(() => {
    scrim.classList.add("is-open");
    node.classList.add("is-open");
    node.querySelector(".drawer__close").focus({ preventScroll: true });
  });
}

export function closeMixer({ instant = false } = {}) {
  if (!drawer) return;
  const { scrim, node, untrap, lastFocus } = drawer;
  drawer = null;
  untrap();
  scrim.classList.remove("is-open");
  node.classList.remove("is-open");
  setTimeout(() => { scrim.remove(); node.remove(); }, instant ? 0 : 460);
  unlockScroll();
  if (lastFocus?.isConnected) lastFocus.focus({ preventScroll: true });
}
