"""
FastAPI Backend Server untuk SmartFlow IDX - Smart Money Stock Screener (v4.0 - 24/7 Cloud & Auto-Sync Ready).
Fitur 24 Jam:
1. Background Auto-Sync Scheduler: Otomatis menarik data harga & volume terbaru dari BEI (Yahoo Finance .JK)
   secara berkala di latar belakang tanpa menghentikan layanan.
2. Siap Deploy 24/7 ke Cloud (Render, Railway, Hugging Face Spaces Docker, VPS) maupun Windows Service.
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Pastikan direktori backend masuk ke sys.path baik dijalankan dari root maupun folder backend/
BACKEND_DIR = Path(__file__).resolve().parent
BASE_DIR = BACKEND_DIR.parent
for p in (str(BASE_DIR), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from excel_generator import (
    build_excel_bytes,
    ensure_default_excel_files,
    generate_900_idx_master_tickers_df,
)
from live_idx_fetcher import fetch_real_idx_market_data
from portfolio_tracker import PortfolioTracker
from signal_tracker import SignalTracker
from telegram_notifier import (
    filter_smart_telegram_picks,
    format_telegram_broadcast,
    format_test_message,
    format_tracker_event_message,
    load_telegram_config,
    save_telegram_config,
    send_telegram_message,
)
from screener_engine import (
    analyze_smart_money_dataframe,
    enrich_master_ticker_list,
    read_multiple_uploaded_files,
    read_uploaded_file,
)

BASE_DIR = BACKEND_DIR.parent
DATA_DIR = BASE_DIR / "data"
FRONTEND_DIR = BASE_DIR / "frontend"
USER_EXCEL_DIR = BASE_DIR / "data" / "user_excel"
REAL_CACHE_CSV = BASE_DIR / "data" / "real_idx_market_latest.csv"
MASTER_UPLOADED_CSV = BASE_DIR / "data" / "master_uploaded_tickers.csv"

# Interval Auto-Sync dalam detik (default: setiap 15 menit = 900 detik)
AUTO_SYNC_INTERVAL_SECONDS = int(os.environ.get("AUTO_SYNC_INTERVAL", "900"))

STATE: dict = {
    "source_name": "Daftar Saham IDX - REAL Market Data",
    "analysis": None,
    "last_sync_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "is_syncing": False,
    "auto_sync_interval_min": AUTO_SYNC_INTERVAL_SECONDS // 60,
    "is_real_market": False,
    "last_tracker_run": None,
}

TRACKER = SignalTracker(BASE_DIR / "data" / "tracker.db")
PORTFOLIO = PortfolioTracker(BASE_DIR / "data" / "tracker.db")
LAST_DAILY_BROADCAST_DATE: str | None = None


def sync_tracker_to_analysis(analysis: dict | None) -> None:
    """Sinkronkan status riil dari database tracker (WATCHLIST, RUNNING, WIN, LOSS)
    ke objek saham dan trading_plan agar Tab Hari Ini, Screener, dan Inspector 100% konsisten dengan Pantauan."""
    if not analysis or "stocks" not in analysis or "details" not in analysis:
        return

    sig_map = TRACKER.get_latest_signals_map()
    if not sig_map:
        return

    for stock in analysis["stocks"]:
        t = str(stock.get("ticker", "")).upper()
        if t in sig_map:
            sig = sig_map[t]
            st = str(sig.get("status", "")).upper()
            stock["tracker_status"] = st
            stock["tracker_pnl_pct"] = sig.get("pnl_pct")
            stock["tracker_entry_price"] = sig.get("entry_price")
            stock["tracker_signal_date"] = sig.get("signal_date")

            plan = stock.get("trading_plan") or {}
            plan["status"] = st
            plan["tracker_id"] = sig["id"]
            plan["signal_date"] = sig.get("signal_date")
            e_p = sig.get("entry_price") or sig.get("entry_high") or sig.get("entry_low")
            if e_p:
                plan["entry_price"] = float(e_p)
                plan["entry_high"] = float(e_p)
                plan["entry_low"] = float(e_p)
            if sig.get("stop_loss") is not None:
                plan["stop_loss"] = float(sig["stop_loss"])
            if sig.get("target") is not None:
                plan["target_1"] = float(sig["target"])
            if sig.get("target_2") is not None:
                plan["target_2"] = float(sig["target_2"])
            if e_p and float(e_p) > 0:
                base_ep = float(e_p)
                if plan.get("stop_loss"):
                    plan["stop_loss_pct"] = round(((plan["stop_loss"] - base_ep) / base_ep) * 100.0, 2)
                if plan.get("target_1"):
                    plan["target_1_pct"] = round(((plan["target_1"] - base_ep) / base_ep) * 100.0, 2)
                if plan.get("target_2"):
                    plan["target_2_pct"] = round(((plan["target_2"] - base_ep) / base_ep) * 100.0, 2)
            if sig.get("pnl_pct") is not None:
                plan["pnl_pct"] = float(sig["pnl_pct"])
            if sig.get("last_close") and float(sig["last_close"]) > 0:
                stock["close"] = int(round(float(sig["last_close"])))

            if st == "WIN":
                pnl = sig.get("pnl_pct", 0)
                plan["action_bias"] = f"🏆 TARGET TERCAPAI (WIN +{pnl}%)"
                plan["rationale"] = f"Target untung (TP1) telah tercapai (+{pnl}%). Rencana trading selesai (Take Profit)."
            elif st == "RUNNING":
                pnl = float(sig.get("pnl_pct", 0) or 0)
                icon = "🔻" if pnl < 0 else "🚀"
                plan["action_bias"] = f"{icon} POSISI AKTIF ({pnl:+.1f}%)"
                plan["rationale"] = f"Posisi beli aktif sejak {sig.get('entry_date', sig.get('signal_date'))} @ Rp {float(sig.get('entry_price', 0)):,.0f}."
            elif st == "WATCHLIST":
                plan["action_bias"] = "⏳ MENUNGGU ENTRY (WATCHLIST)"
                plan["rationale"] = f"Sinyal aktif di Watchlist sejak {sig.get('signal_date')}. Menunggu harga menyentuh area beli."
            elif st == "LOSS":
                pnl = sig.get("pnl_pct", 0)
                plan["action_bias"] = f"🛑 CUT LOSS ({pnl}%)"
                plan["rationale"] = f"Posisi ditutup disiplin batas rugi pada {sig.get('exit_date', sig.get('signal_date'))}."
            elif st in ("EXPIRED", "TIMEOUT", "CANCELLED"):
                plan["action_bias"] = f"⏹️ KADALUARSA ({st})"
                plan["rationale"] = f"Sinyal ditutup ({st}) karena melewati batas waktu toleransi."

            stock["trading_plan"] = plan

    for t, detail in analysis["details"].items():
        t_up = str(t).upper()
        if t_up in sig_map:
            sig = sig_map[t_up]
            st = str(sig.get("status", "")).upper()
            detail["tracker_status"] = st
            detail["tracker_pnl_pct"] = sig.get("pnl_pct")
            detail["tracker_entry_price"] = sig.get("entry_price")
            detail["tracker_signal_date"] = sig.get("signal_date")

            plan = detail.get("trading_plan") or {}
            plan["status"] = st
            plan["tracker_id"] = sig["id"]
            plan["signal_date"] = sig.get("signal_date")
            e_p = sig.get("entry_price") or sig.get("entry_high") or sig.get("entry_low")
            if e_p:
                plan["entry_price"] = float(e_p)
                plan["entry_high"] = float(e_p)
                plan["entry_low"] = float(e_p)
            if sig.get("stop_loss") is not None:
                plan["stop_loss"] = float(sig["stop_loss"])
            if sig.get("target") is not None:
                plan["target_1"] = float(sig["target"])
            if sig.get("target_2") is not None:
                plan["target_2"] = float(sig["target_2"])
            if e_p and float(e_p) > 0:
                base_ep = float(e_p)
                if plan.get("stop_loss"):
                    plan["stop_loss_pct"] = round(((plan["stop_loss"] - base_ep) / base_ep) * 100.0, 2)
                if plan.get("target_1"):
                    plan["target_1_pct"] = round(((plan["target_1"] - base_ep) / base_ep) * 100.0, 2)
                if plan.get("target_2"):
                    plan["target_2_pct"] = round(((plan["target_2"] - base_ep) / base_ep) * 100.0, 2)
            if sig.get("pnl_pct") is not None:
                plan["pnl_pct"] = float(sig["pnl_pct"])
            if sig.get("last_close") and float(sig["last_close"]) > 0:
                lc = int(round(float(sig["last_close"])))
                detail["close"] = lc
                if detail.get("history") and len(detail["history"]) > 0:
                    detail["history"][-1]["close"] = lc
                    if lc > detail["history"][-1].get("high", lc):
                        detail["history"][-1]["high"] = lc
                    if lc < detail["history"][-1].get("low", lc):
                        detail["history"][-1]["low"] = lc

            if st == "WIN":
                pnl = sig.get("pnl_pct", 0)
                plan["action_bias"] = f"🏆 TARGET TERCAPAI (WIN +{pnl}%)"
                plan["rationale"] = f"Target untung (TP1) telah tercapai (+{pnl}%). Rencana trading selesai (Take Profit)."
            elif st == "RUNNING":
                pnl = float(sig.get("pnl_pct", 0) or 0)
                icon = "🔻" if pnl < 0 else "🚀"
                plan["action_bias"] = f"{icon} POSISI AKTIF ({pnl:+.1f}%)"
                plan["rationale"] = f"Posisi beli aktif sejak {sig.get('entry_date', sig.get('signal_date'))} @ Rp {float(sig.get('entry_price', 0)):,.0f}."
            elif st == "WATCHLIST":
                plan["action_bias"] = "⏳ MENUNGGU ENTRY (WATCHLIST)"
                plan["rationale"] = f"Sinyal aktif di Watchlist sejak {sig.get('signal_date')}. Menunggu harga menyentuh area beli."
            elif st == "LOSS":
                pnl = sig.get("pnl_pct", 0)
                plan["action_bias"] = f"🛑 CUT LOSS ({pnl}%)"
                plan["rationale"] = f"Posisi ditutup disiplin batas rugi pada {sig.get('exit_date', sig.get('signal_date'))}."
            elif st in ("EXPIRED", "TIMEOUT", "CANCELLED"):
                plan["action_bias"] = f"⏹️ KADALUARSA ({st})"
                plan["rationale"] = f"Sinyal ditutup ({st}) karena melewati batas waktu toleransi."

            detail["trading_plan"] = plan


def _process_tracker(analysis: dict, sync_live_network: bool = False) -> dict:
    """Evaluasi sinyal aktif dengan candle baru, lalu catat sinyal akumulasi baru ke Watchlist.
    Hanya berjalan untuk data pasar REAL (bukan simulasi / upload manual)."""
    result = {"entered": 0, "win": 0, "loss": 0, "expired": 0, "timeout": 0, "added": 0, "skipped": False}
    if not STATE.get("is_real_market"):
        result["skipped"] = True
        return result
    try:
        # 1. Tarik live quotes intraday via network HANYA jika diminta eksplisit
        if sync_live_network:
            live_res = TRACKER.sync_active_signals_live()
            result.update(live_res)

        # 2. Evaluasi dataset analisis penuh (sudah berisi harga terbaru dari sync)
        if analysis and "details" in analysis:
            main_res = TRACKER.evaluate(analysis["details"])
            for k in ("entered", "win", "loss", "expired", "timeout"):
                result[k] = max(result.get(k, 0), main_res.get(k, 0))
            result["added"] = TRACKER.auto_track(analysis)
            sync_tracker_to_analysis(analysis)

            # Kirim realtime Telegram Alert jika bot sudah terkonfigurasi
            tg_cfg = load_telegram_config()
            if tg_cfg.get("bot_token") and tg_cfg.get("chat_id") and tg_cfg.get("auto_notify", True):
                for ev in main_res.get("events", []):
                    if ev.get("event") in ("WIN", "EXPIRED_GAP_DOWN", "RUNNING"):
                        alert_text = format_tracker_event_message(
                            event_type=ev["event"],
                            ticker=ev["ticker"],
                            price=ev.get("price", 0.0),
                            pnl_pct=ev.get("pnl_pct"),
                            note=ev.get("note", ""),
                        )
                        try:
                            send_telegram_message(tg_cfg["bot_token"], tg_cfg["chat_id"], alert_text)
                        except Exception as tg_err:
                            print(f"[TelegramAutoAlert] Gagal kirim notifikasi {ev['ticker']}: {tg_err}")

        STATE["last_tracker_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[Tracker] {result}")
    except Exception as exc:
        print(f"[Tracker] Error: {exc}")
    return result


class LocalPathRequest(BaseModel):
    path: str


def _run_sync_job_blocking() -> dict:
    """SATU jalur sinkronisasi: tarik pembaruan SELURUH saham BEI secara paralel
    (mode incremental 5 hari bila cache tersedia), hitung ulang indikator semua saham,
    evaluasi status Watchlist/Running, lalu kembalikan data terbaru untuk tampilan."""
    if MASTER_UPLOADED_CSV.exists():
        tickers_df = pd.read_csv(MASTER_UPLOADED_CSV)
    else:
        tickers_df = generate_900_idx_master_tickers_df()

    real_df = fetch_real_idx_market_data(tickers_df, output_csv_path=REAL_CACHE_CSV, period="auto", max_workers=2)
    real_df["Has_Broker_Summary"] = True
    analysis = analyze_smart_money_dataframe(real_df)
    del real_df
    import gc
    gc.collect()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    latest_dt = analysis["kpis"]["latest_date"]
    STATE["source_name"] = f"Live IDX ({latest_dt})"
    STATE["analysis"] = analysis
    STATE["last_sync_time"] = now_str
    STATE["is_real_market"] = True
    tracker_res = _process_tracker(analysis, sync_live_network=False)
    return {
        "status": "success",
        "message": f"Sync selesai: {analysis['kpis'].get('total_emiten', len(analysis['stocks']))} saham diperbarui (data {latest_dt}).",
        "tracker_res": tracker_res,
        "source_name": STATE["source_name"],
        "last_sync_time": STATE["last_sync_time"],
        "kpis": analysis["kpis"],
        "stocks": analysis["stocks"],
    }


# Daftar Hari Libur Resmi Bursa Efek Indonesia (BEI / IDX) 2025 - 2027
IDX_HOLIDAYS: set[str] = {
    # 2025
    "2025-01-01", "2025-01-27", "2025-01-28", "2025-01-29", "2025-03-28", "2025-03-31",
    "2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04", "2025-04-07", "2025-04-18",
    "2025-05-01", "2025-05-12", "2025-05-29", "2025-05-30", "2025-06-06", "2025-06-09",
    "2025-06-27", "2025-08-18", "2025-09-05", "2025-12-24", "2025-12-25", "2025-12-26", "2025-12-31",
    # 2026
    "2026-01-01", "2026-01-16", "2026-02-17", "2026-03-19", "2026-03-20", "2026-03-23",
    "2026-03-24", "2026-03-25", "2026-04-03", "2026-05-01", "2026-05-14", "2026-05-27",
    "2026-05-28", "2026-06-01", "2026-06-16", "2026-07-16", "2026-08-17", "2026-08-25",
    "2026-12-24", "2026-12-25", "2026-12-31",
    # 2027
    "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-09", "2027-03-10", "2027-03-26",
    "2027-04-09", "2027-05-03", "2027-05-06", "2027-05-17", "2027-05-20", "2027-06-01",
    "2027-08-17", "2027-12-24", "2027-12-25", "2027-12-31",
}


def _get_now_wib() -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Jakarta"))
    except Exception:
        from datetime import timezone, timedelta
        return datetime.now(timezone(timedelta(hours=7)))


def _is_idx_holiday(dt: datetime.date) -> bool:
    return dt.strftime("%Y-%m-%d") in IDX_HOLIDAYS


def is_idx_market_open_now() -> bool:
    """
    Mengecek apakah bursa saham BEI/IDX saat ini sedang berlangsung dengan jadwal resmi bursa:
    - Senin s/d Kamis: Sesi 1 (09:00 - 12:00 WIB), Sesi 2 (13:30 - 16:05 WIB)
    - Jumat: Sesi 1 (09:00 - 11:30 WIB), Sesi 2 (14:00 - 16:05 WIB)
    - Sabtu, Minggu, Libur Nasional, Cuti Bersama BEI: TUTUP
    """
    now = _get_now_wib()
    if now.weekday() >= 5 or _is_idx_holiday(now.date()):
        return False

    from datetime import time as dtime
    t = now.time()

    if now.weekday() == 4:  # Hari Jumat
        is_sesi_1 = dtime(9, 0) <= t <= dtime(11, 30)
        is_sesi_2 = dtime(14, 0) <= t <= dtime(16, 5)
    else:  # Senin - Kamis
        is_sesi_1 = dtime(9, 0) <= t <= dtime(12, 0)
        is_sesi_2 = dtime(13, 30) <= t <= dtime(16, 5)

    return is_sesi_1 or is_sesi_2


def _expected_latest_trading_date() -> str:
    """Mengembalikan tanggal hari bursa terakhir yang seharusnya sudah memiliki data (melewati akhir pekan & hari libur BEI)."""
    from datetime import time as dtime, timedelta
    now = _get_now_wib()
    cur = now.date()
    # Jika hari bursa aktif tapi belum jam 09:15 WIB, tanggal yang diharapkan adalah sesi hari sebelumnya
    if cur.weekday() < 5 and not _is_idx_holiday(cur) and now.time() < dtime(9, 15):
        cur -= timedelta(days=1)
    # Lewati akhir pekan dan tanggal merah bursa
    while cur.weekday() >= 5 or _is_idx_holiday(cur):
        cur -= timedelta(days=1)
    return cur.strftime("%Y-%m-%d")


def _is_cache_stale() -> bool:
    """Mengecek apakah tanggal data di STATE['analysis'] tertinggal dari tanggal bursa terakhir."""
    if not STATE.get("analysis") or "kpis" not in STATE["analysis"]:
        return True
    latest_dt = str(STATE["analysis"]["kpis"].get("latest_date", ""))
    expected_dt = _expected_latest_trading_date()
    return bool(not latest_dt or latest_dt < expected_dt)


async def _background_market_session_worker() -> None:
    """
    Worker Otomatis Jam Bursa & Penjaga Kesegaran Data Startup:
    - Saat server pertama kali menyala (atau bangun dari tidur): jika tanggal cache tertinggal dari
      hari bursa terakhir, otomatis melakukan Fast Sync (< 3s) diikuti Full Sync seluruh 844 saham!
    - Selama jam bursa aktif (09:00 - 16:10 WIB, Senin-Jumat): Otomatis memantau harga realtime,
      memperbarui tabel Screener, grafik Inspector, & status Watchlist/Running setiap 90 detik,
      serta menyimpan pembaruan penuh ke CSV setiap ~15 menit.
    """
    print("[MarketWorker] Background Market Session Worker aktif.")
    loop_count = 0
    last_sync_attempt_ts = 0.0
    import time
    while True:
        loop_count += 1
        try:
            market_open = is_idx_market_open_now()
            cache_stale = _is_cache_stale()
            now_ts = time.time()

            # Jadwal Sinkronisasi Background Terukur:
            # - Selama jam bursa aktif (market_open): interval 15 menit (900 detik) sesuai rencana awal
            # - Di luar jam bursa saat cache tertinggal: coba maksimal 1x tiap 30 menit (1800 detik) agar tidak membebani CPU/IP
            # - Saat pertama kali server dinyalakan: hanya sync jika file cache belum ada sama sekali
            should_sync = False
            if not STATE["is_syncing"]:
                if market_open and (now_ts - last_sync_attempt_ts >= 900):
                    should_sync = True
                elif cache_stale and (now_ts - last_sync_attempt_ts >= 1800):
                    should_sync = True
                elif loop_count == 1 and not REAL_CACHE_CSV.exists():
                    should_sync = True

            if should_sync:
                print(f"[MarketWorker] Menjalankan sinkronisasi background (market_open={market_open}, cache_stale={cache_stale})...")
                last_sync_attempt_ts = now_ts
                STATE["is_syncing"] = True
                try:
                    await asyncio.to_thread(_run_sync_job_blocking)
                finally:
                    STATE["is_syncing"] = False

            # Auto-Broadcast Penutupan Pasar (16:15 WIB) ke Telegram
            global LAST_DAILY_BROADCAST_DATE
            from datetime import time as dtime
            now_wib = _get_now_wib()
            today_str = now_wib.strftime("%Y-%m-%d")
            if now_wib.weekday() < 5 and not _is_idx_holiday(now_wib.date()):
                if dtime(16, 15) <= now_wib.time() <= dtime(16, 35) and LAST_DAILY_BROADCAST_DATE != today_str:
                    tg_cfg = load_telegram_config()
                    if tg_cfg.get("bot_token") and tg_cfg.get("chat_id") and tg_cfg.get("auto_notify", True):
                        try:
                            print(f"[MarketWorker] Auto-broadcasting Top Picks Penutupan Bursa ({today_str}) ke Telegram...")
                            stocks = STATE["analysis"]["stocks"] if STATE.get("analysis") else []
                            market_date = STATE["analysis"]["kpis"]["latest_date"] if STATE.get("analysis") else today_str
                            picks = filter_smart_telegram_picks(stocks=stocks, max_picks=3, max_pct_change=2.5, min_score=70)
                            bcast_text = format_telegram_broadcast(picks, market_date)
                            await asyncio.to_thread(send_telegram_message, tg_cfg["bot_token"], tg_cfg["chat_id"], bcast_text)
                            LAST_DAILY_BROADCAST_DATE = today_str
                            print("[MarketWorker] Broadcast Telegram penutupan pasar berhasil dikirim.")
                        except Exception as tg_err:
                            print(f"[MarketWorker] Error broadcast Telegram: {tg_err}")
        except Exception as exc:
            print(f"[MarketWorker] Error: {exc}")

        # Tidur 90 detik sebelum cek iterasi berikutnya
        await asyncio.sleep(90)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Mengelola siklus hidup server: Menjalankan worker market session cerdas secara otomatis."""
    market_task = asyncio.create_task(_background_market_session_worker())
    yield
    market_task.cancel()


app = FastAPI(
    title="SmartFlow IDX - On-Demand Smart Money Stock Screener API",
    description="API Backend On-Demand untuk deteksi pergerakan Smart Money dari seluruh saham IDX",
    version="4.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)


@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


def init_default_state() -> None:
    """Memuat data pasar REAL terbaru dari cache hasil sinkronisasi seluruh saham IDX."""
    ensure_default_excel_files(BASE_DIR)
    USER_EXCEL_DIR.mkdir(parents=True, exist_ok=True)

    if REAL_CACHE_CSV.exists():
        real_df = pd.read_csv(REAL_CACHE_CSV)
        real_df["Has_Broker_Summary"] = True
        STATE["source_name"] = "Daftar Saham IDX - REAL Market Data (24/7 Active)"
        STATE["analysis"] = analyze_smart_money_dataframe(real_df)
        STATE["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        STATE["is_real_market"] = True
        _process_tracker(STATE["analysis"])
        return

    master_900 = generate_900_idx_master_tickers_df()
    enriched_900 = enrich_master_ticker_list(master_900, num_days=15)
    STATE["source_name"] = "daftar_900_emiten_idx.xlsx (900 Emiten IDX)"
    STATE["is_real_market"] = False
    STATE["analysis"] = analyze_smart_money_dataframe(enriched_900)
    STATE["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sync_tracker_to_analysis(STATE["analysis"])


init_default_state()


@app.get("/api/health")
def health_check() -> dict:
    """Endpoint Health Check untuk pemantauan server Cloud & Keep-Alive anti-sleep."""
    return {
        "status": "online",
        "market_open": is_idx_market_open_now(),
        "last_sync_time": STATE["last_sync_time"],
        "last_tracker_run": STATE["last_tracker_run"],
        "is_syncing": STATE["is_syncing"],
        "total_emiten": STATE["analysis"]["kpis"]["total_emiten"] if STATE["analysis"] else 0,
    }


@app.get("/api/screener")
def get_screener_data(
    trigger: Optional[str] = Query(default="ALL", description="Filter berdasarkan tipe trigger Smart Money"),
    min_score: int = Query(default=0, ge=0, le=100, description="Minimum Smart Money Score (0-100)"),
    min_vol_ratio: float = Query(default=0.0, ge=0.0, description="Minimum Volume Spike Ratio terhadap MA20"),
    search: Optional[str] = Query(default="", description="Cari kode Ticker atau Sektor"),
    sort_by: str = Query(default="score", description="Urutkan hasil: score, vol_ratio, top3_bsr, foreign, pct_change"),
) -> dict:
    if STATE["analysis"] is None:
        init_default_state()

    analysis = STATE["analysis"]
    stocks = list(analysis["stocks"])

    if trigger and isinstance(trigger, str) and trigger.upper() != "ALL":
        if trigger.upper() == "ACCUM_ALL":
            stocks = [
                s
                for s in stocks
                if s["trigger_type"] in ("MARKUP_BREAKOUT", "BIG_ACCUMULATION", "SILENT_ACCUMULATION", "FOREIGN_INFLOW")
            ]
        else:
            stocks = [s for s in stocks if s["trigger_type"] == trigger.upper()]

    if isinstance(min_score, int) and min_score > 0:
        stocks = [s for s in stocks if s["smart_money_score"] >= min_score]

    if isinstance(min_vol_ratio, (int, float)) and min_vol_ratio > 0:
        stocks = [s for s in stocks if s["vol_ratio"] >= min_vol_ratio]

    if search and isinstance(search, str) and search.strip():
        q_raw = search.strip().upper()
        # Prioritas 1: Jika pengguna mengetik kode saham persis (misal: BBCA, ASPI, ADRO),
        # tampilkan HANYA 1 saham tersebut sesuai permintaan pengguna.
        exact_matches = [s for s in stocks if s["ticker"].upper() == q_raw]
        if exact_matches:
            stocks = exact_matches
        else:
            q = q_raw.lower()
            # Prioritas 2: Pencarian awalan ticker
            prefix_matches = [s for s in stocks if s["ticker"].lower().startswith(q)]
            if prefix_matches:
                stocks = prefix_matches
            else:
                stocks = [
                    s
                    for s in stocks
                    if q in s["ticker"].lower()
                    or q in s["sector"].lower()
                    or q in s["trigger_label"].lower()
                    or q in s["top_buyers"].lower()
                ]

    sort_key_map = {
        "score": lambda x: (x["smart_money_score"], x["vol_ratio"]),
        "score_desc": lambda x: (x["smart_money_score"], x["vol_ratio"]),
        "vol_ratio": lambda x: (x["vol_ratio"], x["smart_money_score"]),
        "vwap": lambda x: (-abs(float(x.get("diff_bandar_avg_pct", 0) or 0)), x["smart_money_score"]),
        "top3_bsr": lambda x: (x["top3_bsr"], x["smart_money_score"]),
        "foreign": lambda x: (x["net_foreign_pct"], x["smart_money_score"]),
        "pct_change": lambda x: (x["pct_change"], x["smart_money_score"]),
    }
    stocks.sort(key=sort_key_map.get(sort_by, sort_key_map["score"]), reverse=True)

    return {
        "source_name": STATE["source_name"],
        "last_sync_time": STATE["last_sync_time"],
        "is_syncing": STATE["is_syncing"],
        "auto_sync_interval_min": STATE["auto_sync_interval_min"],
        "kpis": analysis["kpis"],
        "count": len(stocks),
        "stocks": stocks,
    }


@app.get("/api/stock/{ticker}")
def get_stock_detail(ticker: str) -> dict:
    if STATE["analysis"] is None:
        init_default_state()

    key = ticker.strip().upper()
    details_map = STATE["analysis"]["details"]
    if key not in details_map:
        raise HTTPException(status_code=404, detail=f"Saham '{key}' tidak ditemukan pada dataset aktif.")
    return details_map[key]


def _fetch_ticker_candles_blocking(ticker: str, period: str = "6mo") -> list[dict]:
    import yfinance as yf

    valid_periods = {"1mo": "1mo", "3mo": "3mo", "6mo": "6mo", "1y": "1y"}
    yf_period = valid_periods.get(period, "6mo")
    try:
        t_obj = yf.Ticker(f"{ticker}.JK")
        sub = t_obj.history(period=yf_period, interval="1d", auto_adjust=False)
        if sub is not None and not sub.empty:
            sub = sub.dropna(subset=["Close"]).copy()
            sub = sub[sub["Close"] > 0].reset_index()
            date_col = "Date" if "Date" in sub.columns else sub.columns[0]
            sub["date"] = pd.to_datetime(sub[date_col]).dt.strftime("%Y-%m-%d")
            candles = []
            for _, row_b in sub.iterrows():
                c_val = int(round(float(row_b["Close"])))
                o_val = int(round(float(row_b.get("Open", c_val)) or c_val))
                h_val = int(round(max(float(row_b.get("High", c_val)) or c_val, c_val, o_val)))
                l_val = int(round(min(float(row_b.get("Low", c_val)) or c_val, c_val, o_val)))
                vol_lot = int(round(max(0.0, float(row_b.get("Volume", 0) or 0)) / 100.0))
                candles.append({
                    "date": str(row_b["date"]),
                    "open": o_val,
                    "high": h_val,
                    "low": l_val,
                    "close": c_val,
                    "volume_lot": vol_lot,
                })
            if candles:
                return candles
    except Exception as exc:
        print(f"[CandlesAPI] Fallback ke history lokal untuk {ticker}: {exc}")
    return []


@app.get("/api/stock/{ticker}/candles")
async def get_stock_candles(ticker: str, period: str = Query(default="6mo")) -> dict:
    if STATE["analysis"] is None:
        init_default_state()

    key = ticker.strip().upper()
    details_map = STATE["analysis"]["details"]
    detail = details_map.get(key, {})

    # Prioritaskan data histori lokal dari memori/cache (< 1ms) agar UI instan dan tidak membebani network
    candles = []
    if detail and detail.get("history") and len(detail["history"]) >= 5:
        candles = [
            {
                "date": h["date"],
                "open": h["open"],
                "high": h["high"],
                "low": h["low"],
                "close": h["close"],
                "volume_lot": h.get("volume_lot", 0),
            }
            for h in detail["history"]
        ]
    else:
        candles = await asyncio.to_thread(_fetch_ticker_candles_blocking, key, period)

    if candles and detail and detail.get("close"):
        lc = int(round(float(detail["close"])))
        candles[-1]["close"] = lc
        if lc > candles[-1]["high"]:
            candles[-1]["high"] = lc
        if lc < candles[-1]["low"]:
            candles[-1]["low"] = lc

    return {
        "ticker": key,
        "sector": detail.get("sector", "IDX Emiten"),
        "trigger_label": detail.get("trigger_label", ""),
        "smart_money_score": detail.get("smart_money_score", 0),
        "trading_plan": detail.get("trading_plan", {}),
        "candles": candles,
    }


@app.post("/api/sync")
@app.post("/api/sync-live")
@app.post("/api/sync-fast")
async def sync_unified_market_data() -> dict:
    """Satu jalur sinkronisasi non-blocking: langsung merespon ke frontend agar koneksi HTTP
    tidak tertutup timeout (ERR_CONNECTION_CLOSED), sementara proses unduh & kalkulasi 844 saham
    berjalan aman di background thread."""
    if STATE["is_syncing"]:
        return {
            "status": "already_running",
            "message": "Sinkronisasi seluruh saham sedang berlangsung di background...",
            "is_syncing": True,
            "source_name": STATE["source_name"],
            "last_sync_time": STATE["last_sync_time"],
            "kpis": STATE["analysis"]["kpis"] if STATE["analysis"] else {},
            "stocks": STATE["analysis"]["stocks"] if STATE["analysis"] else [],
        }

    async def _async_sync_runner():
        STATE["is_syncing"] = True
        try:
            print("[SyncAPI] Memulai proses sinkronisasi background aman...")
            await asyncio.to_thread(_run_sync_job_blocking)
            print("[SyncAPI] Sinkronisasi background selesai dengan sukses.")
        except Exception as exc:
            print(f"[SyncAPI] Error sinkronisasi background: {exc}")
        finally:
            STATE["is_syncing"] = False

    asyncio.create_task(_async_sync_runner())
    return {
        "status": "started",
        "message": "Sinkronisasi 844 saham telah dimulai di server...",
        "is_syncing": True,
        "source_name": STATE["source_name"],
        "last_sync_time": STATE["last_sync_time"],
        "kpis": STATE["analysis"]["kpis"] if STATE["analysis"] else {},
        "stocks": STATE["analysis"]["stocks"] if STATE["analysis"] else [],
    }


@app.get("/api/backtest/summary")
def get_backtest_summary() -> dict:
    """Mengembalikan ringkasan hasil backtesting walk-forward historis tanpa look-ahead bias."""
    try:
        report_6m = DATA_DIR / "backtest_6m_report.json"
        if report_6m.exists():
            import json
            with open(report_6m, "r", encoding="utf-8") as f:
                return json.load(f)
        if REAL_CACHE_CSV.exists():
            df_cache = pd.read_csv(REAL_CACHE_CSV)
            try:
                from backend.backtest_engine import run_historical_backtest
            except ImportError:
                from backtest_engine import run_historical_backtest
            return run_historical_backtest(df_cache)
        return {"error": "Cache data pasar belum tersedia."}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal menjalankan backtest: {exc}") from exc


@app.post("/api/upload")
async def upload_excel_files(
    files: Optional[list[UploadFile]] = File(default=None),
    file: Optional[UploadFile] = File(default=None),
) -> dict:
    upload_list: list[UploadFile] = []
    if files:
        upload_list.extend(files)
    if file:
        upload_list.append(file)

    if not upload_list:
        raise HTTPException(status_code=400, detail="Tidak ada file yang diunggah.")

    files_payload: list[tuple[bytes, str]] = []
    for uf in upload_list:
        if not uf.filename:
            continue
        ext = uf.filename.lower()
        if not (ext.endswith(".xlsx") or ext.endswith(".xls") or ext.endswith(".csv")):
            raise HTTPException(
                status_code=400,
                detail=f"Format file '{uf.filename}' tidak didukung. Gunakan .xlsx, .xls, atau .csv.",
            )
        raw_bytes = await uf.read()
        files_payload.append((raw_bytes, uf.filename))

    try:
        if len(files_payload) == 1:
            df = read_uploaded_file(files_payload[0][0], files_payload[0][1])
            src_label = f"{files_payload[0][1]} (Real Market Data)"
        else:
            df = read_multiple_uploaded_files(files_payload)
            src_label = f"{len(files_payload)} File Excel Digabung (Real Market Data)"

        analysis = analyze_smart_money_dataframe(df)
        STATE["source_name"] = src_label
        STATE["analysis"] = analysis
        STATE["is_real_market"] = False
        STATE["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "status": "success",
            "message": f"Berhasil memuat & menganalisis {analysis['kpis']['total_emiten']} saham aktif IDX dari {src_label}!",
            "source_name": STATE["source_name"],
            "last_sync_time": STATE["last_sync_time"],
            "kpis": analysis["kpis"],
            "stocks": analysis["stocks"],
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal memproses file Excel: {exc}") from exc


@app.post("/api/load-path")
def load_excel_from_local_path(req: LocalPathRequest) -> dict:
    raw_path = req.path.strip().strip('"').strip("'")
    target = Path(raw_path).resolve()
    # Proteksi Keamanan: Hanya izinkan akses file/folder di dalam direktori aplikasi
    try:
        target.relative_to(BASE_DIR.resolve())
    except ValueError:
        raise HTTPException(
            status_code=403,
            detail="Akses ditolak: File atau folder harus berada di dalam direktori data aplikasi.",
        )

    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Lokasi file/folder tidak ditemukan: {raw_path}")

    try:
        if target.is_dir():
            excel_files = sorted(
                [
                    p
                    for p in target.iterdir()
                    if p.is_file() and p.suffix.lower() in (".xlsx", ".xls", ".csv") and not p.name.startswith("~$")
                ]
            )
            if not excel_files:
                raise HTTPException(status_code=400, detail=f"Tidak ada file .xlsx/.xls/.csv di dalam folder {raw_path}")
            payload = [(p.read_bytes(), p.name) for p in excel_files]
            df = read_multiple_uploaded_files(payload)
            src_label = f"{target.name}/ ({len(excel_files)} file)"
        else:
            df = read_uploaded_file(target.read_bytes(), target.name)
            src_label = f"{target.name} (Real Market Data)"

        analysis = analyze_smart_money_dataframe(df)
        STATE["source_name"] = src_label
        STATE["analysis"] = analysis
        STATE["is_real_market"] = False
        STATE["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "status": "success",
            "message": f"Berhasil memuat {analysis['kpis']['total_emiten']} saham IDX dari {src_label}!",
            "source_name": STATE["source_name"],
            "last_sync_time": STATE["last_sync_time"],
            "kpis": analysis["kpis"],
            "stocks": analysis["stocks"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Gagal membaca file dari path tersebut: {exc}") from exc


@app.post("/api/reset")
def reset_to_sample_data() -> dict:
    init_default_state()
    return {
        "status": "success",
        "source_name": STATE["source_name"],
        "last_sync_time": STATE["last_sync_time"],
        "kpis": STATE["analysis"]["kpis"],
        "stocks": STATE["analysis"]["stocks"],
    }


@app.get("/api/template")
def download_excel_template(mode: Literal["sample", "blank"] = Query(default="sample")) -> Response:
    excel_bytes = build_excel_bytes(mode=mode)
    filename = "smart_money_idx_sample_25days.xlsx" if mode == "sample" else "smart_money_blank_template.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ===================== SIGNAL TRACKER / FORWARD TEST =====================


@app.get("/api/tracker/stats")
def tracker_stats() -> dict:
    return {
        "config": TRACKER.config(),
        "stats": TRACKER.stats(),
        "last_tracker_run": STATE.get("last_tracker_run"),
        "is_real_market": STATE.get("is_real_market"),
    }


@app.get("/api/tracker/signals")
def tracker_signals(
    status: str = Query(default="ALL"),
    sort_by: str = Query(default="id_desc", description="Urutkan sinyal: pnl_desc, pnl_asc, score_desc, date_desc, ticker_asc"),
) -> dict:
    rows = TRACKER.list_signals(status=status, sort_by=sort_by)
    return {"count": len(rows), "signals": rows}


@app.post("/api/tracker/add/{ticker}")
def tracker_add(ticker: str) -> dict:
    key = ticker.strip().upper()
    details = STATE["analysis"]["details"] if STATE["analysis"] else {}
    if key not in details:
        raise HTTPException(status_code=404, detail=f"Saham '{key}' tidak ditemukan pada dataset aktif.")
    ok, msg = TRACKER.add_signal(details[key], source="MANUAL")
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@app.post("/api/tracker/evaluate")
async def tracker_evaluate() -> dict:
    if STATE["analysis"] is None:
        init_default_state()
    result = await asyncio.to_thread(_process_tracker, STATE["analysis"])
    if result.get("skipped"):
        msg = "Evaluasi dilewati: dataset aktif bukan data pasar real. Klik 'Sync Harga Real' terlebih dahulu."
    else:
        msg = (
            f"Evaluasi selesai: {result['added']} sinyal baru, {result['entered']} entry, "
            f"{result['win']} win, {result['loss']} loss, {result['expired']} expired, {result['timeout']} timeout."
        )
    return {"status": "success", "result": result, "message": msg}


@app.delete("/api/tracker/signals/{signal_id}")
def tracker_delete(signal_id: int) -> dict:
    if not TRACKER.delete_signal(signal_id):
        raise HTTPException(status_code=404, detail="Sinyal tidak ditemukan.")
    return {"status": "success", "message": "Sinyal dihapus."}


@app.post("/api/tracker/reset")
def tracker_reset() -> dict:
    if not REAL_CACHE_CSV.exists():
        n = TRACKER.reset_all()
        return {"status": "success", "message": f"{n} catatan sinyal dihapus. Cache pasar belum tersedia."}

    real_df = pd.read_csv(REAL_CACHE_CSV)
    summary = TRACKER.rebuild_recent_days(real_df, days=10)
    sync_tracker_to_analysis(STATE.get("analysis"))
    return {
        "status": "success",
        "message": f"Tracker berhasil di-rebuild dengan {summary.get('days_rebuilt', 10)} hari bursa terakhir ({summary.get('added', 0)} sinyal tercatat).",
        "summary": summary,
    }


@app.get("/api/tracker/export")
def export_tracker_csv(status: str = Query(default="ALL")) -> Response:
    """Download riwayat lengkap performa sinyal (Paper Tracker) dalam format CSV."""
    rows = TRACKER.list_signals(status=status, limit=5000)
    if not rows:
        content = "id,ticker,status,signal_date,entry_date,exit_date,entry_price,exit_price,target,stop_loss,pnl_pct,score,trigger_type,note\n"
    else:
        df_export = pd.DataFrame(rows)
        cols = [
            "id", "ticker", "status", "signal_date", "entry_date", "exit_date",
            "entry_price", "exit_price", "target", "stop_loss", "pnl_pct",
            "score", "trigger_type", "bars_held", "note"
        ]
        export_cols = [c for c in cols if c in df_export.columns]
        content = df_export[export_cols].to_csv(index=False)

    dt_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"smartflow_tracker_forward_test_{dt_str}.csv"
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ===================== MARKET REGIME (BREADTH IHSG) =====================


@app.get("/api/market-regime")
def get_market_regime() -> dict:
    """Mengembalikan status rezim pasar IHSG berdasarkan persentase emiten di atas MA20 dan MA50."""
    if STATE["analysis"] is None:
        init_default_state()
    kpis = STATE["analysis"]["kpis"] if STATE["analysis"] else {}
    return kpis.get("market_regime", {
        "status": "NEUTRAL / CONSOLIDATION",
        "label": "Netral / Konsolidasi",
        "color": "amber",
        "allocation": "Alokasi Modal 50% - 70%",
        "breadth_ma20_pct": 50.0,
        "breadth_ma50_pct": 50.0,
        "regime_note": "Menunggu kalkulasi breadth pasar...",
    })


# ===================== REAL PORTFOLIO JOURNAL =====================


class PortfolioBuyRequest(BaseModel):
    ticker: str
    entry_price: float
    lots: int
    entry_date: Optional[str] = None
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    broker: Optional[str] = "Sekuritas"
    notes: Optional[str] = ""
    sector: Optional[str] = ""


class PortfolioSellRequest(BaseModel):
    exit_price: float
    exit_date: Optional[str] = None
    notes: Optional[str] = None


def _get_live_prices_map() -> dict[str, float]:
    price_map: dict[str, float] = {}
    if STATE.get("analysis") and "details" in STATE["analysis"]:
        for t, d in STATE["analysis"]["details"].items():
            c = d.get("close")
            if c:
                price_map[str(t).upper()] = float(c)
    elif STATE.get("analysis") and "stocks" in STATE["analysis"]:
        for s in STATE["analysis"]["stocks"]:
            t = s.get("ticker")
            c = s.get("close")
            if t and c:
                price_map[str(t).upper()] = float(c)
    return price_map


@app.get("/api/portfolio")
def get_portfolio_trades(status: str = Query(default="ALL")) -> dict:
    """Daftar riil transaksi portofolio pengguna beserta live floating P/L."""
    live_prices = _get_live_prices_map()
    trades = PORTFOLIO.list_trades(status=status, live_prices_map=live_prices)
    summary = PORTFOLIO.summary(live_prices_map=live_prices)
    return {"status": "success", "summary": summary, "trades": trades}


@app.get("/api/portfolio/summary")
def get_portfolio_summary() -> dict:
    """Ringkasan ekuitas, floating profit/loss, realized profit, dan win-rate portofolio riil."""
    live_prices = _get_live_prices_map()
    return PORTFOLIO.summary(live_prices_map=live_prices)


@app.post("/api/portfolio/buy")
def portfolio_buy(req: PortfolioBuyRequest) -> dict:
    """Catat pembelian riil saham di sekuritas."""
    try:
        sector = req.sector
        if not sector and STATE.get("analysis") and "details" in STATE["analysis"]:
            det = STATE["analysis"]["details"].get(req.ticker.upper(), {})
            sector = det.get("sector", "")

        trade = PORTFOLIO.add_trade(
            ticker=req.ticker,
            entry_price=req.entry_price,
            lots=req.lots,
            entry_date=req.entry_date,
            stop_loss=req.stop_loss,
            target_price=req.target_price,
            broker=req.broker,
            notes=req.notes,
            sector=sector,
        )
        return {"status": "success", "trade": trade}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal mencatat transaksi: {exc}") from exc


@app.post("/api/portfolio/sell/{trade_id}")
def portfolio_sell(trade_id: int, req: PortfolioSellRequest) -> dict:
    """Catat penjualan / take profit / cut loss saham."""
    try:
        trade = PORTFOLIO.close_trade(
            trade_id=trade_id,
            exit_price=req.exit_price,
            exit_date=req.exit_date,
            notes=req.notes,
        )
        return {"status": "success", "trade": trade}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal merealisasikan penjualan: {exc}") from exc


@app.delete("/api/portfolio/{trade_id}")
def portfolio_delete(trade_id: int) -> dict:
    """Hapus transaksi dari portofolio."""
    if not PORTFOLIO.delete_trade(trade_id):
        raise HTTPException(status_code=404, detail="Data transaksi tidak ditemukan.")
    return {"status": "success", "message": "Catatan transaksi berhasil dihapus."}


# ===================== TELEGRAM NOTIFIER =====================


class TelegramConfigRequest(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


class TelegramSendRequest(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    max_picks: int = 3
    max_pct_change: float = 2.5
    min_score: int = 70


class TelegramConfigSaveRequest(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    auto_notify: Optional[bool] = True


@app.get("/api/telegram/config")
def get_telegram_config() -> dict:
    cfg = load_telegram_config()
    token = cfg.get("bot_token", "")
    masked_token = f"{token[:5]}...{token[-4:]}" if len(token) > 10 else ("***" if token else "")
    return {
        "configured": bool(cfg.get("bot_token") and cfg.get("chat_id")),
        "bot_token": token,
        "masked_token": masked_token,
        "chat_id": cfg.get("chat_id", ""),
        "auto_notify": cfg.get("auto_notify", True),
    }


@app.post("/api/telegram/config")
def save_telegram_config_endpoint(req: TelegramConfigSaveRequest) -> dict:
    cfg = {
        "bot_token": (req.bot_token or "").strip(),
        "chat_id": (req.chat_id or "").strip(),
        "auto_notify": bool(req.auto_notify),
    }
    if cfg["bot_token"]:
        os.environ["TELEGRAM_BOT_TOKEN"] = cfg["bot_token"]
    if cfg["chat_id"]:
        os.environ["TELEGRAM_CHAT_ID"] = cfg["chat_id"]
    ok = save_telegram_config(cfg)
    if not ok:
        raise HTTPException(status_code=500, detail="Gagal menyimpan konfigurasi Telegram ke file disk.")
    return {"status": "success", "message": "Konfigurasi Telegram berhasil disimpan permanen!", "config": cfg}


@app.post("/api/telegram/test")
def test_telegram_connection(req: TelegramConfigRequest) -> dict:
    token = (req.bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
    chat_id = (req.chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
    if not token or not chat_id:
        raise HTTPException(
            status_code=400,
            detail="Telegram Bot Token dan Chat ID wajib diisi.",
        )
    ok, msg = send_telegram_message(token, chat_id, format_test_message())
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@app.post("/api/telegram/send")
async def send_smart_telegram_recommendations(req: TelegramSendRequest) -> dict:
    token = (req.bot_token or os.environ.get("TELEGRAM_BOT_TOKEN", "")).strip()
    chat_id = (req.chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")).strip()
    if not token or not chat_id:
        raise HTTPException(
            status_code=400,
            detail="Telegram Bot Token dan Chat ID belum disetel. Buka pengaturan Telegram untuk memasukkan Token & Chat ID.",
        )

    # 1. Pastikan state data pasar tersedia
    if STATE["analysis"] is None:
        init_default_state()

    # 2. Saring kandidat saham terbaik yang belum terbang
    stocks = STATE["analysis"]["stocks"] if STATE["analysis"] else []
    market_date = STATE["analysis"]["kpis"]["latest_date"] if STATE["analysis"] else "Hari Ini"

    picks = filter_smart_telegram_picks(
        stocks=stocks,
        max_picks=req.max_picks,
        max_pct_change=req.max_pct_change,
        min_score=req.min_score,
    )

    # 3. Format pesan HTML Telegram yang rapi
    text = format_telegram_broadcast(picks, market_date)

    # 4. Kirim ke Telegram
    ok, send_msg = await asyncio.to_thread(send_telegram_message, token, chat_id, text)
    if not ok:
        raise HTTPException(status_code=400, detail=send_msg)

    return {
        "status": "success",
        "picks_count": len(picks),
        "message": f"🚀 Berhasil mengirim {len(picks)} rekomendasi saham aman ke Telegram Anda!",
        "preview": text,
        "picks": [
            {
                "ticker": p.get("ticker"),
                "sector": p.get("sector"),
                "close": p.get("close"),
                "pct_change": p.get("pct_change"),
                "smart_money_score": p.get("smart_money_score"),
                "trigger_label": p.get("trigger_label"),
                "trading_plan": p.get("trading_plan"),
            }
            for p in picks
        ],
    }


# ===================== PROGRESSIVE WEB APP (PWA) =====================


@app.get("/manifest.json")
def serve_manifest() -> FileResponse:
    manifest_file = FRONTEND_DIR / "manifest.json"
    if not manifest_file.exists():
        raise HTTPException(status_code=404, detail="manifest.json tidak ditemukan")
    return FileResponse(str(manifest_file), media_type="application/manifest+json")


@app.get("/sw.js")
def serve_service_worker() -> Response:
    sw_file = FRONTEND_DIR / "sw.js"
    if not sw_file.exists():
        raise HTTPException(status_code=404, detail="sw.js tidak ditemukan")
    content = sw_file.read_text(encoding="utf-8")
    return Response(
        content=content,
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def serve_dashboard() -> FileResponse:
    return FileResponse(str(FRONTEND_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, reload=False)
