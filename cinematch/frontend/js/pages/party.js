// ============================================================================
// CineMatch — pages/party.js  (#/party and #/party/:code)
// Watch party: blend 2+ people's taste into one list.
//   lobby → create a party (add friends by email) or join with a code
//   room  → members, a short Mood-Mixer-style context, and blended results
//           where every card shows each member's predicted stars.
// ============================================================================

import { api } from "../api.js";
import { state } from "../state.js";
import { MOCK } from "../config.js";
import { getMeta } from "../meta.js";
import { setBaseMovie, clearBaseMovie } from "../ambient.js";
import { makeSource, markListShown } from "../tracking.js";
import { navigate } from "../router.js";
import { el, esc, initials, hashString, cleanContext } from "../utils.js";
import { icon } from "../ui/icons.js";
import { captionCard } from "../ui/card.js";
import { fallbackTip } from "../ui/carousel.js";
import { buildMixerForm, baseContext } from "../ui/mixer.js";
import { toast, toastError } from "../ui/toast.js";

function avatar(user, size = "") {
  const name = user.display_name || user.email || "?";
  const h = hashString(name);
  return `<span class="avatar ${size}" style="--a1:hsl(${h % 360} 62% 56%);--a2:hsl(${(h >> 9) % 360} 70% 42%)" aria-hidden="true">${esc(initials(name))}</span>`;
}

export async function render(main, { params, alive }) {
  if (params.code) return room(main, params.code.toUpperCase(), alive);
  return lobby(main);
}

// ---- lobby -------------------------------------------------------------------------------------
function lobby(main) {
  let emails = [];
  const node = el(`
    <div class="page">
      <header class="page-head">
        <h1 class="page-title">Watch party</h1>
        <p class="page-sub">One list for everyone on the sofa. We blend your tastes and leave out anything one of you would dislike.</p>
      </header>
      <div class="party-start">
        <section class="panel party-card" aria-labelledby="start-title">
          <h2 class="party-card__title" id="start-title">Start a party</h2>
          <p class="dim small">Add friends by the email they use on CineMatch. You can also share a code later.</p>
          <form class="inline-form" data-add>
            <input class="input" type="email" placeholder="friend@example.com" aria-label="Friend's email" autocomplete="off">
            <button type="submit" class="btn btn--glass">${icon("plus")} Add</button>
          </form>
          <div class="chips" data-emails></div>
          <p class="form-error" data-error-start role="alert"></p>
          <button type="button" class="btn btn--play" data-act="create">${icon("users")} Create party</button>
          ${MOCK ? '<p class="hint">Demo friends: aman@example.com and riya@example.com</p>' : ""}
        </section>
        <section class="panel party-card" aria-labelledby="join-title">
          <h2 class="party-card__title" id="join-title">Join with a code</h2>
          <p class="dim small">Got a 6-character code from a friend? Enter it here.</p>
          <form class="inline-form" data-join>
            <input class="input code-input" maxlength="6" placeholder="ABC123" aria-label="Party code" autocomplete="off" spellcheck="false">
            <button type="submit" class="btn btn--glass">Join</button>
          </form>
          <p class="form-error" data-error-join role="alert"></p>
        </section>
      </div>
    </div>`);
  main.appendChild(node);

  const emailsEl = node.querySelector("[data-emails]");
  const renderEmails = () => {
    emailsEl.innerHTML = emails.map((e, i) => `<span class="chip chip--active"><span>${esc(e)}</span><button type="button" class="chip__x" data-i="${i}" aria-label="Remove ${esc(e)}">${icon("x")}</button></span>`).join("");
    emailsEl.querySelectorAll(".chip__x").forEach((b) => b.addEventListener("click", () => { emails.splice(Number(b.dataset.i), 1); renderEmails(); }));
  };
  node.querySelector("[data-add]").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = e.currentTarget.querySelector("input");
    const value = input.value.trim().toLowerCase();
    const err = node.querySelector("[data-error-start]");
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value)) { err.textContent = "Enter a full email address, like friend@example.com."; return; }
    if (value === state.user?.email) { err.textContent = "You're already in the party as the host."; return; }
    err.textContent = "";
    if (!emails.includes(value)) emails.push(value);
    input.value = "";
    renderEmails();
  });
  node.querySelector('[data-act="create"]').addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const err = node.querySelector("[data-error-start]");
    btn.disabled = true;
    try {
      const party = await api.post("/api/party", { member_emails: emails });
      navigate(`#/party/${party.code}`);
    } catch (error) {
      err.textContent = error.status === 404 ? error.detail : "";
      if (error.status !== 404) toastError(error);
      btn.disabled = false;
    }
  });
  node.querySelector("[data-join]").addEventListener("submit", async (e) => {
    e.preventDefault();
    const code = e.currentTarget.querySelector("input").value.trim().toUpperCase();
    const err = node.querySelector("[data-error-join]");
    if (!/^[A-Z0-9]{6}$/.test(code)) { err.textContent = "Codes are 6 letters or numbers."; return; }
    try {
      await api.post(`/api/party/${code}/join`);
      navigate(`#/party/${code}`);
    } catch (error) {
      err.textContent = error.status === 404 ? "No party with that code. Check it with your friend." : error.detail;
    }
  });
}

// ---- room --------------------------------------------------------------------------------------------
async function room(main, code, alive) {
  main.innerHTML = `<div class="page"><div class="skel skel--title" style="width:320px"></div></div>`;
  let party;
  try {
    party = await api.get(`/api/party/${code}`);
    if (!party.members?.some((m) => m.id === state.user?.id)) party = await api.post(`/api/party/${code}/join`);
  } catch (err) {
    if (!alive()) return;
    main.innerHTML = "";
    const empty = el(`<div class="page"><div class="empty">
      <h1 class="empty__title">That party doesn't exist</h1>
      <p class="empty__text">${esc(err.status === 404 ? "Check the code with whoever invited you, or start a new party." : err.detail)}</p>
      <a class="btn btn--glass" href="#/party">Back to watch party</a></div></div>`);
    main.appendChild(empty);
    return;
  }
  const meta = await getMeta();
  if (!alive()) return;

  const ctx = { ...baseContext() };
  const node = el(`
    <div class="page">
      <div class="party-room__head">
        <div style="display:grid;gap:10px">
          <p class="dim">Party code</p>
          <div class="code-display" aria-label="Party code ${code.split("").join(" ")}">${esc(code)}</div>
          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <button type="button" class="btn btn--glass btn--sm" data-act="copy">${icon("copy")} Copy code</button>
            <button type="button" class="btn btn--ghost btn--sm" data-act="refresh">${icon("refresh")} Refresh members</button>
          </div>
        </div>
        <div class="members" data-members></div>
      </div>
      <div class="party-room__body">
        <section class="panel" aria-labelledby="party-mix-title" style="position:sticky;top:calc(var(--nav-h) + 16px);max-height:calc(100dvh - var(--nav-h) - 32px);overflow:auto">
          <h2 class="party-card__title" id="party-mix-title">Tonight's plan</h2>
          <div data-form></div>
          <button type="button" class="btn btn--play btn--block" data-act="find" style="margin-top:8px">${icon("sparkle")} Find our film</button>
        </section>
        <section aria-live="polite">
          <div class="section__head"><h2 class="section-title" data-label>Your blended list</h2></div>
          <p class="dim small" data-hint>Pick a plan on the left, or just press "Find our film".</p>
          <div class="grid" data-grid style="margin-top:18px"></div>
        </section>
      </div>
    </div>`);
  main.innerHTML = "";
  main.appendChild(node);

  const renderMembers = (p) => {
    node.querySelector("[data-members]").innerHTML = p.members.map((m) => `
      <div class="member">${avatar(m, "avatar--lg")}<div><span class="member__name">${esc(m.display_name || m.email)}</span>
      <span class="member__role">${m.id === p.host?.id ? "Host" : "Guest"}${m.id === state.user?.id ? ", you" : ""}</span></div></div>`).join("");
  };
  renderMembers(party);

  node.querySelector("[data-form]").appendChild(buildMixerForm(ctx, meta, { sections: ["occasion", "feel", "rules"] }));
  node.querySelector('[data-act="copy"]').addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(code); toast("Code copied. Send it to your friends.", { type: "success" }); }
    catch { toast(`Your party code is ${code}`); }
  });
  node.querySelector('[data-act="refresh"]').addEventListener("click", async () => {
    try { party = await api.get(`/api/party/${code}`); renderMembers(party); } catch (err) { toastError(err); }
  });

  const findBtn = node.querySelector('[data-act="find"]');
  async function find() {
    const grid = node.querySelector("[data-grid]");
    findBtn.disabled = true;
    grid.innerHTML = Array.from({ length: 8 }, () => '<div aria-hidden="true"><div class="skel skel--poster"></div><div class="skel skel--line" style="margin-top:12px;width:75%"></div></div>').join("");
    try {
      const res = await api.post(`/api/party/${code}/recommendations`, { context: cleanContext({ ...ctx, hour: new Date().getHours() }), limit: 20 });
      if (!alive()) return;
      node.querySelector("[data-label]").innerHTML = `${esc(res.fallback ? "Trending now" : res.label || "Your blended list")}${res.fallback ? ` ${fallbackTip()}` : ""}`;
      node.querySelector("[data-hint]").textContent = res.items?.length
        ? "Each card shows how many stars we think each of you would give it."
        : "Nothing suits everyone with these filters. Try loosening them.";
      grid.innerHTML = "";
      const source = makeSource("party", res.request_id);
      (res.items || []).forEach((m) => grid.appendChild(captionCard(m, { source })));
      markListShown(source);
      if (res.items?.[0]) setBaseMovie(res.items[0]);
    } catch (err) {
      grid.innerHTML = "";
      toastError(err);
    } finally {
      findBtn.disabled = false;
    }
  }
  findBtn.addEventListener("click", find);
  find();

  return () => clearBaseMovie();
}
