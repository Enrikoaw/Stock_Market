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
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.excel_generator import generate_900_idx_master_tickers_df
from backend.live_idx_fetcher import fetch_real_idx_market_data
from backend.screener_engine import analyze_smart_money_dataframe
from backend.signal_tracker import SignalTracker

DATA_DIR = BASE_DIR / "data"
USER_EXCEL_DIR = DATA_DIR / "user_excel"
MASTER_UPLOADED_CSV = USER_EXCEL_DIR / "master_uploaded_idx.csv"
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
    real_df["Has_Broker_Summary"] = True

    print("[AutoMarketSync] Menganalisis 5-Pilar Smart Money & Auto Trading Plan...")
    analysis = analyze_smart_money_dataframe(real_df)
    latest_dt = analysis.get("kpis", {}).get("latest_date", "-")
    print(f"[AutoMarketSync] Tanggal Bursa Terbaru: {latest_dt} | Total Emiten: {len(analysis.get('stocks', []))}")

    tracker = SignalTracker(TRACKER_DB_PATH)
    eval_res = tracker.evaluate(analysis["details"])
    added_count = tracker.auto_track(analysis)
    tracker.prune_over_bandar_signals(analysis["details"])

    print(f"[AutoMarketSync] Evaluasi Tracker Selesai: {eval_res} | Sinyal Baru Ditambahkan: {added_count}")


if __name__ == "__main__":
    main()
