"""
Script Otomatis Sinkronisasi Pasar BEI (IDX) & Evaluasi Signal Tracker
Dijalankan oleh GitHub Actions selama jam bursa (Senin - Jumat) agar:
1. Data harga 844 saham BEI (data/real_idx_market_latest.csv) selalu terupdate otomatis setiap hari bursa.
2. Status Watchlist, Running, TP (Win), & SL (Loss) di data/tracker.db selalu terevaluasi otomatis
   walaupun user sedang tidak membuka website.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
BACKEND_DIR = Path(__file__).resolve().parent
for p in (str(BASE_DIR), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from backend.excel_generator import generate_900_idx_master_tickers_df
    from backend.live_idx_fetcher import fetch_real_idx_market_data
    from backend.screener_engine import analyze_smart_money_dataframe
    from backend.signal_tracker import SignalTracker
except ImportError:
    from excel_generator import generate_900_idx_master_tickers_df
    from live_idx_fetcher import fetch_real_idx_market_data
    from screener_engine import analyze_smart_money_dataframe
    from signal_tracker import SignalTracker

DATA_DIR = BASE_DIR / "data"
# Disamakan dengan backend/main.py agar daftar saham yang dipantau identik
MASTER_UPLOADED_CSV = DATA_DIR / "master_uploaded_tickers.csv"
REAL_CACHE_CSV = DATA_DIR / "real_idx_market_latest.csv"
TRACKER_DB_PATH = DATA_DIR / "tracker.db"


def main() -> None:
    print("[AutoMarketSync] Memulai sinkronisasi data pasar BEI (IDX)...")
    if MASTER_UPLOADED_CSV.exists():
        tickers_df = pd.read_csv(MASTER_UPLOADED_CSV)
    else:
        tickers_df = generate_900_idx_master_tickers_df()

    real_df = fetch_real_idx_market_data(
        tickers_df,
        output_csv_path=REAL_CACHE_CSV,
        period="auto",
        max_workers=4,
    )
    if "Has_Broker_Summary" not in real_df.columns:
        real_df["Has_Broker_Summary"] = False

    print("[AutoMarketSync] Menganalisis 5-Pilar Smart Money & Auto Trading Plan...")
    analysis = analyze_smart_money_dataframe(real_df)
    latest_dt = analysis.get("kpis", {}).get("latest_date", "-")
    print(f"[AutoMarketSync] Tanggal Bursa Terbaru: {latest_dt} | Total Emiten: {len(analysis.get('stocks', []))}")

    tracker = SignalTracker(TRACKER_DB_PATH)

    # Sinkronisasi & Seleksi Awal Pilihan Saham Hari Ini
    try:
        from screener_engine import select_today_candidates
        raw_picks = select_today_candidates(analysis["stocks"])
        analysis["today_candidates"] = raw_picks
    except Exception as exc:
        print(f"[AutoMarketSync] Warning: Gagal seleksi awal today candidates: {exc}")

    # Two-Stage Smart Funneling X-Ray (Pilihan Saham Hari Ini + Watchlist Aktif + Stage 1)
    # HANYA dijalankan 2x sehari (tepat setelah Sesi 1 dan setelah Sesi 2).
    # DILARANG KERAS menarik broksum selama Sesi 1 belum selesai!
    try:
        from broker_summary_fetcher import (
            load_broker_api_config,
            enrich_candidates_and_watchlist,
        )
        broker_cfg = load_broker_api_config()
        has_api_cred = bool(
            broker_cfg.get("invezgo_api_key") or
            broker_cfg.get("goapi_key") or
            broker_cfg.get("stockbit_token")
        )
        from datetime import datetime, time as dtime
        try:
            from zoneinfo import ZoneInfo
            now_wib = datetime.now(ZoneInfo("Asia/Jakarta"))
        except Exception:
            now_wib = datetime.now()
        is_jumat = (now_wib.weekday() == 4)
        sesi1_end = dtime(11, 30) if is_jumat else dtime(12, 0)
        is_in_sesi1 = (now_wib.weekday() < 5) and (dtime(9, 0) <= now_wib.time() < sesi1_end)
        is_after_session = (sesi1_end <= now_wib.time() <= dtime(13, 30)) or (now_wib.time() >= dtime(16, 0)) or (now_wib.weekday() >= 5)

        if has_api_cred and not is_in_sesi1 and is_after_session:
            print("[AutoMarketSync] 📡 Mengambil Broker Summary Invezgo (Pasca Sesi 1/Sesi 2)...")
            enrich_candidates_and_watchlist(
                analysis,
                str(latest_dt),
                tracker=tracker,
                cfg=broker_cfg,
                max_total_candidates=broker_cfg.get("max_candidates", 35),
            )

            # Seleksi & Eliminasi Sinyal Watchlist yang Didominasi Ritel / Distribusi
            from broker_summary_fetcher import filter_and_purge_watchlist_by_smart_money
            purge_res = filter_and_purge_watchlist_by_smart_money(
                tracker,
                analysis=analysis,
                date_str=str(latest_dt),
                cfg=broker_cfg,
            )
            print(f"[AutoMarketSync] Audit Smart Money Watchlist: {purge_res.get('retained_count')} lolos, {purge_res.get('eliminated_count')} ritel/distribusi dihapus.")
        else:
            print("[AutoMarketSync] ⏱️ Skip Penarikan Broksum (Sesi 1 belum selesai atau update interval rutin). Hanya update harga pasar & evaluasi Running/SL/TP.")
    except Exception as exc:
        print(f"[AutoMarketSync] Warning: Gagal enrichment broker summary: {exc}")

    eval_res = tracker.evaluate(analysis["details"])
    added_count = tracker.auto_track(analysis)

    # Finalisasi Sinkronisasi Pilihan Saham Hari Ini ke Database & Watchlist
    try:
        from screener_engine import select_today_candidates
        final_picks = analysis.get("today_candidates") or select_today_candidates(analysis["stocks"])
        today_cands = tracker.sync_today_candidates(
            date_str=str(latest_dt),
            candidate_stocks=final_picks,
            all_stocks=analysis["stocks"],
        )
        analysis["today_candidates"] = today_cands
        print(f"[AutoMarketSync] Pilihan Saham Hari Ini: {len(today_cands)} saham disinkronkan ke Watchlist & Broker Summary.")
    except Exception as exc:
        print(f"[AutoMarketSync] Warning: Gagal finalisasi today candidates: {exc}")

    tracker.engine.dispose()

    print(f"[AutoMarketSync] Evaluasi Tracker Selesai: {eval_res} | Sinyal Baru Ditambahkan: {added_count}")


if __name__ == "__main__":
    main()
