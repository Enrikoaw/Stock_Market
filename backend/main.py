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
from datetime import date, datetime
from pathlib import Path
from typing import Literal, Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
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
from broker_summary_fetcher import (
    load_broker_api_config,
    save_broker_api_config,
    filter_stage1_funnel_candidates,
    run_stage2_broker_enrichment,
    enrich_candidates_and_watchlist,
    filter_and_purge_watchlist_by_smart_money,
    test_broker_connection,
    enrich_single_stock_broker,
    can_run_broker_sync_now,
    load_broker_sync_state,
    record_broker_sync_done,
)
from portfolio_tracker import PortfolioTracker
from signal_tracker import SignalTracker
from screener_engine import (
    analyze_smart_money_dataframe,
    enrich_master_ticker_list,
    read_multiple_uploaded_files,
    read_uploaded_file,
    select_today_candidates,
)
from news_fetcher import get_market_news, get_market_news_nonblocking, validate_catalyst, NEWS_CACHE
from push_notifier import (
    is_push_configured, process_positive_news_alerts, send_push,
    get_vapid_keys, add_subscription, remove_subscription,
)
from ownership_manager import (
    get_stock_ownership,
    background_ownership_sync_worker,
)

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
    "last_sync_error": None,
    "auto_sync_interval_min": AUTO_SYNC_INTERVAL_SECONDS // 60,
    "is_real_market": False,
    "last_tracker_run": None,
}

TRACKER = SignalTracker(BASE_DIR / "data" / "tracker.db")
PORTFOLIO = PortfolioTracker(BASE_DIR / "data" / "tracker.db")
_init_broker_st = load_broker_sync_state()
LAST_CLOSE_SYNC_DATE: str | None = None
LAST_BROKSUM_EOD_DATE: str | None = None
LAST_BROKSUM_SESI1_DATE: str | None = _init_broker_st.get("sesi1_last_date")
LAST_BROKSUM_SESI2_DATE: str | None = _init_broker_st.get("sesi2_last_date")


def _overlay_tracker_signal_on_plan(item: dict, sig: dict, latest_dt: str) -> None:
    """Sinkronkan status sinyal tracker ke objek saham/detail TANPA menimpa harga pasar terbaru (close/history).
    Mengunci level trading_plan agar 100% konsisten dengan Pantauan jika sinyal berstatus aktif (WATCHLIST/RUNNING)
    atau baru selesai hari ini."""
    st = str(sig.get("status", "")).upper()
    exit_dt = str(sig.get("exit_date") or "")
    is_active = st in ("WATCHLIST", "RUNNING")
    is_closed_today = st in ("WIN", "LOSS") and exit_dt == latest_dt

    if not is_active and not is_closed_today:
        return

    live_close = float(item.get("close") or 0)
    e_p = float(sig.get("entry_high") or sig.get("entry_price") or sig.get("entry_low") or 0)
    pnl_val = sig.get("pnl_pct")
    if st == "RUNNING" and live_close > 0 and e_p > 0:
        pnl_val = round(((live_close - e_p) / e_p) * 100.0, 2)

    item["tracker_status"] = st
    # Tipe sinyal akumulasi/breakout yang tercatat di Watchlist (agar screener Mode Mahir konsisten dengan Watchlist)
    if is_active and sig.get("trigger_type"):
        item["tracker_trigger_type"] = str(sig.get("trigger_type")).upper()
        item["tracker_trigger_label"] = sig.get("trigger_label") or item["tracker_trigger_type"]
    item["tracker_pnl_pct"] = pnl_val
    item["tracker_entry_price"] = e_p
    item["tracker_signal_date"] = sig.get("signal_date")

    plan = dict(item.get("trading_plan") or {})
    plan["status"] = st
    plan["tracker_id"] = sig["id"]
    plan["signal_date"] = sig.get("signal_date")

    # KUNCI UTAMA SINKRONISASI:
    # Seluruh sinyal yang ada di Pantauan (WATCHLIST, RUNNING, WIN, LOSS)
    # WAJIB memiliki Harga Beli (Entry), Stop Loss, dan Target yang 100% sama persis dengan Pantauan
    if e_p > 0:
        plan["entry_price"] = e_p
        plan["entry_high"] = e_p
        plan["entry_low"] = e_p
    if sig.get("stop_loss") is not None and float(sig["stop_loss"]) > 0:
        plan["stop_loss"] = float(sig["stop_loss"])
    if sig.get("target") is not None and float(sig["target"]) > 0:
        plan["target_1"] = float(sig["target"])
    if sig.get("target_2") is not None and float(sig["target_2"]) > 0:
        plan["target_2"] = float(sig["target_2"])
    if e_p > 0:
        if plan.get("stop_loss"):
            plan["stop_loss_pct"] = round(((plan["stop_loss"] - e_p) / e_p) * 100.0, 2)
        if plan.get("target_1"):
            plan["target_1_pct"] = round(((plan["target_1"] - e_p) / e_p) * 100.0, 2)
        if plan.get("target_2"):
            plan["target_2_pct"] = round(((plan["target_2"] - e_p) / e_p) * 100.0, 2)
    if pnl_val is not None:
        plan["pnl_pct"] = float(pnl_val)

    if st == "WIN":
        pnl_num = float(pnl_val or 0)
        pnl_str = f"{pnl_num:+.1f}%"
        plan["action_bias"] = f"🏆 TARGET WIN ({pnl_str})"
        plan["rationale"] = f"Target untung (TP1) telah tercapai ({pnl_str}). Rencana trading selesai (Take Profit)."
    elif st == "RUNNING":
        pnl_num = float(pnl_val or 0)
        icon = "🔻" if pnl_num < 0 else "🚀"
        pnl_str = f"{pnl_num:+.1f}%"
        plan["action_bias"] = f"{icon} POSISI AKTIF ({pnl_str})"
        plan["rationale"] = f"Posisi beli aktif sejak {sig.get('entry_date', sig.get('signal_date'))} @ Rp {e_p:,.0f} (Floating {pnl_str})."
    elif st == "WATCHLIST":
        plan["action_bias"] = "⏳ MENUNGGU ENTRY"
        plan["rationale"] = f"Sinyal aktif di Watchlist sejak {sig.get('signal_date')}. Antre beli di area support Rp {e_p:,.0f}."
    elif st == "LOSS":
        pnl_num = float(pnl_val or 0)
        pnl_str = f"{pnl_num:+.1f}%"
        plan["action_bias"] = f"🛑 CUT LOSS ({pnl_str})"
        plan["rationale"] = f"Posisi ditutup disiplin batas rugi pada {sig.get('exit_date', sig.get('signal_date'))}."

    if e_p > 0 and plan.get("target_1") and plan.get("stop_loss"):
        t1 = plan["target_1"]
        t2 = plan.get("target_2", t1)
        sl_p = plan["stop_loss"]
        t1_pct = plan.get("target_1_pct", 0)
        t2_pct = plan.get("target_2_pct", 0)
        sl_pct = plan.get("stop_loss_pct", 0)
        plan["auto_order_text"] = (
            f"[Trading Plan Swing - #{item.get('ticker')}]\n"
            f"1. Antre Beli: Rp {e_p:,.0f} (Buy Limit)\n"
            f"2. Kunci Cuan TP1 (50% Lot): Rp {t1:,.0f} ({t1_pct:+.1f}%)\n"
            f"3. Kawal Trend TP2 (50% Lot): Rp {t2:,.0f} ({t2_pct:+.1f}%)\n"
            f"4. Batas Rugi (SL): Rp {sl_p:,.0f} ({sl_pct:.1f}%)\n"
            f"Strategi: Begitu TP1 tercapai, geser Stop Loss sisa lot ke Rp {e_p:,.0f} (BEP/Modal) untuk mengunci cuan bebas risiko."
        )
        plan["worker_guidance"] = {
            "leg1_label": f"Jual 50% Lot @ Rp {t1:,.0f} ({t1_pct:+.1f}%)",
            "leg2_label": f"Kawal 50% Lot @ Rp {t2:,.0f} ({t2_pct:+.1f}%)",
            "sl_label": f"SL Closing @ Rp {sl_p:,.0f} ({sl_pct:.1f}%)",
            "mode": "Set-and-Forget (Bebas pantau bursa saat kerja)",
        }
    item["trading_plan"] = plan


def sync_tracker_to_analysis(analysis: dict | None) -> None:
    """Sinkronkan status aktif dari database tracker (WATCHLIST, RUNNING, atau WIN/LOSS hari ini)
    ke objek saham dan trading_plan tanpa menimpa harga penutupan pasar terbaru."""
    if not analysis or "stocks" not in analysis or "details" not in analysis:
        return

    sig_map = TRACKER.get_latest_signals_map()
    if not sig_map:
        return

    latest_dt = str(analysis.get("kpis", {}).get("latest_date", ""))

    for stock in analysis["stocks"]:
        t = str(stock.get("ticker", "")).upper()
        if t in sig_map:
            _overlay_tracker_signal_on_plan(stock, sig_map[t], latest_dt)

    for t, detail in analysis["details"].items():
        t_up = str(t).upper()
        if t_up in sig_map:
            _overlay_tracker_signal_on_plan(detail, sig_map[t_up], latest_dt)


def _apply_buy_readiness(items: list) -> None:
    """Tempelkan status SIAP BELI/MENUNGGU/DITOLAK dari Database Broksum 3H lokal (+ buy_readiness.json) ke daftar saham."""
    try:
        from broker_summary_fetcher import load_buy_readiness, load_broker_summary_db, compute_buy_readiness
        br = load_buy_readiness()
        db_map = load_broker_summary_db()
    except Exception:
        return
    for it in items:
        t_up = str(it.get("ticker", "")).upper()
        rec = db_map.get(t_up) if db_map else None
        if rec:
            it["bdr_pct"] = rec.get("bdr")
            it["broker_holder_type"] = rec.get("holder_type", "MIXED")
            it["bandar_avg_buy"] = rec.get("bandar_avg")
            it["top_buyers"] = rec.get("top_buyers", "")
            it["top_sellers"] = rec.get("top_sellers", "")
            it["top_buyers_list"] = rec.get("top_buyers_list", [])
            it["top_sellers_list"] = rec.get("top_sellers_list", [])
            it["retail_trap"] = bool(rec.get("retail_trap", False))
            it["has_real_broker_summary"] = bool(it["top_buyers_list"] or it["top_sellers_list"])
            it["broker_date"] = rec.get("date")
            it["broker_range_from"] = rec.get("range_from")
            it["broker_analysis"] = {
                "holder_type": it["broker_holder_type"],
                "bdr": float(rec.get("bdr") or 0.0),
                "top_buyers_list": it["top_buyers_list"],
                "top_sellers_list": it["top_sellers_list"],
                "bandar_avg": it["bandar_avg_buy"],
                "retail_trap": it["retail_trap"],
            }
            c_px = float(it.get("close") or it.get("last_close") or 0)
            if it["bandar_avg_buy"] and c_px > 0:
                it["diff_bandar_avg_pct"] = round(((c_px - float(it["bandar_avg_buy"])) / float(it["bandar_avg_buy"])) * 100.0, 2)
            compute_buy_readiness(it, persist=False)
            continue

        v = br.get(t_up) if br else None
        if v:
            it["buy_status"] = v.get("buy_status")
            it["buy_status_reason"] = v.get("buy_status_reason")
            if v.get("holder_type"):
                it["broker_holder_type"] = v.get("holder_type")
            for k in ("bdr_pct", "bandar_avg_buy", "top_buyers", "top_sellers", "top_buyers_list", "top_sellers_list"):
                if v.get(k) is not None and not it.get(k):
                    it[k] = v[k]


def _sync_buy_readiness_to_tracker() -> None:
    """Setiap screener lolos kandidat hari ini, langsung validasi dengan Database Broksum 3H
    dan masukkan ke Pantauan (SIAP_BELI -> Top 3 Siap Beli, MENUNGGU -> Menunggu, DITOLAK -> hapus)."""
    try:
        from broker_summary_fetcher import (
            load_buy_readiness,
            load_broker_summary_db,
            enrich_stock_from_broksum_db,
        )
        from signal_tracker import align_signal_prices
        br = load_buy_readiness()
        db_map = load_broker_summary_db()
    except Exception:
        return

    analysis = STATE.get("analysis") or {}
    details_map = analysis.get("details") or {}
    latest_dt = str((analysis.get("kpis") or {}).get("latest_date") or datetime.now().strftime("%Y-%m-%d"))

    # 1. Validasi seluruh Kandidat Saham Pilihan Hari Ini langsung dengan Database Broksum 3H
    today_cands = analysis.get("today_candidates") or []
    seen_tickers: set[str] = set()
    for cand in today_cands:
        t_up = str(cand.get("ticker") or "").upper()
        if not t_up:
            continue
        seen_tickers.add(t_up)
        if db_map and t_up in db_map:
            enrich_stock_from_broksum_db(cand, db_map)
            if t_up in details_map:
                enrich_stock_from_broksum_db(details_map[t_up], db_map)
        try:
            TRACKER._ensure_candidate_in_watchlist(cand, latest_dt, "Database Broksum 3H")
        except Exception as ex:
            print(f"[SyncBroksumDB] Warning candidate {t_up}: {ex}")

    # 2. Sinkronkan juga dari buy_readiness.json (termasuk hasil validasi hari ini)
    for t_up, v in (br or {}).items():
        if t_up in seen_tickers:
            continue
        base = details_map.get(t_up)
        d = dict(base) if base else {"ticker": t_up}
        if db_map and t_up in db_map:
            enrich_stock_from_broksum_db(d, db_map)
        else:
            d["buy_status"] = v.get("buy_status") or d.get("buy_status")
            d["buy_status_reason"] = v.get("buy_status_reason") or d.get("buy_status_reason")
            d["broker_holder_type"] = v.get("holder_type") or d.get("broker_holder_type")
            for k in ("bdr_pct", "bandar_avg_buy", "top_buyers", "top_sellers", "top_buyers_list", "top_sellers_list"):
                if v.get(k) is not None:
                    d[k] = v[k]
        if v.get("close") and not d.get("close"):
            d["close"] = float(v["close"])

        if base and d.get("bandar_avg_buy"):
            for k in ("buy_status", "buy_status_reason", "bdr_pct", "bandar_avg_buy", "top_buyers", "top_sellers", "top_buyers_list", "top_sellers_list"):
                if d.get(k) is not None:
                    base[k] = d[k]
            if d.get("buy_status") in ("SIAP_BELI", "MENUNGGU"):
                base["retail_trap"] = False
                d["retail_trap"] = False
            b_avg = float(d["bandar_avg_buy"])
            cur_c = float(base.get("close") or d.get("close") or 0)
            # HANYA jadikan Modal Bandar sebagai harga Antre Beli jika berada di BAWAH harga pasar (sebagai support)!
            if base.get("trading_plan") and b_avg > 0 and d.get("buy_status") in ("SIAP_BELI", "MENUNGGU"):
                if cur_c > 0 and b_avg < cur_c:
                    rev_ep, rev_sl, rev_tp1, rev_tp2 = align_signal_prices(b_avg)
                    base["trading_plan"]["entry_price"] = rev_ep
                    base["trading_plan"]["entry_low"] = rev_ep
                    base["trading_plan"]["entry_high"] = rev_ep
                    base["trading_plan"]["stop_loss"] = rev_sl
                    base["trading_plan"]["target_1"] = rev_tp1
                    base["trading_plan"]["target_2"] = rev_tp2
                    base["trading_plan"]["support_label"] = "Support Avg Bandar"
                    d["trading_plan"] = base["trading_plan"]

        try:
            TRACKER._ensure_candidate_in_watchlist(d, latest_dt, "Database Broksum 3H")
        except Exception as ex:
            print(f"[SyncBuyReadiness] Warning {t_up}: {ex}")

    # 3. Audit seluruh sinyal WATCHLIST yang sudah ada terhadap Database Broksum 3H: hapus jika DITOLAK
    if db_map:
        try:
            wl_existing = [dict(r) for r in TRACKER.list_signals(status="WATCHLIST")]
            _apply_buy_readiness(wl_existing)
            for r in wl_existing:
                if r.get("buy_status") == "DITOLAK" and r.get("id"):
                    TRACKER.delete_signal(int(r["id"]))
        except Exception:
            pass

    # 4. Konsistensi Antre Beli vs Harga Terakhir: harga terakhir <= Antre Beli -> otomatis RUNNING
    try:
        TRACKER.fill_touched_watchlist(latest_dt)
    except Exception as ex:
        print(f"[SyncBroksumDB] Warning fill watchlist: {ex}")


def _process_tracker(analysis: dict, sync_live_network: bool = False, force_auto_track: bool = False) -> dict:
    """Evaluasi sinyal aktif dengan candle baru, lalu catat sinyal akumulasi baru ke Watchlist.
    Hanya berjalan untuk data pasar REAL (bukan simulasi / upload manual).
    Pencatatan sinyal baru (auto_track) secara default hanya dilakukan saat sesi bursa telah tutup (EOD)
    agar tidak menangkap candle intraday parsial."""
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
            TRACKER.repair_corrupted_loss_signals()
            main_res = TRACKER.evaluate(analysis["details"])
            for k in ("entered", "win", "loss", "expired", "timeout"):
                result[k] = max(result.get(k, 0), main_res.get(k, 0))

            # Sinkronisasi & konsistensi menu Pilihan Saham Hari Ini + catat otomatis ke Watchlist
            if "stocks" in analysis and analysis["stocks"]:
                latest_dt = analysis.get("kpis", {}).get("latest_date") or datetime.now().strftime("%Y-%m-%d")
                raw_picks = select_today_candidates(analysis["stocks"])
                today_cands = TRACKER.sync_today_candidates(
                    date_str=str(latest_dt),
                    candidate_stocks=raw_picks,
                    all_stocks=analysis["stocks"],
                )
                analysis["today_candidates"] = today_cands

            # Pencatatan sinyal akumulasi tanpa pembekuan IHSG
            result["added"] = TRACKER.auto_track(analysis)

            # Validasi instan kandidat & Watchlist dengan Database Broksum 3H lokal
            try:
                _sync_buy_readiness_to_tracker()
            except Exception as e_br:
                print(f"[Tracker] Sync broksum DB to tracker warning: {e_br}")

            # Auto-expire antrean Watchlist yang sudah stale (> 3 hari bursa tanpa kena zona entry)
            try:
                latest_dt = analysis.get("kpis", {}).get("latest_date") or datetime.now().strftime("%Y-%m-%d")
                stale_cleaned = TRACKER.cleanup_stale_watchlist(max_days=3, latest_date=str(latest_dt))
                if stale_cleaned:
                    result["expired"] = result.get("expired", 0) + stale_cleaned
            except Exception as e_stale:
                print(f"[Tracker] Auto-cleanup stale watchlist error: {e_stale}")

            sync_tracker_to_analysis(analysis)

        STATE["last_tracker_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[Tracker] {result}")
    except Exception as exc:
        print(f"[Tracker] Error: {exc}")
    return result


class LocalPathRequest(BaseModel):
    path: str


def _run_sync_job_blocking(with_broker_enrichment: bool = False) -> dict:
    """SATU jalur sinkronisasi: tarik pembaruan SELURUH saham BEI secara paralel
    (mode incremental 5 hari bila cache tersedia), hitung ulang indikator semua saham,
    evaluasi status Watchlist/Running, lalu kembalikan data terbaru untuk tampilan.
    with_broker_enrichment HANYA aktif 2x sehari (setelah Sesi 1 dan Sesi 2)."""
    global LAST_CACHE_MTIME
    if MASTER_UPLOADED_CSV.exists():
        tickers_df = pd.read_csv(MASTER_UPLOADED_CSV)
    else:
        tickers_df = generate_900_idx_master_tickers_df()

    real_df = fetch_real_idx_market_data(tickers_df, output_csv_path=REAL_CACHE_CSV, period="auto", max_workers=2)
    if REAL_CACHE_CSV.exists():
        try:
            LAST_CACHE_MTIME = os.path.getmtime(REAL_CACHE_CSV)
        except Exception:
            pass
    if "Has_Broker_Summary" not in real_df.columns:
        real_df["Has_Broker_Summary"] = False
    analysis = analyze_smart_money_dataframe(real_df)
    del real_df
    import gc
    gc.collect()

    latest_dt = analysis["kpis"]["latest_date"]

    # Pre-select Pilihan Saham Hari Ini awal agar masuk prioritas X-Ray Broksum
    try:
        raw_picks = select_today_candidates(analysis.get("stocks", []))
        analysis["today_candidates"] = raw_picks
    except Exception as exc:
        print(f"[Sync] Warning pre-select today candidates: {exc}")

    # Stage 2: Broker Summary API Fetcher via Two-Stage Smart Funneling
    # (Pilihan Saham Hari Ini + Watchlist Aktif + Stage 1 Funneling)
    # HANYA dijalankan maksimal 2x sehari:
    # 1. Pasca Sesi 1 bursa selesai (11:30 WIB Jumat / 12:00 WIB Senin-Kamis).
    # 2. Pasca Sesi 2 bursa selesai sekitar jam 6 sore WIB (18:00 WIB).
    broker_cfg = load_broker_api_config()
    has_api_cred = bool(
        broker_cfg.get("invezgo_api_key") or
        broker_cfg.get("goapi_key") or
        broker_cfg.get("stockbit_token")
    )

    session_name = None
    if with_broker_enrichment:
        allowed, reason, session_name = can_run_broker_sync_now()
        if not allowed:
            print(f"[Sync] 🛑 Proteksi Kuota Invezgo: {reason}")
            with_broker_enrichment = False
        else:
            print(f"[Sync] ✅ Jadwal Broksum Valid ({session_name}): {reason}")

    if with_broker_enrichment and has_api_cred:
        print(f"[Sync] 📡 Jam Update Broksum EOD ({session_name}): Menarik Broksum 3H seluruh saham terdaftar ke Database ({latest_dt})...")
        from broker_summary_fetcher import sync_all_stocks_broksum_eod, apply_broksum_db_to_analysis
        sync_all_stocks_broksum_eod(str(latest_dt))
        apply_broksum_db_to_analysis(analysis)
        try:
            analysis["today_candidates"] = select_today_candidates(analysis.get("stocks", []))
        except Exception:
            pass
        if session_name == "sesi2":
            LAST_BROKSUM_SESI2_DATE = str(latest_dt)
    else:
        print("[Sync] ⏱️ Update Harga Pasar: Validasi kandidat & Watchlist langsung menggunakan Database Broksum 3H lokal (0 API call).")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    STATE["source_name"] = f"Live IDX ({latest_dt})"
    STATE["analysis"] = analysis
    STATE["last_sync_time"] = now_str
    STATE["last_sync_error"] = None
    STATE["is_real_market"] = True
    tracker_res = _process_tracker(analysis, sync_live_network=False)
    try:
        kt = {str(s.get("ticker", "")).upper() for s in analysis["stocks"] if s.get("ticker")}
        get_market_news(known_tickers=kt, analysis_stocks=analysis["stocks"], force_refresh=True)
    except Exception as exc:
        print(f"[Sync] Pra-pemanasan berita gagal: {exc}")
    try:
        _fetch_ihsg_candles_blocking(period="3mo", force=True)
    except Exception as exc:
        print(f"[Sync] Refresh data & grafik IHSG (^JKSE) gagal: {exc}")
    save_screener_snapshot()
    return {
        "status": "success",
        "message": f"Sync selesai: {analysis['kpis'].get('total_emiten', len(analysis['stocks']))} saham diperbarui (data {latest_dt}).",
        "tracker_res": tracker_res,
        "source_name": STATE["source_name"],
        "last_sync_time": STATE["last_sync_time"],
        "kpis": analysis["kpis"],
        "stocks": analysis["stocks"],
    }


SYNC_LOCK: asyncio.Lock | None = None


def get_sync_lock() -> asyncio.Lock:
    global SYNC_LOCK
    if SYNC_LOCK is None:
        SYNC_LOCK = asyncio.Lock()
    return SYNC_LOCK


async def trigger_safe_sync(with_broker_enrichment: bool = False) -> bool:
    """Eksekusi sinkronisasi aman non-reentrant menggunakan asyncio.Lock."""
    lock = get_sync_lock()
    if lock.locked() or STATE["is_syncing"]:
        return False
    async with lock:
        STATE["is_syncing"] = True
        try:
            await asyncio.to_thread(_run_sync_job_blocking, with_broker_enrichment)
            STATE["last_sync_error"] = None
            return True
        except Exception as exc:
            STATE["last_sync_error"] = f"Sinkronisasi gagal: {exc}"
            print(f"[SyncError] {exc}")
            return False
        finally:
            STATE["is_syncing"] = False


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


def _is_idx_holiday(dt: date) -> bool:
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


def is_sesi1_running_now() -> bool:
    """Mengecek apakah saat ini bursa sedang berjalan di Sesi 1 (09:00 - 12:00 WIB, atau Jumat 09:00 - 11:30 WIB)."""
    now = _get_now_wib()
    if now.weekday() >= 5 or _is_idx_holiday(now.date()):
        return False
    from datetime import time as dtime
    t = now.time()
    if now.weekday() == 4:  # Hari Jumat
        return dtime(9, 0) <= t < dtime(11, 30)
    else:  # Senin - Kamis
        return dtime(9, 0) <= t < dtime(12, 0)


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
      hari bursa terakhir, otomatis melakukan sinkronisasi penuh seluruh saham!
    - Selama jam bursa aktif (09:00 - 16:05 WIB, Senin-Jumat): Otomatis menyinkronkan setiap 15 menit.
    - Tepat setelah penutupan pasar (>= 16:10 WIB): Menjalankan sinkronisasi final EOD wajib agar
      candle penutupan hari ini tersimpan dan dievaluasi oleh SignalTracker.
    - Setiap jam 18:00 WIB (Senin-Jumat): Otomatis menarik broker summary resmi final (Invezgo/provider)
      untuk seluruh kandidat hari ini dan watchlist aktif.
    """
    print("[MarketWorker] Background Market Session Worker aktif.")
    global LAST_CLOSE_SYNC_DATE, LAST_BROKSUM_EOD_DATE, LAST_BROKSUM_SESI1_DATE, LAST_BROKSUM_SESI2_DATE
    loop_count = 0
    last_sync_attempt_ts = 0.0
    import time
    from datetime import time as dtime
    while True:
        loop_count += 1
        try:
            market_open = is_idx_market_open_now()
            cache_stale = _is_cache_stale()
            now_ts = time.time()
            now_wib = _get_now_wib()
            today_str = now_wib.strftime("%Y-%m-%d")
            is_trading_day = now_wib.weekday() < 5 and not _is_idx_holiday(now_wib.date())
            is_jumat = (now_wib.weekday() == 4)

            # Muat status sinkronisasi persisten EOD (1x sehari jam 18:00 WIB)
            sync_st = load_broker_sync_state()
            LAST_BROKSUM_SESI2_DATE = sync_st.get("sesi2_last_date")

            # Jadwal Update Broksum EOD Jam 18:00 - 22:00 WIB (1x sehari: tarik semua saham terdaftar ke Database)
            is_sesi2_time = (dtime(18, 0) <= now_wib.time() <= dtime(22, 0))
            needs_sesi2_broksum_sync = (
                is_trading_day
                and is_sesi2_time
                and LAST_BROKSUM_SESI2_DATE != today_str
            )

            # Jadwal Penutupan Pasar 16:10 WIB (HANYA update closing price, TANPA broksum!)
            needs_close_price_sync = (
                is_trading_day
                and (dtime(16, 10) <= now_wib.time() <= dtime(17, 30))
                and LAST_CLOSE_SYNC_DATE != today_str
            )

            should_sync = False
            with_broksum = False

            if not STATE["is_syncing"] and not get_sync_lock().locked():
                if needs_sesi2_broksum_sync:
                    should_sync = True
                    with_broksum = True
                elif needs_close_price_sync:
                    should_sync = True
                    with_broksum = False
                elif market_open and (now_ts - last_sync_attempt_ts >= 300):
                    # Update harga pasar rutin setiap 5 menit saat bursa aktif: validasi memakai Database Broksum lokal
                    should_sync = True
                    with_broksum = False
                elif cache_stale and (now_ts - last_sync_attempt_ts >= 1800):
                    should_sync = True
                    with_broksum = False
                elif loop_count == 1 and not REAL_CACHE_CSV.exists():
                    should_sync = True
                    with_broksum = False

            if should_sync:
                print(
                    f"[MarketWorker] Menjalankan sinkronisasi background "
                    f"(with_broksum={with_broksum}, market_open={market_open}, eod_broksum_due={needs_sesi2_broksum_sync}, close_due={needs_close_price_sync})..."
                )
                last_sync_attempt_ts = now_ts
                synced_ok = await trigger_safe_sync(with_broker_enrichment=with_broksum)
                if synced_ok:
                    if needs_sesi2_broksum_sync:
                        LAST_BROKSUM_SESI2_DATE = today_str
                        LAST_CLOSE_SYNC_DATE = today_str
                        record_broker_sync_done("sesi2", today_str)
                        print(f"[MarketWorker] ✅ Database Broksum EOD ({today_str}) selesai diperbarui untuk seluruh saham terdaftar.")
                    elif needs_close_price_sync:
                        LAST_CLOSE_SYNC_DATE = today_str
                        print(f"[MarketWorker] ✅ Penutupan Pasar ({today_str}): Candle penutupan tersimpan. Update Database Broksum dijadwalkan pukul 18:00 WIB.")
        except Exception as exc:
            print(f"[MarketWorker] Error: {exc}")

        # Tidur 90 detik sebelum cek iterasi berikutnya
        await asyncio.sleep(90)


async def _background_news_alert_worker() -> None:
    """Worker alert HP: setiap 3 menit cek berita; kirim push (Web Push HP/Telegram/ntfy)
    HANYA untuk berita POSITIF terkait emiten."""
    print("[NewsAlertWorker] Aktif (alert berita positif emiten ke bar notifikasi HP).")
    await asyncio.sleep(5)
    while True:
        try:
            if is_push_configured():
                stocks = (STATE.get("analysis") or {}).get("stocks") or []
                kt = {str(s.get("ticker", "")).upper() for s in stocks if s.get("ticker")}
                items = await asyncio.to_thread(
                    get_market_news_nonblocking, known_tickers=kt, analysis_stocks=stocks
                )
                if items:
                    await asyncio.to_thread(process_positive_news_alerts, items)
        except Exception as exc:
            print(f"[NewsAlertWorker] Error: {exc}")
        await asyncio.sleep(180)


FAST_POLL_INTERVAL_SECONDS = int(os.environ.get("FAST_POLL_INTERVAL", "60"))


async def _background_fast_watchlist_poller() -> None:
    """Polling cepat (default 60 detik) harga saham Watchlist/Running via TradingView Scanner
    selama jam bursa, agar entry/TP/SL tercatat lebih responsif dibanding sync penuh yfinance."""
    print("[FastPoller] TradingView Fast Watchlist Poller aktif.")
    await asyncio.sleep(20)
    while True:
        try:
            if STATE.get("is_real_market") and is_idx_market_open_now() and not STATE.get("is_syncing"):
                res = await asyncio.to_thread(TRACKER.sync_active_signals_live, None, True)
                try:
                    _filled = await asyncio.to_thread(TRACKER.fill_touched_watchlist, None)
                    if _filled:
                        res["entered"] = int(res.get("entered") or 0) + _filled
                except Exception as _exf:
                    print(f"[FastPoller] Fill watchlist gagal: {_exf}")
                try:
                    # Deteksi otomatis antrean basi (> 3 hari tidak menyentuh zona beli) -> dihapus
                    _kp = (STATE.get("analysis") or {}).get("kpis", {})
                    await asyncio.to_thread(TRACKER.cleanup_stale_watchlist, 3, _kp.get("latest_date"))
                except Exception as _ex:
                    print(f"[FastPoller] Auto-clean basi gagal: {_ex}")
                if any(res.get(k) for k in ("entered", "win", "loss", "expired")):
                    print(
                        f"[FastPoller] ({res.get('source', 'yfinance')}) entered={res.get('entered')} "
                        f"win={res.get('win')} loss={res.get('loss')} expired={res.get('expired')}"
                    )
        except Exception as exc:
            print(f"[FastPoller] Error: {exc}")
        await asyncio.sleep(max(30, FAST_POLL_INTERVAL_SECONDS))


def _get_ownership_candidate_tickers() -> list[str]:
    analysis = STATE.get("analysis") or {}
    cands = analysis.get("today_candidates") or []
    return [str(c.get("ticker", "")).upper() for c in cands if c.get("ticker")]


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Mengelola siklus hidup server: Menjalankan worker market session cerdas secara otomatis."""
    market_task = asyncio.create_task(_background_market_session_worker())
    news_alert_task = asyncio.create_task(_background_news_alert_worker())
    fast_poll_task = asyncio.create_task(_background_fast_watchlist_poller())
    ownership_task = asyncio.create_task(background_ownership_sync_worker(_get_ownership_candidate_tickers))
    yield
    market_task.cancel()
    news_alert_task.cancel()
    fast_poll_task.cancel()
    ownership_task.cancel()
    try:
        TRACKER.engine.dispose()
        PORTFOLIO.engine.dispose()
    except Exception:
        pass


app = FastAPI(
    title="RadarBandarIDX - On-Demand Smart Money Stock Screener API",
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


LAST_CACHE_MTIME: float = 0.0


def check_and_reload_cache_if_updated() -> None:
    """Otomatis memuat ulang data terbaru jika file real_idx_market_latest.csv diperbarui oleh proses eksternal."""
    global LAST_CACHE_MTIME
    if STATE.get("is_syncing") or not REAL_CACHE_CSV.exists():
        return
    try:
        current_mtime = os.path.getmtime(REAL_CACHE_CSV)
        if current_mtime > LAST_CACHE_MTIME or STATE["analysis"] is None:
            real_df = pd.read_csv(REAL_CACHE_CSV)
            if "Has_Broker_Summary" not in real_df.columns:
                real_df["Has_Broker_Summary"] = False
            STATE["source_name"] = "Daftar Saham IDX - REAL Market Data (24/7 Active)"
            STATE["analysis"] = analyze_smart_money_dataframe(real_df)
            STATE["last_sync_time"] = datetime.fromtimestamp(current_mtime).strftime("%Y-%m-%d %H:%M:%S")
            STATE["is_real_market"] = True
            LAST_CACHE_MTIME = current_mtime
            _process_tracker(STATE["analysis"])
            print(f"[CacheSync] Auto-reloaded {len(real_df)} emiten dari disk (mtime: {current_mtime})")
    except Exception as e:
        print(f"[CacheSync] Error auto-reloading cache: {e}")


def init_default_state() -> None:
    """Memuat data pasar REAL terbaru dari cache hasil sinkronisasi seluruh saham IDX."""
    global LAST_CACHE_MTIME
    ensure_default_excel_files(BASE_DIR)
    USER_EXCEL_DIR.mkdir(parents=True, exist_ok=True)

    if REAL_CACHE_CSV.exists():
        LAST_CACHE_MTIME = os.path.getmtime(REAL_CACHE_CSV)
        real_df = pd.read_csv(REAL_CACHE_CSV)
        if "Has_Broker_Summary" not in real_df.columns:
            real_df["Has_Broker_Summary"] = False
        STATE["source_name"] = "Daftar Saham IDX - REAL Market Data (24/7 Active)"
        STATE["analysis"] = analyze_smart_money_dataframe(real_df)
        STATE["last_sync_time"] = datetime.fromtimestamp(LAST_CACHE_MTIME).strftime("%Y-%m-%d %H:%M:%S")
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
    check_and_reload_cache_if_updated()
    return {
        "status": "online",
        "market_open": is_idx_market_open_now(),
        "last_sync_time": STATE["last_sync_time"],
        "last_sync_error": STATE.get("last_sync_error"),
        "last_tracker_run": STATE["last_tracker_run"],
        "is_syncing": STATE["is_syncing"],
        "total_emiten": STATE["analysis"]["kpis"]["total_emiten"] if STATE["analysis"] else 0,
    }



_NEWS_WARMING = {"running": False}


def _news_catalyst_map(analysis_stocks: list[dict]) -> dict[str, dict]:
    """Peta ticker -> validasi katalis berita terbaru (dihitung ulang dengan data Smart Money live).
    Tidak pernah memblok jaringan: memakai cache memori/disk dan memicu refresh di thread latar."""
    kt = {str(s.get("ticker", "")).upper() for s in analysis_stocks if s.get("ticker")}
    items = get_market_news_nonblocking(known_tickers=kt, analysis_stocks=analysis_stocks)
    if not items:
        return {}
    lookup = {str(s.get("ticker", "")).upper(): s for s in analysis_stocks}
    out: dict[str, dict] = {}
    for n in sorted(items, key=lambda x: x.get("published_ts", 0), reverse=True):
        tk = n.get("ticker")
        st = lookup.get(tk)
        if not st or tk in out:
            continue
        out[tk] = {
            "title": n.get("title"),
            "link": n.get("link"),
            "source": n.get("source"),
            "published_at": n.get("published_at"),
            "sentiment": n.get("sentiment"),
            "sentiment_label": n.get("sentiment_label"),
            **validate_catalyst(n.get("sentiment") or "NEUTRAL", st),
        }
    return out


ACCUM_TRIGGER_SET = {"MARKUP_BREAKOUT", "BIG_ACCUMULATION", "SILENT_ACCUMULATION", "FOREIGN_INFLOW"}


def _effective_triggers(s: dict) -> set[str]:
    """Sinyal hari ini + sinyal akumulasi/breakout yang masih aktif di Watchlist (WATCHLIST/RUNNING)."""
    out = {str(s.get("trigger_type") or "").upper()}
    tt = s.get("tracker_trigger_type")
    if tt and str(s.get("tracker_status") or "").upper() in ("WATCHLIST", "RUNNING"):
        out.add(str(tt).upper())
    return out


def _signal_kpi_counts(stocks: list[dict]) -> dict:
    markup = sum(1 for s in stocks if "MARKUP_BREAKOUT" in _effective_triggers(s))
    accum = sum(
        1 for s in stocks
        if _effective_triggers(s) & {"BIG_ACCUMULATION", "SILENT_ACCUMULATION", "FOREIGN_INFLOW"}
    )
    return {"markup_triggers": markup, "accum_triggers": accum}


def _screener_compute(
    trigger: Optional[str] = "ALL",
    min_score: int = 0,
    min_vol_ratio: float = 0.0,
    search: Optional[str] = "",
    sort_by: str = "score",
    min_value_b: float = 0.0,
) -> dict:
    check_and_reload_cache_if_updated()
    if STATE["analysis"] is None:
        init_default_state()

    analysis = STATE["analysis"]
    stocks = list(analysis["stocks"])

    cat_map = _news_catalyst_map(analysis["stocks"])
    if cat_map:
        stocks = [({**s, "news_catalyst": cat_map[s["ticker"]]} if s["ticker"] in cat_map else s) for s in stocks]

    if isinstance(min_value_b, (int, float)) and min_value_b > 0:
        stocks = [s for s in stocks if float(s.get("value_b_idr") or 0) >= min_value_b]

    if trigger and isinstance(trigger, str) and trigger.upper() != "ALL":
        t_up = trigger.upper()
        if t_up == "NEWS_ACCUM":
            stocks = [
                s for s in stocks
                if s.get("news_catalyst")
                and s["news_catalyst"].get("sentiment") != "NEGATIVE"
                and s["news_catalyst"].get("code") not in ("SELL_ON_NEWS", "NEGATIVE_CONFIRMED")
                and _effective_triggers(s) & ACCUM_TRIGGER_SET
            ]
        elif t_up == "ACCUM_ALL":
            stocks = [s for s in stocks if _effective_triggers(s) & ACCUM_TRIGGER_SET]
        elif t_up == "DISTRIBUTION_WARNING":
            stocks = [s for s in stocks if s.get("trigger_type") == t_up]
        else:
            # Sinyal hari ini ATAU sinyal aktif di Watchlist (Silent/Big Accum, Breakout, Foreign)
            stocks = [s for s in stocks if t_up in _effective_triggers(s)]

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

    # Pastikan Pilihan Saham Hari Ini sinkron dan konsisten antar sesi
    today_cands = analysis.get("today_candidates")
    if not today_cands and analysis.get("stocks"):
        latest_dt = analysis.get("kpis", {}).get("latest_date") or datetime.now().strftime("%Y-%m-%d")
        raw_picks = select_today_candidates(analysis["stocks"])
        today_cands = TRACKER.sync_today_candidates(
            date_str=str(latest_dt),
            candidate_stocks=raw_picks,
            all_stocks=analysis["stocks"],
        )
        analysis["today_candidates"] = today_cands

    _apply_buy_readiness(stocks)
    _apply_buy_readiness(today_cands or [])

    return {
        "source_name": STATE["source_name"],
        "last_sync_time": STATE["last_sync_time"],
        "last_sync_error": STATE.get("last_sync_error"),
        "is_syncing": STATE["is_syncing"],
        "auto_sync_interval_min": STATE["auto_sync_interval_min"],
        "kpis": {**analysis["kpis"], **_signal_kpi_counts(analysis["stocks"])},
        "count": len(stocks),
        "stocks": stocks,
        "today_candidates": today_cands or [],
    }


SCREENER_MEMO: dict = {}
SCREENER_MEMO_TTL = 15.0
SNAPSHOT_FILE = DATA_DIR / "screener_snapshot.json"


def _screener_memo_key(args: tuple) -> tuple:
    a = STATE.get("analysis")
    return (args, id(a), STATE.get("last_sync_time"), STATE.get("last_tracker_run"), NEWS_CACHE.get("timestamp"))


def _unwrap_query(v: Any, default: Any) -> Any:
    """Ekstrak nilai default bila argumen berupa FastAPI Query object saat dipanggil internal."""
    if hasattr(v, "default"):
        d = v.default
        return d if d is not ... else default
    return v if v is not None else default


def _screener_cached(trigger="ALL", min_score=0, min_vol_ratio=0.0, search="", sort_by="score", min_value_b=0.0) -> dict:
    import time as _t
    t_clean = _unwrap_query(trigger, "ALL")
    s_clean = _unwrap_query(min_score, 0)
    v_clean = _unwrap_query(min_vol_ratio, 0.0)
    q_clean = _unwrap_query(search, "")
    o_clean = _unwrap_query(sort_by, "score")
    b_clean = _unwrap_query(min_value_b, 0.0)
    args = (str(t_clean), int(s_clean), float(v_clean), str(q_clean or ""), str(o_clean), float(b_clean))
    key = _screener_memo_key(args)
    hit = SCREENER_MEMO.get(key)
    if hit and (_t.time() - hit[0]) < SCREENER_MEMO_TTL:
        return hit[1]
    result = _screener_compute(*args)
    if len(SCREENER_MEMO) > 24:
        SCREENER_MEMO.clear()
    SCREENER_MEMO[key] = (_t.time(), result)
    return result


def save_screener_snapshot() -> None:
    """Simpan snapshot matang (scoring seluruh emiten + kandidat hari ini) ke JSON statis setelah Auto-Sync."""
    try:
        import json
        SCREENER_MEMO.clear()
        snap = _screener_cached("ALL", 0, 0.0, "", "score", 0.0)
        tmp = SNAPSHOT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(snap, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(SNAPSHOT_FILE)
    except Exception as exc:
        print(f"[Snapshot] Gagal menyimpan snapshot: {exc}")


@app.get("/api/screener")
def get_screener_data(
    trigger: Optional[str] = Query(default="ALL", description="Filter berdasarkan tipe trigger Smart Money"),
    min_score: int = Query(default=0, ge=0, le=100, description="Minimum Smart Money Score (0-100)"),
    min_vol_ratio: float = Query(default=0.0, ge=0.0, description="Minimum Volume Spike Ratio terhadap MA20"),
    search: Optional[str] = Query(default="", description="Cari kode Ticker atau Sektor"),
    sort_by: str = Query(default="score", description="Urutkan hasil: score, vol_ratio, top3_bsr, foreign, pct_change"),
    min_value_b: float = Query(default=0.0, ge=0.0, description="Minimum Nilai Transaksi (Miliar Rupiah)"),
) -> dict:
    check_and_reload_cache_if_updated()
    if STATE["analysis"] is None:
        init_default_state()
    return _screener_cached(trigger, min_score, min_vol_ratio, search, sort_by, min_value_b)


@app.get("/api/today-candidates")
def get_today_candidates_endpoint() -> dict:
    """Mengembalikan daftar Saham Pilihan Hari Ini yang konsisten antar sesi (siang & sore) dan tercatat di Watchlist."""
    if STATE["analysis"] is None:
        init_default_state()
    analysis = STATE["analysis"]
    today_cands = analysis.get("today_candidates")
    if not today_cands and analysis.get("stocks"):
        latest_dt = analysis.get("kpis", {}).get("latest_date") or datetime.now().strftime("%Y-%m-%d")
        raw_picks = select_today_candidates(analysis["stocks"])
        today_cands = TRACKER.sync_today_candidates(
            date_str=str(latest_dt),
            candidate_stocks=raw_picks,
            all_stocks=analysis["stocks"],
        )
        analysis["today_candidates"] = today_cands
    _apply_buy_readiness(today_cands or [])
    return {
        "status": "success",
        "count": len(today_cands or []),
        "candidates": today_cands or [],
    }

@app.get("/api/news")
def get_news_endpoint(
    category: str = Query(default="ALL", description="Filter kategori berita: ALL, PICKS, POSITIVE, NEGATIVE"),
    ticker: Optional[str] = Query(default=None, description="Filter kode saham tertentu"),
    refresh: bool = Query(default=False, description="Paksa refresh RSS dari sumber berita"),
    limit: int = Query(default=20, ge=1, le=50, description="Batas jumlah berita"),
) -> dict:
    """Endpoint Berita & Sentimen Pasar Saham BEI / IDX terintegrasi Smart Money."""
    known_tickers = set()
    analysis_stocks = []
    if STATE.get("analysis") and STATE["analysis"].get("stocks"):
        analysis_stocks = STATE["analysis"]["stocks"]
        known_tickers = {str(s.get("ticker", "")).upper() for s in analysis_stocks if s.get("ticker")}

    if refresh:
        news_items = list(get_market_news(known_tickers=known_tickers, analysis_stocks=analysis_stocks, force_refresh=True))
    else:
        news_items = list(get_market_news_nonblocking(known_tickers=known_tickers, analysis_stocks=analysis_stocks))

    cat_upper = category.upper().strip()
    if ticker and ticker.strip():
        t_clean = ticker.upper().strip()
        news_items = [n for n in news_items if n.get("ticker") == t_clean or t_clean in n.get("other_tickers", [])]

    if cat_upper == "PICKS":
        news_items = [n for n in news_items if n.get("is_pick")]
    elif cat_upper == "POSITIVE":
        news_items = [n for n in news_items if n.get("sentiment") == "POSITIVE"]
    elif cat_upper == "NEGATIVE":
        news_items = [n for n in news_items if n.get("sentiment") == "NEGATIVE"]

    # Pastikan data terurut mutlak dari yang paling baru (published_ts terbesar di atas)
    news_items.sort(key=lambda n: n.get("published_ts", 0), reverse=True)

    return {
        "status": "success",
        "category": cat_upper,
        "count": len(news_items[:limit]),
        "items": news_items[:limit],
    }


def _has_real_broker_codes(item: dict) -> bool:
    if not item.get("has_real_broker_summary"):
        return False
    buyers = item.get("top_buyers_list") or item.get("top_buyers") or []
    if isinstance(buyers, str):
        buyers = [b.strip() for b in buyers.split(",") if b.strip()]
    return bool(buyers)


@app.get("/api/stock/{ticker}")
def get_stock_detail(ticker: str) -> dict:
    if STATE["analysis"] is None:
        init_default_state()

    key = ticker.strip().upper()
    details_map = STATE["analysis"]["details"]
    if key not in details_map:
        raise HTTPException(status_code=404, detail=f"Saham '{key}' tidak ditemukan pada dataset aktif.")

    # Sinkronkan status dan level harga terkini dari tracker ke trading_plan agar 100% konsisten
    sig_map = TRACKER.get_latest_signals_map()
    if key in sig_map:
        latest_dt = str(STATE["analysis"].get("kpis", {}).get("latest_date", ""))
        _overlay_tracker_signal_on_plan(details_map[key], sig_map[key], latest_dt)

    details_map[key]["ownership"] = get_stock_ownership(key, details_map[key])
    return details_map[key]


@app.post("/api/stock/{ticker}/fetch-broker")
def fetch_single_stock_broker_endpoint(ticker: str, force: bool = Query(True)) -> dict:
    if STATE["analysis"] is None:
        init_default_state()

    key = ticker.strip().upper()
    details_map = STATE["analysis"]["details"]
    if key not in details_map:
        raise HTTPException(status_code=404, detail=f"Saham '{key}' tidak ditemukan pada dataset aktif.")

    cfg = load_broker_api_config()
    if not cfg.get("invezgo_api_key") and not cfg.get("stockbit_token") and not cfg.get("goapi_key"):
        raise HTTPException(
            status_code=400,
            detail="Token Invezgo / Stockbit belum diatur. Silakan periksa file .env atau Pengaturan.",
        )

    item = details_map[key]
    # Pengecualian Manual: Setiap tombol diklik pengguna untuk analisa pribadi, langsung akses Invezgo API
    # Jika force=False dan data sudah lengkap, kembalikan item yang ada.
    # Jika force=True (default untuk klik manual), bypass cache & langsung ambil data terbaru dari Invezgo.
    if not force and _has_real_broker_codes(item):
        return item

    latest_dt = str(item.get("date") or STATE["analysis"]["kpis"].get("latest_date") or "")
    if not latest_dt:
        from broker_summary_fetcher import get_now_wib
        latest_dt = get_now_wib().strftime("%Y-%m-%d")

    enrich_single_stock_broker(item, latest_dt, cfg, force=True, is_manual=True)

    _sync_broker_fields_to_stocks(key, item)

    if not _has_real_broker_codes(item):
        raise HTTPException(
            status_code=422,
            detail=f"Data broker summary #{key} belum terbit di Invezgo untuk tanggal {latest_dt}. Data broker harian resmi IDX biasanya diperbarui Invezgo setelah jam 18:00 WIB.",
        )

    return item


_BROKER_SYNC_FIELDS = (
    "broker_analysis", "has_broker_summary", "has_real_broker_summary", "bdr_pct",
    "top_buyers_list", "top_sellers_list", "top_buyers", "top_sellers",
    "bandar_avg_buy", "diff_bandar_avg_pct", "smart_money_score", "retail_trap",
    "trigger_type", "trigger_label", "broker_date", "trading_plan",
    "broker_holder_type", "broker_range_from", "buy_status", "buy_status_reason",
)


def _sync_broker_fields_to_stocks(key: str, item: dict) -> None:
    for lst_name in ("stocks", "today_candidates"):
        for s in STATE["analysis"].get(lst_name, []) or []:
            if str(s.get("ticker", "")).upper() == key:
                for field in _BROKER_SYNC_FIELDS:
                    if field in item:
                        s[field] = item[field]
                break


class CandidateBroksumRequest(BaseModel):
    tickers: list[str]


@app.post("/api/candidates/check-broksum")
def check_candidates_broksum(req: CandidateBroksumRequest) -> dict:
    """Cek manual broksum 3 hari bursa untuk kandidat hari ini (analisa pribadi, bypass jadwal 2 sesi).
    Mengembalikan status SIAP_BELI / MENUNGGU / DITOLAK per saham (maks 12 ticker)."""
    import time as _t
    if STATE["analysis"] is None:
        init_default_state()
    cfg = load_broker_api_config()
    if not cfg.get("invezgo_api_key") and not cfg.get("stockbit_token") and not cfg.get("goapi_key"):
        raise HTTPException(status_code=400, detail="Token Invezgo belum diatur.")
    from broker_summary_fetcher import get_now_wib
    details_map = STATE["analysis"]["details"]
    latest_dt = str(STATE["analysis"].get("kpis", {}).get("latest_date") or get_now_wib().strftime("%Y-%m-%d"))
    results = {}
    for t in list(dict.fromkeys(x.strip().upper() for x in req.tickers if x))[:12]:
        item = details_map.get(t)
        if not item:
            continue
        enrich_single_stock_broker(item, latest_dt, cfg, force=True, is_manual=True)
        _sync_broker_fields_to_stocks(t, item)
        results[t] = {
            "buy_status": item.get("buy_status", "BELUM_CEK"),
            "buy_status_reason": item.get("buy_status_reason", ""),
            "bdr_pct": item.get("bdr_pct"),
            "holder_type": item.get("broker_holder_type"),
        }
        _t.sleep(0.3)
    return {"results": results}


TICKER_CANDLE_CACHE: dict[tuple[str, str], dict] = {}


def _fetch_ticker_candles_blocking(ticker: str, period: str = "6mo") -> list[dict]:
    import time
    import yfinance as yf

    valid_periods = {"1mo": "1mo", "3mo": "3mo", "6mo": "6mo", "1y": "1y"}
    yf_period = valid_periods.get(period, "6mo")
    cache_key = (ticker.upper(), yf_period)
    now_ts = time.time()
    cached = TICKER_CANDLE_CACHE.get(cache_key)
    if cached and (now_ts - cached.get("ts", 0) < 300) and cached.get("candles"):
        return cached["candles"]

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
                TICKER_CANDLE_CACHE[cache_key] = {"ts": now_ts, "candles": candles}
                return candles
    except Exception as exc:
        print(f"[CandlesAPI] Fallback ke history lokal untuk {ticker}: {exc}")
    return []



@app.get("/api/stock/{ticker}/news-catalyst")
def get_stock_news_catalyst(ticker: str) -> dict:
    """Korelasi Sentimen Berita x Smart Money untuk satu emiten (dipakai panel Detail Saham)."""
    if STATE["analysis"] is None:
        init_default_state()
    key = ticker.strip().upper()
    stocks = STATE["analysis"]["stocks"]
    stock = next((s for s in stocks if str(s.get("ticker", "")).upper() == key), None)
    if not stock:
        raise HTTPException(status_code=404, detail=f"Saham '{key}' tidak ditemukan.")
    known = {str(s.get("ticker", "")).upper() for s in stocks if s.get("ticker")}
    items = get_market_news_nonblocking(known_tickers=known, analysis_stocks=stocks)
    related = [n for n in items if n.get("ticker") == key or key in n.get("other_tickers", [])]
    related.sort(key=lambda n: n.get("published_ts", 0), reverse=True)
    latest = related[0] if related else None
    verdict = validate_catalyst(latest.get("sentiment") if latest else "NEUTRAL", stock)
    plan = stock.get("trading_plan") or {}
    return {
        "ticker": key,
        "has_news": bool(latest),
        "verdict": verdict,
        "news": [
            {k: n.get(k) for k in ("title", "link", "source", "published_at", "relative_time", "sentiment", "sentiment_label")}
            for n in related[:3]
        ],
        "plan": {
            "entry_price": plan.get("entry_price"),
            "support_label": plan.get("support_label"),
            "stop_loss": plan.get("stop_loss"),
            "target_1": plan.get("target_1"),
        },
    }


@app.get("/api/stock/{ticker}/candles")
async def get_stock_candles(ticker: str, period: str = Query(default="6mo")) -> dict:
    if STATE["analysis"] is None:
        init_default_state()

    key = ticker.strip().upper()
    details_map = STATE["analysis"]["details"]
    detail = details_map.get(key, {})

    # Prioritaskan data histori lokal dari memori/cache (< 1ms) jika mencukupi rentang candle yang diminta
    candles = []
    required_bars = 100 if period in ("6mo", "1y", "2y") else (50 if period == "3mo" else 20)
    if detail and detail.get("history") and len(detail["history"]) >= required_bars:
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
        if not candles and detail and detail.get("history"):
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
    if get_sync_lock().locked() or STATE["is_syncing"]:
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
        print("[SyncAPI] Memulai proses sinkronisasi background aman...")
        synced = await trigger_safe_sync()
        if synced:
            print("[SyncAPI] Sinkronisasi background selesai dengan sukses.")
        else:
            print("[SyncAPI] Sinkronisasi dilewati atau gagal.")

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
        if analysis and "stocks" in analysis and analysis["stocks"]:
            latest_dt = analysis.get("kpis", {}).get("latest_date") or datetime.now().strftime("%Y-%m-%d")
            raw_picks = select_today_candidates(analysis["stocks"])
            today_cands = TRACKER.sync_today_candidates(
                date_str=str(latest_dt),
                candidate_stocks=raw_picks,
                all_stocks=analysis["stocks"],
            )
            analysis["today_candidates"] = today_cands
            sync_tracker_to_analysis(analysis)
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
    # Proteksi Keamanan: Hanya izinkan akses file/folder di dalam direktori data aplikasi (DATA_DIR)
    try:
        target.relative_to(DATA_DIR.resolve())
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
            if target.suffix.lower() not in (".xlsx", ".xls", ".csv"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Format file '{target.name}' tidak didukung. Gunakan file .xlsx, .xls, atau .csv.",
                )
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
    _sync_buy_readiness_to_tracker()
    st = TRACKER.stats()
    wl_rows = [dict(r) for r in TRACKER.list_signals(status="WATCHLIST")]
    _apply_buy_readiness(wl_rows)
    st["priority"] = sum(1 for r in wl_rows if r.get("buy_status") == "SIAP_BELI")
    st["watchlist_waiting"] = sum(1 for r in wl_rows if r.get("buy_status") not in ("SIAP_BELI", "DITOLAK"))
    st["watchlist"] = st["priority"] + st["watchlist_waiting"]
    return {
        "config": TRACKER.config(),
        "stats": st,
        "last_tracker_run": STATE.get("last_tracker_run"),
        "is_real_market": STATE.get("is_real_market"),
    }


@app.get("/api/tracker/signals")
def tracker_signals(
    status: str = Query(default="ALL"),
    sort_by: str = Query(default="id_desc", description="Urutkan sinyal: pnl_desc, pnl_asc, score_desc, date_desc, ticker_asc, distance_asc"),
) -> dict:
    _sync_buy_readiness_to_tracker()
    status_clean = str(_unwrap_query(status, "ALL"))
    sort_clean = str(_unwrap_query(sort_by, "id_desc"))
    st_up = status_clean.upper()
    if st_up == "PRIORITY":
        rows = TRACKER.list_signals(status="WATCHLIST", sort_by="distance_asc")
    else:
        rows = TRACKER.list_signals(status=status_clean, sort_by=sort_clean)

    # Memperkaya data sinyal dengan metrik broker summary terkini dari memori/analisis
    details_map = STATE.get("analysis", {}).get("details", {}) if STATE.get("analysis") else {}
    if details_map and rows:
        enriched_rows = []
        for r in rows:
            r_dict = dict(r)
            t_up = str(r.get("ticker", "")).upper()
            if t_up in details_map:
                d = details_map[t_up]
                # Jika masih di antrean WATCHLIST, pastikan Harga Beli sinkron dengan Trading Plan terkini
                if r_dict.get("status") == "WATCHLIST" and d.get("trading_plan"):
                    try:
                        from sqlalchemy import update as sa_update
                        from signal_tracker import signals_table, align_signal_prices, _now_str
                        from screener_engine import _round_idx_tick

                        tp = d["trading_plan"]
                        tp_ep = float(tp.get("entry_price") or tp.get("entry_high") or 0)
                        cur_h = float(r_dict.get("entry_high") or 0)
                        last_c_chk = float(r_dict.get("last_close") or 0)
                        if last_c_chk > 0 and tp_ep >= last_c_chk:
                            tp_ep = 0  # Jangan set Antre Beli di atas harga terakhir (sudah terisi / tidak konsisten)
                        if tp_ep > 0 and (tp_ep != cur_h or cur_h != _round_idx_tick(cur_h)):
                            clean_ep, clean_sl, clean_tp1, clean_tp2 = align_signal_prices(
                                tp_ep, float(tp.get("stop_loss") or 0), float(tp.get("target_1") or 0), float(tp.get("target_2") or 0)
                            )
                            r_dict["entry_high"] = clean_ep
                            r_dict["entry_low"] = clean_ep
                            r_dict["entry_price_target"] = clean_ep
                            r_dict["stop_loss"] = clean_sl
                            r_dict["target"] = clean_tp2 if TRACKER.tp_level == 2 else clean_tp1
                            r_dict["target_2"] = clean_tp2
                            last_c = float(r_dict.get("last_close") or 0)
                            if last_c > 0:
                                r_dict["dist_to_entry_pct"] = round((last_c - clean_ep) / clean_ep * 100.0, 2)
                            with TRACKER._lock, TRACKER.engine.begin() as conn:
                                conn.execute(
                                    sa_update(signals_table)
                                    .where(signals_table.c.id == r["id"])
                                    .values(
                                        entry_high=clean_ep,
                                        entry_low=clean_ep,
                                        stop_loss=clean_sl,
                                        target=r_dict["target"],
                                        target_2=clean_tp2,
                                        updated_at=_now_str(),
                                    )
                                )
                    except Exception as ex:
                        print(f"[TrackerSignals] Gagal sinkron watchlist {t_up}: {ex}")
                for fld in (
                    "bdr_pct", "top_buyers", "top_sellers", "top_buyers_list", "top_sellers_list",
                    "bandar_avg_buy", "diff_bandar_avg_pct", "retail_trap", "has_real_broker_summary",
                    "broker_analysis"
                ):
                    if fld in d and d[fld] is not None:
                        r_dict[fld] = d[fld]
            enriched_rows.append(r_dict)
        rows = enriched_rows

    rows = [dict(r) for r in rows]
    _apply_buy_readiness(rows)

    if st_up == "PRIORITY":
        rows = [r for r in rows if r.get("buy_status") == "SIAP_BELI"]
    elif st_up == "WATCHLIST":
        rows = [r for r in rows if r.get("buy_status") not in ("SIAP_BELI", "DITOLAK")]
    elif st_up == "ALL":
        rows = [r for r in rows if not (r.get("status") == "WATCHLIST" and r.get("buy_status") == "DITOLAK")]

    return {"count": len(rows), "signals": rows}


@app.post("/api/tracker/cleanup-stale")
def tracker_cleanup_stale() -> dict:
    deleted = TRACKER.cleanup_duplicate_signals(force_delete=True)
    analysis = STATE.get("analysis")
    ref_dt = analysis.get("kpis", {}).get("latest_date") if analysis else None
    removed = TRACKER.cleanup_stale_watchlist(max_days=3, latest_date=ref_dt)
    if STATE.get("analysis") and "details" in STATE["analysis"]:
        TRACKER.evaluate(STATE["analysis"]["details"])
    return {
        "success": True,
        "cleaned": removed,
        "deleted_duplicates": deleted,
        "message": f"Berhasil menghapus paksa {deleted} sinyal duplikat & membersihkan {removed} antrean kedaluwarsa.",
    }


@app.post("/api/tracker/repair")
def tracker_repair() -> dict:
    """Hapus paksa duplicate sinyal, perbaiki sinyal aktif, dan perbarui data pasar."""
    deleted = TRACKER.cleanup_duplicate_signals(force_delete=True)
    repaired = TRACKER.repair_corrupted_loss_signals()
    details_map = STATE.get("analysis", {}).get("details") if STATE.get("analysis") else None
    sync_w = TRACKER.repair_and_sync_watchlist_entries(details=details_map)
    if STATE.get("analysis") and "details" in STATE["analysis"]:
        TRACKER.evaluate(STATE["analysis"]["details"])
        sync_tracker_to_analysis(STATE["analysis"])
    return {
        "success": True,
        "deleted_duplicates": deleted,
        "repaired_count": repaired,
        "synced_watchlist": sync_w,
        "message": f"Berhasil menghapus paksa {deleted} sinyal duplikat dan memperbarui data pantauan!",
    }


@app.post("/api/tracker/purge-duplicates")
def tracker_purge_duplicates() -> dict:
    """Hapus paksa seluruh sinyal duplikat dari database dan perbarui data sinyal seketika."""
    deleted = TRACKER.cleanup_duplicate_signals(force_delete=True)
    if STATE.get("analysis") and "details" in STATE["analysis"]:
        TRACKER.evaluate(STATE["analysis"]["details"])
    return {
        "success": True,
        "deleted_duplicates": deleted,
        "message": f"Berhasil menghapus paksa {deleted} sinyal duplikat dan memperbarui data pantauan!",
    }


@app.post("/api/tracker/purge-retail-watchlist")
def tracker_purge_retail_watchlist() -> dict:
    """Audit & seleksi seluruh sinyal Watchlist (Menunggu) menggunakan Invezgo Broker Summary.
    Saham yang didominasi ritel atau distribusi langsung dihapus dari Watchlist."""
    cfg = load_broker_api_config()
    latest_dt = STATE.get("analysis", {}).get("kpis", {}).get("latest_date") if STATE.get("analysis") else None
    res = filter_and_purge_watchlist_by_smart_money(TRACKER, analysis=STATE.get("analysis"), date_str=latest_dt, cfg=cfg)
    return {
        "success": True,
        "message": f"Audit Smart Money selesai: {res.get('retained_count', 0)} saham lolos akumulasi, {res.get('eliminated_count', 0)} saham ritel/distribusi dihapus.",
        "data": res,
    }



def _require_admin_token(request: Request) -> None:
    admin_secret = os.environ.get("ADMIN_SECRET_TOKEN", "").strip()
    token = (
        request.headers.get("X-Admin-Token", "").strip()
        or request.query_params.get("admin_token", "").strip()
    )
    if not admin_secret or token != admin_secret:
        raise HTTPException(
            status_code=403,
            detail="Akses ditolak: Operasi modifikasi database ini dikunci khusus Admin RadarBandarIDX.",
        )


@app.post("/api/tracker/add/{ticker}")
def tracker_add(ticker: str, request: Request) -> dict:
    _require_admin_token(request)
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
def tracker_delete(signal_id: int, request: Request) -> dict:
    _require_admin_token(request)
    if not TRACKER.delete_signal(signal_id):
        raise HTTPException(status_code=404, detail="Sinyal tidak ditemukan.")
    return {"status": "success", "message": "Sinyal dihapus."}


@app.post("/api/tracker/reset")
def tracker_reset(request: Request) -> dict:
    _require_admin_token(request)
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


# ===================== MARKET REGIME & IHSG CHART (BREADTH & ^JKSE) =====================

IHSG_CACHE: dict[str, dict] = {}


def _fetch_ihsg_candles_blocking(period: str = "3mo", force: bool = False) -> dict:
    import time
    import yfinance as yf

    valid_periods = {"1mo": "1mo", "3mo": "3mo", "6mo": "6mo", "1y": "1y"}
    yf_period = valid_periods.get(period, "3mo")
    now_ts = time.time()

    cached = IHSG_CACHE.get(yf_period)
    if not force and cached and (now_ts - cached.get("ts", 0) < 300) and cached.get("data"):
        return cached["data"]

    candles: list[dict] = []
    try:
        t_obj = yf.Ticker("^JKSE")
        sub = t_obj.history(period=yf_period, interval="1d", auto_adjust=False)
        if sub is not None and not sub.empty:
            sub = sub.dropna(subset=["Close"]).copy()
            sub = sub[sub["Close"] > 0].reset_index()
            date_col = "Date" if "Date" in sub.columns else sub.columns[0]
            sub["date"] = pd.to_datetime(sub[date_col]).dt.strftime("%Y-%m-%d")
            sub["MA20"] = sub["Close"].rolling(20, min_periods=1).mean()
            sub["MA50"] = sub["Close"].rolling(50, min_periods=1).mean()
            sub["Prev_Close"] = sub["Close"].shift(1).fillna(sub["Open"])

            for _, r in sub.iterrows():
                c_val = round(float(r["Close"]), 2)
                o_val = round(float(r.get("Open", c_val) or c_val), 2)
                h_val = round(max(float(r.get("High", c_val) or c_val), c_val, o_val), 2)
                l_val = round(min(float(r.get("Low", c_val) or c_val), c_val, o_val), 2)
                prev_c = float(r.get("Prev_Close", o_val) or o_val)
                pct_chg = round(((c_val - prev_c) / max(prev_c, 1.0)) * 100.0, 2)
                ma20_val = round(float(r.get("MA20", c_val) or c_val), 2)
                ma50_val = round(float(r.get("MA50", c_val) or c_val), 2)
                vol_val = int(round(max(0.0, float(r.get("Volume", 0) or 0))))
                candles.append({
                    "date": str(r["date"]),
                    "open": o_val,
                    "high": h_val,
                    "low": l_val,
                    "close": c_val,
                    "ma20": ma20_val,
                    "ma50": ma50_val,
                    "pct_change": pct_chg,
                    "volume": vol_val,
                })

            # Selaraskan bar hari ini dengan real-time fast_info dari Yahoo Finance (jika pasar sedang live)
            try:
                fi = getattr(t_obj, "fast_info", None)
                if fi and candles:
                    lp = getattr(fi, "last_price", None)
                    if lp and float(lp) > 0:
                        last_c = candles[-1]
                        last_c["close"] = round(float(lp), 2)
                        dh = getattr(fi, "day_high", None)
                        dl = getattr(fi, "day_low", None)
                        if dh and float(dh) > 0:
                            last_c["high"] = round(max(float(last_c["high"]), float(dh)), 2)
                        if dl and float(dl) > 0:
                            last_c["low"] = round(min(float(last_c["low"]), float(dl)), 2)
                        prev_c_val = candles[-2]["close"] if len(candles) >= 2 else last_c["open"]
                        last_c["pct_change"] = round(((last_c["close"] - prev_c_val) / max(prev_c_val, 1.0)) * 100.0, 2)
            except Exception as fi_exc:
                pass
    except Exception as exc:
        print(f"[IHSGChart] Gagal tarik ^JKSE dari Yahoo Finance, gunakan fallback komposit: {exc}")

    # Fallback komposit dari histori lokal apabila Yahoo Finance sedang offline
    if not candles and STATE.get("analysis") and STATE["analysis"].get("details"):
        try:
            date_returns: dict[str, list[float]] = {}
            for _, d in list(STATE["analysis"]["details"].items())[:100]:
                hist = d.get("history") or []
                for idx_h, h in enumerate(hist):
                    dt_str = str(h.get("date", ""))
                    if not dt_str:
                        continue
                    prev_h_close = float(hist[idx_h - 1]["close"]) if idx_h > 0 else float(h.get("open") or h["close"])
                    cur_h_close = float(h["close"])
                    if prev_h_close > 0:
                        ret = (cur_h_close - prev_h_close) / prev_h_close
                        date_returns.setdefault(dt_str, []).append(ret)

            sorted_dates = sorted(date_returns.keys())
            base_idx = 7200.0
            closes_arr: list[float] = []
            for dt_str in sorted_dates:
                avg_ret = float(np.median(date_returns[dt_str])) if date_returns[dt_str] else 0.0
                open_idx = round(base_idx, 2)
                close_idx = round(base_idx * (1.0 + avg_ret), 2)
                high_idx = round(max(open_idx, close_idx) * 1.004, 2)
                low_idx = round(min(open_idx, close_idx) * 0.996, 2)
                closes_arr.append(close_idx)
                ma20_v = round(float(np.mean(closes_arr[-20:])), 2)
                ma50_v = round(float(np.mean(closes_arr[-50:])), 2)
                candles.append({
                    "date": dt_str,
                    "open": open_idx,
                    "high": high_idx,
                    "low": low_idx,
                    "close": close_idx,
                    "ma20": ma20_v,
                    "ma50": ma50_v,
                    "pct_change": round(avg_ret * 100.0, 2),
                    "volume": 0,
                })
                base_idx = close_idx
        except Exception as fb_exc:
            print(f"[IHSGChart] Fallback komposit gagal: {fb_exc}")

    if not candles:
        return {
            "symbol": "^JKSE",
            "name": "IHSG (IDX Composite)",
            "period": yf_period,
            "candles": [],
        }

    last = candles[-1]
    prev_close = candles[-2]["close"] if len(candles) >= 2 else last["open"]
    result = {
        "symbol": "^JKSE",
        "name": "IHSG (IDX Composite)",
        "period": yf_period,
        "latest_date": last["date"],
        "close": last["close"],
        "open": last["open"],
        "high": last["high"],
        "low": last["low"],
        "ma20": last["ma20"],
        "ma50": last["ma50"],
        "change_pts": round(last["close"] - prev_close, 2),
        "change_pct": last["pct_change"],
        "candles": candles,
    }
    IHSG_CACHE[yf_period] = {"ts": now_ts, "data": result}
    return result


@app.get("/api/ihsg/candles")
async def get_ihsg_candles(period: str = Query(default="3mo"), force: bool = Query(default=False)) -> dict:
    """Mengembalikan data historis candlestick/line Indeks Harga Saham Gabungan (^JKSE) beserta MA20 & MA50."""
    if STATE["analysis"] is None:
        init_default_state()
    data = await asyncio.to_thread(_fetch_ihsg_candles_blocking, period, force)
    regime = STATE["analysis"]["kpis"].get("market_regime", {}) if STATE.get("analysis") else {}
    return {
        **data,
        "market_regime": regime,
    }


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
    status_clean = str(_unwrap_query(status, "ALL"))
    live_prices = _get_live_prices_map()
    trades = PORTFOLIO.list_trades(status=status_clean, live_prices_map=live_prices)
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


class BrokerApiConfigRequest(BaseModel):
    provider: Optional[str] = "invezgo"
    invezgo_api_key: Optional[str] = None
    goapi_key: Optional[str] = None
    stockbit_token: Optional[str] = None
    delay_ms: Optional[int] = 300
    max_candidates: Optional[int] = 30


@app.get("/api/broker/config")
def get_broker_api_config_endpoint() -> dict:
    cfg = load_broker_api_config()
    sync_st = load_broker_sync_state()
    inv_key = cfg.get("invezgo_api_key", "")
    masked_inv = f"{inv_key[:4]}...{inv_key[-4:]}" if len(inv_key) > 8 else ("***" if inv_key else "")
    go_key = cfg.get("goapi_key", "")
    masked_go = f"{go_key[:4]}...{go_key[-4:]}" if len(go_key) > 8 else ("***" if go_key else "")
    allowed_now, sync_msg, next_sess = can_run_broker_sync_now()
    return {
        "provider": cfg.get("provider", "invezgo"),
        "has_invezgo_key": bool(inv_key),
        "masked_invezgo_key": masked_inv,
        "has_goapi_key": bool(go_key),
        "masked_goapi_key": masked_go,
        "has_stockbit_token": bool(cfg.get("stockbit_token")),
        "delay_ms": cfg.get("delay_ms", 300),
        "max_candidates": cfg.get("max_candidates", 30),
        "sync_policy": "2x Sehari Otomatis (Pasca Sesi 1 jam 11:30/12:00 WIB & Pasca Sesi 2 jam 18:00 WIB)",
        "sesi1_last_date": sync_st.get("sesi1_last_date"),
        "sesi1_last_ts": sync_st.get("sesi1_last_ts"),
        "sesi2_last_date": sync_st.get("sesi2_last_date"),
        "sesi2_last_ts": sync_st.get("sesi2_last_ts"),
        "can_sync_now": allowed_now,
        "sync_status_message": sync_msg,
        "current_session_window": next_sess,
    }


@app.post("/api/broker/config")
def save_broker_api_config_endpoint(req: BrokerApiConfigRequest, request: Request) -> dict:
    _require_admin_token(request)
    cfg = load_broker_api_config()
    if req.provider:
        cfg["provider"] = req.provider.strip().lower()
    if req.invezgo_api_key is not None:
        cfg["invezgo_api_key"] = req.invezgo_api_key.strip()
    if req.goapi_key is not None:
        cfg["goapi_key"] = req.goapi_key.strip()
    if req.stockbit_token is not None:
        cfg["stockbit_token"] = req.stockbit_token.strip()
    if req.delay_ms is not None:
        cfg["delay_ms"] = max(100, req.delay_ms)
    if req.max_candidates is not None:
        cfg["max_candidates"] = max(5, min(100, req.max_candidates))
    ok = save_broker_api_config(cfg)
    if not ok:
        raise HTTPException(status_code=500, detail="Gagal menyimpan konfigurasi Broker API.")
    return {"status": "success", "message": "Konfigurasi Broker API berhasil disimpan!", "config": cfg}


class BrokerTestRequest(BaseModel):
    provider: Optional[str] = None
    token_or_key: Optional[str] = None
    ticker: Optional[str] = "BBCA"


@app.post("/api/broker/test")
def test_broker_api_endpoint(req: BrokerTestRequest) -> dict:
    cfg = load_broker_api_config()
    provider = (req.provider or cfg.get("provider", "invezgo")).strip().lower()
    token_or_key = (req.token_or_key or "").strip()
    if not token_or_key:
        if provider == "invezgo":
            token_or_key = cfg.get("invezgo_api_key", "")
        elif provider == "stockbit":
            token_or_key = cfg.get("stockbit_token", "")
        else:
            token_or_key = cfg.get("goapi_key", "")

    if not token_or_key:
        raise HTTPException(status_code=400, detail=f"Token/API Key {provider.upper()} belum diisi. Silakan masukkan token di file .env atau pengaturan.")

    ticker = (req.ticker or "BBCA").strip().upper()
    res = test_broker_connection(provider=provider, token_or_key=token_or_key, ticker=ticker)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error", "Koneksi ke Broker API gagal."))
    return res


@app.get("/api/push/public-key")
def push_public_key() -> dict:
    try:
        keys = get_vapid_keys()
        return {"public_key": keys.get("public", "")}
    except Exception as exc:
        print(f"[PushPublicKey] Error: {exc}")
        return {"public_key": "BIwlaEq_zpXWqFpeIx-iFnJe3S2xBSnJFR6Io8zdcNQ6_0ArEx8osH1DWO8qFx0SuN5XptQDuueKbAR-tVl2VLQ"}


@app.post("/api/push/subscribe")
def push_subscribe(sub: dict) -> dict:
    try:
        total = add_subscription(sub)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    return {"status": "success", "devices": total}


@app.post("/api/push/unsubscribe")
def push_unsubscribe(body: dict) -> dict:
    remove_subscription(str(body.get("endpoint", "")))
    return {"status": "success"}


@app.post("/api/alerts/test-push")
def test_push_alert() -> dict:
    """Kirim notifikasi uji ke HP (bar notifikasi / Telegram / ntfy)."""
    if not is_push_configured():
        return {
            "status": "warning",
            "message": "Perangkat web push belum terdaftar di server. Buka di HP dan tekan 'Aktifkan'.",
        }
    ok = send_push("📈 Katalis Positif: #BBCA (+3.2%)", "Uji Coba: Notifikasi berita katalis positif terhubung ke bar notifikasi HP Anda.", link="/?ticker=BBCA")
    return {"status": "success" if ok else "error", "message": "Notifikasi uji terkirim ke bar HP."}


@app.post("/api/broker/sync-eod")
async def manual_broker_sync_eod() -> dict:
    """Trigger manual sinkronisasi Broker Summary EOD (Pilihan Hari Ini + Watchlist) on-demand."""
    global LAST_BROKSUM_EOD_DATE
    if STATE["analysis"] is None:
        init_default_state()
    allowed, reason, session_name = can_run_broker_sync_now()
    if not allowed:
        return {
            "status": "warning",
            "message": f"Penarikan ditolak untuk proteksi kuota token Invezgo: {reason}",
            "allowed": False,
        }
    synced = await trigger_safe_sync(with_broker_enrichment=True)
    now_wib = _get_now_wib()
    today_str = now_wib.strftime("%Y-%m-%d")
    LAST_BROKSUM_EOD_DATE = today_str
    if session_name:
        record_broker_sync_done(session_name, today_str)
    return {
        "status": "success" if synced else "error",
        "message": f"Sinkronisasi Broker Summary ({today_str} - {session_name}) selesai.",
        "date": today_str,
    }


@app.get("/api/broker/quota-status")
def broker_quota_status() -> dict:
    """Mengembalikan status penggunaan kuota API Invezgo hari ini, batas maksimal hard-cap harian, dan status 2 sesi."""
    from broker_summary_fetcher import (
        get_today_broker_call_count,
        MAX_DAILY_BROKSUM_REQUESTS,
        load_broker_sync_state,
        can_run_broker_sync_now,
        get_now_wib,
    )
    now = get_now_wib()
    today_str = now.strftime("%Y-%m-%d")
    st = load_broker_sync_state()
    today_calls = get_today_broker_call_count(today_str)
    allowed, reason, session = can_run_broker_sync_now(now)
    return {
        "date": today_str,
        "current_time_wib": now.strftime("%H:%M:%S WIB"),
        "today_calls": today_calls,
        "daily_limit": MAX_DAILY_BROKSUM_REQUESTS,
        "remaining_daily_calls": max(0, MAX_DAILY_BROKSUM_REQUESTS - today_calls),
        "hard_cap_active": True,
        "sesi1_status": f"SELESAI ({st.get('sesi1_last_ts')})" if st.get("sesi1_last_date") == today_str else "MENUNGGU JADWAL (11:30/12:00 WIB)",
        "sesi2_status": f"SELESAI ({st.get('sesi2_last_ts')})" if st.get("sesi2_last_date") == today_str else "MENUNGGU JADWAL (18:00 WIB)",
        "can_sync_now": allowed,
        "schedule_info": reason,
        "monthly_quota_estimate": "Maksimal ~1.540 request/bulan (~5% dari 30.000 kuota Invezgo)",
    }




# ===================== AI NAVIGATION & QUANTITATIVE COPILOT (v98.0) =====================

import time as _ai_time
import json as _ai_json
import re as _ai_re
import urllib.request as _ai_urlreq
import urllib.error as _ai_urlerr

AI_CHAT_CACHE: dict[str, tuple[float, dict]] = {}
AI_IP_LAST_CALL: dict[str, float] = {}
AI_CONFIG_FILE = DATA_DIR / "ai_config.json"


class AIChatRequest(BaseModel):
    message: str
    active_ticker: Optional[str] = None


def _load_ai_keys() -> dict[str, str]:
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    groq_key = os.environ.get("GROQ_API_KEY", "").strip()
    if AI_CONFIG_FILE.exists():
        try:
            cfg = _ai_json.loads(AI_CONFIG_FILE.read_text(encoding="utf-8"))
            if not gemini_key:
                gemini_key = str(cfg.get("gemini_api_key") or "").strip()
            if not groq_key:
                groq_key = str(cfg.get("groq_api_key") or "").strip()
        except Exception:
            pass
    return {"gemini": gemini_key, "groq": groq_key}


def _call_cloud_llm(system_prompt: str, user_msg: str) -> Optional[str]:
    keys = _load_ai_keys()
    # 1. Try Google Gemini 1.5 Flash (Free Tier)
    if keys["gemini"]:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={keys['gemini']}"
            payload = {
                "system_instruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_msg}]}],
                "generationConfig": {"temperature": 0.25, "maxOutputTokens": 320},
            }
            req = _ai_urlreq.Request(
                url,
                data=_ai_json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with _ai_urlreq.urlopen(req, timeout=6.0) as resp:
                data = _ai_json.loads(resp.read().decode("utf-8"))
                parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
                if parts and parts[0].get("text"):
                    return str(parts[0]["text"]).strip()
        except Exception as e:
            print(f"[AICopilot] Gemini fallback: {e}")

    # 2. Fallback to Groq Cloud Llama 3.3 (Free Tier)
    if keys["groq"]:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_msg},
                ],
                "temperature": 0.25,
                "max_tokens": 320,
            }
            req = _ai_urlreq.Request(
                url,
                data=_ai_json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {keys['groq']}",
                },
                method="POST",
            )
            with _ai_urlreq.urlopen(req, timeout=6.0) as resp:
                data = _ai_json.loads(resp.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices and choices[0].get("message", {}).get("content"):
                    return str(choices[0]["message"]["content"]).strip()
        except Exception as e:
            print(f"[AICopilot] Groq fallback: {e}")

    return None


@app.get("/api/ownership/{ticker}")
def get_ownership_endpoint(ticker: str) -> dict:
    """Mengambil Struktur Kepemilikan Saham & Free Float secara instan (Read-Only untuk Publik)."""
    clean = str(ticker or "").strip().upper()
    if not clean or len(clean) < 2 or len(clean) > 8:
        raise HTTPException(status_code=400, detail="Kode saham tidak valid.")
    analysis = STATE.get("analysis") or {}
    all_stocks = analysis.get("stocks") or []
    stock_meta = next((s for s in all_stocks if str(s.get("ticker", "")).upper() == clean), None)
    data = get_stock_ownership(clean, stock_meta)
    return {"status": "success", "data": data}


@app.post("/api/ai/chat")
def ai_copilot_chat(payload: AIChatRequest, request: Request) -> dict:
    """
    Endpoint Asisten Navigasi & Analisis AI (RadarBot).
    Dilengkapi 4 lapisan proteksi anti-limit:
    1. Cooldown anti-spam per IP
    2. Cache jawaban pintar 10 menit
    3. Eksekusi navigasi & analisis kuantitatif instan dari memori server
    4. Opsional Cloud LLM (Gemini 1.5 Flash -> Fallback Groq Llama 3 -> Fallback Kuantitatif Lokal)
    """
    client_ip = (request.client.host if request.client else "unknown")
    now = _ai_time.time()
    last_ts = AI_IP_LAST_CALL.get(client_ip, 0.0)
    if now - last_ts < 1.2:
        raise HTTPException(status_code=429, detail="Mohon tunggu sejenak sebelum mengirim pesan berikutnya.")
    AI_IP_LAST_CALL[client_ip] = now

    raw_msg = str(payload.message or "").strip()
    if not raw_msg:
        raise HTTPException(status_code=400, detail="Pesan tidak boleh kosong.")

    if STATE["analysis"] is None:
        init_default_state()
    analysis = STATE["analysis"] or {}
    all_stocks = analysis.get("stocks") or []
    kpis = analysis.get("kpis") or {}
    today_cands = analysis.get("today_candidates") or select_today_candidates(all_stocks[:100])

    norm_key = f"{raw_msg.lower()}|{payload.active_ticker or ''}|{STATE.get('last_sync_time', '')}"
    cached = AI_CHAT_CACHE.get(norm_key)
    if cached and (now - cached[0]) < 600.0:
        return cached[1]

    msg_lower = raw_msg.lower()
    actions: list[dict] = []
    stock_map = {str(s.get("ticker", "")).upper(): s for s in all_stocks}

    # Deteksi kode saham 4 huruf di pesan
    tokens = _ai_re.findall(r"\b[A-Za-z]{4}\b", raw_msg.upper())
    stop_words = {
        "CARA", "BUKA", "CARI", "APA", "YANG", "DARI", "HARI", "BISA", "SAYA", "UNTUK",
        "BELI", "JUAL", "LOT", "PLAN", "DANA", "KUAT", "SAJA", "LIAT", "CEK", "INFO",
        "BANK", "BATU", "BARA", "EMIT", "MAIN", "PADA", "KALO", "JIKA", "MAU", "TANYA",
        "BERI", "DATA", "SKOR", "RATA", "ATAS", "BAWA", "NAIK", "TURU", "RUGI", "TP1",
        "IHSG", "MODE", "TEMA", "PETA", "UANG", "GIMN", "MANA",
    }
    matched_ticker = None
    for tk in tokens:
        if tk not in stop_words and tk in stock_map:
            matched_ticker = tk
            break

    # Deteksi sektor
    sector_aliases = [
        ("Energy", ["energi", "energy", "batubara", "coal", "migas", "minyak", "gas"]),
        ("Basic Materials", ["bahan baku", "basic", "tambang", "emas", "nikel", "logam", "semen", "kimia", "mineral"]),
        ("Financials", ["keuangan", "bank", "perbankan", "financial", "asuransi", "leasing"]),
        ("Consumer Non-Cyclicals", ["konsumer primer", "makanan", "minuman", "sawit", "cpo", "rokok", "poultry", "primer"]),
        ("Consumer Cyclicals", ["konsumer non", "ritel", "otomotif", "media", "non-primer", "cyclical"]),
        ("Infrastructures", ["infrastruktur", "telko", "telekomunikasi", "menara", "tower", "konstruksi", "jalan tol"]),
        ("Properties & Real Estate", ["properti", "property", "real estate", "kawasan industri", "perumahan"]),
        ("Healthcare", ["kesehatan", "farmasi", "rumah sakit", "health", "obat", "medis"]),
        ("Technology", ["teknologi", "tech", "digital", "data center", "internet", "software"]),
        ("Industrials", ["perindustrian", "industri", "alat berat", "kabel", "keramik"]),
        ("Transportation & Logistics", ["transportasi", "logistik", "pelayaran", "kapal", "maskapai", "pengiriman"]),
    ]
    matched_sector = None
    matched_sector_indo = None
    for sec_code, kw_list in sector_aliases:
        if any(kw in msg_lower for kw in kw_list):
            matched_sector = sec_code
            matched_sector_indo = {
                "Energy": "Energi",
                "Basic Materials": "Bahan Baku",
                "Financials": "Keuangan",
                "Consumer Non-Cyclicals": "Konsumer Primer",
                "Consumer Cyclicals": "Konsumer Non-Primer",
                "Infrastructures": "Infrastruktur",
                "Properties & Real Estate": "Properti",
                "Healthcare": "Kesehatan",
                "Technology": "Teknologi",
                "Industrials": "Perindustrian",
                "Transportation & Logistics": "Transportasi",
            }.get(sec_code, sec_code)
            break

    # Bangun respon kuantitatif presisi & daftar aksi navigasi UI
    reply_lines: list[str] = []

    if any(k in msg_lower for k in ["hitung lot", "kalkulator", "berapa lot"]) or ("modal" in msg_lower and "juta" in msg_lower):
        cap_match = _ai_re.search(r"(\d+(?:[.,]\d+)?)\s*juta", msg_lower)
        cap_rp = int(float(cap_match.group(1).replace(",", ".")) * 1_000_000) if cap_match else 10_000_000
        tk = matched_ticker or (payload.active_ticker if payload.active_ticker in stock_map else (today_cands[0]["ticker"] if today_cands else "BBCA"))
        st = stock_map.get(tk, {})
        plan = st.get("trading_plan") or {}
        entry = int(plan.get("entry_price") or st.get("close") or 1000)
        sl = int(plan.get("stop_loss") or round(entry * 0.965))
        actions.append({"type": "calc_lot", "ticker": tk, "capital": cap_rp, "entry": entry, "sl": sl})
        per_share_risk = max(1.0, (entry - sl) + (entry * 0.004))
        lots_by_risk = int((cap_rp * 0.02) // (per_share_risk * 100))
        lots_by_cap = int((cap_rp * 0.20) // (entry * 1.0015 * 100))
        rec_lots = max(0, min(lots_by_risk, lots_by_cap))
        reply_lines.append(f"Saya telah membuka **Kalkulator Lot** untuk **{tk}** dengan modal **Rp {cap_rp:,.0f}**.".replace(",", "."))
        reply_lines.append(f"• Harga Antre Beli: **Rp {entry:,.0f}** | Stop Loss: **Rp {sl:,.0f}**".replace(",", "."))
        reply_lines.append(f"• Kapasitas Aman (Maks 20% Modal / Risiko 2%): **{rec_lots} Lot**")
    elif any(k in msg_lower for k in ["pemilik", "owner", "pengendali", "free float", "kepemilikan", "siapa punya"]):
        tk = matched_ticker or (payload.active_ticker if payload.active_ticker in stock_map else (today_cands[0]["ticker"] if today_cands else "BBCA"))
        st = stock_map.get(tk, {})
        own = get_stock_ownership(tk, st)
        actions.append({"type": "select_stock", "ticker": tk})
        reply_lines.append(f"**Struktur Kepemilikan & Free Float {tk} ({own.get('company_name', tk)}):**")
        reply_lines.append(f"• Pengendali Utama: **{own.get('owner_group', '-')}**")
        reply_lines.append(f"• Proporsi: Pengendali **{own.get('insider_pct', 0):.2f}%** | Institusi **{own.get('institution_pct', 0):.2f}%** | Publik (Free Float) **{own.get('public_pct', 0):.2f}%**")
        reply_lines.append(f"• Karakteristik: **{own.get('badge_text', '-')}** — {own.get('analysis', '')}")
    elif matched_ticker:
        st = stock_map[matched_ticker]
        plan = st.get("trading_plan") or {}
        entry = int(plan.get("entry_price") or st.get("close") or 0)
        tp1 = int(plan.get("target_1") or round(entry * 1.07))
        tp2 = int(plan.get("target_2") or round(entry * 1.12))
        sl = int(plan.get("stop_loss") or round(entry * 0.965))
        bdr = st.get("bdr_pct", 0)
        buyers = st.get("top_buyers") or "-"
        own = get_stock_ownership(matched_ticker, st)
        actions.append({"type": "select_stock", "ticker": matched_ticker})
        reply_lines.append(f"Menampilkan analisis & grafik **{matched_ticker}** di panel detail:")
        reply_lines.append(f"• Harga: **Rp {int(st.get('close', 0)):,.0f}** ({st.get('pct_change', 0):+.2f}%) | Skor Aliran Dana: **{st.get('smart_money_score', 0)}/100**".replace(",", "."))
        reply_lines.append(f"• Status: **{st.get('trigger_label', '-')}** | Modal Bandar (VWAP 5H): **Rp {int(st.get('bandar_avg_buy', 0)):,.0f}** ({st.get('diff_bandar_avg_pct', 0):+.1f}%)".replace(",", "."))
        if st.get("has_broker_summary") or buyers != "-":
            reply_lines.append(f"• Broker Summary 3H: Buyer **{buyers}** (BDR {bdr:+.1f}%)")
        reply_lines.append(f"• Kepemilikan: Pengendali **{own.get('insider_pct', 0):.1f}%** | Free Float **{own.get('public_pct', 0):.1f}%** ({own.get('owner_group', '-')})")
        reply_lines.append(f"• Trading Plan: Antre Beli **Rp {entry:,.0f}** | TP1 **Rp {tp1:,.0f}** | TP2 **Rp {tp2:,.0f}** | SL **Rp {sl:,.0f}**".replace(",", "."))
    elif matched_sector:
        actions.append({"type": "filter_sector", "sector": matched_sector})
        sec_stocks = [s for s in all_stocks if s.get("sector_category") == matched_sector]
        sec_stocks.sort(key=lambda x: (x.get("smart_money_score", 0), x.get("value_b_idr", 0)), reverse=True)
        top_names = ", ".join(f"**{s['ticker']}** (Skor {s['smart_money_score']})" for s in sec_stocks[:4]) or "-"
        reply_lines.append(f"Layar telah diarahkan ke **Tab Jelajah** dengan filter sektor **{matched_sector_indo}** ({len(sec_stocks)} emiten).")
        reply_lines.append(f"• Saham unggulan di sektor ini: {top_names}.")
    elif any(k in msg_lower for k in ["sektor", "rotasi", "peta sektor"]):
        actions.append({"type": "open_modal", "modal": "sector"})
        reply_lines.append("Membuka **Peta Rotasi & Aliran Dana Sektor BEI**.")
        reply_lines.append("Anda dapat melihat peringkat 11 sektor beserta rasio akumulasi dan saham penggerak utamanya.")
    elif any(k in msg_lower for k in ["ihsg", "kondisi pasar", "rezim", "breadth", "market"]):
        reg = kpis.get("market_regime") or {}
        actions.append({"type": "open_modal", "modal": "regime"})
        reply_lines.append(f"**Kondisi Pasar IHSG Saat Ini:** {reg.get('label', 'Konsolidasi')}")
        reply_lines.append(f"• Market Breadth MA20: **{reg.get('breadth_ma20_pct', 50)}%** | MA50: **{reg.get('breadth_ma50_pct', 50)}%**")
        reply_lines.append(f"• Panduan: {reg.get('regime_note', 'Disiplin antre di area support terdekat.')}")
    elif any(k in msg_lower for k in ["pantauan", "watchlist", "favorit", "win rate", "portofolio", "tracker"]):
        actions.append({"type": "switch_tab", "tab": "watchlist"})
        reply_lines.append("Membuka halaman **Pantauan (Favorit, Uji Sinyal Forward-Test & Portofolio Riil)**.")
    elif any(k in msg_lower for k in ["pilihan hari ini", "kandidat", "rekomendasi", "saham bagus", "siap beli", "hari ini"]):
        actions.append({"type": "switch_tab", "tab": "today"})
        top_list = ", ".join(f"**{c['ticker']}** (Rp {int(c.get('close',0)):,.0f})".replace(",", ".") for c in (today_cands or [])[:5])
        reply_lines.append("Menampilkan **Kandidat Saham Pilihan Hari Ini** (dekat rata-rata modal bandar & terverifikasi akumulasi):")
        reply_lines.append(f"• Kandidat Utama: {top_list or 'Memuat kandidat...'}")
        reply_lines.append("• Klik salah satu saham untuk melihat titik Antre Beli, Target TP1/TP2, dan Stop Loss.")
    else:
        # Pertanyaan umum / edukasi -> Coba panggil Cloud LLM jika API Key tersedia, atau jawab cerdas
        top_cands_str = ", ".join(f"{c['ticker']} (Skor {c.get('smart_money_score',0)}, Close {c.get('close',0)})" for c in (today_cands or [])[:5])
        reg_label = (kpis.get("market_regime") or {}).get("label", "Normal")
        sys_prompt = (
            "Anda adalah RadarBot, asisten AI kuantitatif di aplikasi RadarBandarIDX (Screener Smart Money & Bandarmologi BEI). "
            "Jawab singkat (maksimal 3-4 kalimat), padat, profesional dalam Bahasa Indonesia tanpa emoji berlebihan. "
            f"Data live bursa saat ini: Rezim IHSG={reg_label}, Saham Pilihan Hari Ini={top_cands_str}. "
            "Selalu ingatkan disiplin antre di support/modal bandar dan Stop Loss (DYOR, bukan ajakan beli/jual)."
        )
        llm_reply = _call_cloud_llm(sys_prompt, raw_msg)
        if llm_reply:
            reply_lines.append(llm_reply)
        else:
            reply_lines.append("Saya **RadarBot**, asisten navigasi & analisis kuantitatif RadarBandarIDX. Anda dapat memerintahkan saya untuk:")
            reply_lines.append("• **Cek Saham:** ketik kode saham (contoh: *'Analisis BBCA'* atau *'Cek ADRO'*)")
            reply_lines.append("• **Saring Sektor:** ketik *'Tampilkan sektor energi'* atau *'Peta sektor'*")
            reply_lines.append("• **Kandidat & Risiko:** ketik *'Saham pilihan hari ini'* atau *'Hitung lot ANTM modal 15 juta'*")

    resp_obj = {
        "status": "success",
        "reply": "\n".join(reply_lines),
        "actions": actions,
    }
    if len(AI_CHAT_CACHE) > 200:
        AI_CHAT_CACHE.clear()
    AI_CHAT_CACHE[norm_key] = (now, resp_obj)
    return resp_obj


# ===================== PROGRESSIVE WEB APP (PWA) =====================


@app.get("/favicon.ico")
def serve_favicon() -> FileResponse:
    ico_file = FRONTEND_DIR / "icons" / "favicon.ico"
    if not ico_file.exists():
        raise HTTPException(status_code=404, detail="favicon.ico tidak ditemukan")
    return FileResponse(
        str(ico_file),
        media_type="image/x-icon",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/manifest.json")
def serve_manifest() -> FileResponse:
    manifest_file = FRONTEND_DIR / "manifest.json"
    if not manifest_file.exists():
        raise HTTPException(status_code=404, detail="manifest.json tidak ditemukan")
    return FileResponse(
        str(manifest_file),
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


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
    return FileResponse(
        str(FRONTEND_DIR / "index.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, reload=False)
