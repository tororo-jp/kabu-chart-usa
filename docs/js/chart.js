/* Lightweight Charts rendering with annotations */

const ChartModule = (() => {
  let chart = null;
  let candleSeries = null;
  let volumeSeries = null;
  let lineSeries = [];

  function destroy() {
    if (chart) {
      chart.remove();
      chart = null;
      candleSeries = null;
      volumeSeries = null;
      lineSeries = [];
    }
  }

  function render(containerId, stock) {
    destroy();

    const container = document.getElementById(containerId);
    container.innerHTML = "";

    chart = LightweightCharts.createChart(container, {
      width: container.clientWidth,
      height: 400,
      layout: {
        background: { color: "#161b22" },
        textColor: "#7d8590",
      },
      grid: {
        vertLines: { color: "#21262d" },
        horzLines: { color: "#21262d" },
      },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#30363d" },
      timeScale: {
        borderColor: "#30363d",
        timeVisible: true,
        secondsVisible: false,
      },
    });

    // Candle series
    candleSeries = chart.addCandlestickSeries({
      upColor: "#3fb950",
      downColor: "#f85149",
      borderUpColor: "#3fb950",
      borderDownColor: "#f85149",
      wickUpColor: "#3fb950",
      wickDownColor: "#f85149",
    });

    const ohlcv = (stock.ohlcv || []).map((d) => ({
      time: d.t,
      open: d.o,
      high: d.h,
      low: d.l,
      close: d.c,
    }));
    candleSeries.setData(ohlcv);

    // Volume series (histogram on secondary scale)
    volumeSeries = chart.addHistogramSeries({
      color: "#1f6feb44",
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    const volData = (stock.ohlcv || []).map((d) => ({
      time: d.t,
      value: d.v,
      color: d.c >= d.o ? "#3fb95044" : "#f8514944",
    }));
    volumeSeries.setData(volData);

    // MA lines
    const ind = stock.indicators || {};
    if (ohlcv.length > 0) {
      _addMALine(stock, 5, "#58a6ff");
      _addMALine(stock, 25, "#d29922");
      _addMALine(stock, 75, "#f0883e");
      _addMALine(stock, 200, "#bc8cff");
    }

    // Target price line
    if (stock.target) {
      _addHLine(stock.target, "#3fb950", "Target", ohlcv);
    }
    // Stop loss line
    if (stock.stop_loss) {
      _addHLine(stock.stop_loss, "#f85149", "Stop Loss", ohlcv);
    }

    // Markers for pattern signals
    _addPatternMarkers(stock, ohlcv);

    // Resize handler
    const obs = new ResizeObserver(() => {
      if (chart) chart.applyOptions({ width: container.clientWidth });
    });
    obs.observe(container);
  }

  function _addMALine(stock, period, color) {
    const maKey = `sma${period}`;
    const val = (stock.indicators || {})[maKey];
    if (!val) return;
    const ohlcv = stock.ohlcv || [];
    if (ohlcv.length === 0) return;

    const ls = chart.addLineSeries({
      color,
      lineWidth: 1,
      crosshairMarkerVisible: false,
      lastValueVisible: false,
      priceLineVisible: false,
    });
    ls.applyOptions({ priceLineVisible: true, priceLineColor: color, priceLineStyle: 2 });
    ls.setData([{ time: ohlcv[ohlcv.length - 1].t, value: val }]);
    lineSeries.push(ls);
  }

  function _addHLine(price, color, title, ohlcv) {
    if (!ohlcv || ohlcv.length === 0) return;
    const ls = chart.addLineSeries({
      color,
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      crosshairMarkerVisible: false,
      lastValueVisible: true,
      priceLineVisible: false,
      title,
    });
    ls.setData([
      { time: ohlcv[0].time, value: price },
      { time: ohlcv[ohlcv.length - 1].time, value: price },
    ]);
    lineSeries.push(ls);
  }

  function _addPatternMarkers(stock, ohlcv) {
    if (!ohlcv || ohlcv.length === 0) return;
    const markers = [];
    const lastBar = ohlcv[ohlcv.length - 1];

    for (const p of stock.patterns || []) {
      markers.push({
        time: lastBar.time,
        position: "belowBar",
        color: "#1f6feb",
        shape: "arrowUp",
        text: p.label,
      });
    }

    if (markers.length > 0) {
      candleSeries.setMarkers(markers);
    }
  }

  return { render, destroy };
})();
