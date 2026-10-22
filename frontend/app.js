/**
 * SmartFlow IDX - Frontend Controller (app.js)
 * Antarmuka Ramah Pemula & Mahir, Kalkulator Lot, Glosarium, Favorit Pribadi,
 * Live Market Sync, Candlestick Chart.js, dan Forward-Test Signal Tracker.
 */

// =====================================================================
// GLOBAL STATE
// =====================================================================
let currentStocks = [];
let currentPage = 1;
const PAGE_SIZE = 50;
let selectedTicker = null;
let selectedStockDetail = null;
let activeChartTab = 'price';
let chartInstance = null;
let isSyncingFast = false;

// State Baru: Mode Navigasi, Mode Mahir, & Favorit Pribadi (localStorage)
let activeMainTab = localStorage.getItem('smartflow_active_tab') || 'today';
let isExpertMode = localStorage.getItem('smartflow_expert_mode') === 'true';
let favoriteTickers = [];
try {
  favoriteTickers = JSON.parse(localStorage.getItem('smartflow_favorites') || '[]');
  if (!Array.isArray(favoriteTickers)) favoriteTickers = [];
} catch (e) {
  favoriteTickers = [];
}

// Formatters & XSS Sanitizer (T3)
const fmtNumber = (n) => new Intl.NumberFormat('id-ID').format(Math.round(n || 0));
const fmtPrice = (n) => `Rp ${fmtNumber(n)}`;
const fmtSignPct = (n) => `${n >= 0 ? '+' : ''}${Number(n || 0).toFixed(2)}%`;
const escHtml = (str) =>
  String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

// Parameter Baku Rencana Trading & Rasio Risk:Reward (K8 - Seragam di seluruh aplikasi)
const APP_TRADING_RULES = {
  DEFAULT_SL_PCT: 3.5,    // Batas Rugi Baku (-3.5%)
  DEFAULT_TP1_PCT: 7.0,   // Target Profit 1 Baku (+7.0%) -> Rasio Risk:Reward eksak 1 : 2.0
  DEFAULT_TP2_PCT: 12.0,  // Target Profit 2 Baku (+12.0%)
  DEFAULT_RR: 2.0,        // Rasio Baku 1 : 2.0
};



// =====================================================================
// THEME ENGINE (HANYA TEMA GELAP & TERANG)
// =====================================================================
function initTheme() {
  const saved = localStorage.getItem('smartflow_theme') || 'dark';
  const isLight = saved === 'light' || saved === 'paper';
  setAppTheme(isLight ? 'light' : 'dark', false);
}

function setAppTheme(mode, renderChart = true) {
  const html = document.documentElement;
  const isLight = mode === 'light';

  // Bersihkan kelas tema kustom masa lalu agar bersih
  const obsoleteThemes = ['theme-emerald', 'theme-gold', 'theme-midnight', 'theme-slate', 'theme-paper'];
  obsoleteThemes.forEach((t) => html.classList.remove(t));

  const icon = document.getElementById('themeIcon');
  const label = document.getElementById('themeLabel');
  const badge = document.getElementById('themeModeBadge');
  const btnDark = document.getElementById('btnThemeDark');
  const btnLight = document.getElementById('btnThemeLight');

  if (isLight) {
    html.classList.remove('dark');
    html.classList.add('light');
    if (icon) icon.textContent = '☀️';
    if (label) label.textContent = 'Terang';
    if (badge) {
      badge.textContent = 'Terang';
      badge.className = 'text-[10px] font-mono font-bold px-1.5 py-0.2 rounded bg-amber-500/20 text-amber-300 border border-amber-400/40';
    }
    if (btnLight) {
      btnLight.className = 'py-1.5 px-2 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition cursor-pointer active:scale-95 border bg-amber-500/20 text-amber-300 border-amber-400/40 shadow-sm';
    }
    if (btnDark) {
      btnDark.className = 'py-1.5 px-2 rounded-lg text-xs font-medium flex items-center justify-center gap-1.5 transition cursor-pointer active:scale-95 border bg-white/[0.04] text-slate-400 border-white/5 hover:text-white';
    }
    localStorage.setItem('smartflow_theme', 'light');
  } else {
    html.classList.remove('light');
    html.classList.add('dark');
    if (icon) icon.textContent = '🌙';
    if (label) label.textContent = 'Gelap';
    if (badge) {
      badge.textContent = 'Gelap';
      badge.className = 'text-[10px] font-mono font-bold px-1.5 py-0.2 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-400/30';
    }
    if (btnDark) {
      btnDark.className = 'py-1.5 px-2 rounded-lg text-xs font-bold flex items-center justify-center gap-1.5 transition cursor-pointer active:scale-95 border bg-emerald-500/20 text-emerald-300 border-emerald-400/40 shadow-sm';
    }
    if (btnLight) {
      btnLight.className = 'py-1.5 px-2 rounded-lg text-xs font-medium flex items-center justify-center gap-1.5 transition cursor-pointer active:scale-95 border bg-white/[0.04] text-slate-400 border-white/5 hover:text-white';
    }
    localStorage.setItem('smartflow_theme', 'dark');
  }

  if (renderChart && typeof renderInspectorChart === 'function' && selectedStockDetail) {
    renderInspectorChart(selectedStockDetail);
  }
  if (renderChart && typeof renderIhsgTodayChart === 'function' && lastIhsgChartData) {
    renderIhsgTodayChart(lastIhsgChartData);
  }
}

function toggleTheme() {
  const isLight = document.documentElement.classList.contains('light');
  setAppTheme(isLight ? 'dark' : 'light');
}

// Fungsi kompatibilitas jika dipanggil dari modul lain
function selectTheme(themeName, renderChart = true) {
  const isLight = themeName === 'paper' || themeName === 'light';
  setAppTheme(isLight ? 'light' : 'dark', renderChart);
}

function applyTheme(theme) {
  selectTheme(theme);
}

initTheme();

// =====================================================================
// 3 TOP NAVIGATION TABS (Hari Ini · Jelajah · Pantauan)
// =====================================================================
function switchMainTab(tabName, isInitialLoad = false) {
  activeMainTab = tabName;
  localStorage.setItem('smartflow_active_tab', tabName);

  const secToday = document.getElementById('sectionToday');
  const secExplore = document.getElementById('sectionExplore');
  const secWatchlist = document.getElementById('sectionWatchlist');

  const btnToday = document.getElementById('tabNavToday');
  const btnExplore = document.getElementById('tabNavExplore');
  const btnWatchlist = document.getElementById('tabNavWatchlist');

  if (secToday) secToday.classList.toggle('hidden', tabName !== 'today');
  if (secExplore) secExplore.classList.toggle('hidden', tabName !== 'explore');
  if (secWatchlist) secWatchlist.classList.toggle('hidden', tabName !== 'watchlist');

  if (btnToday) btnToday.classList.toggle('active', tabName === 'today');
  if (btnExplore) btnExplore.classList.toggle('active', tabName === 'explore');
  if (btnWatchlist) btnWatchlist.classList.toggle('active', tabName === 'watchlist');

  const mobToday = document.getElementById('mobileNavToday');
  const mobExplore = document.getElementById('mobileNavExplore');
  const mobWatchlist = document.getElementById('mobileNavWatchlist');

  if (mobToday) mobToday.classList.toggle('active', tabName === 'today');
  if (mobExplore) mobExplore.classList.toggle('active', tabName === 'explore');
  if (mobWatchlist) mobWatchlist.classList.toggle('active', tabName === 'watchlist');

  if (isInitialLoad) {
    if (tabName === 'watchlist') renderFavorites();
    return;
  }

  if (tabName === 'today') {
    renderTodayCandidates(currentTodayCandidates.length > 0 ? currentTodayCandidates : currentStocks);
    loadMarketNews(false);
    const now = Date.now();
    if (now - lastIhsgRefreshTs >= 60 * 1000) {
      loadIhsgTodayChart(currentIhsgPeriod, isIDXMarketOpenNow()).catch(() => {});
    }
  } else if (tabName === 'watchlist') {
    renderFavorites();
    loadTracker();
    loadPortfolio();
  } else if (tabName === 'explore') {
    if (selectedStockDetail) {
      renderInspectorChart(selectedStockDetail);
    }
  }
}

// =====================================================================
// SAKLAR MODE PEMULA VS MODE MAHIR
// =====================================================================
function applyExpertModeUI() {
  const modeIcon = document.getElementById('modeIcon');
  const modeLabel = document.getElementById('modeLabel');
  const kpiContainer = document.getElementById('kpiContainer');

  if (isExpertMode) {
    if (modeIcon) modeIcon.textContent = '⚡';
    if (modeLabel) modeLabel.textContent = 'Mode Mahir';
    if (kpiContainer) kpiContainer.classList.remove('hidden');
    document.querySelectorAll('.expert-only').forEach(el => el.classList.remove('hidden'));

    // 1. Kolom Tabel Screener (Mode Mahir: Istilah Teknis Asli)
    const colVol = document.getElementById('colHeaderVolume');
    if (colVol) colVol.textContent = 'Volume / Sinyal';
    const colScore = document.getElementById('colHeaderScore');
    if (colScore) colScore.textContent = 'Skor VSA';
    const colProf = document.getElementById('colHeaderProfile');
    if (colProf) colProf.textContent = 'Profil VSA & VWAP 5H';

    // 2. Rincian 5 Pilar Kuantitatif (Mode Mahir)
    const p1 = document.getElementById('p1Label');
    if (p1) p1.textContent = 'P1: Volume Spike & VSA';
    const p2 = document.getElementById('p2Label');
    if (p2) p2.textContent = 'P2: Tren & Struktur MA20/MA50';
    const p3 = document.getElementById('p3Label');
    if (p3) p3.textContent = 'P3: Kompresi Volatilitas (Squeeze)';
    const p4 = document.getElementById('p4Label');
    if (p4) p4.textContent = 'P4: Likuiditas & Turnover Riil';
    const p5 = document.getElementById('p5Label');
    if (p5) p5.textContent = 'P5: Posisi Harga vs 5-Day VWAP';

    // 3. Opsi Dropdown Pengurutan
    const optVwap = document.querySelector('#filterSortBy option[value="vwap"]');
    if (optVwap) optVwap.textContent = 'Urutkan: Jarak VWAP Terdekat';
  } else {
    if (modeIcon) modeIcon.textContent = '🌱';
    if (modeLabel) modeLabel.textContent = 'Mode Pemula';
    if (kpiContainer) kpiContainer.classList.add('hidden');
    document.querySelectorAll('.expert-only').forEach(el => el.classList.add('hidden'));

    // 1. Kolom Tabel Screener (Mode Pemula: Bahasa Sehari-hari Ramah)
    const colVol = document.getElementById('colHeaderVolume');
    if (colVol) colVol.textContent = 'Lonjakan Volume / Sinyal';
    const colScore = document.getElementById('colHeaderScore');
    if (colScore) colScore.textContent = 'Skor Aliran Dana (0-100)';
    const colProf = document.getElementById('colHeaderProfile');
    if (colProf) colProf.textContent = 'Rata-Rata Harga 5H & Transaksi';

    // 2. Rincian 5 Pilar Kuantitatif (Mode Pemula: Ramah & Jelas)
    const p1 = document.getElementById('p1Label');
    if (p1) p1.textContent = 'P1: Lonjakan Volume & Respon Harga';
    const p2 = document.getElementById('p2Label');
    if (p2) p2.textContent = 'P2: Tren Rata-Rata 20/50 Hari (MA)';
    const p3 = document.getElementById('p3Label');
    if (p3) p3.textContent = 'P3: Rentang Harga Menyempit (Squeeze)';
    const p4 = document.getElementById('p4Label');
    if (p4) p4.textContent = 'P4: Nilai Transaksi Harian (Turnover)';
    const p5 = document.getElementById('p5Label');
    if (p5) p5.textContent = 'P5: Posisi vs Harga Rata-Rata 5 Hari';

    // 3. Opsi Dropdown Pengurutan
    const optVwap = document.querySelector('#filterSortBy option[value="vwap"]');
    if (optVwap) optVwap.textContent = 'Urutkan: Dekat Harga Rata-Rata 5H';
  }

  // Update teks dinamis baris tabel jika sudah ter-render
  document.querySelectorAll('.lbl-vwap-text').forEach(el => {
    el.textContent = isExpertMode ? 'VWAP 5H' : 'Rata2 5H';
  });
  document.querySelectorAll('.lbl-val-text').forEach(el => {
    el.textContent = isExpertMode ? 'Turnover' : 'Transaksi';
  });
}

function toggleExpertMode() {
  isExpertMode = !isExpertMode;
  localStorage.setItem('smartflow_expert_mode', isExpertMode ? 'true' : 'false');
  applyExpertModeUI();
  showToast(
    isExpertMode
      ? 'Beralih ke Mode Mahir (seluruh kartu KPI & filter teknis aktif).'
      : 'Beralih ke Mode Pemula (antarmuka bersih & ramah risiko).',
    'success'
  );
}

// =====================================================================
// FAVORIT PRIBADI (★) - LOCALSTORAGE
// =====================================================================
function isFavorite(ticker) {
  if (!ticker) return false;
  return favoriteTickers.includes(ticker.trim().toUpperCase());
}

function toggleFavorite(ticker, e = null) {
  if (e) {
    e.stopPropagation();
  }
  if (!ticker) return;
  const clean = ticker.trim().toUpperCase();
  const idx = favoriteTickers.indexOf(clean);

  if (idx >= 0) {
    favoriteTickers.splice(idx, 1);
    showToast(`Dihapus dari Favorit: ${clean}`);
  } else {
    favoriteTickers.push(clean);
    showToast(`★ Disimpan ke Favorit: ${clean}`);
  }

  localStorage.setItem('smartflow_favorites', JSON.stringify(favoriteTickers));

  // Perbarui semua tombol bintang di tabel dan kartu
  document.querySelectorAll(`.star-btn-${clean}`).forEach(btn => {
    btn.innerHTML = isFavorite(clean) ? '★' : '☆';
    btn.className = `star-btn star-btn-${clean} text-base transition ${isFavorite(clean) ? 'text-amber-400 drop-shadow-[0_0_8px_rgba(251,191,36,0.6)]' : 'text-slate-500 hover:text-amber-300'}`;
  });

  if (activeMainTab === 'watchlist') {
    renderFavorites();
  }
  if (activeMainTab === 'today') {
    renderTodayCandidates(currentTodayCandidates.length > 0 ? currentTodayCandidates : currentStocks);
  }
}

function renderFavorites() {
  const container = document.getElementById('favoritesContainer');
  const countBadge = document.getElementById('favoritesCountBadge');
  if (countBadge) countBadge.textContent = `${favoriteTickers.length} Saham`;
  if (!container) return;

  if (favoriteTickers.length === 0) {
    container.innerHTML = `
      <div class="col-span-full py-8 text-center text-xs text-slate-500 dark:text-slate-400 bg-slate-50 border border-slate-200 dark:bg-slate-900/40 dark:border-white/[0.08] rounded-xl p-6 shadow-sm dark:shadow-none">
        <span class="text-2xl mb-2 block">⭐</span>
        <p class="font-semibold text-slate-800 dark:text-slate-200 text-sm">Belum ada saham favorit tersimpan.</p>
        <p class="text-[11px] text-slate-500 dark:text-slate-400 mt-1.5 leading-relaxed">
          Klik tanda bintang (★) pada kartu saham di tab <b class="text-slate-700 dark:text-slate-300">Hari Ini</b> atau tabel di tab <b class="text-slate-700 dark:text-slate-300">Jelajah</b> untuk menyimpannya di sini.
        </p>
      </div>
    `;
    return;
  }

  // Cari data saham di currentStocks
  const cardsHtml = favoriteTickers.map(ticker => {
    const s = currentStocks.find(x => x.ticker === ticker) || {
      ticker,
      close: 0,
      pct_change: 0,
      smart_money_score: '-',
      sector: 'Favorit Tersimpan',
      trigger_type: 'ALL',
      trigger_label: 'Pantauan'
    };

    const chgColor = s.pct_change >= 0 ? 'text-emerald-400' : 'text-rose-400';
    const safeTicker = escHtml(s.ticker);
    const safeSector = escHtml(s.sector);
    return `
      <div class="p-3.5 rounded-xl glass-subcard border border-white/[0.08] hover:border-amber-400/40 transition flex flex-col justify-between gap-3">
        <div class="flex items-start justify-between">
          <div class="flex items-center gap-2.5">
            ${getStockLogoImg(s.ticker, 'w-8 h-8')}
            <div>
              <div class="font-mono font-black text-sm text-white flex items-center gap-1.5">
                <span>${safeTicker}</span>
                <span class="text-[10px] font-sans font-bold px-1.5 py-0.2 rounded bg-white/[0.08] text-slate-300">Skor ${escHtml(s.smart_money_score)}</span>
              </div>
              <div class="text-[10px] text-slate-400 truncate max-w-[130px]">${safeSector}</div>
            </div>
          </div>
          <button onclick="toggleFavorite('${safeTicker}', event)" class="text-amber-400 hover:text-rose-400 text-lg transition leading-none" title="Hapus dari favorit">
            ★
          </button>
        </div>

        <div class="flex items-baseline justify-between border-t border-white/[0.06] pt-2">
          <div>
            <div class="font-mono font-bold text-sm text-white">${s.close ? fmtPrice(s.close) : '-'}</div>
            <div class="font-mono text-[11px] font-semibold ${chgColor}">${s.close ? fmtSignPct(s.pct_change) : ''}</div>
          </div>
          <div class="flex items-center gap-1.5">
            <button onclick="openLotCalculatorForTicker('${safeTicker}')" class="px-2 py-1 rounded-lg bg-blue-500/15 hover:bg-blue-500/25 text-blue-300 border border-blue-400/30 text-[10px] font-semibold transition" title="Kalkulator Lot">
              🧮 Lot
            </button>
            <button onclick="selectStockAndGoToInspector('${safeTicker}')" class="px-2.5 py-1 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-400/30 text-[10px] font-semibold transition" title="Buka Detail">
              Lihat Detail →
            </button>
          </div>
        </div>
      </div>
    `;
  }).join('');

  container.innerHTML = cardsHtml;
}

// =====================================================================
// EKSPOR & IMPOR DAFTAR PANTAUAN FAVORIT (TEMUAN K7)
// =====================================================================
function exportFavoritesData() {
  if (!favoriteTickers || favoriteTickers.length === 0) {
    showToast('Daftar pantauan favorit masih kosong.', 'info');
    return;
  }
  const exportPayload = {
    app: 'SmartFlow IDX',
    type: 'smartflow_favorites_backup',
    version: '1.0',
    exported_at: new Date().toISOString(),
    count: favoriteTickers.length,
    tickers: favoriteTickers,
  };
  const blob = new Blob([JSON.stringify(exportPayload, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  a.href = url;
  a.download = `smartflow_watchlist_${dStr}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast(`Cadangan ${favoriteTickers.length} saham favorit berhasil diunduh!`, 'success');
}

function importFavoritesData(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (evt) => {
    try {
      const content = evt.target.result;
      let imported = [];
      if (file.name.endsWith('.json')) {
        const parsed = JSON.parse(content);
        imported = Array.isArray(parsed) ? parsed : (parsed.tickers || []);
      } else {
        imported = content.split(/[\r\n,]+/).map(s => s.trim().toUpperCase()).filter(s => /^[A-Z0-9]{4,6}$/.test(s));
      }
      const validTickers = imported.map(t => String(t).trim().toUpperCase()).filter(t => /^[A-Z0-9]{4,6}$/.test(t));
      if (!validTickers.length) {
        throw new Error('Tidak ditemukan kode saham valid dalam file cadangan.');
      }
      const merged = Array.from(new Set([...favoriteTickers, ...validTickers]));
      favoriteTickers = merged;
      localStorage.setItem('smartflow_favorites', JSON.stringify(favoriteTickers));
      renderFavorites();
      showToast(`Berhasil memulihkan ${validTickers.length} saham ke daftar pantauan!`, 'success');
    } catch (err) {
      showToast(`Gagal mengimpor file: ${err.message}`, 'error');
    } finally {
      e.target.value = '';
    }
  };
  reader.readAsText(file);
}

// =====================================================================
// TAB 1: KANDIDAT PILIHAN HARI INI (BERANDA PEMULA)
// =====================================================================
function getScoreStrengthDots(score) {
  if (score >= 80) return { dots: '●●●●', label: 'Sangat Kuat', color: 'text-emerald-400' };
  if (score >= 70) return { dots: '●●●○', label: 'Kuat', color: 'text-teal-300' };
  if (score >= 60) return { dots: '●●○○', label: 'Cukup', color: 'text-blue-300' };
  return { dots: '●○○○', label: 'Netral', color: 'text-slate-400' };
}

function getHumanExplanation(s) {
  const volTxt = s.vol_ratio >= 1.5
    ? `Volume perdagangan hari ini melonjak ${s.vol_ratio.toFixed(1)}x rata-rata 20 hari, menandakan minat beli nyata.`
    : `Aktivitas volume stabil dan likuiditas sehat.`;

  const vwapDiff = s.diff_bandar_avg_pct || 0;
  let vwapTxt = '';
  if (vwapDiff <= 0) {
    vwapTxt = `Harga masih berada di bawah rata-rata modal bandar 5 hari (${fmtPrice(s.bandar_avg_buy)}), memberikan area diskon relatif aman.`;
  } else if (vwapDiff <= 3.0) {
    vwapTxt = `Harga berada dekat area rata-rata modal bandar 5 hari (${fmtPrice(s.bandar_avg_buy)}), risiko masuk masih terukur.`;
  } else {
    vwapTxt = `Harga sudah naik ${vwapDiff.toFixed(1)}% di atas modal rata-rata 5 hari bandar, disiplin pasang batas rugi.`;
  }

  return `${volTxt} ${vwapTxt}`;
}

// Broker Bursa Efek Indonesia (IDX) Sets & Formatting
const RETAIL_BROKERS = new Set(['YP', 'PD', 'XC', 'XL', 'KK', 'NI', 'SQ', 'BQ', 'AZ', 'MG']);
const INST_FOREIGN_BROKERS = new Set(['AK', 'BK', 'ZP', 'KZ', 'RX', 'YU', 'CC', 'CS', 'DX', 'LG', 'OD', 'BB', 'CP']);

function formatBrokerPills(brokerCodes, isBuyer = true) {
  if (!brokerCodes) {
    return `<span class="text-[10px] text-slate-400 font-sans italic">Belum ada data</span>`;
  }
  const rawList = Array.isArray(brokerCodes)
    ? brokerCodes
    : String(brokerCodes).split(',').map(s => s.trim()).filter(Boolean);

  // Saring HANYA kode broker bursa efek yang sah (2 huruf kapital: AK, BK, YP, PD, dll.)
  const realCodes = rawList
    .map(c => String(c).trim().toUpperCase())
    .filter(c => /^[A-Z]{2}$/.test(c));

  if (!realCodes.length) {
    return `<span class="text-[10px] text-amber-500/90 dark:text-amber-400/90 font-sans italic">Belum ditarik</span>`;
  }

  return realCodes.map(code => {
    if (isBuyer) {
      if (INST_FOREIGN_BROKERS.has(code)) {
        return `<span class="px-1.5 py-0.5 rounded bg-emerald-500/20 text-emerald-300 font-mono font-bold text-[10px] border border-emerald-500/40 inline-flex items-center" title="Broker Institusi / Smart Money: ${code}">${code}</span>`;
      } else if (RETAIL_BROKERS.has(code)) {
        return `<span class="px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 font-mono text-[10px] border border-amber-500/30 inline-flex items-center" title="Broker Ritel: ${code}">${code}</span>`;
      }
      return `<span class="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 font-mono font-bold text-[10px] border border-emerald-500/20" title="${code}">${code}</span>`;
    } else {
      if (RETAIL_BROKERS.has(code)) {
        return `<span class="px-1.5 py-0.5 rounded bg-rose-500/15 text-rose-300 font-mono font-bold text-[10px] border border-rose-500/30 inline-flex items-center" title="Broker Ritel Jual (Bagus): ${code}">${code}</span>`;
      } else if (INST_FOREIGN_BROKERS.has(code)) {
        return `<span class="px-1.5 py-0.5 rounded bg-rose-900/40 text-rose-400 font-mono text-[10px] border border-rose-500/30 inline-flex items-center" title="Institusi Keluar: ${code}">${code}</span>`;
      }
      return `<span class="px-1.5 py-0.5 rounded bg-rose-500/10 text-rose-400 font-mono text-[10px] border border-rose-500/20" title="${code}">${code}</span>`;
    }
  }).join(' ');
}

let currentTodayCandidates = [];

function renderTodayCandidates(stocks) {
  const container = document.getElementById('todayCandidatesGrid');
  if (!container) return;

  // Generate live alerts & trigger sound/notification
  try { generateAlertsFromMarketData(stocks); } catch (_) {}

  const regime = currentMarketRegime || {};
  let defensiveNoticeHtml = '';
  if (regime.status === 'DEFENSIVE_PULLBACK' || regime.color === 'rose' || regime.color === 'amber') {
    defensiveNoticeHtml = `
      <div class="col-span-full p-3.5 rounded-xl bg-slate-900/80 border border-amber-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 text-xs">
        <div>
          <div class="font-mono font-bold text-amber-400 text-xs uppercase tracking-wider">Mode Pasar Defensif • Sinyal Aktif di Watchlist</div>
          <p class="text-slate-300 text-[11px] mt-0.5 leading-relaxed">
            IHSG sedang tertekan. Seluruh saham pilihan di bawah ini otomatis dicatat di Watchlist dengan disiplin antre entry di Support Terdekat (menunggu pullback).
          </p>
        </div>
        <span class="px-2.5 py-1 rounded-md bg-amber-500/15 text-amber-300 border border-amber-400/30 font-mono text-[10px] font-semibold whitespace-nowrap self-start sm:self-auto">
          Antre Support
        </span>
      </div>
    `;
  }

  if (!stocks || stocks.length === 0) {
    container.innerHTML = `
      <div class="col-span-full p-8 rounded-2xl glass-panel text-center text-slate-300 text-xs">
        Belum ada data saham yang dimuat. Silakan tunggu sinkronisasi atau unggah data.
      </div>
    `;
    return;
  }

  // Saring ketat kandidat: HANYA saham yang diakum Smart Money & BELUM JAUH DARI MODAL BANDAR
  const pool = Array.isArray(stocks) ? stocks : [];
  let validPool = pool.filter(s => {
    const pct = Number(s.pct_change || 0);
    const diffBdr = s.diff_bandar_avg_pct != null ? Number(s.diff_bandar_avg_pct) : 0;
    const bdr = s.bdr_pct != null ? Number(s.bdr_pct) : 0;

    // 1. Tolak mutlak saham pucuk yang sudah terbang tinggi (> +4.5%)
    if (pct > 4.5) return false;

    // 2. Tolak saham jebakan ritel / distribusi
    if (s.retail_trap || s.trigger_type === 'DISTRIBUTION_WARNING') return false;

    // 3. Syarat Utama: Belum jauh dari Average Modal Bandar (-4.5% s/d +3.5%)
    if (s.diff_bandar_avg_pct != null && (diffBdr < -4.5 || diffBdr > 3.5)) return false;

    // 4. Diakumulasi Smart Money (BDR positif >= 5% atau pembeli dominan dengan skor tinggi)
    const isAccum = (bdr >= 5.0) || (s.top3_bsr >= 1.15 && (s.smart_money_score || 0) >= 60);
    return isAccum;
  });

  // Jika hasil filter terlalu sedikit (< 4), ambil saham terdekat dari modal bandar yang aman
  if (validPool.length < 4) {
    validPool = pool.filter(s => {
      const pct = Number(s.pct_change || 0);
      const diffBdr = s.diff_bandar_avg_pct != null ? Number(s.diff_bandar_avg_pct) : 0;
      if (pct > 4.5) return false;
      if (s.retail_trap || s.trigger_type === 'DISTRIBUTION_WARNING') return false;
      return (s.diff_bandar_avg_pct == null || (diffBdr >= -5.0 && diffBdr <= 4.0));
    });
  }

  // Urutkan: 1. Paling dekat dengan Modal Bandar -> 2. BDR Akumulasi Tertinggi -> 3. Skor Smart Money
  validPool.sort((a, b) => {
    const diffA = Math.abs(a.diff_bandar_avg_pct != null ? a.diff_bandar_avg_pct : 0);
    const diffB = Math.abs(b.diff_bandar_avg_pct != null ? b.diff_bandar_avg_pct : 0);
    const bdrA = a.bdr_pct != null ? a.bdr_pct : 0;
    const bdrB = b.bdr_pct != null ? b.bdr_pct : 0;
    return (diffA - diffB) || (bdrB - bdrA) || ((b.smart_money_score || 0) - (a.smart_money_score || 0));
  });

  // Diversifikasi Sektor: Maksimal 1 saham per sektor agar portofolio tersebar sehat
  const chosenCandidates = [];
  const seenSectors = {};
  for (const s of validPool) {
    const sec = s.sector_category || s.sector || 'General';
    if (!seenSectors[sec]) {
      seenSectors[sec] = true;
      chosenCandidates.push(s);
    }
    if (chosenCandidates.length >= 8) break;
  }

  // Jika masih di bawah 5, tambahkan tanpa limit sektor
  if (chosenCandidates.length < 5) {
    for (const s of validPool) {
      if (!chosenCandidates.some(c => c.ticker === s.ticker)) {
        chosenCandidates.push(s);
      }
      if (chosenCandidates.length >= 8) break;
    }
  }

  const candidates = chosenCandidates.length > 0 ? chosenCandidates : pool.slice(0, 5);

  const mobileRows = candidates.map((s, idx) => {
    const safeTicker = escHtml(s.ticker);
    const safeSecCat = escHtml(s.sector_category || s.sector || 'General');
    const chgColor = s.pct_change >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-rose-500 dark:text-rose-400';
    const reasons = getWhyCandidateReason(s);
    const reasonsMobileHtml = reasons.map(r => `
      <span class="inline-block px-1.5 py-0.2 rounded text-[9px] font-mono font-medium border ${r.color}">
        ${escHtml(r.text)}
      </span>
    `).join('');

    return `
      <div class="py-2 px-1 hover:bg-slate-50 dark:hover:bg-white/[0.04] transition cursor-pointer flex items-center justify-between gap-2" onclick="selectStockAndGoToInspector('${safeTicker}')">
        <!-- Kiri: # + Logo + Ticker + Sektor + Katalis -->
        <div class="flex items-center gap-2 min-w-0">
          <span class="font-mono text-[11px] text-slate-400 w-4 text-center shrink-0">${idx + 1}</span>
          ${getStockLogoImg(s.ticker, 'w-6 h-6 rounded shrink-0')}
          <div class="min-w-0">
            <div class="flex items-center gap-1.5 leading-tight">
              <span class="font-mono font-black text-xs text-slate-900 dark:text-white tracking-wide">${safeTicker}</span>
              <span class="text-[10px] text-slate-500 dark:text-slate-400 truncate max-w-[110px]">${safeSecCat}</span>
            </div>
            <div class="flex items-center gap-1 mt-0.5 flex-wrap">
              ${reasonsMobileHtml}
            </div>
          </div>
        </div>

        <!-- Kanan: Harga + % Chg + Skor SM + Plan -->
        <div class="text-right shrink-0 flex items-center gap-2.5">
          <div class="leading-tight">
            <div class="font-mono font-bold text-xs text-slate-900 dark:text-white">${fmtPrice(s.close)}</div>
            <div class="font-mono text-[10px] font-bold ${chgColor}">${(s.pct_change >= 0 ? '+' : '') + Number(s.pct_change || 0).toFixed(2)}%</div>
          </div>
          <div class="flex flex-col items-end gap-0.5">
            <span class="font-mono font-bold text-[10px] px-1.5 py-0.2 rounded bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border border-slate-200 dark:border-slate-700/60">${s.smart_money_score}</span>
            <span class="text-[9px] font-bold text-emerald-600 dark:text-emerald-400">Plan &rarr;</span>
          </div>
        </div>
      </div>
    `;
  }).join('');

  const desktopRows = candidates.map((s, idx) => {
    const safeTicker = escHtml(s.ticker);
    const safeSecCat = escHtml(s.sector_category || s.sector || 'General');
    const chgColor = s.pct_change >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-rose-500 dark:text-rose-400';

    const reasons = getWhyCandidateReason(s);
    const reasonsHtml = reasons.map((r) => `
      <span class="inline-block px-1.5 py-0.5 rounded text-[10px] font-mono font-medium border ${r.color}">
        ${escHtml(r.text)}
      </span>
    `).join('');

    return `
      <tr class="hover:bg-slate-50 dark:hover:bg-white/[0.04] transition-colors cursor-pointer group" onclick="selectStockAndGoToInspector('${safeTicker}')">
        <!-- Index -->
        <td class="py-1.5 pl-3 pr-2 text-center font-mono text-[11px] text-slate-400 dark:text-slate-500 w-8 whitespace-nowrap">${idx + 1}</td>

        <!-- Saham -->
        <td class="py-1.5 px-2.5 whitespace-nowrap">
          <div class="flex items-center gap-2">
            ${getStockLogoImg(s.ticker, 'w-5 h-5 rounded shrink-0')}
            <span class="font-mono font-bold text-xs text-slate-900 dark:text-white group-hover:text-emerald-600 dark:group-hover:text-emerald-400 transition tracking-wide">${safeTicker}</span>
            <span class="text-[10px] text-slate-500 dark:text-slate-400 font-sans">${safeSecCat}</span>
          </div>
        </td>

        <!-- Harga -->
        <td class="py-1.5 px-2.5 text-right font-mono font-semibold text-xs text-slate-900 dark:text-slate-100 whitespace-nowrap">
          ${fmtPrice(s.close)}
        </td>

        <!-- Chg -->
        <td class="py-1.5 px-2.5 text-right font-mono font-bold text-[11px] ${chgColor} whitespace-nowrap">
          ${(s.pct_change >= 0 ? '+' : '') + Number(s.pct_change || 0).toFixed(2)}%
        </td>

        <!-- Skor SM -->
        <td class="py-1.5 px-2.5 text-center whitespace-nowrap">
          <span class="font-mono font-bold text-xs ${s.smart_money_score >= 75 ? 'text-emerald-600 dark:text-emerald-400' : 'text-slate-700 dark:text-slate-300'}">
            ${s.smart_money_score}
          </span>
        </td>

        <!-- Katalis & Alasan Watchlist -->
        <td class="py-1.5 px-3 whitespace-nowrap">
          <div class="flex items-center gap-1.5">
            ${reasonsHtml}
          </div>
        </td>

        <!-- Aksi -->
        <td class="py-1.5 pr-3 pl-2 text-right whitespace-nowrap">
          <button
            onclick="event.stopPropagation(); selectStockAndGoToInspector('${safeTicker}')"
            class="px-2.5 py-0.5 rounded text-[10px] font-bold transition text-emerald-700 bg-emerald-100 hover:bg-emerald-200 dark:text-emerald-300 dark:bg-emerald-500/15 dark:hover:bg-emerald-500/25 border border-emerald-300 dark:border-emerald-500/30"
            title="Buka Trading Plan ${safeTicker}"
          >
            Plan
          </button>
        </td>
      </tr>
    `;
  }).join('');

  container.innerHTML = `
    ${defensiveNoticeHtml}
    <div class="glass-panel rounded-2xl p-2.5 sm:p-4 border border-slate-200 dark:border-white/[0.08] shadow-sm space-y-2">
      <div class="flex items-center justify-between flex-wrap gap-2 pb-2 border-b border-slate-200 dark:border-white/[0.06]">
        <div class="flex items-center gap-2">
          <span class="text-xs font-bold text-slate-800 dark:text-slate-200">Kandidat Saham Pilihan Hari Ini</span>
          <span class="px-1.5 py-0.2 rounded font-mono text-[10px] font-bold bg-slate-100 text-slate-600 border border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700">${candidates.length} Emiten</span>
        </div>
        <div class="text-[11px] text-slate-500 dark:text-slate-400">
          Klik emiten untuk membuka Trading Plan
        </div>
      </div>

      <!-- Tampilan Mobile: List Ramping, Padat, Rapi, Pas di Layar -->
      <div class="sm:hidden divide-y divide-slate-100 dark:divide-white/[0.06]">
        ${mobileRows}
      </div>

      <!-- Tampilan Desktop: Tabel Padat & Lengkap -->
      <div class="hidden sm:block overflow-x-auto -mx-1 sm:mx-0">
        <table class="w-full text-left border-collapse text-xs">
          <thead>
            <tr class="bg-slate-100 dark:bg-slate-900/90 border-y border-slate-200 dark:border-white/[0.08] text-slate-600 dark:text-slate-400 font-semibold select-none text-[11px]">
              <th class="py-2 pl-3 pr-2 w-8 text-center text-slate-400">#</th>
              <th class="py-2 px-2.5 whitespace-nowrap">Saham</th>
              <th class="py-2 px-2.5 text-right whitespace-nowrap">Harga</th>
              <th class="py-2 px-2.5 text-right whitespace-nowrap">Chg</th>
              <th class="py-2 px-2.5 text-center whitespace-nowrap">Skor SM</th>
              <th class="py-2 px-3 whitespace-nowrap">Katalis &amp; Alasan Watchlist</th>
              <th class="py-2 pr-3 pl-2 text-right w-20 whitespace-nowrap">Aksi</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-slate-100 dark:divide-white/[0.04]">
            ${desktopRows}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function getWhyCandidateReason(s) {
  const reasons = [];

  // 1. Sentimen Berita & Katalis Positif
  const cat = s.news_catalyst;
  if (cat && (cat.sentiment === 'POSITIVE' || cat.verdict === 'VALID_CATALYST' || cat.code === 'POSITIVE_CONFIRMED')) {
    reasons.push({
      text: 'Sentimen Berita Positif',
      color: 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-300 dark:bg-emerald-950/40 dark:border-emerald-800/40'
    });
  }

  // 2. Posisi Modal Bandar (Dijaga Bandar di Dekat Modal / Harga Diskon)
  const diffBdr = s.diff_bandar_avg_pct != null ? Number(s.diff_bandar_avg_pct) : null;
  if (diffBdr !== null && Math.abs(diffBdr) <= 2.5) {
    const diffText = diffBdr >= 0 ? `+${diffBdr.toFixed(1)}%` : `${diffBdr.toFixed(1)}%`;
    reasons.push({
      text: `Dijaga Bandar (${diffText})`,
      color: 'text-sky-700 bg-sky-50 border-sky-200 dark:text-sky-300 dark:bg-sky-950/40 dark:border-sky-800/40'
    });
  } else if (diffBdr !== null && diffBdr < -2.5) {
    reasons.push({
      text: `Diskon Support (${Math.abs(diffBdr).toFixed(1)}%)`,
      color: 'text-teal-700 bg-teal-50 border-teal-200 dark:text-teal-300 dark:bg-teal-950/40 dark:border-teal-800/40'
    });
  }

  // 3. Volume & Lonjakan Transaksi
  const vr = s.vol_ratio != null ? Number(s.vol_ratio) : null;
  if (vr !== null && vr >= 1.4) {
    reasons.push({
      text: `Vol Spike ${vr.toFixed(1)}x`,
      color: 'text-amber-700 bg-amber-50 border-amber-200 dark:text-amber-300 dark:bg-amber-950/40 dark:border-amber-800/40'
    });
  }

  // 4. Akumulasi / Dominasi Buyer Top 3 Broker
  const bsr = s.top3_bsr != null ? Number(s.top3_bsr) : null;
  const bdr = s.bdr_pct != null ? Number(s.bdr_pct) : null;
  const trig = String(s.trigger_type || '').toUpperCase();
  const trigLabel = String(s.trigger_label || '');

  if (trig.includes('SILENT') || trigLabel.toLowerCase().includes('silent')) {
    reasons.push({
      text: 'Silent Accumulation',
      color: 'text-purple-700 bg-purple-50 border-purple-200 dark:text-purple-300 dark:bg-purple-950/40 dark:border-purple-800/40'
    });
  } else if (bsr !== null && bsr >= 1.25) {
    reasons.push({
      text: `Buyer Dominan (${bsr.toFixed(1)}x)`,
      color: 'text-indigo-700 bg-indigo-50 border-indigo-200 dark:text-indigo-300 dark:bg-indigo-950/40 dark:border-indigo-800/40'
    });
  } else if (bdr !== null && bdr >= 8.0) {
    reasons.push({
      text: `Akumulasi Bandar (+${bdr.toFixed(1)}%)`,
      color: 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-300 dark:bg-emerald-950/40 dark:border-emerald-800/40'
    });
  }

  // Broker Buyer Teratas
  const topB = s.top_buyers_list && s.top_buyers_list.length ? s.top_buyers_list.slice(0, 2).join(', ') : (s.top_buyers ? s.top_buyers.split(',').slice(0, 2).map(x => x.trim()).join(', ') : '');
  if (topB && reasons.length < 2) {
    reasons.push({
      text: `Buyer: ${topB}`,
      color: 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-300 dark:bg-emerald-950/40 dark:border-emerald-800/40'
    });
  }

  // 5. Setup Teknikal: Koreksi Sehat / Breakout
  const chg = Number(s.pct_change || 0);
  if (chg <= 0.5 && chg >= -3.5 && reasons.length < 2) {
    reasons.push({
      text: 'Koreksi Sehat (Swing)',
      color: 'text-blue-700 bg-blue-50 border-blue-200 dark:text-blue-300 dark:bg-blue-950/40 dark:border-blue-800/40'
    });
  } else if ((trig.includes('BREAKOUT') || trigLabel.toLowerCase().includes('breakout')) && reasons.length < 2) {
    reasons.push({
      text: 'Breakout Resistance',
      color: 'text-emerald-700 bg-emerald-50 border-emerald-200 dark:text-emerald-300 dark:bg-emerald-950/40 dark:border-emerald-800/40'
    });
  }

  // Fallback
  if (reasons.length === 0) {
    reasons.push({
      text: s.trigger_label || `Akumulasi (Skor ${s.smart_money_score || 70})`,
      color: 'text-slate-700 bg-slate-100 border-slate-200 dark:text-slate-300 dark:bg-slate-800/80 dark:border-slate-700/60'
    });
  }

  return reasons.slice(0, 2);
}

function selectStockAndGoToInspector(ticker) {
  switchMainTab('explore');
  selectStock(ticker, true, true);
}

// =====================================================================
// MODUL BERITA & SENTIMEN PASAR SAHAM (INTEGRASI SMART MONEY)
// =====================================================================
let cachedNewsItems = [];
let activeNewsCategory = 'ALL';
let isNewsLoading = false;
let isNewsExpanded = false;
const NEWS_COLLAPSED_LIMIT = 10;


// Fetch dengan batas waktu timeout 9 detik (Temuan K6 - penanganan gagal terukur)
async function fetchWithTimeout(url, opts = {}, ms = 9000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal });
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error(`Waktu tunggu server melebihi ${Math.round(ms / 1000)} detik (Timeout).`);
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

// =====================================================================
// ERROR & SKELETON RENDERERS DENGAN TOMBOL COBA LAGI (TEMUAN K6)
// =====================================================================
function renderCandidatesError(errorMsg) {
  const container = document.getElementById('todayCandidatesGrid');
  if (!container) return;
  container.innerHTML = `
    <div class="col-span-full p-6 rounded-2xl glass-panel border border-rose-500/30 text-center space-y-3 shadow-lg">
      <div class="text-rose-400 font-bold text-xs sm:text-sm flex items-center justify-center gap-1.5">
        <span>⚠️</span>
        <span>Gagal Mengambil Data Pasar</span>
      </div>
      <p class="text-[11px] text-slate-400 max-w-md mx-auto leading-relaxed">${escHtml(errorMsg || 'Koneksi ke server backend tertunda atau waktu tunggu habis.')}</p>
      <button onclick="loadScreenerData(true)" class="px-4 py-2 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-400/30 text-xs font-bold transition active:scale-95 cursor-pointer shadow-sm">
        🔄 Muat Ulang / Coba Lagi
      </button>
    </div>
  `;
}

function renderTableError(errorMsg) {
  const tbody = document.getElementById('screenerTableBody');
  const mobileList = document.getElementById('screenerMobileList');
  if (tbody) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="py-12 text-center space-y-3">
          <div class="text-rose-400 font-bold text-xs sm:text-sm">Gagal Memuat Daftar Saham Bursa</div>
          <p class="text-[11px] text-slate-400 max-w-sm mx-auto leading-relaxed">${escHtml(errorMsg || 'Waktu tunggu server melebihi batas. Periksa koneksi backend Anda.')}</p>
          <button onclick="loadScreenerData(true)" class="mt-2 px-4 py-1.5 rounded-xl bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 border border-emerald-400/30 text-xs font-bold transition active:scale-95 cursor-pointer shadow-sm">
            Muat Ulang / Coba Lagi
          </button>
        </td>
      </tr>
    `;
  }
  if (mobileList) {
    mobileList.innerHTML = `
      <div class="p-6 rounded-xl bg-slate-900/50 border border-rose-500/20 text-center space-y-2">
        <div class="text-xs text-rose-400 font-bold">Gagal Memuat Daftar Saham Bursa</div>
        <p class="text-[10px] text-slate-400">${escHtml(errorMsg || 'Waktu tunggu server melebihi batas. Periksa koneksi backend Anda.')}</p>
        <button onclick="loadScreenerData(true)" class="mt-2 px-3.5 py-1.5 rounded-lg bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-300 text-xs font-semibold transition cursor-pointer">
          Muat Ulang / Coba Lagi
        </button>
      </div>
    `;
  }
}

function renderNewsError(errorMsg) {
  const container = document.getElementById('marketNewsList');
  if (!container) return;
  container.innerHTML = `
    <div class="col-span-full p-6 rounded-xl glass-subcard border border-rose-500/20 text-center space-y-2">
      <div class="text-xs text-rose-300 font-semibold">⚠️ Gagal Memuat Arus Berita Bursa</div>
      <p class="text-[10px] text-slate-400">${escHtml(errorMsg || 'Koneksi ke feed berita pasar tertunda.')}</p>
      <button onclick="loadMarketNews(true)" class="px-3.5 py-1 rounded-lg bg-white/10 hover:bg-white/20 text-slate-200 text-xs font-semibold transition cursor-pointer">
        🔄 Coba Lagi
      </button>
    </div>
  `;
}

function renderTrackerError(errorMsg) {
  const tbody = document.getElementById('trackerTableBody');
  const mobileList = document.getElementById('trackerMobileList');
  const content = `
    <div class="py-10 text-center space-y-2.5">
      <div class="text-rose-400 font-bold text-xs">Gagal Memuat Data Pantauan Sinyal</div>
      <p class="text-[10px] text-slate-400">${escHtml(errorMsg || 'Koneksi database tracker terputus.')}</p>
      <button onclick="loadTracker()" class="px-3 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 text-xs font-semibold transition cursor-pointer">
        Muat Ulang
      </button>
    </div>
  `;
  if (tbody) {
    tbody.innerHTML = `<tr><td colspan="10">${content}</td></tr>`;
  }
  if (mobileList) {
    mobileList.innerHTML = content;
  }
}

function renderPortfolioError(errorMsg) {
  const tbody = document.getElementById('portfolioTableBody');
  if (!tbody) return;
  tbody.innerHTML = `
    <tr>
      <td colspan="10" class="py-10 text-center space-y-2.5">
        <div class="text-rose-400 font-bold text-xs">⚠️ Gagal Memuat Catatan Jurnal Portofolio</div>
        <p class="text-[10px] text-slate-400">${escHtml(errorMsg || 'Koneksi database portofolio terputus.')}</p>
        <button onclick="loadPortfolio()" class="px-3 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 text-xs font-semibold transition cursor-pointer">
          🔄 Muat Ulang
        </button>
      </td>
    </tr>
  `;
}

async function loadMarketNews(forceRefresh = false) {
  if (isNewsLoading) return;
  const listEl = document.getElementById('marketNewsList');
  const refreshLabel = document.getElementById('refreshNewsLabel');
  const refreshBtn = document.getElementById('btnRefreshNews');

  isNewsLoading = true;
  if (refreshLabel) refreshLabel.textContent = 'Memuat...';
  if (refreshBtn) refreshBtn.disabled = true;

  try {
    const res = await fetchWithTimeout(`/api/news?category=${encodeURIComponent(activeNewsCategory)}&refresh=${forceRefresh ? 'true' : 'false'}&limit=25`, {}, forceRefresh ? 25000 : 10000);
    if (!res.ok) throw new Error('Gagal memuat berita pasar');
    const data = await res.json();
    cachedNewsItems = (data.items || []).sort((a, b) => (b.published_ts || 0) - (a.published_ts || 0));
    renderMarketNewsFeed(cachedNewsItems);
    triggerPositiveNewsBarNotification(cachedNewsItems);
  } catch (err) {
    if (listEl && (!cachedNewsItems || cachedNewsItems.length === 0)) {
      renderNewsError(err.message);
    }
  } finally {
    isNewsLoading = false;
    if (refreshLabel) refreshLabel.textContent = 'Perbarui';
    if (refreshBtn) refreshBtn.disabled = false;
  }
}

function setNewsCategoryFilter(cat) {
  activeNewsCategory = cat;
  isNewsExpanded = false;
  const tabs = ['ALL', 'PICKS', 'POSITIVE', 'NEGATIVE'];
  tabs.forEach((t) => {
    const btn = document.getElementById(`newsTab-${t}`);
    if (!btn) return;
    if (t === cat) {
      btn.className = 'news-tab-btn px-2.5 py-1 rounded-lg bg-emerald-600 text-white font-semibold transition';
    } else {
      btn.className = 'news-tab-btn px-2.5 py-1 rounded-lg text-slate-300 hover:text-white transition';
    }
  });
  loadMarketNews(false);
}

function renderMarketNewsFeed(items) {
  const listEl = document.getElementById('marketNewsList');
  const expandContainer = document.getElementById('newsExpandContainer');
  const expandBtnText = document.getElementById('newsExpandText');
  const expandBtnIcon = document.getElementById('newsExpandIcon');
  if (!listEl) return;

  if (!items || items.length === 0) {
    listEl.innerHTML = `
      <div class="p-6 rounded-xl glass-subcard text-center text-slate-400 text-xs col-span-full">
        Tidak ada berita pada kategori ini saat ini.
      </div>
    `;
    if (expandContainer) expandContainer.classList.add('hidden');
    return;
  }

  // Jaminan mutlak data terurut dari yang paling baru ke yang paling lama
  const sortedItems = [...items].sort((a, b) => (b.published_ts || 0) - (a.published_ts || 0));
  cachedNewsItems = sortedItems;

  const totalCount = sortedItems.length;
  const shouldLimit = totalCount > NEWS_COLLAPSED_LIMIT;
  const displayedItems = (!isNewsExpanded && shouldLimit)
    ? sortedItems.slice(0, NEWS_COLLAPSED_LIMIT)
    : sortedItems;

  listEl.innerHTML = displayedItems.map((n) => {
    const origIdx = sortedItems.indexOf(n);
    const isPos = n.sentiment === 'POSITIVE';
    const isNeg = n.sentiment === 'NEGATIVE';
    const sentColor = isPos
      ? 'border-emerald-500/30 text-emerald-300 bg-emerald-500/15'
      : isNeg
      ? 'border-rose-500/30 text-rose-300 bg-rose-500/15'
      : 'border-slate-500/30 text-slate-300 bg-slate-500/15';

    const safeTicker = escHtml(n.ticker || 'IHSG');
    const safeTitle = escHtml(n.title || '');
    const safeSummary = escHtml(n.summary || '');
    const safeSource = escHtml(n.source || 'IDX');
    const safeRelTime = escHtml(n.relative_time || '');
    const safePubAt = escHtml(n.published_at || '');
    const safeSentLabel = escHtml(n.sentiment_label || 'Informasi');

    return `
      <div
        onclick="inspectNewsCorrelation(${origIdx >= 0 ? origIdx : 0})"
        class="p-4 rounded-xl bg-slate-900/60 hover:bg-slate-900/90 border border-white/[0.06] hover:border-emerald-400/35 transition cursor-pointer flex flex-col justify-between gap-3 group"
      >
        <div class="space-y-2">
          <div class="flex items-center justify-between text-xs">
            <div class="flex items-center gap-2">
              <span class="font-mono font-bold text-xs text-white group-hover:text-emerald-400 transition">
                #${safeTicker}
              </span>
              <span class="text-[10px] font-semibold px-2 py-0.5 rounded border ${sentColor}">
                ${safeSentLabel}
              </span>
            </div>
            <span class="text-[11px] text-emerald-400/90 font-mono font-semibold" title="${safePubAt}">${safeRelTime}</span>
          </div>

          <h3 class="text-xs font-bold text-slate-100 group-hover:text-white leading-snug line-clamp-2">
            ${safeTitle}
          </h3>

          ${safeSummary ? `<p class="text-[11px] text-slate-400 leading-relaxed line-clamp-2">${safeSummary}</p>` : ''}
        </div>

        <div class="flex items-center justify-between text-[11px] pt-2 border-t border-white/[0.05]">
          <span class="text-slate-400 font-mono text-[10px]">${safeSource} · ${safePubAt}</span>
          <div class="flex items-center gap-3">
            ${n.link ? `<a href="${escHtml(n.link)}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()" class="text-slate-400 hover:text-white underline text-[10px]">Buka Sumber</a>` : ''}
            <span class="text-emerald-400 font-semibold text-[10px] group-hover:translate-x-0.5 transition flex items-center gap-0.5">
              <span>Korelasi</span>
              <span>&rarr;</span>
            </span>
          </div>
        </div>
      </div>
    `;
  }).join('');

  if (expandContainer) {
    if (shouldLimit) {
      expandContainer.classList.remove('hidden');
      if (!isNewsExpanded) {
        const remaining = totalCount - NEWS_COLLAPSED_LIMIT;
        if (expandBtnText) expandBtnText.textContent = `Lihat Selengkapnya (${remaining} Berita Lainnya)`;
        if (expandBtnIcon) expandBtnIcon.innerHTML = '&darr;';
      } else {
        if (expandBtnText) expandBtnText.textContent = 'Tampilkan Lebih Sedikit (10 Berita Teratas)';
        if (expandBtnIcon) expandBtnIcon.innerHTML = '&uarr;';
      }
    } else {
      expandContainer.classList.add('hidden');
    }
  }
}

function toggleNewsExpand() {
  isNewsExpanded = !isNewsExpanded;
  renderMarketNewsFeed(cachedNewsItems);

  if (!isNewsExpanded) {
    const target = document.getElementById('sectionMarketNews');
    if (target) {
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }
}

function inspectNewsCorrelation(idx) {
  const item = cachedNewsItems[idx];
  if (!item) return;

  const box = document.getElementById('newsCorrelationBox');
  const badge = document.getElementById('corrTickerBadge');
  const techEl = document.getElementById('corrTechText');
  const newsEl = document.getElementById('corrNewsTitle');
  const actionEl = document.getElementById('corrActionText');
  const btnRow = document.getElementById('corrActionBtnRow');
  const btnExplore = document.getElementById('btnCorrExploreStock');

  if (!box) return;
  box.classList.remove('hidden');

  const corr = item.correlation || {};
  const ticker = item.ticker || 'IHSG';

  if (badge) badge.textContent = `#${ticker}`;
  if (newsEl) newsEl.textContent = item.title || '-';

  if (corr.score != null) {
    if (techEl) {
      const cat = corr.catalyst;
      techEl.textContent = cat
        ? `${cat.label} · Skor ${cat.base_score} → ${cat.adjusted_score}`
        : `Skor ${corr.score}/100 (${corr.trigger_label || 'Aktif'})`;
    }
  } else {
    if (techEl) {
      techEl.textContent = ticker === 'IHSG' ? 'Indeks Harga Saham Gabungan (IHSG)' : 'Belum Masuk Pantauan Sinyal Aktif';
    }
  }

  if (actionEl) {
    actionEl.textContent = corr.action_eval || 'Pantau pergerakan volume dan aksi akumulasi Smart Money.';
  }

  if (btnRow && btnExplore) {
    if (ticker && ticker !== 'IHSG') {
      btnRow.classList.remove('hidden');
      btnExplore.onclick = () => {
        selectStockAndGoToInspector(ticker);
      };
    } else {
      btnRow.classList.add('hidden');
    }
  }

  box.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// =====================================================================
// KALKULATOR LOT & UKURAN RISIKO INTERAKTIF
// =====================================================================
function openLotCalculatorModal() {
  const modal = document.getElementById('lotCalculatorModal');
  if (modal) modal.classList.remove('hidden');

  // Pre-fill jika ada saham yang sedang dipilih
  if (selectedStockDetail) {
    const entryInput = document.getElementById('calcModalEntry');
    const stopInput = document.getElementById('calcModalStop');
    const plan = selectedStockDetail.trading_plan || {};
    const entry = plan.entry_price || plan.entry_high || selectedStockDetail.close;
    const sl = plan.stop_loss || Math.round(entry * 0.96);
    if (entryInput) entryInput.value = entry;
    if (stopInput) stopInput.value = sl;
  }
  runModalLotCalculation();
}

function openLotCalcForSelectedStock() {
  openLotCalculatorModal();
}

function openLotCalculatorForStockDetails(ticker, price, stopLoss) {
  const modal = document.getElementById('lotCalculatorModal');
  if (modal) modal.classList.remove('hidden');

  const entryInput = document.getElementById('calcModalEntry');
  const stopInput = document.getElementById('calcModalStop');
  if (entryInput) entryInput.value = price;
  if (stopInput) stopInput.value = stopLoss;

  runModalLotCalculation();
}

function openLotCalculatorForTicker(ticker) {
  const s = currentStocks.find(x => x.ticker === ticker);
  if (s) {
    const plan = s.trading_plan || {};
    const entry = plan.entry_price || plan.entry_high || s.close;
    const sl = plan.stop_loss || Math.round(entry * 0.96);
    openLotCalculatorForStockDetails(s.ticker, entry, sl);
  } else {
    openLotCalculatorModal();
  }
}

function closeLotCalculatorModal() {
  const modal = document.getElementById('lotCalculatorModal');
  if (modal) modal.classList.add('hidden');
}

function runModalLotCalculation() {
  const capital = parseFloat(document.getElementById('calcModalCapital')?.value) || 0;
  const riskPct = parseFloat(document.getElementById('calcModalRiskPct')?.value) || 0;
  const entry = parseFloat(document.getElementById('calcModalEntry')?.value) || 0;
  const stop = parseFloat(document.getElementById('calcModalStop')?.value) || 0;

  const lotEl = document.getElementById('resLotCount');
  const valEl = document.getElementById('resTotalVal');
  const riskEl = document.getElementById('resMaxRisk');
  const profitEl = document.getElementById('resTargetProfit');

  if (entry <= stop) {
    if (lotEl) lotEl.textContent = '0 Lot (Batas Rugi harus < Harga Beli!)';
    if (valEl) valEl.textContent = 'Rp 0';
    if (riskEl) riskEl.textContent = 'Periksa kembali harga batas rugi';
    if (profitEl) profitEl.textContent = 'Rp 0';
    return;
  }

  // Biaya Fee Sekuritas (~0.15% Beli + 0.25% Jual = 0.40% Roundtrip)
  const feeBuyPct = 0.0015;
  const feeSellPct = 0.0025;
  const feeRoundtripPct = feeBuyPct + feeSellPct; // 0.0040 (0.4%)

  // Risiko per lembar saham = penurunan harga ke SL + fee sekuritas
  const perShareRisk = (entry - stop) + (entry * feeRoundtripPct);
  const maxRiskRp = capital * (riskPct / 100);

  let lots = 0;
  if (perShareRisk > 0 && entry > 0) {
    const lotsByRisk = Math.floor(maxRiskRp / (perShareRisk * 100));
    // Manajemen Risiko (Position Sizing): Batasi alokasi maksimal 20% modal per saham demi diversifikasi & proteksi
    const maxAllocCapital = capital * 0.20;
    const lotsByCap = Math.floor(maxAllocCapital / (entry * (1 + feeBuyPct) * 100));
    lots = Math.max(0, Math.min(lotsByRisk, lotsByCap));
  }

  const grossCost = lots * entry * 100;
  const buyFee = grossCost * feeBuyPct;
  const totalCost = Math.round(grossCost + buyFee);
  const actualRiskRp = Math.round(lots * perShareRisk * 100);
  const actualRiskPct = capital > 0 ? ((actualRiskRp / capital) * 100).toFixed(1) : '0.0';

  // Estimasi Target Profit TP1 (Target Baku R:R 1 : 2.0 terhadap risiko per lembar) setelah dikurangi fee sekuritas
  const riskPerShare = Math.max(1, entry - stop);
  const tp1Price = selectedStockDetail?.trading_plan?.target_1 || Math.round(entry + (APP_TRADING_RULES.DEFAULT_RR * riskPerShare));
  const grossProfit = lots * (tp1Price - entry) * 100;
  const totalFee = (grossCost * feeBuyPct) + (lots * tp1Price * 100 * feeSellPct);
  const netProfit = Math.max(0, Math.round(grossProfit - totalFee));
  const netProfitPct = totalCost > 0 ? ((netProfit / totalCost) * 100).toFixed(1) : '0.0';

  if (lotEl) lotEl.textContent = `${fmtNumber(lots)} Lot (Maks. 20% Modal)`;
  if (valEl) valEl.textContent = fmtPrice(totalCost);
  if (riskEl) riskEl.textContent = `${fmtPrice(actualRiskRp)} (${actualRiskPct}% modal)`;
  if (profitEl) profitEl.textContent = `${fmtPrice(netProfit)} (+${netProfitPct}% net, R:R 1 : ${APP_TRADING_RULES.DEFAULT_RR.toFixed(1)})`;
}

// =====================================================================
// KAMUS ISTILAH SAHAM INTERAKTIF (GLOSSARY)
// =====================================================================
const GLOSSARY_TERMS = {
  scenario: {
    title: 'Skenario Rencana Trading (2-Leg Swing Plan)',
    badge: 'Rencana Trading',
    desc: 'Panduan objektif titik Harga Beli (Entry Pullback dekat support MA20 / VWAP), Batas Rugi (Stop Loss di bawah struktur Low + ATR), serta 2 target keuntungan bertahap (TP1 untuk amankan modal & geser SL ke titik impas, TP2 untuk mengawal tren).'
  },
  smart_money: {
    title: 'Smart Money (Bandar / Investor Institusi)',
    badge: 'Konsep Dasar',
    desc: 'Pelaku pasar bermodal sangat besar (manajer investasi, dana pensiun, institusi asing, atau bandar profesional). Pergerakan akumulasi atau distribusi dana mereka menggerakkan tren harga saham utama.'
  },
  vwap: {
    title: 'VWAP 5 Hari (Volume-Weighted Average Price)',
    badge: 'Indikator Modal',
    desc: 'Rata-rata harga beli saham yang dibobotkan dengan volume transaksi selama 5 hari bursa terakhir. Level ini mencerminkan perkiraan modal rata-rata pelaku pasar besar. Membeli dekat area VWAP meminimalkan risiko harga berbalik turun.'
  },
  vsa: {
    title: 'VSA (Volume Spread Analysis)',
    badge: 'Analisis Candle',
    desc: 'Metodologi membaca niat pasar dengan mengamati lebar rentang candle (spread harga tinggi-rendah) dipadukan dengan volume transaksi. Kenaikan harga disertai lonjakan volume menandakan permintaan beli nyata.'
  },
  stop_loss: {
    title: 'Batas Rugi (Stop Loss / SL)',
    badge: 'Pagar Pengaman',
    desc: 'Tingkat harga yang ditentukan sebelum membeli di mana Anda wajib menjual saham untuk membatasi kerugian. Stop loss melindungi modal Anda dari penurunan harga yang dalam (nyangkut).'
  },
  take_profit: {
    title: 'Target Untung (Take Profit / TP)',
    badge: 'Strategi Keluar',
    desc: 'Tingkat harga target di mana Anda merealisasikan keuntungan sesuai skenario trading yang telah direncanakan.'
  },
  risk_reward: {
    title: 'Rasio Risiko terhadap Keuntungan (Risk/Reward)',
    badge: 'Manajemen Risiko',
    desc: 'Perbandingan potensi kerugian terhadap potensi keuntungan. Rasio 1 : 2 artinya jika Anda siap menanggung risiko rugi Rp 100.000, maka potensi keuntungan minimal yang ditargetkan adalah Rp 200.000.'
  },
  lot: {
    title: '1 Lot Saham',
    badge: 'Ketentuan Bursa',
    desc: 'Satuan standar transaksi di Bursa Efek Indonesia (BEI). 1 Lot sama dengan 100 lembar saham.'
  },
  markup: {
    title: 'Markup Breakout',
    badge: 'Fase Tren',
    desc: 'Fase di mana harga didorong naik menembus area resisten disertai volume besar setelah tahap akumulasi selesai.'
  },
  akumulasi: {
    title: 'Akumulasi Bertahap',
    badge: 'Fase Tren',
    desc: 'Tahap pengumpulan saham oleh Smart Money secara tenang dan perlahan di rentang harga tertentu tanpa membuat harga melonjak drastis.'
  },
  distribusi: {
    title: 'Peringatan Distribusi (Waspada)',
    badge: 'Peringatan Risiko',
    desc: 'Fase di mana Smart Money mulai menjual saham mereka kepada investor ritel di harga tinggi sebelum harga mengalami penurunan signifikan.'
  },
  squeeze: {
    title: 'Squeeze & Kompresi Volatilitas (Rentang Harga Menyempit)',
    badge: 'Volatilitas',
    desc: 'Kondisi di mana Bollinger Bands masuk ke dalam Keltner Channel. Ini menandakan fluktuasi harga sedang menyusut tajam (fase istirahat/konsolidasi) sebelum terjadinya ledakan arah tren baru yang signifikan.'
  },
  turnover: {
    title: 'Turnover (Nilai Transaksi Harian)',
    badge: 'Likuiditas',
    desc: 'Total perputaran uang Rupiah riil dalam satu hari perdagangan saham. Saham dengan Turnover tinggi (≥ Rp 1 Miliar - Rp 5 Miliar) menjamin likuiditas yang cukup agar posisi Anda mudah dibeli dan dijual kembali tanpa tertahan.'
  },
  ma: {
    title: 'MA20 & MA50 (Moving Average 20 & 50 Hari)',
    badge: 'Tren Harga',
    desc: 'Garis rata-rata pergerakan harga 20 hari (tren jangka pendek) dan 50 hari (tren jangka menengah). Harga di atas MA20 menandakan tren naik yang sehat dan bertindak sebagai area support dinamis saat terjadi pullback.'
  },
  market_breadth: {
    title: 'Market Breadth (Keluasan Tren Pasar)',
    badge: 'Kondisi Bursa',
    desc: 'Persentase jumlah saham di seluruh bursa IDX yang posisinya berada di atas rata-rata MA20. Jika persentasenya di atas 55%, bursa berada dalam fase Bullish Expansion yang kondusif untuk swing trading. Jika di bawah 40%, bursa cenderung defensif/bearish.'
  }
};

function openGlossaryModal(termKey = 'all') {
  const modal = document.getElementById('glossaryModal');
  const body = document.getElementById('glossaryBody');
  if (!modal || !body) return;

  let entries = termKey === 'all'
    ? Object.entries(GLOSSARY_TERMS)
    : Object.entries(GLOSSARY_TERMS).filter(([k]) => k === termKey);

  if (entries.length === 0) {
    entries = Object.entries(GLOSSARY_TERMS);
  }

  body.innerHTML = entries.map(([key, item]) => `
    <div class="p-3.5 rounded-xl glass-subcard border border-white/[0.08] space-y-1.5" id="glossary-${key}">
      <div class="flex items-center justify-between gap-2">
        <span class="font-bold text-white text-xs">${item.title}</span>
        <span class="text-[10px] font-semibold px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-300 border border-emerald-400/30">${item.badge}</span>
      </div>
      <p class="text-xs text-slate-300 leading-relaxed">${item.desc}</p>
    </div>
  `).join('');

  modal.classList.remove('hidden');
}

function closeGlossaryModal() {
  const modal = document.getElementById('glossaryModal');
  if (modal) modal.classList.add('hidden');
}

// =====================================================================
// NOTIFIKASI & PERINGATAN PINTAR (LIVE TRADING ALERTS & AUDIO SYSTEM)
// =====================================================================
let activeAlertList = [];
let hasUnreadAlerts = false;

let sharedAudioCtx = null;

function playAlertChime() {
  const soundEnabled = localStorage.getItem('smartflow_alert_sound') !== 'false';
  if (!soundEnabled) return;
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;
    if (!sharedAudioCtx || sharedAudioCtx.state === 'closed') {
      sharedAudioCtx = new AudioCtx();
    }
    const ctx = sharedAudioCtx;
    if (ctx.state === 'suspended') {
      ctx.resume().catch(() => {});
    }
    const now = ctx.currentTime;

    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = 'sine';
    osc1.frequency.setValueAtTime(587.33, now);
    gain1.gain.setValueAtTime(0.18, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.25);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.25);

    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = 'sine';
    osc2.frequency.setValueAtTime(880.00, now + 0.10);
    gain2.gain.setValueAtTime(0.22, now + 0.10);
    gain2.gain.exponentialRampToValueAtTime(0.0001, now + 0.60);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(now + 0.10);
    osc2.stop(now + 0.60);
  } catch (e) {
    console.warn('AudioContext alert chime warning:', e);
  }
}

function testAlertSound() {
  playAlertChime();
  showToast('🔊 Nada lonceng alert berhasil diuji!', 'success');
}

function toggleAlertSound() {
  const current = localStorage.getItem('smartflow_alert_sound') !== 'false';
  const next = !current;
  localStorage.setItem('smartflow_alert_sound', next ? 'true' : 'false');
  updateAlertSoundUI(next);
  if (next) playAlertChime();
}

function updateAlertSoundUI(enabled) {
  const btn = document.getElementById('btnToggleAlertSound');
  const badge = document.getElementById('alertSoundStatusBadge');
  if (btn) {
    btn.textContent = enabled ? 'ON' : 'OFF';
    btn.className = enabled
      ? 'px-2.5 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 text-[10px] font-bold transition active:scale-95 cursor-pointer min-w-[42px] text-center'
      : 'px-2.5 py-1 rounded-lg bg-slate-800 text-slate-400 border border-white/10 text-[10px] font-bold transition active:scale-95 cursor-pointer min-w-[42px] text-center';
  }
  if (badge) {
    badge.textContent = enabled ? 'Suara Aktif' : 'Suara Senyap';
    badge.className = enabled
      ? 'text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-400/30'
      : 'text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-800 text-slate-400 border border-white/10';
  }
}

function updateBrowserNotificationUI() {
  const statusText = document.getElementById('browserNotificationStatusText');
  const btn = document.getElementById('btnRequestNotification');
  if (!('Notification' in window)) {
    if (statusText) statusText.textContent = 'Browser ini tidak mendukung notifikasi push desktop';
    if (btn) {
      btn.textContent = 'Tidak Didukung';
      btn.disabled = true;
      btn.className = 'px-2.5 py-1 rounded-lg bg-slate-800 text-slate-500 text-[10px] font-bold cursor-not-allowed';
    }
    return;
  }

  if (Notification.permission === 'granted') {
    if (statusText) statusText.textContent = '🟢 Izin notifikasi browser aktif di perangkat ini';
    if (btn) {
      btn.textContent = 'Aktif ✓';
      btn.disabled = true;
      btn.className = 'px-2.5 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 text-[10px] font-bold cursor-default';
    }
  } else if (Notification.permission === 'denied') {
    if (statusText) statusText.textContent = '⚠️ Notifikasi diblokir di izin peramban Anda';
    if (btn) {
      btn.textContent = 'Diblokir';
      btn.disabled = true;
      btn.className = 'px-2.5 py-1 rounded-lg bg-rose-500/20 text-rose-300 border border-rose-400/30 text-[10px] font-bold cursor-not-allowed';
    }
  } else {
    if (statusText) statusText.textContent = 'Peringatan muncul di layar saat browser di latar belakang';
    if (btn) {
      btn.textContent = 'Aktifkan';
      btn.disabled = false;
      btn.className = 'px-2.5 py-1 rounded-lg bg-blue-500/20 text-blue-300 border border-blue-400/30 text-[10px] font-bold transition active:scale-95 cursor-pointer';
    }
  }
}

function _b64uToUint8(b64u) {
  const pad = '='.repeat((4 - (b64u.length % 4)) % 4);
  const raw = atob((b64u + pad).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

// Daftarkan perangkat ke Web Push server agar alert berita positif emiten masuk ke bar notifikasi HP
async function subscribeWebPush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return false;
  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    const keyRes = await fetch('/api/push/public-key');
    const { public_key } = await keyRes.json();
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: _b64uToUint8(public_key),
    });
  }
  const res = await fetch('/api/push/subscribe', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(sub.toJSON()),
  });
  return res.ok;
}

async function requestBrowserNotification() {
  if (!('Notification' in window)) {
    showToast('Peramban Anda tidak mendukung API Notifikasi.', 'error');
    return;
  }
  try {
    const perm = await Notification.requestPermission();
    updateBrowserNotificationUI();
    if (perm === 'granted') {
      playAlertChime();
      let ok = false;
      try { ok = await subscribeWebPush(); } catch (e) { console.error('Web push subscribe error:', e); }
      if (ok) {
        showToast('🔔 Aktif! Alert berita positif emiten akan masuk ke bar notifikasi HP.', 'success');
        fetch('/api/alerts/test-push', { method: 'POST' }).catch(() => {});
      } else {
        showToast('Izin diberikan, tetapi pendaftaran push gagal. Di iPhone: pasang aplikasi ke Layar Utama dulu.', 'error');
      }
    } else if (perm === 'denied') {
      showToast('Izin notifikasi tidak diberikan oleh pengguna.', 'error');
    }
  } catch (err) {
    console.error('Request notification error:', err);
  }
}

function getAlertPreferences() {
  try {
    const raw = localStorage.getItem('smartflow_alert_prefs');
    if (raw) return JSON.parse(raw);
  } catch (_) {}
  return {
    support: true,
    tpSl: true,
    volSpike: true,
    news: true,
  };
}

// Mengirim notifikasi sistem langsung ke bar notifikasi HP / Desktop via Service Worker
async function sendSystemNotification(title, body, url = '/', tag = '') {
  if (!('Notification' in window) || Notification.permission !== 'granted') return false;
  try {
    const prefs = getAlertPreferences();
    if (!prefs.news && tag.startsWith('news-')) return false;

    // 1. Prioritas Utama: Service Worker showNotification (Muncul di bar notifikasi HP)
    if ('serviceWorker' in navigator) {
      try {
        const reg = await navigator.serviceWorker.ready;
        if (reg && reg.showNotification) {
          await reg.showNotification(title, {
            body: body,
            icon: '/static/icons/icon-192.svg',
            badge: '/static/icons/icon-192.svg',
            data: { url: url },
            vibrate: [200, 100, 200],
            tag: tag || ('news-alert-' + Date.now()),
            renotify: true,
          });
          return true;
        }
      } catch (swErr) {
        console.warn('[Notification] SW showNotification fallback:', swErr);
      }
    }

    // 2. Fallback: Window Notification
    const n = new Notification(title, {
      body: body,
      icon: '/static/icons/icon-192.svg',
      data: { url: url },
      tag: tag || undefined,
    });
    n.onclick = function() {
      window.focus();
      if (url && url !== '/') {
        const matchTicker = url.match(/ticker=([A-Z0-9]+)/);
        if (matchTicker) selectStockAndGoToInspector(matchTicker[1]);
      }
      n.close();
    };
    return true;
  } catch (err) {
    console.error('[Notification] Error sendSystemNotification:', err);
    return false;
  }
}

// Uji coba kirim notifikasi berita katalis positif langsung ke bar notifikasi HP
async function testPositiveNewsNotification() {
  if (!('Notification' in window)) {
    showToast('Peramban Anda tidak mendukung API Notifikasi.', 'error');
    return;
  }

  if (Notification.permission !== 'granted') {
    await requestBrowserNotification();
    if (Notification.permission !== 'granted') return;
  }

  playAlertChime();

  // 1. Kirim notifikasi lokal via Service Worker ke bar notifikasi HP
  const sentLocal = await sendSystemNotification(
    '📈 Katalis Positif: #BBCA (+3.2%)',
    'Laba Bersih & Arus Dana Smart Money Terverifikasi • Berhasil terhubung ke Bar Notifikasi HP Anda!',
    '/?ticker=BBCA',
    'test-notif-' + Date.now()
  );

  // 2. Kirim juga tes push ke server
  fetch('/api/alerts/test-push', { method: 'POST' })
    .then(r => r.json())
    .catch(() => ({}));

  if (sentLocal) {
    showToast('🔔 Notifikasi berita katalis terkirim ke bar notifikasi HP Anda!', 'success');
  } else {
    showToast('Notifikasi dikirim. Periksa izin notifikasi browser HP Anda.', 'info');
  }
}

// Memeriksa dan memicu notifikasi bar HP untuk berita katalis positif baru
async function triggerPositiveNewsBarNotification(items) {
  if (!items || !items.length) return;
  const prefs = getAlertPreferences();
  if (!prefs.news) return;

  const posItems = items.filter(n => n.sentiment === 'POSITIVE' && n.ticker && n.ticker !== 'IHSG');
  if (!posItems.length) return;

  let notifiedMap = {};
  try {
    notifiedMap = JSON.parse(localStorage.getItem('smartflow_notified_news') || '{}');
  } catch (_) {
    notifiedMap = {};
  }

  let newNotifCount = 0;
  for (const n of posItems.slice(0, 3)) {
    const key = String(n.title || '').trim().toLowerCase();
    if (!key || notifiedMap[key]) continue;

    notifiedMap[key] = Date.now();
    newNotifCount++;

    const corr = n.correlation || {};
    let subDesc = n.title;
    if (corr.close) {
      subDesc += `\nHarga: ${fmtPrice(corr.close)}` + (corr.pct_change != null ? ` (${corr.pct_change >= 0 ? '+' : ''}${corr.pct_change}%)` : '');
    }
    subDesc += `\nSumber: ${n.source || 'BEI'} • Terverifikasi Katalis`;

    await sendSystemNotification(
      `📈 Katalis Positif #${n.ticker}`,
      subDesc,
      `/?ticker=${n.ticker}`,
      `news-${n.ticker}`
    );
  }

  if (newNotifCount > 0) {
    playAlertChime();
    const now = Date.now();
    const cleaned = {};
    for (const [k, ts] of Object.entries(notifiedMap)) {
      if (now - ts < 3 * 86400 * 1000) cleaned[k] = ts;
    }
    localStorage.setItem('smartflow_notified_news', JSON.stringify(cleaned));
  }
}

function saveAlertPreferences() {
  const prefs = {
    support: document.getElementById('prefAlertSupport')?.checked ?? true,
    tpSl: document.getElementById('prefAlertTpSl')?.checked ?? true,
    volSpike: document.getElementById('prefAlertVolSpike')?.checked ?? true,
    news: document.getElementById('prefAlertNews')?.checked ?? true,
  };
  localStorage.setItem('smartflow_alert_prefs', JSON.stringify(prefs));
  showToast('Preferensi kategori alert disimpan.', 'success');
}

function loadAlertPreferences() {
  try {
    const raw = localStorage.getItem('smartflow_alert_prefs');
    if (raw) {
      const prefs = JSON.parse(raw);
      if (document.getElementById('prefAlertSupport')) document.getElementById('prefAlertSupport').checked = prefs.support ?? true;
      if (document.getElementById('prefAlertTpSl')) document.getElementById('prefAlertTpSl').checked = prefs.tpSl ?? true;
      if (document.getElementById('prefAlertVolSpike')) document.getElementById('prefAlertVolSpike').checked = prefs.volSpike ?? true;
      if (document.getElementById('prefAlertNews')) document.getElementById('prefAlertNews').checked = prefs.news ?? true;
    }
  } catch (_) {}
}

function generateAlertsFromMarketData(stocks) {
  if (!stocks || !Array.isArray(stocks)) return;

  const alerts = [];
  const regime = currentMarketRegime || {};

  // 1. Alert Market Regime
  if (regime.status === 'DEFENSIVE_PULLBACK' || regime.color === 'rose' || regime.color === 'amber') {
    alerts.push({
      id: 'regime-defensive',
      type: 'REGIME',
      badge: 'PASAR DEFENSIF',
      badgeColor: 'bg-amber-500/15 text-amber-300 border-amber-400/30',
      title: 'IHSG Tertekan (Mode Defensif)',
      desc: 'Disiplin antre entry di Support Terdekat (menunggu pullback terkonfirmasi).',
      time: 'Hari Ini'
    });
  }

  // 2. Alert Katalis Berita Positif Emiten (Paling Relevan untuk Bar HP & Feed)
  if (cachedNewsItems && cachedNewsItems.length > 0) {
    const posNews = cachedNewsItems.filter(n => n.sentiment === 'POSITIVE' && n.ticker && n.ticker !== 'IHSG').slice(0, 4);
    posNews.forEach(n => {
      alerts.push({
        id: 'news-' + n.ticker + '-' + (n.published_ts || n.title.slice(0, 10)),
        ticker: n.ticker,
        type: 'NEWS_CATALYST',
        badge: 'KATALIS POSITIF',
        badgeColor: 'bg-emerald-500/15 text-emerald-300 border-emerald-400/30',
        title: `${n.ticker} • Katalis Berita Terverifikasi`,
        desc: `${n.title} (${n.source || 'BEI'} • ${n.relative_time || 'Baru'})`,
        time: n.relative_time || 'Baru'
      });
    });
  }

  // 3. Alert Kandidat Saham Pilihan (Fix double Rp Rp)
  const topCandidates = stocks.filter(s =>
    (s.close || 0) >= 70 &&
    (s.value_b_idr || 0) >= 1.0 &&
    (s.tape_quality == null || s.tape_quality.is_organic !== false) &&
    !s.retail_trap &&
    (s.bdr_pct >= 5.0 || s.top3_bsr >= 1.15 || (s.smart_money_score || 0) >= 70)
  ).slice(0, 3);

  topCandidates.forEach(s => {
    const plan = s.trading_plan || {};
    const entryPrice = plan.entry_price || plan.entry_low || s.close;
    const supportLabel = plan.support_label || 'Support Terdekat';
    alerts.push({
      id: 'support-' + s.ticker,
      ticker: s.ticker,
      type: 'SUPPORT_ENTRY',
      badge: 'BUY ON SUPPORT',
      badgeColor: 'bg-emerald-500/15 text-emerald-300 border-emerald-400/30',
      title: `${s.ticker} • Antre Support ${fmtPrice(entryPrice)}`,
      desc: `Area ${supportLabel} • Skor SM ${s.smart_money_score || '-'} • Target TP1 ${fmtPrice(plan.target_1 || Math.round(s.close * 1.07))}`,
      time: 'Sesi Ini'
    });
  });

  // 4. Alert Volume Spike Ekstrem (> 1.5x)
  const volSpikes = stocks
    .filter(s => (s.vol_ratio || 0) >= 1.5 && (s.value_b_idr || 0) >= 1.0 && (s.close || 0) >= 70)
    .sort((a, b) => (b.vol_ratio || 0) - (a.vol_ratio || 0))
    .slice(0, 2);

  volSpikes.forEach(s => {
    if (!alerts.some(a => a.ticker === s.ticker)) {
      alerts.push({
        id: 'vol-' + s.ticker,
        ticker: s.ticker,
        type: 'VOL_SPIKE',
        badge: 'VOL SPIKE',
        badgeColor: 'bg-teal-500/15 text-teal-300 border-teal-400/30',
        title: `${s.ticker} • Lonjakan Volume ${s.vol_ratio}x`,
        desc: `Transaksi Rp ${(s.value_b_idr || 0).toFixed(1)} Miliar • Terdeteksi lonjakan volume di atas rata-rata.`,
        time: 'Terdeteksi'
      });
    }
  });

  // Filter alerts berdasarkan preferensi yang dicentang di modal
  const prefs = getAlertPreferences();
  activeAlertList = alerts.filter(a => {
    if (a.type === 'NEWS_CATALYST' && !prefs.news) return false;
    if (a.type === 'SUPPORT_ENTRY' && !prefs.support) return false;
    if (a.type === 'VOL_SPIKE' && !prefs.volSpike) return false;
    return true;
  });

  renderAlertFeed();

  // Tampilkan indikator badge jika ada sinyal
  if (activeAlertList.length > 0) {
    hasUnreadAlerts = true;
    updateAlertBadgeUI(true, activeAlertList.length);
  }
}

function renderAlertFeed() {
  const container = document.getElementById('alertLiveFeedContainer');
  const countBadge = document.getElementById('alertFeedCountBadge');
  if (countBadge) countBadge.textContent = activeAlertList.length;

  if (!container) return;

  if (activeAlertList.length === 0) {
    container.innerHTML = `
      <div class="p-4 rounded-xl bg-slate-900/30 border border-white/[0.04] text-center text-slate-400 text-xs">
        Belum ada sinyal baru. Sinkronisasi data pasar untuk memperbarui feed peringatan.
      </div>
    `;
    return;
  }

  container.innerHTML = activeAlertList.map(a => {
    const clickAttr = a.ticker
      ? `onclick="closeAlertModal(); selectStockAndGoToInspector('${escHtml(a.ticker)}')"`
      : '';
    const cursorClass = a.ticker ? 'cursor-pointer hover:border-emerald-500/40 hover:bg-white/[0.06]' : '';

    return `
      <div ${clickAttr} class="p-2.5 rounded-xl bg-slate-900/60 border border-white/[0.06] flex items-start justify-between gap-2.5 transition ${cursorClass}">
        <div class="space-y-1">
          <div class="flex items-center gap-1.5 flex-wrap">
            <span class="text-[9px] font-mono font-bold px-1.5 py-0.2 rounded border ${a.badgeColor}">
              ${a.badge}
            </span>
            <span class="font-bold text-white text-xs">${escHtml(a.title)}</span>
          </div>
          <p class="text-[10px] text-slate-300 leading-relaxed">${escHtml(a.desc)}</p>
        </div>
        <div class="text-right shrink-0">
          <span class="text-[9px] font-mono text-slate-400">${a.time}</span>
          ${a.ticker ? '<div class="text-[9px] text-emerald-400 font-semibold mt-1">Detail &rarr;</div>' : ''}
        </div>
      </div>
    `;
  }).join('');
}

function updateAlertBadgeUI(hasUnread, count = 0) {
  const headerDot = document.getElementById('headerAlertDot');
  const menuDot = document.getElementById('alertMenuBadgeDot');
  const countBadge = document.getElementById('dropdownAlertCount');

  if (headerDot) {
    if (hasUnread) headerDot.classList.remove('hidden');
    else headerDot.classList.add('hidden');
  }
  if (menuDot) {
    if (hasUnread) menuDot.classList.remove('hidden');
    else menuDot.classList.add('hidden');
  }
  if (countBadge) {
    if (hasUnread && count > 0) {
      countBadge.textContent = `${count} Baru`;
      countBadge.className = 'text-[10px] font-mono font-bold px-1.5 py-0.2 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-400/30';
    } else {
      countBadge.textContent = 'Live';
      countBadge.className = 'text-[10px] font-mono font-bold px-1.5 py-0.2 rounded-full bg-blue-500/20 text-blue-300 border border-blue-400/30';
    }
  }
}

function markAllAlertsRead() {
  hasUnreadAlerts = false;
  updateAlertBadgeUI(false, 0);
  showToast('Seluruh notifikasi ditandai sudah dibaca.', 'success');
}

function openAlertModal() {
  const modal = document.getElementById('alertModal');
  if (modal) {
    modal.classList.remove('hidden');
    const soundEnabled = localStorage.getItem('smartflow_alert_sound') !== 'false';
    updateAlertSoundUI(soundEnabled);
    updateBrowserNotificationUI();
    loadAlertPreferences();
    renderAlertFeed();
  }
}

function closeAlertModal() {
  const modal = document.getElementById('alertModal');
  if (modal) modal.classList.add('hidden');
}

// Kompatibilitas jika dipanggil dari tempat lama
function openSettingsModal() {
  // Arahkan langsung ke menu pengaturan utama Gambar 1
  toggleSettingsDropdown();
}

function closeSettingsModal() {
  closeAlertModal();
  closeSettingsDropdown();
}


function toggleExpertPillarsView() {
  const content = document.getElementById('expertPillarsContent');
  const btn = document.getElementById('btnTogglePillars');
  if (!content) return;
  const isHidden = content.classList.contains('hidden');
  content.classList.toggle('hidden', !isHidden);
  if (btn) btn.textContent = isHidden ? 'Sembunyikan Rincian' : 'Tampilkan Rincian';
}

function toggleCatalystDetails() {
  const content = document.getElementById('snc-factors');
  const btn = document.getElementById('snc-factors-toggle');
  if (!content || !btn) return;
  const isHidden = content.classList.toggle('hidden');
  const count = content.children.length;
  const passed = Array.from(content.children).filter(item => item.textContent.trim().startsWith('Terpenuhi:')).length;
  btn.innerHTML = isHidden
    ? `<span>${passed} dari ${count} kriteria terpenuhi</span><span class="text-[9px]">▾</span>`
    : `<span>Sembunyikan kriteria</span><span class="text-[9px]">▴</span>`;
}

function openTradingViewSuperchart(ticker) {
  openTradingViewModal();
}

// =====================================================================
// BADGES & HELPERS
// =====================================================================
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

const SIGNAL_SHORT_LABEL = {
  MARKUP_BREAKOUT: 'Breakout',
  BIG_ACCUMULATION: 'Big Accum',
  SILENT_ACCUMULATION: 'Silent Accum',
  FOREIGN_INFLOW: 'Foreign Inflow',
  DISTRIBUTION_WARNING: 'Distribusi',
};

// Badge tipe sinyal (Mode Mahir): sinyal hari ini, atau sinyal aktif yang tercatat di Watchlist
function renderSignalTypeBadge(s) {
  const today = String(s.trigger_type || '').toUpperCase();
  const wl = String(s.tracker_trigger_type || '').toUpperCase();
  const wlActive = ['WATCHLIST', 'RUNNING'].includes(String(s.tracker_status || '').toUpperCase());
  let code = '';
  let suffix = '';
  if (SIGNAL_SHORT_LABEL[today]) {
    code = today;
  } else if (wl && wlActive && SIGNAL_SHORT_LABEL[wl]) {
    code = wl;
    suffix = ' · WL';
  }
  if (!code) return '';
  const hidden = isExpertMode ? '' : 'hidden';
  const title = suffix ? `Sinyal ${SIGNAL_SHORT_LABEL[code]} aktif di Watchlist sejak ${s.tracker_signal_date || '-'}` : `Sinyal hari ini: ${SIGNAL_SHORT_LABEL[code]}`;
  return `<span class="expert-only ${hidden} block mb-1 mx-auto w-fit px-2 py-0.5 rounded-full text-[9px] font-bold ${getTriggerBadgeClass(code)}" title="${escHtml(title)}">${SIGNAL_SHORT_LABEL[code]}${suffix}</span>`;
}

function getScoreColor(score) {
  if (score >= 76) return 'from-emerald-500 to-teal-400 text-emerald-300';
  if (score >= 64) return 'from-blue-500 to-emerald-400 text-blue-300';
  if (score >= 50) return 'from-amber-500 to-yellow-400 text-amber-300';
  return 'from-rose-600 to-red-400 text-rose-300';
}

function getStockLogoImg(ticker, sizeCls = 'w-7 h-7') {
  if (!ticker) return '';
  const rawTicker = String(ticker).trim().toUpperCase().replace(/[^A-Z0-9.-]/g, '');
  const cleanTicker = escHtml(rawTicker);
  const cdnUrl = `https://assets.stockbit.com/logos/companies/${encodeURIComponent(rawTicker)}.png`;
  const fallbackUrl = `https://ui-avatars.com/api/?name=${encodeURIComponent(rawTicker)}&background=1e293b&color=38bdf8&bold=true&length=2`;
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

let toastTimeoutId = null;

function showToast(msg, type = 'success') {
  const banner = document.getElementById('toastBanner');
  if (!banner) return;
  const text = document.getElementById('toastMessage');
  banner.classList.remove(
    'hidden',
    'bg-emerald-950/90',
    'border-emerald-500/40',
    'text-emerald-200',
    'bg-rose-950/90',
    'border-rose-500/40',
    'text-rose-200',
    'bg-sky-950/90',
    'border-sky-500/40',
    'text-sky-200'
  );
  if (type === 'error') {
    banner.classList.add('bg-rose-950/90', 'border-rose-500/40', 'text-rose-200');
  } else if (type === 'info') {
    banner.classList.add('bg-sky-950/90', 'border-sky-500/40', 'text-sky-200');
  } else {
    banner.classList.add('bg-emerald-950/90', 'border-emerald-500/40', 'text-emerald-200');
  }
  if (text) text.textContent = msg;

  if (toastTimeoutId) clearTimeout(toastTimeoutId);
  toastTimeoutId = setTimeout(() => {
    banner.classList.add('hidden');
  }, 4000);
}

// =====================================================================
// DATA LOADING: SCREENER & KPIS
// =====================================================================
let lastShownSyncError = null;

async function loadScreenerData(preserveSelection = false) {
  const trigger = document.getElementById('filterTrigger')?.value || 'ALL';
  const minVol = document.getElementById('filterVolRatio')?.value || '0.0';
  const minScore = document.getElementById('filterMinScore')?.value || '0';
  const sortBy = document.getElementById('filterSortBy')?.value || 'score';
  const search = document.getElementById('filterSearch')?.value.trim() || '';

  const params = new URLSearchParams({
    trigger,
    min_vol_ratio: minVol,
    min_score: minScore,
    sort_by: sortBy,
    min_value_b: document.getElementById('filterMinValue')?.value || '0',
    search,
    _t: Date.now(),
  });

  try {
    const res = await fetchWithTimeout(`/api/screener?${params.toString()}`, { cache: 'no-store' }, 30000);
    if (!res.ok) throw new Error('Gagal mengambil data screener');
    const data = await res.json();

    const srcBadge = document.getElementById('activeSourceBadge');
    if (srcBadge) srcBadge.textContent = data.source_name;

    const syncEl = document.getElementById('lastSyncBadge');
    if (syncEl && data.last_sync_time) {
      syncEl.textContent = `Update: ${data.last_sync_time} (Auto ${data.auto_sync_interval_min || 30}m)`;
      if (data.last_sync_error) {
        syncEl.title = `Peringatan Sync Terakhir: ${data.last_sync_error}`;
      } else {
        syncEl.title = '';
      }
    }

    // S5: Tampilkan peringatan bila terjadi error pada background sync
    if (data.last_sync_error && data.last_sync_error !== lastShownSyncError) {
      lastShownSyncError = data.last_sync_error;
      showToast(`⚠️ Peringatan Sync: ${data.last_sync_error}`, 'error');
    } else if (!data.last_sync_error) {
      lastShownSyncError = null;
    }

    updateKPICards(data.kpis, trigger);
    if (data.kpis && data.kpis.market_regime) {
      renderMarketRegimeBadge(data.kpis.market_regime);
    }

    currentStocks = data.stocks || [];
    currentTodayCandidates = data.today_candidates || [];
    if (!preserveSelection) currentPage = 1;
    renderScreenerTable(currentStocks);

    // Render kartu pilihan hari ini yang konsisten antar sesi & tercatat di watchlist
    renderTodayCandidates(currentTodayCandidates.length > 0 ? currentTodayCandidates : currentStocks);

    if (currentStocks.length > 0) {
      const targetTicker =
        preserveSelection && currentStocks.some((s) => s.ticker === selectedTicker)
          ? selectedTicker
          : currentStocks[0].ticker;
      await selectStock(targetTicker, false, false);
    }
  } catch (err) {
    showToast(`Error: ${err.message}`, 'error');
    if (!currentStocks || currentStocks.length === 0) {
      renderTableError(err.message);
      renderCandidatesError(err.message);
    }
  }
}

function renderKpiSparkline(svgId, gradId, series, colorHex) {
  const svgEl = document.getElementById(svgId);
  if (!svgEl || !Array.isArray(series) || series.length === 0) return;

  const pts = series.length === 1 ? [series[0], series[0]] : series.slice(-10);
  const minVal = Math.min(...pts);
  const maxVal = Math.max(...pts);
  const span = Math.max(maxVal - minVal, 1e-5);

  const xStart = 4;
  const xEnd = 76;
  const yBottom = 25;
  const yTop = 5;

  const coords = pts.map((val, idx) => {
    const x = +(xStart + (idx / Math.max(pts.length - 1, 1)) * (xEnd - xStart)).toFixed(1);
    const norm = maxVal === minVal ? 0.5 : (val - minVal) / span;
    const y = +(yBottom - norm * (yBottom - yTop)).toFixed(1);
    return { x, y };
  });

  const lineCmds = coords.map((pt, i) => `${i === 0 ? 'M' : 'L'}${pt.x} ${pt.y}`).join(' ');
  const firstPt = coords[0];
  const lastPt = coords[coords.length - 1];
  const areaCmds = `${lineCmds} L${lastPt.x} 29 L${firstPt.x} 29 Z`;

  svgEl.innerHTML = `
    <defs>
      <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="${colorHex}" stop-opacity="0.30"/>
        <stop offset="100%" stop-color="${colorHex}" stop-opacity="0"/>
      </linearGradient>
    </defs>
    <path d="${areaCmds}" fill="url(#${gradId})"/>
    <path d="${lineCmds}" stroke="${colorHex}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
    <circle cx="${lastPt.x}" cy="${lastPt.y}" r="2.2" fill="${colorHex}"/>
  `;
}

function renderKpiDeltaBadge(deltaId, labelId, pctChange, diffVal, prevVal, invertColor = false, isFloatDiff = false) {
  const deltaEl = document.getElementById(deltaId);
  const labelEl = document.getElementById(labelId);
  if (!deltaEl) return '#10b981';

  const numDiff = Number(diffVal || 0);
  const absPct = Math.abs(Number(pctChange || 0)).toFixed(1);
  const arrow = numDiff > 0 ? '↑' : numDiff < 0 ? '↓' : '•';
  const fmtDiff = isFloatDiff
    ? `${numDiff > 0 ? '+' : ''}${numDiff.toFixed(1)}`
    : `${numDiff > 0 ? '+' : ''}${Math.round(numDiff)}`;

  const isPositiveGood = invertColor ? numDiff < 0 : numDiff > 0;
  const isNegativeBad = invertColor ? numDiff > 0 : numDiff < 0;

  let textCls = 'text-slate-400';
  let strokeHex = '#94a3b8';
  if (isPositiveGood) {
    textCls = 'text-emerald-400';
    strokeHex = '#10b981';
  } else if (isNegativeBad) {
    textCls = 'text-rose-400';
    strokeHex = '#f43f5e';
  }

  deltaEl.className = `font-bold ${textCls} flex items-center gap-0.5`;
  deltaEl.textContent = `${arrow} ${absPct}% (${fmtDiff})`;

  if (labelEl) {
    labelEl.textContent = prevVal !== undefined && prevVal !== null ? `vs kemarin (${prevVal})` : 'vs kemarin';
  }
  return strokeHex;
}

function updateKPICards(kpis, currentTrigger) {
  if (!kpis) return;
  const elTotal = document.getElementById('kpiTotalEmiten');
  if (elTotal) elTotal.textContent = kpis.total_emiten;
  const elAvg = document.getElementById('kpiAvgScore');
  if (elAvg) elAvg.textContent = `Avg Skor: ${kpis.avg_smart_money_score}`;
  const elMarkup = document.getElementById('kpiMarkupCount');
  if (elMarkup) elMarkup.textContent = kpis.markup_triggers;
  const elAccum = document.getElementById('kpiAccumCount');
  if (elAccum) elAccum.textContent = kpis.accum_triggers;
  const elDist = document.getElementById('kpiDistCount');
  if (elDist) elDist.textContent = kpis.distribution_warnings;

  if (kpis.market_regime) {
    const autoTimerEl = document.getElementById('marketAutoTimer');
    const todayRegimeBadge = document.getElementById('todayRegimeBadge');
    const todayMarketSentence = document.getElementById('todayMarketSentence');
    const reg = kpis.market_regime;

    const isCrash = reg.status === 'CRASH_LOCKED' || reg.color === 'rose';
    const isBull = reg.status === 'NORMAL_ACTIVE' || reg.color === 'emerald';
    const badgeCls = isCrash ? 'text-rose-400 font-semibold' : isBull ? 'text-emerald-400 font-semibold' : 'text-amber-400 font-semibold';

    if (autoTimerEl) {
      autoTimerEl.innerHTML = `<span class="${badgeCls}" title="${escHtml(reg.regime_note)}">Regime: ${escHtml(reg.label || reg.status)} (${escHtml(reg.breadth_ma20_pct)}% &gt; MA20)</span>`;
    }

    if (todayRegimeBadge) {
      todayRegimeBadge.textContent = reg.label || reg.status;
      todayRegimeBadge.className = `text-[10px] font-semibold px-2 py-0.5 rounded-full ${
        isCrash
          ? 'bg-rose-500/15 text-rose-300 border border-rose-400/30'
          : isBull
          ? 'bg-emerald-500/15 text-emerald-300 border border-emerald-400/30'
          : 'bg-amber-500/15 text-amber-300 border border-amber-400/30'
      }`;
    }

    if (todayMarketSentence) {
      todayMarketSentence.textContent = reg.regime_note || 'Kondisi pasar sedang dipantau.';
    }
  }

  // Update sparklines KPI
  const c1Hex = renderKpiDeltaBadge('kpiAllDelta', 'kpiAllVsLabel', kpis.avg_score_pct_change, kpis.avg_score_diff, kpis.prev_avg_smart_money_score !== undefined ? `Skor ${kpis.prev_avg_smart_money_score}` : null, false, true);
  renderKpiSparkline('kpiAllSpark', 'sparkGrad1', kpis.trend_avg_score, c1Hex);

  const c2Hex = renderKpiDeltaBadge('kpiMarkupDelta', 'kpiMarkupVsLabel', kpis.markup_pct_change, kpis.markup_diff, kpis.prev_markup_triggers, false, false);
  renderKpiSparkline('kpiMarkupSpark', 'sparkGrad2', kpis.trend_markup, c2Hex);

  const c3Hex = renderKpiDeltaBadge('kpiAccumDelta', 'kpiAccumVsLabel', kpis.accum_pct_change, kpis.accum_diff, kpis.prev_accum_triggers, false, false);
  renderKpiSparkline('kpiAccumSpark', 'sparkGrad3', kpis.trend_accum, c3Hex);

  const c4Hex = renderKpiDeltaBadge('kpiDistDelta', 'kpiDistVsLabel', kpis.dist_pct_change, kpis.dist_diff, kpis.prev_distribution_warnings, true, false);
  renderKpiSparkline('kpiDistSpark', 'sparkGrad4', kpis.trend_dist, c4Hex);

  // Highlight KPI card
  const mapCard = { ALL: 'kpiAll', MARKUP_BREAKOUT: 'kpiMarkup', ACCUM_ALL: 'kpiAccum', DISTRIBUTION_WARNING: 'kpiDist' };
  ['kpiAll', 'kpiMarkup', 'kpiAccum', 'kpiDist'].forEach((id) => {
    const cardEl = document.getElementById(id);
    if (cardEl) cardEl.classList.remove('active-filter');
  });
  if (mapCard[currentTrigger]) {
    const targetCard = document.getElementById(mapCard[currentTrigger]);
    if (targetCard) targetCard.classList.add('active-filter');
  }
}

function applyQuickFilter(triggerCode) {
  const triggerEl = document.getElementById('filterTrigger');
  if (triggerEl) triggerEl.value = triggerCode;
  loadScreenerData(false);
}

function changePage(delta) {
  const totalPages = Math.max(1, Math.ceil(currentStocks.length / PAGE_SIZE));
  currentPage = Math.min(totalPages, Math.max(1, currentPage + delta));
  renderScreenerTable(currentStocks);
}

// =====================================================================
// TABLE SCREENER (TAB JELAJAH)
// =====================================================================
function renderScreenerTable(stocks) {
  const tbody = document.getElementById('screenerTableBody');
  const mobileList = document.getElementById('screenerMobileList');
  if (!tbody && !mobileList) return;

  const totalPages = Math.max(1, Math.ceil(stocks.length / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = totalPages;

  const startIdx = (currentPage - 1) * PAGE_SIZE;
  const pageStocks = stocks.slice(startIdx, startIdx + PAGE_SIZE);

  const resultCountEl = document.getElementById('tableResultCount');
  if (resultCountEl) {
    resultCountEl.textContent = stocks.length
      ? `Menampilkan ${startIdx + 1}-${startIdx + pageStocks.length} dari ${stocks.length} saham`
      : 'Menampilkan 0 saham';
  }

  const pageInd = document.getElementById('pageIndicator');
  const btnPrev = document.getElementById('btnPrevPage');
  const btnNext = document.getElementById('btnNextPage');
  if (pageInd) pageInd.textContent = `Hal ${currentPage} / ${totalPages}`;
  if (btnPrev) btnPrev.disabled = currentPage <= 1;
  if (btnNext) btnNext.disabled = currentPage >= totalPages;

  if (!pageStocks.length) {
    const emptyHtml = `
      <tr>
        <td colspan="6" class="py-10 text-center text-slate-400">
          Tidak ada saham yang memenuhi filter kriteria saat ini. Coba longgarkan filter di atas.
        </td>
      </tr>
    `;
    if (tbody) tbody.innerHTML = emptyHtml;
    if (mobileList) {
      mobileList.innerHTML = `
        <div class="py-10 text-center text-xs text-slate-400 bg-white/5 dark:bg-slate-900/40 rounded-xl p-4 border border-white/5">
          Tidak ada saham yang memenuhi filter kriteria saat ini. Coba longgarkan filter di atas.
        </div>
      `;
    }
    return;
  }

  // 1. Render Desktop Table Rows (Tablet & Desktop >= md)
  if (tbody) {
    tbody.innerHTML = pageStocks
      .map((s) => {
        const safeTicker = escHtml(s.ticker);
        const safeSector = escHtml(s.sector);
        const safeSecCat = s.sector_category ? escHtml(s.sector_category) : '';
        const isSelected = s.ticker === selectedTicker;
        const starActive = isFavorite(s.ticker);
        const chgColor = s.pct_change >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-rose-500 dark:text-rose-400';

        return `
          <tr
            id="row-${safeTicker}"
            onclick="selectStock('${safeTicker}', true)"
            class="stock-row hover:bg-white/[0.05] transition-colors cursor-pointer ${isSelected ? 'selected-row' : ''}"
          >
            <!-- Ticker & Logo & Star -->
            <td class="py-3 pl-4 pr-2">
              <div class="flex items-center gap-2.5">
                <button
                  onclick="event.stopPropagation(); toggleFavorite('${safeTicker}', event)"
                  class="star-btn star-btn-${safeTicker} text-base leading-none transition ${starActive ? 'text-amber-400 drop-shadow-[0_0_8px_rgba(251,191,36,0.6)]' : 'text-slate-400 hover:text-amber-300'}"
                  title="Simpan ke Favorit"
                >
                  ${starActive ? '★' : '☆'}
                </button>
                ${getStockLogoImg(s.ticker, 'w-8 h-8')}
                <div>
                  <div class="flex items-center gap-1.5">
                    <div class="font-mono font-black text-sm text-slate-900 dark:text-white">${safeTicker}</div>
                    ${safeSecCat ? `<span class="text-[9px] font-sans font-bold px-1.5 py-0.2 rounded bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border border-slate-200 dark:border-slate-700 leading-none">${safeSecCat}</span>` : ''}
                  </div>
                  <div class="text-[10px] text-slate-400 truncate max-w-[120px]">${safeSector}</div>
                </div>
              </div>
            </td>

            <!-- Price -->
            <td class="py-3 px-2 text-right font-mono font-bold text-slate-900 dark:text-white text-xs whitespace-nowrap">
              ${fmtPrice(s.close)}
            </td>

            <!-- Change -->
            <td class="py-3 px-2 text-right font-mono text-xs font-bold ${chgColor} whitespace-nowrap">
              ${fmtSignPct(s.pct_change)}
            </td>

            <!-- Volume Spike Badge & Status Pantauan -->
            <td class="py-3 px-2 text-center font-mono">
              ${renderSignalTypeBadge(s)}
              <span class="inline-block px-2.5 py-0.5 rounded-full text-[10px] font-bold whitespace-nowrap ${s.vol_ratio >= 1.5 ? 'bg-orange-100 text-orange-800 border border-orange-200 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-400/35 shadow-[0_0_12px_rgba(245,158,11,0.15)]' : 'bg-slate-100 text-slate-700 border border-slate-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-400/30 shadow-[0_0_10px_rgba(16,185,129,0.12)]'}">
                ${s.vol_ratio >= 2.0 ? 'Vol Spike' : s.vol_ratio >= 1.2 ? 'High Vol' : 'Normal'} ${s.vol_ratio.toFixed(1)}x
              </span>
              ${s.tape_quality && s.tape_quality.code !== 'ORGANIC_FLOW' ? `<span class="block text-[8px] font-bold text-amber-800 bg-amber-100 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 mt-0.5 font-mono px-1 py-0.2 rounded whitespace-nowrap" title="${escHtml(s.tape_quality.reason)}">${s.tape_quality.code === 'SUSPICIOUS_CROSSING' ? 'Crossing' : s.tape_quality.code === 'UPTHRUST_DISTRIBUTION' ? 'Upthrust' : 'Thin'}</span>` : ''}
              ${s.tracker_status === 'WIN' ? '<span class="block text-[9px] font-bold text-emerald-800 bg-emerald-100 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50 mt-1 font-mono px-1 py-0.5 rounded whitespace-nowrap">WIN (TP1)</span>' : s.tracker_status === 'RUNNING' ? ((s.tracker_pnl_pct || 0) < 0 ? `<span class="block text-[9px] font-bold text-rose-800 bg-rose-100 border border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50 mt-1 font-mono px-1 py-0.5 rounded whitespace-nowrap">RUNNING ${(s.tracker_pnl_pct || 0) >= 0 ? '+' : ''}${s.tracker_pnl_pct || 0}%</span>` : `<span class="block text-[9px] font-bold text-emerald-800 bg-emerald-100 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50 mt-1 font-mono px-1 py-0.5 rounded whitespace-nowrap">RUNNING ${(s.tracker_pnl_pct || 0) >= 0 ? '+' : ''}${s.tracker_pnl_pct || 0}%</span>`) : s.tracker_status === 'WATCHLIST' ? '<span class="block text-[9px] font-bold text-blue-800 bg-blue-100 border border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800/50 mt-1 font-mono px-1 py-0.5 rounded whitespace-nowrap">WATCHLIST</span>' : ''}
            </td>

            <!-- Smart Money Score with Progress Bar -->
            <td class="py-3 px-2 text-right whitespace-nowrap">
              <div class="flex items-center justify-end gap-2">
                <span class="font-mono font-extrabold text-xs text-slate-900 dark:text-white">${escHtml(s.smart_money_score)}</span>
                <div class="w-16 bg-slate-200 dark:bg-white/[0.08] h-2 rounded-full overflow-hidden">
                  <div class="h-full bg-gradient-to-r from-emerald-500 to-teal-400 dark:from-emerald-400 dark:to-teal-300 rounded-full" style="width: ${Math.min(100, Math.max(0, Number(s.smart_money_score || 0)))}%"></div>
                </div>
              </div>
            </td>

            <!-- Profil VSA & VWAP 5H -->
            <td class="py-3 pl-2 pr-4 text-xs font-mono whitespace-nowrap">
              <div class="text-[11px] text-slate-600 dark:text-slate-300">
                <span class="lbl-vwap-text">${isExpertMode ? 'VWAP 5H' : 'Modal Bandar'}</span>: <span class="text-slate-900 dark:text-white font-bold">${fmtPrice(s.bandar_avg_buy)}</span> <span class="${s.diff_bandar_avg_pct >= 0 ? 'text-amber-500 dark:text-amber-300' : 'text-emerald-600 dark:text-emerald-400'} font-semibold">(${s.diff_bandar_avg_pct >= 0 ? '+' : ''}${s.diff_bandar_avg_pct.toFixed(1)}%)</span>
              </div>
              <div class="text-[10px] text-slate-500 dark:text-slate-400">
                CR: <span class="text-slate-800 dark:text-slate-200 font-semibold">${escHtml(s.closing_range_pct)}%</span> · <span class="lbl-val-text">${isExpertMode ? 'Turnover' : 'Transaksi'}</span>: <span class="text-slate-800 dark:text-slate-200">Rp ${escHtml(s.value_b_idr)} M</span>
              </div>
            </td>
          </tr>
        `;
      })
      .join('');
  }

  // 2. Render Mobile Card List View (Khusus Mobile < md: Rapi, Proporsional, Tanpa Teks Terpotong)
  if (mobileList) {
    mobileList.innerHTML = pageStocks
      .map((s) => {
        const safeTicker = escHtml(s.ticker);
        const safeSector = escHtml(s.sector);
        const safeSecCat = s.sector_category ? escHtml(s.sector_category) : '';
        const isSelected = s.ticker === selectedTicker;
        const starActive = isFavorite(s.ticker);
        const chgColor = s.pct_change >= 0 ? 'text-emerald-500 dark:text-emerald-400' : 'text-rose-500 dark:text-rose-400';

        // Broksum ratio pill
        const bdr = s.bdr_pct != null ? Number(s.bdr_pct) : null;
        let bdrPill = '';
        if (bdr !== null) {
          bdrPill = `<span class="px-1.5 py-0.2 rounded font-mono font-bold text-[9px] ${bdr >= 10 ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30' : bdr <= -10 ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30' : 'bg-slate-500/15 text-slate-600 dark:text-slate-300 border border-slate-500/20'}">BDR ${bdr >= 0 ? '+' : ''}${bdr.toFixed(1)}%</span>`;
        }

        return `
          <div
            id="mob-row-${safeTicker}"
            onclick="selectStock('${safeTicker}', true)"
            class="stock-row p-3 rounded-xl bg-white dark:bg-slate-900/70 border border-slate-200/80 dark:border-white/[0.08] shadow-xs hover:border-slate-300 dark:hover:border-white/20 transition cursor-pointer active:scale-[0.99] space-y-2 ${isSelected ? 'selected-row' : ''}"
          >
            <!-- Baris 1: Logo, Ticker, Sektor & Harga, % Perubahan -->
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2.5 min-w-0">
                <button
                  onclick="event.stopPropagation(); toggleFavorite('${safeTicker}', event)"
                  class="star-btn star-btn-${safeTicker} text-base leading-none transition shrink-0 ${starActive ? 'text-amber-400 drop-shadow-[0_0_8px_rgba(251,191,36,0.6)]' : 'text-slate-400 hover:text-amber-300'}"
                  title="Simpan ke Favorit"
                >
                  ${starActive ? '★' : '☆'}
                </button>
                ${getStockLogoImg(s.ticker, 'w-7 h-7 rounded-lg shrink-0')}
                <div class="min-w-0">
                  <div class="flex items-center gap-1.5 flex-wrap">
                    <span class="font-mono font-black text-sm text-slate-900 dark:text-white leading-tight">${safeTicker}</span>
                    ${safeSecCat ? `<span class="text-[9px] font-sans font-bold px-1.5 py-0.2 rounded bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border border-slate-200 dark:border-slate-700 leading-none">${safeSecCat}</span>` : ''}
                  </div>
                  <div class="text-[10px] text-slate-500 dark:text-slate-400 truncate max-w-[150px] leading-tight mt-0.5">${safeSector}</div>
                </div>
              </div>

              <!-- Kanan: Harga & % Change (Single Line) -->
              <div class="text-right shrink-0">
                <div class="font-mono font-bold text-sm text-slate-900 dark:text-white whitespace-nowrap">${fmtPrice(s.close)}</div>
                <div class="font-mono text-xs font-bold ${chgColor} whitespace-nowrap">${fmtSignPct(s.pct_change)}</div>
              </div>
            </div>

            <!-- Baris 2: Sinyal VSA & Skor Smart Money -->
            <div class="flex items-center justify-between gap-2 text-xs pt-1.5 border-t border-slate-100 dark:border-white/[0.04]">
              <!-- Sinyal & Vol Ratio Badges -->
              <div class="flex items-center gap-1.5 flex-wrap min-w-0">
                ${renderSignalTypeBadge(s)}
                <span class="inline-block px-2 py-0.5 rounded-full text-[10px] font-bold ${s.vol_ratio >= 1.5 ? 'bg-orange-100 text-orange-800 border border-orange-200 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-400/35' : 'bg-slate-100 text-slate-700 border border-slate-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-400/30'}">
                  ${s.vol_ratio >= 2.0 ? 'Vol Spike' : s.vol_ratio >= 1.2 ? 'High Vol' : 'Normal'} ${s.vol_ratio.toFixed(1)}x
                </span>
                ${bdrPill}
                ${s.tape_quality && s.tape_quality.code !== 'ORGANIC_FLOW' ? `<span class="text-[9px] font-bold text-amber-800 bg-amber-100 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 font-mono px-1.5 py-0.2 rounded" title="${escHtml(s.tape_quality.reason)}">${s.tape_quality.code === 'SUSPICIOUS_CROSSING' ? 'Crossing' : s.tape_quality.code === 'UPTHRUST_DISTRIBUTION' ? 'Upthrust' : 'Thin'}</span>` : ''}
                ${s.tracker_status === 'WIN' ? '<span class="text-[9px] font-bold text-emerald-800 bg-emerald-100 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 px-1.5 py-0.2 rounded font-mono">WIN</span>' : s.tracker_status === 'RUNNING' ? `<span class="text-[9px] font-bold text-emerald-800 bg-emerald-100 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 px-1.5 py-0.2 rounded font-mono">RUNNING ${(s.tracker_pnl_pct || 0) >= 0 ? '+' : ''}${s.tracker_pnl_pct || 0}%</span>` : s.tracker_status === 'WATCHLIST' ? '<span class="text-[9px] font-bold text-blue-800 bg-blue-100 border border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 px-1.5 py-0.2 rounded font-mono">WATCHLIST</span>' : ''}
              </div>

              <!-- Skor Smart Money -->
              <div class="flex items-center gap-1.5 shrink-0">
                <span class="text-[10px] text-slate-500 dark:text-slate-400 font-medium">Skor:</span>
                <span class="font-mono font-extrabold text-[11px] px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30">${escHtml(s.smart_money_score)}</span>
              </div>
            </div>

            <!-- Baris 3: Modal Bandar (VWAP) & Turnover Transaksi -->
            <div class="flex items-center justify-between text-[10px] font-mono text-slate-500 dark:text-slate-400 pt-0.5">
              <div>
                <span>${isExpertMode ? 'VWAP 5H' : 'Modal Bandar'}:</span>
                <span class="text-slate-900 dark:text-white font-bold">${fmtPrice(s.bandar_avg_buy)}</span>
                <span class="${s.diff_bandar_avg_pct >= 0 ? 'text-amber-500 dark:text-amber-300' : 'text-emerald-600 dark:text-emerald-400'} font-semibold">(${s.diff_bandar_avg_pct >= 0 ? '+' : ''}${s.diff_bandar_avg_pct.toFixed(1)}%)</span>
              </div>
              <div>
                <span>${isExpertMode ? 'Turnover' : 'Tx'}:</span>
                <span class="text-slate-900 dark:text-white font-semibold">Rp ${escHtml(s.value_b_idr)} M</span>
              </div>
            </div>
          </div>
        `;
      })
      .join('');
  }
}

// =====================================================================
// INSPECTOR PANEL & DETAIL SAHAM
// =====================================================================

const CATALYST_STYLE = {
  VALID_CATALYST: 'bg-emerald-500/15 text-emerald-300 border-emerald-400/30',
  ABSORBED: 'bg-emerald-500/15 text-emerald-300 border-emerald-400/30',
  SELL_ON_NEWS: 'bg-rose-500/15 text-rose-300 border-rose-400/30',
  NEGATIVE_CONFIRMED: 'bg-rose-500/15 text-rose-300 border-rose-400/30',
  UNCONFIRMED: 'bg-amber-500/15 text-amber-300 border-amber-400/30',
  WAIT_CONFIRM: 'bg-amber-500/15 text-amber-300 border-amber-400/30',
  NEGATIVE_UNCONFIRMED: 'bg-amber-500/15 text-amber-300 border-amber-400/30',
};

async function loadStockNewsCatalyst(ticker) {
  const badge = document.getElementById('snc-verdict');
  if (!badge) return;
  const factorsEl = document.getElementById('snc-factors');
  const noteEl = document.getElementById('snc-note');
  const newsEl = document.getElementById('snc-news');
  badge.textContent = 'Memuat...';
  badge.className = 'text-[10px] font-mono font-bold px-2 py-0.5 rounded-lg border bg-slate-700/40 text-slate-300 border-white/10';
  try {
    const res = await fetch(`/api/stock/${encodeURIComponent(ticker)}/news-catalyst?_t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error('gagal');
    const d = await res.json();
    if (selectedTicker !== ticker) return; // pengguna sudah pindah emiten
    const v = d.verdict || {};
    const cls = CATALYST_STYLE[v.code] || 'bg-slate-700/40 text-slate-300 border-white/10';
    badge.className = `text-[10px] font-mono font-bold px-2 py-0.5 rounded-lg border ${cls}`;
    badge.textContent = d.has_news ? `${v.label} (Skor ${v.base_score} → ${v.adjusted_score})` : 'Belum Ada Berita Terkait';
    factorsEl.innerHTML = (v.factors || []).map(f => `
      <div class="px-2 py-1 rounded-md border ${f.ok ? 'border-emerald-500/30 text-emerald-300 bg-emerald-500/10' : 'border-white/10 text-slate-400 bg-slate-900/30'}">
        ${f.ok ? 'Terpenuhi' : 'Belum'}: ${escHtml(f.label)}
      </div>`).join('');
    const factorsToggle = document.getElementById('snc-factors-toggle');
    const passedFactors = (v.factors || []).filter(f => f.ok).length;
    if (factorsToggle) factorsToggle.innerHTML = `<span>${passedFactors} dari ${(v.factors || []).length} kriteria terpenuhi</span><span class="text-[9px]">▾</span>`;
    noteEl.textContent = d.has_news ? v.note : '';
    newsEl.innerHTML = (d.news || []).map(n => `
      <div class="text-[11px] text-slate-400">
        <span class="font-mono text-[10px]">${escHtml(n.source || '')} · ${escHtml(n.published_at || '')}</span>
        ${n.link ? `<a href="${escHtml(n.link)}" target="_blank" rel="noopener noreferrer" class="block text-slate-200 hover:text-white underline-offset-2 hover:underline">${escHtml(n.title || '')}</a>` : `<span class="block text-slate-200">${escHtml(n.title || '')}</span>`}
      </div>`).join('');
    if (selectedStockDetail && selectedStockDetail.ticker === ticker) {
      renderStockBroksum(selectedStockDetail);
    }
  } catch (e) {
    badge.textContent = 'Data berita tidak tersedia';
    if (factorsEl) factorsEl.innerHTML = '';
    if (noteEl) noteEl.textContent = '';
    if (newsEl) newsEl.innerHTML = '';
    if (selectedStockDetail && selectedStockDetail.ticker === ticker) {
      renderStockBroksum(selectedStockDetail);
    }
  }
}

function renderStockBroksum(d) {
  const container = document.getElementById('snc-broksum');
  if (!container) return;

  if (!d) {
    container.innerHTML = '';
    return;
  }

  const bdr = d.bdr_pct != null ? Number(d.bdr_pct) : (d.broker_analysis && d.broker_analysis.bdr != null ? Number(d.broker_analysis.bdr) : null);
  const rawBuyers = d.top_buyers_list && d.top_buyers_list.length ? d.top_buyers_list : (d.top_buyers ? d.top_buyers.split(',').map(s => s.trim()).filter(Boolean) : []);
  const topBuyers = rawBuyers.map(s => String(s).trim().toUpperCase()).filter(s => /^[A-Z]{2}$/.test(s));

  const rawSellers = d.top_sellers_list && d.top_sellers_list.length ? d.top_sellers_list : (d.top_sellers ? d.top_sellers.split(',').map(s => s.trim()).filter(Boolean) : []);
  const topSellers = rawSellers.map(s => String(s).trim().toUpperCase()).filter(s => /^[A-Z]{2}$/.test(s));

  const bandarAvg = d.bandar_avg_buy || (d.broker_analysis ? d.broker_analysis.bandar_avg : null);
  const isRetailTrap = Boolean(d.retail_trap || (d.broker_analysis && d.broker_analysis.retail_trap));
  const hasRealBrokerSummary = Boolean(d.has_real_broker_summary || d.has_broker_summary);
  const hasBrokData = hasRealBrokerSummary && (topBuyers.length > 0 || topSellers.length > 0 || bdr !== null);

  if (!hasBrokData) {
    container.innerHTML = `
      <div class="p-2.5 rounded-xl bg-slate-100/70 dark:bg-slate-800/40 border border-slate-200 dark:border-white/[0.08] flex items-center justify-between gap-3 shadow-xs">
        <div class="flex items-center gap-2">
          <span class="w-2 h-2 rounded-full bg-slate-400 shrink-0"></span>
          <div class="text-[11px] text-slate-600 dark:text-slate-400 leading-snug">
            <span class="font-semibold text-slate-900 dark:text-white">Broker Summary:</span> Belum dimuat untuk ${escHtml(d.ticker)}
            <div class="text-[10px] text-slate-500 mt-0.5">Analisa Pribadi: Klik tombol untuk cek langsung via API Invezgo</div>
          </div>
        </div>
        <button onclick="fetchBrokerSummaryForSelected('${escHtml(d.ticker)}', true)" class="text-[10px] px-2.5 py-1.5 rounded-lg bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30 font-semibold transition shrink-0 whitespace-nowrap active:scale-95 flex items-center gap-1">
          <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
          <span>Cek Broksum</span>
        </button>
      </div>
    `;
    return;
  }

  // Status Badge
  let statusBadgeHtml = '';
  if (isRetailTrap) {
    statusBadgeHtml = `<span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/30">DISTRIBUSI / RITEL TRAP</span>`;
  } else if (bdr !== null && bdr >= 25.0) {
    statusBadgeHtml = `<span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30">AKUMULASI BESAR (+${bdr.toFixed(1)}%)</span>`;
  } else if (bdr !== null && bdr >= 10.0) {
    statusBadgeHtml = `<span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30">AKUMULASI (+${bdr.toFixed(1)}%)</span>`;
  } else if (bdr !== null && bdr <= -15.0) {
    statusBadgeHtml = `<span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/30">DISTRIBUSI (${bdr.toFixed(1)}%)</span>`;
  } else {
    const bdrText = bdr !== null ? `${bdr >= 0 ? '+' : ''}${bdr.toFixed(1)}%` : '-';
    statusBadgeHtml = `<span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-slate-500/15 text-slate-700 dark:text-slate-300 border border-slate-500/30">NETRAL (${bdrText})</span>`;
  }

  const INST_BROKERS = new Set(["AK", "BK", "ZP", "KZ", "RX", "YU", "CC", "CS", "MG", "DX", "LG", "OD"]);
  const RETAIL_BROKERS = new Set(["YP", "PD", "XC", "XL", "KK", "NI", "SQ", "BQ"]);

  const buyersPillsHtml = topBuyers.length
    ? topBuyers.map(code => {
        const c = String(code).toUpperCase().trim();
        const isInst = INST_BROKERS.has(c);
        const isRtl = RETAIL_BROKERS.has(c);
        const tag = isInst ? '<span class="text-[8px] opacity-75 font-normal">Inst</span>' : isRtl ? '<span class="text-[8px] opacity-75 font-normal">Rtl</span>' : '';
        return `<span class="px-1.5 py-0.5 rounded font-mono font-bold text-[11px] bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/25 inline-flex items-center gap-1">${escHtml(c)}${tag}</span>`;
      }).join(' ')
    : '<span class="text-slate-400 text-[10px]">-</span>';

  const sellersPillsHtml = topSellers.length
    ? topSellers.map(code => {
        const c = String(code).toUpperCase().trim();
        const isInst = INST_BROKERS.has(c);
        const isRtl = RETAIL_BROKERS.has(c);
        const tag = isInst ? '<span class="text-[8px] opacity-75 font-normal">Inst</span>' : isRtl ? '<span class="text-[8px] opacity-75 font-normal">Rtl</span>' : '';
        return `<span class="px-1.5 py-0.5 rounded font-mono font-bold text-[11px] bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/25 inline-flex items-center gap-1">${escHtml(c)}${tag}</span>`;
      }).join(' ')
    : '<span class="text-slate-400 text-[10px]">-</span>';

  // Distance from Bandar Avg
  let bandarDiffHtml = '';
  if (bandarAvg && d.close) {
    const diff = Number(((d.close - bandarAvg) / bandarAvg * 100).toFixed(1));
    const isDisc = diff < 0;
    bandarDiffHtml = `<span class="text-[10px] font-mono ${isDisc ? 'text-teal-600 dark:text-teal-400' : 'text-emerald-600 dark:text-emerald-400'} font-semibold">(${diff >= 0 ? '+' : ''}${diff}% vs Close)</span>`;
  }

  // Verdict note
  let verdictNote = '';
  if (isRetailTrap) {
    verdictNote = 'Awas Ritel Trap: Sekuritas ritel menampung jualan institusi/asing. Hindari spekulasi atau tunggu konfirmasi bantalan support.';
  } else if (bdr !== null && bdr >= 15.0) {
    verdictNote = 'Smart money institusi mengakumulasi bersih secara masif. Katalis kuat yang mengonfirmasi zona antre support.';
  } else if (bdr !== null && bdr >= 5.0) {
    verdictNote = 'Terdeteksi akumulasi awal broker institusi. Disiplin antre di harga support rencana eksekusi.';
  } else {
    verdictNote = 'Aktivitas broker seimbang. Keputusan tetap disiplin mengacu pada harga support dan batasan risiko trading plan.';
  }

  container.innerHTML = `
    <div class="p-2.5 rounded-xl bg-slate-100/80 dark:bg-slate-800/60 border border-slate-200 dark:border-white/[0.08] space-y-2 shadow-xs">
      <!-- Header Broksum -->
      <div class="flex items-center justify-between gap-2">
        <div class="flex items-center gap-1.5 flex-wrap">
          <span class="text-[11px] font-bold text-slate-900 dark:text-white tracking-wide">Broker Summary (Bandarmology)</span>
          <span class="text-[9px] font-mono px-1.5 py-0.2 rounded text-slate-500 dark:text-slate-400 bg-slate-200 dark:bg-white/5">Top 3</span>
          ${d.broker_date ? `<span class="text-[9px] font-mono text-slate-500 dark:text-slate-400">(${escHtml(d.broker_date)})</span>` : ''}
        </div>
        <div class="flex items-center gap-1.5 shrink-0">
          ${statusBadgeHtml}
          <button onclick="fetchBrokerSummaryForSelected('${escHtml(d.ticker)}', true)" title="Tarik data terbaru langsung dari API Invezgo untuk analisa pribadi" class="text-[10px] px-2 py-0.5 rounded-md bg-indigo-500/15 hover:bg-indigo-500/25 text-indigo-600 dark:text-indigo-400 border border-indigo-500/30 font-semibold transition active:scale-95 flex items-center gap-1 shrink-0">
            <span>↻</span> <span class="hidden sm:inline">Cek API</span>
          </button>
        </div>
      </div>

      <!-- Top 3 Buyer vs Seller Grid -->
      <div class="grid grid-cols-2 gap-2 text-xs">
        <div class="p-2 rounded-lg bg-white dark:bg-slate-900/50 border border-emerald-500/20">
          <div class="text-[10px] text-emerald-600 dark:text-emerald-400 font-semibold mb-1 flex items-center justify-between">
            <span>Top 3 Buyer</span>
            <span class="font-mono text-[9px] text-emerald-500/70">Akumulasi</span>
          </div>
          <div class="flex items-center gap-1 flex-wrap">
            ${buyersPillsHtml}
          </div>
        </div>

        <div class="p-2 rounded-lg bg-white dark:bg-slate-900/50 border border-rose-500/20">
          <div class="text-[10px] text-rose-600 dark:text-rose-400 font-semibold mb-1 flex items-center justify-between">
            <span>Top 3 Seller</span>
            <span class="font-mono text-[9px] text-rose-500/70">Distribusi</span>
          </div>
          <div class="flex items-center gap-1 flex-wrap">
            ${sellersPillsHtml}
          </div>
        </div>
      </div>

      <!-- Modal Bandar & BDR Ratio Row -->
      <div class="flex items-center justify-between text-[11px] px-0.5 text-slate-600 dark:text-slate-300">
        <div class="flex items-center gap-1.5 flex-wrap">
          <span class="text-slate-400 text-[10px]">Modal Bandar:</span>
          <span class="font-mono font-bold text-slate-900 dark:text-white">${bandarAvg ? fmtPrice(bandarAvg) : '-'}</span>
          ${bandarDiffHtml}
        </div>
        <div class="font-mono font-semibold text-[10px] text-slate-500 dark:text-slate-400 whitespace-nowrap">
          BDR: <span class="${bdr !== null && bdr >= 10 ? 'text-emerald-500 font-bold' : bdr !== null && bdr <= -10 ? 'text-rose-500 font-bold' : 'text-slate-300'}">${bdr !== null ? (bdr >= 0 ? '+' : '') + bdr.toFixed(1) + '%' : '-'}</span>
        </div>
      </div>

      <p class="text-[10px] text-slate-500 dark:text-slate-400 leading-tight pt-0.5 border-t border-slate-200/50 dark:border-white/[0.04]">
        ${escHtml(verdictNote)}
      </p>
    </div>
  `;
}

window.fetchBrokerSummaryForSelected = async function(ticker, force = true) {
  const btns = document.querySelectorAll(`button[onclick*="fetchBrokerSummaryForSelected('${ticker}'"]`);
  btns.forEach(b => {
    b.disabled = true;
    b.dataset.origHtml = b.innerHTML;
    b.innerHTML = '<span class="inline-block animate-spin mr-1">⌛</span> Mengambil...';
  });

  try {
    const res = await fetch(`/api/stock/${encodeURIComponent(ticker)}/fetch-broker?force=${force ? 'true' : 'false'}`, { method: 'POST' });
    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || 'Gagal mengambil data broker');
    }
    const updated = await res.json();
    selectedStockDetail = updated;
    renderInspectorPanel(updated);
    renderStockBroksum(updated);
    showToast(`Data Invezgo #${ticker} berhasil diambil langsung!`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
    btns.forEach(b => {
      b.disabled = false;
      if (b.dataset.origHtml) b.innerHTML = b.dataset.origHtml;
    });
  }
};

async function selectStock(ticker, isUserClick = false, scrollToTradingPlan = false) {
  selectedTicker = ticker;

  document.querySelectorAll('.stock-row').forEach((el) => el.classList.remove('selected-row'));
  const activeRow = document.getElementById(`row-${ticker}`);
  if (activeRow) activeRow.classList.add('selected-row');
  const activeMobRow = document.getElementById(`mob-row-${ticker}`);
  if (activeMobRow) activeMobRow.classList.add('selected-row');

  try {
    const res = await fetch(`/api/stock/${encodeURIComponent(ticker)}?_t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) throw new Error(`Gagal memuat detail ${ticker}`);
    selectedStockDetail = await res.json();
    renderInspectorPanel(selectedStockDetail);
    loadStockNewsCatalyst(ticker);

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
    } else if (isUserClick && window.innerWidth < 1280) {
      // Pada layar mobile/tablet, otomatis gulir halus ke Inspector HANYA jika pengguna sengaja mengklik saham
      setTimeout(() => {
        const inspector = document.getElementById('inspectorPanel');
        if (inspector) {
          inspector.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
      }, 120);
    }
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function renderInspectorPanel(d) {
  const logoEl = document.getElementById('inspLogoContainer');
  if (logoEl) logoEl.innerHTML = getStockLogoImg(d.ticker, 'w-10 h-10');

  const tickerEl = document.getElementById('inspTicker');
  if (tickerEl) tickerEl.textContent = d.ticker;

  const badgeEl = document.getElementById('inspTriggerBadge');
  if (badgeEl) {
    badgeEl.textContent = d.trigger_label;
    badgeEl.className = `text-[11px] font-semibold px-2.5 py-0.5 rounded-full ${getTriggerBadgeClass(d.trigger_type)}`;
  }

  const sectorEl = document.getElementById('inspSector');
  if (sectorEl) {
    const secCat = d.sector_category ? `${d.sector_category} • ` : '';
    sectorEl.textContent = `${secCat}${d.sector} • Update: ${d.date}`;
  }

  const tapeBadge = document.getElementById('inspTapeBadge');
  if (tapeBadge) {
    if (d.tape_quality) {
      tapeBadge.classList.remove('hidden');
      tapeBadge.textContent = d.tape_quality.label;
      if (d.tape_quality.is_organic) {
        tapeBadge.className = 'text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50';
      } else if (d.tape_quality.code === 'SUSPICIOUS_CROSSING') {
        tapeBadge.className = 'text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-800/50';
      } else {
        tapeBadge.className = 'text-[10px] font-semibold px-2 py-0.5 rounded-full bg-rose-100 text-rose-800 border border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50';
      }
      tapeBadge.title = d.tape_quality.reason || '';
    } else {
      tapeBadge.classList.add('hidden');
    }
  }

  const priceEl = document.getElementById('inspPrice');
  if (priceEl) priceEl.textContent = fmtPrice(d.close);

  const chgEl = document.getElementById('inspPctChange');
  if (chgEl) {
    chgEl.textContent = `${fmtSignPct(d.pct_change)} (${fmtNumber(d.volume_lot)} Lot)`;
    chgEl.className = `text-xs font-mono font-semibold ${d.pct_change >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;
  }

  // 5-Pillar Scores
  const totalScoreBadge = document.getElementById('inspTotalScoreBadge');
  if (totalScoreBadge) totalScoreBadge.textContent = `Score: ${d.smart_money_score} / 100`;

  const p1 = document.getElementById('p1Score'); if (p1) p1.textContent = `${d.vsa_score}/25`;
  const p2 = document.getElementById('p2Score'); if (p2) p2.textContent = `${d.bandar_score}/20`;
  const p3 = document.getElementById('p3Score'); if (p3) p3.textContent = `${d.ticket_score}/15`;
  const p4 = document.getElementById('p4Score'); if (p4) p4.textContent = `${d.foreign_score}/15`;
  const p5 = document.getElementById('p5Score'); if (p5) p5.textContent = `${d.structure_score}/25`;

  const bar1 = document.getElementById('p1Bar');
  const bar2 = document.getElementById('p2Bar');
  const bar3 = document.getElementById('p3Bar');
  const bar4 = document.getElementById('p4Bar');
  const bar5 = document.getElementById('p5Bar');
  if (bar1) bar1.style.width = `${Math.min(100, Math.round((d.vsa_score / 25) * 100))}%`;
  if (bar2) bar2.style.width = `${Math.min(100, Math.round((d.bandar_score / 20) * 100))}%`;
  if (bar3) bar3.style.width = `${Math.min(100, Math.round((d.ticket_score / 15) * 100))}%`;
  if (bar4) bar4.style.width = `${Math.min(100, Math.round((d.foreign_score / 15) * 100))}%`;
  if (bar5) bar5.style.width = `${Math.min(100, Math.round((d.structure_score / 25) * 100))}%`;

  // Auto Trading Plan
  const plan = d.trading_plan;
  const biasEl = document.getElementById('planActionBias');
  const pel = document.getElementById('planEntryLabel');
  const pez = document.getElementById('planEntryZone');
  const slEl = document.getElementById('planStopLoss');
  const tgtEl = document.getElementById('planTargets');
  const tgt2El = document.getElementById('planTarget2');
  const pr = document.getElementById('planRationale');
  const btnWatch = document.getElementById('btnAddToWatchlist');

  if (plan) {
    const trackerSt = d.tracker_status || plan.status;
    if (biasEl) {
      biasEl.textContent = plan.action_bias;
      if (trackerSt === 'WIN') {
        biasEl.className = 'text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-lg bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50';
      } else if (trackerSt === 'RUNNING') {
        const isLoss = (plan.pnl_pct || 0) < 0;
        if (isLoss) {
          biasEl.className = 'text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-lg bg-rose-100 text-rose-800 border border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50';
        } else {
          biasEl.className = 'text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-lg bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50';
        }
      } else if (trackerSt === 'LOSS' || d.trigger_type === 'DISTRIBUTION_WARNING') {
        biasEl.className = 'text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-lg bg-rose-100 text-rose-800 border border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50';
      } else if (trackerSt === 'WATCHLIST') {
        biasEl.className = 'text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-lg bg-blue-100 text-blue-800 border border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800/50';
      } else {
        biasEl.className = 'text-[10px] font-mono font-bold px-2.5 py-0.5 rounded-lg bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50';
      }
    }

    if (pel) {
      if (trackerSt === 'WIN') {
        pel.textContent = 'Harga Beli (Selesai)';
      } else if (trackerSt === 'RUNNING') {
        pel.textContent = 'Harga Beli (Aktif)';
      } else if (trackerSt === 'WATCHLIST') {
        pel.textContent = plan.support_label ? `Antre Entry (${plan.support_label})` : 'Harga Beli (Antre Support)';
      } else {
        pel.textContent = plan.support_label ? `Harga Beli (${plan.support_label})` : 'Harga Beli (Support)';
      }
    }

    if (pez) {
      const targetBuy = plan.entry_price || plan.entry_high || plan.entry_low;
      if (trackerSt === 'WIN') {
        pez.innerHTML = `<span class="text-amber-300 font-bold">${fmtPrice(targetBuy)}</span>`;
      } else if (trackerSt === 'RUNNING') {
        const isLoss = (plan.pnl_pct || 0) < 0;
        const col = isLoss ? 'text-rose-300' : 'text-emerald-300';
        pez.innerHTML = `<span class="${col} font-bold">${fmtPrice(targetBuy)}</span>`;
      } else {
        pez.innerHTML = `<span class="text-white font-bold">${fmtPrice(targetBuy)}</span>`;
      }
    }

    if (slEl) slEl.textContent = `${fmtPrice(plan.stop_loss)} (${plan.stop_loss_pct != null ? plan.stop_loss_pct : -4}%)`;
    if (tgtEl) tgtEl.textContent = `${fmtPrice(plan.target_1)} (+${plan.target_1_pct != null ? plan.target_1_pct : 4}%)`;

    if (tgt2El) {
      if (plan.target_2 && plan.target_2 > 0) {
        tgt2El.textContent = `${fmtPrice(plan.target_2)} (+${plan.target_2_pct != null ? plan.target_2_pct : 7}%)`;
      } else {
        tgt2El.textContent = '-';
      }
    }

    if (pr) {
      const rr = plan.risk_reward ? ` (R:R = ${plan.risk_reward})` : '';
      pr.textContent = `${plan.rationale || ''}${rr}`;
    }

    // Wire Jejak Broksum di Trading Plan
    const planBroksumSec = document.getElementById('planBroksumSection');
    const planTopBuyersEl = document.getElementById('planTopBuyers');
    const planBandarAvgEl = document.getElementById('planBandarAvg');
    const planBroksumBadge = document.getElementById('planBroksumBadge');

    if (planBroksumSec && planTopBuyersEl && planBandarAvgEl && planBroksumBadge) {
      const rawBuyers = d.top_buyers_list && d.top_buyers_list.length
        ? d.top_buyers_list
        : (d.top_buyers ? d.top_buyers.split(',').map(s => s.trim()).filter(Boolean) : []);
      const validBuyers = rawBuyers.map(s => String(s).trim().toUpperCase()).filter(s => /^[A-Z]{2}$/.test(s));

      const bandarAvg = d.bandar_avg_buy || (plan && plan.bandar_avg_buy) || (d.broker_analysis && d.broker_analysis.bandar_avg);
      const bdr = d.bdr_pct != null ? Number(d.bdr_pct) : (d.broker_analysis && d.broker_analysis.bdr != null ? Number(d.broker_analysis.bdr) : null);
      const isRetailTrap = Boolean(d.retail_trap || (d.broker_analysis && d.broker_analysis.retail_trap));

      const hasRealBrokerSummary = Boolean(d.has_real_broker_summary || d.has_broker_summary);
      if (hasRealBrokerSummary && (validBuyers.length > 0 || bdr !== null)) {
        const INST_BROKERS = new Set(["AK", "BK", "ZP", "KZ", "RX", "YU", "CC", "CS", "MG", "DX", "LG", "OD"]);
        const buyersFormatted = validBuyers.map(b => {
          const isInst = INST_BROKERS.has(b);
          return isInst
            ? `<span class="px-1.5 py-0.5 rounded font-mono font-bold text-[11px] bg-emerald-500/20 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30">${b}</span>`
            : `<span class="px-1.5 py-0.5 rounded font-mono font-bold text-[11px] bg-slate-200 dark:bg-white/10 text-slate-700 dark:text-slate-300 border border-slate-300 dark:border-white/10">${b}</span>`;
        }).join(' ');

        planTopBuyersEl.innerHTML = buyersFormatted || '-';

        if (bandarAvg) {
          const diff = d.close ? Number(((d.close - bandarAvg) / bandarAvg * 100).toFixed(1)) : null;
          const diffText = diff !== null ? ` <span class="text-[10px] font-normal ${diff <= 0 ? 'text-teal-400' : 'text-emerald-400'}">(${diff >= 0 ? '+' : ''}${diff}%)</span>` : '';
          planBandarAvgEl.innerHTML = `${fmtPrice(bandarAvg)}${diffText}`;
        } else {
          planBandarAvgEl.textContent = '-';
        }

        if (isRetailTrap) {
          planBroksumBadge.textContent = 'RITEL TRAP';
          planBroksumBadge.className = 'font-mono font-bold text-[10px] px-2 py-0.5 rounded-md bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/30';
        } else if (bdr !== null && bdr >= 10) {
          planBroksumBadge.textContent = `BDR +${bdr.toFixed(1)}% (AKUMULASI)`;
          planBroksumBadge.className = 'font-mono font-bold text-[10px] px-2 py-0.5 rounded-md bg-emerald-500/15 text-emerald-700 dark:text-emerald-300 border border-emerald-500/30';
        } else if (bdr !== null && bdr < 0) {
          planBroksumBadge.textContent = `BDR ${bdr.toFixed(1)}% (DISTRIBUSI)`;
          planBroksumBadge.className = 'font-mono font-bold text-[10px] px-2 py-0.5 rounded-md bg-rose-500/15 text-rose-700 dark:text-rose-300 border border-rose-500/30';
        } else {
          planBroksumBadge.textContent = bdr !== null ? `BDR +${bdr.toFixed(1)}%` : 'TERKONFIRMASI';
          planBroksumBadge.className = 'font-mono font-bold text-[10px] px-2 py-0.5 rounded-md bg-slate-500/15 text-slate-700 dark:text-slate-300 border border-slate-500/30';
        }
      } else {
        planTopBuyersEl.innerHTML = `<span class="text-slate-400 font-normal italic">Belum dimuat</span> <button onclick="fetchBrokerSummaryForSelected('${escHtml(d.ticker)}', true)" class="ml-1 text-[9px] px-1.5 py-0.5 rounded bg-emerald-600/20 text-emerald-600 dark:text-emerald-400 hover:bg-emerald-600/30 font-semibold">Cek Broksum</button>`;
        planBandarAvgEl.textContent = '-';
        planBroksumBadge.textContent = 'DATA BELUM ADA';
        planBroksumBadge.className = 'font-mono font-bold text-[10px] px-2 py-0.5 rounded-md bg-slate-500/10 text-slate-500 dark:text-slate-400 border border-slate-500/20';
      }
    }

    if (btnWatch) {
      if (trackerSt === 'WIN') {
        btnWatch.innerHTML = `
          <span class="neon-icon-badge">
            <svg viewBox="0 0 24 24" class="w-3.5 h-3.5" fill="none" stroke="#090d16" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M6 9H4.5a2.5 2.5 0 0 1 0-5H6M18 9h1.5a2.5 2.5 0 0 0 0-5H18M4 22h16M10 14.66V17c0 .55-.45 1-1 1H8c-.55 0-1 .45-1 1v3h10v-3c0-.55-.45-1-1-1h-1c-.55 0-1-.45-1-1v-2.34M7 4h10v6a5 5 0 0 1-10 0V4z"/>
            </svg>
          </span>
          <span>Target 1 Selesai</span>
        `;
        btnWatch.className = 'liquid-glass-btn neon-amber active py-2 px-3 justify-center active:scale-95 w-full';
        btnWatch.onclick = () => switchMainTab('watchlist');
        btnWatch.title = 'Sinyal telah mencapai Target 1 di Pantauan (Klik untuk melihat)';
      } else if (trackerSt === 'RUNNING') {
        const isLoss = (plan.pnl_pct || 0) < 0;
        btnWatch.innerHTML = `
          <span class="neon-icon-badge">
            <svg viewBox="0 0 24 24" class="w-3.5 h-3.5" fill="none" stroke="#090d16" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09zM12 15l-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/>
            </svg>
          </span>
          <span>Posisi Aktif (${(Number(plan.pnl_pct) || 0) >= 0 ? '+' : ''}${(Number(plan.pnl_pct) || 0).toFixed(1)}%)</span>
        `;
        btnWatch.className = isLoss
          ? 'liquid-glass-btn neon-rose active py-2 px-3 justify-center active:scale-95 w-full'
          : 'liquid-glass-btn neon-emerald active py-2 px-3 justify-center active:scale-95 w-full';
        btnWatch.onclick = () => switchMainTab('watchlist');
        btnWatch.title = 'Saham sedang dalam posisi berjalan di Pantauan (Klik untuk melihat)';
      } else if (trackerSt === 'WATCHLIST') {
        btnWatch.innerHTML = `
          <span class="neon-icon-badge">
            <svg viewBox="0 0 24 24" class="w-3.5 h-3.5" fill="none" stroke="#090d16" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
            </svg>
          </span>
          <span>Di Watchlist (Antre)</span>
        `;
        btnWatch.className = 'liquid-glass-btn neon-blue active py-2 px-3 justify-center active:scale-95 w-full';
        btnWatch.onclick = () => switchMainTab('watchlist');
        btnWatch.title = 'Sudah masuk antrean beli Watchlist (Klik untuk melihat)';
      } else {
        btnWatch.innerHTML = `
          <span class="neon-icon-badge">
            <svg viewBox="0 0 24 24" class="w-3.5 h-3.5" fill="none" stroke="#090d16" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
              <line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>
            </svg>
          </span>
          <span>Masuk Watchlist</span>
        `;
        btnWatch.className = 'liquid-glass-btn neon-blue py-2 px-3 justify-center active:scale-95 w-full';
        btnWatch.onclick = addToWatchlist;
        btnWatch.title = 'Masukkan saham ini ke Watchlist Tracker';
      }
    }
  }

  // Checklist 5 Pilar
  const checklistEl = document.getElementById('inspChecklist');
  if (checklistEl) {
    checklistEl.innerHTML = (d.checklist || [])
      .map((item) => {
        const icon =
          item.status === 'pass'
            ? '<span class="w-5 h-5 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-400/30 flex items-center justify-center font-bold text-xs">✓</span>'
            : item.status === 'warn'
            ? '<span class="w-5 h-5 rounded-full bg-amber-500/20 text-amber-400 border border-amber-400/30 flex items-center justify-center font-bold text-xs">!</span>'
            : '<span class="w-5 h-5 rounded-full bg-rose-500/20 text-rose-400 border border-rose-400/30 flex items-center justify-center font-bold text-xs">✕</span>';

        return `
          <div class="p-2.5 rounded-xl bg-slate-50 border border-slate-200 dark:bg-slate-800/60 dark:border-white/[0.06] transition space-y-1">
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2">
                ${icon}
                <span class="text-xs font-semibold text-slate-900 dark:text-white">${escHtml(item.title)}</span>
              </div>
              <span class="font-mono text-[11px] font-semibold text-emerald-800 bg-emerald-100 border border-emerald-200 dark:text-emerald-300 dark:bg-white/[0.06] dark:border-white/10 px-2 py-0.5 rounded-md">${escHtml(item.metric)}</span>
            </div>
            <p class="text-[11px] text-slate-600 dark:text-slate-400 pl-7 leading-relaxed">${escHtml(item.detail)}</p>
          </div>
        `;
      })
      .join('');
  }

  renderInspectorChart(d);
  renderStockBroksum(d);
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
    if (!btn) return;
    if (key === tabName) {
      btn.className = 'px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-emerald-600 text-white shadow-[0_0_12px_rgba(16,185,129,0.3)] transition';
    } else {
      btn.className = 'px-2.5 py-1 rounded-lg text-[11px] font-medium text-slate-400 hover:text-white transition';
    }
  });

  const btnToggleLines = document.getElementById('btnToggleScenarioLines');
  if (btnToggleLines) {
    btnToggleLines.style.display = tabName === 'price' ? 'flex' : 'none';
  }

  if (selectedStockDetail) {
    renderInspectorChart(selectedStockDetail);
  }
}

// State visibilitas garis rencana trading
let showScenarioLines = true;

function toggleScenarioLines() {
  showScenarioLines = !showScenarioLines;

  const eyeOpen = document.getElementById('eyeIconOpen');
  const eyeClosed = document.getElementById('eyeIconClosed');
  if (eyeOpen && eyeClosed) {
    eyeOpen.classList.toggle('hidden', !showScenarioLines);
    eyeClosed.classList.toggle('hidden', showScenarioLines);
  }

  // Render ulang grafik inspector
  if (selectedStockDetail) {
    renderInspectorChart(selectedStockDetail);
  }
}

// =====================================================================
// CHART.JS INSPECTOR DENGAN CANDLESTICK & GARIS RENCANA TP/SL/ENTRY
// =====================================================================
function renderInspectorChart(d) {
  const chartCanvas = document.getElementById('inspectorChart');
  if (!chartCanvas) return;
  const ctx = chartCanvas.getContext('2d');
  if (chartInstance) {
    chartInstance.destroy();
  }

  const btnToggleLines = document.getElementById('btnToggleScenarioLines');
  if (btnToggleLines) {
    btnToggleLines.style.display = activeChartTab === 'price' ? 'flex' : 'none';
  }

  const eyeOpen = document.getElementById('eyeIconOpen');
  const eyeClosed = document.getElementById('eyeIconClosed');
  if (eyeOpen && eyeClosed) {
    eyeOpen.classList.toggle('hidden', !showScenarioLines);
    eyeClosed.classList.toggle('hidden', showScenarioLines);
  }

  const hist = d.history || [];
  const labels = hist.map((h) => h.date.slice(5)); // MM-DD

  const isLight = document.documentElement.classList.contains('light');
  const chartTextColor = isLight ? '#334155' : '#cbd5e1';
  const chartSubColor = isLight ? '#64748b' : '#94a3b8';
  const chartGridColor = isLight ? 'rgba(203, 213, 225, 0.65)' : 'rgba(51, 65, 85, 0.25)';

  if (activeChartTab === 'price') {
    // 1. Sinkronkan harga penutupan candle terakhir dengan harga riil saat ini (d.close)
    const currentPrice = Number(d.close || (hist.length > 0 ? hist[hist.length - 1].close : 0));
    if (hist.length > 0 && currentPrice > 0) {
      const lastBar = hist[hist.length - 1];
      if (Number(lastBar.close) !== currentPrice) {
        lastBar.close = currentPrice;
        if (currentPrice > Number(lastBar.high || 0)) lastBar.high = currentPrice;
        if (Number(lastBar.low || Infinity) > currentPrice) lastBar.low = currentPrice;
      }
    }

    const prices = hist.map((h) => Number(h.close));
    const ma20s = hist.map((h) => Number(h.ma20 || h.close));
    const vols = hist.map((h) => Number(h.volume_lot || 0));
    const allLows = hist.map((h) => Number(h.low || h.close));
    const allHighs = hist.map((h) => Number(h.high || h.close));

    const plan = d.trading_plan || {};
    // Ekstraksi seluruh parameter rencana trading yang konsisten dengan 1 harga entry
    const entryVal = plan && (plan.entry_price || plan.entry_high || plan.entry_low)
      ? Number(plan.entry_price || plan.entry_high || plan.entry_low)
      : null;
    const tp1Val = plan && plan.target_1 ? Number(plan.target_1) : null;
    const tp2Val = plan && plan.target_2 ? Number(plan.target_2) : null;
    const slVal = plan && plan.stop_loss ? Number(plan.stop_loss) : null;
    const tp1Pct = plan.target_1_pct != null ? plan.target_1_pct : 4;
    const tp2Pct = plan.target_2_pct != null ? plan.target_2_pct : 7;
    const slPct = plan.stop_loss_pct != null ? plan.stop_loss_pct : -4;

    // Batas rentang harga sumbu Y (otomatis terisolasi ke candle jika garis rencana disembunyikan)
    const valCandidatesMin = [...allLows, ...ma20s.filter((v) => v > 0)];
    if (currentPrice > 0) valCandidatesMin.push(currentPrice);
    if (showScenarioLines) {
      if (slVal && slVal > 0) valCandidatesMin.push(slVal);
      if (entryVal && entryVal > 0) valCandidatesMin.push(entryVal);
    }

    const valCandidatesMax = [...allHighs, ...ma20s.filter((v) => v > 0)];
    if (currentPrice > 0) valCandidatesMax.push(currentPrice);
    if (showScenarioLines) {
      if (tp1Val && tp1Val > 0) valCandidatesMax.push(tp1Val);
      if (tp2Val && tp2Val > 0) valCandidatesMax.push(tp2Val);
    }

    const rawMin = valCandidatesMin.length > 0 ? Math.min(...valCandidatesMin) : 0;
    const rawMax = valCandidatesMax.length > 0 ? Math.max(...valCandidatesMax) : 100;
    const priceRange = Math.max(10, rawMax - rawMin);
    const pricePad = Math.max(4, Math.round(priceRange * 0.12));

    const volColors = hist.map((h, i) => {
      const o = Number(h.open || h.close);
      const cl = Number(h.close);
      const prev = i > 0 ? Number(hist[i - 1].close) : o;
      const isBull = cl > o || (cl === o && cl >= prev);
      return isBull ? 'rgba(16, 185, 129, 0.32)' : 'rgba(239, 68, 68, 0.32)';
    });

    const candlestickPlugin = {
      id: 'candlestickPlugin',
      afterDatasetsDraw(chart) {
        const {
          ctx: c,
          scales: { x: xScale, yPrice: yScale },
        } = chart;
        if (!xScale || !yScale) return;
        const count = hist.length || 1;
        const plotWidth = xScale.width || 300;
        const bodyWidth = Math.max(4, Math.min(13, Math.floor((plotWidth / count) * 0.58)));

        c.save();

        // 1. Gambar Candlestick Body & Wick
        hist.forEach((h, i) => {
          const o = Number(h.open || h.close);
          const hi = Number(h.high || Math.max(o, h.close));
          const lo = Number(h.low || Math.min(o, h.close));
          const cl = Number(h.close);
          const prevCl = i > 0 ? Number(hist[i - 1].close) : o;
          const isBull = cl > o || (cl === o && cl >= prevCl);

          const candleColor = isBull ? '#10b981' : '#ef4444';
          const x = xScale.getPixelForValue(i);
          const yHigh = yScale.getPixelForValue(hi);
          const yLow = yScale.getPixelForValue(lo);
          const yOpen = yScale.getPixelForValue(o);
          const yClose = yScale.getPixelForValue(cl);

          // Sumbu / Wick
          c.beginPath();
          c.strokeStyle = candleColor;
          c.lineWidth = 1.4;
          c.moveTo(x, yHigh);
          c.lineTo(x, yLow);
          c.stroke();

          // Body Candle
          const topY = Math.min(yOpen, yClose);
          const botY = Math.max(yOpen, yClose);
          const boxH = Math.max(2, botY - topY);

          c.fillStyle = candleColor;
          c.strokeStyle = candleColor;
          c.lineWidth = 1;
          c.fillRect(x - bodyWidth / 2, topY, bodyWidth, boxH);
          c.strokeRect(x - bodyWidth / 2, topY, bodyWidth, boxH);
        });

        // 2. Gambar Garis Skenario Horizontal (Hanya TP2, TP1, Entry di kiri, dan SL)
        const leftX = xScale.left;
        const rightX = xScale.right;
        const drawnBadges = [];

        function drawScenarioLine(val, strokeColor, labelText, isDashed = true, alignRight = true) {
          if (!val || isNaN(val)) return;
          const y = yScale.getPixelForValue(val);
          if (y < yScale.top - 4 || y > yScale.bottom + 4) return;

          // Garis Horizontal Skenario
          c.save();
          c.beginPath();
          if (isDashed) {
            c.setLineDash([5, 4]);
            c.lineWidth = 1.5;
          } else {
            c.setLineDash([]);
            c.lineWidth = 1.8;
          }
          c.strokeStyle = strokeColor;
          c.moveTo(leftX, y);
          c.lineTo(rightX, y);
          c.stroke();
          c.setLineDash([]);

          // Badge Pill Box Ringkas
          c.font = 'bold 9px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, monospace';
          const textMetrics = c.measureText(labelText);
          const badgeH = 14;
          const badgeW = textMetrics.width + 8;
          let badgeY = Math.max(yScale.top + 2, Math.min(yScale.bottom - badgeH - 2, y - badgeH / 2));

          // Cek tabrakan vertikal dengan badge sebelumnya pada sisi yang sama
          for (const b of drawnBadges) {
            if (b.alignRight === alignRight && Math.abs(b.y - badgeY) < badgeH + 2) {
              if (badgeY >= b.y) {
                badgeY = b.y + badgeH + 2;
              } else {
                badgeY = b.y - badgeH - 2;
              }
            }
          }
          drawnBadges.push({ alignRight, y: badgeY });

          const badgeX = alignRight ? (rightX - badgeW - 4) : (leftX + 4);

          // Background Pill Badge
          c.fillStyle = isLight ? '#ffffff' : '#090d16';
          c.strokeStyle = strokeColor;
          c.lineWidth = 1.1;
          c.beginPath();
          if (c.roundRect) {
            c.roundRect(badgeX, badgeY, badgeW, badgeH, 3);
          } else {
            c.rect(badgeX, badgeY, badgeW, badgeH);
          }
          c.fill();
          c.stroke();

          // Label Text Ringkas
          c.fillStyle = strokeColor;
          c.textAlign = 'left';
          c.textBaseline = 'middle';
          c.fillText(labelText, badgeX + 4, badgeY + badgeH / 2);
          c.restore();
        }

        // Garis Rencana Skenario Trading (Hanya digambar jika showScenarioLines === true)
        if (showScenarioLines) {
          if (tp2Val && tp2Val > 0) {
            drawScenarioLine(tp2Val, '#14b8a6', `TP2: Rp ${fmtNumber(tp2Val)} (+${tp2Pct}%)`, true, true);
          }
          if (tp1Val && tp1Val > 0) {
            drawScenarioLine(tp1Val, '#10b981', `TP1: Rp ${fmtNumber(tp1Val)} (+${tp1Pct}%)`, true, true);
          }
          if (entryVal && entryVal > 0) {
            drawScenarioLine(entryVal, '#f59e0b', `Beli: Rp ${fmtNumber(entryVal)}`, false, false);
          }
          if (slVal && slVal > 0) {
            drawScenarioLine(slVal, '#ef4444', `SL: Rp ${fmtNumber(slVal)} (${slPct}%)`, true, true);
          }
        }

        // Garis harga penutupan terakhir tetap ditampilkan
        if (currentPrice && currentPrice > 0 && (!showScenarioLines || currentPrice !== entryVal)) {
          drawScenarioLine(currentPrice, '#38bdf8', `Last: Rp ${fmtNumber(currentPrice)}`, true, false);
        }

        c.restore();
      },
    };

    chartInstance = new Chart(ctx, {
      plugins: [candlestickPlugin],
      data: {
        labels,
        datasets: [
          {
            type: 'line',
            label: 'Candle OHLC',
            data: prices,
            borderColor: '#10b981',
            backgroundColor: '#10b981',
            borderWidth: 0,
            pointRadius: 0,
            pointHoverRadius: 3,
            yAxisID: 'yPrice',
            order: 1,
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
            order: 2,
          },
          {
            type: 'bar',
            label: 'Volume (Lot)',
            data: vols,
            backgroundColor: volColors,
            yAxisID: 'yVol',
            order: 3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { labels: { color: chartSubColor, font: { size: 10 } } },
          tooltip: {
            callbacks: {
              label(context) {
                const idx = context.dataIndex;
                const h = hist[idx] || {};
                if (context.dataset.label === 'Candle OHLC') {
                  return `O: Rp ${fmtNumber(h.open)} | H: Rp ${fmtNumber(h.high)} | L: Rp ${fmtNumber(h.low)} | C: Rp ${fmtNumber(h.close)}`;
                }
                if (context.dataset.label === 'MA20') {
                  return `MA20: Rp ${fmtNumber(h.ma20)}`;
                }
                return `Vol: ${fmtNumber(h.volume_lot)} Lot (${h.vol_ratio || 1}x)`;
              },
            },
          },
        },
        scales: {
          x: { ticks: { color: chartSubColor, font: { size: 9 } }, grid: { display: false } },
          yPrice: {
            position: 'right',
            min: Math.max(0, rawMin - pricePad),
            max: rawMax + pricePad,
            ticks: {
              color: chartTextColor,
              font: { size: 9 },
              callback: (val) => 'Rp ' + fmtNumber(val),
            },
            grid: { color: chartGridColor },
          },
          yVol: {
            position: 'left',
            display: false,
            max: Math.max(...vols, 1) * 3.4,
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

// =====================================================================
// UPLOAD EXCEL & MODAL HANDLERS
// =====================================================================
function openUploadModal() {
  document.getElementById('uploadModal')?.classList.remove('hidden');
}
function closeUploadModal() {
  document.getElementById('uploadModal')?.classList.add('hidden');
}
async function openGuideModal() {
  document.getElementById('guideModal')?.classList.remove('hidden');
  try {
    const res = await fetch('/api/backtest/summary?_t=' + Date.now(), { cache: 'no-store' });
    if (res.ok) {
      const d = await res.json();
      const s = d.summary_6m?.high_quality_signals || {};
      const winRate = s.tp1_win_rate_pct != null ? s.tp1_win_rate_pct : 37.7;
      const lossRate = s.sl_loss_pct != null ? s.sl_loss_pct : 32.4;
      const avgWin = s.tp1_avg_win_pct != null ? s.tp1_avg_win_pct : 6.48;
      const avgLoss = s.sl_avg_loss_pct != null ? s.sl_avg_loss_pct : -4.63;
      const actualRR = Math.abs(avgWin / Math.max(0.01, Math.abs(avgLoss))).toFixed(2);

      const rrEl = document.getElementById('guideDynamicRR');
      if (rrEl) rrEl.textContent = `${actualRR}x`;

      const winEl = document.getElementById('guideAvgWinText');
      if (winEl) winEl.textContent = `+${Number(avgWin).toFixed(2)}%`;

      const lossEl = document.getElementById('guideAvgLossText');
      if (lossEl) lossEl.textContent = `${Number(avgLoss).toFixed(2)}%`;

      const winBadge = document.getElementById('guideAvgWinBadge');
      if (winBadge) winBadge.textContent = `Avg Win TP1: +${Number(avgWin).toFixed(2)}%`;

      const lossBadge = document.getElementById('guideAvgLossBadge');
      if (lossBadge) lossBadge.textContent = `Avg Loss SL: ${Number(avgLoss).toFixed(2)}%`;

      const ratioEl = document.getElementById('guideWinLossRatio');
      if (ratioEl) ratioEl.textContent = `${winRate}% Win / ${lossRate}% Loss`;

      const barWin = document.getElementById('guideWinBar');
      if (barWin) barWin.style.width = `${winRate}%`;
      const barLoss = document.getElementById('guideLossBar');
      if (barLoss) barLoss.style.width = `${lossRate}%`;
    }
  } catch (err) {
    console.warn('[GuideModal] Gagal memuat ringkasan backtest:', err);
  }
}
function closeGuideModal() {
  document.getElementById('guideModal')?.classList.add('hidden');
}

// =====================================================================
// OFFICIAL TRADINGVIEW ADVANCED CHART MODAL
// =====================================================================
function openTradingViewModal() {
  const ticker = selectedTicker || (selectedStockDetail ? selectedStockDetail.ticker : 'BBCA');
  const cleanTicker = ticker.trim().toUpperCase();

  const modal = document.getElementById('tradingViewModal');
  const modalTicker = document.getElementById('tvModalTicker');
  const modalLogo = document.getElementById('tvModalLogo');
  const modalPrice = document.getElementById('tvModalPriceBadge');
  const modalSector = document.getElementById('tvModalSector');
  const extLink = document.getElementById('tvModalExternalLink');
  const container = document.getElementById('tradingViewWidgetContainer');

  if (modalTicker) modalTicker.textContent = cleanTicker;
  if (modalLogo) modalLogo.innerHTML = getStockLogoImg(cleanTicker, 'w-8 h-8');
  if (extLink) extLink.href = `https://id.tradingview.com/chart/?symbol=IDX%3A${cleanTicker}`;

  if (selectedStockDetail && selectedStockDetail.ticker === cleanTicker) {
    if (modalPrice) {
      const sign = selectedStockDetail.pct_change >= 0 ? '+' : '';
      modalPrice.textContent = `${fmtPrice(selectedStockDetail.close)} (${sign}${selectedStockDetail.pct_change}%)`;
      modalPrice.className = `text-xs font-mono font-bold ${selectedStockDetail.pct_change >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;
    }
    if (modalSector) {
      modalSector.textContent = `${selectedStockDetail.sector} • Gunakan toolbar kiri TradingView untuk tarik garis & menu Indikator di atas`;
    }
  }

  const isLight = document.documentElement.classList.contains('light');
  const theme = isLight ? 'light' : 'dark';

  if (modal) modal.classList.remove('hidden');

  if (container) {
    container.innerHTML = '<div id="tv_advanced_chart_inner" class="w-full h-full"></div>';

    if (typeof TradingView !== 'undefined' && TradingView.widget) {
      new TradingView.widget({
        autosize: true,
        symbol: `IDX:${cleanTicker}`,
        interval: 'D',
        timezone: 'Asia/Jakarta',
        theme: theme,
        style: '1',
        locale: 'id',
        toolbar_bg: isLight ? '#f8fafc' : '#0f172a',
        enable_publishing: false,
        withdateranges: true,
        hide_side_toolbar: false,
        hide_top_toolbar: false,
        allow_symbol_change: true,
        save_image: true,
        details: false,
        hotlist: false,
        calendar: false,
        show_popup_button: true,
        popup_width: '1280',
        popup_height: '820',
        studies: ['MASimple@tv-basicstudies', 'RSI@tv-basicstudies'],
        container_id: 'tv_advanced_chart_inner',
      });
    } else {
      const symbolParam = encodeURIComponent(`IDX:${cleanTicker}`);
      container.innerHTML = `
        <iframe
          id="tradingview_iframe"
          src="https://s.tradingview.com/widgetembed/?frameElementId=tradingview_widget&symbol=${symbolParam}&interval=D&hidesidetoolbar=0&symboledit=1&saveimage=1&toolbarbg=0f172a&studies=MASimple%40tv-basicstudies%1FRSI%40tv-basicstudies&theme=${theme}&style=1&timezone=Asia%2FJakarta&withdateranges=1&showpopupbutton=1&studies_overrides=%7B%7D&overrides=%7B%7D&enabled_features=%5B%22study_templates%22%2C%22side_toolbar_in_fullscreen_mode%22%2C%22header_in_fullscreen_mode%22%5D&disabled_features=%5B%5D&locale=id"
          style="width: 100%; height: 100%; border: none;"
          allowtransparency="true"
          scrolling="no"
          allowfullscreen="true"
        ></iframe>
      `;
    }
  }
}

function closeTradingViewModal() {
  const modal = document.getElementById('tradingViewModal');
  const container = document.getElementById('tradingViewWidgetContainer');
  if (modal) modal.classList.add('hidden');
  if (container) container.innerHTML = '';
}

// =====================================================================
// UPLOAD FILE EXCEL & LOCAL PATH
// =====================================================================
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

// =====================================================================
// SYNC CEPAT & FULL LIVE DATA
// =====================================================================
let isUnifiedSyncing = false;

async function triggerUnifiedSync() {
  if (isUnifiedSyncing) {
    showToast('Sinkronisasi data pasar sedang berlangsung...', 'info');
    return;
  }
  isUnifiedSyncing = true;
  const navBtn = document.getElementById('btnUnifiedSync');
  const navIcon = document.getElementById('unifiedSyncIcon');
  const navLabel = document.getElementById('unifiedSyncLabel');

  if (navBtn) navBtn.disabled = true;
  if (navIcon) navIcon.classList.add('animate-spin');
  if (navLabel) navLabel.textContent = 'Syncing...';

  showToast('🔄 Memulai pembaruan data bursa seluruh 844 saham IDX...', 'info');

  try {
    const res = await fetch('/api/sync', { method: 'POST', cache: 'no-store' });
    if (!res.ok) throw new Error('Gagal menghubungi server untuk sinkronisasi');
    await res.json();

    // Polling status background sync secara berkala hingga server selesai mengolah data
    showToast('⏳ Server sedang mengunduh & menganalisis 844 saham di background...', 'info');
    let attempts = 0;
    while (attempts < 60) {
      await new Promise((r) => setTimeout(r, 2500));
      attempts++;
      try {
        const checkRes = await fetch(`/api/screener?min_vol_ratio=0.0&_t=${Date.now()}`, { cache: 'no-store' });
        if (checkRes.ok) {
          const checkData = await checkRes.json();
          if (!checkData.is_syncing) {
            showToast('✅ Sinkronisasi seluruh saham IDX selesai!', 'success');
            await Promise.all([loadScreenerData(true), loadTracker()]);
            return;
          }
        }
      } catch (_) {}
    }
    // Jika waktu polling tercapai, muat data terbaru
    await Promise.all([loadScreenerData(true), loadTracker()]);
  } catch (err) {
    showToast(`Error sync: ${err.message}`, 'error');
  } finally {
    isUnifiedSyncing = false;
    if (navBtn) navBtn.disabled = false;
    if (navIcon) navIcon.classList.remove('animate-spin');
    if (navLabel) navLabel.textContent = 'Sync';
  }
}

const syncFastMarketData = triggerUnifiedSync;
const syncLiveMarketData = triggerUnifiedSync;

// =====================================================================
// LIVE MARKET SESSION AUTO-SYNC & ANTI-SLEEP ENGINE
// =====================================================================
let autoSyncTimerId = null;
let keepAliveTimerId = null;

function isIDXMarketOpenNow() {
  const now = new Date();
  const utcHours = now.getUTCHours();
  const utcMinutes = now.getUTCMinutes();
  const totalUtcMinutes = utcHours * 60 + utcMinutes;
  const wibTotalMinutes = (totalUtcMinutes + 7 * 60) % (24 * 60);
  const dayShift = Math.floor((totalUtcMinutes + 7 * 60) / (24 * 60));
  const dayOfWeek = (now.getUTCDay() + dayShift) % 7;

  if (dayOfWeek < 1 || dayOfWeek > 5) return false;

  if (dayOfWeek === 5) {
    const isSesi1 = wibTotalMinutes >= 9 * 60 && wibTotalMinutes <= 11 * 60 + 30;
    const isSesi2 = wibTotalMinutes >= 14 * 60 && wibTotalMinutes <= 16 * 60 + 5;
    return isSesi1 || isSesi2;
  } else {
    const isSesi1 = wibTotalMinutes >= 9 * 60 && wibTotalMinutes <= 12 * 60;
    const isSesi2 = wibTotalMinutes >= 13 * 60 + 30 && wibTotalMinutes <= 16 * 60 + 5;
    return isSesi1 || isSesi2;
  }
}

function updateMarketLiveStatusUI() {
  const isLive = isIDXMarketOpenNow();
  const dots = document.querySelectorAll('#marketStatusDot, #dropdownMarketDot');
  const textEls = document.querySelectorAll('#marketStatusText, #dropdownMarketText');
  const timer = document.getElementById('marketAutoTimer');

  // Format Jam WIB saat ini
  const now = new Date();
  const utc = now.getTime() + (now.getTimezoneOffset() * 60000);
  const wibDate = new Date(utc + (3600000 * 7));
  const hh = String(wibDate.getHours()).padStart(2, '0');
  const mm = String(wibDate.getMinutes()).padStart(2, '0');
  const wibTime = `${hh}:${mm} WIB`;

  // Dapatkan tanggal sesi EOD (dari badge IHSG atau tanggal hari ini)
  let dateStr = '';
  const dateBadge = document.getElementById('ihsgDateBadge');
  if (dateBadge && dateBadge.textContent && dateBadge.textContent !== '—' && dateBadge.textContent !== '-') {
    dateStr = dateBadge.textContent.trim();
  } else {
    const d = wibDate.getDate();
    const months = ['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'];
    const m = months[wibDate.getMonth()];
    const y = wibDate.getFullYear();
    dateStr = `${d} ${m} ${y}`;
  }

  if (isLive) {
    dots.forEach(d => {
      d.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-pulse shrink-0';
    });
    textEls.forEach(t => {
      t.textContent = `Harga Delayed 15 Menit • ${wibTime}`;
      t.className = 'font-bold text-emerald-400 text-[11px]';
    });
    if (timer) timer.textContent = 'Auto-Sync 60s';
  } else {
    dots.forEach(d => {
      d.className = 'w-2 h-2 rounded-full bg-slate-500 shrink-0';
    });
    textEls.forEach(t => {
      t.textContent = `Bursa Tutup • Data Akhir Sesi (${dateStr})`;
      t.className = 'font-medium text-slate-300 text-[11px]';
    });
    if (timer) timer.textContent = 'Bursa Buka 09:00 WIB';
  }
}

// Handler Dropdown Menu Pengaturan (Header Streamlined)
function toggleSettingsDropdown() {
  const menu = document.getElementById('settingsDropdownMenu');
  if (menu) {
    menu.classList.toggle('hidden');
    // Sinkronkan teks status bursa di dropdown saat dibuka
    updateMarketLiveStatusUI();
  }
}

function closeSettingsDropdown() {
  const menu = document.getElementById('settingsDropdownMenu');
  if (menu) menu.classList.add('hidden');
}

function initLiveMarketAutoSync() {
  updateMarketLiveStatusUI();

  if (keepAliveTimerId) clearInterval(keepAliveTimerId);
  keepAliveTimerId = setInterval(() => {
    if (isIDXMarketOpenNow()) {
      fetch(`/api/health?_t=${Date.now()}`, { cache: 'no-store' }).catch(() => {});
    }
  }, 5 * 60 * 1000);

  // Poller grafik IHSG otomatis setiap 5 menit (300 detik) saat jam bursa aktif
  if (ihsgAutoSyncTimerId) clearInterval(ihsgAutoSyncTimerId);
  ihsgAutoSyncTimerId = setInterval(async () => {
    if (isIDXMarketOpenNow()) {
      try {
        console.log('[IHSGChart] ⏱️ Memperbarui grafik IHSG 5 menitan (Jam Bursa Aktif)...');
        await loadIhsgTodayChart(currentIhsgPeriod, true);
      } catch (err) {
        console.debug('[IHSGChart] Auto-refresh 5 menit:', err);
      }
    }
  }, 5 * 60 * 1000);

  if (autoSyncTimerId) clearInterval(autoSyncTimerId);
  autoSyncTimerId = setInterval(async () => {
    updateMarketLiveStatusUI();
    if (isIDXMarketOpenNow()) {
      try {
        await Promise.all([loadScreenerData(true), loadTracker()]);
      } catch (err) {
        console.debug('Background market auto-update:', err);
      }
      // Backup trigger jika timer 5 menit terlewat
      const now = Date.now();
      if (now - lastIhsgRefreshTs >= 5 * 60 * 1000) {
        loadIhsgTodayChart(currentIhsgPeriod, true).catch(() => {});
      }
    }
  }, 60 * 1000);
}

// =====================================================================
// SIGNAL TRACKER — FORWARD TEST (Watchlist -> Running -> Win / Loss)
// =====================================================================
let trackerTab = 'ALL';
let trackerSortBy = 'pnl_desc';
let currentTrackerSignals = [];
let trackerSearchTerm = '';

const TRACKER_STATUS_STYLE = {
  WATCHLIST: 'bg-blue-100 text-blue-800 border border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800/50',
  RUNNING: 'bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50',
  WIN: 'bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50',
  LOSS: 'bg-rose-100 text-rose-800 border border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50',
  EXPIRED: 'bg-rose-100 text-rose-800 border border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50',
  TIMEOUT: 'bg-purple-100 text-purple-800 border border-purple-200 dark:bg-purple-900/30 dark:text-purple-400 dark:border-purple-800/50',
  CANCELLED: 'bg-slate-100 text-slate-700 border border-slate-200 dark:bg-slate-800/60 dark:text-slate-400 dark:border-slate-600/60',
};

const fmtPctOrDash = (v) => (v === null || v === undefined ? '-' : `${v >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`);
const pctClass = (v) => (v === null || v === undefined ? 'text-slate-400' : v >= 0 ? 'text-emerald-400' : 'text-rose-400');

async function loadTracker() {
  try {
    const [statsRes, sigRes] = await Promise.all([
      fetchWithTimeout(`/api/tracker/stats?_t=${Date.now()}`, { cache: 'no-store' }, 9000),
      fetchWithTimeout(`/api/tracker/signals?status=${encodeURIComponent(trackerTab)}&sort_by=${encodeURIComponent(trackerSortBy)}&_t=${Date.now()}`, { cache: 'no-store' }, 9000),
    ]);
    if (!statsRes.ok || !sigRes.ok) throw new Error('Gagal memuat data pantauan sinyal');
    const statsData = await statsRes.json();
    const sigData = await sigRes.json();
    currentTrackerSignals = sigData.signals || [];
    renderTrackerStats(statsData);
    filterAndRenderTracker();
  } catch (err) {
    console.warn('Tracker error:', err);
    if (!currentTrackerSignals || currentTrackerSignals.length === 0) {
      renderTrackerError(err.message);
    }
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

  const cfgLine = document.getElementById('trackerConfigLine');
  if (cfgLine) {
    cfgLine.textContent =
      `Auto-track: Score ≥ ${c.min_score} · Transaksi ≥ Rp 1.0M · Target TP${c.tp_level} · Entry kedaluwarsa ${c.entry_expiry_days} hari · ` +
      `Max hold ${c.max_hold_days} hari · Fee ${c.fee_roundtrip_pct}% · DB: ${c.db_backend} · Candle final s/d ${c.final_session_date}` +
      (data.last_tracker_run ? ` · Evaluasi terakhir: ${data.last_tracker_run}` : '') +
      (data.is_real_market ? '' : ' · ⚠ Dataset aktif bukan data real (tracker pause)');
  }

  const elWR = document.getElementById('tsWinRate');
  if (elWR) elWR.textContent = s.win_rate === null ? '-' : `${s.win_rate}%`;

  const elDec = document.getElementById('tsDecided');
  if (elDec) elDec.textContent = s.decided ? `${s.win}W / ${s.loss}L dari ${s.decided} trade` : 'belum ada trade selesai';

  const elBar = document.getElementById('tsWinBar');
  if (elBar) elBar.style.width = `${s.win_rate || 0}%`;

  const elW = document.getElementById('tsWatch'); if (elW) elW.textContent = s.watchlist;
  const elR = document.getElementById('tsRunning'); if (elR) elR.textContent = s.running;
  const elRPnl = document.getElementById('tsRunningPnl'); if (elRPnl) elRPnl.textContent = `floating ${fmtPctOrDash(s.running_avg_pnl_pct)}`;
  const elWin = document.getElementById('tsWin'); if (elWin) elWin.textContent = s.win;
  const elAvgW = document.getElementById('tsAvgWin'); if (elAvgW) elAvgW.textContent = `avg ${fmtPctOrDash(s.avg_win_pct)}`;
  const elLoss = document.getElementById('tsLoss'); if (elLoss) elLoss.textContent = s.loss;
  const elAvgL = document.getElementById('tsAvgLoss'); if (elAvgL) elAvgL.textContent = `avg ${fmtPctOrDash(s.avg_loss_pct)}`;
  const elExp = document.getElementById('tsExpired'); if (elExp) elExp.textContent = s.expired;
  const elTime = document.getElementById('tsTimeout'); if (elTime) elTime.textContent = s.timeout;

  const pfEl = document.getElementById('tsPF');
  if (pfEl) {
    pfEl.textContent = s.profit_factor !== null ? s.profit_factor.toFixed(2) : s.win > 0 ? '∞' : '-';
    pfEl.className = `text-lg font-bold font-mono mt-0.5 ${s.profit_factor === null ? 'text-white' : s.profit_factor >= 1.5 ? 'text-emerald-400' : s.profit_factor >= 1 ? 'text-amber-300' : 'text-rose-400'}`;
  }

  const expEl = document.getElementById('tsExp');
  if (expEl) {
    expEl.textContent = fmtPctOrDash(s.expectancy_net_pct);
    expEl.className = `text-lg font-bold font-mono mt-0.5 ${pctClass(s.expectancy_net_pct)}`;
  }

  const totEl = document.getElementById('tsTotal');
  if (totEl) {
    totEl.textContent = s.decided || s.timeout ? fmtPctOrDash(s.total_return_net_pct) : '-';
    totEl.className = `text-lg font-bold font-mono mt-0.5 ${s.decided || s.timeout ? pctClass(s.total_return_net_pct) : 'text-white'}`;
  }

  const elTotSig = document.getElementById('tsTotalSignals');
  if (elTotSig) elTotSig.textContent = s.total;

  // Win rate per trigger
  const bt = Object.entries(s.by_trigger || {});
  const btEl = document.getElementById('tsByTrigger');
  if (btEl) {
    btEl.innerHTML = bt.length
      ? bt
          .map(([type, b]) => {
            const wr = b.win_rate;
            return `
            <div class="glass-subcard rounded-xl p-3 hover:border-white/15 transition">
              <div class="flex items-center justify-between">
                <span class="inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold ${getTriggerBadgeClass(type)}">${escHtml(b.label)}</span>
                <span class="font-mono font-bold ${wr === null ? 'text-slate-400' : wr >= 50 ? 'text-emerald-400' : 'text-rose-400'}">${wr === null ? '-' : wr + '%'}</span>
              </div>
              <div class="mt-2 text-[11px] font-mono text-slate-400">
                ${b.total} sinyal · <span class="text-emerald-400">${b.win}W</span> / <span class="text-rose-400">${b.loss}L</span> · <span class="text-amber-300">${b.running} run</span>
              </div>
              <div class="text-[11px] font-mono ${pctClass(b.avg_pnl)}">Avg P/L: ${fmtPctOrDash(b.avg_pnl)}</div>
            </div>`;
          })
          .join('')
      : '<div class="text-slate-400 text-[11px]">Belum ada data.</div>';
  }

  // Tab counts
  const counts = {
    PRIORITY: Math.min(3, s.watchlist || 0),
    ALL: s.total,
    WATCHLIST: s.watchlist,
    RUNNING: s.running,
    WIN: s.win,
    LOSS: s.loss,
    CLOSED_OTHER: (s.expired || 0) + (s.timeout || 0) + (s.cancelled || 0),
    EXPIRED: s.expired,
    TIMEOUT: s.timeout,
  };
  const TAB_LABELS = {
    PRIORITY: 'Top 3 Siap Beli',
    ALL: 'Semua Sinyal',
    WATCHLIST: 'Menunggu',
    RUNNING: 'Berjalan',
    WIN: 'Target Win',
    LOSS: 'Batas Rugi',
    CLOSED_OTHER: 'Selesai Lainnya',
    EXPIRED: 'Expired',
    TIMEOUT: 'Timeout',
  };
  document.querySelectorAll('#trackerTabs .tracker-tab').forEach((btn) => {
    const tab = btn.dataset.tab;
    const label = TAB_LABELS[tab] || btn.dataset.tab;
    btn.innerHTML = `${escHtml(label)}<span class="tab-count ml-1 px-1.5 py-0.2 rounded bg-white/10 text-[10px]">${counts[tab] ?? 0}</span>`;
    btn.classList.toggle('active', tab === trackerTab);
  });
}

function formatSignalTime(dateStr) {
  if (!dateStr) return '16:00 WIB';
  let t = '';
  if (dateStr.includes(' ')) {
    t = dateStr.split(' ')[1].slice(0, 5);
  } else if (dateStr.includes('T')) {
    t = dateStr.split('T')[1].slice(0, 5);
  }
  return t ? `${t} WIB` : '16:00 WIB';
}

function renderTrackerTable(rows) {
  const tbody = document.getElementById('trackerTableBody');
  const mobileList = document.getElementById('trackerMobileList');
  if (!tbody && !mobileList) return;

  if (!rows.length) {
    const emptyMsg = trackerTab === 'PRIORITY'
      ? 'Belum ada saham antrean yang memenuhi kriteria Top 3 Siap Beli saat ini. Pantau tab Menunggu.'
      : 'Belum ada sinyal pada kategori ini. Sinyal akumulasi dengan score tinggi akan otomatis tercatat setelah sinkronisasi data real.';
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="10" class="py-8 text-center text-slate-400">${emptyMsg}</td></tr>`;
    }
    if (mobileList) {
      mobileList.innerHTML = `<div class="py-8 text-center text-xs text-slate-400 bg-white/5 dark:bg-slate-900/40 rounded-xl p-4 border border-white/5">${emptyMsg}</div>`;
    }
    return;
  }

  // 1. Render Desktop Table Rows
  if (tbody) {
    tbody.innerHTML = rows
      .map((r) => {
        const safeTicker = escHtml(r.ticker);
        const safeSector = escHtml(r.sector || (r.source === 'AUTO' ? 'Auto Sinyal' : 'Manual'));
        const safeTriggerLabel = escHtml(r.trigger_label || '-');
        const safeSignalDate = escHtml(r.signal_date || '');
        const pnl = r.status === 'WATCHLIST' || r.status === 'EXPIRED' || r.status === 'CANCELLED' ? null : r.pnl_pct;
        const isRunningLoss = r.status === 'RUNNING' && pnl !== null && pnl < 0;

        let statusCls = TRACKER_STATUS_STYLE[r.status] || TRACKER_STATUS_STYLE.EXPIRED;
        if (isRunningLoss) {
          statusCls = 'bg-rose-100 text-rose-800 border border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50';
        }

        const isClosed = ['WIN', 'LOSS', 'EXPIRED', 'TIMEOUT', 'CANCELLED'].includes(r.status);
        const exitOrLast = isClosed && r.exit_price
          ? `${fmtNumber(r.exit_price)}<div class="text-[10px] text-slate-500 font-medium dark:text-slate-400">${escHtml(r.exit_date || '')}</div>`
          : `${fmtNumber(r.last_close)}<div class="text-[10px] text-slate-500 font-medium dark:text-slate-400">last</div>`;

        let entryCell = '<span class="text-slate-400 dark:text-slate-500">-</span>';
        if (r.entry_price) {
          entryCell = `${fmtNumber(r.entry_price)}<div class="text-[10px] text-slate-500 font-medium dark:text-slate-400">${escHtml(r.entry_date || '')}</div>`;
        } else if (r.status === 'WATCHLIST' && r.dist_to_entry_pct !== undefined && r.dist_to_entry_pct !== null) {
          const distNum = Number(r.dist_to_entry_pct);
          const absDist = Math.abs(distNum);
          const distStr = fmtPctOrDash(distNum);
          if (absDist <= 1.0) {
            entryCell = `
              <div class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-500/40">
                <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
                <span>Siap Beli (${distStr})</span>
              </div>
              <div class="text-[10px] text-emerald-600 dark:text-emerald-400 font-medium mt-0.5">Dekat Entry Support</div>`;
          } else if (absDist <= 2.5) {
            entryCell = `
              <div class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-300 dark:bg-amber-500/20 dark:text-amber-300 dark:border-amber-500/40">
                <span class="w-1.5 h-1.5 rounded-full bg-amber-500"></span>
                <span>Mendekati (${distStr})</span>
              </div>
              <div class="text-[10px] text-amber-600 dark:text-amber-400 font-medium mt-0.5">Pantau Ketat</div>`;
          } else {
            entryCell = `
              <div class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-100 text-slate-600 border border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700">
                <span class="w-1.5 h-1.5 rounded-full bg-slate-400"></span>
                <span>Masih Jauh (${distStr})</span>
              </div>
              <div class="text-[10px] text-slate-500 font-medium dark:text-slate-400 mt-0.5">Menunggu Retrace</div>`;
          }
        }

        let isHighFlyer = false;
        if (r.status === 'RUNNING' && pnl !== null && pnl >= 2.0) {
          isHighFlyer = true;
        }

        const noteText = String(r.note || '');
        const safeNote = escHtml(noteText);
        const hasDistWarning = noteText.includes('DISTRIBUSI') || noteText.includes('Awas Distribusi') || noteText.startsWith('⚠️');

        const rowHighlight = hasDistWarning
          ? 'hover:bg-rose-500/10 bg-rose-500/[0.06] border-l-4 border-rose-500 transition-colors'
          : isRunningLoss
            ? 'hover:bg-rose-500/10 bg-rose-500/[0.04] border-l-4 border-rose-400/80 transition-colors'
            : isHighFlyer
              ? 'hover:bg-white/[0.06] bg-emerald-500/[0.06] border-l-4 border-emerald-400 transition-colors'
              : 'hover:bg-white/[0.05] transition-colors';

        return `
        <tr class="${rowHighlight}">
          <!-- Saham -->
          <td class="py-3.5 pl-4 pr-2">
            <div class="flex items-center gap-3 cursor-pointer group" onclick="selectStockAndGoToInspector('${safeTicker}')" title="Klik untuk membuka detail ${safeTicker}">
              ${getStockLogoImg(r.ticker, 'w-8 h-8')}
              <div>
                <div class="font-sans font-extrabold text-sm text-slate-900 dark:text-white group-hover:text-emerald-600 dark:group-hover:text-emerald-300 flex items-center gap-1.5 transition">
                  <span>${safeTicker}</span>
                  ${trackerTab === 'PRIORITY' ? '<span class="px-1.5 py-0.2 rounded text-[9px] font-bold bg-amber-500/25 text-amber-300 border border-amber-400/40 tracking-wider">TOP 3</span>' : ''}
                </div>
                <div class="text-[11px] text-slate-500 dark:text-slate-400 group-hover:text-slate-700 dark:group-hover:text-slate-300 truncate max-w-[150px] mt-0.5">${safeSector}</div>
              </div>
            </div>
          </td>

          <!-- Trigger & Score -->
          <td class="py-3.5 px-3">
            <span class="inline-flex items-center gap-2 px-3 py-1 rounded-full text-[11px] font-semibold ${getTriggerBadgeClass(r.trigger_type)}">
              <span>${safeTriggerLabel}</span>
              <span class="font-mono font-extrabold text-slate-900 dark:text-white">${escHtml(r.score ?? '-')}</span>
            </span>
            ${(r.bdr_pct != null || r.top_buyers) ? `
              <div class="mt-1 flex items-center gap-1.5 text-[9px] font-mono text-slate-500 dark:text-slate-400">
                <span class="px-1.5 py-0.2 rounded font-bold ${r.bdr_pct >= 10 ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 border border-emerald-500/30' : r.bdr_pct <= -10 ? 'bg-rose-500/15 text-rose-600 dark:text-rose-400 border border-rose-500/30' : 'bg-slate-500/15 text-slate-600 dark:text-slate-300 border border-slate-400/20'}">BDR ${r.bdr_pct != null ? (r.bdr_pct >= 0 ? '+' : '') + Number(r.bdr_pct).toFixed(1) + '%' : ''}</span>
                ${r.top_buyers ? `<span class="truncate max-w-[120px] font-semibold text-emerald-600 dark:text-emerald-400">Buyer: ${escHtml(r.top_buyers)}</span>` : ''}
              </div>` : ''}
          </td>

          <!-- Tanggal & Waktu Sinyal -->
          <td class="py-3.5 px-3 font-sans font-medium text-slate-800 dark:text-slate-200 text-xs">
            <div>${safeSignalDate}</div>
            <div class="text-[10px] text-emerald-600 dark:text-emerald-400 font-mono flex items-center gap-1 mt-0.5" title="Waktu terdeteksi">
              <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 dark:bg-emerald-400"></span>
              ${escHtml(formatSignalTime(r.created_at))}
            </div>
          </td>

          <!-- Harga Beli -->
          <td class="py-3.5 px-3 text-right font-mono text-slate-900 dark:text-white font-bold text-xs">${fmtPrice(r.entry_high || r.entry_low || r.entry_price)}</td>

          <!-- SL / TP -->
          <td class="py-3.5 px-3 text-right font-mono text-slate-900 dark:text-white font-semibold text-xs">
            ${fmtNumber(r.stop_loss)} / ${fmtNumber(r.target)}
          </td>

          <!-- Status Simulasi -->
          <td class="py-3.5 px-3 text-center">
            <span class="inline-block min-w-[82px] text-center px-3.5 py-1 rounded-full border text-xs font-bold tracking-wide ${statusCls}" title="${safeNote}">
              ${r.status === 'RUNNING' ? (isRunningLoss ? 'Running Loss' : 'Running') : r.status === 'WIN' ? 'Win' : r.status === 'WATCHLIST' ? 'Watchlist' : r.status === 'LOSS' ? 'Loss' : escHtml(r.status)}
            </span>
            ${hasDistWarning ? `<div class="mt-1 text-[9px] font-bold text-rose-800 bg-rose-100 border border-rose-200 dark:text-rose-300 dark:bg-rose-500/20 dark:border-rose-500/40 rounded px-1.5 py-0.5" title="${safeNote}">Awas Distribusi</div>` : ''}
          </td>

          <!-- Harga Masuk -->
          <td class="py-3.5 px-3 text-right font-mono text-slate-900 dark:text-white font-semibold text-xs">${entryCell}</td>

          <!-- Harga Terkini -->
          <td class="py-3.5 px-3 text-right font-mono text-slate-900 dark:text-white font-semibold text-xs">${exitOrLast}</td>

          <!-- Hasil (P/L) -->
          <td class="py-3.5 px-3 text-right font-mono">
            ${pnl !== null ? `
              <span class="inline-block min-w-[66px] text-center px-3 py-1 rounded-full text-xs font-extrabold font-mono ${pnl >= 0 ? 'bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-400/70 shadow-[0_0_16px_rgba(16,185,129,0.1)]' : 'bg-rose-100 text-rose-800 border border-rose-200 dark:bg-rose-500/20 dark:text-rose-300 dark:border-rose-400/70 shadow-[0_0_16px_rgba(244,63,94,0.1)]'}">
                ${pnl >= 0 ? '+' : ''}${pnl.toFixed(1)}%
              </span>
            ` : '<span class="text-slate-400 dark:text-slate-500">-</span>'}
          </td>

          <!-- Action / Delete -->
          <td class="py-3.5 pl-1 pr-3 text-right">
            <button onclick="deleteSignal(${Number(r.id)})" class="text-slate-500 hover:text-rose-400 text-base font-bold transition px-1" title="Hapus sinyal">&times;</button>
          </td>
        </tr>`;
      })
      .join('');
  }

  // 2. Render Mobile Card List View
  if (mobileList) {
    mobileList.innerHTML = rows
      .map((r) => {
        const safeTicker = escHtml(r.ticker);
        const safeSector = escHtml(r.sector || (r.source === 'AUTO' ? 'Auto Sinyal' : 'Manual'));
        const safeTriggerLabel = escHtml(r.trigger_label || '-');
        const safeSignalDate = escHtml(r.signal_date || '');
        const pnl = r.status === 'WATCHLIST' || r.status === 'EXPIRED' || r.status === 'CANCELLED' ? null : r.pnl_pct;
        const isRunningLoss = r.status === 'RUNNING' && pnl !== null && pnl < 0;
        const isHighFlyer = r.status === 'RUNNING' && pnl !== null && pnl >= 2.0;

        const noteText = String(r.note || '');
        const safeNote = escHtml(noteText);
        const hasDistWarning = noteText.includes('DISTRIBUSI') || noteText.includes('Awas Distribusi') || noteText.startsWith('⚠️');

        const isClosed = ['WIN', 'LOSS', 'EXPIRED', 'TIMEOUT', 'CANCELLED'].includes(r.status);
        const exitOrLast = isClosed && r.exit_price ? r.exit_price : r.last_close;
        const exitOrLastLabel = isClosed && r.exit_price ? 'Exit' : 'Terkini';

        // Readiness or Status Badge for Mobile
        let statusBadge = '';
        if (r.status === 'WATCHLIST') {
          if (r.dist_to_entry_pct !== undefined && r.dist_to_entry_pct !== null) {
            const distNum = Number(r.dist_to_entry_pct);
            const absDist = Math.abs(distNum);
            const distStr = fmtPctOrDash(distNum);
            if (absDist <= 1.0) {
              statusBadge = `<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-500/40"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>Siap Beli (${distStr})</span>`;
            } else if (absDist <= 2.5) {
              statusBadge = `<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-300 dark:bg-amber-500/20 dark:text-amber-300 dark:border-amber-500/40"><span class="w-1.5 h-1.5 rounded-full bg-amber-500"></span>Mendekati (${distStr})</span>`;
            } else {
              statusBadge = `<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-100 text-slate-600 border border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700"><span class="w-1.5 h-1.5 rounded-full bg-slate-400"></span>Masih Jauh (${distStr})</span>`;
            }
          } else {
            statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-100 text-slate-600 border border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700">Menunggu</span>`;
          }
        } else if (r.status === 'RUNNING') {
          statusBadge = `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold ${isRunningLoss ? 'bg-rose-100 text-rose-800 border border-rose-300 dark:bg-rose-500/20 dark:text-rose-300 dark:border-rose-500/40' : 'bg-emerald-100 text-emerald-800 border border-emerald-300 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-500/40'}"><span class="w-1.5 h-1.5 rounded-full ${isRunningLoss ? 'bg-rose-500' : 'bg-emerald-500'}"></span>Running ${pnl !== null ? (pnl >= 0 ? '+' : '') + pnl.toFixed(1) + '%' : ''}</span>`;
        } else if (r.status === 'WIN') {
          statusBadge = `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-500/40">Win ${pnl !== null ? '+' + pnl.toFixed(1) + '%' : ''}</span>`;
        } else if (r.status === 'LOSS') {
          statusBadge = `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-100 text-rose-800 border border-rose-300 dark:bg-rose-500/20 dark:text-rose-300 dark:border-rose-500/40">Loss ${pnl !== null ? pnl.toFixed(1) + '%' : ''}</span>`;
        } else {
          statusBadge = `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-100 text-slate-600 border border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700">${escHtml(r.status)}</span>`;
        }

        const cardHighlight = hasDistWarning
          ? 'border-l-4 border-l-rose-500 bg-rose-500/[0.04]'
          : isRunningLoss
            ? 'border-l-4 border-l-rose-400 bg-rose-500/[0.03]'
            : isHighFlyer
              ? 'border-l-4 border-l-emerald-400 bg-emerald-500/[0.03]'
              : '';

        return `
          <div onclick="selectStockAndGoToInspector('${safeTicker}')" class="p-3 rounded-xl bg-white dark:bg-slate-900/70 border border-slate-200/80 dark:border-white/[0.08] shadow-sm hover:border-slate-300 dark:hover:border-white/20 transition cursor-pointer active:scale-[0.99] space-y-2.5 ${cardHighlight}">
            <!-- Top Line: Logo, Ticker, Badges, Status & Delete -->
            <div class="flex items-center justify-between gap-2">
              <div class="flex items-center gap-2.5 min-w-0">
                ${getStockLogoImg(r.ticker, 'w-7 h-7 flex-shrink-0')}
                <div class="min-w-0">
                  <div class="flex items-center gap-1.5 flex-wrap">
                    <span class="font-sans font-black text-sm text-slate-900 dark:text-white leading-tight">${safeTicker}</span>
                    ${trackerTab === 'PRIORITY' ? '<span class="px-1.5 py-0.2 rounded text-[9px] font-bold bg-amber-500/20 text-amber-700 dark:text-amber-300 border border-amber-400/30">TOP 3</span>' : ''}
                    ${hasDistWarning ? '<span class="px-1.5 py-0.2 rounded text-[9px] font-bold bg-rose-500/20 text-rose-700 dark:text-rose-300 border border-rose-400/30">Awas Distribusi</span>' : ''}
                  </div>
                  <div class="text-[10px] text-slate-500 dark:text-slate-400 truncate max-w-[140px] leading-tight mt-0.5">${safeSector}</div>
                </div>
              </div>
              <div class="flex items-center gap-1.5 flex-shrink-0">
                ${statusBadge}
                <button onclick="event.stopPropagation(); deleteSignal(${Number(r.id)})" class="w-6 h-6 rounded flex items-center justify-center text-slate-400 hover:text-rose-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition text-sm font-bold" title="Hapus sinyal">&times;</button>
              </div>
            </div>

            <!-- Middle Line: Trigger Badge & Signal Date/Time -->
            <div class="flex items-center justify-between gap-2 text-xs">
              <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold ${getTriggerBadgeClass(r.trigger_type)}">
                <span>${safeTriggerLabel}</span>
                <span class="font-mono font-bold text-slate-900 dark:text-white">${escHtml(r.score ?? '-')}</span>
              </span>
              <span class="text-[10px] text-slate-500 dark:text-slate-400 font-mono">
                ${safeSignalDate} · ${escHtml(formatSignalTime(r.created_at))}
              </span>
            </div>

            <!-- Broksum Metrics on Mobile if Available -->
            ${(r.bdr_pct != null || r.top_buyers) ? `
              <div class="flex items-center justify-between text-[10px] font-mono px-0.5">
                <span class="inline-flex items-center gap-1 text-slate-600 dark:text-slate-300">
                  <span class="text-slate-400 text-[9px]">BDR:</span>
                  <strong class="${r.bdr_pct >= 10 ? 'text-emerald-600 dark:text-emerald-400' : r.bdr_pct <= -10 ? 'text-rose-600 dark:text-rose-400' : 'text-slate-400'}">${(r.bdr_pct >= 0 ? '+' : '') + Number(r.bdr_pct).toFixed(1)}%</strong>
                </span>
                ${r.top_buyers ? `<span class="truncate max-w-[150px] text-slate-500 dark:text-slate-400">Buyer: <strong class="text-emerald-600 dark:text-emerald-400">${escHtml(r.top_buyers)}</strong></span>` : ''}
              </div>` : ''}

            <!-- Bottom Line: Price Matrix (3 columns) -->
            <div class="grid grid-cols-3 gap-1.5 pt-2 border-t border-slate-100 dark:border-white/[0.06] text-center">
              <div class="bg-slate-50 dark:bg-slate-800/60 rounded-lg py-1 px-1.5">
                <div class="text-[9px] text-slate-500 dark:text-slate-400 font-medium">Beli (Entry)</div>
                <div class="font-mono font-bold text-xs text-slate-900 dark:text-white mt-0.5">${fmtPrice(r.entry_high || r.entry_low || r.entry_price)}</div>
              </div>
              <div class="bg-slate-50 dark:bg-slate-800/60 rounded-lg py-1 px-1.5">
                <div class="text-[9px] text-slate-500 dark:text-slate-400 font-medium">SL / TP</div>
                <div class="font-mono font-semibold text-xs text-slate-900 dark:text-white mt-0.5">${fmtNumber(r.stop_loss)} / ${fmtNumber(r.target)}</div>
              </div>
              <div class="bg-slate-50 dark:bg-slate-800/60 rounded-lg py-1 px-1.5">
                <div class="text-[9px] text-slate-500 dark:text-slate-400 font-medium">${exitOrLastLabel}</div>
                <div class="font-mono font-bold text-xs text-slate-900 dark:text-white mt-0.5">${fmtNumber(exitOrLast)}</div>
              </div>
            </div>
          </div>
        `;
      })
      .join('');
  }
}

function setTrackerTab(tab) {
  trackerTab = tab;
  if (tab === 'RUNNING' && trackerSortBy !== 'pnl_desc' && trackerSortBy !== 'pnl_asc') {
    trackerSortBy = 'pnl_desc';
    const sel = document.getElementById('trackerSortSelect');
    if (sel) sel.value = 'pnl_desc';
  } else if (tab === 'PRIORITY' || tab === 'WATCHLIST') {
    if (trackerSortBy === 'pnl_desc' || trackerSortBy === 'pnl_asc') {
      trackerSortBy = 'distance_asc';
      const sel = document.getElementById('trackerSortSelect');
      if (sel) sel.value = 'distance_asc';
    }
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
  if (!confirm('Hapus sinyal ini dari simulasi tracker?')) return;
  const res = await fetch(`/api/tracker/signals/${id}`, { method: 'DELETE' });
  if (res.ok) {
    showToast('Sinyal dihapus.');
    await loadTracker();
  }
}

async function evaluateTracker() {
  const btn = document.getElementById('btnEvalTracker');
  if (btn) {
    btn.disabled = true;
    btn.textContent = '⏳ Mengevaluasi...';
  }
  try {
    const res = await fetch('/api/tracker/evaluate', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Evaluasi gagal');
    showToast(data.message, data.result && data.result.skipped ? 'error' : 'success');
    await loadTracker();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '⚡ Evaluasi Sekarang';
    }
  }
}

async function cleanupStaleWatchlist() {
  if (!confirm('Bersihkan antrean saham yang sudah lebih dari 3 hari bursa tidak menyentuh zona beli?\n\nSinyal lama akan diarsipkan ke status EXPIRED agar antrean tetap fokus.')) {
    return;
  }
  const btn = document.getElementById('btnCleanupStaleTracker');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span><span>Membersihkan...</span>';
  }
  try {
    const res = await fetch('/api/tracker/cleanup-stale', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Gagal membersihkan antrean');
    showToast(data.message || `${data.cleaned} antrean kedaluwarsa berhasil dibersihkan.`, 'success');
    await loadTracker();
  } catch (err) {
    console.error('cleanupStaleWatchlist error:', err);
    showToast(err.message || 'Gagal membersihkan antrean.', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<span>🧹</span><span>Bersihkan Basi</span>';
    }
  }
}

async function purgeRetailWatchlist() {
  if (!confirm('Audit antrean Watchlist dengan Broker Summary Invezgo?\n\nSaham yang terdeteksi distribusi atau didominasi ritel akan otomatis dihapus agar antrean hanya menyisakan saham yang diakumulasi Smart Money.')) {
    return;
  }
  const btn = document.getElementById('btnPurgeRetailWatchlist');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '<span>Memfilter...</span>';
  }
  try {
    const res = await fetch('/api/tracker/purge-retail-watchlist', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Gagal memfilter watchlist');
    showToast(data.message || 'Audit Smart Money selesai!', 'success');
    await loadTracker();
  } catch (err) {
    console.error('purgeRetailWatchlist error:', err);
    showToast(err.message || 'Gagal memfilter watchlist.', 'error');
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '<span>Filter Broksum</span>';
    }
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
// PWA REGISTRATION
// =====================================================================
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    // Daftarkan ulang langganan Web Push bila izin sudah diberikan (server bisa kehilangan data saat redeploy)
    if ('Notification' in window && Notification.permission === 'granted') {
      setTimeout(() => { subscribeWebPush().catch(() => {}); }, 3000);
    }
    navigator.serviceWorker.register('/sw.js').then((reg) => {
      reg.update().catch(() => {});
    }).catch((err) => {
      console.warn('[PWA] Service Worker registration failed:', err);
    });
  });
}

// =====================================================================
// REZIM PASAR IHSG (MARKET BREADTH)
// =====================================================================
let currentMarketRegime = null;

function renderMarketRegimeBadge(regime) {
  if (!regime) return;
  currentMarketRegime = regime;

  const dot = document.getElementById('regimeDot');
  const label = document.getElementById('regimeLabel');

  if (dot) {
    dot.className = 'w-2 h-2 rounded-full animate-pulse ' +
      (regime.color === 'emerald' ? 'bg-emerald-400 shadow-[0_0_8px_#10b981]' :
       regime.color === 'rose' ? 'bg-rose-400 shadow-[0_0_8px_#f43f5e]' :
       'bg-amber-400 shadow-[0_0_8px_#f59e0b]');
  }

  if (label) {
    label.className = 'font-bold text-[11px] sm:text-xs ' +
      (regime.color === 'emerald' ? 'text-emerald-300' :
       regime.color === 'rose' ? 'text-rose-300' :
       'text-amber-300');
    label.textContent = `${regime.label} (${regime.breadth_ma20_pct}%)`;
  }

  // Jika sedang di tab Pilihan Hari Ini, sesuaikan tampilan kandidat sesuai status lock/rebound
  if (activeMainTab === 'today' && (currentTodayCandidates.length > 0 || currentStocks.length > 0)) {
    renderTodayCandidates(currentTodayCandidates.length > 0 ? currentTodayCandidates : currentStocks);
  }
}

async function loadMarketRegime() {
  try {
    const res = await fetch(`/api/market-regime?_t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    renderMarketRegimeBadge(data);
  } catch (err) {
    console.warn('[MarketRegime] Gagal memuat rezim pasar:', err);
  }
}

// =====================================================================
// GRAFIK INDEKS IHSG (^JKSE / COMPOSITE) DI TAB HARI INI
// =====================================================================
let ihsgChartInstance = null;
let lastIhsgChartData = null;
let ihsgChartCollapsed = false;
let currentIhsgPeriod = '3mo';
let lastIhsgRefreshTs = 0;
let ihsgAutoSyncTimerId = null;

function fmtIndexNum(n) {
  if (n == null || isNaN(n)) return '—';
  return new Intl.NumberFormat('id-ID', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(Number(n));
}

function toggleIhsgChartCollapse() {
  ihsgChartCollapsed = !ihsgChartCollapsed;
  const wrapper = document.getElementById('ihsgChartWrapper');
  const icon = document.getElementById('ihsgCollapseIcon');
  if (wrapper) {
    wrapper.classList.toggle('hidden', ihsgChartCollapsed);
  }
  if (icon) {
    icon.textContent = ihsgChartCollapsed ? '▼' : '▲';
  }
}

async function loadIhsgTodayChart(period = currentIhsgPeriod, force = false) {
  currentIhsgPeriod = period;
  try {
    ['1mo', '3mo', '6mo', '1y'].forEach((p) => {
      const btn = document.getElementById(`ihsgPeriod-${p}`);
      if (btn) {
        if (p === period) {
          btn.className = 'ihsg-period-btn px-2.5 py-1 rounded-lg bg-emerald-500/20 text-emerald-300 border border-emerald-400/30 font-bold transition';
        } else {
          btn.className = 'ihsg-period-btn px-2.5 py-1 rounded-lg text-slate-300 hover:text-white transition';
        }
      }
    });

    const forceQuery = force ? '&force=true' : '';
    const res = await fetchWithTimeout(`/api/ihsg/candles?period=${encodeURIComponent(period)}${forceQuery}&_t=${Date.now()}`, { cache: 'no-store' }, 9000);
    if (!res.ok) throw new Error('Gagal memuat grafik candle IHSG');
    const data = await res.json();
    lastIhsgChartData = data;
    lastIhsgRefreshTs = Date.now();
    renderIhsgTodayChart(data);
  } catch (err) {
    console.warn('[IHSGChart] Gagal memuat grafik IHSG:', err);
    const subStats = document.getElementById('ihsgSubStats');
    if (subStats) {
      subStats.innerHTML = `<span class="text-rose-400 font-medium">Gagal memuat grafik IHSG. <button onclick="loadIhsgTodayChart('${period}', true)" class="underline hover:text-white ml-1 font-bold cursor-pointer">Coba Lagi</button></span>`;
    }
  }
}

function renderIhsgTodayChart(data) {
  if (!data || !Array.isArray(data.candles) || data.candles.length === 0) return;

  const candles = data.candles;
  const last = candles[candles.length - 1];
  const chgPct = Number(data.change_pct ?? last.pct_change ?? 0);
  const chgPts = Number(data.change_pts ?? 0);
  const isUp = chgPct >= 0;

  const valEl = document.getElementById('ihsgCurrentValue');
  const badgeEl = document.getElementById('ihsgChangeBadge');
  const dateEl = document.getElementById('ihsgDateBadge');
  const subEl = document.getElementById('ihsgSubStats');
  const dotEl = document.getElementById('ihsgLegendDot');

  if (valEl) {
    valEl.textContent = fmtIndexNum(data.close ?? last.close);
  }
  if (dateEl) {
    dateEl.textContent = data.latest_date || last.date || '—';
  }
  if (badgeEl) {
    const sign = isUp ? '+' : '';
    badgeEl.textContent = `${sign}${fmtIndexNum(chgPts)} (${sign}${chgPct.toFixed(2)}%)`;
    badgeEl.className = isUp
      ? 'text-xs font-mono font-bold px-2 py-0.5 rounded-lg bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-400/30'
      : 'text-xs font-mono font-bold px-2 py-0.5 rounded-lg bg-rose-100 text-rose-800 border border-rose-200 dark:bg-rose-500/20 dark:text-rose-300 dark:border-rose-400/30';
  }
  if (subEl) {
    const breadth = data.market_regime?.breadth_ma20_pct ?? currentMarketRegime?.breadth_ma20_pct;
    const breadthTxt = breadth != null ? ` • Breadth >MA20: ${breadth}%` : '';
    subEl.textContent = `Open: ${fmtIndexNum(last.open)} • High: ${fmtIndexNum(last.high)} • Low: ${fmtIndexNum(last.low)} • MA20: ${fmtIndexNum(last.ma20)}${breadthTxt}`;
  }

  const canvas = document.getElementById('ihsgTodayChart');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  if (ihsgChartInstance) {
    ihsgChartInstance.destroy();
  }

  const isAboveMa20 = Number(last.close) >= Number(last.ma20 || last.close);
  const mainColor = isAboveMa20 ? '#10b981' : '#f43f5e';
  if (dotEl) {
    dotEl.className = `w-2.5 h-2.5 rounded-full inline-block ${isAboveMa20 ? 'bg-emerald-400' : 'bg-rose-400'}`;
  }

  const isLight = document.documentElement.classList.contains('light');
  const chartSubColor = isLight ? '#64748b' : '#94a3b8';
  const chartGridColor = isLight ? 'rgba(203, 213, 225, 0.65)' : 'rgba(51, 65, 85, 0.25)';

  const grad = ctx.createLinearGradient(0, 0, 0, 220);
  if (isAboveMa20) {
    grad.addColorStop(0, isLight ? 'rgba(16, 185, 129, 0.28)' : 'rgba(16, 185, 129, 0.30)');
    grad.addColorStop(1, 'rgba(16, 185, 129, 0.0)');
  } else {
    grad.addColorStop(0, isLight ? 'rgba(244, 63, 94, 0.28)' : 'rgba(244, 63, 94, 0.30)');
    grad.addColorStop(1, 'rgba(244, 63, 94, 0.0)');
  }

  const labels = candles.map((c) => c.date.slice(5));
  const closes = candles.map((c) => Number(c.close));
  const ma20s = candles.map((c) => Number(c.ma20 || c.close));

  ihsgChartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: 'IHSG Close',
          data: closes,
          borderColor: mainColor,
          backgroundColor: grad,
          borderWidth: 2.2,
          fill: true,
          tension: 0.25,
          pointRadius: 0,
          pointHoverRadius: 5,
          pointHoverBackgroundColor: mainColor,
        },
        {
          label: 'MA20 Trend',
          data: ma20s,
          borderColor: '#f59e0b',
          borderWidth: 1.6,
          borderDash: [5, 5],
          fill: false,
          tension: 0.25,
          pointRadius: 0,
          pointHoverRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false,
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: isLight ? 'rgba(255, 255, 255, 0.96)' : 'rgba(15, 23, 42, 0.95)',
          titleColor: isLight ? '#0f172a' : '#f8fafc',
          bodyColor: isLight ? '#334155' : '#cbd5e1',
          borderColor: isLight ? '#cbd5e1' : 'rgba(255, 255, 255, 0.12)',
          borderWidth: 1,
          padding: 10,
          callbacks: {
            title: (items) => {
              const idx = items[0]?.dataIndex;
              const bar = candles[idx];
              return bar ? `IHSG — ${bar.date}` : 'IHSG';
            },
            label: (ctxItem) => {
              const idx = ctxItem.dataIndex;
              const bar = candles[idx];
              if (ctxItem.dataset.label === 'IHSG Close' && bar) {
                const s = bar.pct_change >= 0 ? '+' : '';
                return [
                  `Close: ${fmtIndexNum(bar.close)} (${s}${Number(bar.pct_change).toFixed(2)}%)`,
                  `Open: ${fmtIndexNum(bar.open)} | High: ${fmtIndexNum(bar.high)} | Low: ${fmtIndexNum(bar.low)}`,
                ];
              }
              return `MA20: ${fmtIndexNum(ctxItem.raw)}`;
            },
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            color: chartSubColor,
            font: { size: 10, family: 'JetBrains Mono' },
            maxTicksLimit: 8,
          },
        },
        y: {
          position: 'right',
          grid: { color: chartGridColor },
          ticks: {
            color: chartSubColor,
            font: { size: 10, family: 'JetBrains Mono' },
            callback: (v) => fmtNumber(v),
          },
        },
      },
    },
  });
}

function openMarketRegimeModal() {
  const modal = document.getElementById('marketRegimeModal');
  if (!modal) return;

  const regime = currentMarketRegime || {
    status: 'NEUTRAL / CONSOLIDATION',
    label: 'Netral / Konsolidasi',
    color: 'amber',
    allocation: 'Alokasi Modal 50% - 70% (Selektif)',
    breadth_ma20_pct: 50.0,
    breadth_ma50_pct: 50.0,
    regime_note: 'Memuat data breadth bursa...',
  };

  const badge = document.getElementById('modalRegimeStatusBadge');
  const title = document.getElementById('modalRegimeTitle');
  const note = document.getElementById('modalRegimeNote');
  const b20 = document.getElementById('modalBreadthMA20');
  const b20Bar = document.getElementById('modalBreadthMA20Bar');
  const b50 = document.getElementById('modalBreadthMA50');
  const b50Bar = document.getElementById('modalBreadthMA50Bar');
  const alloc = document.getElementById('modalRegimeAlloc');

  if (badge) {
    badge.textContent = regime.status;
    badge.className = 'text-xs font-mono font-bold px-2.5 py-1 rounded-lg border ' +
      (regime.color === 'emerald' ? 'bg-emerald-500/20 text-emerald-300 border-emerald-400/30' :
       regime.color === 'rose' ? 'bg-rose-500/20 text-rose-300 border-rose-400/30' :
       'bg-amber-500/20 text-amber-300 border-amber-400/30');
  }

  if (title) title.textContent = regime.label;
  if (note) note.textContent = regime.regime_note;

  if (b20) b20.textContent = `${regime.breadth_ma20_pct}%`;
  if (b20Bar) b20Bar.style.width = `${Math.min(100, Math.max(0, regime.breadth_ma20_pct))}%`;

  if (b50) b50.textContent = `${regime.breadth_ma50_pct}%`;
  if (b50Bar) b50Bar.style.width = `${Math.min(100, Math.max(0, regime.breadth_ma50_pct))}%`;

  if (alloc) alloc.textContent = regime.allocation;

  modal.classList.remove('hidden');
}

function closeMarketRegimeModal() {
  const modal = document.getElementById('marketRegimeModal');
  if (modal) modal.classList.add('hidden');
}

// =====================================================================
// UNDUH LAPORAN FORWARD-TEST CSV (TRACKER EXPORT)
// =====================================================================
function exportTrackerCSV() {
  showToast('📥 Mengunduh riwayat forward-test (CSV)...', 'info');
  const status = trackerTab || 'ALL';
  window.location.href = `/api/tracker/export?status=${encodeURIComponent(status)}`;
}

// =====================================================================
// SUB-TAB PANTAUAN: PAPER TRACKER vs PORTOFOLIO RIIL
// =====================================================================
let activePantauanSubTab = 'paper';

function switchPantauanSubTab(tab) {
  activePantauanSubTab = tab;

  const btnPaper = document.getElementById('subTabBtnPaper');
  const btnPortfolio = document.getElementById('subTabBtnPortfolio');
  const secTracker = document.getElementById('trackerSection');
  const secPortfolio = document.getElementById('portfolioSection');
  const btnBuy = document.getElementById('btnOpenPortfolioBuyModal');

  if (tab === 'paper') {
    if (btnPaper) {
      btnPaper.className = 'px-3.5 sm:px-4 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-400/30 shadow-sm';
    }
    if (btnPortfolio) {
      btnPortfolio.className = 'px-3.5 sm:px-4 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white';
    }
    if (secTracker) secTracker.classList.remove('hidden');
    if (secPortfolio) secPortfolio.classList.add('hidden');
    if (btnBuy) btnBuy.classList.add('hidden');
  } else {
    if (btnPaper) {
      btnPaper.className = 'px-3.5 sm:px-4 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white';
    }
    if (btnPortfolio) {
      btnPortfolio.className = 'px-3.5 sm:px-4 py-1.5 rounded-xl text-xs font-bold transition flex items-center gap-1.5 bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-500/20 dark:text-emerald-300 dark:border-emerald-400/30 shadow-sm';
    }
    if (secTracker) secTracker.classList.add('hidden');
    if (secPortfolio) secPortfolio.classList.remove('hidden');
    if (btnBuy) btnBuy.classList.remove('hidden');
    loadPortfolio();
  }
}

// =====================================================================
// PORTOFOLIO RIIL (JURNAL SAYA) CONTROLLER
// =====================================================================
let currentPortfolioStatus = 'ALL';
let portfolioTrades = [];

async function loadPortfolio(status = currentPortfolioStatus) {
  currentPortfolioStatus = status;
  try {
    const res = await fetchWithTimeout(`/api/portfolio?status=${encodeURIComponent(status)}&_t=${Date.now()}`, { cache: 'no-store' }, 9000);
    if (!res.ok) throw new Error('Gagal mengambil data portofolio riil');
    const data = await res.json();

    const summary = data.summary || {};
    portfolioTrades = data.trades || [];

    // Render Summary Cards
    const elCap = document.getElementById('portCapital');
    const elHold = document.getElementById('portHoldingCount');
    const elVal = document.getElementById('portCurrentVal');
    const elFloatPnl = document.getElementById('portFloatingPnl');
    const elFloatPct = document.getElementById('portFloatingPct');
    const elRealPnl = document.getElementById('portRealizedPnl');
    const elClosed = document.getElementById('portClosedCount');
    const elWinRate = document.getElementById('portWinRate');
    const elTotal = document.getElementById('portTotalCount');

    if (elCap) elCap.textContent = fmtPrice(summary.total_capital_holding || 0);
    if (elHold) elHold.textContent = `${summary.holding_count || 0} Posisi Aktif`;
    if (elVal) elVal.textContent = fmtPrice(summary.total_value_holding || 0);

    const fPnl = summary.floating_pnl_rp || 0;
    const fPct = summary.floating_pnl_pct || 0;
    if (elFloatPnl) {
      elFloatPnl.textContent = `${fPnl >= 0 ? '+' : ''}${fmtPrice(fPnl)}`;
      elFloatPnl.className = `text-lg sm:text-xl font-black font-mono mt-0.5 ${fPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;
    }
    if (elFloatPct) {
      elFloatPct.textContent = `(${fPct >= 0 ? '+' : ''}${fPct.toFixed(2)}%)`;
      elFloatPct.className = `text-[10px] font-mono mt-1 ${fPnl >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;
    }

    const rPnl = summary.realized_pnl_rp || 0;
    if (elRealPnl) {
      elRealPnl.textContent = `${rPnl >= 0 ? '+' : ''}${fmtPrice(rPnl)}`;
      elRealPnl.className = `text-lg sm:text-xl font-black font-mono mt-0.5 ${rPnl >= 0 ? 'text-emerald-300' : 'text-rose-400'}`;
    }
    if (elClosed) elClosed.textContent = `${summary.closed_count || 0} Trade Selesai`;

    if (elWinRate) {
      elWinRate.textContent = summary.win_rate !== null ? `${summary.win_rate}%` : '—';
    }
    if (elTotal) elTotal.textContent = String(summary.total_trades || 0);

    // Render Table
    renderPortfolioTable(portfolioTrades);
  } catch (err) {
    console.warn('[Portfolio] Error:', err);
    if (!portfolioTrades || portfolioTrades.length === 0) {
      renderPortfolioError(err.message);
    }
  }
}

// =====================================================================
// EKSPOR & IMPOR JURNAL PORTOFOLIO RIIL (TEMUAN K7)
// =====================================================================
function exportPortfolioData() {
  if (!portfolioTrades || portfolioTrades.length === 0) {
    showToast('Jurnal portofolio masih kosong. Belum ada transaksi yang dicatat.', 'info');
    return;
  }
  const headers = ['id', 'ticker', 'entry_date', 'entry_price', 'lots', 'stop_loss', 'target_price', 'broker', 'status', 'exit_price', 'exit_date', 'pnl_pct', 'pnl_rp', 'notes'];
  const rows = portfolioTrades.map(t => [
    t.id ?? '',
    t.ticker ?? '',
    t.entry_date ?? '',
    t.entry_price ?? '',
    t.lots ?? '',
    t.stop_loss ?? '',
    t.target_price ?? '',
    `"${String(t.broker || 'Sekuritas').replace(/"/g, '""')}"`,
    t.status ?? 'HOLDING',
    t.exit_price ?? '',
    t.exit_date ?? '',
    t.pnl_pct ?? '',
    t.pnl_rp ?? '',
    `"${String(t.notes || '').replace(/"/g, '""')}"`
  ].join(','));
  const csvContent = [headers.join(','), ...rows].join('\n');
  const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const dStr = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  a.href = url;
  a.download = `smartflow_jurnal_${dStr}.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  showToast(`Cadangan ${portfolioTrades.length} transaksi jurnal berhasil diunduh!`, 'success');
}

function parseCsvRow(line) {
  const res = [];
  let cur = '';
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const ch = line[i];
    if (inQuotes) {
      if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
      else if (ch === '"') { inQuotes = false; }
      else { cur += ch; }
    } else {
      if (ch === '"') { inQuotes = true; }
      else if (ch === ',') { res.push(cur.trim()); cur = ''; }
      else { cur += ch; }
    }
  }
  res.push(cur.trim());
  return res;
}

async function importPortfolioData(e) {
  const file = e.target.files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = async (evt) => {
    try {
      const content = evt.target.result;
      let tradesToImport = [];
      if (file.name.endsWith('.json')) {
        const parsed = JSON.parse(content);
        tradesToImport = Array.isArray(parsed) ? parsed : (parsed.trades || []);
      } else {
        const lines = content.split(/\r?\n/).filter(Boolean);
        if (lines.length > 1) {
          const headers = parseCsvRow(lines[0]).map(h => h.toLowerCase());
          const getCol = (cols, name, altIdx) => {
            const idx = headers.indexOf(name);
            return (idx >= 0 && cols[idx] !== undefined) ? cols[idx] : (cols[altIdx] || '');
          };
          for (let i = 1; i < lines.length; i++) {
            const cols = parseCsvRow(lines[i]);
            if (cols.length >= 3) {
              const ticker = getCol(cols, 'ticker', 1).toUpperCase();
              const entry_price = parseFloat(getCol(cols, 'entry_price', 3)) || 0;
              const lots = parseInt(getCol(cols, 'lots', 4), 10) || 1;
              if (ticker && entry_price > 0) {
                tradesToImport.push({
                  ticker,
                  entry_date: getCol(cols, 'entry_date', 2) || new Date().toISOString().slice(0, 10),
                  entry_price,
                  lots,
                  stop_loss: parseFloat(getCol(cols, 'stop_loss', 5)) || undefined,
                  target_price: parseFloat(getCol(cols, 'target_price', 6) || getCol(cols, 'target_1', 6)) || undefined,
                  broker: getCol(cols, 'broker', 7) || 'Sekuritas',
                  status: (getCol(cols, 'status', 8) || 'HOLDING').toUpperCase(),
                  exit_price: parseFloat(getCol(cols, 'exit_price', 9)) || undefined,
                  exit_date: getCol(cols, 'exit_date', 10) || undefined,
                  notes: getCol(cols, 'notes', 13) || 'Impor Cadangan'
                });
              }
            }
          }
        }
      }

      if (!tradesToImport.length) throw new Error('Tidak ditemukan baris transaksi yang valid.');

      let importedCount = 0;
      for (const t of tradesToImport) {
        try {
          const res = await fetch('/api/portfolio/buy', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              ticker: t.ticker,
              entry_date: t.entry_date,
              entry_price: t.entry_price,
              lots: t.lots,
              stop_loss: t.stop_loss,
              target_price: t.target_price,
              broker: t.broker,
              notes: t.notes
            })
          });
          if (res.ok) {
            const buyData = await res.json();
            importedCount++;
            if (t.status === 'CLOSED' && t.exit_price > 0 && buyData.trade?.id) {
              await fetch(`/api/portfolio/sell/${buyData.trade.id}`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  exit_price: t.exit_price,
                  exit_date: t.exit_date || t.entry_date,
                  notes: t.notes
                })
              });
            }
          }
        } catch (err) {
          console.warn('Import item error:', t.ticker, err);
        }
      }
      await loadPortfolio();
      showToast(`Berhasil memulihkan ${importedCount} transaksi ke portofolio!`, 'success');
    } catch (err) {
      showToast(`Gagal mengimpor file jurnal: ${err.message}`, 'error');
    } finally {
      e.target.value = '';
    }
  };
  reader.readAsText(file);
}

function setPortfolioTab(status) {
  currentPortfolioStatus = status;
  document.querySelectorAll('#portfolioFilterTabs .portfolio-tab').forEach((btn) => {
    const isAct = btn.dataset.status === status;
    btn.className = isAct
      ? 'portfolio-tab px-3 py-1.5 rounded-lg text-xs font-semibold bg-white/10 text-white'
      : 'portfolio-tab px-3 py-1.5 rounded-lg text-xs font-medium text-slate-300 hover:text-white';
  });
  loadPortfolio(status);
}

function renderPortfolioTable(trades) {
  const tbody = document.getElementById('portfolioTableBody');
  if (!tbody) return;

  if (!trades || trades.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="10" class="py-8 text-center text-slate-400">
          Belum ada transaksi pada kategori ini. Klik "Catat Beli Saham" untuk mulai mencatat.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = trades.map((t) => {
    const safeTicker = escHtml(t.ticker);
    const safeSector = escHtml(t.sector || 'IDX Emiten');
    const safeEntryDate = escHtml(t.entry_date || '');
    const safeBroker = escHtml(t.broker || 'Sekuritas');
    const safeNotes = escHtml(t.notes || '-');
    const isHolding = t.status === 'HOLDING';
    const pnlVal = t.pnl_rp || 0;
    const pnlPct = t.pnl_pct || 0;
    const pnlColor = pnlVal >= 0 ? 'text-emerald-400 font-bold' : 'text-rose-400 font-bold';
    const sign = pnlVal >= 0 ? '+' : '';

    const statusBadge = isHolding
      ? '<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-400/30">HOLDING</span>'
      : '<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-800 text-slate-300 border border-white/10">CLOSED</span>';

    return `
      <tr class="hover:bg-white/[0.03] transition">
        <td class="py-3 pl-4 pr-2 font-mono font-bold text-white">
          <div class="flex items-center gap-2">
            ${getStockLogoImg(t.ticker, 'w-6 h-6')}
            <div>
              <span class="text-sm font-black text-white">${safeTicker}</span>
              <div class="text-[10px] text-slate-400 font-sans truncate max-w-[120px]">${safeSector}</div>
            </div>
          </div>
        </td>
        <td class="py-3 px-3 font-mono text-slate-300 text-[11px]">${safeEntryDate}</td>
        <td class="py-3 px-3 text-right font-mono text-white font-semibold">${fmtPrice(t.entry_price)}</td>
        <td class="py-3 px-3 text-center font-mono font-bold text-sky-300">${Number(t.lots || 0)} lot</td>
        <td class="py-3 px-3 text-right font-mono text-slate-200">${fmtPrice(t.total_capital)}</td>
        <td class="py-3 px-3 text-right font-mono text-white font-semibold">${fmtPrice(t.current_price)}</td>
        <td class="py-3 px-3 text-right font-mono ${pnlColor}">
          <div>${sign}${fmtPrice(pnlVal)}</div>
          <div class="text-[10px]">${sign}${pnlPct.toFixed(2)}%</div>
        </td>
        <td class="py-3 px-3 text-center">${statusBadge}</td>
        <td class="py-3 px-3 text-slate-300 text-[11px]">
          <div class="font-medium text-white">${safeBroker}</div>
          <div class="text-slate-400 text-[10px] truncate max-w-[150px]" title="${safeNotes}">${safeNotes}</div>
        </td>
        <td class="py-3 pl-1 pr-4 text-right">
          <div class="flex items-center justify-end gap-1.5">
            ${isHolding ? `
              <button
                onclick="openPortfolioSellModal(${Number(t.id)}, '${safeTicker}', ${Number(t.entry_price || 0)}, ${Number(t.lots || 0)})"
                class="px-2.5 py-1 rounded-lg bg-sky-500/15 hover:bg-sky-500/25 text-sky-300 border border-sky-400/30 text-[11px] font-bold transition active:scale-95"
                title="Jual dan realisasikan posisi"
              >
                Jual
              </button>
            ` : ''}
            <button
              onclick="deletePortfolioTrade(${Number(t.id)})"
              class="px-2 py-1 rounded-lg bg-rose-500/10 hover:bg-rose-500/20 text-rose-300 border border-rose-400/20 text-[11px] transition active:scale-95"
              title="Hapus riwayat trade"
            >
              ✕
            </button>
          </div>
        </td>
      </tr>
    `;
  }).join('');
}

function openPortfolioBuyModal(ticker = '') {
  const modal = document.getElementById('portfolioBuyModal');
  if (!modal) return;

  const tInput = document.getElementById('buyTickerInput');
  const pInput = document.getElementById('buyPriceInput');
  const lInput = document.getElementById('buyLotsInput');
  const dInput = document.getElementById('buyDateInput');
  const slInput = document.getElementById('buyStopLossInput');
  const tpInput = document.getElementById('buyTargetInput');
  const bInput = document.getElementById('buyBrokerInput');
  const nInput = document.getElementById('buyNotesInput');

  if (pInput) pInput.value = '';
  if (slInput) slInput.value = '';
  if (tpInput) tpInput.value = '';
  if (dInput) dInput.value = new Date().toISOString().split('T')[0];
  if (lInput && !lInput.value) lInput.value = '5';
  if (bInput && !bInput.value) bInput.value = 'Sekuritas';
  if (nInput) nInput.value = '';

  const clean = String(ticker || selectedTicker || '').trim().toUpperCase();
  if (tInput) {
    tInput.value = clean;
    if (clean) handleBuyTickerInput(clean);
  }

  calcBuyTotalCapital();
  modal.classList.remove('hidden');
}

function closePortfolioBuyModal() {
  const modal = document.getElementById('portfolioBuyModal');
  if (modal) modal.classList.add('hidden');
}

function handleBuyTickerInput(rawTicker) {
  const ticker = String(rawTicker || '').trim().toUpperCase();
  if (!ticker) return;

  const pInput = document.getElementById('buyPriceInput');
  const slInput = document.getElementById('buyStopLossInput');
  const tpInput = document.getElementById('buyTargetInput');

  const stock = currentStocks.find(s => s.ticker === ticker);
  if (stock) {
    const plan = stock.trading_plan || {};
    if (pInput) pInput.value = plan.entry_price || plan.entry_high || stock.close;
    if (slInput && plan.stop_loss) slInput.value = plan.stop_loss;
    if (tpInput && plan.target_1) tpInput.value = plan.target_1;
  }
  calcBuyTotalCapital();
}

function calcBuyTotalCapital() {
  const p = parseFloat(document.getElementById('buyPriceInput')?.value) || 0;
  const l = parseInt(document.getElementById('buyLotsInput')?.value) || 0;
  const total = p * l * 100;
  const prev = document.getElementById('buyTotalCapitalPreview');
  if (prev) prev.textContent = fmtPrice(total);
}

async function handlePortfolioBuySubmit(e) {
  e.preventDefault();
  const ticker = document.getElementById('buyTickerInput')?.value.trim().toUpperCase();
  const price = parseFloat(document.getElementById('buyPriceInput')?.value) || 0;
  const lots = parseInt(document.getElementById('buyLotsInput')?.value) || 0;
  const date = document.getElementById('buyDateInput')?.value || undefined;
  const sl = parseFloat(document.getElementById('buyStopLossInput')?.value) || undefined;
  const tp = parseFloat(document.getElementById('buyTargetInput')?.value) || undefined;
  const broker = document.getElementById('buyBrokerInput')?.value.trim() || 'Sekuritas';
  const notes = document.getElementById('buyNotesInput')?.value.trim() || '';

  if (!ticker || price <= 0 || lots <= 0) {
    showToast('Kode saham, harga beli, dan jumlah lot wajib diisi.', 'error');
    return;
  }

  const btn = document.getElementById('btnSubmitBuyTrade');
  if (btn) btn.disabled = true;

  try {
    const res = await fetch('/api/portfolio/buy', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ticker,
        entry_price: price,
        lots,
        entry_date: date,
        stop_loss: sl,
        target_price: tp,
        broker,
        notes,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Gagal mencatat transaksi.');

    showToast(`✅ ${data.trade.message || 'Transaksi berhasil disimpan!'}`, 'success');
    closePortfolioBuyModal();
    await loadPortfolio();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

function openPortfolioSellModal(tradeId, ticker, entryPrice, lots) {
  const modal = document.getElementById('portfolioSellModal');
  if (!modal) return;

  const idInput = document.getElementById('sellTradeId');
  const tEl = document.getElementById('sellModalTicker');
  const pEl = document.getElementById('sellModalEntryPrice');
  const lEl = document.getElementById('sellModalLots');
  const pInput = document.getElementById('sellPriceInput');
  const dInput = document.getElementById('sellDateInput');
  const nInput = document.getElementById('sellNotesInput');

  if (idInput) idInput.value = tradeId;
  if (tEl) tEl.textContent = ticker;
  if (pEl) pEl.textContent = fmtPrice(entryPrice);
  if (lEl) lEl.textContent = `${lots} lot`;
  if (dInput) dInput.value = new Date().toISOString().split('T')[0];
  if (nInput) nInput.value = '';

  const stock = currentStocks.find(s => s.ticker === ticker);
  if (pInput) {
    pInput.value = stock ? stock.close : entryPrice;
  }

  calcSellRealizedPreview();
  modal.classList.remove('hidden');
}

function closePortfolioSellModal() {
  const modal = document.getElementById('portfolioSellModal');
  if (modal) modal.classList.add('hidden');
}

function calcSellRealizedPreview() {
  const pEl = document.getElementById('sellModalEntryPrice');
  const lEl = document.getElementById('sellModalLots');
  const exitInput = document.getElementById('sellPriceInput');
  const prevEl = document.getElementById('sellRealizedPreview');

  const entryStr = (pEl?.textContent || '0').replace(/[^0-9]/g, '');
  const lotsStr = (lEl?.textContent || '0').replace(/[^0-9]/g, '');
  const entry = parseFloat(entryStr) || 0;
  const lots = parseInt(lotsStr) || 0;
  const exit = parseFloat(exitInput?.value) || 0;

  if (entry > 0 && lots > 0 && exit > 0) {
    const grossBuy = entry * lots * 100;
    const grossSell = exit * lots * 100;
    const feeRp = (grossBuy * 0.0015) + (grossSell * 0.0025);
    const netDiff = Math.round(grossSell - grossBuy - feeRp);
    const pct = (netDiff / grossBuy) * 100;
    const sign = netDiff >= 0 ? '+' : '';
    if (prevEl) {
      prevEl.textContent = `${sign}${fmtPrice(netDiff)} (${sign}${pct.toFixed(2)}% net)`;
      prevEl.className = `font-mono font-bold text-sm ${netDiff >= 0 ? 'text-emerald-400' : 'text-rose-400'}`;
    }
  } else if (prevEl) {
    prevEl.textContent = '-';
  }
}

async function handlePortfolioSellSubmit(e) {
  e.preventDefault();
  const tradeId = parseInt(document.getElementById('sellTradeId')?.value) || 0;
  const exitPrice = parseFloat(document.getElementById('sellPriceInput')?.value) || 0;
  const exitDate = document.getElementById('sellDateInput')?.value || undefined;
  const notes = document.getElementById('sellNotesInput')?.value.trim() || undefined;

  if (!tradeId || exitPrice <= 0) {
    showToast('Harga jual harus lebih dari Rp 0.', 'error');
    return;
  }

  const btn = document.getElementById('btnSubmitSellTrade');
  if (btn) btn.disabled = true;

  try {
    const res = await fetch(`/api/portfolio/sell/${tradeId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        exit_price: exitPrice,
        exit_date: exitDate,
        notes,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Gagal merealisasikan penjualan.');

    showToast(`💰 ${data.trade.message || 'Penjualan berhasil dicatat!'}`, 'success');
    closePortfolioSellModal();
    await loadPortfolio();
  } catch (err) {
    showToast(err.message, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function deletePortfolioTrade(tradeId) {
  if (!confirm('Hapus catatan transaksi ini dari portofolio?')) return;
  try {
    const res = await fetch(`/api/portfolio/${tradeId}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || 'Gagal menghapus transaksi.');
    showToast(data.message, 'success');
    await loadPortfolio();
  } catch (err) {
    showToast(err.message, 'error');
  }
}

// =====================================================================
// GLOBAL KEYBOARD & BACKDROP MODAL HANDLERS
// =====================================================================
function closeAllModals() {
  closeAlertModal();
  closeLotCalculatorModal();
  closeGlossaryModal();
  closeUploadModal();
  closeGuideModal();
  closeTradingViewModal();
  closeMarketRegimeModal();
  closePortfolioBuyModal();
  closePortfolioSellModal();
  closeSettingsDropdown();
}

window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeAllModals();
  }
});

// Tutup dropdown menu pengaturan jika klik di luar
document.addEventListener('click', (e) => {
  const container = document.getElementById('settingsDropdownContainer');
  if (container && !container.contains(e.target)) {
    closeSettingsDropdown();
  }
});

// Tutup modal jika user mengklik backdrop / area hitam di luar modal
document.querySelectorAll('#alertModal, #lotCalculatorModal, #glossaryModal, #uploadModal, #guideModal, #tradingViewModal, #marketRegimeModal, #portfolioBuyModal, #portfolioSellModal').forEach(modalEl => {
  modalEl.addEventListener('click', (e) => {
    if (e.target === modalEl) {
      modalEl.classList.add('hidden');
    }
  });
});

// =====================================================================
// EVENT LISTENERS INITIALIZATION
// =====================================================================
document.addEventListener('DOMContentLoaded', async () => {
  // 1. Terapkan state mode (Pemula vs Mahir) & Tab Aktif
  applyExpertModeUI();
  switchMainTab(activeMainTab, true);

  // 2. Muat data awal secepat mungkin
  // Modul independen & paralel: kegagalan/keterlambatan satu modul tidak menahan modul lain
  const initTasks = [
    ['screener', () => loadScreenerData(false)],
    ['tracker', () => loadTracker()],
    ['portfolio', () => loadPortfolio()],
    ['regime', () => loadMarketRegime()],
    ['ihsg', () => loadIhsgTodayChart('3mo', true)],
    ['news', () => loadMarketNews(false)],
  ];
  const initDone = Promise.allSettled(initTasks.map(([, fn]) => fn())).then((results) => {
    results.forEach((r, i) => {
      if (r.status === 'rejected') console.warn(`[Init] Modul ${initTasks[i][0]} gagal:`, r.reason);
    });
  });

  // 3. Setup filter listeners di Tab Jelajah
  ['filterTrigger', 'filterVolRatio', 'filterMinScore', 'filterSortBy', 'filterMinValue'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('change', () => loadScreenerData(true));
  });

  let searchTimeout = null;
  const searchInput = document.getElementById('filterSearch');
  if (searchInput) {
    searchInput.addEventListener('input', () => {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(() => loadScreenerData(true), 200);
    });
  }

  // 4. Setup Drag & Drop File Upload
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('excelFileInput');

  if (dropZone && fileInput) {
    ['dragenter', 'dragover'].forEach((eventName) => {
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropZone.classList.add('border-emerald-400', 'bg-emerald-500/10');
      });
    });

    ['dragleave', 'drop'].forEach((eventName) => {
      dropZone.addEventListener(eventName, (e) => {
        e.preventDefault();
        dropZone.classList.remove('border-emerald-400', 'bg-emerald-500/10');
      });
    });

    dropZone.addEventListener('drop', (e) => {
      const dt = e.dataTransfer;
      if (dt && dt.files && dt.files.length) {
        handleExcelUpload(dt.files);
      }
    });

    fileInput.addEventListener('change', () => {
      if (fileInput.files && fileInput.files.length) {
        handleExcelUpload(fileInput.files);
      }
    });
  }

  // 5. Inisialisasi Market Auto Poller & Anti-Sleep
  initLiveMarketAutoSync();

  // 6. Jalankan kalkulasi default di modal kalkulator lot
  runModalLotCalculation();

  // 7. Selalu tampilkan data IHSG terbaru saat aplikasi dibuka kembali / tab aktif kembali
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      updateMarketLiveStatusUI();
      const now = Date.now();
      if (now - lastIhsgRefreshTs >= 60 * 1000 || isIDXMarketOpenNow()) {
        loadIhsgTodayChart(currentIhsgPeriod, true).catch(() => {});
      }
    }
  });

  window.addEventListener('focus', () => {
    const now = Date.now();
    if (now - lastIhsgRefreshTs >= 60 * 1000) {
      loadIhsgTodayChart(currentIhsgPeriod, isIDXMarketOpenNow()).catch(() => {});
    }
  });
});
