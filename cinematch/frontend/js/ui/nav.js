// ============================================================================
// CineMatch — ui/nav.js
// Top navigation (glassy, turns solid on scroll), the mobile tab bar, the
// expanding search box, the user menu and the context chip
// (detected weather + time of day, click to override — FR-2.3).
// ============================================================================

import { state, on, setOverrides, hasOverrides, effectiveContext, labelFor } from "../state.js";
import { clearSession } from "../auth.js";
import { resetAmbient } from "../ambient.js";
import { retryLocation } from "../context.js";
import { navigate, currentRoute } from "../router.js";
import { el, esc, debounce, initials, hashString } from "../utils.js";
import { icon, hasIcon } from "./icons.js";
import { openMixer } from "./mixer.js";
import { getMeta } from "../meta.js";

let navEl = null;
let tabbarEl = null;
let popover = null;

const LINKS = [
  { route: "home", href: "#/", label: "Home", icon: "home" },
  { route: "movies", href: "#/movies", label: "Movies", icon: "film" },
  { route: "series", href: "#/series", label: "Series", icon: "tv" },
  { route: "mixer", action: "mixer", label: "Mood Mixer", short: "Mixer", icon: "sliders" },
  { route: "party", href: "#/party", label: "Watch Party", short: "Party", icon: "users" },
  { route: "profile", href: "#/profile", label: "Profile", icon: "user" },
  { route: "admin", href: "#/admin", label: "Admin", icon: "chart", admin: true },
];

export function renderNav() {
  navEl = document.getElementById("nav");
  tabbarEl = document.getElementById("tabbar");
  const user = state.user || {};
  const isAdmin = !!user.is_admin;
  const h = hashString(user.display_name || user.email || "you");
  const avatarStyle = `--a1:hsl(${h % 360} 62% 56%);--a2:hsl(${(h >> 9) % 360} 70% 42%)`;

  navEl.innerHTML = `
    <div class="nav__inner">
      <a class="brand" href="#/" aria-label="CineMatch home"><span class="brand__mark" aria-hidden="true"></span><span class="brand__word">CineMatch</span></a>
      <ul class="nav__links">
        ${LINKS.filter((l) => !l.admin || isAdmin).map((l) => `<li>${l.action
          ? `<button type="button" class="nav__link" data-action="${l.action}">${l.label}</button>`
          : `<a class="nav__link" href="${l.href}" data-route="${l.route}">${l.label}</a>`}</li>`).join("")}
      </ul>
      <div class="nav__tools">
        <form class="search" role="search" autocomplete="off">
          <button type="button" class="icon-btn icon-btn--plain search__btn" aria-label="Search titles">${icon("search")}</button>
          <input class="search__input" type="search" name="q" placeholder="Search titles" aria-label="Search titles" tabindex="-1">
        </form>
        <button type="button" class="ctx-chip" aria-haspopup="dialog" aria-expanded="false"></button>
        <div class="usermenu">
          <button type="button" class="avatar avatar--sm" style="${avatarStyle}" aria-haspopup="menu" aria-expanded="false" aria-label="Account menu">${esc(initials(user.display_name || user.email))}</button>
          <div class="usermenu__menu" role="menu" hidden>
            <div class="usermenu__who"><strong>${esc(user.display_name || "")}</strong><span class="tiny faint">${esc(user.email || "")}</span></div>
            <a class="usermenu__item" role="menuitem" href="#/profile">${icon("user")} Profile</a>
            ${isAdmin ? `<a class="usermenu__item" role="menuitem" href="#/admin">${icon("chart")} Admin</a>` : ""}
            <button type="button" class="usermenu__item" role="menuitem" data-action="logout">${icon("logout")} Sign out</button>
          </div>
        </div>
      </div>
    </div>`;

  tabbarEl.innerHTML = LINKS.filter((l) => ["home", "movies", "series", "mixer", "party"].includes(l.route)).map((l) => l.action
    ? `<button type="button" class="tabbar__item" data-action="${l.action}">${icon(l.icon)}<span>${l.short || l.label}</span></button>`
    : `<a class="tabbar__item" href="${l.href}" data-route="${l.route}">${icon(l.icon)}<span>${l.short || l.label}</span></a>`).join("");

  // actions
  [navEl, tabbarEl].forEach((root) => root.querySelectorAll('[data-action="mixer"]').forEach((b) => b.addEventListener("click", () => openMixer())));
  wireSearch();
  wireUserMenu();
  navEl.querySelector(".ctx-chip").addEventListener("click", toggleContextPopover);

  updateActive(currentRoute());
  updateContextChip();
}

export function showNav(visible) {
  if (!navEl) return;
  navEl.hidden = !visible;
  tabbarEl.hidden = !visible;
}

function updateActive(route) {
  const name = route?.name;
  const map = { "party-room": "party", search: null, results: null };
  const active = name in map ? map[name] : name;
  document.querySelectorAll("#nav [data-route], #tabbar [data-route]").forEach((a) => {
    if (a.dataset.route === active) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
}

// ---- search -------------------------------------------------------------------------------------
function wireSearch() {
  const form = navEl.querySelector(".search");
  const input = form.querySelector("input");
  const btn = form.querySelector(".search__btn");
  const open = () => {
    form.classList.add("is-open");
    input.tabIndex = 0;
    input.focus();
  };
  const close = () => {
    if (input.value) return;
    form.classList.remove("is-open");
    input.tabIndex = -1;
  };
  btn.addEventListener("click", () => (form.classList.contains("is-open") && input.value ? go(input.value) : open()));
  input.addEventListener("blur", () => setTimeout(close, 150));
  const go = (q) => {
    const query = q.trim();
    const onSearch = currentRoute()?.name === "search";
    if (!query) { if (onSearch) navigate("#/search", { replace: true }); return; }
    navigate(`#/search?q=${encodeURIComponent(query)}`, { replace: onSearch });
  };
  const goSoon = debounce(go, 320);
  input.addEventListener("input", () => goSoon(input.value));
  form.addEventListener("submit", (e) => { e.preventDefault(); goSoon.cancel(); go(input.value); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { input.value = ""; input.blur(); form.classList.remove("is-open"); }
  });
  // "/" focuses search from anywhere
  addEventListener("keydown", (e) => {
    if (e.key === "/" && !e.target.closest("input, textarea, select, [contenteditable]") && !navEl.hidden) { e.preventDefault(); open(); }
  });
  on("route", (route) => {
    if (route.name === "search") {
      input.value = route.query.get("q") || "";
      if (input.value) { form.classList.add("is-open"); input.tabIndex = 0; }
    } else if (document.activeElement !== input) {
      input.value = "";
      form.classList.remove("is-open");
    }
  });
}

// ---- user menu ------------------------------------------------------------------------------------
function wireUserMenu() {
  const btn = navEl.querySelector(".usermenu .avatar");
  const menu = navEl.querySelector(".usermenu__menu");
  const setOpen = (open) => {
    menu.hidden = !open;
    btn.setAttribute("aria-expanded", String(open));
    if (open) menu.querySelector(".usermenu__item")?.focus();
  };
  btn.addEventListener("click", (e) => { e.stopPropagation(); setOpen(menu.hidden); });
  menu.addEventListener("click", (e) => e.stopPropagation());
  menu.addEventListener("keydown", (e) => {
    const items = [...menu.querySelectorAll(".usermenu__item")];
    const i = items.indexOf(document.activeElement);
    if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
    if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
    if (e.key === "Escape") { setOpen(false); btn.focus(); }
  });
  menu.querySelectorAll("a").forEach((a) => a.addEventListener("click", () => setOpen(false)));
  document.addEventListener("click", () => setOpen(false));
  menu.querySelector('[data-action="logout"]').addEventListener("click", () => {
    setOpen(false);
    clearSession();
    resetAmbient();
    navigate("#/login");
  });
}

// ---- context chip + override popover (FR-2.3 / FR-2.4) --------------------------------------------
function chipContent() {
  const ctx = state.context;
  const eff = effectiveContext();
  const tod = labelFor("time_of_day", eff.time_of_day);
  const geoOff = state.geo.status === "denied" || ctx?.weather_status === "no_location";

  if (hasOverrides()) {
    const w = eff.weather ? labelFor("weather", eff.weather) : null;
    return { iconName: eff.weather && hasIcon(eff.weather) ? eff.weather : eff.time_of_day, text: w ? `${w}, ${tod.toLowerCase()}` : tod, title: "Your choice (click to change)" };
  }
  if (ctx?.weather) {
    const temp = ctx.weather.temp_c != null ? ` ${Math.round(ctx.weather.temp_c)}°` : "";
    return { iconName: hasIcon(ctx.weather.id) ? ctx.weather.id : "cloudy", text: `${ctx.weather.label}${temp}, ${tod.toLowerCase()}`, title: `${ctx.weather.description || ctx.weather.label} in ${ctx.weather.city || "your area"}` };
  }
  if (geoOff) return { iconName: "pinOff", text: "Location off — using time of day", title: `Using ${tod.toLowerCase()} only. Click to set the weather yourself.` };
  if (ctx?.weather_status === "unavailable") return { iconName: eff.time_of_day, text: tod, title: "Weather is unavailable right now, so we're using the time of day." };
  return { iconName: eff.time_of_day, text: tod, title: "Detecting your weather…" };
}

export function updateContextChip() {
  const chip = navEl?.querySelector(".ctx-chip");
  if (!chip) return;
  const { iconName, text, title } = chipContent();
  chip.innerHTML = `${icon(hasIcon(iconName) ? iconName : "clock")}<span class="ctx-chip__text">${esc(text)}</span>`;
  chip.title = title;
  chip.setAttribute("aria-label", `${text}. Change weather or time of day`);
  chip.dataset.overridden = String(hasOverrides());
  if (popover) renderPopover();
}

function detectedText() {
  const ctx = state.context;
  const tod = labelFor("time_of_day", ctx?.time_of_day || effectiveContext().time_of_day).toLowerCase();
  if (ctx?.weather) return `Detected <strong>${esc(ctx.weather.label.toLowerCase())}${ctx.weather.temp_c != null ? `, ${Math.round(ctx.weather.temp_c)}°C` : ""}</strong> in ${esc(ctx.weather.city || "your area")} this <strong>${esc(tod)}</strong>.`;
  if (state.geo.status === "denied" || ctx?.weather_status === "no_location") return `Location is off, so we're only using the time of day (<strong>${esc(tod)}</strong>). Pick the weather yourself if you like.`;
  if (ctx?.weather_status === "unavailable") return `Weather is unavailable right now. Using the time of day (<strong>${esc(tod)}</strong>).`;
  return `Using the time of day (<strong>${esc(tod)}</strong>).`;
}

async function renderPopover() {
  const meta = await getMeta();
  if (!popover) return;
  const ov = state.overrides;
  const chipBtn = (group, id, label, pressed, iconName) =>
    `<button type="button" class="chip chip--sm" data-group="${group}" data-v="${esc(id ?? "")}" aria-pressed="${pressed}">${iconName && hasIcon(iconName) ? icon(iconName) : ""}<span>${esc(label)}</span></button>`;
  const geoOff = state.geo.status !== "granted";
  popover.innerHTML = `
    <p class="pop__detected">${detectedText()}</p>
    <div>
      <p class="pop__label">Weather</p>
      <div class="chips">${chipBtn("weather", "", "Auto", ov.weather === undefined)}${meta.weather.map((w) => chipBtn("weather", w.id, w.label, ov.weather === w.id, w.id)).join("")}</div>
    </div>
    <div>
      <p class="pop__label">Time of day</p>
      <div class="chips">${chipBtn("time", "", "Auto", !ov.time_of_day)}${meta.time_of_day.map((t) => chipBtn("time", t.id, t.label, ov.time_of_day === t.id, t.id)).join("")}</div>
    </div>
    <div class="pop__actions">
      ${hasOverrides() ? `<button type="button" class="btn btn--ghost btn--sm" data-act="reset">Use detected values</button>` : ""}
      ${geoOff ? `<button type="button" class="btn btn--glass btn--sm" data-act="geo">${icon("pin")} Use my location</button>` : ""}
    </div>`;
  popover.querySelectorAll("[data-group]").forEach((b) => b.addEventListener("click", () => {
    const next = { ...state.overrides };
    const v = b.dataset.v || undefined;
    if (b.dataset.group === "weather") { if (v) next.weather = v; else delete next.weather; }
    else { if (v) next.time_of_day = v; else delete next.time_of_day; }
    setOverrides(next);
  }));
  popover.querySelector('[data-act="reset"]')?.addEventListener("click", () => setOverrides({}));
  popover.querySelector('[data-act="geo"]')?.addEventListener("click", async (e) => {
    e.currentTarget.disabled = true;
    await retryLocation();
  });
}

function toggleContextPopover(e) {
  e.stopPropagation();
  if (popover) { closePopover(); return; }
  const chip = e.currentTarget;
  popover = el('<div class="pop" role="dialog" aria-label="Weather and time of day"></div>');
  document.getElementById("overlay-root").appendChild(popover);
  const r = chip.getBoundingClientRect();
  popover.style.top = `${Math.round(r.bottom + 10)}px`;
  popover.style.right = `${Math.max(12, Math.round(innerWidth - r.right))}px`;
  chip.setAttribute("aria-expanded", "true");
  renderPopover().then(() => popover?.querySelector("button")?.focus());
  popover.addEventListener("click", (ev) => ev.stopPropagation());
  popover.addEventListener("keydown", (ev) => { if (ev.key === "Escape") { closePopover(); chip.focus(); } });
  setTimeout(() => document.addEventListener("click", closePopover, { once: true }), 0);
}

function closePopover() {
  popover?.remove();
  popover = null;
  navEl?.querySelector(".ctx-chip")?.setAttribute("aria-expanded", "false");
}

// keep things fresh
on("context:changed", updateContextChip);
on("geo:changed", updateContextChip);
on("route", (route) => { updateActive(route); closePopover(); });
on("auth:changed", () => { if (navEl && state.user) renderNav(); });
addEventListener("scroll", () => navEl?.classList.toggle("is-solid", scrollY > 24), { passive: true });
