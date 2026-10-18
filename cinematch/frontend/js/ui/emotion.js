// ============================================================================
// CineMatch — ui/emotion.js
// The "emotional journey" picture: a curve from how a film starts to how it
// ends (e.g. Sad → Happy). Used in the details modal and the Mood Mixer.
// Positive feelings sit high, negative ones low; the arc type shapes the middle.
// ============================================================================

import { EMOTION_COLORS } from "../palette.js";
import { VOCAB } from "../state.js";
import { esc } from "../utils.js";

// how "up" each feeling is (1 = very positive, -1 = very negative)
const LIFT = { joy: 0.95, surprise: 0.5, neutral: 0.05, sadness: -0.55, fear: -0.7, anger: -0.8, disgust: -0.9 };
export const EMOTIONS = ["joy", "surprise", "neutral", "sadness", "fear", "anger", "disgust"];
export const emotionLabel = (id) => VOCAB.emotions[id] || id;
export const emotionColor = (id) => EMOTION_COLORS[id] || "#8a96ab";

const W = 320;
const H = 104;
const PAD_X = 26;
const PAD_Y = 18;
const yFor = (id) => PAD_Y + (1 - ((LIFT[id] ?? 0) + 1) / 2) * (H - 2 * PAD_Y);

/** SVG path for the curve. arc: rise | fall | fall-rise | rise-fall | steady */
export function arcPath(start, end, arc) {
  const x0 = PAD_X;
  const x1 = W - PAD_X;
  const y0 = yFor(start || "neutral");
  const y1 = yFor(end || "neutral");
  const xm = W / 2;
  if (arc === "fall-rise" || arc === "rise-fall") {
    const dip = arc === "fall-rise" ? Math.min(H - 8, Math.max(y0, y1) + 30) : Math.max(8, Math.min(y0, y1) - 30);
    return `M ${x0} ${y0} C ${x0 + 50} ${y0}, ${xm - 60} ${dip}, ${xm} ${dip} C ${xm + 60} ${dip}, ${x1 - 50} ${y1}, ${x1} ${y1}`;
  }
  // rise / fall / steady (and unknown): a smooth S-curve with a gentle wobble in the middle
  const wob = arc === "steady" ? 10 : 0;
  return `M ${x0} ${y0} C ${x0 + 90} ${y0 - wob}, ${x1 - 90} ${y1 + wob}, ${x1} ${y1}`;
}

/**
 * Full SVG markup. Pass { id } to make gradient ids unique on the page.
 * The parts have class names so the mixer can animate them (d / cy / stop-color transitions).
 */
export function arcSVG(start, end, arc, { id = "arc", animated = true } = {}) {
  const c0 = emotionColor(start || "neutral");
  const c1 = emotionColor(end || "neutral");
  const d = arcPath(start, end, arc);
  const midY = yFor("neutral");
  return `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(`Starts ${emotionLabel(start || "neutral")}, ends ${emotionLabel(end || "neutral")}`)}">
      <defs>
        <linearGradient id="${id}-g" x1="0" y1="0" x2="1" y2="0">
          <stop class="emo-arc__stop" data-end="start" offset="0" stop-color="${c0}"/>
          <stop class="emo-arc__stop" data-end="end" offset="1" stop-color="${c1}"/>
        </linearGradient>
      </defs>
      <line x1="${PAD_X}" y1="${midY}" x2="${W - PAD_X}" y2="${midY}" stroke="rgba(244,239,232,.14)" stroke-dasharray="2 5"/>
      <path class="emo-arc__path" d="${d}" fill="none" stroke="url(#${id}-g)" stroke-width="10" stroke-linecap="round" opacity=".22"/>
      <path class="emo-arc__path" d="${d}" fill="none" stroke="url(#${id}-g)" stroke-width="3" stroke-linecap="round"/>
      ${animated ? `<path class="emo-arc__path emo-arc__flow" d="${d}" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round" stroke-dasharray="1.5 18.5" opacity=".7"/>` : ""}
      <circle class="emo-arc__dot" data-end="start" cx="${PAD_X}" cy="${yFor(start || "neutral")}" r="6" fill="${c0}" stroke="rgba(10,9,14,.9)" stroke-width="2"/>
      <circle class="emo-arc__dot" data-end="end" cx="${W - PAD_X}" cy="${yFor(end || "neutral")}" r="6" fill="${c1}" stroke="rgba(10,9,14,.9)" stroke-width="2"/>
    </svg>`;
}

/** Animate an existing arc SVG to new emotions (used by the Mood Mixer). */
export function updateArc(svg, start, end, arc) {
  const d = arcPath(start, end, arc);
  svg.querySelectorAll(".emo-arc__path").forEach((p) => {
    p.style.d = `path("${d}")`; // CSS "d" can transition smoothly in modern browsers
    p.setAttribute("d", d);
  });
  svg.querySelectorAll(".emo-arc__stop").forEach((s) => {
    s.style.stopColor = emotionColor((s.dataset.end === "start" ? start : end) || "neutral");
  });
  svg.querySelectorAll(".emo-arc__dot").forEach((c) => {
    const id = (c.dataset.end === "start" ? start : end) || "neutral";
    c.style.cy = `${yFor(id)}px`;
    c.setAttribute("cy", yFor(id));
    c.style.fill = emotionColor(id);
  });
  svg.setAttribute("aria-label", `Starts ${emotionLabel(start || "neutral")}, ends ${emotionLabel(end || "neutral")}`);
}

/** "Starts tense, ends happy" */
export function arcCaption(start, end) {
  if (!start && !end) return "Pick how you want to feel at the start and at the end.";
  if (start && !end) return `Starts ${emotionLabel(start).toLowerCase()}, ends any way it likes`;
  if (!start && end) return `Ends ${emotionLabel(end).toLowerCase()}`;
  return `Starts ${emotionLabel(start).toLowerCase()}, ends ${emotionLabel(end).toLowerCase()}`;
}
