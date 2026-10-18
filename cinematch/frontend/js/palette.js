// ============================================================================
// CineMatch — palette.js
// Every film gets a colour palette. It comes from one of two places:
//   (a) the real poster/backdrop image: we draw it small on an offscreen
//       <canvas>, read the pixels and pick a dominant + vibrant colours;
//   (b) when there is no image (or it can't be read): a palette built from
//       the film's genres, mood tags and start/end emotion.
// Palettes are cached per movie, so each one is only worked out once.
//
// A palette looks like:
//   { c1, c2, c3, c4,   // four glow colours for the ambient blobs
//     deep,             // the near-black base, tinted with the film's hue
//     accent,           // a light, readable accent for UI text/focus rings
//     paper, ink }      // light "paper" + dark "ink" for generated posters
// ============================================================================

import { seededRandom } from "./utils.js";

// ---- Colour maths -------------------------------------------------------------------
export function hexToRgb(hex) {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
export function rgbToHex(r, g, b) {
  return `#${[r, g, b].map((v) => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, "0")).join("")}`;
}
export function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  let h = 0;
  let s = 0;
  const l = (max + min) / 2;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
    else if (max === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60;
  }
  return [h, s, l];
}
export function hslToHex(h, s, l) {
  h = ((h % 360) + 360) % 360;
  const k = (n) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return rgbToHex(f(0) * 255, f(8) * 255, f(4) * 255);
}
export const hexToHsl = (hex) => rgbToHsl(...hexToRgb(hex));
export function mix(a, b, t = 0.5) {
  const x = hexToRgb(a);
  const y = hexToRgb(b);
  return rgbToHex(x[0] + (y[0] - x[0]) * t, x[1] + (y[1] - x[1]) * t, x[2] + (y[2] - x[2]) * t);
}
export function withAlpha(hex, alpha) {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}
/** Re-tune a colour's saturation / lightness into a range (keeps its hue). */
function tune(hex, { sMin = 0, sMax = 1, lMin = 0, lMax = 1 } = {}) {
  const [h, s, l] = hexToHsl(hex);
  return hslToHex(h, Math.min(sMax, Math.max(sMin, s)), Math.min(lMax, Math.max(lMin, l)));
}

// ---- (b) Palettes from genres / moods / emotions ---------------------------------------
// Each genre has a pair of colours. Chosen to stay rich but not neon.
export const GENRE_COLORS = {
  Horror: ["#b3122e", "#3a0612"],
  Romance: ["#e0457b", "#9c2f8f"],
  "Sci-Fi": ["#22b8d1", "#6c4be0"],
  Comedy: ["#f2a93b", "#ef6a55"],
  Animation: ["#ff7ab6", "#5fc8f5", "#ffd166"],
  Children: ["#7ccf5a", "#ffc94a"],
  Drama: ["#3d4fb0", "#1f8c88"],
  Thriller: ["#4a6fa5", "#c8323a"],
  Fantasy: ["#7b3fc4", "#d9a441"],
  Crime: ["#b08d57", "#3a3226"],
  "Film-Noir": ["#9c8256", "#3c3c46"],
  Documentary: ["#8da88a", "#d2b48c"],
  Action: ["#f26b1d", "#3e5c76"],
  Adventure: ["#2fa36b", "#f08a3c"],
  Mystery: ["#16757a", "#5b2a6e"],
  War: ["#76794a", "#9a4a2a"],
  Western: ["#c98b4e", "#8a3b1f"],
  Musical: ["#d6339a", "#f2c14e"],
  IMAX: ["#2f6bff", "#22b8d1"],
};

export const EMOTION_COLORS = {
  joy: "#f2b544", sadness: "#4f78db", fear: "#9b2c4a", anger: "#e0533a",
  surprise: "#2fc1d6", disgust: "#8a9a34", neutral: "#8a96ab",
};

const MOOD_COLORS = {
  "feel-good": "#f2b544", dark: "#3b2650", cozy: "#d98a4a", thrilling: "#d0353f", romantic: "#e0457b",
  "mind-bending": "#7a4cf0", epic: "#d9a441", heartwarming: "#f0846c", scary: "#8c0f1f", funny: "#f39a3c",
  inspiring: "#3fb6a8", melancholic: "#4f6a8f", "action-packed": "#f26b1d", family: "#7ccf5a",
  "slow-burn": "#a0522d", light: "#ffd27a",
};

const DEFAULT_PALETTE = buildPalette(["#5a3fcf", "#1d8a88", "#b23a6c", "#c99a3e"]);
export const defaultPalette = () => DEFAULT_PALETTE;

/** Turn 4 raw colours into a complete, "premium" palette. */
export function buildPalette(colors) {
  const [a, b = a, c = b, d = a] = colors;
  // glow colours: saturated enough to feel colourful, never neon
  const glow = (hex) => tune(hex, { sMin: 0.38, sMax: 0.8, lMin: 0.36, lMax: 0.58 });
  const c1 = glow(a);
  const c2 = glow(b);
  const c3 = glow(c);
  const c4 = glow(d);
  const [h1, s1] = hexToHsl(c1);
  // pick the most saturated colour as the readable accent, lifted to ~72% lightness
  const vivid = [c1, c2, c3, c4].sort((x, y) => hexToHsl(y)[1] - hexToHsl(x)[1])[0];
  const [ha, sa] = hexToHsl(vivid);
  return {
    c1, c2, c3, c4,
    deep: hslToHex(h1, Math.min(0.45, s1 * 0.6), 0.055),
    accent: hslToHex(ha, Math.min(0.9, Math.max(0.6, sa)), 0.74),
    paper: hslToHex(hexToHsl(c2)[0], 0.32, 0.88),
    ink: hslToHex(h1, 0.35, 0.09),
  };
}

const fallbackCache = new Map();

/** Palette from genres + mood tags + emotions (deterministic per movie). */
export function fallbackPalette(movie) {
  if (!movie) return DEFAULT_PALETTE;
  const key = movie.movie_id;
  if (fallbackCache.has(key)) return fallbackCache.get(key);

  const rand = seededRandom((Number(movie.movie_id) || 1) * 2654435761);
  const genres = (movie.genres || []).filter((g) => GENRE_COLORS[g]);
  const g1 = GENRE_COLORS[genres[0]] || GENRE_COLORS.Drama;
  const g2 = GENRE_COLORS[genres[1]] || g1;
  const moods = movie.mood_tags || [];
  // nudge each hue a little so two dramas don't look identical
  const jitter = (hex) => {
    const [h, s, l] = hexToHsl(hex);
    return hslToHex(h + (rand() - 0.5) * 40, s, l + (rand() - 0.5) * 0.08);
  };
  const raw = [
    jitter(g1[0]),
    jitter(g2 === g1 ? g1[1] : g2[0]),
    jitter(EMOTION_COLORS[movie.end_emotion] && movie.end_emotion !== "neutral" ? mix(EMOTION_COLORS[movie.end_emotion], g1[1], 0.25) : g1[1]),
    jitter(MOOD_COLORS[moods[0]] || EMOTION_COLORS[movie.start_emotion] || g2[1] || g1[0]),
  ];
  // "dark" films get a darker, moodier set
  if (moods.includes("dark") || moods.includes("scary")) {
    raw[1] = mix(raw[1], "#1a1022", 0.35);
    raw[3] = mix(raw[3], "#1a1022", 0.3);
  }
  const pal = buildPalette(raw);
  fallbackCache.set(key, pal);
  return pal;
}

// ---- (a) Palettes extracted from real images --------------------------------------------
const imageCache = new Map(); // url -> Promise<palette|null>

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = "anonymous"; // TMDB sends CORS headers, so the canvas stays readable
    img.decoding = "async";
    const timer = setTimeout(() => reject(new Error("timeout")), 6000);
    img.onload = () => { clearTimeout(timer); resolve(img); };
    img.onerror = () => { clearTimeout(timer); reject(new Error("load failed")); };
    img.src = url;
  });
}

/**
 * Read an image's colours. Buckets pixels by hue/saturation/lightness, then picks:
 * the dominant colourful bucket, the most vibrant one, and two more with different hues.
 * Returns null if the image can't be read (e.g. CORS) — callers fall back to genres.
 */
export function extractPalette(url) {
  if (!url) return Promise.resolve(null);
  if (imageCache.has(url)) return imageCache.get(url);
  const job = (async () => {
    try {
      const img = await loadImage(url);
      const W = 48;
      const H = Math.max(24, Math.round((img.naturalHeight / img.naturalWidth) * W)) || 48;
      const canvas = document.createElement("canvas");
      canvas.width = W; canvas.height = H;
      const ctx = canvas.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0, W, H);
      const { data } = ctx.getImageData(0, 0, W, H); // throws if the canvas is "tainted"
      const buckets = new Map();
      for (let i = 0; i < data.length; i += 4) {
        if (data[i + 3] < 128) continue;
        const [h, s, l] = rgbToHsl(data[i], data[i + 1], data[i + 2]);
        if (l < 0.08 || l > 0.94) continue; // ignore near-black / near-white
        const key = `${Math.round(h / 24)}-${s > 0.45 ? 2 : s > 0.2 ? 1 : 0}-${l > 0.6 ? 2 : l > 0.32 ? 1 : 0}`;
        const b = buckets.get(key) || { n: 0, r: 0, g: 0, b: 0 };
        b.n++; b.r += data[i]; b.g += data[i + 1]; b.b += data[i + 2];
        buckets.set(key, b);
      }
      const colours = [...buckets.values()].map((b) => {
        const hex = rgbToHex(b.r / b.n, b.g / b.n, b.b / b.n);
        const [h, s, l] = hexToHsl(hex);
        return { hex, h, s, l, n: b.n, vib: Math.sqrt(b.n) * s * (1 - Math.abs(l - 0.5) * 1.4) };
      });
      if (!colours.length) return null;
      const dominant = [...colours].sort((a, b) => b.n * (0.3 + b.s) - a.n * (0.3 + a.s))[0];
      const byVibrance = [...colours].sort((a, b) => b.vib - a.vib);
      const picked = [dominant];
      for (const c of byVibrance) {
        if (picked.length >= 4) break;
        if (picked.every((p) => Math.min(Math.abs(p.h - c.h), 360 - Math.abs(p.h - c.h)) > 28 || Math.abs(p.l - c.l) > 0.3)) picked.push(c);
      }
      while (picked.length < 4) picked.push(byVibrance[picked.length % byVibrance.length] || dominant);
      // put the most vibrant first so the strongest glow sits top-left
      const [first, ...rest] = picked;
      return buildPalette([byVibrance[0]?.hex || first.hex, first.hex, ...rest.map((c) => c.hex)].slice(0, 4));
    } catch {
      return null; // CORS blocked, offline, or decode error
    }
  })();
  imageCache.set(url, job);
  return job;
}

const movieCache = new Map(); // movie_id -> palette

/** Synchronous best guess (cached image palette if we already have it, else genres). */
export function paletteNow(movie) {
  return movieCache.get(movie?.movie_id) || fallbackPalette(movie);
}

/** Best palette for a movie: image colours when possible, otherwise genre colours. */
export async function moviePalette(movie) {
  if (!movie) return DEFAULT_PALETTE;
  if (movieCache.has(movie.movie_id)) return movieCache.get(movie.movie_id);
  const url = movie.backdrop_url || movie.poster_url;
  let pal = null;
  if (url) pal = await extractPalette(url.replace("/w1280/", "/w300/").replace("/w342/", "/w185/"));
  pal = pal || fallbackPalette(movie);
  movieCache.set(movie.movie_id, pal);
  return pal;
}
