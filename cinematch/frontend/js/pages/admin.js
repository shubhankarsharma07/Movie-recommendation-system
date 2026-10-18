// ============================================================================
// CineMatch — pages/admin.js  (#/admin, admins only)
// Engagement + model health from GET /api/admin/stats:
//   KPI tiles, Chart.js charts (one measure per chart, never two y-axes),
//   a model card with the evaluation table, and Reload / Retrain buttons.
// Every chart has a "Show the numbers" table underneath for accessibility.
// ============================================================================

import { api } from "../api.js";
import { setAmbientMode } from "../ambient.js";
import { el, esc, formatMs, formatNumber, formatPercent, sleep } from "../utils.js";
import { icon } from "../ui/icons.js";
import { toast, toastError } from "../ui/toast.js";

const CHART_URL = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js";
const TARGET_MS = 2000; // NFR-1: ranked list in under 2 s at p95

// Chart colours (validated for the dark surface: contrast ≥ 3:1, see dataviz palette)
const SERIES = "#3987e5";
const SERIES_WASH = "rgba(57, 135, 229, 0.12)";
const GRID = "rgba(244, 239, 232, 0.08)";
const TICK = "rgba(244, 239, 232, 0.55)";
const TEXT = "rgba(244, 239, 232, 0.9)";

let chartPromise = null;
function loadChartJs() {
  if (window.Chart) return Promise.resolve(window.Chart);
  if (!chartPromise) {
    chartPromise = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = CHART_URL;
      s.async = true;
      s.onload = () => (window.Chart ? resolve(window.Chart) : reject(new Error("Chart.js missing")));
      s.onerror = () => { chartPromise = null; reject(new Error("Chart.js failed to load")); };
      document.head.appendChild(s);
    });
  }
  return chartPromise;
}

const CONTEXT_LABELS = {
  weather: "Weather", time_of_day: "Time of day", time_available_min: "Time available", occasion: "Occasion",
  festival: "Festival", reference_movie_ids: "Reference films", directors: "Directors", actors: "Actors",
  language: "Language", max_age_rating: "Age rating", franchise_mode: "Franchise", nostalgia_decade: "Nostalgia",
  start_emotion: "Start feeling", end_emotion: "End feeling", genres: "Genres", content_type: "Movie or series",
  preset: "Row preset (See all)",
};

let charts = [];
let lastRetrain = null; // survives the stats reload after a retrain finishes

export async function render(main, { alive }) {
  setAmbientMode("quiet");
  main.innerHTML = `
    <div class="page">
      <header class="page-head" style="max-width:none">
        <div style="display:flex;flex-wrap:wrap;align-items:end;justify-content:space-between;gap:16px">
          <div style="display:grid;gap:8px">
            <h1 class="page-title">Admin</h1>
            <p class="page-sub">How people use CineMatch, and how the recommender is doing.</p>
          </div>
          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <button type="button" class="btn btn--glass btn--sm" data-act="reload">${icon("refresh")} Reload model</button>
            <button type="button" class="btn btn--play btn--sm" data-act="retrain">${icon("sparkle")} Retrain model</button>
          </div>
        </div>
      </header>
      <div data-body>
        <div class="kpis">${Array.from({ length: 6 }, () => '<div class="kpi"><div class="skel skel--line" style="width:60%"></div><div class="skel skel--line" style="height:26px;width:40%;margin-top:8px"></div></div>').join("")}</div>
      </div>
    </div>`;

  main.querySelector('[data-act="reload"]').addEventListener("click", reloadModel);
  main.querySelector('[data-act="retrain"]').addEventListener("click", (e) => retrain(main, e.currentTarget, alive));

  await loadStats(main, alive);
  pollRetrain(main, alive, { quiet: true });

  return () => {
    charts.forEach((c) => c.destroy());
    charts = [];
    lastRetrain = null;
    setAmbientMode("");
  };
}

async function loadStats(main, alive) {
  let stats;
  try {
    stats = await api.get("/api/admin/stats");
  } catch (err) {
    if (!alive()) return;
    main.querySelector("[data-body]").innerHTML = `<div class="empty"><p class="empty__title">Stats didn't load</p><p class="empty__text">${esc(err.detail)}</p></div>`;
    toastError(err);
    return;
  }
  if (!alive()) return;
  charts.forEach((c) => c.destroy());
  charts = [];
  const body = main.querySelector("[data-body]");
  body.innerHTML = "";
  body.appendChild(kpis(stats));
  const grid = el('<div class="admin-grid"></div>');
  body.appendChild(grid);

  const ratingsDays = stats.ratings_by_day || [];
  const requestDays = stats.requests_by_day || [];
  const hist = Object.entries(stats.rating_histogram || {}).sort((a, b) => Number(a[0]) - Number(b[0]));
  const usage = Object.entries(stats.context_usage || {}).sort((a, b) => b[1] - a[1]);

  const panels = {
    ratings: panel(grid, "span-8", "Ratings per day", "Last 30 days", table(["Date", "Ratings"], ratingsDays.map((d) => [d.date, formatNumber(d.count)]))),
    hist: panel(grid, "span-4", "How people rate", "Share of all ratings by star value", table(["Stars", "Ratings"], hist.map(([k, v]) => [k, formatNumber(v)]))),
    requests: panel(grid, "span-8", "Recommendation requests per day", "Every request is logged with its context (NFR-3)", table(["Date", "Requests"], requestDays.map((d) => [d.date, formatNumber(d.count)]))),
    latency: panel(grid, "span-4", "Response time", `p50 and p95 against the ${TARGET_MS / 1000} s target`, table(["Percentile", "Milliseconds"], [["p50", Math.round(stats.latency_p50_ms ?? 0)], ["p95", Math.round(stats.latency_p95_ms ?? 0)]])),
    usage: panel(grid, "span-6", "Which filters people use", "Requests that included each part of the context", table(["Filter", "Requests"], usage.map(([k, v]) => [CONTEXT_LABELS[k] || k, formatNumber(v)])), "chart-box--tall"),
  };
  grid.appendChild(modelCard(stats.model || {}));
  grid.appendChild(retrainPanel());
  if (lastRetrain) setRetrainUI(main, lastRetrain.status, lastRetrain.message, lastRetrain.log);
  grid.appendChild(topRated(stats.top_rated || []));

  let Chart;
  try {
    Chart = await loadChartJs();
  } catch {
    Object.values(panels).forEach((p) => {
      p.querySelector(".chart-box").replaceWith(el('<p class="chart-fallback">Charts couldn\'t load (no internet?), so here are the numbers.</p>'));
      p.querySelector("details").open = true;
    });
    return;
  }
  if (!alive()) return;
  Chart.defaults.font.family = "'Hanken Grotesk', system-ui, sans-serif";
  Chart.defaults.font.size = 12;
  Chart.defaults.color = TICK;
  Chart.defaults.animation.duration = matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : 600;

  const tooltip = {
    backgroundColor: "rgba(20, 18, 28, 0.96)", borderColor: "rgba(244,239,232,.16)", borderWidth: 1,
    titleColor: TEXT, bodyColor: TEXT, padding: 10, cornerRadius: 8, displayColors: false,
  };
  const axis = (extra = {}) => ({ grid: { color: GRID, drawTicks: false }, border: { display: false }, ticks: { padding: 8, color: TICK }, ...extra });
  const shortDate = (iso) => new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });

  charts.push(new Chart(panels.ratings.querySelector("canvas"), {
    type: "line",
    data: { labels: ratingsDays.map((d) => shortDate(d.date)), datasets: [{ data: ratingsDays.map((d) => d.count), borderColor: SERIES, backgroundColor: SERIES_WASH, fill: true, borderWidth: 2, tension: 0.35, pointRadius: ratingsDays.length <= 3 ? 4 : 0, pointHoverRadius: 5, pointHoverBorderWidth: 2, pointHoverBorderColor: "#120f18", pointBackgroundColor: SERIES }] },
    options: {
      maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      plugins: { legend: { display: false }, tooltip: { ...tooltip, callbacks: { label: (c) => `${formatNumber(c.parsed.y)} ratings` } } },
      scales: { x: axis({ grid: { display: false }, ticks: { maxTicksLimit: 8, color: TICK } }), y: axis({ beginAtZero: true, ticks: { maxTicksLimit: 5, color: TICK, padding: 8 } }) },
    },
  }));

  charts.push(new Chart(panels.hist.querySelector("canvas"), {
    type: "bar",
    data: { labels: hist.map(([k]) => Number(k).toFixed(1)), datasets: [{ data: hist.map(([, v]) => v), backgroundColor: SERIES, borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "start", maxBarThickness: 24 }] },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { ...tooltip, callbacks: { title: (c) => `${c[0].label} stars`, label: (c) => `${formatNumber(c.parsed.y)} ratings` } } },
      scales: { x: axis({ grid: { display: false } }), y: axis({ beginAtZero: true, ticks: { maxTicksLimit: 5, color: TICK, padding: 8 } }) },
    },
  }));

  charts.push(new Chart(panels.requests.querySelector("canvas"), {
    type: "bar",
    data: { labels: requestDays.map((d) => shortDate(d.date)), datasets: [{ data: requestDays.map((d) => d.count), backgroundColor: SERIES, borderRadius: { topLeft: 4, topRight: 4 }, borderSkipped: "start", maxBarThickness: 18, categoryPercentage: 0.8 }] },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { ...tooltip, callbacks: { label: (c) => `${formatNumber(c.parsed.y)} requests` } } },
      scales: { x: axis({ grid: { display: false }, ticks: { maxTicksLimit: 8, color: TICK } }), y: axis({ beginAtZero: true, ticks: { maxTicksLimit: 5, color: TICK, padding: 8 } }) },
    },
  }));

  // latency: horizontal bars + a labelled 2 s target line (drawn by a tiny inline plugin)
  const targetLine = {
    id: "targetLine",
    afterDatasetsDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      const x = scales.x.getPixelForValue(TARGET_MS);
      ctx.save();
      ctx.strokeStyle = "rgba(244,239,232,.7)";
      ctx.lineWidth = 1;
      ctx.beginPath(); ctx.moveTo(x, chartArea.top); ctx.lineTo(x, chartArea.bottom); ctx.stroke();
      ctx.fillStyle = TEXT;
      ctx.font = "600 11px 'Hanken Grotesk', sans-serif";
      ctx.textAlign = "right";
      ctx.fillText(`${TARGET_MS / 1000} s target`, x - 6, chartArea.top + 10);
      ctx.restore();
    },
  };
  const p50 = Math.round(stats.latency_p50_ms ?? 0);
  const p95 = Math.round(stats.latency_p95_ms ?? 0);
  charts.push(new Chart(panels.latency.querySelector("canvas"), {
    type: "bar",
    data: { labels: ["p50", "p95"], datasets: [{ data: [p50, p95], backgroundColor: SERIES, borderRadius: { topRight: 4, bottomRight: 4 }, borderSkipped: "start", maxBarThickness: 24 }] },
    options: {
      indexAxis: "y", maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { ...tooltip, callbacks: { label: (c) => `${formatNumber(c.parsed.x)} ms` } } },
      scales: { x: axis({ beginAtZero: true, suggestedMax: Math.max(TARGET_MS * 1.15, p95 * 1.1), ticks: { maxTicksLimit: 5, color: TICK, callback: (v) => `${v / 1000} s` } }), y: axis({ grid: { display: false } }) },
    },
    plugins: [targetLine],
  }));

  charts.push(new Chart(panels.usage.querySelector("canvas"), {
    type: "bar",
    data: { labels: usage.map(([k]) => CONTEXT_LABELS[k] || k), datasets: [{ data: usage.map(([, v]) => v), backgroundColor: SERIES, borderRadius: { topRight: 4, bottomRight: 4 }, borderSkipped: "start", maxBarThickness: 14, categoryPercentage: 0.85 }] },
    options: {
      indexAxis: "y", maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { ...tooltip, callbacks: { label: (c) => `${formatNumber(c.parsed.x)} requests` } } },
      scales: { x: axis({ beginAtZero: true, ticks: { maxTicksLimit: 5, color: TICK } }), y: axis({ grid: { display: false }, ticks: { autoSkip: false, color: TICK, font: { size: 11.5 } } }) },
    },
  }));
}

function kpis(s) {
  const p95 = s.latency_p95_ms;
  const tiles = [
    ["People", formatNumber(s.users), "registered accounts"],
    ["Ratings", formatNumber(s.ratings), "stored, all time"],
    ["Watch sessions", formatNumber(s.sessions), "started from the app"],
    ["Click-through", formatPercent(s.rec_ctr, 1), "recommended items opened"],
    ["Not for me", formatPercent(s.dismiss_rate, 1), "of shown items dismissed"],
    ["Finish rate", formatPercent(s.avg_completion), "average completion"],
    ["Time to pick", formatMs(s.avg_browse_to_select_ms), "browse to first select"],
    ["p95 response", formatMs(p95), p95 != null ? (p95 <= TARGET_MS ? '<span class="ok">Within the 2 s target</span>' : '<span class="warn">Slower than the 2 s target</span>') : "no data yet"],
  ];
  return el(`<div class="kpis">${tiles.map(([label, value, note]) => `
    <div class="kpi"><span class="kpi__label">${label}</span><span class="kpi__value">${esc(value)}</span><span class="kpi__note">${note}</span></div>`).join("")}</div>`);
}

function table(head, rows) {
  return `<table class="table"><thead><tr>${head.map((h, i) => `<th class="${i ? "num" : ""}">${esc(h)}</th>`).join("")}</tr></thead>
    <tbody>${rows.map((r) => `<tr>${r.map((c, i) => `<td class="${i ? "num" : ""}">${esc(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`;
}

function panel(grid, span, title, sub, tableHTML, boxClass = "") {
  const node = el(`
    <section class="panel ${span}">
      <div class="panel__head"><div><h2 class="panel__title">${esc(title)}</h2><p class="panel__sub">${esc(sub)}</p></div></div>
      <div class="chart-box ${boxClass}"><canvas role="img" aria-label="${esc(title)}"></canvas></div>
      <details style="margin-top:10px"><summary class="link-btn" style="cursor:pointer">Show the numbers</summary><div style="max-height:220px;overflow:auto;margin-top:8px">${tableHTML}</div></details>
    </section>`);
  grid.appendChild(node);
  return node;
}

function modelCard(m) {
  const metrics = m.metrics || {};
  const rmseRows = [
    ["Level 0: global mean", metrics.baseline_global_mean_rmse],
    ["Level 1: user + item bias", metrics.baseline_bias_rmse],
    ["SVD (matrix factorisation)", metrics.rmse],
  ].filter(([, v]) => v != null);
  const maxRmse = Math.max(0.0001, ...rmseRows.map(([, v]) => v));
  const best = Math.min(...rmseRows.map(([, v]) => v));
  // ranking metrics: show popularity / SVD / blended side by side when the ml step reports them
  const RANK = [["Precision@10", "precision_at_10"], ["Recall@10", "recall_at_10"], ["NDCG@10", "ndcg_at_10"]];
  const cols = [["Popularity", "popularity_"], ["SVD", ""], ["Blended", "blend_"]].filter(([, prefix]) => RANK.some(([, k]) => metrics[prefix + k] != null));
  const rankRows = RANK.filter(([, k]) => cols.some(([, prefix]) => metrics[prefix + k] != null));
  const trained = m.trained_at ? new Date(m.trained_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "–";
  return el(`
    <section class="panel span-6" aria-labelledby="model-title">
      <div class="panel__head">
        <div><h2 class="panel__title" id="model-title">Model card</h2><p class="panel__sub">${esc(m.algorithm || "Recommender")}</p></div>
        <span class="badge ${m.dataset_mode === "sample" ? "" : "badge--solid"}">${esc(m.dataset_mode === "sample" ? "Sample data" : m.dataset_mode === "full" ? "Full data" : m.dataset_mode || "Unknown data")}</span>
      </div>
      <dl class="facts" style="grid-template-columns:repeat(auto-fit,minmax(140px,1fr));display:grid;gap:12px 18px;font-size:var(--fs-sm)">
        <div><dt>Version</dt><dd class="tabular">${esc(m.version || "–")}</dd></div>
        <div><dt>Trained</dt><dd>${esc(trained)}</dd></div>
        <div><dt>Catalogue</dt><dd>${formatNumber(m.n_items)} titles${m.n_cf_items ? `, ${formatNumber(m.n_cf_items)} with ratings` : ""}</dd></div>
        <div><dt>Training ratings</dt><dd>${formatNumber(m.n_train_ratings)}</dd></div>
      </dl>
      <h3 class="small" style="margin:20px 0 6px;font-weight:700">Rating error (RMSE, lower is better)</h3>
      <table class="table">
        <thead><tr><th>Model</th><th class="bar-cell"></th><th class="num">RMSE</th></tr></thead>
        <tbody>${rmseRows.map(([label, v]) => `<tr class="${v === best ? "is-best" : ""}"><td>${esc(label)}</td><td class="bar-cell"><div class="mini-bar" style="width:${((v / maxRmse) * 100).toFixed(1)}%"></div></td><td class="num">${Number(v).toFixed(3)}</td></tr>`).join("")}</tbody>
      </table>
      ${rankRows.length ? `
      <h3 class="small" style="margin:20px 0 6px;font-weight:700">Ranking quality (higher is better)</h3>
      <table class="table">
        <thead><tr><th>Metric</th>${cols.map(([label]) => `<th class="num">${label}</th>`).join("")}</tr></thead>
        <tbody>${rankRows.map(([label, k]) => {
          const vals = cols.map(([, prefix]) => metrics[prefix + k]);
          const top = Math.max(...vals.filter((v) => v != null));
          return `<tr><td>${esc(label)}</td>${vals.map((v) => `<td class="num" ${v === top && cols.length > 1 ? 'style="color:var(--screen);font-weight:700"' : ""}>${v != null ? Number(v).toFixed(3) : "–"}</td>`).join("")}</tr>`;
        }).join("")}</tbody>
      </table>` : ""}
      ${metrics.mae != null ? `<p class="hint" style="margin-top:10px">Mean absolute error of the SVD model: ${Number(metrics.mae).toFixed(3)} stars.</p>` : ""}
    </section>`);
}

function retrainPanel() {
  return el(`
    <section class="panel span-6" aria-labelledby="retrain-title" data-retrain>
      <div class="panel__head"><div><h2 class="panel__title" id="retrain-title">Retraining</h2>
        <p class="panel__sub">Runs ml/retrain.py in the background. If it fails, the last good model keeps serving.</p></div>
        <span class="badge" data-status>Idle</span></div>
      <p class="small dim" data-msg>Press "Retrain model" to fold in new ratings and watch history.</p>
      <pre class="logbox" data-log hidden></pre>
    </section>`);
}

function topRated(list) {
  return el(`
    <section class="panel span-6" aria-labelledby="top-title">
      <div class="panel__head"><div><h2 class="panel__title" id="top-title">Highest rated titles</h2><p class="panel__sub">Average user rating</p></div></div>
      <table class="table">
        <thead><tr><th>Title</th><th class="num">Average</th><th class="num">Ratings</th></tr></thead>
        <tbody>${list.map((t) => `<tr><td>${esc(t.movie?.title || "")}${t.movie?.year ? ` <span class="faint">${t.movie.year}</span>` : ""}</td><td class="num">★ ${Number(t.avg).toFixed(2)}</td><td class="num">${formatNumber(t.count)}</td></tr>`).join("")}</tbody>
      </table>
    </section>`);
}

async function reloadModel(e) {
  const btn = e.currentTarget;
  btn.disabled = true;
  try {
    const res = await api.post("/api/admin/reload-model");
    toast(`Now serving model ${res.version}.`, { type: "success" });
  } catch (err) {
    toastError(err);
  } finally {
    btn.disabled = false;
  }
}

async function retrain(main, btn, alive) {
  btn.disabled = true;
  try {
    const res = await api.post("/api/admin/retrain");
    if (res?.status && res.status !== "started" && res.status !== "running") {
      setRetrainUI(main, res.status, res.detail || res.message || "Retraining isn't available on this server.");
      btn.disabled = false;
      return;
    }
    toast("Retraining started. This can take a few minutes.");
    await pollRetrain(main, alive);
  } catch (err) {
    setRetrainUI(main, "unavailable", err.detail);
    toastError(err);
  } finally {
    btn.disabled = false;
  }
}

function setRetrainUI(main, status, message, log) {
  lastRetrain = { status, message, log };
  const box = main.querySelector("[data-retrain]");
  if (!box) return;
  const labels = { idle: "Idle", running: "Running", started: "Running", finished: "Finished", failed: "Failed", disabled: "Disabled", unavailable: "Unavailable" };
  const badge = box.querySelector("[data-status]");
  badge.textContent = labels[status] || status;
  badge.classList.toggle("badge--solid", status === "running" || status === "started");
  if (message) box.querySelector("[data-msg]").textContent = message;
  const logEl = box.querySelector("[data-log]");
  if (log) { logEl.hidden = false; logEl.textContent = log; logEl.scrollTop = logEl.scrollHeight; }
}

async function pollRetrain(main, alive, { quiet = false } = {}) {
  for (let i = 0; i < 400 && alive(); i++) {
    let res;
    try { res = await api.get("/api/admin/retrain", null, { wake: false }); } catch { return; }
    if (!alive()) return;
    const status = res.status || "idle";
    const messages = {
      running: "Training a new model. You can leave this page; it carries on in the background.",
      finished: "The new model is trained and live.",
      failed: "Retraining failed. The previous model is still serving.",
      disabled: "In-app retraining is turned off on this server (ENABLE_INAPP_RETRAIN).",
    };
    setRetrainUI(main, status, messages[status], res.last_log_tail);
    if (status !== "running" && status !== "started") {
      if (!quiet && status === "finished") {
        toast("Retraining finished. The new model is live.", { type: "success" });
        loadStats(main, alive);
      }
      return;
    }
    quiet = false;
    await sleep(2000);
  }
}
