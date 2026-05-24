/* Position management page — data stored in localStorage */

const POSITIONS_KEY   = "usa_positions";
const PNL_HISTORY_KEY = "usa_pnl_history";
const MONTHLY_REQUIRED = 7;   // required (%)
const MONTHLY_TARGET   = 10;  // target (%)
const GAUGE_MAX        = 15;  // gauge scale max (%)
const DATA_URL       = "data/results.json";

let allPositions = [];
let stockData    = {};
let scanMeta     = {};
let closingId    = null;
let pnlHistory   = {};
let showAfterTax = false;
let _benchJson   = null;   // cached benchmark.json

const STOP_STAGES = [
  { label: 'Initial',     cls: 'stage-initial',   title: 'Initial stop: entry − ATR×2 (no change needed)' },
  { label: 'Breakeven',   cls: 'stage-breakeven', title: 'Price ≥ entry + ATR → raise stop to entry (no risk)' },
  { label: 'Lock Profit', cls: 'stage-profit',    title: '50%+ to target → raise stop to entry + ATR' },
  { label: 'Trailing',    cls: 'stage-trailing',  title: '70%+ to target → trail stop at current − ATR×1.5' },
];

let formScanAtr = null;

// ── Bootstrap ─────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await loadScanData();
  loadPositions();
  loadPnlHistory();
  setDefaultDate();
  render();
});

async function loadScanData() {
  try {
    const res = await fetch(DATA_URL);
    if (!res.ok) return;
    const json = await res.json();
    scanMeta = { generated_at: json.generated_at || "" };
    (json.results || []).forEach(r => { stockData[r.code] = r; });
    document.getElementById("pos-scan-time").textContent =
      scanMeta.generated_at ? `Last Scan: ${scanMeta.generated_at}` : "";
    document.getElementById("pos-scan-label").textContent =
      scanMeta.generated_at ? `Scan: ${scanMeta.generated_at}` : "";
  } catch (e) {
    console.warn("results.json load failed:", e);
  }
}

function setDefaultDate() {
  const today = new Date().toISOString().slice(0, 10);
  document.getElementById("f-date").value      = today;
  document.getElementById("close-date").value  = today;
}

// ── localStorage ──────────────────────────────────────────────────────
function loadPositions() {
  try {
    const saved = localStorage.getItem(POSITIONS_KEY);
    allPositions = saved ? JSON.parse(saved) : [];
  } catch {
    allPositions = [];
  }
}

function savePositions() {
  localStorage.setItem(POSITIONS_KEY, JSON.stringify(allPositions));
}

function loadPnlHistory() {
  try {
    const saved = localStorage.getItem(PNL_HISTORY_KEY);
    pnlHistory = saved ? JSON.parse(saved) : {};
  } catch { pnlHistory = {}; }
}

function savePnlHistory() {
  localStorage.setItem(PNL_HISTORY_KEY, JSON.stringify(pnlHistory));
}

function _histEntry(v) {
  if (v == null)           return { pnl: 0, cost: null };
  if (typeof v === "number") return { pnl: v, cost: null };
  return { pnl: v.pnl ?? 0, cost: v.cost ?? null };
}

function applyTax(pnl) {
  return showAfterTax && pnl > 0 ? Math.round(pnl * 0.8) : pnl;
}

function _timeFmt(t) {
  const s = typeof t === "string" ? t
    : `${t.year}-${String(t.month).padStart(2,"0")}-${String(t.day).padStart(2,"0")}`;
  return s.slice(5).replace("-", "/");
}

function toggleTax() {
  showAfterTax = !showAfterTax;
  const btn = document.getElementById("tax-btn");
  if (btn) {
    btn.textContent = showAfterTax ? "After Tax 20%" : "Pre-tax";
    btn.classList.toggle("tax-active", showAfterTax);
  }
  render();
}

// ── Render ─────────────────────────────────────────────────────────────
function render() {
  renderSummary();
  renderMonthlyPerf();
  renderOpen();
  renderHistory();
  renderPnlChart();
  renderComparisonChart();
}

// ── Monthly performance ──────────────────────────────────────────────────────
function calcMonthlyPerf() {
  const ym = new Date().toISOString().slice(0, 7);
  let pnl = 0, cost = 0;

  allPositions.filter(p => p.status !== "open" && (p.close_date || "").startsWith(ym)).forEach(p => {
    pnl  += (p.close_price - p.entry_price) * p.shares;
    cost += p.entry_price * p.shares;
  });

  allPositions.filter(p => p.status === "open").forEach(p => {
    const cur = currentPrice(p);
    if (cur != null) pnl += (cur - p.entry_price) * p.shares;
    cost += p.entry_price * p.shares;
  });

  const displayPnl = applyTax(Math.round(pnl));
  return { pnl: displayPnl, cost: Math.round(cost), pct: cost > 0 ? displayPnl / cost * 100 : null };
}

function renderMonthlyPerf() {
  const wrap = document.getElementById("monthly-perf-wrap");
  if (!wrap) return;

  const { pnl, cost, pct } = calcMonthlyPerf();
  if (cost === 0 || pct === null) { wrap.style.display = "none"; return; }
  wrap.style.display = "";

  document.getElementById("monthly-perf-pct").textContent = pct >= 0 ? "+" + pct.toFixed(1) + "%" : pct.toFixed(1) + "%";
  document.getElementById("monthly-perf-pct").className =
    "monthly-perf-pct " + (pct >= 0 ? "pnl-pos" : "pnl-neg");

  const subEl = document.getElementById("monthly-perf-sub");
  if (subEl) {
    const pnlSign = pnl >= 0 ? "+" : "-";
    subEl.textContent = `Capital $${cost.toLocaleString("en-US")} / P&L ${pnlSign}$${Math.abs(pnl).toLocaleString("en-US")}`;
  }

  let badgeText, badgeCls, fillCls;
  if (pct >= MONTHLY_TARGET) {
    badgeText = "Target Hit ✓"; badgeCls = "mpb-achieved"; fillCls = "gf-green";
  } else if (pct >= MONTHLY_REQUIRED) {
    badgeText = "Required Hit";   badgeCls = "mpb-required"; fillCls = "gf-blue";
  } else if (pct >= 0) {
    badgeText = `${(MONTHLY_REQUIRED - pct).toFixed(1)}% to Required`;
    badgeCls = "mpb-progress"; fillCls = "gf-yellow";
  } else {
    badgeText = "In Loss";    badgeCls = "mpb-loss";     fillCls = "gf-red";
  }

  const badgeEl = document.getElementById("monthly-perf-badge");
  badgeEl.textContent = badgeText;
  badgeEl.className   = "monthly-perf-badge " + badgeCls;

  const fillEl  = document.getElementById("gauge-fill");
  const fillPct = Math.max(0, Math.min(100, (pct / GAUGE_MAX) * 100));
  fillEl.style.width = fillPct + "%";
  fillEl.className   = "gauge-fill " + fillCls;
}

function renderSummary() {
  const open = allPositions.filter(p => p.status === "open");
  let totalPnl = 0, totalCost = 0;
  open.forEach(p => {
    const cur = currentPrice(p);
    if (cur != null) {
      totalPnl  += (cur - p.entry_price) * p.shares;
      totalCost += p.entry_price * p.shares;
    } else {
      totalCost += p.entry_price * p.shares;
    }
  });
  const rawPnl      = Math.round(totalPnl);
  const displayPnl  = applyTax(rawPnl);
  const pct = totalCost > 0 ? displayPnl / totalCost * 100 : 0;
  const pnlClass = displayPnl > 0 ? "pnl-pos" : displayPnl < 0 ? "pnl-neg" : "pnl-zero";

  document.getElementById("sum-count").textContent = open.length;
  const pnlEl = document.getElementById("sum-pnl");
  const pnlSign = displayPnl >= 0 ? "+" : "-";
  pnlEl.textContent = pnlSign + "$" + Math.abs(displayPnl).toLocaleString("en-US");
  pnlEl.className   = `sc-value ${pnlClass}`;
  document.getElementById("sum-pnl-pct").textContent =
    (pct >= 0 ? "+" : "") + pct.toFixed(1) + "%";
  document.getElementById("sum-cost").textContent =
    "$" + Math.round(totalCost).toLocaleString("en-US");

  const upgradeCount = open.filter(p => calcStopAdvice(p)?.canUpgrade).length;
  const upgradeCard  = document.getElementById("sum-upgrades-card");
  if (upgradeCard) {
    upgradeCard.style.display = upgradeCount > 0 ? '' : 'none';
    document.getElementById("sum-upgrades").textContent = upgradeCount;
  }

  if (open.length > 0) {
    const today = new Date().toISOString().slice(0, 10);
    pnlHistory[today] = { pnl: rawPnl, cost: Math.round(totalCost) };
    savePnlHistory();
  }
}

function renderOpen() {
  const open  = allPositions.filter(p => p.status === "open");
  const tbody = document.getElementById("pos-body");

  if (open.length === 0) {
    tbody.innerHTML = `<tr><td colspan="14" class="pos-empty">
      No open positions.<br>
      Click "＋ Add Position" to get started.
    </td></tr>`;
    return;
  }

  tbody.innerHTML = open.map(p => {
    const stock  = stockData[p.code];
    const cur    = currentPrice(p);
    const target = p.target;
    const stop   = p.stop_loss;

    let pnlHtml = "-";
    if (cur != null) {
      const pnl    = (cur - p.entry_price) * p.shares;
      const pnlPct = (cur - p.entry_price) / p.entry_price * 100;
      const cls    = pnl >= 0 ? "pnl-pos" : "pnl-neg";
      const pnlSign = pnl >= 0 ? "+" : "-";
      pnlHtml = `<span class="${cls}">${pnlSign}$${Math.abs(Math.round(pnl)).toLocaleString("en-US")}</span>
                 <br><small class="${cls}">${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(1)}%</small>`;
    }

    let progHtml = "-";
    if (cur != null && target != null && stop != null && target > stop) {
      const range      = target - stop;
      const entryPct   = clamp((p.entry_price - stop) / range * 100);
      const curPct     = clamp((cur - stop) / range * 100);
      const fillClass  = cur >= p.entry_price ? "prog-fill-pos" : "prog-fill-neg";
      const stopLabel  = "$" + fmt(stop);
      const tgtLabel   = "$" + fmt(target);
      progHtml = `
        <div class="prog-wrap">
          <div class="prog-bg">
            <div class="prog-fill ${fillClass}" style="width:${curPct}%"></div>
            <div class="prog-entry-mark" style="left:${entryPct}%" title="Entry $${fmt(p.entry_price)}"></div>
          </div>
          <div class="prog-label"><span>${stopLabel}</span><span>${tgtLabel}</span></div>
        </div>`;
    }

    let toTargetHtml = "-", toStopHtml = "-";
    if (cur != null && target != null) {
      const pct = (target - cur) / cur * 100;
      const cls = pct <= 3 ? "near-target" : "";
      toTargetHtml = `<span class="${cls}">+${pct.toFixed(1)}%</span>`;
    }
    if (cur != null && stop != null) {
      const pct = (cur - stop) / cur * 100;
      const cls = pct <= 3 ? "near-stop" : "";
      toStopHtml = `<span class="${cls}">-${pct.toFixed(1)}%</span>`;
    }

    const advice = calcStopAdvice(p);
    let adviceHtml = '-';
    if (advice) {
      const st = STOP_STAGES[advice.stage];
      const upgBtn = advice.canUpgrade
        ? `<button class="apply-stop-btn" onclick="applyStopAdvice('${p.id}')">↑ Apply</button>`
        : '';
      adviceHtml = `<div class="stop-advice">
        <span class="stop-stage-badge ${st.cls}" title="${st.title}">${st.label}</span>
        <div class="stop-rec-price">$${fmt(advice.recommended)}</div>
        ${upgBtn}
      </div>`;
    }

    const score = stock?.score ?? null;
    const scoreCls = score == null ? "" : score >= 60 ? "score-hi" : score >= 40 ? "score-mid" : "score-lo";
    const scoreHtml = stock == null
      ? `<span class="score-gone" title="Not in today's scan">–</span>`
      : `<span class="${scoreCls}">${score}</span>`;

    const notInScan = stock == null
      ? `<span class="not-in-scan" title="Not in today's scan results">–</span>`
      : "";
    const curStr = cur != null ? `$${fmt(cur)}` : "-";

    return `<tr>
      <td><a href="index.html?code=${encodeURIComponent(p.code)}" class="code-link"><strong>${escHtml(p.code)}</strong></a>${notInScan}</td>
      <td>${escHtml(p.name)}</td>
      <td class="num">${p.shares.toLocaleString("en-US")}</td>
      <td class="num price">$${fmt(p.entry_price)}</td>
      <td class="num price">${curStr}</td>
      <td class="num">${pnlHtml}</td>
      <td>${progHtml}</td>
      <td class="num">${toTargetHtml}</td>
      <td class="num">${toStopHtml}</td>
      <td>${adviceHtml}</td>
      <td class="num">${scoreHtml}</td>
      <td>${escHtml(p.entry_date || "-")}</td>
      <td>${deadlineHtml(p)}</td>
      <td>
        <button class="pos-close-btn" onclick="showCloseModal('${p.id}')">Close</button>
        <button class="pos-del-btn"   onclick="deletePosition('${p.id}')">Delete</button>
      </td>
    </tr>`;
  }).join("");

  const hasUpgrades = open.some(p => calcStopAdvice(p)?.canUpgrade);
  const bulkBtn = document.getElementById("bulk-advice-btn");
  if (bulkBtn) bulkBtn.style.display = hasUpgrades ? '' : 'none';
}

function renderHistory() {
  const closed = allPositions.filter(p => p.status !== "open");
  const section = document.getElementById("history-section");
  if (closed.length === 0) { section.style.display = "none"; return; }
  section.style.display = "block";

  document.getElementById("history-body").innerHTML = closed.slice().reverse().map(p => {
    const pnl    = (p.close_price - p.entry_price) * p.shares;
    const pnlPct = (p.close_price - p.entry_price) / p.entry_price * 100;
    const cls    = pnl >= 0 ? "pnl-pos" : "pnl-neg";
    const pnlSign = pnl >= 0 ? "+" : "-";
    return `<tr>
      <td><strong>${escHtml(p.code)}</strong></td>
      <td>${escHtml(p.name)}</td>
      <td class="num">${p.shares.toLocaleString("en-US")}</td>
      <td class="num price">$${fmt(p.entry_price)}</td>
      <td class="num price">$${fmt(p.close_price)}</td>
      <td class="num">
        <span class="${cls}">${pnlSign}$${Math.abs(Math.round(pnl)).toLocaleString("en-US")}</span>
        <br><small class="${cls}">${pnlPct >= 0 ? "+" : ""}${pnlPct.toFixed(1)}%</small>
      </td>
      <td>${escHtml(p.entry_date || "-")}</td>
      <td>${escHtml(p.close_date || "-")}</td>
      <td><button class="pos-del-btn" onclick="deletePosition('${p.id}')">Delete</button></td>
    </tr>`;
  }).join("");
}

// ── P&L Chart (daily absolute) ────────────────────────────────────────────
function renderPnlChart() {
  const wrap = document.getElementById("pnl-chart-wrap");
  if (!wrap) return;

  const entries = Object.entries(pnlHistory)
    .filter(([, v]) => v != null)
    .sort((a, b) => a[0].localeCompare(b[0]));

  if (entries.length < 2) {
    wrap.style.display = "none";
    return;
  }
  wrap.style.display = "";

  const container = document.getElementById("pnl-chart-container");
  container.innerHTML = "";

  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth || 600,
    height: 200,
    layout:          { background: { color: "#0d1117" }, textColor: "#7d8590" },
    grid:            { vertLines: { color: "#21262d" }, horzLines: { color: "#21262d" } },
    timeScale:       { borderColor: "#30363d", tickMarkFormatter: _timeFmt },
    rightPriceScale: { borderColor: "#30363d" },
    crosshair:       { mode: 1 },
    handleScroll: false,
    handleScale:  false,
  });

  const data = entries.map(([date, v]) => {
    const { pnl } = _histEntry(v);
    return { time: date, value: applyTax(pnl) };
  });

  const hasPositive = data.some(d => d.value > 0);
  const lineColor   = hasPositive ? "#3fb950" : "#f85149";

  const series = chart.addAreaSeries({
    lineColor,
    topColor:    hasPositive ? "rgba(63,185,80,0.2)"  : "rgba(248,81,73,0.2)",
    bottomColor: "rgba(0,0,0,0)",
    lineWidth:   2,
    priceLineVisible:       false,
    lastValueVisible:       true,
    crosshairMarkerVisible: true,
    priceFormat: { type: "custom", formatter: v => {
      const sign = v >= 0 ? "+" : "-";
      return sign + "$" + Math.abs(Math.round(v)).toLocaleString("en-US");
    }},
  });

  series.setData(data);
  series.createPriceLine({ price: 0, color: "#484f58", lineWidth: 1, lineStyle: 2, axisLabelVisible: false });
  chart.timeScale().fitContent();

  const ro = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }));
  ro.observe(container);
}

// ── Benchmark fetch ────────────────────────────────────────────────────────
async function _fetchBenchmark(symbol, fromDate) {
  if (!_benchJson) {
    try {
      const res = await fetch("data/benchmark.json");
      if (res.ok) _benchJson = await res.json();
    } catch (e) {
      console.warn("benchmark.json load failed:", e);
    }
  }
  if (!_benchJson) return null;

  const key  = symbol === "^gspc" ? "sp500" : "nasdaq";
  const rows = (_benchJson[key] || []).filter(r => r.date >= fromDate);
  return rows.length ? rows : null;
}

// ── Benchmark comparison chart ───────────────────────────────────────────────
async function renderComparisonChart() {
  const wrap = document.getElementById("bench-chart-wrap");
  if (!wrap) return;

  const entries = Object.entries(pnlHistory)
    .filter(([, v]) => v != null)
    .sort((a, b) => a[0].localeCompare(b[0]));

  if (entries.length < 2) {
    wrap.style.display = "none";
    return;
  }

  const userSeries = entries.map(([date, v]) => {
    const { pnl, cost } = _histEntry(v);
    const pct = cost && cost > 0 ? applyTax(pnl) / cost * 100 : 0;
    return { time: date, value: pct };
  });

  const fromDate = entries[0][0];
  const [spData, nqData] = await Promise.all([
    _fetchBenchmark("^gspc", fromDate),
    _fetchBenchmark("^ixic", fromDate),
  ]);

  function normalizeBench(data) {
    if (!data || data.length === 0) return null;
    const base = data[0].close;
    return data.map(d => ({ time: d.date, value: (d.close / base - 1) * 100 }));
  }

  const spSeries = normalizeBench(spData);
  const nqSeries = normalizeBench(nqData);

  wrap.style.display = "";

  const container = document.getElementById("bench-chart-container");
  container.innerHTML = "";

  const pctFmt = { type: "custom", formatter: v => (v >= 0 ? "+" : "") + v.toFixed(2) + "%" };

  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth || 600,
    height: 240,
    layout:          { background: { color: "#0d1117" }, textColor: "#7d8590" },
    grid:            { vertLines: { color: "#21262d" }, horzLines: { color: "#21262d" } },
    timeScale:       { borderColor: "#30363d", tickMarkFormatter: _timeFmt },
    rightPriceScale: { borderColor: "#30363d" },
    crosshair:       { mode: 1 },
    handleScroll: false,
    handleScale:  false,
  });

  const userLine = chart.addLineSeries({
    color: "#3fb950", lineWidth: 2, title: "Mine",
    priceFormat: pctFmt, lastValueVisible: true, priceLineVisible: false,
  });
  userLine.setData(userSeries);
  userLine.createPriceLine({ price: 0, color: "#484f58", lineWidth: 1, lineStyle: 2, axisLabelVisible: false });

  if (spSeries) {
    const spLine = chart.addLineSeries({
      color: "#58a6ff", lineWidth: 1, lineStyle: 2, title: "S&P 500",
      priceFormat: pctFmt, lastValueVisible: true, priceLineVisible: false,
    });
    spLine.setData(spSeries);
  }

  if (nqSeries) {
    const nqLine = chart.addLineSeries({
      color: "#ffa348", lineWidth: 1, lineStyle: 2, title: "NASDAQ",
      priceFormat: pctFmt, lastValueVisible: true, priceLineVisible: false,
    });
    nqLine.setData(nqSeries);
  }

  const last = userSeries[userSeries.length - 1];
  const legendEl = document.getElementById("bench-legend-user");
  if (legendEl && last) {
    legendEl.textContent = `Mine ${last.value >= 0 ? "+" : ""}${last.value.toFixed(2)}%`;
  }

  chart.timeScale().fitContent();
  const ro = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }));
  ro.observe(container);
}

// ── Deadline ─────────────────────────────────────────────────────────────
function calcDeadline(p) {
  if (!p.entry_date) return null;
  const stock  = stockData[p.code];
  const weeks  = p.weeks_max ?? stock?.weeks_max ?? 4;
  const dt     = new Date(p.entry_date + "T00:00:00");
  dt.setDate(dt.getDate() + weeks * 7);
  return dt.toISOString().slice(0, 10);
}

function deadlineHtml(p) {
  const dl = calcDeadline(p);
  if (!dl) return "-";
  const today = new Date().toISOString().slice(0, 10);
  const daysLeft = Math.round((new Date(dl) - new Date(today)) / 86400000);
  const [, mm, dd] = dl.split("-");
  const dateStr = `${mm}/${dd}`;
  if (daysLeft < 0)  return `<span class="deadline-over">${dateStr} (overdue)</span>`;
  if (daysLeft <= 7) return `<span class="deadline-near">${dateStr} (${daysLeft}d left)</span>`;
  return `<span class="deadline-ok">${dateStr} (${daysLeft}d left)</span>`;
}

// ── Stop Advice ────────────────────────────────────────────────────────────
function calcStopAdvice(p) {
  const stock = stockData[p.code];
  const cur   = currentPrice(p);
  const atr   = stock?.indicators?.atr || p.initial_atr || (p.entry_price * 0.03);
  if (!cur || !atr || atr <= 0) return null;

  const entry    = p.entry_price;
  const target   = p.target;
  const range    = (target && target > entry) ? (target - entry) : null;
  const progress = range ? (cur - entry) / range : null;

  let stage, recommended;
  if (progress !== null && progress >= 0.7 && cur > entry) {
    stage       = 3;
    recommended = Math.round((cur - atr * 1.5) * 100) / 100;
  } else if (progress !== null && progress >= 0.5 && cur > entry) {
    stage       = 2;
    recommended = Math.round((entry + atr) * 100) / 100;
  } else if (cur >= entry + atr * 0.8) {
    stage       = 1;
    recommended = Math.round(entry * 100) / 100;
  } else {
    stage       = 0;
    recommended = Math.round((entry - atr * 2) * 100) / 100;
  }

  recommended = Math.min(recommended, Math.round((cur - 0.01) * 100) / 100);

  const currentStop = p.stop_loss ?? 0;
  const canUpgrade  = recommended > currentStop + cur * 0.003;
  return { stage, recommended, canUpgrade, atr: Math.round(atr * 100) / 100 };
}

function applyStopAdvice(id) {
  const p = allPositions.find(x => x.id === id);
  if (!p) return;
  const advice = calcStopAdvice(p);
  if (!advice || !advice.canUpgrade) return;
  p.stop_loss = advice.recommended;
  savePositions();
  render();
}

function applyAllAdvice() {
  let updated = 0;
  allPositions.forEach(p => {
    if (p.status !== 'open') return;
    const advice = calcStopAdvice(p);
    if (advice?.canUpgrade) { p.stop_loss = advice.recommended; updated++; }
  });
  if (updated > 0) { savePositions(); render(); }
}

// ── Add form ─────────────────────────────────────────────────────────────
function toggleForm() {
  const wrap = document.getElementById("pos-form-wrap");
  const isHidden = wrap.classList.toggle("hidden");
  document.getElementById("add-btn").textContent = isHidden ? "＋ Add Position" : "✕ Cancel";
  if (!isHidden) document.getElementById("f-code").focus();
  if (isHidden) { formScanAtr = null; }
  document.getElementById("form-error").textContent = "";
}

function autoFill() {
  const code  = document.getElementById("f-code").value.trim().toUpperCase();
  const stock = stockData[code];
  if (!stock) {
    document.getElementById("form-error").textContent =
      `Ticker "${code}" not found in today's scan results`;
    return;
  }
  document.getElementById("form-error").textContent = "";
  document.getElementById("f-name").value   = stock.name  || "";
  document.getElementById("f-entry").value  = stock.price || "";

  formScanAtr = stock.indicators?.atr ?? null;

  if (stock.target != null) {
    document.getElementById("f-target").value = stock.target;
  }

  recalcTargets();
}

function recalcTargets() {
  const entry = parseFloat(document.getElementById("f-entry").value);
  if (!entry || entry <= 0) return;

  if (formScanAtr !== null) {
    document.getElementById("f-stop").value =
      Math.round((entry - formScanAtr * 2) * 100) / 100;
  }
}

function submitAdd() {
  const code   = document.getElementById("f-code").value.trim().toUpperCase();
  const name   = document.getElementById("f-name").value.trim();
  const shares = parseFloat(document.getElementById("f-shares").value);
  const entry  = parseFloat(document.getElementById("f-entry").value);
  const date   = document.getElementById("f-date").value;
  const target = parseFloat(document.getElementById("f-target").value) || null;
  const stop   = parseFloat(document.getElementById("f-stop").value)   || null;
  const errEl  = document.getElementById("form-error");

  if (!code)           { errEl.textContent = "Please enter a ticker symbol"; return; }
  if (!shares || shares <= 0) { errEl.textContent = "Please enter share count"; return; }
  if (!entry  || entry  <= 0) { errEl.textContent = "Please enter entry price"; return; }

  const stock = stockData[code];
  allPositions.push({
    id:          Date.now().toString(),
    code,
    name:        name || stock?.name || code,
    shares,
    entry_price: entry,
    entry_date:  date,
    target:      target ?? stock?.target ?? null,
    stop_loss:   stop   ?? stock?.stop_loss ?? null,
    initial_atr: stock?.indicators?.atr ?? null,
    weeks_max:   stock?.weeks_max ?? null,
    status:      "open",
  });
  savePositions();

  ["f-code","f-name","f-shares","f-entry","f-target","f-stop"].forEach(id => {
    document.getElementById(id).value = "";
  });
  errEl.textContent = "";
  toggleForm();
  render();
}

// ── Close modal ────────────────────────────────────────────────────────────
function showCloseModal(id) {
  closingId = id;
  const p = allPositions.find(x => x.id === id);
  if (!p) return;
  const cur = currentPrice(p);
  document.getElementById("close-price").value = cur ?? p.entry_price;
  document.getElementById("close-date").value  = new Date().toISOString().slice(0, 10);
  const modal = document.getElementById("close-modal");
  modal.style.display = "flex";
}

function hideCloseModal() {
  document.getElementById("close-modal").style.display = "none";
  closingId = null;
}

function confirmClose() {
  if (!closingId) return;
  const price = parseFloat(document.getElementById("close-price").value);
  const date  = document.getElementById("close-date").value;
  if (!price || price <= 0) return;

  const pos = allPositions.find(p => p.id === closingId);
  if (pos) {
    pos.status      = "closed";
    pos.close_price = price;
    pos.close_date  = date;
  }
  savePositions();
  hideCloseModal();
  render();
}

// ── Delete ──────────────────────────────────────────────────────────────
function deletePosition(id) {
  const p = allPositions.find(x => x.id === id);
  if (!p) return;
  if (!confirm(`Delete ${p.code} ${p.name}?`)) return;
  allPositions = allPositions.filter(x => x.id !== id);
  savePositions();
  render();
}

// ── Helpers ─────────────────────────────────────────────────────────────
function currentPrice(p) {
  return stockData[p.code]?.price ?? null;
}

function clamp(v, lo = 0, hi = 100) {
  return Math.max(lo, Math.min(hi, v));
}

function fmt(n) {
  if (n == null) return "-";
  return Number(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function escHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
