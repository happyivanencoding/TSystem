(function () {
  const DATA = window.DASHBOARD_DATA;
  const RISK_UP = "#e53935", RISK_DOWN = "#2e7d32";
  let region = "US";
  let charts = {};

  // 累计收益的状态背景着色插件
  const regimeBg = {
    id: "regimeBg",
    beforeDatasetsDraw(chart, _a, opts) {
      const { ctx, chartArea: ca, scales: { x } } = chart;
      const states = opts.states, colors = opts.colors;
      if (!states) return;
      const w = ca.width / states.length;
      ctx.save();
      states.forEach((s, i) => {
        ctx.fillStyle = colors[s] + "33"; // 透明度
        ctx.fillRect(ca.left + i * w, ca.top, w + 1, ca.height);
      });
      ctx.restore();
    },
  };
  Chart.register(regimeBg);

  function destroyCharts() { Object.values(charts).forEach((c) => c && c.destroy()); charts = {}; }

  function fmtPct(x) { return (x * 100).toFixed(1) + "%"; }

  function render() {
    const d = DATA[region];
    destroyCharts();

    // 快照
    const cur = d.current;
    const color = d.colors[cur.state];
    const chip = document.getElementById("stateChip");
    chip.textContent = cur.label;
    chip.style.background = color;
    document.getElementById("asOf").textContent = "数据截至 " + d.as_of;
    document.getElementById("predVol").textContent = fmtPct(cur.pred_vol);
    document.getElementById("equityW").textContent = (cur.equity_weight * 100).toFixed(0) + "%";
    document.getElementById("allocBreak").innerHTML =
      `波动目标 ${fmtPct(cur.target_vol)} → 波动权重 ${cur.w_vol.toFixed(2)}` +
      `<br>状态系数 ×${cur.state_mult} → 最终 ${(cur.equity_weight * 100).toFixed(0)}%`;

    // 图例
    document.getElementById("regimeLegend").innerHTML = d.state_labels
      .map((l, i) => `<span><i class="dot" style="background:${d.colors[i]}"></i>${l}</span>`)
      .join("");

    // 贡献(可解释性) 横向发散柱
    const c = d.contrib.slice(0, 14);
    charts.contrib = bar("contribChart", c.map((x) => x.feat),
      c.map((x) => x.contrib), c.map((x) => (x.contrib >= 0 ? RISK_UP : RISK_DOWN)),
      "对预测波动的贡献");

    // Ridge 全局系数
    const co = d.ridge_coef.slice(0, 14);
    charts.coef = bar("coefChart", co.map((x) => x.feat),
      co.map((x) => x.coef), co.map((x) => (x.coef >= 0 ? RISK_UP : RISK_DOWN)), "系数");

    // 状态画像
    const p = d.state_profile.slice(0, 14);
    charts.profile = bar("profileChart", p.map((x) => x.feat),
      p.map((x) => x.z), p.map((x) => (x.z >= 0 ? "#fb8c00" : "#1976d2")), "标准化偏离 z");

    // 累计收益 + 状态背景
    charts.regime = new Chart(document.getElementById("regimeChart"), {
      type: "line",
      data: { labels: d.series.dates,
        datasets: [{ label: "累计收益(等权)", data: d.series.cum_return, borderColor: "#202124",
          borderWidth: 1.5, pointRadius: 0, tension: .1 }] },
      options: lineOpts({ regimeBg: { states: d.series.state, colors: d.colors } }),
    });

    // 波动：已实现 vs 拟合
    charts.vol = new Chart(document.getElementById("volChart"), {
      type: "line",
      data: { labels: d.series.dates, datasets: [
        { label: "已实现波动", data: d.series.realized_vol, borderColor: "#90a4ae",
          borderWidth: 1.2, pointRadius: 0, tension: .1 },
        { label: "Ridge 拟合", data: d.series.fitted_vol, borderColor: "#1976d2",
          borderWidth: 1.8, pointRadius: 0, tension: .1 } ] },
      options: lineOpts({}),
    });
  }

  function bar(id, labels, values, colors, title) {
    return new Chart(document.getElementById(id), {
      type: "bar",
      data: { labels, datasets: [{ data: values, backgroundColor: colors, borderRadius: 3 }] },
      options: {
        indexAxis: "y", responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, title: { display: false },
          tooltip: { callbacks: { label: (i) => `${title}: ${i.raw.toFixed ? i.raw.toFixed(4) : i.raw}` } } },
        scales: { x: { grid: { color: "#eceff1" }, ticks: { font: { size: 11 } } },
          y: { grid: { display: false }, ticks: { font: { size: 11 } } } },
      },
    });
  }

  function lineOpts(extra) {
    return {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: Object.assign({ legend: { labels: { boxWidth: 14, font: { size: 12 } } } }, extra),
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: 10, font: { size: 11 } } },
        y: { grid: { color: "#eceff1" }, ticks: { font: { size: 11 } } },
      },
    };
  }

  // 区域切换
  document.getElementById("regionToggle").addEventListener("click", (e) => {
    const btn = e.target.closest("button"); if (!btn) return;
    region = btn.dataset.region;
    document.querySelectorAll("#regionToggle button").forEach((b) => b.classList.toggle("active", b === btn));
    render();
  });

  render();
})();
