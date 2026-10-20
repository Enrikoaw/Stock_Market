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



// =====================================================================
// THEME ENGINE (Emerald · Obsidian Gold · Midnight Blue · Clean Slate · Clean Paper)
// =====================================================================
const VALID_THEMES = ['emerald', 'gold', 'midnight', 'slate', 'paper'];

function initTheme() {
  let saved = localStorage.getItem('smartflow_theme') || 'emerald';
  if (saved === 'dark') saved = 'emerald';
  if (saved === 'light') saved = 'paper';
  selectTheme(saved, false);
}

function selectTheme(themeName, renderChart = true) {
  const valid = VALID_THEMES.includes(themeName) ? themeName : 'emerald';
  const html = document.documentElement;

  // Hapus seluruh kelas tema terdahulu
  VALID_THEMES.forEach((t) => html.classList.remove(`theme-${t}`));
  html.classList.add(`theme-${valid}`);

  const icon = document.getElementById('themeIcon');
  const label = document.getElementById('themeLabel');
  const badge = document.getElementById('activeThemeBadge');

  if (valid === 'paper') {
    html.classList.remove('dark');
    html.classList.add('light');
    if (icon) icon.textContent = '☀️';
    if (label) label.textContent = 'Terang';
    if (badge) {
      badge.textContent = 'Clean Paper';
      badge.className = 'text-[10px] font-mono px-2 py-0.5 rounded-full bg-slate-200 text-slate-800 border border-slate-300';
    }
  } else {
    html.classList.remove('light');
    html.classList.add('dark');
    if (icon) icon.textContent = '🌙';
    if (label) label.textContent = 'Gelap';

    const themeMeta = {
      emerald: { label: 'Emerald Cyber', badgeClass: 'bg-emerald-500/20 text-emerald-300 border-emerald-400/30' },
      gold: { label: 'Obsidian Gold', badgeClass: 'bg-yellow-500/20 text-yellow-300 border-yellow-400/30' },
      midnight: { label: 'Midnight Blue', badgeClass: 'bg-sky-500/20 text-sky-300 border-sky-400/30' },
      slate: { label: 'Clean Slate', badgeClass: 'bg-slate-500/20 text-slate-300 border-slate-400/30' },
    };
    const meta = themeMeta[valid] || themeMeta.emerald;
    if (badge) {
      badge.textContent = meta.label;
      badge.className = `text-[10px] font-mono px-2 py-0.5 rounded-full border ${meta.badgeClass}`;
    }
  }

  // Perbarui indikator tombol aktif di modal Pengaturan
  VALID_THEMES.forEach((t) => {
    const btn = document.getElementById(`themeBtn-${t}`);
    if (btn) {
      if (t === valid) {
        btn.classList.add('active-theme', 'border-emerald-400', 'shadow-[0_0_12px_rgba(16,185,129,0.25)]');
        btn.classList.remove('border-white/10');
      } else {
        btn.classList.remove('active-theme', 'border-emerald-400', 'shadow-[0_0_12px_rgba(16,185,129,0.25)]');
        btn.classList.add('border-white/10');
      }
    }
  });

  localStorage.setItem('smartflow_theme', valid);

  if (renderChart && typeof renderInspectorChart === 'function' && selectedStockDetail) {
    renderInspectorChart(selectedStockDetail);
  }
  if (renderChart && typeof renderIhsgTodayChart === 'function' && lastIhsgChartData) {
    renderIhsgTodayChart(lastIhsgChartData);
  }
}

function applyTheme(theme) {
  selectTheme(theme);
}

function toggleTheme() {
  const current = localStorage.getItem('smartflow_theme') || 'emerald';
  if (current === 'paper') {
    const lastDark = localStorage.getItem('smartflow_last_dark_theme') || 'emerald';
    selectTheme(lastDark);
  } else {
    localStorage.setItem('smartflow_last_dark_theme', current);
    selectTheme('paper');
  }
}

initTheme();

// =====================================================================
// 3 TOP NAVIGATION TABS (Hari Ini · Jelajah · Pantauan)
// =====================================================================
function switchMainTab(tabName) {
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

  // Desktop Header Tabs (Liquid Glass Pill with Glowing Neon Badges)
  if (btnToday) btnToday.classList.toggle('active', tabName === 'today');
  if (btnExplore) btnExplore.classList.toggle('active', tabName === 'explore');
  if (btnWatchlist) btnWatchlist.classList.toggle('active', tabName === 'watchlist');

  // Mobile Bottom Bar Tabs (Liquid Glass Pill with Glowing Neon Badges)
  const mobToday = document.getElementById('mobileNavToday');
  const mobExplore = document.getElementById('mobileNavExplore');
  const mobWatchlist = document.getElementById('mobileNavWatchlist');

  if (mobToday) mobToday.classList.toggle('active', tabName === 'today');
  if (mobExplore) mobExplore.classList.toggle('active', tabName === 'explore');
  if (mobWatchlist) mobWatchlist.classList.toggle('active', tabName === 'watchlist');

  if (tabName === 'today') {
    renderTodayCandidates(currentTodayCandidates.length > 0 ? currentTodayCandidates : currentStocks);
    loadMarketNews(false);
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
    if (modeIcon) modeIcon.textContent = '🚀';
    if (modeLabel) modeLabel.textContent = 'Mode Mahir';
    if (kpiContainer) kpiContainer.classList.remove('hidden');
    document.querySelectorAll('.expert-only').forEach(el => el.classList.remove('hidden'));
  } else {
    if (modeIcon) modeIcon.textContent = '🌱';
    if (modeLabel) modeLabel.textContent = 'Mode Pemula';
    if (kpiContainer) kpiContainer.classList.add('hidden');
    document.querySelectorAll('.expert-only').forEach(el => el.classList.add('hidden'));
  }
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

  // Jika input adalah kandidat konsisten dari backend (memiliki session_label atau dipasok dari today_candidates),
  // gunakan langsung agar konsisten antar sesi (siang & sore)!
  let candidates = [];
  const hasPreselected = stocks.some(s => s.session_label != null);
  if (hasPreselected) {
    candidates = stocks;
  } else {
    // Saring saham untuk strategi Swing Trading "Buy on Pullback / Koreksi Sehat + Akumulasi Broker"
    const rawCandidates = stocks.filter(s =>
      (s.close || 0) >= 70 &&
      (s.value_b_idr || 0) >= 1.0 &&
      !String(s.sector || '').toLowerCase().includes('pemantauan khusus') &&
      !String(s.sector || '').toLowerCase().includes('akselerasi') &&
      (s.fundamental_safety == null || s.fundamental_safety.is_safe !== false) &&
      (s.tape_quality == null || s.tape_quality.is_organic !== false) &&
      s.trigger_type !== 'DISTRIBUTION_WARNING' &&
      !s.retail_trap &&
      s.tracker_status !== 'WIN' &&
      s.tracker_status !== 'LOSS' &&
      s.pct_change >= -3.5 &&
      s.pct_change <= 2.0 &&
      (s.vol_ratio == null || s.vol_ratio <= 1.40) &&
      (s.diff_bandar_avg_pct == null || (s.diff_bandar_avg_pct >= -3.0 && s.diff_bandar_avg_pct <= 2.5)) &&
      (s.bdr_pct >= 5.0 || s.top3_bsr >= 1.15 || (s.smart_money_score || 0) >= 70)
    );

    rawCandidates.sort((a, b) => {
      const bdrA = a.bdr_pct != null ? a.bdr_pct : 0;
      const bdrB = b.bdr_pct != null ? b.bdr_pct : 0;
      return (bdrB - bdrA) || (b.smart_money_score - a.smart_money_score) || ((a.diff_bandar_avg_pct || 0) - (b.diff_bandar_avg_pct || 0));
    });

    const seenSectors = new Set();
    for (const s of rawCandidates) {
      const secCat = s.sector_category || s.sector || 'General';
      if (!seenSectors.has(secCat)) {
        seenSectors.add(secCat);
        candidates.push(s);
      }
      if (candidates.length >= 6) break;
    }

    if (candidates.length < 3) {
      const fallbackList = stocks
        .filter(s =>
          (s.close || 0) >= 70 &&
          (s.value_b_idr || 0) >= 1.0 &&
          !String(s.sector || '').toLowerCase().includes('pemantauan khusus') &&
          !String(s.sector || '').toLowerCase().includes('akselerasi') &&
          (s.fundamental_safety == null || s.fundamental_safety.is_safe !== false) &&
          (s.tape_quality == null || s.tape_quality.is_organic !== false) &&
          s.trigger_type !== 'DISTRIBUTION_WARNING' &&
          !s.retail_trap &&
          s.tracker_status !== 'WIN' &&
          s.tracker_status !== 'LOSS'
        )
        .sort((a, b) => {
          const bdrA = a.bdr_pct != null ? a.bdr_pct : 0;
          const bdrB = b.bdr_pct != null ? b.bdr_pct : 0;
          return (bdrB - bdrA) || (b.smart_money_score - a.smart_money_score);
        });

      for (const s of fallbackList) {
        const secCat = s.sector_category || s.sector || 'General';
        if (!seenSectors.has(secCat)) {
          seenSectors.add(secCat);
          candidates.push(s);
        }
        if (candidates.length >= 6) break;
      }
    }

    if (candidates.length === 0) {
      candidates = stocks
        .filter(s => (s.close || 0) >= 70 && !String(s.sector || '').toLowerCase().includes('pemantauan khusus'))
        .sort((a, b) => (b.smart_money_score || 0) - (a.smart_money_score || 0))
        .slice(0, 3);
    }
  }

  container.innerHTML = defensiveNoticeHtml + candidates.map(s => {
    const safeTicker = escHtml(s.ticker);
    const safeSector = escHtml(s.sector);
    const safeSecCat = escHtml(s.sector_category || 'Sektor');
    const starActive = isFavorite(s.ticker);
    const strength = getScoreStrengthDots(s.smart_money_score);
    const chgColor = s.pct_change >= 0 ? 'text-emerald-400' : 'text-rose-400';

    // Ambil Trading Plan terukur langsung dari backend (TP1 +6%, TP2 +10%, SL Closing Basis)
    const plan = s.trading_plan || {};
    const entryLow = plan.entry_low || Math.round(s.close * 0.99);
    const entryHigh = plan.entry_high || s.close;
    const stopLoss = plan.stop_loss || Math.round(s.close * 0.95);
    const target1 = plan.target_1 || Math.round(s.close * 1.06);
    const target2 = plan.target_2 || Math.round(s.close * 1.10);

    const slPct = plan.stop_loss_pct != null ? plan.stop_loss_pct : (((stopLoss - s.close) / s.close) * 100).toFixed(1);
    const tp1Pct = plan.target_1_pct != null ? plan.target_1_pct : (((target1 - s.close) / s.close) * 100).toFixed(1);
    const tp2Pct = plan.target_2_pct != null ? plan.target_2_pct : (((target2 - s.close) / s.close) * 100).toFixed(1);

    // Kualitas Pita (Tape Quality) Badge
    const tapePill = (s.tape_quality && s.tape_quality.code !== 'ORGANIC_FLOW')
      ? `<span class="text-[10px] font-bold px-2 py-0.5 rounded-md bg-amber-100 text-amber-800 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-400" title="${escHtml(s.tape_quality.reason)}">${escHtml(s.tape_quality.label)}</span>`
      : '<span class="text-[10px] font-bold px-2 py-0.5 rounded-md bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400">Arus Organik</span>';

    // Label Sesi (Konsistensi Siang & Pembaruan Sore)
    const sessionBadge = s.session_label
      ? `<span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-sky-500/15 text-sky-300 border border-sky-400/30" title="Sesi Deteksi: ${escHtml(s.first_seen_time || '')}">${escHtml(s.session_label)}</span>`
      : '<span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-sky-500/15 text-sky-300 border border-sky-400/30">Pilihan Hari Ini</span>';

    // Status Watchlist Wajib
    let statusPill = '<span class="text-[10px] font-bold px-2 py-0.5 rounded-md bg-blue-100 text-blue-800 border border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800/50">Tercatat di Watchlist</span>';
    if (s.tracker_status === 'RUNNING') {
      const isLoss = (s.tracker_pnl_pct || 0) < 0;
      const pnlColor = isLoss
        ? 'bg-rose-100 text-rose-800 border border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50'
        : 'bg-emerald-100 text-emerald-800 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50';
      statusPill = `<span class="text-[10px] font-bold px-2 py-0.5 rounded-md ${pnlColor} border">Posisi Aktif (${(s.tracker_pnl_pct || 0) >= 0 ? '+' : ''}${s.tracker_pnl_pct || 0}%)</span>`;
    }

    const entryPrice = plan.entry_price || entryLow || entryHigh;
    const supportLbl = plan.support_label ? escHtml(plan.support_label) : (s.support_label ? escHtml(s.support_label) : 'Support Terdekat');
    let entryLabel = 'Antre Beli (Support)';
    let entryValue = fmtPrice(entryPrice);
    if (s.tracker_status === 'RUNNING') {
      entryLabel = 'Harga Beli Terkunci';
      entryValue = fmtPrice(entryPrice);
    }

    const pbPct = plan.pullback_from_close_pct != null
      ? plan.pullback_from_close_pct
      : (((entryPrice - s.close) / Math.max(s.close, 1)) * 100).toFixed(1);

    return `
      <div class="p-5 rounded-2xl glass-panel border border-white/[0.08] hover:border-emerald-400/40 transition shadow-lg flex flex-col justify-between gap-4">
        
        <!-- Header: Logo, Ticker, Star, Price -->
        <div class="flex items-start justify-between gap-2">
          <div class="flex items-center gap-3">
            ${getStockLogoImg(s.ticker, 'w-10 h-10')}
            <div>
              <div class="flex items-center gap-1.5 flex-wrap">
                <span class="font-mono font-black text-base text-slate-900 dark:text-white">${safeTicker}</span>
                <span class="text-[10px] font-sans font-bold px-1.5 py-0.2 rounded bg-slate-100 text-slate-700 border border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700">${safeSecCat}</span>
                ${sessionBadge}
                <button
                  onclick="toggleFavorite('${safeTicker}', event)"
                  class="star-btn star-btn-${safeTicker} text-lg leading-none ${starActive ? 'text-amber-400 drop-shadow-[0_0_8px_rgba(251,191,36,0.6)]' : 'text-slate-500 hover:text-amber-300'}"
                  title="Simpan ke Favorit"
                >
                  ★
                </button>
              </div>
              <div class="text-[11px] text-slate-400 truncate max-w-[150px] sm:max-w-[190px]" title="${safeSector}">${safeSector}</div>
            </div>
          </div>
          <div class="text-right">
            <div class="font-mono font-bold text-base text-slate-900 dark:text-white">${fmtPrice(s.close)}</div>
            <div class="font-mono text-xs font-semibold ${chgColor}">${(s.pct_change >= 0 ? '+' : '') + Number(s.pct_change || 0).toFixed(2)}%</div>
          </div>
        </div>

        <!-- Badges Row -->
        <div class="flex items-center gap-1.5 flex-wrap">
          <span class="text-[10px] font-mono font-bold px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            ${escHtml(s.trigger_label || s.trigger_type)}
          </span>
          ${tapePill}
          ${statusPill}
        </div>

        <!-- 3 Metrik Inti Smart Money -->
        <div class="grid grid-cols-3 gap-2 p-2.5 rounded-xl bg-slate-900/40 border border-white/[0.04] text-center">
          <div>
            <div class="text-[10px] text-slate-400">Skor SM</div>
            <div class="font-mono font-bold text-sm text-emerald-400">${s.smart_money_score}</div>
          </div>
          <div>
            <div class="text-[10px] text-slate-400">Vol Spike</div>
            <div class="font-mono font-bold text-sm text-white">${s.vol_ratio ? s.vol_ratio + 'x' : '-'}</div>
          </div>
          <div>
            <div class="text-[10px] text-slate-400">Top 3 BSR</div>
            <div class="font-mono font-bold text-sm text-white">${s.top3_bsr || '-'}</div>
          </div>
        </div>

        <!-- Trading Plan Terukur: Entry di Support Terdekat -->
        <div class="space-y-2 pt-1 border-t border-white/[0.06]">
          <div class="flex items-center justify-between text-[11px]">
            <span class="font-mono font-bold text-slate-300">TRADING PLAN (SWING)</span>
            <span class="text-[10px] text-emerald-400 font-semibold" title="${supportLbl}">${supportLbl}</span>
          </div>

          <!-- Kotak Harga Beli Support -->
          <div class="p-2.5 rounded-xl bg-slate-900/60 border border-emerald-500/20 flex items-center justify-between gap-2">
            <div>
              <div class="text-[10px] text-slate-400 font-medium">${entryLabel}</div>
              <div class="text-[11px] font-mono font-bold text-emerald-300">${supportLbl}</div>
            </div>
            <div class="text-right">
              <div class="font-mono font-bold text-sm text-white">${entryValue}</div>
              <div class="text-[10px] font-mono font-semibold text-amber-400">${pbPct}% (Pullback)</div>
            </div>
          </div>

          <!-- Target & Stop Loss -->
          <div class="grid grid-cols-3 gap-1.5 text-center text-[10px] font-mono">
            <div class="p-1.5 rounded-lg bg-slate-900/40 border border-white/[0.04]">
              <div class="text-slate-400">TP1 (+6%)</div>
              <div class="font-bold text-emerald-400">${fmtPrice(target1)}</div>
              <div class="text-[9px] text-slate-400">+${tp1Pct}%</div>
            </div>
            <div class="p-1.5 rounded-lg bg-slate-900/40 border border-white/[0.04]">
              <div class="text-slate-400">TP2 (+10%)</div>
              <div class="font-bold text-emerald-400">${fmtPrice(target2)}</div>
              <div class="text-[9px] text-slate-400">+${tp2Pct}%</div>
            </div>
            <div class="p-1.5 rounded-lg bg-slate-900/40 border border-white/[0.04]">
              <div class="text-slate-400">SL (Close)</div>
              <div class="font-bold text-rose-400">${fmtPrice(stopLoss)}</div>
              <div class="text-[9px] text-slate-400">${slPct}%</div>
            </div>
          </div>
        </div>

        <!-- Action Buttons -->
        <div class="flex items-center gap-2 pt-1 border-t border-white/[0.06]">
          <button
            onclick="openLotCalculatorForStockDetails('${safeTicker}', ${entryPrice}, ${stopLoss})"
            class="flex-1 py-1.5 px-3 rounded-xl bg-emerald-500/10 hover:bg-emerald-500/20 text-emerald-400 border border-emerald-500/20 text-xs font-semibold transition flex items-center justify-center gap-1.5"
            title="Hitung manajemen modal & ukuran lot posisi berdasarkan entry support Rp ${fmtPrice(entryPrice)}"
          >
            <span>Hitung Lot</span>
          </button>
          <button
            onclick="selectStockAndGoToInspector('${safeTicker}')"
            class="flex-1 py-1.5 px-3 rounded-xl bg-white/[0.05] hover:bg-white/[0.10] text-slate-200 text-xs font-semibold transition flex items-center justify-center gap-1"
          >
            <span>Lihat Detail</span>
            <span>&rarr;</span>
          </button>
        </div>

      </div>
    `;
  }).join('');
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


// Fetch dengan batas waktu agar modul lambat (mis. berita eksternal) tidak menahan UI
async function fetchWithTimeout(url, opts = {}, ms = 15000) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), ms);
  try {
    return await fetch(url, { ...opts, signal: ctrl.signal });
  } finally {
    clearTimeout(timer);
  }
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
  } catch (err) {
    if (listEl && (!cachedNewsItems || cachedNewsItems.length === 0)) {
      listEl.innerHTML = `
        <div class="p-6 rounded-xl glass-subcard text-center text-slate-400 text-xs col-span-full">
          Tidak dapat memuat feed berita saat ini. Silakan klik tombol Perbarui.
        </div>
      `;
    }
  } finally {
    isNewsLoading = false;
    if (refreshLabel) refreshLabel.textContent = 'Perbarui';
    if (refreshBtn) refreshBtn.disabled = false;
  }
}

function setNewsCategoryFilter(cat) {
  activeNewsCategory = cat;
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
  if (!listEl) return;

  if (!items || items.length === 0) {
    listEl.innerHTML = `
      <div class="p-6 rounded-xl glass-subcard text-center text-slate-400 text-xs col-span-full">
        Tidak ada berita pada kategori ini saat ini.
      </div>
    `;
    return;
  }

  // Jaminan mutlak data terurut dari yang paling baru ke yang paling lama
  const sortedItems = [...items].sort((a, b) => (b.published_ts || 0) - (a.published_ts || 0));
  cachedNewsItems = sortedItems;

  listEl.innerHTML = sortedItems.map((n, idx) => {
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
        onclick="inspectNewsCorrelation(${idx})"
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
    const lotsByCap = Math.floor(capital / (entry * (1 + feeBuyPct) * 100));
    lots = Math.max(0, Math.min(lotsByRisk, lotsByCap));
  }

  const grossCost = lots * entry * 100;
  const buyFee = grossCost * feeBuyPct;
  const totalCost = Math.round(grossCost + buyFee);
  const actualRiskRp = Math.round(lots * perShareRisk * 100);
  const actualRiskPct = capital > 0 ? ((actualRiskRp / capital) * 100).toFixed(1) : '0.0';

  // Estimasi Target Profit TP1 (+6% dari harga entry) setelah dikurangi fee sekuritas roundtrip 0.4%
  const tp1Price = Math.round(entry * 1.06);
  const grossProfit = lots * (tp1Price - entry) * 100;
  const totalFee = (grossCost * feeBuyPct) + (lots * tp1Price * 100 * feeSellPct);
  const netProfit = Math.max(0, Math.round(grossProfit - totalFee));
  const netProfitPct = totalCost > 0 ? ((netProfit / totalCost) * 100).toFixed(1) : '0.0';

  if (lotEl) lotEl.textContent = `${fmtNumber(lots)} Lot (${fmtNumber(lots * 100)} Lembar)`;
  if (valEl) valEl.textContent = fmtPrice(totalCost);
  if (riskEl) riskEl.textContent = `${fmtPrice(actualRiskRp)} (${actualRiskPct}% modal)`;
  if (profitEl) profitEl.textContent = `${fmtPrice(netProfit)} (+${netProfitPct}% net)`;
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
// PENGATURAN & ALAT TEKNIS MODAL (GEAR ICON)
// =====================================================================
function openSettingsModal() {
  const modal = document.getElementById('settingsModal');
  if (modal) {
    modal.classList.remove('hidden');
    const current = localStorage.getItem('smartflow_theme') || 'emerald';
    selectTheme(current, false);
  }
}

function closeSettingsModal() {
  const modal = document.getElementById('settingsModal');
  if (modal) modal.classList.add('hidden');
}

function toggleExpertPillarsView() {
  const content = document.getElementById('expertPillarsContent');
  const btn = document.getElementById('btnTogglePillars');
  if (!content) return;
  const isHidden = content.classList.contains('hidden');
  content.classList.toggle('hidden', !isHidden);
  if (btn) btn.textContent = isHidden ? 'Sembunyikan Rincian' : 'Tampilkan Rincian';
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
    'text-rose-200'
  );
  if (type === 'error') {
    banner.classList.add('bg-rose-950/90', 'border-rose-500/40', 'text-rose-200');
  } else {
    banner.classList.add('bg-emerald-950/90', 'border-emerald-500/40', 'text-emerald-200');
  }
  if (text) text.textContent = msg;

  setTimeout(() => {
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
  if (!tbody) return;

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
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="py-10 text-center text-slate-400">
          Tidak ada saham yang memenuhi filter kriteria saat ini. Coba longgarkan filter di atas.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = pageStocks
    .map((s) => {
      const safeTicker = escHtml(s.ticker);
      const safeSector = escHtml(s.sector);
      const safeSecCat = s.sector_category ? escHtml(s.sector_category) : '';
      const isSelected = s.ticker === selectedTicker;
      const starActive = isFavorite(s.ticker);
      const chgColor = s.pct_change >= 0 ? 'text-emerald-400' : 'text-rose-400';

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
                onclick="toggleFavorite('${safeTicker}', event)"
                class="star-btn star-btn-${safeTicker} text-base leading-none transition ${starActive ? 'text-amber-400 drop-shadow-[0_0_8px_rgba(251,191,36,0.6)]' : 'text-slate-500 hover:text-amber-300'}"
                title="Simpan ke Favorit"
              >
                ${starActive ? '★' : '☆'}
              </button>
              ${getStockLogoImg(s.ticker, 'w-8 h-8')}
              <div>
                <div class="flex items-center gap-1.5">
                  <div class="font-mono font-black text-sm text-slate-900 dark:text-white">${safeTicker}</div>
                  ${safeSecCat ? `<span class="text-[9px] font-sans font-bold px-1.5 py-0.2 rounded bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 border border-slate-200 dark:border-slate-700">${safeSecCat}</span>` : ''}
                </div>
                <div class="text-[10px] text-slate-400 truncate max-w-[120px]">${safeSector}</div>
              </div>
            </div>
          </td>

          <!-- Price -->
          <td class="py-3 px-2 text-right font-mono font-bold text-slate-900 dark:text-white text-xs">
            ${fmtPrice(s.close)}
          </td>

          <!-- Change -->
          <td class="py-3 px-2 text-right font-mono text-xs font-bold ${chgColor}">
            ${fmtSignPct(s.pct_change)}
          </td>

          <!-- Volume Spike Badge & Status Pantauan -->
          <td class="py-3 px-2 text-center font-mono">
            <span class="inline-block px-2.5 py-0.5 rounded-full text-[10px] font-bold ${s.vol_ratio >= 1.5 ? 'bg-orange-100 text-orange-800 border border-orange-200 dark:bg-amber-500/15 dark:text-amber-300 dark:border-amber-400/35 shadow-[0_0_12px_rgba(245,158,11,0.15)]' : 'bg-slate-100 text-slate-700 border border-slate-200 dark:bg-emerald-500/15 dark:text-emerald-300 dark:border-emerald-400/30 shadow-[0_0_10px_rgba(16,185,129,0.12)]'}">
              ${s.vol_ratio >= 2.0 ? 'Vol Spike' : s.vol_ratio >= 1.2 ? 'High Vol' : 'Normal'} ${s.vol_ratio.toFixed(1)}x
            </span>
            ${s.tape_quality && s.tape_quality.code !== 'ORGANIC_FLOW' ? `<span class="block text-[8px] font-bold text-amber-800 bg-amber-100 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-400 mt-0.5 font-mono px-1 py-0.2 rounded" title="${escHtml(s.tape_quality.reason)}">⚠️ ${s.tape_quality.code === 'SUSPICIOUS_CROSSING' ? 'Crossing' : s.tape_quality.code === 'UPTHRUST_DISTRIBUTION' ? 'Upthrust' : 'Thin'}</span>` : ''}
            ${s.tracker_status === 'WIN' ? '<span class="block text-[9px] font-bold text-emerald-800 bg-emerald-100 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50 mt-1 font-mono px-1 py-0.5 rounded">🏆 WIN (TP1)</span>' : s.tracker_status === 'RUNNING' ? ((s.tracker_pnl_pct || 0) < 0 ? `<span class="block text-[9px] font-bold text-rose-800 bg-rose-100 border border-rose-200 dark:bg-rose-900/30 dark:text-rose-400 dark:border-rose-800/50 mt-1 font-mono px-1 py-0.5 rounded">🔻 RUNNING ${(s.tracker_pnl_pct || 0) >= 0 ? '+' : ''}${s.tracker_pnl_pct || 0}%</span>` : `<span class="block text-[9px] font-bold text-emerald-800 bg-emerald-100 border border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-800/50 mt-1 font-mono px-1 py-0.5 rounded">🚀 RUNNING ${(s.tracker_pnl_pct || 0) >= 0 ? '+' : ''}${s.tracker_pnl_pct || 0}%</span>`) : s.tracker_status === 'WATCHLIST' ? '<span class="block text-[9px] font-bold text-blue-800 bg-blue-100 border border-blue-200 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-800/50 mt-1 font-mono px-1 py-0.5 rounded">⏳ WATCHLIST</span>' : ''}
          </td>

          <!-- Smart Money Score with Progress Bar -->
          <td class="py-3 px-2 text-right">
            <div class="flex items-center justify-end gap-2.5">
              <span class="font-mono font-extrabold text-xs text-slate-900 dark:text-white">${escHtml(s.smart_money_score)}</span>
              <div class="w-20 bg-slate-200 dark:bg-white/[0.08] h-2 rounded-full overflow-hidden">
                <div class="h-full bg-gradient-to-r from-emerald-500 to-teal-400 dark:from-emerald-400 dark:to-teal-300 rounded-full" style="width: ${Math.min(100, Math.max(0, Number(s.smart_money_score || 0)))}%"></div>
              </div>
            </div>
          </td>

          <!-- Profil VSA & VWAP 5H -->
          <td class="py-3 pl-2 pr-4 text-xs font-mono">
            <div class="text-[11px] text-slate-600 dark:text-slate-300">
              VWAP 5H: <span class="text-slate-900 dark:text-white font-bold">${fmtPrice(s.bandar_avg_buy)}</span> <span class="${s.diff_bandar_avg_pct >= 0 ? 'text-amber-500 dark:text-amber-300' : 'text-emerald-600 dark:text-emerald-400'} font-semibold">(${s.diff_bandar_avg_pct >= 0 ? '+' : ''}${s.diff_bandar_avg_pct.toFixed(1)}%)</span>
            </div>
            <div class="text-[10px] text-slate-500 dark:text-slate-400">
              CR: <span class="text-slate-800 dark:text-slate-200 font-semibold">${escHtml(s.closing_range_pct)}%</span> · Val: <span class="text-slate-800 dark:text-slate-200">Rp ${escHtml(s.value_b_idr)} M</span>
            </div>
          </td>
        </tr>
      `;
    })
    .join('');
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
    noteEl.textContent = d.has_news
      ? v.note
      : 'Tidak ada berita terbaru untuk emiten ini. Keputusan bertumpu pada 5 Pilar kuantitatif dan rencana eksekusi di bawah.';
    newsEl.innerHTML = (d.news || []).map(n => `
      <div class="text-[11px] text-slate-400">
        <span class="font-mono text-[10px]">${escHtml(n.source || '')} · ${escHtml(n.published_at || '')}</span>
        ${n.link ? `<a href="${escHtml(n.link)}" target="_blank" rel="noopener noreferrer" class="block text-slate-200 hover:text-white underline-offset-2 hover:underline">${escHtml(n.title || '')}</a>` : `<span class="block text-slate-200">${escHtml(n.title || '')}</span>`}
      </div>`).join('');
  } catch (e) {
    badge.textContent = 'Data berita tidak tersedia';
    if (factorsEl) factorsEl.innerHTML = '';
    if (noteEl) noteEl.textContent = '';
    if (newsEl) newsEl.innerHTML = '';
  }
}

async function selectStock(ticker, isUserClick = false, scrollToTradingPlan = false) {
  selectedTicker = ticker;

  document.querySelectorAll('.stock-row').forEach((el) => el.classList.remove('selected-row'));
  const activeRow = document.getElementById(`row-${ticker}`);
  if (activeRow) activeRow.classList.add('selected-row');

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
          <span>Posisi Aktif (${(plan.pnl_pct || 0) >= 0 ? '+' : ''}${plan.pnl_pct || 0}%)</span>
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
function openGuideModal() {
  document.getElementById('guideModal')?.classList.remove('hidden');
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
  const pill = document.getElementById('marketLivePill');
  const dot = document.getElementById('marketStatusDot');
  const text = document.getElementById('marketStatusText');
  const timer = document.getElementById('marketAutoTimer');

  if (!pill) return;

  if (isLive) {
    if (dot) dot.className = 'w-2 h-2 rounded-full bg-emerald-400 animate-pulse';
    if (text) {
      text.textContent = 'BURSA LIVE';
      text.className = 'font-bold text-emerald-300 text-[11px] sm:text-xs';
    }
    if (timer) timer.textContent = 'Auto-Sync 60s';
  } else {
    if (dot) dot.className = 'w-2 h-2 rounded-full bg-slate-500';
    if (text) {
      text.textContent = 'BURSA TUTUP';
      text.className = 'font-bold text-slate-400 text-[11px] sm:text-xs';
    }
    if (timer) timer.textContent = 'Data Terakhir 16:00';
  }
}

function initLiveMarketAutoSync() {
  updateMarketLiveStatusUI();

  if (keepAliveTimerId) clearInterval(keepAliveTimerId);
  keepAliveTimerId = setInterval(() => {
    if (isIDXMarketOpenNow()) {
      fetch(`/api/health?_t=${Date.now()}`, { cache: 'no-store' }).catch(() => {});
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
    ALL: s.total,
    WATCHLIST: s.watchlist,
    RUNNING: s.running,
    WIN: s.win,
    LOSS: s.loss,
    CLOSED_OTHER: (s.expired || 0) + (s.timeout || 0) + (s.cancelled || 0),
    EXPIRED: s.expired,
    TIMEOUT: s.timeout,
  };
  document.querySelectorAll('#trackerTabs .tracker-tab').forEach((btn) => {
    const tab = btn.dataset.tab;
    const label = btn.textContent.replace(/\s*\d+$/, '').trim();
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
  if (!tbody) return;

  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="10" class="py-8 text-center text-slate-400">
      Belum ada sinyal pada kategori ini. Sinyal akumulasi dengan score tinggi akan otomatis tercatat setelah sinkronisasi data real.
    </td></tr>`;
    return;
  }

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
      const entryCell = r.entry_price
        ? `${fmtNumber(r.entry_price)}<div class="text-[10px] text-slate-500 font-medium dark:text-slate-400">${escHtml(r.entry_date || '')}</div>`
        : r.status === 'WATCHLIST' && r.dist_to_entry_pct !== undefined
        ? `<span class="text-slate-400 dark:text-slate-500">-</span><div class="text-[10px] text-slate-500 font-medium dark:text-slate-400">jarak ${fmtPctOrDash(r.dist_to_entry_pct)}</div>`
        : '<span class="text-slate-400 dark:text-slate-500">-</span>';

      let isHighFlyer = false;
      if (r.status === 'RUNNING' && pnl !== null && pnl >= 2.0) {
        isHighFlyer = true;
      }

      const noteText = String(r.note || '');
      const safeNote = escHtml(noteText);
      const hasDistWarning = noteText.startsWith('⚠️');

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
                ${isHighFlyer ? '<span class="text-xs" title="Terbang Tinggi">🚀</span>' : ''}
                ${hasDistWarning ? `<span class="text-xs animate-pulse" title="${safeNote}">⚠️</span>` : ''}
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
          ${hasDistWarning ? `<div class="mt-1 text-[9px] font-extrabold text-rose-800 bg-rose-100 border border-rose-200 dark:text-rose-300 dark:bg-rose-500/20 dark:border-rose-500/40 rounded px-1.5 py-0.5 animate-pulse" title="${safeNote}">⚠️ AWAS DISTRIBUSI</div>` : ''}
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

function setTrackerTab(tab) {
  trackerTab = tab;
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
  if (activeMainTab === 'today' && currentStocks && currentStocks.length > 0) {
    renderTodayCandidates(currentStocks);
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

async function loadIhsgTodayChart(period = '3mo') {
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

    const res = await fetch(`/api/ihsg/candles?period=${encodeURIComponent(period)}&_t=${Date.now()}`, { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    lastIhsgChartData = data;
    renderIhsgTodayChart(data);
  } catch (err) {
    console.warn('[IHSGChart] Gagal memuat grafik IHSG:', err);
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
    const res = await fetch(`/api/portfolio?status=${encodeURIComponent(status)}&_t=${Date.now()}`);
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
  }
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
    if (pInput && (!pInput.value || pInput.value === '0')) {
      pInput.value = plan.entry_price || plan.entry_high || stock.close;
    }
    if (slInput && !slInput.value && plan.stop_loss) {
      slInput.value = plan.stop_loss;
    }
    if (tpInput && !tpInput.value && plan.target_1) {
      tpInput.value = plan.target_1;
    }
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
  closeSettingsModal();
  closeLotCalculatorModal();
  closeGlossaryModal();
  closeUploadModal();
  closeGuideModal();
  closeTradingViewModal();
  closeMarketRegimeModal();
  closePortfolioBuyModal();
  closePortfolioSellModal();
}

window.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeAllModals();
  }
});

// Tutup modal jika user mengklik backdrop / area hitam di luar modal
document.querySelectorAll('#settingsModal, #lotCalculatorModal, #glossaryModal, #uploadModal, #guideModal, #tradingViewModal, #marketRegimeModal, #portfolioBuyModal, #portfolioSellModal').forEach(modalEl => {
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
  switchMainTab(activeMainTab);

  // 2. Muat data awal secepat mungkin
  // Modul independen & paralel: kegagalan/keterlambatan satu modul tidak menahan modul lain
  const initTasks = [
    ['screener', () => loadScreenerData(false)],
    ['tracker', () => loadTracker()],
    ['portfolio', () => loadPortfolio()],
    ['regime', () => loadMarketRegime()],
    ['ihsg', () => loadIhsgTodayChart('3mo')],
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

  // 7. Muat berita pasar terkini untuk tab Pilihan Hari Ini
  loadMarketNews(false);
});
