"""
SmartFlow IDX - Quantitative Walk-Forward Backtesting Engine
Menguji performa sinyal kuantitatif secara historis tanpa look-ahead bias:
1. Sinyal dievaluasi di akhir hari t menggunakan data hingga hari t.
2. Entry dieksekusi di hari t+1 jika harga menyentuh zona entry [entry_low, entry_high].
3. Posisi dipantau dengan batas Stop Loss berbasis ATR(14) dan Target Profit (2R / TP1).
4. Hasil dikelompokkan ke dalam Bucket Skor (80+, 70-79, 60-69, <60) untuk membuktikan expectancy kuantitatif.
"""

from __future__ import annotations

import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Pastikan root workspace terdaftar di sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.screener_engine import compute_quantitative_dataframe


@dataclass
class BacktestResultBucket:
    bucket_name: str
    total_signals: int
    trades_entered: int
    wins: int
    losses: int
    timeouts: int
    win_rate_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    expectancy_pct: float
    avg_holding_bars: float


def run_historical_backtest(
    market_df: pd.DataFrame,
    max_holding_bars: int = 10,
    min_liquidity_idr: float = 500_000_000,
) -> dict[str, Any]:
    """
    Menjalankan walk-forward historical backtesting pada dataset OHLCV saham BEI.
    """
    # Hitung seluruh indikator kuantitatif 5 pilar pada seluruh data
    df = compute_quantitative_dataframe(market_df)
    unique_dates = sorted(df["Date"].unique())

    if len(unique_dates) < 6:
        return {
            "error": "Data historis tidak mencukupi untuk backtest (minimal 6 hari bursa).",
            "buckets": {},
            "total_trades": 0,
        }

    # Buat indeks lookup harga harian per ticker untuk simulasi forward cepat
    price_matrix: dict[str, dict[str, dict[str, float]]] = {}
    for r in df[["Ticker", "Date", "Open", "High", "Low", "Close"]].itertuples():
        t = str(r.Ticker)
        d = str(r.Date)
        if t not in price_matrix:
            price_matrix[t] = {}
        price_matrix[t][d] = {
            "open": float(r.Open),
            "high": float(r.High),
            "low": float(r.Low),
            "close": float(r.Close),
        }

    date_to_idx = {d: i for i, d in enumerate(unique_dates)}
    trade_logs: list[dict[str, Any]] = []

    # Iterasi tanggal evaluasi sinyal (sampai N hari sebelum tanggal terakhir)
    eval_dates = unique_dates[:-1]

    for date_str in eval_dates:
        curr_idx = date_to_idx[date_str]
        sub_latest = df[df["Date"] == date_str]

        # Filter saham aktif & likuid pada tanggal tersebut
        candidates = sub_latest[
            (sub_latest["Close"] >= 50)
            & (sub_latest["Value_IDR"] >= min_liquidity_idr)
            & (sub_latest["Volume_Ratio"] >= 1.0)
        ]

        for cand in candidates.itertuples():
            ticker = str(cand.Ticker)
            score = int(cand.Daily_SM_Score) if hasattr(cand, "Daily_SM_Score") else 50
            trigger_type = str(cand.Trigger_Type) if hasattr(cand, "Trigger_Type") else "NEUTRAL_FLOW"

            # Ambil trading plan
            close_p = float(cand.Close)
            atr14 = float(cand.ATR14) if hasattr(cand, "ATR14") else max(1.0, close_p * 0.03)

            entry_high = close_p
            entry_low = round(close_p * 0.99)
            sl_dist = max(entry_low * 0.025, min(entry_low * 0.075, 1.75 * atr14))
            stop_loss = round(entry_low - sl_dist)
            risk = max(1.0, entry_high - stop_loss)
            tp1 = round(entry_high + 2.0 * risk)

            # Klasifikasikan ke bucket
            if score >= 80:
                bucket_key = "SCORE_80_PLUS"
            elif score >= 70:
                bucket_key = "SCORE_70_79"
            elif score >= 60:
                bucket_key = "SCORE_60_69"
            else:
                bucket_key = "SCORE_BELOW_60"

            # Simulasi forward test mulai hari bursa berikutnya (curr_idx + 1)
            future_dates = unique_dates[curr_idx + 1 :]
            if not future_dates:
                continue

            ticker_prices = price_matrix.get(ticker, {})

            # Cek entry di hari t+1
            day1_date = future_dates[0]
            if day1_date not in ticker_prices:
                continue

            day1_bar = ticker_prices[day1_date]
            is_entry = day1_bar["low"] <= entry_high and day1_bar["high"] >= entry_low

            if not is_entry:
                trade_logs.append({
                    "ticker": ticker,
                    "date": date_str,
                    "score": score,
                    "bucket": bucket_key,
                    "entered": False,
                    "result": "NO_ENTRY",
                    "pnl_pct": 0.0,
                    "bars_held": 0,
                })
                continue

            # Posisi berhasil terbuka
            entry_price = min(day1_bar["open"], entry_high) if day1_bar["open"] <= entry_high else entry_high
            status = "TIMEOUT"
            exit_price = entry_price
            pnl_pct = 0.0
            bars_held = 0

            # Pantau bar-by-bar
            for b_idx, f_date in enumerate(future_dates[:max_holding_bars]):
                bars_held = b_idx + 1
                if f_date not in ticker_prices:
                    continue
                bar = ticker_prices[f_date]

                hit_sl = bar["low"] <= stop_loss
                hit_tp = bar["high"] >= tp1

                # Di hari pertama entry, TP belum dihitung (konservatif)
                if b_idx == 0:
                    if hit_sl:
                        status = "LOSS"
                        exit_price = min(bar["open"], stop_loss)
                        break
                    continue

                if hit_sl and hit_tp:
                    status = "LOSS"
                    exit_price = stop_loss
                    break
                elif hit_tp:
                    status = "WIN"
                    exit_price = max(bar["open"], tp1)
                    break
                elif hit_sl:
                    status = "LOSS"
                    exit_price = min(bar["open"], stop_loss)
                    break

            if status == "TIMEOUT" and bars_held > 0:
                last_bar_date = future_dates[min(bars_held - 1, len(future_dates) - 1)]
                if last_bar_date in ticker_prices:
                    exit_price = ticker_prices[last_bar_date]["close"]

            pnl_pct = round(((exit_price - entry_price) / max(entry_price, 1.0)) * 100.0, 2)
            trade_logs.append({
                "ticker": ticker,
                "date": date_str,
                "score": score,
                "bucket": bucket_key,
                "entered": True,
                "result": status,
                "pnl_pct": pnl_pct,
                "bars_held": bars_held,
            })

    # Rekapitulasi Metrik per Bucket Skor
    buckets_summary: dict[str, dict[str, Any]] = {}
    bucket_order = [
        ("SCORE_80_PLUS", "Skor 80 - 100 (High Conviction)"),
        ("SCORE_70_79", "Skor 70 - 79 (Strong Accumulation)"),
        ("SCORE_60_69", "Skor 60 - 69 (Moderate Setup)"),
        ("SCORE_BELOW_60", "Skor < 60 (Benchmark / Control)"),
    ]

    for b_key, b_label in bucket_order:
        b_trades = [t for t in trade_logs if t["bucket"] == b_key]
        total_sig = len(b_trades)
        entered_trades = [t for t in b_trades if t["entered"]]
        n_entered = len(entered_trades)

        wins = [t for t in entered_trades if t["result"] == "WIN"]
        losses = [t for t in entered_trades if t["result"] == "LOSS"]
        timeouts = [t for t in entered_trades if t["result"] == "TIMEOUT"]

        n_win = len(wins)
        n_loss = len(losses)
        n_to = len(timeouts)

        win_rate = round((n_win / max(n_win + n_loss, 1)) * 100.0, 1) if (n_win + n_loss) > 0 else 0.0

        avg_win = round(float(np.mean([t["pnl_pct"] for t in wins])), 2) if wins else 0.0
        avg_loss = round(float(np.mean([t["pnl_pct"] for t in losses])), 2) if losses else 0.0

        total_gain = sum(t["pnl_pct"] for t in wins)
        total_loss_abs = abs(sum(t["pnl_pct"] for t in losses))
        profit_factor = round(total_gain / max(total_loss_abs, 1e-4), 2) if total_loss_abs > 0 else (99.0 if total_gain > 0 else 0.0)

        # Expectancy = (Win_Rate * Avg_Win) - (Loss_Rate * |Avg_Loss|)
        win_prob = n_win / max(n_win + n_loss, 1)
        loss_prob = n_loss / max(n_win + n_loss, 1)
        expectancy = round((win_prob * avg_win) - (loss_prob * abs(avg_loss)), 2) if (n_win + n_loss) > 0 else 0.0

        avg_bars = round(float(np.mean([t["bars_held"] for t in entered_trades])), 1) if entered_trades else 0.0

        bucket_obj = BacktestResultBucket(
            bucket_name=b_label,
            total_signals=total_sig,
            trades_entered=n_entered,
            wins=n_win,
            losses=n_loss,
            timeouts=n_to,
            win_rate_pct=win_rate,
            avg_win_pct=avg_win,
            avg_loss_pct=avg_loss,
            profit_factor=profit_factor,
            expectancy_pct=expectancy,
            avg_holding_bars=avg_bars,
        )
        buckets_summary[b_key] = asdict(bucket_obj)

    return {
        "status": "success",
        "total_evaluated_dates": len(eval_dates),
        "total_signals_tested": len(trade_logs),
        "total_trades_entered": sum(b["trades_entered"] for b in buckets_summary.values()),
        "buckets": buckets_summary,
    }


if __name__ == "__main__":
    cache_p = Path(__file__).resolve().parent.parent / "data" / "real_idx_market_latest.csv"
    if cache_p.exists():
        df_test = pd.read_csv(cache_p)
        res = run_historical_backtest(df_test)
        print("=== HASIL WALK-FORWARD HISTORICAL BACKTEST ===")
        for k, v in res.get("buckets", {}).items():
            print(f"\n[{v['bucket_name']}]")
            print(f"  Total Signals: {v['total_signals']} | Entered: {v['trades_entered']}")
            print(f"  Win Rate: {v['win_rate_pct']}% (Wins: {v['wins']}, Losses: {v['losses']}, Timeouts: {v['timeouts']})")
            print(f"  Avg Win: +{v['avg_win_pct']}% | Avg Loss: {v['avg_loss_pct']}%")
            print(f"  Profit Factor: {v['profit_factor']} | Expectancy: {v['expectancy_pct']:+}% per trade")
