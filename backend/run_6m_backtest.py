"""
SmartFlow IDX - 6-Month Walk-Forward Historical Backtest Runner
Mengunduh data pasar 6 bulan ke belakang (~125 hari bursa) untuk seluruh saham IDX
dan menjalankan evaluasi backtesting walk-forward secara mandiri.
"""

from __future__ import annotations

import gc
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

# Pastikan root workspace terdaftar di sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.live_idx_fetcher import fetch_real_idx_market_data
from backend.screener_engine import compute_quantitative_dataframe
from backend.backtest_engine import run_historical_backtest


DATA_DIR = BASE_DIR / "data"
CACHE_6MO_CSV = DATA_DIR / "real_idx_market_6mo.csv"
MASTER_TICKERS_CSV = DATA_DIR / "master_uploaded_tickers.csv"


def get_or_download_6m_data() -> pd.DataFrame:
    """Mengambil atau mengunduh dataset 6 bulan ke belakang untuk seluruh saham IDX."""
    if CACHE_6MO_CSV.exists() and CACHE_6MO_CSV.stat().st_size > 1_000_000:
        print(f"[6M Backtest] Menggunakan cache 6 bulan yang sudah ada: {CACHE_6MO_CSV} ({CACHE_6MO_CSV.stat().st_size / 1024 / 1024:.1f} MB)")
        df = pd.read_csv(CACHE_6MO_CSV)
        print(f"   -> Terbaca {len(df):,} baris, {df['Ticker'].nunique()} emiten, rentang tanggal: {df['Date'].min()} s/d {df['Date'].max()} ({df['Date'].nunique()} hari bursa)")
        return df

    print("[6M Backtest] Cache 6 bulan belum ada. Memulai pengunduhan data 6 bulan dari bursa...")
    if not MASTER_TICKERS_CSV.exists():
        raise FileNotFoundError(f"Master ticker file {MASTER_TICKERS_CSV} tidak ditemukan.")

    tickers_df = pd.read_csv(MASTER_TICKERS_CSV)
    print(f"   -> Terdaftar {len(tickers_df)} emiten master. Mengunduh data 6mo...")

    # Unduh dengan period='6mo', max_workers=3, batch_size=60
    df = fetch_real_idx_market_data(
        tickers_df=tickers_df,
        output_csv_path=CACHE_6MO_CSV,
        period="6mo",
        batch_size=80,
        max_workers=3,
        force_full=True,
    )
    print(f"[6M Backtest] Pengunduhan selesai! Data disimpan ke {CACHE_6MO_CSV}")
    return df


def run_detailed_6m_analysis(market_df: pd.DataFrame) -> dict:
    """Menjalankan backtest komprehensif dan menghasilkan analisis mendalam."""
    print("\n[6M Backtest] Menghitung indikator kuantitatif 5 pilar untuk seluruh data 6 bulan...")
    t0 = time.time()
    
    # Hitung 5 pilar
    df = compute_quantitative_dataframe(market_df)
    unique_dates = sorted(df["Date"].unique())
    total_dates = len(unique_dates)
    print(f"   -> Selesai dalam {time.time() - t0:.1f}s. Total hari bursa: {total_dates} hari.")

    # Jalankan engine walk-forward
    print("[6M Backtest] Menjalankan simulasi Walk-Forward (Zero Look-Ahead Bias)...")
    res = run_historical_backtest(market_df, max_holding_bars=10, min_liquidity_idr=1_000_000_000)
    
    return res


if __name__ == "__main__":
    t_start_total = time.time()
    df_6m = get_or_download_6m_data()
    res = run_detailed_6m_analysis(df_6m)

    output_lines = []
    output_lines.append("=" * 70)
    output_lines.append("HASIL LENGKAP BACKTEST HISTORIS 6 BULAN (SMARTFLOW IDX)")
    output_lines.append("=" * 70)
    output_lines.append(f"Total Hari Bursa Dievaluasi : {res.get('total_evaluated_dates', 0)} hari")
    output_lines.append(f"Total Sinyal Teridentifikasi: {res.get('total_signals_tested', 0):,} sinyal")
    output_lines.append(f"Total Trade Masuk Area Beli : {res.get('total_trades_entered', 0):,} trade")
    output_lines.append("-" * 70)

    for b_key, b in res.get("buckets", {}).items():
        output_lines.append(f"\n[{b['bucket_name']}]")
        output_lines.append(f"  - Total Sinyal Muncul : {b['total_signals']:,} | Masuk Beli: {b['trades_entered']:,}")
        output_lines.append(f"  - Win Rate (TP Hit)   : {b['win_rate_pct']}% (Menang: {b['wins']:,} | Rugi: {b['losses']:,} | Timeout: {b['timeouts']:,})")
        output_lines.append(f"  - Rata-rata Untung    : +{b['avg_win_pct']}%")
        output_lines.append(f"  - Rata-rata Rugi      : {b['avg_loss_pct']}%")
        output_lines.append(f"  - Profit Factor       : {b['profit_factor']}")
        output_lines.append(f"  - Expectancy per Trade: {b['expectancy_pct']:+}%")
        output_lines.append(f"  - Rata-rata Waktu Hold: {b['avg_holding_bars']} hari bursa")

    output_lines.append("\n" + "=" * 70)
    output_lines.append(f"Total Waktu Proses: {time.time() - t_start_total:.1f} detik")
    output_lines.append("=" * 70)

    summary_text = "\n".join(output_lines)
    print(summary_text)

    # Simpan hasil dalam format JSON
    json_path = DATA_DIR / "backtest_6m_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2)

    # Simpan laporan Markdown
    md_path = DATA_DIR / "backtest_6m_report.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# Laporan Backtest Historis 6 Bulan SmartFlow IDX\n\n```\n" + summary_text + "\n```\n")

    print(f"\n[6M Backtest] Laporan lengkap berhasil disimpan ke {json_path} dan {md_path}")
