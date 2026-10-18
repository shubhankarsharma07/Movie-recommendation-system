// ============================================================================
// CineMatch — posters.js
// Generated poster + backdrop art for titles without images.
//
// Each film gets a deterministic minimalist poster (think A24 / Criterion):
//   * a composition chosen from its main genre's set (sun, orbit, shards,
//     bands, blobs, arch, ridges, grid, colour fields, halftone dots) and
//     seeded by movie_id, so the same film always looks the same,
//   * colours from palette.js (the same colours the ambient background uses),
//   * the title set in a typeface that suits the genre, plus a small billing
//     line with the year and genres.
// Backdrops (16:9) use the same composition without text.
// Results are cached as SVG strings.
// ============================================================================

import { paletteNow, mix, hexToHsl, hslToHex } from "./palette.js";
import { seededRandom, esc } from "./utils.js";

const svgCache = new Map();
const registry = new Map(); // movie_id -> movie, so a broken <img> can fall back to generated art

// Which compositions each genre can use (one is picked per film by its seed) and its typeface
const COMPOSITION = {
  Horror: ["shards", "fields"], Thriller: ["shards", "bands", "fields"], Crime: ["shards", "fields", "grid"], "Film-Noir": ["shards", "fields"],
  "Sci-Fi": ["orbit", "dots", "orbit"], Mystery: ["orbit", "fields", "shards"], IMAX: ["orbit"],
  Action: ["bands", "shards"], War: ["bands", "ridges"],
  Adventure: ["ridges", "sun", "dots"], Western: ["sun", "ridges"], Documentary: ["grid", "ridges", "dots"],
  Drama: ["sun", "fields", "arch", "dots"], Romance: ["arch", "fields", "blobs", "sun"], Musical: ["arch", "dots", "blobs"], Fantasy: ["arch", "ridges", "orbit"],
  Comedy: ["blobs", "dots", "grid"], Animation: ["blobs", "dots", "ridges"], Children: ["blobs", "dots"],
};
const TYPE = {
  Action: "condensed", Thriller: "condensed", Horror: "condensed", Crime: "condensed", War: "condensed", Western: "condensed", "Film-Noir": "condensed",
  "Sci-Fi": "wide", Mystery: "wide", Documentary: "wide", IMAX: "wide",
  Romance: "serifItalic", Drama: "serifItalic", Musical: "serifItalic",
  Fantasy: "serifBold", Adventure: "serifBold", Comedy: "serifBold", Animation: "serifBold", Children: "serifBold",
};
const LIGHT_FRIENDLY = new Set(["Comedy", "Animation", "Children", "Documentary", "Romance", "Musical", "Drama"]);

const TYPE_STYLES = {
  condensed:   { family: "'League Gothic', 'Arial Narrow', Impact, sans-serif", weight: 400, italic: false, upper: true, size: 46, factor: 0.4, tracking: 0.6, lh: 0.9, align: "start" },
  wide:        { family: "'Hanken Grotesk', system-ui, sans-serif", weight: 300, italic: false, upper: true, size: 15, factor: 0.82, tracking: 3.6, lh: 1.4, align: "middle" },
  serifItalic: { family: "'Bodoni Moda', Didot, Georgia, serif", weight: 500, italic: true, upper: false, size: 30, factor: 0.48, tracking: -0.3, lh: 1.02, align: "middle" },
  serifBold:   { family: "'Bodoni Moda', Didot, Georgia, serif", weight: 700, italic: false, upper: false, size: 28, factor: 0.55, tracking: -0.4, lh: 1.02, align: "start" },
};

const fmt = (n) => Math.round(n * 10) / 10;
const pick = (rand, list) => list[Math.floor(rand() * list.length) % list.length];
const lighten = (hex, amount) => { const [h, s, l] = hexToHsl(hex); return hslToHex(h, s, Math.min(0.92, l + amount)); };

// ---- Compositions ---------------------------------------------------------------------
// Each returns { defs, body } SVG strings. o = { W, H, p, r, id, light, fx, fy }

function sun(o) {
  const { W, H, p, r, id, light } = o;
  const cx = W * o.fx;
  const cy = H * o.fy;
  const R = Math.min(W, H) * (0.19 + r() * 0.09);
  const horizon = cy + R * (0.3 + r() * 0.35);
  const skyTop = light ? p.paper : mix(p.deep, p.c2, 0.32);
  const skyBot = light ? mix(p.paper, p.c3, 0.3) : mix(p.deep, p.c1, 0.55);
  const ground = light ? mix(p.paper, p.c3, 0.38) : mix(p.deep, "#000", 0.25);
  let stripes = "";
  for (let i = 0; i < 8; i++) {
    const w = R * 2 * (1 - i * 0.1) * (0.9 + r() * 0.15);
    const y = horizon + 4 + i * ((H - horizon) / 10);
    stripes += `<rect x="${fmt(cx - w / 2)}" y="${fmt(y)}" width="${fmt(w)}" height="${fmt(1 + i * 0.35)}" fill="${p.c4}" opacity="${fmt(0.75 - i * 0.08)}"/>`;
  }
  return {
    defs: `<linearGradient id="${id}s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${skyTop}"/><stop offset="1" stop-color="${skyBot}"/></linearGradient>
      <linearGradient id="${id}o" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${lighten(p.c4, 0.12)}"/><stop offset="1" stop-color="${p.c1}"/></linearGradient>
      <radialGradient id="${id}g"><stop offset="0" stop-color="${p.c3}" stop-opacity=".55"/><stop offset="1" stop-color="${p.c3}" stop-opacity="0"/></radialGradient>`,
    body: `<rect width="${W}" height="${H}" fill="url(#${id}s)"/>
      <circle cx="${fmt(cx)}" cy="${fmt(cy)}" r="${fmt(R * 2.6)}" fill="url(#${id}g)"/>
      <circle cx="${fmt(cx)}" cy="${fmt(cy)}" r="${fmt(R)}" fill="url(#${id}o)"/>
      <rect y="${fmt(horizon)}" width="${W}" height="${fmt(H - horizon)}" fill="${ground}"/>
      ${stripes}`,
  };
}

function orbit(o) {
  const { W, H, p, r, id, light } = o;
  const cx = W * o.fx;
  const cy = H * o.fy;
  const R = Math.min(W, H) * 0.27;
  const angle = -25 + r() * 50;
  let rings = "";
  const n = 5 + Math.floor(r() * 3);
  for (let i = 0; i < n; i++) {
    const rx = R * (0.62 + i * 0.34);
    rings += `<ellipse cx="${fmt(cx)}" cy="${fmt(cy)}" rx="${fmt(rx)}" ry="${fmt(rx * (0.26 + r() * 0.08))}" fill="none" stroke="${i % 2 ? p.c1 : p.c3}" stroke-width="${fmt(0.6 + r() * 0.9)}" opacity="${fmt(0.62 - i * 0.06)}" transform="rotate(${fmt(angle)} ${fmt(cx)} ${fmt(cy)})"/>`;
  }
  let stars = "";
  for (let i = 0; i < 34; i++) {
    stars += `<circle cx="${fmt(r() * W)}" cy="${fmt(r() * H)}" r="${fmt(0.3 + r() * 0.8)}" fill="${light ? p.ink : "#fff"}" opacity="${fmt(0.15 + r() * 0.6)}"/>`;
  }
  const pr = R * (0.36 + r() * 0.12);
  return {
    defs: `<radialGradient id="${id}b" cx="${o.fx}" cy="${o.fy}" r="0.85"><stop offset="0" stop-color="${light ? mix(p.paper, p.c2, 0.25) : mix(p.deep, p.c2, 0.5)}"/><stop offset="1" stop-color="${light ? p.paper : p.deep}"/></radialGradient>
      <linearGradient id="${id}p" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${lighten(p.c4, 0.1)}"/><stop offset="1" stop-color="${p.c2}"/></linearGradient>
      <clipPath id="${id}c"><circle cx="${fmt(cx)}" cy="${fmt(cy)}" r="${fmt(pr)}"/></clipPath>`,
    body: `<rect width="${W}" height="${H}" fill="url(#${id}b)"/>${stars}${rings}
      <circle cx="${fmt(cx)}" cy="${fmt(cy)}" r="${fmt(pr)}" fill="url(#${id}p)"/>
      <circle cx="${fmt(cx + pr * 0.45)}" cy="${fmt(cy - pr * 0.3)}" r="${fmt(pr * 1.05)}" fill="${p.deep}" opacity=".55" clip-path="url(#${id}c)"/>`,
  };
}

function shards(o) {
  const { W, H, p, r, id } = o;
  const cx = W * o.fx;
  const cy = H * o.fy;
  const S = Math.min(W, H);
  let polys = "";
  const fills = [p.c1, p.c2, p.c4, p.c3];
  const n = 4 + Math.floor(r() * 3);
  for (let i = 0; i < n; i++) {
    const a = r() * Math.PI * 2;
    const len = S * (0.35 + r() * 0.55);
    const x1 = cx + Math.cos(a) * len;
    const y1 = cy + Math.sin(a) * len;
    const x2 = cx + Math.cos(a + 0.18 + r() * 0.35) * len * (0.5 + r() * 0.6);
    const y2 = cy + Math.sin(a + 0.18 + r() * 0.35) * len * (0.5 + r() * 0.6);
    polys += `<polygon points="${fmt(cx)},${fmt(cy)} ${fmt(x1)},${fmt(y1)} ${fmt(x2)},${fmt(y2)}" fill="${fills[i % 4]}" opacity="${fmt(0.35 + r() * 0.55)}"/>`;
  }
  const sx = W * (0.15 + r() * 0.7);
  const slash = `<polygon points="${fmt(sx)},0 ${fmt(sx + 3)},0 ${fmt(sx - W * 0.35 + 3)},${H} ${fmt(sx - W * 0.35)},${H}" fill="${lighten(p.c1, 0.18)}" opacity=".9"/>`;
  return {
    defs: `<linearGradient id="${id}b" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${mix(p.deep, "#000", 0.3)}"/><stop offset="1" stop-color="${mix(p.deep, p.c1, 0.3)}"/></linearGradient>`,
    body: `<rect width="${W}" height="${H}" fill="url(#${id}b)"/>${polys}${slash}
      <circle cx="${fmt(cx)}" cy="${fmt(cy)}" r="${fmt(S * 0.035)}" fill="${lighten(p.c1, 0.25)}"/>`,
  };
}

function bands(o) {
  const { W, H, p, r, id } = o;
  const angle = -28 + r() * 14;
  const fills = [p.c1, p.c3, p.deep, p.c4, p.c2];
  let rects = "";
  const n = 7;
  const step = (W * 2.2) / n;
  for (let i = 0; i < n; i++) {
    const w = step * (0.3 + r() * 0.55);
    rects += `<rect x="${fmt(-W * 0.6 + i * step)}" y="${fmt(-H)}" width="${fmt(w)}" height="${fmt(H * 3)}" fill="${fills[i % fills.length]}" opacity="${fmt(0.7 + r() * 0.3)}"/>`;
  }
  let lines = "";
  for (let i = 0; i < 6; i++) {
    const y = r() * H;
    lines += `<line x1="${fmt(r() * W * 0.4)}" y1="${fmt(y)}" x2="${fmt(W * (0.6 + r() * 0.4))}" y2="${fmt(y)}" stroke="#fff" stroke-width=".5" opacity=".18"/>`;
  }
  return {
    defs: "",
    body: `<rect width="${W}" height="${H}" fill="${mix(p.deep, p.c2, 0.3)}"/>
      <g transform="rotate(${fmt(angle)} ${W / 2} ${H / 2})">${rects}</g>${lines}`,
  };
}

function blobs(o) {
  const { W, H, p, r, light } = o;
  const S = Math.min(W, H);
  const fills = [p.c2, p.c3, p.c4, p.c1];
  let circles = "";
  for (let i = 0; i < 4; i++) {
    const cx = W * o.fx + (r() - 0.5) * W * 0.6;
    const cy = H * o.fy + (r() - 0.5) * H * 0.45;
    circles += `<circle cx="${fmt(cx)}" cy="${fmt(cy)}" r="${fmt(S * (0.17 + r() * 0.2))}" fill="${fills[i]}" opacity=".88" style="mix-blend-mode:${light ? "multiply" : "screen"}"/>`;
  }
  // a playful squiggle
  const y0 = H * (0.12 + r() * 0.2);
  let d = `M ${fmt(W * 0.08)} ${fmt(y0)}`;
  for (let i = 1; i <= 6; i++) d += ` Q ${fmt(W * 0.08 + (i - 0.5) * W * 0.14)} ${fmt(y0 + (i % 2 ? -1 : 1) * S * 0.05)} ${fmt(W * 0.08 + i * W * 0.14)} ${fmt(y0)}`;
  return {
    defs: "",
    body: `<rect width="${W}" height="${H}" fill="${light ? p.paper : mix(p.deep, p.c1, 0.35)}"/>${circles}
      <path d="${d}" fill="none" stroke="${light ? p.ink : "#f4efe8"}" stroke-width="${fmt(S * 0.012)}" stroke-linecap="round" opacity=".8"/>`,
  };
}

function arch(o) {
  const { W, H, p, r, id, light } = o;
  const cx = W * o.fx;
  const w = Math.min(W * 0.56, H * 0.52);
  const top = H * o.fy - w * 0.55;
  const ya = top + w / 2;
  const yb = Math.min(H * 0.98, top + w * 1.45);
  const x0 = cx - w / 2;
  const x1 = cx + w / 2;
  const path = (dx) => `M ${fmt(x0 - dx)} ${fmt(yb)} V ${fmt(ya)} A ${fmt(w / 2 + dx)} ${fmt(w / 2 + dx)} 0 0 1 ${fmt(x1 + dx)} ${fmt(ya)} V ${fmt(yb)}`;
  let waves = "";
  for (let i = 0; i < 6; i++) {
    const y = ya + w * 0.45 + i * w * 0.08;
    waves += `<line x1="${fmt(x0)}" y1="${fmt(y)}" x2="${fmt(x1)}" y2="${fmt(y)}" stroke="${p.deep}" stroke-width="${fmt(0.8 + i * 0.25)}" opacity="${fmt(0.25 + i * 0.08)}"/>`;
  }
  return {
    defs: `<linearGradient id="${id}a" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${p.c1}"/><stop offset=".65" stop-color="${p.c3}"/><stop offset="1" stop-color="${p.c4}"/></linearGradient>
      <clipPath id="${id}k"><path d="${path(0)} Z"/></clipPath>`,
    body: `<rect width="${W}" height="${H}" fill="${light ? p.paper : p.deep}"/>
      <path d="${path(0)} Z" fill="url(#${id}a)"/>
      <g clip-path="url(#${id}k)">${waves}<circle cx="${fmt(cx + (r() - 0.5) * w * 0.3)}" cy="${fmt(ya + w * 0.05)}" r="${fmt(w * 0.14)}" fill="${light ? "#fffaf0" : lighten(p.c4, 0.25)}" opacity=".95"/></g>
      <path d="${path(w * 0.07)}" fill="none" stroke="${light ? p.ink : p.c3}" stroke-width=".8" opacity=".5"/>`,
  };
}

function ridges(o) {
  const { W, H, p, r, id, light } = o;
  let layers = "";
  for (let i = 0; i < 4; i++) {
    const base = H * (0.48 + i * 0.12);
    let pts = `-5,${H} `;
    let y = base - r() * H * 0.08;
    for (let x = -5; x <= W + 5; x += W / 10) {
      y = Math.max(H * 0.25, Math.min(H, y + (r() - 0.5) * H * 0.12));
      pts += `${fmt(x)},${fmt(y)} `;
    }
    pts += `${W + 5},${H}`;
    layers += `<polygon points="${pts}" fill="${light ? mix(p.c1, p.ink, 0.15 + i * 0.22) : mix(p.c1, p.deep, 0.2 + i * 0.25)}"/>`;
  }
  return {
    defs: `<linearGradient id="${id}s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${light ? p.paper : mix(p.deep, p.c2, 0.45)}"/><stop offset="1" stop-color="${p.c3}"/></linearGradient>`,
    body: `<rect width="${W}" height="${H}" fill="url(#${id}s)"/>
      <circle cx="${fmt(W * o.fx)}" cy="${fmt(H * Math.min(0.32, o.fy))}" r="${fmt(Math.min(W, H) * 0.11)}" fill="${lighten(p.c4, 0.15)}"/>${layers}`,
  };
}

function grid(o, movie) {
  const { W, H, p, r, light, poster } = o;
  const ink = light ? p.ink : "#f4efe8";
  let lines = "";
  for (let x = W / 6; x < W; x += W / 6) lines += `<line x1="${fmt(x)}" y1="0" x2="${fmt(x)}" y2="${H}" stroke="${ink}" stroke-width=".4" opacity=".1"/>`;
  for (let y = H / 9; y < H; y += H / 9) lines += `<line x1="0" y1="${fmt(y)}" x2="${W}" y2="${fmt(y)}" stroke="${ink}" stroke-width=".4" opacity=".1"/>`;
  // posters: numerals in the upper half (the title sits below); backdrops: numerals on the right
  const size = poster ? Math.min(W * 0.5, H * 0.34) : H * 0.62;
  const tx = poster ? W * 0.07 : W * 0.5;
  const ty = poster ? H * 0.5 : H * 0.86;
  const cx = poster ? W * (0.66 + r() * 0.12) : W * (0.8 + r() * 0.08);
  const cy = poster ? H * 0.2 : H * 0.28;
  return {
    defs: "",
    body: `<rect width="${W}" height="${H}" fill="${light ? p.paper : p.deep}"/>${lines}
      <circle cx="${fmt(cx)}" cy="${fmt(cy)}" r="${fmt(Math.min(W, H) * (poster ? 0.15 : 0.13))}" fill="${p.c2}" opacity=".9"/>
      <text x="${fmt(tx)}" y="${fmt(ty)}" font-family="'League Gothic', 'Arial Narrow', Impact, sans-serif" font-size="${fmt(size)}" fill="${p.c1}" opacity=".92">${esc(movie.year || "")}</text>`,
  };
}

/** Colour fields: two or three soft-edged blocks, like a Rothko canvas. */
function fields(o) {
  const { W, H, p, r, id, light, poster } = o;
  const x0 = poster ? W * 0.1 : W * 0.44;
  const x1 = poster ? W * 0.9 : W * 0.93;
  const top = H * (poster ? 0.07 : 0.1);
  const bottom = H * (poster ? 0.64 : 0.9);
  const n = 2 + Math.floor(r() * 2);
  const gap = H * 0.025;
  const weights = Array.from({ length: n }, () => 0.6 + r());
  const total = weights.reduce((a, b) => a + b, 0);
  const fills = light ? [p.c1, p.c3, p.c2] : [p.c1, p.c3, p.c4];
  let y = top;
  let blocks = "";
  weights.forEach((w, i) => {
    const h = ((bottom - top - gap * (n - 1)) * w) / total;
    blocks += `<rect x="${fmt(x0)}" y="${fmt(y)}" width="${fmt(x1 - x0)}" height="${fmt(h)}" rx="2" fill="${fills[i % fills.length]}" opacity="${fmt(0.82 + r() * 0.15)}" filter="url(#${id}f)"/>`;
    y += h + gap;
  });
  return {
    defs: `<filter id="${id}f" x="-10%" y="-10%" width="120%" height="120%"><feGaussianBlur stdDeviation="${fmt(Math.min(W, H) * 0.008)}"/></filter>`,
    body: `<rect width="${W}" height="${H}" fill="${light ? p.paper : mix(p.deep, p.c2, 0.22)}"/>${blocks}`,
  };
}

/** Halftone dots that swell toward a focal point. */
function dots(o) {
  const { W, H, p, r, light, poster } = o;
  const step = Math.min(W, H) / (poster ? 12 : 17);
  const cx = W * o.fx;
  const cy = poster ? H * 0.3 : H * o.fy;
  const R = Math.min(W, H) * (poster ? 0.36 + r() * 0.08 : 0.42 + r() * 0.12);
  let out = "";
  for (let y = step / 2; y < H; y += step) {
    for (let x = step / 2; x < W; x += step) {
      const d = Math.hypot(x - cx, y - cy) / R;
      if (d > 1.05) continue;
      const rad = step * 0.48 * Math.pow(Math.max(0, 1 - d), 0.7);
      if (rad < 0.4) continue;
      out += `<circle cx="${fmt(x)}" cy="${fmt(y)}" r="${fmt(rad)}" fill="${mix(p.c1, p.c3, Math.min(1, d))}"/>`;
    }
  }
  const sx = W * (o.fx + (r() - 0.5) * 0.5);
  const sy = cy + Math.min(W, H) * (0.18 + r() * 0.1);
  return {
    defs: "",
    body: `<rect width="${W}" height="${H}" fill="${light ? p.paper : p.deep}"/>${out}
      <circle cx="${fmt(sx)}" cy="${fmt(sy)}" r="${fmt(Math.min(W, H) * 0.09)}" fill="${p.c4}" opacity=".9" style="mix-blend-mode:${light ? "multiply" : "screen"}"/>`,
  };
}

const COMPOSERS = { sun, orbit, shards, bands, blobs, arch, ridges, grid, fields, dots };

// ---- Title typesetting -------------------------------------------------------------------
function wrap(text, maxChars) {
  const words = text.split(/\s+/);
  const lines = [];
  let line = "";
  for (const word of words) {
    if (!line) line = word;
    else if ((line + " " + word).length <= maxChars) line += " " + word;
    else { lines.push(line); line = word; }
  }
  if (line) lines.push(line);
  return lines;
}

function titleBlock(movie, o, styleName, rand) {
  const { W, H, p, light } = o;
  const st = TYPE_STYLES[styleName];
  const pad = W * 0.085;
  const maxW = W - pad * 2;
  const text = st.upper ? movie.title.toUpperCase() : movie.title;
  let size = st.size;
  let lines = [];
  for (let attempt = 0; attempt < 6; attempt++) {
    const charW = size * st.factor + st.tracking;
    const maxChars = Math.max(4, Math.floor(maxW / charW));
    lines = wrap(text, maxChars);
    const longest = Math.max(...lines.map((l) => l.length));
    const maxLines = styleName === "condensed" || text.length > 28 ? 4 : 3;
    if (lines.length <= maxLines && longest <= maxChars) break;
    size *= 0.86;
  }
  const align = st.align === "middle" ? "middle" : rand() < 0.75 ? "start" : "middle";
  const x = align === "middle" ? W / 2 : pad;
  const lineH = size * st.lh;
  const bottom = H * 0.86;
  const firstY = bottom - (lines.length - 1) * lineH;
  const color = light ? p.ink : "#f6f1ea";
  const tspans = lines.map((l, i) => `<tspan x="${fmt(x)}" y="${fmt(firstY + i * lineH)}">${esc(l)}</tspan>`).join("");
  const genres = (movie.genres || []).slice(0, 2).join("  ").toUpperCase();
  const scrim = light ? "" : `<rect y="${fmt(H * 0.5)}" width="${W}" height="${fmt(H * 0.5)}" fill="url(#${o.id}t)"/>`;
  return {
    defs: light ? "" : `<linearGradient id="${o.id}t" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${p.deep}" stop-opacity="0"/><stop offset="1" stop-color="${mix(p.deep, "#000", 0.4)}" stop-opacity=".88"/></linearGradient>`,
    body: `${scrim}
      <text text-anchor="${align}" font-family="${st.family}" font-weight="${st.weight}" ${st.italic ? 'font-style="italic"' : ""} font-size="${fmt(size)}" letter-spacing="${st.tracking}" fill="${color}">${tspans}</text>
      <g font-family="'Hanken Grotesk', system-ui, sans-serif" font-size="6.4" font-weight="600" letter-spacing="1.3" fill="${color}" opacity=".66">
        <text x="${fmt(pad)}" y="${fmt(H * 0.945)}">${esc(movie.year || "")}</text>
        <text x="${fmt(W - pad)}" y="${fmt(H * 0.945)}" text-anchor="end">${esc(movie.content_type === "series" ? "SERIES" : genres)}</text>
      </g>`,
  };
}

// ---- Public API ------------------------------------------------------------------------------
function build(movie, kind) {
  const id = `${kind[0]}${movie.movie_id}`;
  const key = `${kind}:${movie.movie_id}`;
  if (svgCache.has(key)) return svgCache.get(key);

  const rand = seededRandom((Number(movie.movie_id) || 7) * 40503 + 11);
  const genres = movie.genres || [];
  const main = genres.find((g) => COMPOSITION[g]) || "Drama";
  const second = genres.find((g) => g !== main && COMPOSITION[g]);
  const options = COMPOSITION[second && rand() < 0.25 ? second : main];
  const comp = options[Math.floor(rand() * options.length) % options.length];
  // light "paper" grounds only on posters: backdrops sit behind white text, so they stay dark
  const light = kind === "poster" && LIGHT_FRIENDLY.has(main) && ["blobs", "grid", "sun", "arch", "orbit", "fields", "dots"].includes(comp) && rand() < 0.3;

  const p = paletteNow(movie);
  const poster = kind === "poster";
  const W = poster ? 200 : 480;
  const H = poster ? 300 : 270;
  // focal point: posters keep the art in the upper half (title goes below),
  // backdrops push it right so hero text on the left stays readable
  const fx = poster ? 0.42 + rand() * 0.18 : 0.6 + rand() * 0.14;
  const fy = poster ? 0.3 + rand() * 0.1 : 0.4 + rand() * 0.14;
  const o = { W, H, p, r: rand, id, light, fx, fy, poster };

  const art = (COMPOSERS[comp] || sun)(o, movie);
  const title = poster ? titleBlock(movie, o, TYPE[main] || pick(rand, ["serifItalic", "serifBold"]), rand) : { defs: "", body: "" };
  const frame = poster && rand() < 0.28
    ? `<rect x="7" y="7" width="${W - 14}" height="${H - 14}" fill="none" stroke="${light ? p.ink : "#f4efe8"}" stroke-width=".6" opacity=".4"/>`
    : "";

  const svg = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid slice" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false"><defs>${art.defs}${title.defs}</defs>${art.body}${title.body}${frame}</svg>`;
  svgCache.set(key, svg);
  return svg;
}

export const posterSVG = (movie) => build(movie, "poster");
export const backdropSVG = (movie) => build(movie, "backdrop");

/**
 * Art for a film: the real TMDB image when there is one, generated art otherwise.
 * kind = "poster" (2:3) or "backdrop" (16:9)
 */
export function artHTML(movie, kind = "poster", { alt = "", eager = false } = {}) {
  if (!movie) return "";
  registry.set(movie.movie_id, movie);
  const url = kind === "poster" ? movie.poster_url : movie.backdrop_url;
  if (url) {
    return `<img src="${esc(url)}" alt="${esc(alt)}" ${eager ? 'fetchpriority="high"' : 'loading="lazy"'} decoding="async" crossorigin="anonymous" data-art="${kind}" data-mid="${movie.movie_id}">`;
  }
  return build(movie, kind);
}

/** If a TMDB image fails to load, swap in generated art (one listener for the whole page). */
document.addEventListener("error", (event) => {
  const img = event.target;
  if (!(img instanceof HTMLImageElement) || !img.dataset.art) return;
  const movie = registry.get(Number(img.dataset.mid));
  if (!movie) return;
  img.outerHTML = build(movie, img.dataset.art);
}, true);

/** Film grain texture, made once on a canvas and shared via the --grain CSS variable. */
export function initGrain() {
  try {
    const size = 160;
    const canvas = document.createElement("canvas");
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext("2d");
    const img = ctx.createImageData(size, size);
    for (let i = 0; i < img.data.length; i += 4) {
      const v = Math.random() * 255;
      img.data[i] = v; img.data[i + 1] = v; img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    document.documentElement.style.setProperty("--grain", `url(${canvas.toDataURL("image/png")})`);
  } catch { /* canvas unavailable: no grain, no problem */ }
}
