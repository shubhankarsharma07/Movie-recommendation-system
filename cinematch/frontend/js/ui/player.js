// ============================================================================
// CineMatch — ui/player.js
// The player overlay. CineMatch doesn't stream films (SRS scope), so:
//   * if the film has a trailer_key → we play the YouTube trailer with the
//     YouTube IFrame Player API and read its state (pause / resume / seeks);
//   * otherwise → a SIMULATED cinematic player: an accelerated timeline over
//     the real runtime, with play/pause, 10-second skips and a scrubber.
// Either way we log the session for the recommender (Module 3):
//   POST /api/playback/start   → { session_id, is_rewatch, start_number }
//   POST /api/playback/{id}/event  pause | resume | seek_back | seek_forward
//   POST /api/playback/{id}/stop   position, duration, completed (drop-off, AC-4)
// "stop" is also sent with fetch keepalive if the tab is closed mid-film.
// Series get a "Next episode" countdown that logs binge_next.
// ============================================================================

import { api } from "../api.js";
import { SIM_SPEED } from "../config.js";
import { artHTML } from "../posters.js";
import { setAmbientMode, getAmbientMode, showMovie as ambientShow } from "../ambient.js";
import { track, trackSelect } from "../tracking.js";
import { el, esc, formatClock, trapFocus, lockScroll, unlockScroll } from "../utils.js";
import { icon } from "./icons.js";
import { toast } from "./toast.js";

let active = null;

export async function openPlayer(movie, { source = null, mode = "play" } = {}) {
  if (active) await active.close();
  trackSelect(source, movie.movie_id);
  active = new Player(movie, { source, mode });
  active.open();
}

// ---- YouTube IFrame API loader (loaded once, only when needed) ------------------------------
let ytPromise = null;
function loadYouTube(timeoutMs = 7000) {
  if (window.YT?.Player) return Promise.resolve(window.YT);
  if (!ytPromise) {
    ytPromise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => { ytPromise = null; reject(new Error("YouTube timed out")); }, timeoutMs);
      const previous = window.onYouTubeIframeAPIReady;
      window.onYouTubeIframeAPIReady = () => { clearTimeout(timer); previous?.(); resolve(window.YT); };
      const s = document.createElement("script");
      s.src = "https://www.youtube.com/iframe_api";
      s.async = true;
      s.onerror = () => { clearTimeout(timer); ytPromise = null; reject(new Error("YouTube blocked")); };
      document.head.appendChild(s);
    });
  }
  return ytPromise;
}

class Player {
  constructor(movie, { source, mode }) {
    this.movie = movie;
    this.source = source;
    this.mode = mode;                       // "play" | "trailer"
    this.isSeries = movie.content_type === "series";
    this.useYouTube = !!movie.trailer_key;
    this.episode = 1;
    this.duration = Math.max(60, (movie.runtime || (this.isSeries ? 45 : 110)) * 60);
    this.position = 0;
    this.playing = false;
    this.ended = false;
    this.sessionId = null;
    this.raf = 0;
    this.closed = false;
    this.onPageHide = () => this.sendStop({ keepalive: true });
  }

  // ---------- lifecycle ----------
  open() {
    this.prevAmbient = getAmbientMode();
    this.lastFocus = document.activeElement;
    this.root = el(`
      <div class="player" role="dialog" aria-modal="true" aria-label="${esc(`Playing ${this.movie.title}`)}">
        <div class="player__stage"></div>
        <div class="player__flash" aria-hidden="true"></div>
        <div class="player__chrome">
          <div class="player__top">
            <button type="button" class="btn btn--glass btn--sm" data-act="close">${icon("chevronLeft")} Back</button>
            <div>
              <div class="player__title">${esc(this.movie.title)}</div>
              <div class="small dim" data-subtitle></div>
            </div>
            <div class="player__badges"></div>
          </div>
          <div class="player__bottom-slot"></div>
        </div>
      </div>`);
    this.$ = (sel) => this.root.querySelector(sel);
    this.$('[data-act="close"]').addEventListener("click", () => this.close());
    this.root.addEventListener("keydown", (e) => this.onKey(e));
    this.root.addEventListener("pointermove", () => this.wake());
    this.root.addEventListener("click", (e) => {
      if (e.target.closest(".player__stage") && !this.useYouTube) this.toggle();
    });

    document.getElementById("overlay-root").appendChild(this.root);
    lockScroll();
    this.untrap = trapFocus(this.root);
    setAmbientMode("player");
    ambientShow(this.movie);
    addEventListener("pagehide", this.onPageHide);
    requestAnimationFrame(() => this.root.classList.add("is-open"));
    this.$('[data-act="close"]').focus({ preventScroll: true });

    this.updateSubtitle();
    if (this.mode === "trailer") this.addBadge("Trailer", true);
    this.startSession();
    if (this.useYouTube) this.mountYouTube();
    else this.mountSimulated();
  }

  async close() {
    if (this.closed) return;
    this.closed = true;
    cancelAnimationFrame(this.raf);
    clearInterval(this.ytPoll);
    clearInterval(this.countdownTimer);
    clearTimeout(this.idleTimer);
    removeEventListener("pagehide", this.onPageHide);
    this.sendStop();
    try { this.yt?.destroy(); } catch { /* ignore */ }
    this.untrap?.();
    this.root.classList.remove("is-open");
    const node = this.root;
    setTimeout(() => node.remove(), 360);
    unlockScroll();
    setAmbientMode(this.prevAmbient);
    if (this.lastFocus?.isConnected) this.lastFocus.focus({ preventScroll: true });
    if (active === this) active = null;
  }

  // ---------- logging ----------
  async startSession() {
    if (this.mode !== "play") return;
    try {
      const res = await api.post("/api/playback/start", { movie_id: this.movie.movie_id, request_id: this.source?.request_id || null });
      if (this.closed) { this.sessionId = res.session_id; this.sendStop(); return; }
      this.sessionId = res.session_id;
      if (res.is_rewatch) this.addBadge(`Rewatch #${Math.max(1, (res.start_number || 2) - 1)}`, true);
    } catch {
      // playback still works; we just can't log this session
    }
  }

  logEvent(type) {
    if (!this.sessionId) return;
    api.post(`/api/playback/${this.sessionId}/event`, { type, position_sec: Math.round(this.currentTime()) }, { wake: false }).catch(() => {});
  }

  sendStop({ keepalive = false, completed } = {}) {
    if (!this.sessionId) return;
    const id = this.sessionId;
    this.sessionId = null;
    const position = Math.round(this.currentTime());
    const duration = Math.round(this.currentDuration());
    const done = completed ?? (this.ended || position >= duration * 0.95);
    api.post(`/api/playback/${id}/stop`, { position_sec: position, duration_sec: duration, completed: done }, { wake: false, keepalive }).catch(() => {});
  }

  currentTime() {
    if (this.useYouTube && this.yt?.getCurrentTime) { try { return this.yt.getCurrentTime() || 0; } catch { return 0; } }
    return this.position;
  }
  currentDuration() {
    if (this.useYouTube && this.yt?.getDuration) { try { return this.yt.getDuration() || this.duration; } catch { return this.duration; } }
    return this.duration;
  }

  // ---------- UI helpers ----------
  addBadge(text, accent = false) {
    this.$(".player__badges").appendChild(el(`<span class="player__badge ${accent ? "player__badge--accent" : ""}">${esc(text)}</span>`));
  }
  updateSubtitle() {
    const sub = this.$("[data-subtitle]");
    if (this.isSeries) sub.textContent = `Season 1, episode ${this.episode}`;
    else if (this.mode === "trailer") sub.textContent = "Official trailer";
    else sub.textContent = this.movie.year ? String(this.movie.year) : "";
  }
  flash(name) {
    const f = this.$(".player__flash");
    f.innerHTML = icon(name);
    f.classList.remove("is-on");
    void f.offsetWidth;
    f.classList.add("is-on");
  }
  wake() {
    this.root.classList.remove("is-idle");
    clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => { if (this.playing) this.root.classList.add("is-idle"); }, 2800);
  }
  onKey(e) {
    if (e.key === "Escape") { e.preventDefault(); this.close(); return; }
    if (this.useYouTube) return; // YouTube handles its own keys
    if (e.target.matches("input[type=range]") && (e.key === "ArrowLeft" || e.key === "ArrowRight")) return;
    if (e.key === " " || e.key === "k") { if (e.target.tagName === "BUTTON" && e.key === " ") return; e.preventDefault(); this.toggle(); }
    else if (e.key === "ArrowLeft" || e.key === "j") { e.preventDefault(); this.skip(-10); }
    else if (e.key === "ArrowRight" || e.key === "l") { e.preventDefault(); this.skip(10); }
    this.wake();
  }

  // ---------- simulated player ----------
  mountSimulated() {
    this.useYouTube = false;
    this.root.classList.remove("player--yt");
    this.$(".player__stage").innerHTML = `
      <div class="player__sim">${artHTML(this.movie, "backdrop", { eager: true })}</div>
      <div class="player__flicker"></div>
      <div class="player__titlecard is-on"><div>${esc(this.movie.title)}<small>${this.isSeries ? `Episode ${this.episode}` : this.movie.year || ""}</small></div></div>`;
    this.$(".player__bottom-slot").outerHTML = `
      <div class="player__bottom">
        <div class="player__bar">
          <span class="player__time" data-cur>0:00</span>
          <input type="range" class="range" data-scrub min="0" max="${Math.round(this.duration)}" step="1" value="0" aria-label="Seek">
          <span class="player__time" data-dur>${formatClock(this.duration)}</span>
        </div>
        <div class="player__buttons">
          <button type="button" class="icon-btn" data-act="back10" aria-label="Back 10 seconds">${icon("rewind10")}</button>
          <button type="button" class="icon-btn icon-btn--solid" data-act="toggle" aria-label="Pause">${icon("pause")}</button>
          <button type="button" class="icon-btn" data-act="fwd10" aria-label="Forward 10 seconds">${icon("forward10")}</button>
          ${this.isSeries ? `<button type="button" class="btn btn--glass btn--sm" data-act="next">${icon("skipNext")} Next episode</button>` : ""}
          <p class="player__note">Simulated playback at ${SIM_SPEED}× speed.<br>CineMatch recommends films; it doesn't stream them.</p>
        </div>
      </div>`;
    this.$('[data-act="toggle"]').addEventListener("click", (e) => { e.stopPropagation(); this.toggle(); });
    this.$('[data-act="back10"]').addEventListener("click", (e) => { e.stopPropagation(); this.skip(-10); });
    this.$('[data-act="fwd10"]').addEventListener("click", (e) => { e.stopPropagation(); this.skip(10); });
    this.$('[data-act="next"]')?.addEventListener("click", (e) => { e.stopPropagation(); this.nextEpisode(); });

    const scrub = this.$("[data-scrub]");
    let before = 0;
    let scrubbing = false;
    scrub.addEventListener("pointerdown", () => { scrubbing = true; before = this.position; });
    scrub.addEventListener("keydown", () => { if (!scrubbing) before = this.position; });
    scrub.addEventListener("input", () => {
      this.position = Number(scrub.value);
      this.ended = false;
      this.renderTime();
    });
    scrub.addEventListener("change", () => {
      scrubbing = false;
      const delta = this.position - before;
      if (Math.abs(delta) >= 2) this.logEvent(delta > 0 ? "seek_forward" : "seek_back");
    });

    this.play(true);
    this.lastTick = performance.now();
    const loop = (now) => {
      if (this.playing) {
        this.position += ((now - this.lastTick) / 1000) * SIM_SPEED;
        if (this.position >= this.duration) {
          this.position = this.duration;
          this.onEnded();
        }
      }
      this.lastTick = now;
      this.renderTime();
      this.raf = requestAnimationFrame(loop);
    };
    this.raf = requestAnimationFrame(loop);
    this.wake();
  }

  renderTime() {
    const scrub = this.$("[data-scrub]");
    if (!scrub) return;
    if (document.activeElement !== scrub || !scrub.matches(":active")) scrub.value = Math.round(this.position);
    scrub.style.setProperty("--p", `${(this.position / this.duration) * 100}%`);
    this.$("[data-cur]").textContent = formatClock(this.position);
    // title card shows for the first few real seconds of each episode/film
    this.$(".player__titlecard")?.classList.toggle("is-on", this.position < SIM_SPEED * 3.5);
  }

  play(initial = false) {
    if (this.ended && this.position >= this.duration) { this.position = 0; this.ended = false; }
    this.playing = true;
    this.root.classList.add("is-playing");
    const btn = this.$('[data-act="toggle"]');
    if (btn) { btn.innerHTML = icon("pause"); btn.setAttribute("aria-label", "Pause"); }
    if (!initial) { this.logEvent("resume"); this.flash("play"); }
  }
  pause() {
    this.playing = false;
    this.root.classList.remove("is-playing", "is-idle");
    const btn = this.$('[data-act="toggle"]');
    if (btn) { btn.innerHTML = icon("play"); btn.setAttribute("aria-label", "Play"); }
    this.logEvent("pause");
    this.flash("pause");
  }
  toggle() {
    if (this.useYouTube) return;
    this.hideCountdown();
    if (this.playing) this.pause(); else this.play();
  }
  skip(seconds) {
    if (this.useYouTube) return;
    const before = this.position;
    this.position = Math.max(0, Math.min(this.duration, this.position + seconds));
    this.ended = this.position >= this.duration;
    if (this.position !== before) {
      this.logEvent(seconds > 0 ? "seek_forward" : "seek_back");
      this.flash(seconds > 0 ? "forward10" : "rewind10");
    }
    this.renderTime();
  }

  onEnded() {
    if (this.ended) return;
    this.ended = true;
    this.playing = false;
    this.root.classList.remove("is-playing", "is-idle");
    const btn = this.$('[data-act="toggle"]');
    if (btn) { btn.innerHTML = icon("replay"); btn.setAttribute("aria-label", "Play again"); }
    if (this.isSeries) this.showCountdown();
  }

  // ---------- series: next-episode autoplay ----------
  showCountdown(seconds = 8) {
    this.hideCountdown();
    const r = 22;
    const c = 2 * Math.PI * r;
    const box = el(`
      <div class="next-ep" role="status">
        <div class="next-ep__ring"><svg viewBox="0 0 52 52"><circle cx="26" cy="26" r="${r}" fill="none" stroke="rgba(244,239,232,.15)" stroke-width="3"/>
          <circle cx="26" cy="26" r="${r}" fill="none" stroke="var(--accent)" stroke-width="3" stroke-linecap="round" stroke-dasharray="${c}" stroke-dashoffset="0"/></svg>
          <span data-n>${seconds}</span></div>
        <div class="next-ep__text"><strong>Episode ${this.episode + 1}</strong><span class="small dim">starts in <span data-n2>${seconds}</span> s</span></div>
        <div class="next-ep__actions">
          <button type="button" class="btn btn--play btn--sm" data-act="now">${icon("play")} Play now</button>
          <button type="button" class="btn btn--ghost btn--sm" data-act="cancel">Cancel</button>
        </div>
      </div>`);
    this.root.appendChild(box);
    this.countdownBox = box;
    const ring = box.querySelectorAll("circle")[1];
    let left = seconds;
    requestAnimationFrame(() => { ring.style.strokeDashoffset = String(c / seconds); });
    this.countdownTimer = setInterval(() => {
      left--;
      box.querySelector("[data-n]").textContent = left;
      box.querySelector("[data-n2]").textContent = left;
      ring.style.strokeDashoffset = String((c * (seconds - left + 1)) / seconds);
      if (left <= 0) this.nextEpisode();
    }, 1000);
    box.querySelector('[data-act="now"]').addEventListener("click", (e) => { e.stopPropagation(); this.nextEpisode(); });
    box.querySelector('[data-act="cancel"]').addEventListener("click", (e) => { e.stopPropagation(); this.hideCountdown(); });
    box.querySelector('[data-act="now"]').focus({ preventScroll: true });
  }
  hideCountdown() {
    clearInterval(this.countdownTimer);
    this.countdownBox?.remove();
    this.countdownBox = null;
  }

  async nextEpisode() {
    this.hideCountdown();
    this.sendStop({ completed: true });
    track("binge_next", { movie_id: this.movie.movie_id, request_id: this.source?.request_id, value: this.episode + 1 });
    this.episode++;
    this.position = 0;
    this.ended = false;
    this.updateSubtitle();
    const card = this.$(".player__titlecard");
    if (card) card.innerHTML = `<div>${esc(this.movie.title)}<small>Episode ${this.episode}</small></div>`;
    this.startSession();
    if (this.useYouTube) { try { this.yt.seekTo(0); this.yt.playVideo(); } catch { /* ignore */ } }
    else this.play(true);
  }

  // ---------- YouTube trailer ----------
  async mountYouTube() {
    this.root.classList.add("player--yt");
    this.$(".player__stage").innerHTML = `<div class="player__yt"><div data-yt></div></div>`;
    try {
      const YT = await loadYouTube();
      if (this.closed) return;
      let lastPos = 0;
      let lastAt = performance.now();
      let started = false;
      let paused = false;
      this.yt = new YT.Player(this.$("[data-yt]"), {
        videoId: this.movie.trailer_key,
        width: "100%",
        height: "100%",
        playerVars: { autoplay: 1, rel: 0, modestbranding: 1, playsinline: 1 },
        events: {
          onReady: (e) => { e.target.playVideo(); },
          onError: () => this.fallbackToSimulated(),
          onStateChange: (e) => {
            if (e.data === YT.PlayerState.PLAYING) {
              if (started && paused) this.logEvent("resume");
              started = true;
              paused = false;
              this.playing = true;
            } else if (e.data === YT.PlayerState.PAUSED) {
              if (!paused) this.logEvent("pause");
              paused = true;
              this.playing = false;
            } else if (e.data === YT.PlayerState.ENDED) {
              this.playing = false;
              this.ended = true;
              if (this.isSeries) this.showCountdown();
            }
          },
        },
      });
      // Seek detection: compare where the video is with where it should be.
      this.ytPoll = setInterval(() => {
        if (!this.yt?.getCurrentTime) return;
        let now;
        try { now = this.yt.getCurrentTime(); } catch { return; }
        const t = performance.now();
        const expected = lastPos + (this.playing ? (t - lastAt) / 1000 : 0);
        if (started && Math.abs(now - expected) > 2.5) this.logEvent(now > expected ? "seek_forward" : "seek_back");
        lastPos = now;
        lastAt = t;
      }, 500);
    } catch {
      this.fallbackToSimulated();
    }
  }

  fallbackToSimulated() {
    if (this.closed || !this.useYouTube) return;
    clearInterval(this.ytPoll);
    try { this.yt?.destroy(); } catch { /* ignore */ }
    this.yt = null;
    toast("The trailer couldn't load here, so here's a simulated preview instead.");
    this.mountSimulated();
  }
}
