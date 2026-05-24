/* Standalone backtest page — auto-loads and renders on DOMContentLoaded */

const BT_URL = "data/backtest.json";

function escBt(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

async function loadBacktest() {
  try {
    const res = await fetch(BT_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    render(data);
  } catch (e) {
    document.getElementById("bt-page").innerHTML =
      `<div class="bt-empty-page">
        No backtest data available.<br>
        Data will appear automatically once signals accumulate (updated weekly after US market close).<br>
        <small style="font-size:12px">${escBt(e.message)}</small>
      </div>`;
  }
}

function render(d) {
  const s = d.summary || {};
  const f = d.filter  || {};

  document.getElementById("bt-updated").textContent =
    d.generated_at ? `Updated: ${d.generated_at}` : "";

  document.getElementById("bt-filter-score").textContent    = `Score ≥ ${f.score_min ?? "-"}`;
  document.getElementById("bt-filter-prob").textContent     = `Prob ≥ ${f.prob_min != null ? Math.round(f.prob_min * 100) + "%" : "-"}`;
  document.getElementById("bt-filter-rr").textContent       = `RR ≥ ${f.rr_min ?? "-"}`;
  document.getElementById("bt-filter-limit").textContent    = `Max ${f.max_per_day ?? "-"}/day`;
  document.getElementById("bt-filter-cooldown").textContent = `Cooldown ${f.cooldown_days ?? "-"}d`;

  const wr      = s.win_rate;
  const wrPct   = wr != null ? Math.round(wr * 100) : "-";
  const wrClass = wr >= 0.60 ? "bt-good" : wr >= 0.50 ? "bt-mid" : "bt-bad";
  const sharpe  = s.sharpe_ratio;
  const sharpeCls = sharpe >= 1.5 ? "bt-good" : sharpe >= 0.8 ? "bt-mid" : "bt-bad";
  const dd      = s.max_drawdown;
  const ddCls   = dd <= 10 ? "bt-good" : dd <= 20 ? "bt-mid" : "bt-bad";

  document.getElementById("bt-summary-cards").innerHTML = `
    <div class="bt-card">
      <div class="bt-card-label">Signals</div>
      <div class="bt-card-value">${s.total_signals ?? "-"}</div>
      <div class="bt-card-sub">Closed ${s.completed ?? 0} / Open ${s.open ?? 0}</div>
    </div>
    <div class="bt-card">
      <div class="bt-card-label">Win Rate</div>
      <div class="bt-card-value ${wrClass}">${wrPct}%</div>
      <div class="bt-card-sub">W ${s.wins ?? 0} / L ${s.losses ?? 0} / Exp ${s.expired ?? 0}</div>
    </div>
    <div class="bt-card">
      <div class="bt-card-label">Avg Return</div>
      <div class="bt-card-value ${(s.avg_return_all ?? 0) >= 0 ? "bt-good" : "bt-bad"}">
        ${s.avg_return_all != null ? ((s.avg_return_all >= 0 ? "+" : "") + s.avg_return_all + "%") : "-"}
      </div>
      <div class="bt-card-sub">
        W ${s.avg_return_win  != null ? "+" + s.avg_return_win  + "%" : "-"} /
        L ${s.avg_return_loss != null ?       s.avg_return_loss + "%" : "-"}
      </div>
    </div>
    <div class="bt-card">
      <div class="bt-card-label">Profit Factor</div>
      <div class="bt-card-value ${s.profit_factor >= 1.5 ? "bt-good" : s.profit_factor >= 1.0 ? "bt-mid" : "bt-bad"}">
        ${s.profit_factor ?? "-"}
      </div>
      <div class="bt-card-sub">Expectancy ${s.expected_value != null ? ((s.expected_value >= 0 ? "+" : "") + s.expected_value + "%") : "-"}</div>
    </div>
    <div class="bt-card">
      <div class="bt-card-label">Sharpe Ratio (ann.)</div>
      <div class="bt-card-value ${sharpe != null ? sharpeCls : ""}">
        ${sharpe != null ? sharpe.toFixed(2) : "-"}
      </div>
      <div class="bt-card-sub">Max DD ${dd != null ? "-" + dd + "%" : "-"}</div>
    </div>
    <div class="bt-card bt-card-capital">
      <div class="bt-card-label">$10,000 Simulation</div>
      <div class="bt-card-value ${(s.capital_return ?? 0) >= 0 ? "bt-good" : "bt-bad"}">
        $${s.capital_end != null ? Number(s.capital_end).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : "-"}
      </div>
      <div class="bt-card-sub">${s.capital_return != null ? ((s.capital_return >= 0 ? "+" : "") + s.capital_return + "%") : ""}</div>
    </div>
  `;

  renderBreakdown(s.breakdown_win, s.breakdown_loss);
  renderCalibration(s.calibration || []);
  renderCapitalCurve(s.capital_curve || []);

  document.getElementById("bt-pattern-body").innerHTML =
    (s.by_pattern || []).map(p => {
      const wr = Math.round(p.win_rate * 100);
      return `<tr>
        <td>${escBt(p.pattern)}</td>
        <td>${p.total}</td>
        <td class="${wr >= 60 ? "bt-good" : wr >= 50 ? "bt-mid" : "bt-bad'}">${wr}%</td>
        <td class="${p.avg_return >= 0 ? "bt-good" : "bt-bad'}">${p.avg_return >= 0 ? "+" : ""}${p.avg_return}%</td>
      </tr>`;
    }).join("") || '<tr><td colspan="4" class="bt-empty-cell">No data</td></tr>';

  document.getElementById("bt-score-body").innerHTML =
    (s.by_score || []).map(sc => {
      const wr = Math.round(sc.win_rate * 100);
      return `<tr>
        <td>${sc.range}</td>
        <td>${sc.total}</td>
        <td class="${wr >= 60 ? "bt-good" : wr >= 50 ? "bt-mid" : "bt-bad'}">${wr}%</td>
        <td class="${sc.avg_return >= 0 ? "bt-good" : "bt-bad'}">${sc.avg_return >= 0 ? "+" : ""}${sc.avg_return}%</td>
      </tr>`;
    }).join("") || '<tr><td colspan="4" class="bt-empty-cell">No data</td></tr>';

  renderSignals(d.signals || []);
}

function renderBreakdown(win, loss) {
  const el = document.getElementById("bt-breakdown");
  const hasData = win && Object.values(win).some(v => v !== null);
  if (!hasData) {
    el.innerHTML = '<p style="color:var(--text-muted);font-size:13px">Score component comparison will appear once sufficient signals accumulate.</p>';
    return;
  }

  const components = [
    { key: "trend",     label: "Trend",     max: 25 },
    { key: "pattern",   label: "Pattern",   max: 35 },
    { key: "momentum",  label: "Momentum",  max: 20 },
    { key: "volume",    label: "Volume",    max: 10 },
    { key: "liquidity", label: "Liquidity", max: 5  },
    { key: "rs",        label: "RS",        max: 5  },
  ];

  const rows = components.map(({ key, label, max }) => {
    const wv   = win?.[key]  ?? null;
    const lv   = loss?.[key] ?? null;
    const diff = wv != null && lv != null ? Math.round((wv - lv) * 10) / 10 : null;
    const diffCls = diff > 0 ? "bd-diff-pos" : diff < 0 ? "bd-diff-neg" : "bd-diff-neu";
    const diffStr = diff != null ? (diff >= 0 ? `+${diff.toFixed(1)}` : diff.toFixed(1)) : "-";
    const wPct = wv != null ? Math.round(wv / max * 100) : 0;
    const lPct = lv != null ? Math.round(lv / max * 100) : 0;

    return `<tr>
      <td><strong>${label}</strong></td>
      <td class="bd-max">${max}pts</td>
      <td>
        <div class="bd-bar-wrap">
          <div class="bd-bar-bg"><div class="bd-bar-fill-win" style="width:${wPct}%"></div></div>
          <span class="bd-val bt-good">${wv ?? "-"}</span>
        </div>
      </td>
      <td>
        <div class="bd-bar-wrap">
          <div class="bd-bar-bg"><div class="bd-bar-fill-loss" style="width:${lPct}%"></div></div>
          <span class="bd-val bt-bad">${lv ?? "-"}</span>
        </div>
      </td>
      <td class="${diffCls}">${diffStr}</td>
    </tr>`;
  }).join("");

  el.innerHTML = `
    <table class="breakdown-table">
      <thead>
        <tr>
          <th>Component</th>
          <th>Max</th>
          <th>✅ Wins (avg)</th>
          <th>❌ Losses (avg)</th>
          <th>Diff</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="bd-note">Components with a larger positive diff are more predictive of winning trades. Use this to tune scorer.py weights as data accumulates.</p>
  `;
}

function renderCalibration(calibration) {
  const el = document.getElementById("bt-calibration");
  if (!calibration.length) {
    el.innerHTML = '<p style="color:var(--text-muted);font-size:13px">Probability model calibration will appear once sufficient signals accumulate.</p>';
    return;
  }

  const rows = calibration.map(c => {
    const predicted = Math.round(c.predicted_center * 100);
    const actual    = Math.round(c.actual_win_rate * 100);
    const err       = c.calibration_err;
    const errCls    = err > 0.05 ? "bt-good" : err < -0.05 ? "bt-bad" : "bd-diff-neu";
    const errStr    = (err >= 0 ? "+" : "") + Math.round(err * 100) + "pp";
    const barPct    = actual;
    const barColor  = actual >= 60 ? "var(--green)" : actual >= 50 ? "var(--yellow)" : "var(--red)";

    return `<tr>
      <td>${escBt(c.band)}</td>
      <td>${predicted}%</td>
      <td>
        <div class="calib-bar-wrap">
          <div class="calib-bar-bg">
            <div class="calib-bar-fill" style="width:${barPct}%;background:${barColor}"></div>
          </div>
          <span style="font-size:12px;font-weight:600;width:36px;text-align:right;color:${barColor}">${actual}%</span>
        </div>
      </td>
      <td>${c.total}</td>
      <td class="${errCls}">${errStr}</td>
    </tr>`;
  }).join("");

  el.innerHTML = `
    <table class="calib-table">
      <thead>
        <tr>
          <th>Predicted Band</th>
          <th>Center</th>
          <th>Actual Win Rate</th>
          <th>Count</th>
          <th>Error (pred−actual)</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="calib-note">
      Near-zero error means the model is well-calibrated. Positive bias (actual &gt; predicted) suggests room to raise probability weights; negative bias suggests over-estimation.
    </p>
  `;
}

function renderCapitalCurve(curve) {
  const wrap = document.getElementById("capital-chart-wrap");
  if (!wrap || curve.length < 2) {
    if (wrap) wrap.style.display = "none";
    return;
  }
  wrap.style.display = "";

  const container = document.getElementById("capital-chart-container");
  container.innerHTML = "";

  const data = curve
    .filter(d => d.date && d.capital != null)
    .map(d => ({ time: d.date, value: d.capital }));

  if (data.length < 2) { wrap.style.display = "none"; return; }

  const last = data[data.length - 1].value;
  const isPos = last >= 10_000;
  const lineColor = isPos ? "#3fb950" : "#f85149";

  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth || 800,
    height: 220,
    layout:          { background: { color: "#0d1117" }, textColor: "#7d8590" },
    grid:            { vertLines: { color: "#21262d" }, horzLines: { color: "#21262d" } },
    timeScale:       { borderColor: "#30363d" },
    rightPriceScale: { borderColor: "#30363d" },
    crosshair:       { mode: 1 },
    handleScroll: false,
    handleScale:  false,
  });

  const series = chart.addAreaSeries({
    lineColor,
    topColor:    isPos ? "rgba(63,185,80,0.2)"  : "rgba(248,81,73,0.2)",
    bottomColor: "rgba(0,0,0,0)",
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: true,
    priceFormat: { type: "custom", formatter: v => "$" + Number(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) },
  });

  series.setData(data);
  series.createPriceLine({ price: 10_000, color: "#484f58", lineWidth: 1, lineStyle: 2, axisLabelVisible: false });
  chart.timeScale().fitContent();

  const capReturn = ((last / 10_000 - 1) * 100).toFixed(1);
  const subEl = document.getElementById("capital-chart-sub");
  if (subEl) subEl.textContent = `Current $${Number(last).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} (${capReturn >= 0 ? "+" : ""}${capReturn}%)`;

  const ro = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }));
  ro.observe(container);
}

function renderSignals(signals) {
  const outcomeLabel = { win: "✅ Target Hit", loss: "❌ Stopped Out", expired: "⏱ Expired", open: "📈 Open" };
  const outcomeClass = { win: "bt-good", loss: "bt-bad", expired: "bt-mid", open: "" };

  const rows = signals.slice().reverse().map(r => {
    const ret = r.actual_return != null
      ? `<span class="${r.actual_return >= 0 ? "bt-good" : "bt-bad'}">${r.actual_return >= 0 ? "+" : ""}${r.actual_return}%</span>`
      : "-";
    const bd = r.score_breakdown || {};
    const bdStr = (bd.trend != null)
      ? `T:${bd.trend} P:${bd.pattern ?? 0} M:${bd.momentum ?? 0} V:${bd.volume ?? 0} R:${bd.rs ?? 0}`
      : "";

    return `<tr>
      <td>${r.date}</td>
      <td><strong>${r.code}</strong></td>
      <td>${escBt(r.name)}</td>
      <td>
        <strong>${r.score}</strong>
        ${bdStr ? `<div class="score-bd-cell">${bdStr}</div>` : ""}
      </td>
      <td>${escBt(r.pattern)}</td>
      <td>$${Number(r.entry_price).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
      <td>$${Number(r.target).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
      <td class="${outcomeClass[r.outcome] || ""}">${outcomeLabel[r.outcome] || escBt(r.outcome)}</td>
      <td>${ret}</td>
      <td>${r.holding_days != null ? r.holding_days + "d" : "-"}</td>
    </tr>`;
  }).join("");

  document.getElementById("bt-signals-body").innerHTML =
    rows || '<tr><td colspan="10" class="bt-empty-cell">No data</td></tr>';
}

document.addEventListener("DOMContentLoaded", loadBacktest);
