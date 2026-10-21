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

    # Two-Stage Smart Funneling X-Ray (jika token Invezgo / provider tersedia)
    try:
        from broker_summary_fetcher import (
            load_broker_api_config,
            filter_stage1_funnel_candidates,
            run_stage2_broker_enrichment,
        )
        broker_cfg = load_broker_api_config()
        has_api_cred = bool(
            broker_cfg.get("invezgo_api_key") or
            broker_cfg.get("goapi_key") or
            broker_cfg.get("stockbit_token")
        )
        if has_api_cred:
            stage1_cands = filter_stage1_funnel_candidates(
                analysis.get("stocks", []),
                max_candidates=broker_cfg.get("max_candidates", 30),
            )
            if stage1_cands:
                run_stage2_broker_enrichment(
                    stage1_cands,
                    str(latest_dt),
                    broker_cfg,
                    details_map=analysis.get("details"),
                )
    except Exception as exc:
        print(f"[AutoMarketSync] Warning: Gagal enrichment broker summary: {exc}")

    tracker = SignalTracker(TRACKER_DB_PATH)
    eval_res = tracker.evaluate(analysis["details"])
    added_count = tracker.auto_track(analysis)

    # Sinkronisasi Pilihan Saham Hari Ini
    try:
        from screener_engine import select_today_candidates
        raw_picks = select_today_candidates(analysis["stocks"])
        today_cands = tracker.sync_today_candidates(
            raw_picks,
            str(latest_dt),
            session_label="Auto Sync EOD",
        )
        analysis["today_candidates"] = today_cands
        print(f"[AutoMarketSync] Pilihan Saham Hari Ini: {len(today_cands)} saham disinkronkan.")
    except Exception as exc:
        print(f"[AutoMarketSync] Warning: Gagal sinkronisasi today candidates: {exc}")

    tracker.engine.dispose()

    print(f"[AutoMarketSync] Evaluasi Tracker Selesai: {eval_res} | Sinyal Baru Ditambahkan: {added_count}")


if __name__ == "__main__":
    main()
