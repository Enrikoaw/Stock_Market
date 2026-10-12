/**
 * SmartFlow IDX - Frontend Controller (app.js)
 * Mengelola state screener, filter interaktif, upload Excel, dan grafik Inspector.
 */

let currentStocks = [];
let currentPage = 1;
const PAGE_SIZE = 50;
let selectedTicker = null;
let selectedStockDetail = null;
let activeChartTab = 'price';
let chartInstance = null;
let isSyncingFast = false;

// Formatters
const fmtNumber = (n) => new Intl.NumberFormat('id-ID').format(Math.round(n || 0));
const fmtPrice = (n) => `Rp ${fmtNumber(n)}`;
const fmtSignPct = (n) => `${n >= 0 ? '+' : ''}${Number(n || 0).toFixed(2)}%`;

// =====================================================================
// THEME ENGINE (Dark & Light Mode Toggle)
// =====================================================================
function initTheme() {
  const saved = localStorage.getItem('smartflow_theme') || 'dark';
  applyTheme(saved);
}

function applyTheme(theme) {
  const html = document.documentElement;
  const icon = document.getElementById('themeIcon');
  const label = document.getElementById('themeLabel');

  if (theme === 'light') {
    html.classList.remove('dark');
    html.classList.add('light');
    if (icon) icon.textContent = '☀️';
    if (label) label.textContent = 'Terang';
  } else {
    html.classList.remove('light');
    html.classList.add('dark');
    if (icon) icon.textContent = '🌙';
    if (label) label.textContent = 'Gelap';
  }
  localStorage.setItem('smartflow_theme', theme);

  if (selectedStockDetail) {
    renderInspectorChart(selectedStockDetail);
  }
}

function toggleTheme() {
  const isDark = document.documentElement.classList.contains('dark');
  applyTheme(isDark ? 'light' : 'dark');
}

// Inisialisasi tema segera
initTheme();

function getTriggerBadgeClass(triggerType) {
  switch (triggerType) {
    case 'MARKUP_BREAKOUT':
      return 'badge-markup';
    case 'BIG_ACCUMULATION':
      return 'badge-big-accum';
    case 'SILENT_ACCUMULATION':
      return 'badge-silent-accum';
    case 'FOREIGN_INFLOW':
      return 'badge-foreign';
    case 'DISTRIBUTION_WARNING':
      return 'badge-dist';
    default:
      return 'badge-neutral';
  }
}

function getScoreColor(score) {
  if (score >= 76) return 'from-emerald-500 to-teal-400 text-emerald-300';
  if (score >= 64) return 'from-blue-500 to-emerald-400 text-blue-300';
  if (score >= 50) return 'from-amber-500 to-yellow-400 text-amber-300';
  return 'from-rose-600 to-red-400 text-rose-300';
}

function getStockLogoImg(ticker, sizeCls = 'w-7 h-7') {
  if (!ticker) return '';
  const cleanTicker = ticker.trim().toUpperCase();
  const cdnUrl = `https://assets.stockbit.com/logos/companies/${cleanTicker}.png`;
  const fallbackUrl = `https://ui-avatars.com/api/?name=${encodeURIComponent(cleanTicker)}&background=1e293b&color=38bdf8&bold=true&length=2`;
  return `
    <img
      src="${cdnUrl}"
      alt="${cleanTicker}"
      loading="lazy"
      class="${sizeCls} rounded-full bg-slate-900 border border-slate-700/60 object-contain p-0.5 shrink-0 shadow-sm inline-block"
      onerror="this.onerror=null; this.src='${fallbackUrl}';"
    />
  `;
}

function showToast(msg, type = 'success') {
  const banner = document.getElementById('toastBanner');
  const text = document.getElementById('toastMessage');
  banner.classList.remove(
    'hidden',
    'bg-emerald-950/90',
    'border-emerald-500/40',
    'text-emerald-200',
    'bg-rose-950/90',
    'border-rose-500/40',
    'text-rose-200'
  );
  if (type === 'error') {
    banner.classList.add('bg-rose-950/90', 'border-rose-500/40', 'text-rose-200');
  } else {
    banner.classList.add('bg-emerald-950/90', 'border-emerald-500/40', 'text-emerald-200');
  }
  text.textContent = msg;
}

async function loadScreenerData(preserveSelection = false) {
  const trigger = document.getElementById('filterTrigger').value;
  const minVol = document.getElementById('filterVolRatio').value;
  const minScore = document.getElementById('filterMinScore').value;
  const sortBy = document.getElementById('filterSortBy').value;
  const search = document.getElementById('filterSearch').value.trim();

  const params = new URLSearchParams({
    trigger,
    min_vol_ratio: minVol,
    min_score: minScore,
    sort_by: sortBy,
    search,
    _t: Date.now(),
  });

  try {
    const res = await fetch(`/api/screener?${params.toString()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error('Gagal mengambil data screener');
    const data = await res.json();

    document.getElementById('activeSourceBadge').textContent = data.source_name;
    const syncEl = document.getElementById('lastSyncBadge');
    if (syncEl && data.last_sync_time) {
      syncEl.textContent = `Update: ${data.last_sync_time} (Auto ${data.auto_sync_interval_min || 30}m)`;
    }
    updateKPICards(data.kpis, trigger);

    currentStocks = data.stocks || [];
    if (!preserveSelection) currentPage = 1;
    renderScreenerTable(currentStocks);

    if (currentStocks.length > 0) {
      const targetTicker =
        preserveSelection && currentStocks.some((s) => s.ticker === selectedTicker)
          ? selectedTicker
          : currentStocks[0].ticker;
      await selectStock(targetTicker);
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, 'error');
  }
}

function updateKPICards(kpis, currentTrigger) {
  if (!kpis) return;
  const elTotal = document.getElementById('kpiTotalEmiten');
  if (elTotal) elTotal.textContent = kpis.total_emiten;
  const elAvg = document.getElementById('kpiAvgScore');
  if (elAvg) elAvg.textContent = `Avg: ${kpis.avg_smart_money_score}`;
  const elMarkup = document.getElementById('kpiMarkupCount');
  if (elMarkup) elMarkup.textContent = kpis.markup_triggers;
  const elAccum = document.getElementById('kpiAccumCount');
  if (elAccum) elAccum.textContent = kpis.accum_triggers;
  const elDist = document.getElementById('kpiDistCount');
  if (elDist) elDist.textContent = kpis.distribution_warnings;

  // Highlight active KPI card
  const mapCard = {
    ALL: 'kpiAll',
    MARKUP_BREAKOUT: 'kpiMarkup',
    ACCUM_ALL: 'kpiAccum',
    DISTRIBUTION_WARNING: 'kpiDist',
  };
  ['kpiAll', 'kpiMarkup', 'kpiAccum', 'kpiDist'].forEach((id) => {
    document.getElementById(id).classList.remove('active-filter');
  });
  if (mapCard[currentTrigger]) {
    document.getElementById(mapCard[currentTrigger]).classList.add('active-filter');
  }
}

function applyQuickFilter(triggerCode) {
  document.getElementById('filterTrigger').value = triggerCode;
  loadScreenerData(false);
}

function changePage(delta) {
  const totalPages = Math.max(1, Math.ceil(currentStocks.length / PAGE_SIZE));
  currentPage = Math.min(totalPages, Math.max(1, currentPage + delta));
  renderScreenerTable(currentStocks);
}

function renderScreenerTable(stocks) {
  const tbody = document.getElementById('screenerTableBody');
  const totalPages = Math.max(1, Math.ceil(stocks.length / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = totalPages;

  const startIdx = (currentPage - 1) * PAGE_SIZE;
  const pageStocks = stocks.slice(startIdx, startIdx + PAGE_SIZE);

  document.getElementById('tableResultCount').textContent = stocks.length
    ? `Menampilkan ${startIdx + 1}-${startIdx + pageStocks.length} dari ${stocks.length} saham`
    : 'Menampilkan 0 saham';

  const pageInd = document.getElementById('pageIndicator');
  const btnPrev = document.getElementById('btnPrevPage');
  const btnNext = document.getElementById('btnNextPage');
  if (pageInd) pageInd.textContent = `Hal ${currentPage} / ${totalPages}`;
  if (btnPrev) btnPrev.disabled = currentPage <= 1;
  if (btnNext) btnNext.disabled = currentPage >= totalPages;

  if (!pageStocks.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="py-10 text-center text-slate-400">
          Tidak ada saham yang memenuhi filter kriteria saat ini. Coba longgarkan filter di atas.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = pageStocks
    .map((s) => {
      const isSelected = s.ticker === selectedTicker;
      const chgColor = s.pct_change >= 0 ? 'text-emerald-400' : 'text-rose-400';
      const volColor =
        s.vol_ratio >= 2.0
          ? 'text-amber-300 font-bold'
          : s.vol_ratio >= 1.35
          ? 'text-emerald-300 font-semibold'
          : 'text-slate-300';
      const bsrColor =
        s.top3_bsr >= 1.35
          ? 'text-emerald-400 font-bold'
          : s.top3_bsr < 0.85
          ? 'text-rose-400 font-semibold'
          : 'text-slate-300';
      const foreignColor = s.net_foreign_pct >= 0 ? 'text-emerald-400' : 'text-rose-400';
      const badgeCls = getTriggerBadgeClass(s.trigger_type);
      const barGrad = getScoreColor(s.smart_money_score);

      return `
        <tr
          id="row-${s.ticker}"
          onclick="selectStock('${s.ticker}')"
          class="stock-row ${isSelected ? 'selected-row' : ''}"
        >
          <!-- Ticker & Logo -->
          <td class="py-3 pl-4 pr-2">
            <div class="flex items-center gap-2.5">
              ${getStockLogoImg(s.ticker, 'w-8 h-8')}
              <div>
                <div class="font-mono font-black text-sm text-white">${s.ticker}</div>
                <div class="text-[10px] text-slate-400 truncate max-w-[120px]">${s.sector}</div>
              </div>
            </div>
          </td>

          <!-- Price -->
          <td class="py-3 px-2 text-right font-mono font-bold text-slate-100 text-xs">
            ${fmtPrice(s.close)}
          </td>

          <!-- Change -->
          <td class="py-3 px-2 text-right font-mono text-xs font-bold ${chgColor}">
            ${fmtSignPct(s.pct_change)}
          </td>

          <!-- Volume Spike Badge -->
          <td class="py-3 px-2 text-center font-mono">
            <span class="inline-block px-2.5 py-0.5 rounded-full text-[10px] font-bold ${s.vol_ratio >= 1.5 ? 'bg-amber-500/20 text-amber-300 border border-amber-500/35' : 'bg-emerald-500/15 text-emerald-300 border border-emerald-500/30'}">
              ${s.vol_ratio >= 2.0 ? 'Vol Spike' : s.vol_ratio >= 1.2 ? 'High Vol' : 'Normal'} ${s.vol_ratio.toFixed(1)}x
            </span>
          </td>

          <!-- Smart Money Score with Progress Bar -->
          <td class="py-3 px-2 text-right">
            <div class="flex items-center justify-end gap-2.5">
              <span class="font-mono font-extrabold text-xs text-white">${s.smart_money_score}</span>
              <div class="w-20 bg-slate-800 h-2 rounded-full overflow-hidden">
                <div class="h-full bg-gradient-to-r from-emerald-400 to-teal-300 rounded-full" style="width: ${s.smart_money_score}%"></div>
              </div>
            </div>
          </td>

          <!-- Broker Summary -->
          <td class="py-3 pl-2 pr-4 text-xs font-mono">
            <div class="text-[11px] text-slate-300">
              Top B: <span class="text-emerald-400 font-bold">${s.top_buyers || '-'}</span> | S: <span class="text-rose-400 font-bold">${s.top_sellers || '-'}</span>
            </div>
            <div class="text-[10px] text-slate-400">
              Ratio: <span class="${bsrColor}">${s.top3_bsr.toFixed(2)}x</span> · Net F: <span class="${foreignColor}">${s.net_foreign_pct >= 0 ? '+' : ''}${s.net_foreign_pct.toFixed(1)}%</span>
            </div>
          </td>
        </tr>
      `;
    })
    .join('');
}

async function selectStock(ticker, scrollToTradingPlan = false) {
  selectedTicker = ticker;

  // Update row highlight
  document.querySelectorAll('.stock-row').forEach((el) => el.classList.remove('selected-row'));
  const activeRow = document.getElementById(`row-${ticker}`);
  if (activeRow) activeRow.classList.add('selected-row');

  try {
    const res = await fetch(`/api/stock/${encodeURIComponent(ticker)}?_t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`Gagal memuat detail ${ticker}`);
    selectedStockDetail = await res.json();
    renderInspectorPanel(selectedStockDetail);

    if (scrollToTradingPlan) {
      setTimeout(() => {
        const planCard = document.getElementById('autoTradingPlanCard');
        if (planCard) {
          planCard.scrollIntoView({ behavior: 'smooth', block: 'center' });
          planCard.classList.add('ring-2', 'ring-emerald-400', 'ring-offset-2', 'ring-offset-slate-900');
          setTimeout(() => {
            planCard.classList.remove('ring-2', 'ring-emerald-400', 'ring-offset-2', 'ring-offset-slate-900');
          }, 2000);
        }
      }, 100);
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function renderInspectorPanel(d) {
  const logoEl = document.getElementById('inspLogoContainer');
  if (logoEl) logoEl.innerHTML = getStockLogoImg(d.ticker, 'w-10 h-10');

  document.getElementById('inspTicker').textContent = d.ticker;
  const badgeEl = document.getElementById('inspTriggerBadge');
  badgeEl.textContent = d.trigger_label;
  badgeEl.className = `text-[11px] font-semibold px-2.5 py-0.5 rounded-full ${getTriggerBadgeClass(d.trigger_type)}`;

  document.getElementById('inspSector').textContent = `${d.sector} • Update: ${d.date}`;
  document.getElementById('inspPrice').textContent = fmtPrice(d.close);

  const chgEl = document.getElementById('inspPctChange');
  if (chgEl) {
    chgEl.textContent = `${fmtSignPct(d.pct_change)} (${ fmtNumber(d.volume_lot) } Lot)`;
    chgEl.className = `text-xs font-mono font-semibold ${d.pct_change >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;
  }

  // 5-Pillar Scores
  const totalScoreBadge = document.getElementById('inspTotalScoreBadge');
  if (totalScoreBadge) totalScoreBadge.textContent = `Score: ${d.smart_money_score} / 100`;

  const p1 = document.getElementById('p1Score'); if (p1) p1.textContent = `${d.vsa_score}/25`;
  const p2 = document.getElementById('p2Score'); if (p2) p2.textContent = `${d.bandar_score}/30`;
  const p3 = document.getElementById('p3Score'); if (p3) p3.textContent = `${d.ticket_score}/15`;
  const p4 = document.getElementById('p4Score'); if (p4) p4.textContent = `${d.foreign_score}/15`;
  const p5 = document.getElementById('p5Score'); if (p5) p5.textContent = `${d.structure_score}/15`;

  const bar1 = document.getElementById('p1Bar');
  const bar2 = document.getElementById('p2Bar');
  const bar3 = document.getElementById('p3Bar');
  const bar4 = document.getElementById('p4Bar');
  const bar5 = document.getElementById('p5Bar');
  if (bar1) bar1.style.width = `${Math.min(100, Math.round((d.vsa_score / 25) * 100))}%`;
  if (bar2) bar2.style.width = `${Math.min(100, Math.round((d.bandar_score / 30) * 100))}%`;
  if (bar3) bar3.style.width = `${Math.min(100, Math.round((d.ticket_score / 15) * 100))}%`;
  if (bar4) bar4.style.width = `${Math.min(100, Math.round((d.foreign_score / 15) * 100))}%`;
  if (bar5) bar5.style.width = `${Math.min(100, Math.round((d.structure_score / 15) * 100))}%`;

  // Auto Trading Plan
  const plan = d.trading_plan;
  const biasEl = document.getElementById('planActionBias');
  if (biasEl) {
    biasEl.textContent = plan.action_bias;
    if (d.trigger_type === 'DISTRIBUTION_WARNING') {
      biasEl.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30';
    } else {
      biasEl.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
    }
  }

  const pez = document.getElementById('planEntryZone');
  if (pez) pez.textContent = `${fmtPrice(plan.entry_low)} - ${fmtNumber(plan.entry_high)}`;
  const slEl = document.getElementById('planStopLoss');
  if (slEl) slEl.textContent = `${fmtPrice(plan.stop_loss)} (${plan.stop_loss_pct}%)`;
  const tgtEl = document.getElementById('planTargets');
  if (tgtEl) tgtEl.textContent = `${fmtNumber(plan.target_1)} (+${plan.target_1_pct}%)`;
  const tgt2El = document.getElementById('planTarget2');
  if (tgt2El) {
    if (plan.target_2 && plan.target_2 > 0) {
      tgt2El.textContent = `${fmtNumber(plan.target_2)} (+${plan.target_2_pct}%)`;
    } else {
      tgt2El.textContent = '-';
    }
  }
  const pr = document.getElementById('planRationale');
  if (pr) pr.textContent = `${plan.rationale} (Risk/Reward = ${plan.risk_reward})`;

  // Render 5-Pillar Checklist
  const checklistEl = document.getElementById('inspChecklist');
  checklistEl.innerHTML = (d.checklist || [])
    .map((item) => {
      const icon =
        item.status === 'pass'
          ? '<span class="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 flex items-center justify-center font-bold text-xs">✓</span>'
          : item.status === 'warn'
          ? '<span class="w-5 h-5 rounded-full bg-amber-500/20 text-amber-400 flex items-center justify-center font-bold text-xs">!</span>'
          : '<span class="w-5 h-5 rounded-full bg-rose-500/20 text-rose-400 flex items-center justify-center font-bold text-xs">✕</span>';

      return `
        <div class="p-2.5 rounded-xl bg-slate-950/80 border border-slate-800/90 space-y-1">
          <div class="flex items-center justify-between gap-2">
            <div class="flex items-center gap-2">
              ${icon}
              <span class="text-xs font-semibold text-slate-200">${item.title}</span>
            </div>
            <span class="font-mono text-[11px] font-semibold text-emerald-300 bg-slate-900 px-2 py-0.5 rounded border border-slate-800">${item.metric}</span>
          </div>
          <p class="text-[11px] text-slate-400 pl-7 leading-relaxed">${item.detail}</p>
        </div>
      `;
    })
    .join('');

  renderInspectorChart(d);
}

function switchChartTab(tabName) {
  activeChartTab = tabName;
  const tabs = {
    price: 'tabChartPrice',
    bandar: 'tabChartBandar',
    score: 'tabChartScore',
  };
  Object.entries(tabs).forEach(([key, id]) => {
    const btn = document.getElementById(id);
    if (key === tabName) {
      btn.className = 'px-2.5 py-1 rounded-md text-[11px] font-semibold bg-emerald-600 text-white transition';
    } else {
      btn.className = 'px-2.5 py-1 rounded-md text-[11px] font-medium text-slate-400 hover:text-white transition';
    }
  });
  if (selectedStockDetail) {
    renderInspectorChart(selectedStockDetail);
  }
}

function renderInspectorChart(d) {
  const ctx = document.getElementById('inspectorChart').getContext('2d');
  if (chartInstance) {
    chartInstance.destroy();
  }

  const hist = d.history || [];
  const labels = hist.map((h) => h.date.slice(5)); // MM-DD

  const isLight = document.documentElement.classList.contains('light');
  const chartTextColor = isLight ? '#334155' : '#cbd5e1';
  const chartSubColor = isLight ? '#64748b' : '#94a3b8';
  const chartGridColor = isLight ? 'rgba(203, 213, 225, 0.65)' : 'rgba(51, 65, 85, 0.25)';

  if (activeChartTab === 'price') {
    const prices = hist.map((h) => h.close);
    const ma20s = hist.map((h) => h.ma20);
    const vols = hist.map((h) => h.volume_lot);
    const volColors = hist.map((h, i) => {
      const prev = i > 0 ? hist[i - 1].close : h.open;
      return h.close >= prev ? 'rgba(16, 185, 129, 0.45)' : 'rgba(239, 68, 68, 0.45)';
    });

    chartInstance = new Chart(ctx, {
      data: {
        labels,
        datasets: [
          {
            type: 'line',
            label: 'Close Price',
            data: prices,
            borderColor: '#10b981',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            borderWidth: 2,
            pointRadius: 2,
            tension: 0.25,
            yAxisID: 'yPrice',
          },
          {
            type: 'line',
            label: 'MA20',
            data: ma20s,
            borderColor: '#3b82f6',
            borderDash: [4, 4],
            borderWidth: 1.5,
            pointRadius: 0,
            tension: 0.25,
            yAxisID: 'yPrice',
          },
          {
            type: 'bar',
            label: 'Volume (Lot)',
            data: vols,
            backgroundColor: volColors,
            yAxisID: 'yVol',
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: chartSubColor, font: { size: 10 } } },
        },
        scales: {
          x: { ticks: { color: chartSubColor, font: { size: 9 } }, grid: { display: false } },
          yPrice: {
            position: 'right',
            ticks: { color: chartTextColor, font: { size: 9 } },
            grid: { color: chartGridColor },
          },
          yVol: {
            position: 'left',
            display: false,
            max: Math.max(...vols) * 3.2,
          },
        },
      },
    });
  } else if (activeChartTab === 'bandar') {
    const netTop3 = hist.map((h) => h.net_top3_lot);
    const barColors = netTop3.map((v) => (v >= 0 ? 'rgba(16, 185, 129, 0.75)' : 'rgba(239, 68, 68, 0.75)'));

    chartInstance = new Chart(ctx, {
      type: 'bar',
      data: {
        labels,
        datasets: [
          {
            label: 'Net Top 3 Broker (Lot)',
            data: netTop3,
            backgroundColor: barColors,
            borderRadius: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: chartSubColor, font: { size: 10 } } },
        },
        scales: {
          x: { ticks: { color: chartSubColor, font: { size: 9 } }, grid: { display: false } },
          y: {
            ticks: { color: chartTextColor, font: { size: 9 } },
            grid: { color: chartGridColor },
          },
        },
      },
    });
  } else {
    const scores = hist.map((h) => h.sm_score);
    chartInstance = new Chart(ctx, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            label: 'Smart Money Score (0-100)',
            data: scores,
            borderColor: '#f59e0b',
            backgroundColor: 'rgba(245, 158, 11, 0.15)',
            fill: true,
            borderWidth: 2,
            pointRadius: 2.5,
            tension: 0.3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { labels: { color: chartSubColor, font: { size: 10 } } },
        },
        scales: {
          x: { ticks: { color: chartSubColor, font: { size: 9 } }, grid: { display: false } },
          y: {
            min: 0,
            max: 100,
            ticks: { color: chartTextColor, font: { size: 9 } },
            grid: { color: chartGridColor },
          },
        },
      },
    });
  }
}

// Upload Excel Modal & Drag-and-Drop Handlers
function openUploadModal() {
  document.getElementById('uploadModal').classList.remove('hidden');
}
function closeUploadModal() {
  document.getElementById('uploadModal').classList.add('hidden');
}
function openGuideModal() {
  document.getElementById('guideModal').classList.remove('hidden');
}
function closeGuideModal() {
  document.getElementById('guideModal').classList.add('hidden');
}

// =====================================================================
// INTERACTIVE TECHNICAL ANALYSIS & DRAWING STUDIO ENGINE (IDX REAL DATA)
// =====================================================================
const taState = {
  ticker: 'BBCA',
  period: '6mo',
  candles: [],
  tradingPlan: {},
  sector: '',
  viewStart: 0,
  viewEnd: 0,
  tool: 'pan', // pan, trendline, ray, hline, fib, rect, measure, brush
  color: '#f59e0b',
  indicators: {
    candle: true,
    ma20: true,
    ma50: true,
    ema9: false,
    bb: false,
    plan: true,
  },
  subPanel: 'vol', // vol, rsi, macd
  drawings: [], // saved per ticker in localStorage
  activeDrawing: null,
  isDragging: false,
  dragStartX: 0,
  dragStartViewStart: 0,
  dragStartViewEnd: 0,
  hoverPos: null, // { x, y }
  computed: {},
  listenersAttached: false,
};

function _loadTADrawings(ticker) {
  try {
    const raw = localStorage.getItem(`smartflow_drawings_${ticker}`);
    taState.drawings = raw ? JSON.parse(raw) : [];
  } catch {
    taState.drawings = [];
  }
}

function _saveTADrawings() {
  try {
    localStorage.setItem(`smartflow_drawings_${taState.ticker}`, JSON.stringify(taState.drawings));
  } catch {
    // ignore storage quota errors
  }
}

function _computeTAIndicators(candles) {
  const n = candles.length;
  const closes = candles.map((c) => c.close);
  const vols = candles.map((c) => c.volume_lot || 0);

  const sma = (arr, len) => {
    const out = new Array(arr.length).fill(null);
    let sum = 0;
    for (let i = 0; i < arr.length; i++) {
      sum += arr[i];
      if (i >= len) sum -= arr[i - len];
      if (i >= len - 1) out[i] = sum / len;
    }
    return out;
  };

  const ema = (arr, len) => {
    const out = new Array(arr.length).fill(null);
    if (!arr.length) return out;
    const k = 2 / (len + 1);
    let prev = arr[0];
    out[0] = prev;
    for (let i = 1; i < arr.length; i++) {
      prev = arr[i] * k + prev * (1 - k);
      out[i] = prev;
    }
    return out;
  };

  const ma20 = sma(closes, 20);
  const ma50 = sma(closes, 50);
  const ema9 = ema(closes, 9);
  const volMa20 = sma(vols, 20);

  // Bollinger Bands (20, 2)
  const bbUpper = new Array(n).fill(null);
  const bbLower = new Array(n).fill(null);
  for (let i = 19; i < n; i++) {
    const mean = ma20[i];
    let sq = 0;
    for (let j = i - 19; j <= i; j++) {
      const d = closes[j] - mean;
      sq += d * d;
    }
    const sd = Math.sqrt(sq / 20);
    bbUpper[i] = mean + 2 * sd;
    bbLower[i] = mean - 2 * sd;
  }

  // RSI (14)
  const rsi14 = new Array(n).fill(null);
  if (n > 1) {
    let avgGain = 0;
    let avgLoss = 0;
    const period = Math.min(14, n - 1);
    for (let i = 1; i <= period; i++) {
      const chg = closes[i] - closes[i - 1];
      if (chg > 0) avgGain += chg;
      else avgLoss -= chg;
    }
    avgGain /= period;
    avgLoss /= period;
    rsi14[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    for (let i = period + 1; i < n; i++) {
      const chg = closes[i] - closes[i - 1];
      const gain = chg > 0 ? chg : 0;
      const loss = chg < 0 ? -chg : 0;
      avgGain = (avgGain * (period - 1) + gain) / period;
      avgLoss = (avgLoss * (period - 1) + loss) / period;
      rsi14[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
    }
  }

  // MACD (12, 26, 9)
  const ema12 = ema(closes, 12);
  const ema26 = ema(closes, 26);
  const macdLine = closes.map((_, i) => (ema12[i] !== null && ema26[i] !== null ? ema12[i] - ema26[i] : 0));
  const macdSignal = ema(macdLine, 9);
  const macdHist = macdLine.map((v, i) => v - (macdSignal[i] || 0));

  taState.computed = { ma20, ma50, ema9, volMa20, bbUpper, bbLower, rsi14, macdLine, macdSignal, macdHist };
}

async function openTradingViewModal() {
  const ticker = selectedTicker || (selectedStockDetail ? selectedStockDetail.ticker : 'BBCA');
  const cleanTicker = ticker.trim().toUpperCase();
  taState.ticker = cleanTicker;

  const modal = document.getElementById('tradingViewModal');
  const modalTicker = document.getElementById('tvModalTicker');
  const modalLogo = document.getElementById('tvModalLogo');
  const modalPrice = document.getElementById('tvModalPriceBadge');
  const modalSector = document.getElementById('tvModalSector');
  const extLink = document.getElementById('tvModalExternalLink');

  if (modalTicker) modalTicker.textContent = cleanTicker;
  if (modalLogo) modalLogo.innerHTML = getStockLogoImg(cleanTicker, 'w-8 h-8');
  if (extLink) extLink.href = `https://id.tradingview.com/symbols/IDX-${cleanTicker}/`;

  if (selectedStockDetail && selectedStockDetail.ticker === cleanTicker) {
    if (modalPrice) {
      const sign = selectedStockDetail.pct_change >= 0 ? '+' : '';
      modalPrice.textContent = `${fmtPrice(selectedStockDetail.close)} (${sign}${selectedStockDetail.pct_change}%)`;
      modalPrice.className = `text-xs font-mono font-bold ${selectedStockDetail.pct_change >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;
    }
    if (modalSector) {
      modalSector.textContent = `${selectedStockDetail.sector} • ${selectedStockDetail.trigger_label}`;
    }
    taState.tradingPlan = selectedStockDetail.trading_plan || {};
    taState.candles = (selectedStockDetail.history || []).map((h) => ({
      date: h.date,
      open: h.open,
      high: h.high,
      low: h.low,
      close: h.close,
      volume_lot: h.volume_lot || 0,
    }));
  }

  _loadTADrawings(cleanTicker);
  modal.classList.remove('hidden');
  _initTACanvasEvents();

  if (taState.candles.length) {
    _computeTAIndicators(taState.candles);
    taState.viewStart = 0;
    taState.viewEnd = taState.candles.length - 1;
    renderTAStudio();
  }

  await loadTACandlesFromServer(cleanTicker, taState.period);
}

async function loadTACandlesFromServer(ticker, period) {
  const loader = document.getElementById('taLoadingOverlay');
  if (loader) loader.classList.remove('hidden');
  try {
    const res = await fetch(`/api/stock/${encodeURIComponent(ticker)}/candles?period=${encodeURIComponent(period)}&_t=${Date.now()}`, { cache: 'no-store' });
    if (res.ok) {
      const data = await res.json();
      if (data.candles && data.candles.length) {
        taState.candles = data.candles;
        if (data.trading_plan && Object.keys(data.trading_plan).length) {
          taState.tradingPlan = data.trading_plan;
        }
        _computeTAIndicators(taState.candles);
        const total = taState.candles.length;
        const visibleCount = Math.min(total, period === '1mo' ? 25 : period === '3mo' ? 65 : period === '6mo' ? 100 : 140);
        taState.viewStart = Math.max(0, total - visibleCount);
        taState.viewEnd = total - 1;
        renderTAStudio();
      }
    }
  } catch (err) {
    console.warn('Gagal memuat candle historis:', err);
  } finally {
    if (loader) loader.classList.add('hidden');
  }
}

function closeTradingViewModal() {
  const modal = document.getElementById('tradingViewModal');
  if (modal) modal.classList.add('hidden');
}

function setTAChartPeriod(period) {
  taState.period = period;
  ['1mo', '3mo', '6mo', '1y'].forEach((p) => {
    const btn = document.getElementById(`taPeriod_${p}`);
    if (!btn) return;
    if (p === period) {
      btn.className = 'px-2 py-1 rounded bg-emerald-600 text-white font-bold transition';
    } else {
      btn.className = 'px-2 py-1 rounded text-slate-400 hover:text-white transition';
    }
  });
  loadTACandlesFromServer(taState.ticker, period);
}

function toggleTAIndicator(key) {
  taState.indicators[key] = !taState.indicators[key];
  const btn = document.getElementById(`taInd_${key}`);
  if (btn) {
    const active = taState.indicators[key];
    if (key === 'candle') {
      btn.textContent = active ? '🕯️ Candle' : '📈 Line';
    }
    btn.className = active
      ? 'px-2 py-1 rounded bg-emerald-600/30 text-emerald-300 border border-emerald-500/40 font-semibold transition'
      : 'px-2 py-1 rounded text-slate-400 hover:text-white transition';
  }
  renderTAStudio();
}

function setTASubPanel(panel) {
  taState.subPanel = panel;
  ['vol', 'rsi', 'macd'].forEach((p) => {
    const btn = document.getElementById(`taSub_${p}`);
    if (!btn) return;
    btn.className =
      p === panel
        ? 'px-2 py-1 rounded bg-emerald-600 text-white font-semibold transition'
        : 'px-2 py-1 rounded text-slate-400 hover:text-white transition';
  });
  renderTAStudio();
}

function setTADrawTool(tool) {
  taState.tool = tool;
  taState.activeDrawing = null;
  ['pan', 'trendline', 'ray', 'hline', 'fib', 'rect', 'measure', 'brush'].forEach((t) => {
    const btn = document.getElementById(`taTool_${t}`);
    if (!btn) return;
    btn.className =
      t === tool
        ? 'px-2.5 py-1 rounded-md bg-emerald-600 text-white font-semibold transition flex items-center gap-1 shadow-sm'
        : 'px-2.5 py-1 rounded-md bg-slate-900 hover:bg-slate-800 text-slate-300 border border-slate-800 transition flex items-center gap-1';
  });
  const canvas = document.getElementById('taStudioCanvas');
  if (canvas) {
    canvas.style.cursor = tool === 'pan' ? 'grab' : 'crosshair';
  }
  renderTAStudio();
}

function setTADrawColor(color) {
  taState.color = color;
  const map = {
    '#f59e0b': 'taColor_amber',
    '#10b981': 'taColor_emerald',
    '#38bdf8': 'taColor_sky',
    '#f43f5e': 'taColor_rose',
    '#f8fafc': 'taColor_white',
  };
  Object.entries(map).forEach(([c, id]) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (c === color) {
      el.classList.add('ring-2', 'ring-white', 'scale-110');
      el.classList.remove('opacity-70');
    } else {
      el.classList.remove('ring-2', 'ring-white', 'scale-110');
      el.classList.add('opacity-70');
    }
  });
}

function undoTADrawing() {
  if (taState.drawings.length > 0) {
    taState.drawings.pop();
    _saveTADrawings();
    renderTAStudio();
  }
}

function clearTADrawings() {
  taState.drawings = [];
  taState.activeDrawing = null;
  _saveTADrawings();
  renderTAStudio();
  showToast(`Semua tarikan garis pada ${taState.ticker} telah dihapus.`);
}

function zoomTAChart(factor) {
  const total = taState.candles.length;
  if (total < 5) return;
  const curSpan = Math.max(5, taState.viewEnd - taState.viewStart + 1);
  const newSpan = Math.min(total, Math.max(10, Math.round(curSpan / factor)));
  const center = (taState.viewStart + taState.viewEnd) / 2;
  let s = Math.round(center - newSpan / 2);
  let e = s + newSpan - 1;
  if (s < 0) {
    s = 0;
    e = Math.min(total - 1, newSpan - 1);
  }
  if (e >= total) {
    e = total - 1;
    s = Math.max(0, total - newSpan);
  }
  taState.viewStart = s;
  taState.viewEnd = e;
  renderTAStudio();
}

function resetTAZoom() {
  const total = taState.candles.length;
  if (!total) return;
  const visible = Math.min(total, 95);
  taState.viewStart = Math.max(0, total - visible);
  taState.viewEnd = total - 1;
  renderTAStudio();
}

function _getTALayout(canvas) {
  const w = canvas.clientWidth || 900;
  const h = canvas.clientHeight || 520;
  const padLeft = 14;
  const padRight = 84;
  const padTop = 18;
  const padBottom = 26;
  const subGap = 18;
  const plotW = Math.max(100, w - padLeft - padRight);
  const totalPlotH = Math.max(150, h - padTop - padBottom - subGap);
  const mainH = Math.round(totalPlotH * 0.73);
  const subH = totalPlotH - mainH;
  const mainTop = padTop;
  const mainBottom = mainTop + mainH;
  const subTop = mainBottom + subGap;
  const subBottom = subTop + subH;

  const sIdx = Math.max(0, Math.min(taState.candles.length - 1, taState.viewStart));
  const eIdx = Math.max(sIdx, Math.min(taState.candles.length - 1, taState.viewEnd));
  const count = Math.max(1, eIdx - sIdx + 1);

  let minP = Infinity;
  let maxP = -Infinity;
  for (let i = sIdx; i <= eIdx; i++) {
    const c = taState.candles[i];
    if (!c) continue;
    if (c.low < minP) minP = c.low;
    if (c.high > maxP) maxP = c.high;
    if (taState.indicators.bb && taState.computed.bbUpper && taState.computed.bbUpper[i] !== null) {
      if (taState.computed.bbUpper[i] > maxP) maxP = taState.computed.bbUpper[i];
      if (taState.computed.bbLower[i] < minP) minP = taState.computed.bbLower[i];
    }
  }
  if (taState.indicators.plan && taState.tradingPlan) {
    const p = taState.tradingPlan;
    [p.stop_loss, p.entry_low, p.entry_high, p.target_1, p.target_2].forEach((val) => {
      if (val && val > 0) {
        if (val < minP * 0.82 || val > maxP * 1.22) return;
        if (val < minP) minP = val;
        if (val > maxP) maxP = val;
      }
    });
  }
  if (!isFinite(minP) || !isFinite(maxP) || minP === maxP) {
    minP = (minP || 100) * 0.95;
    maxP = (maxP || 100) * 1.05;
  }
  const marginP = (maxP - minP) * 0.08;
  minP -= marginP;
  maxP += marginP;

  const idxToX = (idx) => padLeft + ((idx - sIdx + 0.5) / count) * plotW;
  const xToIdx = (x) => sIdx + ((x - padLeft) / plotW) * count - 0.5;
  const priceToY = (p) => mainBottom - ((p - minP) / (maxP - minP)) * mainH;
  const yToPrice = (y) => minP + ((mainBottom - y) / mainH) * (maxP - minP);

  return {
    w,
    h,
    padLeft,
    padRight,
    padTop,
    padBottom,
    plotW,
    mainTop,
    mainBottom,
    mainH,
    subTop,
    subBottom,
    subH,
    sIdx,
    eIdx,
    count,
    minP,
    maxP,
    idxToX,
    xToIdx,
    priceToY,
    yToPrice,
  };
}

function _initTACanvasEvents() {
  if (taState.listenersAttached) return;
  const canvas = document.getElementById('taStudioCanvas');
  if (!canvas) return;
  taState.listenersAttached = true;

  const getPos = (e) => {
    const rect = canvas.getBoundingClientRect();
    const clientX = e.touches && e.touches.length ? e.touches[0].clientX : e.clientX;
    const clientY = e.touches && e.touches.length ? e.touches[0].clientY : e.clientY;
    return { x: clientX - rect.left, y: clientY - rect.top };
  };

  const onDown = (e) => {
    if (!taState.candles.length) return;
    const pos = getPos(e);
    const layout = _getTALayout(canvas);
    const idx = layout.xToIdx(pos.x);
    const price = layout.yToPrice(pos.y);

    if (taState.tool === 'pan') {
      taState.isDragging = true;
      taState.dragStartX = pos.x;
      taState.dragStartViewStart = taState.viewStart;
      taState.dragStartViewEnd = taState.viewEnd;
      canvas.style.cursor = 'grabbing';
      return;
    }

    if (taState.tool === 'hline') {
      taState.drawings.push({
        type: 'hline',
        color: taState.color,
        p1: { idx, price },
        p2: { idx, price },
      });
      _saveTADrawings();
      renderTAStudio();
      return;
    }

    if (taState.tool === 'brush') {
      taState.isDragging = true;
      taState.activeDrawing = {
        type: 'brush',
        color: taState.color,
        points: [{ idx, price }],
      };
      return;
    }

    // Two-point tools: trendline, ray, fib, rect, measure
    taState.isDragging = true;
    taState.activeDrawing = {
      type: taState.tool,
      color: taState.color,
      p1: { idx, price },
      p2: { idx, price },
    };
    renderTAStudio();
  };

  const onMove = (e) => {
    if (!taState.candles.length) return;
    const pos = getPos(e);
    taState.hoverPos = pos;
    const layout = _getTALayout(canvas);

    if (taState.isDragging) {
      if (e.cancelable) e.preventDefault();
      if (taState.tool === 'pan') {
        const dx = pos.x - taState.dragStartX;
        const span = taState.dragStartViewEnd - taState.dragStartViewStart + 1;
        const shiftBars = Math.round((-dx / layout.plotW) * span);
        const total = taState.candles.length;
        let ns = taState.dragStartViewStart + shiftBars;
        let ne = taState.dragStartViewEnd + shiftBars;
        if (ns < 0) {
          ns = 0;
          ne = Math.min(total - 1, span - 1);
        }
        if (ne >= total) {
          ne = total - 1;
          ns = Math.max(0, total - span);
        }
        taState.viewStart = ns;
        taState.viewEnd = ne;
      } else if (taState.activeDrawing) {
        const idx = layout.xToIdx(pos.x);
        const price = layout.yToPrice(pos.y);
        if (taState.activeDrawing.type === 'brush') {
          taState.activeDrawing.points.push({ idx, price });
        } else {
          taState.activeDrawing.p2 = { idx, price };
        }
      }
    }
    renderTAStudio();
  };

  const onUp = () => {
    if (taState.tool === 'pan') {
      canvas.style.cursor = 'grab';
    }
    if (taState.isDragging && taState.activeDrawing) {
      taState.drawings.push(taState.activeDrawing);
      taState.activeDrawing = null;
      _saveTADrawings();
    }
    taState.isDragging = false;
    renderTAStudio();
  };

  canvas.addEventListener('mousedown', onDown);
  window.addEventListener('mousemove', (e) => {
    const modal = document.getElementById('tradingViewModal');
    if (!modal || modal.classList.contains('hidden')) return;
    const rect = canvas.getBoundingClientRect();
    if (
      e.clientX >= rect.left &&
      e.clientX <= rect.right &&
      e.clientY >= rect.top &&
      e.clientY <= rect.bottom
    ) {
      onMove(e);
    }
  });
  window.addEventListener('mouseup', onUp);

  canvas.addEventListener('touchstart', onDown, { passive: false });
  canvas.addEventListener('touchmove', onMove, { passive: false });
  canvas.addEventListener('touchend', onUp);

  canvas.addEventListener(
    'wheel',
    (e) => {
      e.preventDefault();
      zoomTAChart(e.deltaY < 0 ? 1.18 : 0.85);
    },
    { passive: false }
  );

  window.addEventListener('resize', () => {
    const modal = document.getElementById('tradingViewModal');
    if (modal && !modal.classList.contains('hidden')) {
      renderTAStudio();
    }
  });
}

function _drawSingleTAObject(ctx, d, layout) {
  ctx.save();
  ctx.strokeStyle = d.color || '#f59e0b';
  ctx.fillStyle = d.color || '#f59e0b';
  ctx.lineWidth = 2;

  if (d.type === 'hline') {
    const y = layout.priceToY(d.p1.price);
    if (y >= layout.mainTop && y <= layout.mainBottom) {
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      ctx.moveTo(layout.padLeft, y);
      ctx.lineTo(layout.padLeft + layout.plotW, y);
      ctx.stroke();
      ctx.setLineDash([]);
      // Price tag on right axis
      ctx.fillRect(layout.padLeft + layout.plotW + 2, y - 9, layout.padRight - 6, 18);
      ctx.fillStyle = '#0f172a';
      ctx.font = 'bold 10px JetBrains Mono, monospace';
      ctx.fillText(`S/R ${fmtNumber(d.p1.price)}`, layout.padLeft + layout.plotW + 5, y + 3);
    }
    ctx.restore();
    return;
  }

  if (d.type === 'brush' && d.points && d.points.length > 1) {
    ctx.beginPath();
    d.points.forEach((pt, i) => {
      const x = layout.idxToX(pt.idx);
      const y = layout.priceToY(pt.price);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.restore();
    return;
  }

  if (!d.p1 || !d.p2) {
    ctx.restore();
    return;
  }

  const x1 = layout.idxToX(d.p1.idx);
  const y1 = layout.priceToY(d.p1.price);
  const x2 = layout.idxToX(d.p2.idx);
  const y2 = layout.priceToY(d.p2.price);

  if (d.type === 'trendline' || d.type === 'ray') {
    ctx.beginPath();
    ctx.moveTo(x1, y1);
    if (d.type === 'ray' && Math.abs(x2 - x1) > 1) {
      const slope = (y2 - y1) / (x2 - x1);
      const targetX = x2 >= x1 ? layout.padLeft + layout.plotW : layout.padLeft;
      const targetY = y1 + slope * (targetX - x1);
      ctx.lineTo(targetX, targetY);
    } else {
      ctx.lineTo(x2, y2);
    }
    ctx.stroke();

    // Anchor circles
    [
      [x1, y1],
      [x2, y2],
    ].forEach(([ax, ay]) => {
      ctx.beginPath();
      ctx.arc(ax, ay, 3.5, 0, Math.PI * 2);
      ctx.fill();
    });
  } else if (d.type === 'rect') {
    const rx = Math.min(x1, x2);
    const ry = Math.min(y1, y2);
    const rw = Math.abs(x2 - x1);
    const rh = Math.abs(y2 - y1);
    ctx.globalAlpha = 0.18;
    ctx.fillRect(rx, ry, rw, rh);
    ctx.globalAlpha = 0.85;
    ctx.strokeRect(rx, ry, rw, rh);
  } else if (d.type === 'measure') {
    const rx = Math.min(x1, x2);
    const ry = Math.min(y1, y2);
    const rw = Math.abs(x2 - x1);
    const rh = Math.abs(y2 - y1);
    const diffP = d.p2.price - d.p1.price;
    const pct = (diffP / Math.max(1, d.p1.price)) * 100;
    const bars = Math.abs(Math.round(d.p2.idx - d.p1.idx));
    const isUp = diffP >= 0;

    ctx.fillStyle = isUp ? 'rgba(16, 185, 129, 0.18)' : 'rgba(244, 63, 94, 0.18)';
    ctx.strokeStyle = isUp ? '#10b981' : '#f43f5e';
    ctx.fillRect(rx, ry, rw, rh);
    ctx.setLineDash([4, 4]);
    ctx.strokeRect(rx, ry, rw, rh);
    ctx.setLineDash([]);

    // Label pill
    const lbl = `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}% (Rp ${diffP >= 0 ? '+' : ''}${fmtNumber(diffP)} | ${bars} Bar)`;
    ctx.font = 'bold 11px JetBrains Mono, monospace';
    const tw = ctx.measureText(lbl).width + 14;
    const bx = Math.min(layout.padLeft + layout.plotW - tw, Math.max(layout.padLeft, (x1 + x2) / 2 - tw / 2));
    const by = Math.max(layout.mainTop + 20, Math.min(y1, y2) - 8);
    ctx.fillStyle = isUp ? '#065f46' : '#881337';
    ctx.fillRect(bx, by - 16, tw, 22);
    ctx.strokeRect(bx, by - 16, tw, 22);
    ctx.fillStyle = '#ffffff';
    ctx.fillText(lbl, bx + 7, by - 1);
  } else if (d.type === 'fib') {
    const levels = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
    const minX = Math.min(x1, x2);
    const maxX = Math.max(x1, x2, minX + 120);
    ctx.font = '10px JetBrains Mono, monospace';
    levels.forEach((lv) => {
      const p = d.p1.price + (d.p2.price - d.p1.price) * lv;
      const y = layout.priceToY(p);
      if (y < layout.mainTop || y > layout.mainBottom) return;
      ctx.beginPath();
      ctx.setLineDash([3, 3]);
      ctx.moveTo(minX, y);
      ctx.lineTo(maxX, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillText(`Fib ${(lv * 100).toFixed(1)}% (Rp ${fmtNumber(p)})`, minX + 4, y - 3);
    });
  }

  ctx.restore();
}

function renderTAStudio() {
  const canvas = document.getElementById('taStudioCanvas');
  if (!canvas || !taState.candles.length) return;

  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 900;
  const h = canvas.clientHeight || 520;
  if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }

  const ctx = canvas.getContext('2d');
  ctx.save();
  ctx.scale(dpr, dpr);

  const layout = _getTALayout(canvas);

  // Background
  ctx.fillStyle = '#020617';
  ctx.fillRect(0, 0, w, h);

  // Horizontal price grid lines (Main Panel)
  ctx.strokeStyle = 'rgba(51, 65, 85, 0.35)';
  ctx.fillStyle = '#94a3b8';
  ctx.font = '10px JetBrains Mono, monospace';
  ctx.lineWidth = 1;
  const gridSteps = 6;
  for (let i = 0; i <= gridSteps; i++) {
    const p = layout.minP + ((layout.maxP - layout.minP) * i) / gridSteps;
    const y = layout.priceToY(p);
    ctx.beginPath();
    ctx.moveTo(layout.padLeft, y);
    ctx.lineTo(layout.padLeft + layout.plotW, y);
    ctx.stroke();
    ctx.fillText(fmtNumber(p), layout.padLeft + layout.plotW + 6, y + 3);
  }

  // Vertical date grid lines
  const stepX = Math.max(1, Math.floor(layout.count / 8));
  for (let i = layout.sIdx; i <= layout.eIdx; i += stepX) {
    const x = layout.idxToX(i);
    ctx.beginPath();
    ctx.moveTo(x, layout.mainTop);
    ctx.lineTo(x, layout.subBottom);
    ctx.stroke();
    const dt = taState.candles[i]?.date || '';
    ctx.fillText(dt.slice(5), x - 14, layout.subBottom + 14);
  }

  // Clip Main Panel
  ctx.save();
  ctx.beginPath();
  ctx.rect(layout.padLeft, layout.mainTop, layout.plotW, layout.mainH);
  ctx.clip();

  // Bollinger Bands
  if (taState.indicators.bb && taState.computed.bbUpper) {
    ctx.fillStyle = 'rgba(56, 189, 248, 0.07)';
    ctx.beginPath();
    let started = false;
    for (let i = layout.sIdx; i <= layout.eIdx; i++) {
      const u = taState.computed.bbUpper[i];
      if (u === null) continue;
      const x = layout.idxToX(i);
      const y = layout.priceToY(u);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else ctx.lineTo(x, y);
    }
    for (let i = layout.eIdx; i >= layout.sIdx; i--) {
      const l = taState.computed.bbLower[i];
      if (l === null) continue;
      ctx.lineTo(layout.idxToX(i), layout.priceToY(l));
    }
    ctx.closePath();
    ctx.fill();

    ['bbUpper', 'bbLower'].forEach((k) => {
      ctx.strokeStyle = 'rgba(56, 189, 248, 0.45)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      let st = false;
      for (let i = layout.sIdx; i <= layout.eIdx; i++) {
        const v = taState.computed[k][i];
        if (v === null) continue;
        const x = layout.idxToX(i);
        const y = layout.priceToY(v);
        if (!st) {
          ctx.moveTo(x, y);
          st = true;
        } else ctx.lineTo(x, y);
      }
      ctx.stroke();
    });
  }

  // Auto Trading Plan Overlay (Entry Zone, SL, TP1, TP2, Avg Bandar)
  if (taState.indicators.plan && taState.tradingPlan) {
    const p = taState.tradingPlan;
    if (p.entry_low && p.entry_high) {
      const yHigh = layout.priceToY(p.entry_high);
      const yLow = layout.priceToY(p.entry_low);
      ctx.fillStyle = 'rgba(16, 185, 129, 0.13)';
      ctx.fillRect(layout.padLeft, Math.min(yHigh, yLow), layout.plotW, Math.max(2, Math.abs(yLow - yHigh)));
    }
    const planLines = [
      { price: p.target_2, label: `TP2 Rp ${fmtNumber(p.target_2)}`, color: '#2dd4bf' },
      { price: p.target_1, label: `TP1 Rp ${fmtNumber(p.target_1)}`, color: '#10b981' },
      { price: p.entry_high, label: `Entry Rp ${fmtNumber(p.entry_low)}-${fmtNumber(p.entry_high)}`, color: '#38bdf8' },
      { price: p.bandar_avg_buy, label: `Avg Bandar Rp ${fmtNumber(p.bandar_avg_buy)}`, color: '#f59e0b' },
      { price: p.stop_loss, label: `SL Rp ${fmtNumber(p.stop_loss)}`, color: '#f43f5e' },
    ];
    planLines.forEach((pl) => {
      if (!pl.price || pl.price <= 0) return;
      const y = layout.priceToY(pl.price);
      if (y < layout.mainTop || y > layout.mainBottom) return;
      ctx.strokeStyle = pl.color;
      ctx.lineWidth = 1.2;
      ctx.setLineDash([5, 5]);
      ctx.beginPath();
      ctx.moveTo(layout.padLeft, y);
      ctx.lineTo(layout.padLeft + layout.plotW, y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = pl.color;
      ctx.font = 'bold 10px JetBrains Mono, monospace';
      ctx.fillText(pl.label, layout.padLeft + 8, y - 4);
    });
  }

  // Candlesticks or Line
  const barW = Math.max(2, Math.min(18, (layout.plotW / layout.count) * 0.72));
  if (taState.indicators.candle) {
    for (let i = layout.sIdx; i <= layout.eIdx; i++) {
      const c = taState.candles[i];
      if (!c) continue;
      const x = layout.idxToX(i);
      const yO = layout.priceToY(c.open);
      const yC = layout.priceToY(c.close);
      const yH = layout.priceToY(c.high);
      const yL = layout.priceToY(c.low);
      const isUp = c.close >= c.open;
      const col = isUp ? '#10b981' : '#f43f5e';

      ctx.strokeStyle = col;
      ctx.fillStyle = col;
      ctx.lineWidth = 1.3;
      ctx.beginPath();
      ctx.moveTo(x, yH);
      ctx.lineTo(x, yL);
      ctx.stroke();

      const bodyTop = Math.min(yO, yC);
      const bodyH = Math.max(1.5, Math.abs(yC - yO));
      ctx.fillRect(x - barW / 2, bodyTop, barW, bodyH);
    }
  } else {
    ctx.strokeStyle = '#10b981';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = layout.sIdx; i <= layout.eIdx; i++) {
      const c = taState.candles[i];
      const x = layout.idxToX(i);
      const y = layout.priceToY(c.close);
      if (i === layout.sIdx) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // Moving Averages (MA20, MA50, EMA9)
  const drawLineSeries = (arr, color, width = 1.6) => {
    if (!arr) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.beginPath();
    let started = false;
    for (let i = layout.sIdx; i <= layout.eIdx; i++) {
      const val = arr[i];
      if (val === null || val === undefined) continue;
      const x = layout.idxToX(i);
      const y = layout.priceToY(val);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else ctx.lineTo(x, y);
    }
    ctx.stroke();
  };

  if (taState.indicators.ma20) drawLineSeries(taState.computed.ma20, '#3b82f6', 1.7);
  if (taState.indicators.ma50) drawLineSeries(taState.computed.ma50, '#f59e0b', 1.7);
  if (taState.indicators.ema9) drawLineSeries(taState.computed.ema9, '#c084fc', 1.5);

  ctx.restore(); // end Main Panel clip

  // User Drawings & Active Drawing
  taState.drawings.forEach((d) => _drawSingleTAObject(ctx, d, layout));
  if (taState.activeDrawing) {
    _drawSingleTAObject(ctx, taState.activeDrawing, layout);
  }

  // Divider between Main and Sub Panel
  ctx.strokeStyle = '#1e293b';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(layout.padLeft, layout.subTop - 6);
  ctx.lineTo(layout.padLeft + layout.plotW, layout.subTop - 6);
  ctx.stroke();

  // Sub-Panel (Volume / RSI / MACD)
  ctx.save();
  ctx.beginPath();
  ctx.rect(layout.padLeft, layout.subTop, layout.plotW, layout.subH);
  ctx.clip();

  if (taState.subPanel === 'vol') {
    let maxV = 1;
    for (let i = layout.sIdx; i <= layout.eIdx; i++) {
      const v = taState.candles[i]?.volume_lot || 0;
      if (v > maxV) maxV = v;
    }
    for (let i = layout.sIdx; i <= layout.eIdx; i++) {
      const c = taState.candles[i];
      const x = layout.idxToX(i);
      const bh = ((c.volume_lot || 0) / maxV) * (layout.subH - 8);
      ctx.fillStyle = c.close >= c.open ? 'rgba(16, 185, 129, 0.55)' : 'rgba(244, 68, 68, 0.55)';
      ctx.fillRect(x - barW / 2, layout.subBottom - bh, barW, bh);
    }
    // Vol MA20 line
    if (taState.computed.volMa20) {
      ctx.strokeStyle = '#f59e0b';
      ctx.lineWidth = 1.3;
      ctx.beginPath();
      let st = false;
      for (let i = layout.sIdx; i <= layout.eIdx; i++) {
        const vm = taState.computed.volMa20[i];
        if (vm === null) continue;
        const x = layout.idxToX(i);
        const y = layout.subBottom - (vm / maxV) * (layout.subH - 8);
        if (!st) {
          ctx.moveTo(x, y);
          st = true;
        } else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    ctx.fillStyle = '#94a3b8';
    ctx.font = '10px JetBrains Mono, monospace';
    ctx.fillText('Volume (Lot) + MA20', layout.padLeft + 6, layout.subTop + 12);
  } else if (taState.subPanel === 'rsi') {
    const y70 = layout.subBottom - (70 / 100) * layout.subH;
    const y30 = layout.subBottom - (30 / 100) * layout.subH;
    ctx.fillStyle = 'rgba(148, 163, 184, 0.06)';
    ctx.fillRect(layout.padLeft, y70, layout.plotW, y30 - y70);
    ctx.strokeStyle = 'rgba(244, 63, 94, 0.4)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(layout.padLeft, y70);
    ctx.lineTo(layout.padLeft + layout.plotW, y70);
    ctx.moveTo(layout.padLeft, y30);
    ctx.lineTo(layout.padLeft + layout.plotW, y30);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 1.6;
    ctx.beginPath();
    let st = false;
    for (let i = layout.sIdx; i <= layout.eIdx; i++) {
      const r = taState.computed.rsi14?.[i];
      if (r === null || r === undefined) continue;
      const x = layout.idxToX(i);
      const y = layout.subBottom - (r / 100) * layout.subH;
      if (!st) {
        ctx.moveTo(x, y);
        st = true;
      } else ctx.lineTo(x, y);
    }
    ctx.stroke();
    ctx.fillStyle = '#38bdf8';
    ctx.font = '10px JetBrains Mono, monospace';
    ctx.fillText('RSI (14) [70 / 30]', layout.padLeft + 6, layout.subTop + 12);
  } else if (taState.subPanel === 'macd') {
    let maxM = 1;
    for (let i = layout.sIdx; i <= layout.eIdx; i++) {
      const m1 = Math.abs(taState.computed.macdLine?.[i] || 0);
      const m2 = Math.abs(taState.computed.macdSignal?.[i] || 0);
      const m3 = Math.abs(taState.computed.macdHist?.[i] || 0);
      maxM = Math.max(maxM, m1, m2, m3);
    }
    const zeroY = layout.subTop + layout.subH / 2;
    ctx.strokeStyle = 'rgba(148, 163, 184, 0.25)';
    ctx.beginPath();
    ctx.moveTo(layout.padLeft, zeroY);
    ctx.lineTo(layout.padLeft + layout.plotW, zeroY);
    ctx.stroke();

    for (let i = layout.sIdx; i <= layout.eIdx; i++) {
      const hVal = taState.computed.macdHist?.[i] || 0;
      const x = layout.idxToX(i);
      const bh = (Math.abs(hVal) / maxM) * (layout.subH * 0.42);
      ctx.fillStyle = hVal >= 0 ? 'rgba(16, 185, 129, 0.55)' : 'rgba(244, 63, 94, 0.55)';
      ctx.fillRect(x - barW / 2, hVal >= 0 ? zeroY - bh : zeroY, barW, bh);
    }

    const drawMacdCurve = (arr, col) => {
      ctx.strokeStyle = col;
      ctx.lineWidth = 1.4;
      ctx.beginPath();
      for (let i = layout.sIdx; i <= layout.eIdx; i++) {
        const v = arr?.[i] || 0;
        const x = layout.idxToX(i);
        const y = zeroY - (v / maxM) * (layout.subH * 0.42);
        if (i === layout.sIdx) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    };
    drawMacdCurve(taState.computed.macdLine, '#38bdf8');
    drawMacdCurve(taState.computed.macdSignal, '#f59e0b');
    ctx.fillStyle = '#38bdf8';
    ctx.font = '10px JetBrains Mono, monospace';
    ctx.fillText('MACD (12, 26, 9)', layout.padLeft + 6, layout.subTop + 12);
  }
  ctx.restore(); // end Sub-Panel clip

  // Crosshair & Live OHLCV Info Update
  let hoverIdx = layout.eIdx;
  if (taState.hoverPos) {
    const { x, y } = taState.hoverPos;
    if (x >= layout.padLeft && x <= layout.padLeft + layout.plotW) {
      hoverIdx = Math.max(layout.sIdx, Math.min(layout.eIdx, Math.round(layout.xToIdx(x))));
      const snapX = layout.idxToX(hoverIdx);

      ctx.strokeStyle = 'rgba(148, 163, 184, 0.5)';
      ctx.lineWidth = 1;
      ctx.setLineDash([4, 4]);
      ctx.beginPath();
      ctx.moveTo(snapX, layout.mainTop);
      ctx.lineTo(snapX, layout.subBottom);
      if (y >= layout.mainTop && y <= layout.mainBottom) {
        ctx.moveTo(layout.padLeft, y);
        ctx.lineTo(layout.padLeft + layout.plotW, y);
      }
      ctx.stroke();
      ctx.setLineDash([]);

      if (y >= layout.mainTop && y <= layout.mainBottom) {
        const curP = layout.yToPrice(y);
        ctx.fillStyle = '#1e293b';
        ctx.fillRect(layout.padLeft + layout.plotW + 2, y - 9, layout.padRight - 6, 18);
        ctx.fillStyle = '#38bdf8';
        ctx.font = 'bold 10px JetBrains Mono, monospace';
        ctx.fillText(fmtNumber(curP), layout.padLeft + layout.plotW + 6, y + 3);
      }
    }
  }

  const hc = taState.candles[hoverIdx];
  const prevC = hoverIdx > 0 ? taState.candles[hoverIdx - 1].close : hc?.open || 1;
  const chgPct = hc ? (((hc.close - prevC) / Math.max(1, prevC)) * 100).toFixed(2) : '0.00';
  const infoBar = document.getElementById('taCrosshairInfo');
  if (infoBar && hc) {
    const ma20v = taState.computed.ma20?.[hoverIdx];
    const ma50v = taState.computed.ma50?.[hoverIdx];
    const rsiv = taState.computed.rsi14?.[hoverIdx];
    infoBar.innerHTML = `
      <span>📅 <b class="text-white">${hc.date}</b></span>
      <span>O: <b class="text-slate-200">${fmtNumber(hc.open)}</b></span>
      <span>H: <b class="text-emerald-400">${fmtNumber(hc.high)}</b></span>
      <span>L: <b class="text-rose-400">${fmtNumber(hc.low)}</b></span>
      <span>C: <b class="${hc.close >= prevC ? 'text-emerald-400' : 'text-rose-400'}">${fmtNumber(hc.close)} (${chgPct >= 0 ? '+' : ''}${chgPct}%)</b></span>
      <span>Vol: <b class="text-amber-300">${fmtNumber(hc.volume_lot)} Lot</b></span>
      <span class="text-blue-400">MA20: <b>${ma20v ? fmtNumber(ma20v) : '-'}</b></span>
      <span class="text-amber-400">MA50: <b>${ma50v ? fmtNumber(ma50v) : '-'}</b></span>
      <span class="text-sky-400">RSI(14): <b>${rsiv ? rsiv.toFixed(1) : '-'}</b></span>
    `;
  }

  ctx.restore();
}

async function handleExcelUpload(fileList) {
  if (!fileList || !fileList.length) return;
  const formData = new FormData();
  const filesArr = Array.from(fileList);
  filesArr.forEach((f) => formData.append('files', f));

  try {
    const label = filesArr.length === 1 ? filesArr[0].name : `${filesArr.length} file Excel`;
    showToast(`Sedang memproses & menganalisis ${label}...`);
    const res = await fetch('/api/upload', {
      method: 'POST',
      body: formData,
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Gagal memproses file Excel');
    }
    closeUploadModal();
    showToast(data.message || `Berhasil memuat ${label}`);
    await loadScreenerData(false);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function handleLoadLocalPath() {
  const pathInput = document.getElementById('localPathInput');
  const rawPath = pathInput ? pathInput.value.trim() : '';
  if (!rawPath) {
    showToast('Masukkan lokasi path file atau folder Excel terlebih dahulu.', 'error');
    return;
  }

  try {
    showToast(`Sedang membaca data saham dari ${rawPath}...`);
    const res = await fetch('/api/load-path', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: rawPath }),
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Gagal membaca path file/folder');
    }
    closeUploadModal();
    showToast(data.message);
    await loadScreenerData(false);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function syncFastMarketData() {
  if (isSyncingFast) return;
  isSyncingFast = true;
  const btn = document.getElementById('btnSyncFast');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Memeriksa...';
  }
  try {
    showToast('⚡ Mengevaluasi harga live Screener, Watchlist & Running...');
    const res = await fetch('/api/sync-fast', { method: 'POST', cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Gagal sync cepat');
    showToast(data.message || '⚡ Status Screener, Watchlist & Running berhasil diperbarui!');
    await Promise.all([loadScreenerData(true), loadTracker()]);
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    isSyncingFast = false;
    if (btn) {
      btn.disabled = false;
      btn.textContent = '⚡ Sync Cepat (< 2s)';
    }
  }
}

async function syncLiveMarketData() {
  const btn = document.getElementById('btnSyncLive');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Sync Background...';
  }
  try {
    showToast('🚀 Memulai unduh paralel 844 saham di background (~30s)...');
    const res = await fetch('/api/sync-live', { method: 'POST', cache: 'no-store' });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || 'Gagal sinkronisasi live data');
    }
    showToast(data.message);

    // Polling status background worker via /api/health setiap 6 detik
    let pollCount = 0;
    const pollInterval = setInterval(async () => {
      pollCount++;
      try {
        const hRes = await fetch(`/api/health?_t=${Date.now()}`, { cache: 'no-store' });
        const hData = await hRes.json();
        if (!hData.is_syncing || pollCount >= 20) {
          clearInterval(pollInterval);
          if (btn) {
            btn.disabled = false;
            btn.textContent = '🔄 Full Sync IDX';
          }
          await Promise.all([loadScreenerData(true), loadTracker()]);
          showToast('✅ Pembaruan seluruh 844 saham IDX selesai!', 'success');
        }
      } catch {
        // ignore polling network errors
      }
    }, 6000);
  } catch (err) {
    showToast(err.message, 'error');
    if (btn) {
      btn.disabled = false;
      btn.textContent = '🔄 Full Sync IDX';
    }
  }
}

// Event Listeners Setup
document.addEventListener('DOMContentLoaded', async () => {
  // 1. Tampilkan data awal secepat mungkin
  await Promise.all([loadScreenerData(false), loadTracker()]);

  // 2. Otomatis tarik harga live & riwayat chart terbaru dari bursa di latar belakang saat web pertama dibuka!
  // Pengguna tidak perlu lagi mengklik tombol sync manual.
  (async () => {
    try {
      await fetch('/api/sync-fast', { method: 'POST', cache: 'no-store' });
      await Promise.all([loadScreenerData(true), loadTracker()]);
    } catch (e) {
      console.debug('Initial auto-sync background:', e);
    }
  })();

  ['filterTrigger', 'filterVolRatio', 'filterMinScore', 'filterSortBy'].forEach((id) => {
    document.getElementById(id).addEventListener('change', () => loadScreenerData(true));
  });

  let searchTimeout = null;
  document.getElementById('filterSearch').addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => loadScreenerData(true), 200);
  });

  const guideBtn = document.getElementById('btnOpenGuideModal');
  if (guideBtn) guideBtn.addEventListener('click', openGuideModal);

  // Setup Live Market Auto Poller & Anti-Sleep Keep-Alive
  initLiveMarketAutoSync();
});

// =====================================================================
// REALTIME MARKET SESSION AUTO-SYNC & ANTI-SLEEP ENGINE
// =====================================================================
let autoSyncTimerId = null;
let keepAliveTimerId = null;

function isIDXMarketOpenNow() {
  // Waktu Indonesia Barat (WIB = UTC+7)
  const now = new Date();
  const utcHours = now.getUTCHours();
  const utcMinutes = now.getUTCMinutes();
  const wibHours = (utcHours + 7) % 24;
  const wibMinutes = utcMinutes;
  const dayOfWeek = (now.getUTCDay() + (utcHours + 7 >= 24 ? 1 : 0)) % 7; // 0=Sun, 6=Sat

  // Senin (1) s/d Jumat (5)
  const isWeekday = dayOfWeek >= 1 && dayOfWeek <= 5;
  // Jam Bursa: 09:00 s/d 16:05 WIB
  const wibTotalMins = wibHours * 60 + wibMinutes;
  const isMarketHours = wibTotalMins >= 9 * 60 && wibTotalMins <= 16 * 60 + 5;

  return isWeekday && isMarketHours;
}

function updateMarketLiveStatusUI() {
  const isLive = isIDXMarketOpenNow();
  const pill = document.getElementById('marketLivePill');
  const dot = document.getElementById('marketStatusDot');
  const text = document.getElementById('marketStatusText');
  const timer = document.getElementById('marketAutoTimer');

  if (!pill) return;

  if (isLive) {
    if (dot) dot.className = 'w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse';
    if (text) {
      text.textContent = 'BURSA LIVE';
      text.className = 'font-bold text-emerald-300';
    }
    if (timer) timer.textContent = 'Auto-Update Tiap 60s';
  } else {
    if (dot) dot.className = 'w-2.5 h-2.5 rounded-full bg-slate-500';
    if (text) {
      text.textContent = 'BURSA TUTUP';
      text.className = 'font-bold text-slate-400';
    }
    if (timer) timer.textContent = 'Data Terakhir 16:00';
  }
}

function initLiveMarketAutoSync() {
  updateMarketLiveStatusUI();

  // 1. Ping server setiap 5 menit (Keep-Alive agar Render tidak tidur di jam bursa)
  if (keepAliveTimerId) clearInterval(keepAliveTimerId);
  keepAliveTimerId = setInterval(() => {
    if (isIDXMarketOpenNow()) {
      fetch(`/api/health?_t=${Date.now()}`, { cache: 'no-store' }).catch(() => {});
    }
  }, 5 * 60 * 1000);

  // 2. Auto-Sync Screener & Watchlist setiap 60 detik selama jam bursa aktif
  if (autoSyncTimerId) clearInterval(autoSyncTimerId);
  autoSyncTimerId = setInterval(async () => {
    updateMarketLiveStatusUI();
    if (isIDXMarketOpenNow() && !isSyncingFast) {
      try {
        // Otomatis tarik harga live saham Watchlist/Running & update Screener
        await fetch('/api/sync-fast', { method: 'POST', cache: 'no-store' }).catch(() => {});
        await Promise.all([
          loadScreenerData(true),
          loadTracker(),
        ]);
      } catch (err) {
        console.debug('Background market auto-update:', err);
      }
    }
  }, 60 * 1000);
}


// =====================================================================
// SIGNAL TRACKER — FORWARD TEST (Watchlist -> Running -> Win / Loss)
// =====================================================================
let trackerTab = 'ALL';
let trackerSortBy = 'pnl_desc'; // Default: Running Profit Terbanyak (Terbang Tinggi)
let currentTrackerSignals = [];
let trackerSearchTerm = '';

const TRACKER_STATUS_STYLE = {
  WATCHLIST: 'bg-sky-500/20 text-sky-300 border-sky-400/50 shadow-sm shadow-sky-500/20',
  RUNNING: 'bg-amber-500/25 text-amber-300 border-amber-400/60 shadow-sm shadow-amber-500/25',
  WIN: 'bg-emerald-500/25 text-emerald-300 border-emerald-400/60 shadow-sm shadow-emerald-500/25',
  LOSS: 'bg-rose-500/25 text-rose-300 border-rose-400/60 shadow-sm shadow-rose-500/25',
  EXPIRED: 'bg-slate-700/40 text-slate-300 border-slate-600',
  TIMEOUT: 'bg-purple-500/20 text-purple-300 border-purple-400/50 shadow-sm shadow-purple-500/20',
};

const fmtPctOrDash = (v) => (v === null || v === undefined ? '-' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`);
const pctClass = (v) => (v === null || v === undefined ? 'text-slate-400' : v >= 0 ? 'text-emerald-400' : 'text-rose-400');

async function loadTracker() {
  try {
    const [statsRes, sigRes] = await Promise.all([
      fetch(`/api/tracker/stats?_t=${Date.now()}`, { cache: 'no-store' }),
      fetch(`/api/tracker/signals?status=${encodeURIComponent(trackerTab)}&sort_by=${encodeURIComponent(trackerSortBy)}&_t=${Date.now()}`, { cache: 'no-store' }),
    ]);
    if (!statsRes.ok || !sigRes.ok) return;
    const statsData = await statsRes.json();
    const sigData = await sigRes.json();
    currentTrackerSignals = sigData.signals || [];
    renderTrackerStats(statsData);
    filterAndRenderTracker();
  } catch (err) {
    console.warn('Tracker error:', err);
  }
}

function changeTrackerSort(newSort) {
  trackerSortBy = newSort;
  const sel = document.getElementById('trackerSortSelect');
  if (sel) sel.value = newSort;
  updateTrackerSortIcons();
  loadTracker();
}

function toggleTrackerSort(field) {
  if (field === 'pnl') {
    trackerSortBy = trackerSortBy === 'pnl_desc' ? 'pnl_asc' : 'pnl_desc';
  } else if (field === 'ticker') {
    trackerSortBy = trackerSortBy === 'ticker_asc' ? 'ticker_desc' : 'ticker_asc';
  } else if (field === 'score') {
    trackerSortBy = trackerSortBy === 'score_desc' ? 'score_asc' : 'score_desc';
  } else if (field === 'date') {
    trackerSortBy = trackerSortBy === 'date_desc' ? 'date_asc' : 'date_desc';
  }
  const sel = document.getElementById('trackerSortSelect');
  if (sel) sel.value = trackerSortBy;
  updateTrackerSortIcons();
  loadTracker();
}

function updateTrackerSortIcons() {
  const icons = {
    pnl: document.getElementById('sortIconPnl'),
    ticker: document.getElementById('sortIconTicker'),
    score: document.getElementById('sortIconScore'),
    date: document.getElementById('sortIconDate'),
  };
  Object.values(icons).forEach((el) => { if (el) el.textContent = ''; });
  if (trackerSortBy === 'pnl_desc' && icons.pnl) icons.pnl.textContent = '▼';
  else if (trackerSortBy === 'pnl_asc' && icons.pnl) icons.pnl.textContent = '▲';
  else if (trackerSortBy === 'ticker_asc' && icons.ticker) icons.ticker.textContent = '▲';
  else if (trackerSortBy === 'ticker_desc' && icons.ticker) icons.ticker.textContent = '▼';
  else if (trackerSortBy === 'score_desc' && icons.score) icons.score.textContent = '▼';
  else if (trackerSortBy === 'score_asc' && icons.score) icons.score.textContent = '▲';
  else if (trackerSortBy === 'date_desc' && icons.date) icons.date.textContent = '▼';
  else if (trackerSortBy === 'date_asc' && icons.date) icons.date.textContent = '▲';
}

function filterTrackerRows() {
  const input = document.getElementById('trackerSearchInput');
  trackerSearchTerm = input ? input.value.trim().toUpperCase() : '';
  filterAndRenderTracker();
}

function filterAndRenderTracker() {
  let list = currentTrackerSignals;
  if (trackerSearchTerm) {
    list = list.filter((r) =>
      (r.ticker && r.ticker.toUpperCase().includes(trackerSearchTerm)) ||
      (r.trigger_label && r.trigger_label.toUpperCase().includes(trackerSearchTerm)) ||
      (r.sector && r.sector.toUpperCase().includes(trackerSearchTerm))
    );
  }
  renderTrackerTable(list);
}

function renderTrackerStats(data) {
  const s = data.stats;
  const c = data.config;

  document.getElementById('trackerConfigLine').textContent =
    `Auto-track: Score ≥ ${c.min_score} · Target TP${c.tp_level} · Entry kedaluwarsa ${c.entry_expiry_days} hari · ` +
    `Max hold ${c.max_hold_days} hari · Fee ${c.fee_roundtrip_pct}% · DB: ${c.db_backend} · Candle final s/d ${c.final_session_date}` +
    (data.last_tracker_run ? ` · Evaluasi terakhir: ${data.last_tracker_run}` : '') +
    (data.is_real_market ? '' : ' · ⚠ Dataset aktif bukan data real (tracker pause)');

  document.getElementById('tsWinRate').textContent = s.win_rate === null ? '-' : `${s.win_rate}%`;
  document.getElementById('tsDecided').textContent = s.decided ? `${s.win}W / ${s.loss}L dari ${s.decided} trade` : 'belum ada trade selesai';
  document.getElementById('tsWinBar').style.width = `${s.win_rate || 0}%`;

  document.getElementById('tsWatch').textContent = s.watchlist;
  document.getElementById('tsRunning').textContent = s.running;
  document.getElementById('tsRunningPnl').textContent = `floating ${fmtPctOrDash(s.running_avg_pnl_pct)}`;
  document.getElementById('tsWin').textContent = s.win;
  document.getElementById('tsAvgWin').textContent = `avg ${fmtPctOrDash(s.avg_win_pct)}`;
  document.getElementById('tsLoss').textContent = s.loss;
  document.getElementById('tsAvgLoss').textContent = `avg ${fmtPctOrDash(s.avg_loss_pct)}`;
  document.getElementById('tsExpired').textContent = s.expired;
  document.getElementById('tsTimeout').textContent = s.timeout;

  const pfEl = document.getElementById('tsPF');
  pfEl.textContent = s.profit_factor !== null ? s.profit_factor.toFixed(2) : s.win > 0 ? '∞' : '-';
  pfEl.className = `text-lg font-bold font-mono mt-0.5 ${s.profit_factor === null ? 'text-white' : s.profit_factor >= 1.5 ? 'text-emerald-400' : s.profit_factor >= 1 ? 'text-amber-300' : 'text-rose-400'}`;

  const expEl = document.getElementById('tsExp');
  expEl.textContent = fmtPctOrDash(s.expectancy_net_pct);
  expEl.className = `text-lg font-bold font-mono mt-0.5 ${pctClass(s.expectancy_net_pct)}`;

  const totEl = document.getElementById('tsTotal');
  totEl.textContent = s.decided || s.timeout ? fmtPctOrDash(s.total_return_net_pct) : '-';
  totEl.className = `text-lg font-bold font-mono mt-0.5 ${s.decided || s.timeout ? pctClass(s.total_return_net_pct) : 'text-white'}`;

  document.getElementById('tsTotalSignals').textContent = s.total;

  // Win rate per trigger
  const bt = Object.entries(s.by_trigger || {});
  const btEl = document.getElementById('tsByTrigger');
  btEl.innerHTML = bt.length
    ? bt
        .map(([type, b]) => {
          const wr = b.win_rate;
          return `
          <div class="bg-slate-950/70 border border-slate-800 rounded-xl p-3">
            <div class="flex items-center justify-between">
              <span class="inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold ${getTriggerBadgeClass(type)}">${b.label}</span>
              <span class="font-mono font-bold ${wr === null ? 'text-slate-400' : wr >= 50 ? 'text-emerald-400' : 'text-rose-400'}">${wr === null ? '-' : wr + '%'}</span>
            </div>
            <div class="mt-2 text-[11px] font-mono text-slate-400">
              ${b.total} sinyal · <span class="text-emerald-400">${b.win}W</span> / <span class="text-rose-400">${b.loss}L</span> · <span class="text-amber-300">${b.running} run</span>
            </div>
            <div class="text-[11px] font-mono ${pctClass(b.avg_pnl)}">Avg P/L: ${fmtPctOrDash(b.avg_pnl)}</div>
          </div>`;
        })
        .join('')
    : '<div class="text-slate-500 text-[11px]">Belum ada data.</div>';

  // Tab counts
  const counts = { ALL: s.total, WATCHLIST: s.watchlist, RUNNING: s.running, WIN: s.win, LOSS: s.loss, EXPIRED: s.expired, TIMEOUT: s.timeout };
  document.querySelectorAll('#trackerTabs .tracker-tab').forEach((btn) => {
    const tab = btn.dataset.tab;
    const label = btn.textContent.replace(/\s*\d+$/, '').trim();
    btn.innerHTML = `${label}<span class="tab-count">${counts[tab] ?? 0}</span>`;
    btn.classList.toggle('active', tab === trackerTab);
  });
}

function renderTrackerTable(rows) {
  const tbody = document.getElementById('trackerTableBody');
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="11" class="py-8 text-center text-slate-500">
      Belum ada sinyal pada kategori ini. Sinyal akumulasi dengan score tinggi akan otomatis tercatat setelah sinkronisasi data real.
    </td></tr>`;
    return;
  }

  tbody.innerHTML = rows
    .map((r) => {
      const statusCls = TRACKER_STATUS_STYLE[r.status] || TRACKER_STATUS_STYLE.EXPIRED;
      const isClosed = ['WIN', 'LOSS', 'EXPIRED', 'TIMEOUT'].includes(r.status);
      const exitOrLast = isClosed && r.exit_price
        ? `${fmtNumber(r.exit_price)}<div class="text-[10px] text-slate-500">${r.exit_date || ''}</div>`
        : `${fmtNumber(r.last_close)}<div class="text-[10px] text-slate-500">last</div>`;
      const entryCell = r.entry_price
        ? `${fmtNumber(r.entry_price)}<div class="text-[10px] text-slate-500">${r.entry_date || ''}</div>`
        : r.status === 'WATCHLIST' && r.dist_to_entry_pct !== undefined
        ? `<span class="text-slate-500">-</span><div class="text-[10px] text-blue-300">jarak ${fmtPctOrDash(r.dist_to_entry_pct)}</div>`
        : '<span class="text-slate-500">-</span>';
      const pnl = r.status === 'WATCHLIST' || r.status === 'EXPIRED' ? null : r.pnl_pct;

      // Desain P/L Cell & Badge Terbang Tinggi
      let pnlContent = '';
      let isHighFlyer = false;

      if (r.status === 'RUNNING') {
        if (pnl !== null && pnl >= 2.0) {
          isHighFlyer = true;
          pnlContent = `
            <div class="flex items-center justify-end gap-1">
              <span class="text-xs" title="Sedang Terbang Tinggi!">🚀</span>
              <span class="font-extrabold text-emerald-400 font-mono text-xs">${fmtPctOrDash(pnl)}</span>
            </div>
            <div class="text-[9px] font-bold uppercase tracking-wider text-emerald-300 bg-emerald-500/20 px-1.5 py-0.2 rounded border border-emerald-500/30 inline-block mt-0.5">
              Terbang Tinggi
            </div>`;
        } else if (pnl !== null && pnl > 0) {
          pnlContent = `
            <div class="font-bold text-emerald-400 font-mono text-xs">${fmtPctOrDash(pnl)}</div>
            <div class="text-[10px] text-emerald-500/80">floating profit</div>`;
        } else if (pnl !== null) {
          pnlContent = `
            <div class="font-bold text-rose-400 font-mono text-xs">${fmtPctOrDash(pnl)}</div>
            <div class="text-[10px] text-slate-500">floating loss</div>`;
        }
      } else if (r.status === 'WIN') {
        pnlContent = `
          <div class="flex items-center justify-end gap-1">
            <span class="text-xs">🏆</span>
            <span class="font-bold text-emerald-400 font-mono text-xs">${fmtPctOrDash(pnl)}</span>
          </div>
          <div class="text-[10px] text-emerald-500/80 font-medium">take profit</div>`;
      } else if (r.status === 'LOSS') {
        pnlContent = `
          <div class="font-bold text-rose-400 font-mono text-xs">${fmtPctOrDash(pnl)}</div>
          <div class="text-[10px] text-rose-500/80 font-medium">stop loss</div>`;
      } else {
        pnlContent = `<span class="text-slate-500">-</span>`;
      }

      const rowHighlight = isHighFlyer
        ? 'hover:bg-slate-800/60 bg-emerald-950/20 border-l-4 border-emerald-400'
        : 'hover:bg-slate-800/40 transition-colors';

      return `
      <tr class="${rowHighlight}">
        <!-- Saham -->
        <td class="py-3 pl-4 pr-2">
          <div class="flex items-center gap-2.5 cursor-pointer group" onclick="selectStock('${r.ticker}', true)" title="Klik untuk membuka Auto Trading Plan ${r.ticker}">
            ${getStockLogoImg(r.ticker, 'w-7 h-7')}
            <div>
              <div class="font-mono font-black text-sm text-white group-hover:text-emerald-300 flex items-center gap-1.5 transition">
                <span>${r.ticker}</span>
                ${isHighFlyer ? '<span class="text-xs" title="Terbang Tinggi">🚀</span>' : ''}
              </div>
              <div class="text-[10px] text-slate-400 group-hover:text-slate-300 truncate max-w-[140px] mt-0.5">${r.sector || (r.source === 'AUTO' ? '🤖 Auto Sinyal' : '👤 Watchlist Manual')}</div>
            </div>
          </div>
        </td>

        <!-- Trigger & Score -->
        <td class="py-3 px-2">
          <span class="inline-block px-2.5 py-1 rounded-full text-[10px] font-bold ${getTriggerBadgeClass(r.trigger_type)}">${r.trigger_label || '-'}</span>
          <span class="font-mono text-white ml-1.5 font-extrabold text-xs">${r.score ?? '-'}</span>
        </td>

        <!-- Tanggal Sinyal -->
        <td class="py-3 px-2 font-mono text-slate-300 text-xs">${r.signal_date}</td>

        <!-- Zona Entry -->
        <td class="py-3 px-2 text-right font-mono text-emerald-400 font-bold text-xs">${fmtNumber(r.entry_low)} - ${fmtNumber(r.entry_high)}</td>

        <!-- SL / TP -->
        <td class="py-3 px-2 text-right font-mono text-xs">
          <span class="text-rose-400 font-bold">${fmtNumber(r.stop_loss)}</span> / <span class="text-emerald-300 font-bold">${fmtNumber(r.target)}</span>
        </td>

        <!-- Status Pill Glowing (Matching Image) -->
        <td class="py-3 px-2 text-center">
          <span class="inline-block px-3 py-1 rounded-full border text-[11px] font-black tracking-wide ${statusCls}">
            ${r.status === 'RUNNING' ? 'Running' : r.status === 'WIN' ? 'Win' : r.status === 'WATCHLIST' ? 'Watchlist' : r.status === 'LOSS' ? 'Loss' : r.status}
          </span>
        </td>

        <!-- Entry Price -->
        <td class="py-3 px-2 text-right font-mono text-slate-100 font-semibold text-xs">${entryCell}</td>

        <!-- Last Price -->
        <td class="py-3 px-2 text-right font-mono text-slate-100 font-semibold text-xs">${exitOrLast}</td>

        <!-- P/L Badge (Pill Hijau / Merah Matching Image) -->
        <td class="py-3 px-2 text-right font-mono">
          ${pnl !== null ? `
            <span class="inline-block px-2.5 py-1 rounded-full text-xs font-black font-mono ${pnl >= 0 ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-400/60 shadow-sm shadow-emerald-500/20' : 'bg-rose-500/20 text-rose-300 border border-rose-400/60 shadow-sm shadow-rose-500/20'}">
              ${pnl >= 0 ? '+' : ''}${pnl.toFixed(1)}%
            </span>
          ` : '<span class="text-slate-500">-</span>'}
        </td>

        <!-- Action / Delete -->
        <td class="py-3 pl-2 pr-4 text-right">
          <button onclick="deleteSignal(${r.id})" class="text-slate-500 hover:text-rose-400 text-base font-bold transition px-1" title="Hapus sinyal">&times;</button>
        </td>
      </tr>`;
    })
    .join('');
}

function setTrackerTab(tab) {
  trackerTab = tab;
  // Jika tab RUNNING dipilih, otomatis urutkan dari profit tertinggi (terbang tinggi)
  if (tab === 'RUNNING' && trackerSortBy !== 'pnl_desc' && trackerSortBy !== 'pnl_asc') {
    trackerSortBy = 'pnl_desc';
    const sel = document.getElementById('trackerSortSelect');
    if (sel) sel.value = 'pnl_desc';
  }
  updateTrackerSortIcons();
  loadTracker();
}

async function addToWatchlist() {
  if (!selectedTicker) {
    showToast('Pilih saham terlebih dahulu dari tabel screener.', 'error');
    return;
  }
  try {
    const res = await fetch(`/api/tracker/add/${encodeURIComponent(selectedTicker)}`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Gagal menambahkan ke watchlist');
    showToast(data.message);
    await loadTracker();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function deleteSignal(id) {
  if (!confirm('Hapus sinyal ini dari tracker?')) return;
  const res = await fetch(`/api/tracker/signals/${id}`, { method: 'DELETE' });
  if (res.ok) {
    showToast('Sinyal dihapus.');
    await loadTracker();
  }
}

async function evaluateTracker() {
  const btn = document.getElementById('btnEvalTracker');
  btn.disabled = true;
  btn.textContent = '⏳ Mengevaluasi...';
  try {
    const res = await fetch('/api/tracker/evaluate', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Evaluasi gagal');
    showToast(data.message, data.result && data.result.skipped ? 'error' : 'success');
    await loadTracker();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '⚡ Evaluasi Sekarang';
  }
}

async function resetTracker() {
  if (!confirm('Hapus SEMUA catatan Watchlist/Running/Win/Loss dan mulai uji dari nol?')) return;
  const res = await fetch('/api/tracker/reset', { method: 'POST' });
  const data = await res.json();
  showToast(data.message);
  await loadTracker();
}


// =====================================================================
// TELEGRAM NOTIFIER INTEGRATION
// =====================================================================
function openTelegramModal() {
  const token = localStorage.getItem('smartflow_telegram_token') || '';
  const chatId = localStorage.getItem('smartflow_telegram_chat_id') || '';
  const tokenInput = document.getElementById('telegramBotToken');
  const chatInput = document.getElementById('telegramChatId');
  if (tokenInput && !tokenInput.value) tokenInput.value = token;
  if (chatInput && !chatInput.value) chatInput.value = chatId;
  const modal = document.getElementById('telegramModal');
  if (modal) modal.classList.remove('hidden');
}

function closeTelegramModal() {
  const modal = document.getElementById('telegramModal');
  if (modal) modal.classList.add('hidden');
}

function getTelegramCredentials() {
  const tokenInput = document.getElementById('telegramBotToken');
  const chatInput = document.getElementById('telegramChatId');
  const token = (tokenInput ? tokenInput.value.trim() : '') || localStorage.getItem('smartflow_telegram_token') || '';
  const chatId = (chatInput ? chatInput.value.trim() : '') || localStorage.getItem('smartflow_telegram_chat_id') || '';
  return { token, chatId };
}

async function testTelegramConnection() {
  const { token, chatId } = getTelegramCredentials();
  if (!token || !chatId) {
    showToast('Masukkan Bot Token dan Chat ID terlebih dahulu.', 'error');
    return;
  }
  const btn = document.getElementById('btnTestTelegram');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Menguji...';
  }
  try {
    const res = await fetch('/api/telegram/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ bot_token: token, chat_id: chatId }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Gagal terhubung ke Telegram');
    localStorage.setItem('smartflow_telegram_token', token);
    localStorage.setItem('smartflow_telegram_chat_id', chatId);
    showToast('🔔 ' + data.message, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '🔔 Tes Koneksi Bot';
    }
  }
}

async function handleTelegramClick() {
  const { token, chatId } = getTelegramCredentials();
  if (!token || !chatId) {
    try {
      const cRes = await fetch('/api/telegram/config');
      const cData = await cRes.json();
      if (!cData.configured) {
        openTelegramModal();
        return;
      }
    } catch {
      openTelegramModal();
      return;
    }
  }
  await sendTelegramRecommendations(token, chatId);
}

async function saveAndSendTelegram() {
  const tokenInput = document.getElementById('telegramBotToken');
  const chatInput = document.getElementById('telegramChatId');
  const token = tokenInput ? tokenInput.value.trim() : '';
  const chatId = chatInput ? chatInput.value.trim() : '';

  if (!token || !chatId) {
    showToast('Bot Token dan Chat ID wajib diisi.', 'error');
    return;
  }

  localStorage.setItem('smartflow_telegram_token', token);
  localStorage.setItem('smartflow_telegram_chat_id', chatId);

  closeTelegramModal();
  await sendTelegramRecommendations(token, chatId);
}

async function sendTelegramRecommendations(token, chatId) {
  const btn = document.getElementById('btnTelegramSend');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '⏳ Menyaring & Mengirim...';
  }

  try {
    showToast('🔍 Menyaring saham akumulasi aman (< 2.5%) & mengirim ke Telegram...');
    const res = await fetch('/api/telegram/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        bot_token: token || undefined,
        chat_id: chatId || undefined,
        max_picks: 3,
        max_pct_change: 2.5,
        min_score: 70,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Gagal mengirim rekomendasi ke Telegram');

    showToast(data.message, 'success');
  } catch (err) {
    showToast(err.message, 'error');
    if (err.message.includes('Token') || err.message.includes('Chat ID') || err.message.includes('belum disetel')) {
      openTelegramModal();
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `
        <svg class="w-4 h-4 text-sky-400" fill="currentColor" viewBox="0 0 24 24">
          <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm4.64 6.8c-.15 1.58-.8 5.42-1.13 7.19-.14.75-.42 1-.68 1.03-.58.05-1.02-.38-1.58-.75-.88-.58-1.38-.94-2.23-1.5-.99-.65-.35-1.01.22-1.59.15-.15 2.71-2.48 2.76-2.69a.2.2 0 00-.05-.18c-.06-.05-.14-.03-.21-.02-.09.02-1.49.95-4.22 2.79-.4.27-.76.41-1.08.4-.36-.01-1.04-.2-1.55-.37-.63-.2-1.12-.31-1.08-.66.02-.18.27-.36.75-.55 2.92-1.27 4.86-2.11 5.83-2.52 2.77-1.16 3.35-1.36 3.73-1.36.08 0 .27.02.39.12.1.08.13.19.14.27-.01.06.01.24 0 .38z"/>
        </svg>
        ✈️ Kirim ke Telegram`;
    }
  }
}

document.addEventListener('DOMContentLoaded', () => {
  loadTracker();
});
