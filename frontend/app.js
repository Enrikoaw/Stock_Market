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
    renderDetailChart(selectedStockDetail);
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
  });

  try {
    const res = await fetch(`/api/screener?${params.toString()}`);
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
  document.getElementById('kpiTotalEmiten').textContent = kpis.total_emiten;
  document.getElementById('kpiAvgScore').textContent = `Avg Score: ${kpis.avg_smart_money_score}`;
  document.getElementById('kpiMarkupCount').textContent = kpis.markup_triggers;
  document.getElementById('kpiAccumCount').textContent = kpis.accum_triggers;
  document.getElementById('kpiDistCount').textContent = kpis.distribution_warnings;

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
          <!-- Emiten -->
          <td class="py-3 pl-4 pr-2">
            <div class="font-mono font-extrabold text-sm text-white">${s.ticker}</div>
            <div class="text-[11px] text-slate-400 truncate max-w-[130px]">${s.sector}</div>
          </td>

          <!-- Harga & Change -->
          <td class="py-3 px-2 text-right font-mono">
            <div class="font-bold text-slate-100">${fmtPrice(s.close)}</div>
            <div class="text-[11px] font-semibold ${chgColor}">${fmtSignPct(s.pct_change)}</div>
          </td>

          <!-- Volume Spike Ratio -->
          <td class="py-3 px-2 text-center font-mono">
            <div class="${volColor}">${s.vol_ratio.toFixed(2)}x <span class="text-[10px] font-normal text-slate-400">MA20</span></div>
            <div class="text-[10px] text-slate-400">Close Range: ${s.closing_range_pct}%</div>
          </td>

          <!-- Smart Money Trigger Badge -->
          <td class="py-3 px-2 text-center">
            <span class="inline-block px-2.5 py-1 rounded-full text-[11px] font-semibold ${badgeCls}">
              ${s.trigger_label}
            </span>
          </td>

          <!-- Bandarmology Top 3 B/S -->
          <td class="py-3 px-2">
            <div class="flex items-center gap-1.5 font-mono">
              <span class="${bsrColor}">${s.top3_bsr.toFixed(2)}x</span>
              <span class="text-[10px] text-slate-400">(${s.bdr_pct >= 0 ? '+' : ''}${s.bdr_pct.toFixed(1)}% Vol)</span>
            </div>
            <div class="text-[10px] text-slate-400 mt-0.5">
              B: <span class="text-emerald-300 font-mono">${s.top_buyers}</span> | S: <span class="text-rose-300 font-mono">${s.top_sellers}</span>
            </div>
          </td>

          <!-- Ticket Size & Foreign Flow -->
          <td class="py-3 px-2 text-right font-mono">
            <div class="text-slate-200">${s.ticket_size.toFixed(0)} <span class="text-[10px] text-slate-400">Lot/Tx (${s.ticket_ratio.toFixed(1)}x)</span></div>
            <div class="text-[11px] ${foreignColor}">F: ${s.net_foreign_pct >= 0 ? '+' : ''}${s.net_foreign_pct.toFixed(1)}% (${s.net_foreign_b_idr >= 0 ? '+' : ''}${s.net_foreign_b_idr}B)</div>
          </td>

          <!-- Smart Money Score -->
          <td class="py-3 pl-2 pr-4 text-right">
            <div class="flex items-center justify-end gap-2">
              <div class="w-16 bg-slate-800 h-2 rounded-full overflow-hidden">
                <div class="h-full bg-gradient-to-r ${barGrad}" style="width: ${s.smart_money_score}%"></div>
              </div>
              <span class="font-mono font-extrabold text-sm w-7 text-right text-white">${s.smart_money_score}</span>
            </div>
          </td>
        </tr>
      `;
    })
    .join('');
}

async function selectStock(ticker) {
  selectedTicker = ticker;

  // Update row highlight
  document.querySelectorAll('.stock-row').forEach((el) => el.classList.remove('selected-row'));
  const activeRow = document.getElementById(`row-${ticker}`);
  if (activeRow) activeRow.classList.add('selected-row');

  try {
    const res = await fetch(`/api/stock/${encodeURIComponent(ticker)}`);
    if (!res.ok) throw new Error(`Gagal memuat detail ${ticker}`);
    selectedStockDetail = await res.json();
    renderInspectorPanel(selectedStockDetail);
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function renderInspectorPanel(d) {
  document.getElementById('inspTicker').textContent = d.ticker;
  const badgeEl = document.getElementById('inspTriggerBadge');
  badgeEl.textContent = d.trigger_label;
  badgeEl.className = `text-[11px] font-semibold px-2.5 py-0.5 rounded-full ${getTriggerBadgeClass(d.trigger_type)}`;

  document.getElementById('inspSector').textContent = `${d.sector} • Update: ${d.date}`;
  document.getElementById('inspPrice').textContent = fmtPrice(d.close);

  const chgEl = document.getElementById('inspPctChange');
  chgEl.textContent = `${fmtSignPct(d.pct_change)} (${ fmtNumber(d.volume_lot) } Lot)`;
  chgEl.className = `text-xs font-mono font-semibold ${d.pct_change >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;

  // 5-Pillar Scores
  document.getElementById('inspTotalScoreBadge').textContent = `Score: ${d.smart_money_score} / 100`;
  document.getElementById('p1Score').textContent = `${d.vsa_score}/25`;
  document.getElementById('p2Score').textContent = `${d.bandar_score}/30`;
  document.getElementById('p3Score').textContent = `${d.ticket_score}/15`;
  document.getElementById('p4Score').textContent = `${d.foreign_score}/15`;
  document.getElementById('p5Score').textContent = `${d.structure_score}/15`;

  // Auto Trading Plan
  const plan = d.trading_plan;
  const biasEl = document.getElementById('planActionBias');
  biasEl.textContent = plan.action_bias;
  if (d.trigger_type === 'DISTRIBUTION_WARNING') {
    biasEl.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 border border-rose-500/30';
  } else {
    biasEl.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30';
  }

  document.getElementById('planEntryZone').textContent = `${fmtPrice(plan.entry_low)} - ${fmtNumber(plan.entry_high)}`;
  document.getElementById('planBandarAvg').textContent = `${fmtPrice(plan.bandar_avg_buy)} (${fmtSignPct(plan.diff_bandar_avg_pct)})`;
  document.getElementById('planStopLoss').textContent = `${fmtPrice(plan.stop_loss)} (${plan.stop_loss_pct}%)`;
  document.getElementById('planTargets').textContent = `${fmtNumber(plan.target_1)} (+${plan.target_1_pct}%) / ${fmtNumber(plan.target_2)}`;
  document.getElementById('planRationale').textContent = `${plan.rationale} (Risk/Reward = ${plan.risk_reward})`;

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
  const btn = document.getElementById('btnSyncFast');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Memeriksa...';
  }
  try {
    showToast('⚡ Mengevaluasi harga live Watchlist & Running...');
    const res = await fetch('/api/sync-fast', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Gagal sync cepat');
    showToast(data.message || '⚡ Status Watchlist & Running berhasil diperbarui!');
    await Promise.all([loadScreenerData(false), loadTracker()]);
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
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
    const res = await fetch('/api/sync-live', { method: 'POST' });
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
        const hRes = await fetch('/api/health');
        const hData = await hRes.json();
        if (!hData.is_syncing || pollCount >= 20) {
          clearInterval(pollInterval);
          if (btn) {
            btn.disabled = false;
            btn.textContent = '🔄 Full Sync IDX';
          }
          await Promise.all([loadScreenerData(false), loadTracker()]);
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
document.addEventListener('DOMContentLoaded', () => {
  loadScreenerData(false);

  ['filterTrigger', 'filterVolRatio', 'filterMinScore', 'filterSortBy'].forEach((id) => {
    document.getElementById(id).addEventListener('change', () => loadScreenerData(true));
  });

  let searchTimeout = null;
  document.getElementById('filterSearch').addEventListener('input', () => {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(() => loadScreenerData(true), 200);
  });

  document.getElementById('btnOpenUploadModal').addEventListener('click', openUploadModal);
  document.getElementById('btnOpenGuideModal').addEventListener('click', openGuideModal);

  document.getElementById('excelFileInput').addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleExcelUpload(e.target.files);
      e.target.value = '';
    }
  });

  const dropZone = document.getElementById('dropZone');
  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('dropzone-active');
  });
  dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('dropzone-active');
  });
  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('dropzone-active');
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleExcelUpload(e.dataTransfer.files);
    }
  });

  document.getElementById('btnResetSample').addEventListener('click', async () => {
    const res = await fetch('/api/reset', { method: 'POST' });
    if (res.ok) {
      document.getElementById('filterTrigger').value = 'ALL';
      document.getElementById('filterVolRatio').value = '0';
      document.getElementById('filterMinScore').value = '0';
      document.getElementById('filterSearch').value = '';
      showToast('Dataset dikembalikan ke Data Pasar Real 844 Saham IDX.');
      await loadScreenerData(false);
    }
  });
});


// =====================================================================
// SIGNAL TRACKER — FORWARD TEST (Watchlist -> Running -> Win / Loss)
// =====================================================================
let trackerTab = 'ALL';
let trackerSortBy = 'pnl_desc'; // Default: Running Profit Terbanyak (Terbang Tinggi)
let currentTrackerSignals = [];
let trackerSearchTerm = '';

const TRACKER_STATUS_STYLE = {
  WATCHLIST: 'bg-blue-500/15 text-blue-300 border-blue-500/40',
  RUNNING: 'bg-amber-500/15 text-amber-300 border-amber-500/40',
  WIN: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  LOSS: 'bg-rose-500/15 text-rose-300 border-rose-500/40',
  EXPIRED: 'bg-slate-500/15 text-slate-300 border-slate-500/40',
  TIMEOUT: 'bg-purple-500/15 text-purple-300 border-purple-500/40',
};

const fmtPctOrDash = (v) => (v === null || v === undefined ? '-' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`);
const pctClass = (v) => (v === null || v === undefined ? 'text-slate-400' : v >= 0 ? 'text-emerald-400' : 'text-rose-400');

async function loadTracker() {
  try {
    const [statsRes, sigRes] = await Promise.all([
      fetch('/api/tracker/stats'),
      fetch(`/api/tracker/signals?status=${encodeURIComponent(trackerTab)}&sort_by=${encodeURIComponent(trackerSortBy)}`),
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
        ? 'hover:bg-slate-800/60 bg-emerald-950/20 border-l-2 border-emerald-400'
        : 'hover:bg-slate-800/40';

      return `
      <tr class="${rowHighlight}">
        <td class="py-2.5 pl-4 pr-2">
          <div class="font-mono font-extrabold text-white cursor-pointer hover:text-emerald-300 flex items-center gap-1.5" onclick="selectStock('${r.ticker}')">
            <span>${r.ticker}</span>
            ${isHighFlyer ? '<span class="text-[11px]" title="Terbang Tinggi">🚀</span>' : ''}
          </div>
          <div class="text-[10px] text-slate-500 truncate max-w-[140px]">${r.source === 'AUTO' ? '🤖 Auto' : '👤 Manual'}</div>
        </td>
        <td class="py-2.5 px-2">
          <span class="inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold ${getTriggerBadgeClass(r.trigger_type)}">${r.trigger_label || '-'}</span>
          <span class="font-mono text-slate-300 ml-1 font-bold">${r.score ?? '-'}</span>
        </td>
        <td class="py-2.5 px-2 font-mono text-slate-300">${r.signal_date}</td>
        <td class="py-2.5 px-2 text-right font-mono text-emerald-300">${fmtNumber(r.entry_low)} - ${fmtNumber(r.entry_high)}</td>
        <td class="py-2.5 px-2 text-right font-mono">
          <span class="text-rose-400">${fmtNumber(r.stop_loss)}</span> / <span class="text-amber-300">${fmtNumber(r.target)}</span>
        </td>
        <td class="py-2.5 px-2 text-center">
          <span class="inline-block px-2 py-0.5 rounded border text-[10px] font-bold ${statusCls}">${r.status}</span>
        </td>
        <td class="py-2.5 px-2 text-right font-mono text-slate-200">${entryCell}</td>
        <td class="py-2.5 px-2 text-right font-mono text-slate-200">${exitOrLast}</td>
        <td class="py-2.5 px-2 text-right font-mono font-bold">${pnlContent}</td>
        <td class="py-2.5 px-2 text-[11px] text-slate-400 max-w-[240px]">${r.note || ''}</td>
        <td class="py-2.5 pl-2 pr-4 text-right">
          <button onclick="deleteSignal(${r.id})" class="text-slate-500 hover:text-rose-400 text-sm" title="Hapus sinyal">&times;</button>
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

document.addEventListener('DOMContentLoaded', () => {
  loadTracker();
});
