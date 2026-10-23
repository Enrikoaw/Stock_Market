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

    # Penarikan Broksum 3H Seluruh Saham Terdaftar ke Database (HANYA 1x sehari saat Bursa Tutup / 18:00 WIB).
    # Saat jam bursa berlangsung, sistem langsung memvalidasi kandidat dari Database Broksum EOD (0 panggilan API).
    try:
        from broker_summary_fetcher import (
            load_broker_api_config,
            sync_all_stocks_broksum_eod,
            apply_broksum_db_to_analysis,
            can_run_broker_sync_now,
            record_broker_sync_done,
            filter_and_purge_watchlist_by_smart_money,
        )
        broker_cfg = load_broker_api_config()
        has_api_cred = bool(
            broker_cfg.get("invezgo_api_key") or
            broker_cfg.get("goapi_key") or
            broker_cfg.get("stockbit_token")
        )
        allowed, reason, session_name = can_run_broker_sync_now()

        if has_api_cred and allowed:
            print(f"[AutoMarketSync] 📡 Menarik Broksum 3H Seluruh Saham ke Database ({reason})...")
            all_reg_tickers = [str(s.get("ticker", "")).upper() for s in analysis.get("stocks", []) if s.get("ticker")]
            sync_all_stocks_broksum_eod(
                date_str=str(latest_dt),
                tickers=all_reg_tickers,
                cfg=broker_cfg,
                force=False,
            )
            if session_name:
                record_broker_sync_done(session_name, str(latest_dt))
        else:
            print(f"[AutoMarketSync] ⏱️ Validasi Broksum dari Database EOD Lokal ({reason}).")

        apply_broksum_db_to_analysis(analysis)
        from screener_engine import select_today_candidates
        analysis["today_candidates"] = select_today_candidates(analysis["stocks"])

        purge_res = filter_and_purge_watchlist_by_smart_money(
            tracker,
            analysis=analysis,
            date_str=str(latest_dt),
            cfg=broker_cfg,
        )
        print(f"[AutoMarketSync] Audit Smart Money Database EOD: {purge_res.get('retained_count')} lolos, {purge_res.get('eliminated_count')} ritel/distribusi dihapus.")
    except Exception as exc:
        print(f"[AutoMarketSync] Warning: Gagal sinkronisasi/validasi broker summary database: {exc}")

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
