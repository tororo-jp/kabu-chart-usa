/* Main app: data loading, filtering, sorting, rendering */

const DATA_URL = "data/results.json";

let allResults = [];
let filteredResults = [];
let currentSort = { key: "score", asc: false };
let selectedCode = null;
let scanMeta = {};
let savedScrollY = 0;
let favorites = new Set();
let showFavoritesOnly = false;
let showRecOnly = false;
let prevScores = {};   // { code: score } previous trading day
let weekScores = {};   // { code: score } ~1 week ago
let _chartStock = null;
let _indHelpOpen = false;

// ── Favorites ────────────────────────────────────────────
function loadFavorites() {
  try {
    const saved = localStorage.getItem("usa_favorites");
    if (saved) favorites = new Set(JSON.parse(saved));
  } catch (e) {}
  _syncFavUI();
}

function saveFavorites() {
  localStorage.setItem("usa_favorites", JSON.stringify([...favorites]));
}

function toggleFavorite(code, e) {
  e.stopPropagation();
  if (favorites.has(code)) {
    favorites.delete(code);
  } else {
    favorites.add(code);
  }
  saveFavorites();
  document.querySelectorAll(`#results-body .fav-btn[data-code="${code}"]`).forEach(btn => {
    btn.classList.toggle("fav-active", favorites.has(code));
    btn.textContent = favorites.has(code) ? "⭐" : "☆";
  });
  _syncFavUI();
  if (showFavoritesOnly) applyFilters();
}

function _syncFavUI() {
  const count = favorites.size;
  document.getElementById("stat-favorites").textContent = count;
  document.getElementById("fav-toggle-btn").textContent =
    `⭐ Favorites${count > 0 ? ` (${count})` : ""}`;
}

// ── Presets ──────────────────────────────────────────────────
const PRESETS = {
  breakout: {
    pattern: "resistance_breakout",
    prob: "0.5",
    score: "30",
    rr: "1.5",
    sector: "",
  },
  reversal: {
    pattern: "inverse_head_shoulders",
    prob: "0.5",
    score: "30",
    rr: "0",
    sector: "",
  },
  momentum: {
    pattern: "perfect_order",
    prob: "0.5",
    score: "50",
    rr: "0",
    sector: "",
  },
  ma_squeeze: {
    pattern: "ma_compression",
    prob: "0",
    score: "30",
    rr: "0",
    sector: "",
  },
  ichimoku: {
    pattern: "ichimoku_cloud_break",
    prob: "0.5",
    score: "30",
    rr: "0",
    sector: "",
  },
};

// ── Historical scores ─────────────────────────────────────────────────
async function _fetchScores(dateStr) {
  try {
    const res = await fetch(`data/results_${dateStr}.json`);
    if (!res.ok) return null;
    const json = await res.json();
    const map = {};
    (json.results || []).forEach(r => { map[r.code] = r.score; });
    return map;
  } catch (e) {
    return null;
  }
}

async function loadHistoricalScores(scanDateStr) {
  prevScores = {};
  weekScores = {};

  const base = new Date(scanDateStr + "T00:00:00");

  for (let d = 1; d <= 5; d++) {
    const dt = new Date(base);
    dt.setDate(dt.getDate() - d);
    const map = await _fetchScores(dt.toISOString().slice(0, 10));
    if (map) { prevScores = map; break; }
  }

  for (let d = 5; d <= 12; d++) {
    const dt = new Date(base);
    dt.setDate(dt.getDate() - d);
    const map = await _fetchScores(dt.toISOString().slice(0, 10));
    if (map) { weekScores = map; break; }
  }
}

function scoreDeltaHtml(score, historical, code) {
  if (!(code in historical)) return `<span class="score-delta score-delta-new">New</span>`;
  const d = score - historical[code];
  if (d === 0) return `<span class="score-delta score-delta-flat">±0</span>`;
  const sign = d > 0 ? "+" : "";
  const cls  = d >= 5 ? "score-delta-up" : d <= -5 ? "score-delta-down" : "score-delta-flat";
  return `<span class="score-delta ${cls}">${sign}${d}</span>`;
}

// ── Fetch data ───────────────────────────────────────────────
async function loadData() {
  try {
    const res = await fetch(DATA_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    scanMeta = {
      generated_at:  json.generated_at  || "",
      total_scanned: json.total_scanned || 0,
      total_signals: json.total_signals || 0,
      market_env:    json.market_env    || null,
    };
    allResults = json.results || [];
    const scanDateStr = scanMeta.generated_at
      ? scanMeta.generated_at.slice(0, 10)
      : new Date().toISOString().slice(0, 10);
    loadHistoricalScores(scanDateStr).then(() => renderTable());
    document.getElementById("last-update").textContent =
      scanMeta.generated_at ? `Last Update: ${scanMeta.generated_at}` : "";
    document.getElementById("stat-scanned").textContent = scanMeta.total_scanned.toLocaleString();
    document.getElementById("stat-signals").textContent = scanMeta.total_signals.toLocaleString();

    _buildSectorFilter();
    _renderMarketBanner();
    applyFilters();

    const urlCode = new URLSearchParams(window.location.search).get("code");
    if (urlCode) openChart(urlCode);
  } catch (e) {
    const tbody = document.getElementById("results-body");
    tbody.innerHTML = `<tr><td colspan="12" class="loading" style="color:#f85149">Failed to load data: ${e.message}</td></tr>`;
  }
}

function _renderMarketBanner() {
  const banner = document.getElementById("market-banner");
  const env = scanMeta.market_env || {};
  const bull = env.bull;
  if (bull === null || bull === undefined) {
    banner.classList.add("hidden");
    return;
  }
  const sp500 = env.sp500 ? env.sp500.toLocaleString("en-US") : "-";
  const sma200 = env.sma200 ? env.sma200.toLocaleString("en-US") : "-";
  banner.className = `market-banner ${bull ? "market-bull" : "market-bear"}`;
  banner.innerHTML = bull
    ? `🟢 <strong>Bull Market</strong> — S&amp;P 500 ${sp500} is above the 200MA ${sma200}. Favorable entry environment.`
    : `🔴 <strong>Bear Market</strong> — S&amp;P 500 ${sp500} is below the 200MA ${sma200}. Exercise caution on new entries.`;
}

function _buildSectorFilter() {
  const sectors = [...new Set(allResults.map((r) => r.sector).filter(Boolean))].sort();
  const sel = document.getElementById("filter-sector");
  sectors.forEach((s) => {
    const opt = document.createElement("option");
    opt.value = s;
    opt.textContent = s;
    sel.appendChild(opt);
  });
}

// ── Filtering ───────────────────────────────────────────────────
function applyFilters() {
  const search  = (document.getElementById("filter-search").value || "").trim().toLowerCase();
  const pattern = document.getElementById("filter-pattern").value;
  const minProb = parseFloat(document.getElementById("filter-prob").value) || 0;
  const minScore = parseInt(document.getElementById("filter-score").value) || 0;
  const minRR = parseFloat(document.getElementById("filter-rr").value) || 0;
  const sector = document.getElementById("filter-sector").value;

  filteredResults = allResults.filter((r) => {
    if (search) {
      const code = (r.code || "").toLowerCase();
      const name = (r.name || "").toLowerCase();
      if (!code.includes(search) && !name.includes(search)) return false;
    }
    if (minProb > 0 && r.probability < minProb) return false;
    if (minScore > 0 && r.score < minScore) return false;
    if (minRR > 0 && r.rr_ratio < minRR) return false;
    if (sector && r.sector !== sector) return false;
    if (pattern) {
      const hasPattern = (r.patterns || []).some((p) => p.name === pattern);
      if (!hasPattern) return false;
    }
    return true;
  });

  if (showFavoritesOnly) {
    filteredResults = filteredResults.filter(r => favorites.has(r.code));
  }

  if (showRecOnly) {
    filteredResults = filteredResults.filter(r =>
      r.score >= 60 && r.probability >= 0.60 && r.rr_ratio >= 2.0 && !r.earnings_warning
    );
  }

  sortResults();
}

// ── Sorting ─────────────────────────────────────────────────────
function sortResults() {
  const { key, asc } = currentSort;
  filteredResults.sort((a, b) => {
    let va = a[key] ?? 0;
    let vb = b[key] ?? 0;
    return asc ? va - vb : vb - va;
  });
  renderTable();
  document.getElementById("stat-showing").textContent = filteredResults.length.toLocaleString();
}

// ── Table rendering ───────────────────────────────────────────────
function renderTable() {
  const tbody = document.getElementById("results-body");
  if (filteredResults.length === 0) {
    const msg = showFavoritesOnly
      ? "No favorites saved. Click ☆ to add stocks."
      : showRecOnly
      ? "No recommended candidates (Score 60+, Prob 60%+, RR 2.0+, no earnings)."
      : "No stocks match the current filters";
    tbody.innerHTML = `<tr><td colspan="12" class="loading">${msg}</td></tr>`;
    return;
  }

  const rows = filteredResults.map((r) => {
    const prob = r.probability || 0;
    const probClass = prob >= 0.65 ? "prob-high" : prob >= 0.55 ? "prob-mid" : "prob-low";
    const rr = r.rr_ratio || 0;
    const rrClass = rr >= 2 ? "rr-good" : rr >= 1.5 ? "rr-ok" : "rr-bad";
    const isSelected = r.code === selectedCode ? "selected" : "";
    const isFav = favorites.has(r.code);
    const earningsBadge = r.earnings_warning
      ? `<span class="earnings-warn" title="Earnings date: ${r.next_earnings_date || "upcoming"}">📅</span>`
      : "";
    const liqBadge = r.liquidity_warning
      ? `<span class="liq-warn" title="Liquidity warning: avg daily volume under $1M. Watch for slippage.">💧</span>`
      : "";
    const isRec = r.score >= 60 && r.probability >= 0.60 && r.rr_ratio >= 2.0 && !r.earnings_warning;
    const recBadge = isRec ? `<span class="rec-badge" title="Recommended (Score, Prob, RR all above threshold)">★</span>` : "";

    const allPatterns = r.patterns || [];
    const visibleTags = allPatterns.slice(0, 3)
      .map((p) => `<span class="pattern-tag">${p.label}</span>`)
      .join("");
    const extra = allPatterns.length - 3;
    const patternTags = visibleTags + (extra > 0 ? `<span class="pattern-tag-more">+${extra}</span>` : "");

    return `
      <tr class="${isSelected}" data-code="${r.code}">
        <td class="star-cell"><button class="fav-btn${isFav ? " fav-active" : ""}" data-code="${r.code}">${isFav ? "⭐" : "☆"}</button></td>
        <td><strong>${r.code}</strong>${earningsBadge}${liqBadge}${recBadge}</td>
        <td>${escHtml(r.name || r.code)}</td>
        <td>
          <div class="score-cell">
            <div class="score-bar-bg">
              <div class="score-bar-fill" style="width:${r.score}%"></div>
            </div>
            <span class="score-num">${r.score}</span>
          </div>
        </td>
        <td style="text-align:center">${scoreDeltaHtml(r.score, prevScores, r.code)}</td>
        <td style="text-align:center">${scoreDeltaHtml(r.score, weekScores, r.code)}</td>
        <td><span class="prob-badge ${probClass}">${Math.round(prob * 100)}%</span></td>
        <td class="price">$${fmt(r.price)}</td>
        <td class="price price-target">
          $${fmt(r.target)}
          <span class="target-weeks">${r.weeks_min || 2}–${r.weeks_max || 4}wks</span>
        </td>
        <td class="price price-stop">$${fmt(r.stop_loss)}</td>
        <td class="${rrClass}">${rr.toFixed(1)}:1</td>
        <td><div class="pattern-tags">${patternTags}</div></td>
      </tr>
    `;
  });

  tbody.innerHTML = rows.join("");

  tbody.querySelectorAll(".fav-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => toggleFavorite(btn.dataset.code, e));
  });

  tbody.querySelectorAll("tr[data-code]").forEach((tr) => {
    tr.addEventListener("click", () => {
      const code = tr.dataset.code;
      openChart(code);
    });
  });
}

function fmt(n) {
  if (n == null) return "-";
  const num = Number(n);
  const decimals = num < 1000 ? 2 : 0;
  return num.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ── Chart panel ───────────────────────────────────────────────────
function openChart(code) {
  const stock = filteredResults.find((r) => r.code === code)
             || allResults.find((r) => r.code === code);
  if (!stock) return;

  savedScrollY = window.scrollY;
  selectedCode = code;

  document.querySelectorAll("#results-body tr").forEach((tr) => {
    tr.classList.toggle("selected", tr.dataset.code === code);
  });

  const panel = document.getElementById("chart-panel");
  panel.classList.remove("hidden");
  document.getElementById("chart-title").textContent =
    `${stock.code} ${escHtml(stock.name || stock.code)} — Score ${stock.score} / Prob ${Math.round(stock.probability * 100)}%`;

  try {
    ChartModule.render("chart-container", stock);
  } catch (e) {
    console.error("Chart render error:", e);
    document.getElementById("chart-container").innerHTML =
      `<div style="padding:20px;color:#7d8590">Chart render failed: ${e.message}</div>`;
  }

  _chartStock = stock;
  _renderOrderMemo(stock, null);

  const ind = stock.indicators || {};
  const details = [
    { label: "RSI", value: ind.rsi != null ? `${ind.rsi}` : "-" },
    { label: "ADX", value: ind.adx != null ? `${ind.adx}` : "-" },
    { label: "Vol Ratio", value: ind.vol_ratio != null ? `${ind.vol_ratio}×` : "-" },
    { label: "Avg Volume", value: ind.avg_daily_value != null
        ? `$${ind.avg_daily_value >= 1000
            ? (ind.avg_daily_value / 1000).toFixed(1) + "B"
            : ind.avg_daily_value.toFixed(1) + "M"}/day${stock.liquidity_warning ? " 💧" : ""}`
        : "-" },
    { label: "Target", value: stock.target ? `$${fmt(stock.target)}` : "-" },
    { label: "Est. Period", value: (stock.weeks_min && stock.weeks_max) ? `${stock.weeks_min}–${stock.weeks_max}wks` : "-" },
    { label: "Stop Loss", value: stock.stop_loss ? `$${fmt(stock.stop_loss)}` : "-" },
    { label: "RR Ratio", value: stock.rr_ratio ? `${stock.rr_ratio.toFixed(1)}:1` : "-" },
    { label: "RS Score", value: stock.rs != null ? `${stock.rs}` : "-" },
  ];

  document.getElementById("signal-detail").innerHTML = details
    .map(
      (d) =>
        `<div class="signal-detail-item">
          <span class="label">${d.label}</span>
          <span class="value">${d.value}</span>
        </div>`
    )
    .join("");

  const patterns = stock.patterns || [];
  document.getElementById("pattern-list").innerHTML = patterns.length
    ? patterns.map((p) => {
        const pct = Math.round(p.confidence * 100);
        const cls = pct >= 80 ? "conf-high" : pct >= 60 ? "conf-mid" : "conf-low";
        return `<div class="pattern-list-item">
          <span class="pattern-tag">${escHtml(p.label)}</span>
          <div class="conf-bar-bg"><div class="conf-bar-fill ${cls}" style="width:${pct}%"></div></div>
          <span class="conf-pct ${cls}">${pct}%</span>
        </div>`;
      }).join("")
    : `<span class="conf-empty">No patterns detected</span>`;

  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

function closeChart() {
  selectedCode = null;
  _chartStock  = null;
  _indHelpOpen = false;
  document.getElementById("chart-panel").classList.add("hidden");
  document.getElementById("order-memo").innerHTML = "";
  const hp = document.getElementById("ind-help-panel");
  if (hp) { hp.classList.add("hidden"); hp.dataset.built = ""; hp.innerHTML = ""; }
  ChartModule.destroy();
  document.querySelectorAll("#results-body tr.selected").forEach((tr) =>
    tr.classList.remove("selected")
  );
  window.scrollTo({ top: savedScrollY, behavior: "instant" });
}

// ── Order memo with entry override ───────────────────────────────────────────
function _renderOrderMemo(stock, overrideEntry) {
  const entry  = overrideEntry != null ? overrideEntry : stock.price;
  const target = stock.target;
  const stop   = stock.stop_loss;

  let rrHtml;
  if (entry != null && target != null && stop != null && entry !== stop) {
    const rr   = (target - entry) / (entry - stop);
    const sign = overrideEntry != null && stock.price != null
      ? (overrideEntry - stock.price) / stock.price * 100
      : null;
    const rrCls  = rr >= 2 ? "rr-good" : rr >= 1.5 ? "rr-ok" : "rr-bad";
    const verdict = rr >= 1.5
      ? `<span class="entry-ok">✓ Entry OK</span>`
      : `<span class="entry-ng">✗ Skip (poor RR)</span>`;
    const gapStr = sign != null
      ? `<span class="entry-gap ${sign > 0 ? "entry-gap-up" : "entry-gap-dn'}">${sign >= 0 ? "+" : ""}${sign.toFixed(1)}% vs scan</span>`
      : "";
    rrHtml = `<span class="order-val ${rrCls}" id="order-rr-val">${rr >= 0 ? rr.toFixed(1) : "-"}:1</span>${gapStr} ${verdict}`;
  } else {
    rrHtml = `<span class="order-val" id="order-rr-val">-</span>`;
  }

  const isRec = stock.score >= 60 && stock.probability >= 0.60 && stock.rr_ratio >= 2.0 && !stock.earnings_warning;

  document.getElementById("order-memo").innerHTML = `
    <div class="order-memo">
      <div class="order-memo-title">📝 Order Memo <button class="ind-help-btn" onclick="toggleIndHelp()" title="Indicator guide">?</button></div>
      <div class="order-row">
        <span class="order-label">Entry Price</span>
        <div class="order-entry-wrap">
          <span class="order-hint-prefix">$</span>
          <input id="order-entry-input" class="order-entry-input" type="number" step="0.01"
            value="${entry != null ? Number(entry).toFixed(2) : ""}"
            placeholder="${stock.price != null ? Number(stock.price).toFixed(2) : ""}"
            oninput="recalcOrderMemo()" />
          <button class="order-entry-reset" onclick="recalcOrderMemo(true)" title="Reset to scan price">↺</button>
        </div>
        <span class="order-hint">Scan close: $${fmt(stock.price)}</span>
      </div>
      <div class="order-row">
        <span class="order-label">Target</span>
        <span class="order-val order-target">$${fmt(target)}</span>
        <span class="order-hint">${stock.weeks_min || 2}–${stock.weeks_max || 4}wks</span>
      </div>
      <div class="order-row">
        <span class="order-label">Stop Loss</span>
        <span class="order-val order-stop">$${fmt(stop)}</span>
      </div>
      <div class="order-row">
        <span class="order-label">RR Ratio</span>
        ${rrHtml}
      </div>
      ${stock.blue_sky ? `<div class="order-alert order-alert-sky">🌤 All-time high breakout (${stock.sky_years}+ yr high) — no overhead resistance. Shallow pullbacks likely.</div>` : stock.at_52w_high ? `<div class="order-alert order-alert-sky">📈 52-week high breakout — cleared recent resistance. Potential new trend.</div>` : ""}
      ${stock.earnings_warning ? `<div class="order-alert order-alert-earnings">📅 Earnings ${stock.next_earnings_date || "upcoming"} — caution on entry</div>` : ""}
      ${stock.liquidity_warning ? `<div class="order-alert order-alert-liq">💧 Low liquidity: avg daily volume under $1M — watch for slippage. Consider split entry.</div>` : ""}
      ${isRec && (overrideEntry == null) ? `<div class="order-alert order-alert-rec">★ Recommended (Score, Prob, RR all above threshold)</div>` : ""}
    </div>
  `;
}

function recalcOrderMemo(reset) {
  if (!_chartStock) return;
  if (reset) {
    _renderOrderMemo(_chartStock, null);
    return;
  }
  const input = document.getElementById("order-entry-input");
  if (!input) return;
  const val = parseFloat(input.value);
  _renderOrderMemo(_chartStock, isNaN(val) || val <= 0 ? null : val);
  const next = document.getElementById("order-entry-input");
  if (next) { next.focus(); next.setSelectionRange(next.value.length, next.value.length); }
}

// ── Indicator help panel ────────────────────────────────────────────────
const IND_HELP = [
  {
    name: "RSI",
    ideal: "50–65",
    warn: "Above 75 / Below 25",
    desc: "Relative Strength Index over 14 days (0–100). Ideal entry zone for uptrends is 50–65. Above 75 is overbought — risk of buying the top. Below 30 recovering from oversold is suitable for reversal plays combined with a pattern signal.",
  },
  {
    name: "ADX",
    ideal: "25+",
    warn: "Below 20",
    desc: "Measures trend strength (0–100), direction-neutral. Above 25 indicates a clear trend; above 40 is a strong trend. Below 20 suggests a ranging market where breakout signals have a higher rate of failure.",
  },
  {
    name: "Vol Ratio",
    ideal: "1.5× or more",
    warn: "Below 1.0×",
    desc: "Today's volume ÷ 20-day average volume. Volume confirmation is critical for breakouts and reversals. 1.5× or more increases signal reliability; 2× or more may indicate institutional activity. Breakouts on low volume are prone to being false.",
  },
  {
    name: "RR Ratio",
    ideal: "2.0+",
    warn: "Below 1.5",
    desc: "(Target − Entry) ÷ (Entry − Stop). A ratio of 2:1 means you win twice as much as you risk per trade. At 50% win rate, a 2:1 RR is still profitable over time. Aim for 1.5 minimum, 2.0 ideally. Avoid below 1.0.",
  },
  {
    name: "RS Score",
    ideal: "60+",
    warn: "Below 40",
    desc: "Relative strength vs the S&P 500 (0–100). Higher means the stock outperforms the broader market. Above 80 means top 20% of all scanned stocks. Strong RS stocks tend to move sharply on market rebounds.",
  },
  {
    name: "Daily Volume (Liquidity)",
    ideal: "$1M/day+",
    warn: "Under $1M/day 💧",
    desc: "Estimated daily dollar volume (20-day avg shares × price). For swing trading, liquidity is critical — you need to be able to sell when you want. Under $1M/day means a thin order book with slippage risk. $5M+ is comfortable for most position sizes; $10M+ allows institutional-size trades. 💧 mark indicates under $1M/day.",
  },
];

function toggleIndHelp() {
  let modal = document.getElementById("ind-help-modal");
  if (!modal) {
    modal = document.createElement("div");
    modal.id = "ind-help-modal";
    modal.className = "help-modal-overlay hidden";
    modal.innerHTML = `
      <div class="help-modal-box">
        <div class="help-modal-head">
          Indicator Guide
          <button class="help-modal-close" aria-label="Close">✕</button>
        </div>
        <div class="help-modal-body">
          ${IND_HELP.map(ind => `
            <div class="ind-help-row">
              <div class="ind-help-name">${ind.name}</div>
              <div class="ind-help-body">
                <div class="ind-help-desc">${ind.desc}</div>
                <div class="ind-help-tags">
                  <span class="ind-tag ind-tag-ideal">Ideal: ${ind.ideal}</span>
                  <span class="ind-tag ind-tag-warn">Caution: ${ind.warn}</span>
                </div>
              </div>
            </div>`).join("")}
        </div>
      </div>
    `;
    modal.addEventListener("click", (e) => {
      if (e.target === modal) modal.classList.add("hidden");
    });
    modal.querySelector(".help-modal-close").addEventListener("click", () => {
      modal.classList.add("hidden");
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") modal.classList.add("hidden");
    });
    document.body.appendChild(modal);
  }
  modal.classList.toggle("hidden");
}

// ── Event wiring ─────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadFavorites();
  loadData();

  ["filter-pattern", "filter-prob", "filter-score", "filter-rr", "filter-sector"].forEach((id) => {
    document.getElementById(id).addEventListener("change", applyFilters);
  });
  document.getElementById("filter-search").addEventListener("input", applyFilters);

  document.getElementById("preset").addEventListener("change", (e) => {
    const preset = PRESETS[e.target.value];
    if (!preset) return;
    document.getElementById("filter-pattern").value = preset.pattern;
    document.getElementById("filter-prob").value = preset.prob;
    document.getElementById("filter-score").value = preset.score;
    document.getElementById("filter-rr").value = preset.rr;
    document.getElementById("filter-sector").value = preset.sector;
    applyFilters();
  });

  document.querySelectorAll(".sort-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.sort;
      if (currentSort.key === key) {
        currentSort.asc = !currentSort.asc;
      } else {
        currentSort = { key, asc: false };
      }
      document.querySelectorAll(".sort-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      sortResults();
    });
  });

  document.getElementById("chart-close").addEventListener("click", closeChart);

  document.getElementById("preset-help-btn").addEventListener("click", () => {
    const tip = document.getElementById("preset-tooltip");
    const btn = document.getElementById("preset-help-btn");
    const hidden = tip.classList.toggle("hidden");
    btn.classList.toggle("active", !hidden);
  });

  document.getElementById("rec-toggle-btn").addEventListener("click", () => {
    showRecOnly = !showRecOnly;
    document.getElementById("rec-toggle-btn").classList.toggle("fav-toggle-active", showRecOnly);
    applyFilters();
  });

  document.getElementById("fav-toggle-btn").addEventListener("click", () => {
    showFavoritesOnly = !showFavoritesOnly;
    document.getElementById("fav-toggle-btn").classList.toggle("fav-toggle-active", showFavoritesOnly);
    applyFilters();
  });

});
