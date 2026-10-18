// ============================================================================
// CineMatch — pages/search.js  (#/search?q=...)
// Instant title search (the nav box is debounced and updates this page in
// place). Also suggests matching directors / actors, which open the Mood
// Mixer pre-filled with that person.
// ============================================================================

import { api } from "../api.js";
import { track, makeSource, markListShown } from "../tracking.js";
import { el, esc } from "../utils.js";
import { icon } from "../ui/icons.js";
import { captionCard } from "../ui/card.js";
import { openMixer } from "../ui/mixer.js";
import { toastError } from "../ui/toast.js";

let page = null;
let seq = 0;

export async function render(main, { query }) {
  page = el(`
    <div class="page">
      <header class="page-head">
        <h1 class="page-title" data-title></h1>
        <p class="page-sub" data-sub></p>
        <div class="chips" data-people></div>
      </header>
      <div class="grid" data-grid aria-live="polite"></div>
    </div>`);
  main.appendChild(page);
  run(query.get("q") || "");
  return () => { page = null; };
}

export function update({ query }) {
  if (page) run(query.get("q") || "");
}

async function run(q) {
  const mine = ++seq;
  const title = page.querySelector("[data-title]");
  const sub = page.querySelector("[data-sub]");
  const grid = page.querySelector("[data-grid]");
  const people = page.querySelector("[data-people]");
  document.title = q ? `${q} | CineMatch search` : "Search | CineMatch";

  if (!q) {
    title.textContent = "Search";
    sub.textContent = "Type a title in the search box above. Press / to jump there from anywhere.";
    grid.innerHTML = "";
    people.innerHTML = "";
    return;
  }
  title.textContent = `Results for “${q}”`;
  sub.textContent = "Searching…";
  grid.innerHTML = Array.from({ length: 8 }, () => '<div aria-hidden="true"><div class="skel skel--poster"></div><div class="skel skel--line" style="margin-top:12px;width:75%"></div></div>').join("");

  // people suggestions (quiet: failures don't matter)
  Promise.all(["director", "actor"].map((role) => api.get("/api/meta/people", { role, q, limit: 3 }, { wake: false })
    .then((r) => (r.items || []).map((name) => ({ name, role }))).catch(() => [])))
    .then((lists) => {
      if (mine !== seq || !page) return;
      const found = lists.flat().slice(0, 5);
      people.innerHTML = found.map((p, i) => `<button type="button" class="chip" data-i="${i}">${icon(p.role === "director" ? "film" : "user")}<span>${esc(p.name)}</span><span class="chip__note">${p.role === "director" ? "director" : "actor"}</span></button>`).join("");
      people.querySelectorAll("[data-i]").forEach((b) => b.addEventListener("click", () => {
        const p = found[Number(b.dataset.i)];
        openMixer(p.role === "director" ? { directors: [p.name] } : { actors: [p.name] }, { fromRow: p.name });
      }));
    });

  try {
    const res = await api.get("/api/movies", { q, sort: "popular", page: 1, page_size: 40 });
    if (mine !== seq || !page) return;
    const items = res.items || [];
    const total = res.total ?? items.length;
    track("search", { row_id: "search", value: total });
    sub.textContent = total ? `${total} ${total === 1 ? "title" : "titles"}` : "";
    grid.innerHTML = "";
    if (!items.length) {
      const empty = el(`<div class="empty" style="grid-column:1/-1">
        <p class="empty__title">Nothing called “${esc(q)}”</p>
        <p class="empty__text">Check the spelling or try fewer words. If you know the mood rather than the name, the Mood Mixer can help.</p>
        <button type="button" class="btn btn--glass">${icon("sliders")} Open the Mood Mixer</button></div>`);
      empty.querySelector("button").addEventListener("click", () => openMixer());
      grid.appendChild(empty);
      return;
    }
    const source = makeSource("search");
    items.forEach((m) => grid.appendChild(captionCard(m, { source, showReason: false })));
    markListShown(source);
  } catch (err) {
    if (mine !== seq) return;
    grid.innerHTML = "";
    sub.textContent = "";
    toastError(err);
  }
}
