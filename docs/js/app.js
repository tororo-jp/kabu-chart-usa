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
    `⭐ お気に入り${count > 0 ? ` (${count})` : ""}`;
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
  if (!(code in historical)) return `<span class="score-delta score-delta-new">新規</span>`;
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
      scanMeta.generated_at ? `最終更新：${scanMeta.generated_at}` : "";
    document.getElementById("stat-scanned").textContent = scanMeta.total_scanned.toLocaleString();
    document.getElementById("stat-signals").textContent = scanMeta.total_signals.toLocaleString();

    _buildSectorFilter();
    _renderMarketBanner();
    applyFilters();

    const urlCode = new URLSearchParams(window.location.search).get("code");
    if (urlCode) openChart(urlCode);
  } catch (e) {
    const tbody = document.getElementById("results-body");
    tbody.innerHTML = `<tr><td colspan="12" class="loading" style="color:#f85149">データの読み込みに失敗しました：${e.message}</td></tr>`;
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
    ? `🟢 <strong>強気市場</strong> — S&amp;P 500 ${sp500} は200MA ${sma200} を上回っています。エントリーに有利な環境です。`
    : `🔴 <strong>弱気市場</strong> — S&amp;P 500 ${sp500} は200MA ${sma200} を下回っています。新規エントリーには注意が必要です。`;
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
      ? "お気に入りがありません。☆をクリックして追加してください。"
      : showRecOnly
      ? "推奨候補なし（スコア60以上、確率60%以上、RR 2.0以上、決算なし）"
      : "現在のフィルターに一致する銘柄がありません";
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
      `<div style="padding:20px;color:#7d8590">チャートの描画に失敗しました：${e.message}</div>`;
  }

  _chartStock = stock;
  _renderOrderMemo(stock, null);

  const ind = stock.indicators || {};
  const details = [
    { label: "RSI", value: ind.rsi != null ? `${ind.rsi}` : "-" },
    { label: "ADX", value: ind.adx != null ? `${ind.adx}` : "-" },
    { label: "出来高比", value: ind.vol_ratio != null ? `${ind.vol_ratio}×` : "-" },
    { label: "平均出来高", value: ind.avg_daily_value != null
        ? `$${ind.avg_daily_value >= 1000
            ? (ind.avg_daily_value / 1000).toFixed(1) + "B"
            : ind.avg_daily_value.toFixed(1) + "M"}/日${stock.liquidity_warning ? " 💧" : ""}`
        : "-" },
    { label: "目標", value: stock.target ? `$${fmt(stock.target)}` : "-" },
    { label: "予想期間", value: (stock.weeks_min && stock.weeks_max) ? `${stock.weeks_min}–${stock.weeks_max}週` : "-" },
    { label: "損切り", value: stock.stop_loss ? `$${fmt(stock.stop_loss)}` : "-" },
    { label: "RR比率", value: stock.rr_ratio ? `${stock.rr_ratio.toFixed(1)}:1` : "-" },
    { label: "RSスコア", value: stock.rs != null ? `${stock.rs}` : "-" },
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
    : `<span class="conf-empty">パターンが検出されませんでした</span>`;

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
      ? `<span class="entry-ok">✓ エントリーOK</span>`
      : `<span class="entry-ng">✗ スキップ（RR不足）</span>`;
    const gapStr = sign != null
      ? `<span class="entry-gap ${sign > 0 ? "entry-gap-up" : "entry-gap-dn'}">${sign >= 0 ? "+" : ""}${sign.toFixed(1)}%（スキャン比）</span>`
      : "";
    rrHtml = `<span class="order-val ${rrCls}" id="order-rr-val">${rr >= 0 ? rr.toFixed(1) : "-"}:1</span>${gapStr} ${verdict}`;
  } else {
    rrHtml = `<span class="order-val" id="order-rr-val">-</span>`;
  }

  const isRec = stock.score >= 60 && stock.probability >= 0.60 && stock.rr_ratio >= 2.0 && !stock.earnings_warning;

  document.getElementById("order-memo").innerHTML = `
    <div class="order-memo">
      <div class="order-memo-title">📝 注文メモ <button class="ind-help-btn" onclick="toggleIndHelp()" title="インジケーターガイド">?</button></div>
      <div class="order-row">
        <span class="order-label">エントリー価格</span>
        <div class="order-entry-wrap">
          <span class="order-hint-prefix">$</span>
          <input id="order-entry-input" class="order-entry-input" type="number" step="0.01"
            value="${entry != null ? Number(entry).toFixed(2) : ""}"
            placeholder="${stock.price != null ? Number(stock.price).toFixed(2) : ""}"
            oninput="recalcOrderMemo()" />
          <button class="order-entry-reset" onclick="recalcOrderMemo(true)" title="スキャン価格にリセット">↺</button>
        </div>
        <span class="order-hint">スキャン終値：$${fmt(stock.price)}</span>
      </div>
      <div class="order-row">
        <span class="order-label">目標</span>
        <span class="order-val order-target">$${fmt(target)}</span>
        <span class="order-hint">${stock.weeks_min || 2}–${stock.weeks_max || 4}週</span>
      </div>
      <div class="order-row">
        <span class="order-label">損切り</span>
        <span class="order-val order-stop">$${fmt(stop)}</span>
      </div>
      <div class="order-row">
        <span class="order-label">RR比率</span>
        ${rrHtml}
      </div>
      ${stock.blue_sky ? `<div class="order-alert order-alert-sky">🌤 史上最高値ブレイクアウト（${stock.sky_years}年以上ぶり高値）— 上値抵抗なし。浅い押し目が予想されます。</div>` : stock.at_52w_high ? `<div class="order-alert order-alert-sky">📈 52週高値ブレイクアウト — 直近レジスタンスを突破。新トレンドの可能性。</div>` : ""}
      ${stock.earnings_warning ? `<div class="order-alert order-alert-earnings">📅 決算 ${stock.next_earnings_date || "予定"} — エントリーに注意</div>` : ""}
      ${stock.liquidity_warning ? `<div class="order-alert order-alert-liq">💧 流動性低下：平均日次出来高$1M未満 — スリッページに注意。分割エントリーを検討。</div>` : ""}
      ${isRec && (overrideEntry == null) ? `<div class="order-alert order-alert-rec">★ おすすめ（スコア、確率、RRすべて基準以上）</div>` : ""}
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
    warn: "75超 / 25未満",
    desc: "14日間の相対力指数（0–100）。上昇トレンドへの理想的なエントリーゾーンは50–65。75超は買われすぎ — 高値掴みのリスクあり。30以下から回復中は、パターンシグナルと組み合わせた反転プレーに適している。",
  },
  {
    name: "ADX",
    ideal: "25以上",
    warn: "20未満",
    desc: "トレンド強度を測定（0–100）、方向性は問わない。25超は明確なトレンドあり、40超は強いトレンド。20未満はレンジ相場を示し、ブレイクアウトシグナルの失敗率が高くなる。",
  },
  {
    name: "出来高比",
    ideal: "1.5倍以上",
    warn: "1.0倍未満",
    desc: "当日出来高 ÷ 20日平均出来高。ブレイクアウトや反転においては出来高の確認が重要。1.5倍以上でシグナルの信頼性が向上、2倍以上は機関投資家の活動を示す可能性あり。出来高の少ないブレイクアウトはダマシになりやすい。",
  },
  {
    name: "RR比率",
    ideal: "2.0以上",
    warn: "1.5未満",
    desc: "（目標 − エントリー）÷（エントリー − 損切り）。2:1は1回のリスクに対して2倍の利益が得られることを意味する。勝率50%でも2:1のRRなら長期的にプラスになる。最低1.5、理想は2.0を目指す。1.0未満は避けること。",
  },
  {
    name: "RSスコア",
    ideal: "60以上",
    warn: "40未満",
    desc: "S&P 500対比の相対力スコア（0–100）。高いほど市場平均を上回るパフォーマンス。80超はスキャン全銘柄の上位20%。RSスコアが高い銘柄は市場反発時に急騰しやすい。",
  },
  {
    name: "日次出来高（流動性）",
    ideal: "$100万/日以上",
    warn: "$100万/日未満 💧",
    desc: "推定日次ドル出来高（20日平均株数×価格）。スイングトレードでは流動性が重要 — 売りたい時に売れる必要がある。$100万/日未満は板が薄くスリッページリスクあり。$500万以上は大半のポジションサイズに問題なし、$1000万以上なら機関投資家規模の取引も可能。💧マークは$100万/日未満を示す。",
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
          インジケーターガイド
          <button class="help-modal-close" aria-label="閉じる">✕</button>
        </div>
        <div class="help-modal-body">
          ${IND_HELP.map(ind => `
            <div class="ind-help-row">
              <div class="ind-help-name">${ind.name}</div>
              <div class="ind-help-body">
                <div class="ind-help-desc">${ind.desc}</div>
                <div class="ind-help-tags">
                  <span class="ind-tag ind-tag-ideal">理想：${ind.ideal}</span>
                  <span class="ind-tag ind-tag-warn">注意：${ind.warn}</span>
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
