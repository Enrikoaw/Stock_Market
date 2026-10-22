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
BACKEND_DIR = Path(__file__).resolve().parent
for p in (str(BASE_DIR), str(BACKEND_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    from backend.screener_engine import compute_quantitative_dataframe, _round_idx_tick, compute_support_entry_plan
except ImportError:
    from screener_engine import compute_quantitative_dataframe, _round_idx_tick, compute_support_entry_plan


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
    max_holding_bars: int = 5,
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

    # Parameter 1: Muat indeks makro IHSG > MA50 dari ihsg_5y.csv bila tersedia
    ihsg_uptrend_map: dict[str, bool] = {}
    try:
        ihsg_csv = BASE_DIR / "data" / "ihsg_5y.csv"
        if ihsg_csv.exists():
            ihsg_df = pd.read_csv(ihsg_csv, usecols=["Date", "Close"]).sort_values("Date").reset_index(drop=True)
            ihsg_df["MA50"] = ihsg_df["Close"].rolling(50, min_periods=20).mean()
            ihsg_df["Uptrend"] = ihsg_df["Close"] >= ihsg_df["MA50"]
            ihsg_uptrend_map = dict(zip(ihsg_df["Date"].astype(str), ihsg_df["Uptrend"].astype(bool)))
    except Exception:
        ihsg_uptrend_map = {}

    # Iterasi tanggal evaluasi sinyal (sampai N hari sebelum tanggal terakhir)
    eval_dates = unique_dates[:-1]

    for date_str in eval_dates:
        curr_idx = date_to_idx[date_str]
        sub_latest = df[df["Date"] == date_str]
        if sub_latest.empty:
            continue

        # Evaluasi Sinyal Akumulasi (Sistem tanpa pembekuan IHSG, tetap selektif berbasis support terdekat)

        # 6 Filter Kuantitatif Wajib SmartFlow IDX:
        score_col = "Daily_SM_Score" if "Daily_SM_Score" in sub_latest.columns else "Smart_Money_Score"
        valid_triggers = ("MARKUP_BREAKOUT", "BIG_ACCUMULATION", "SILENT_ACCUMULATION", "FOREIGN_INFLOW")
        sec_col = sub_latest["Sector"].astype(str).str.lower() if "Sector" in sub_latest.columns else pd.Series("", index=sub_latest.index)

        candidates = sub_latest[
            (sub_latest["Close"] >= 70)
            & (~sec_col.str.contains("pemantauan khusus", na=False))
            & (~sec_col.str.contains("akselerasi", na=False))
            & (sub_latest["Value_IDR"] >= min_liquidity_idr)
            & (sub_latest["Volume_Ratio"] >= 1.0)
            & (sub_latest["Closing_Range"] >= 0.65)
            & (sub_latest["Pct_Change"] >= -1.5)
            & (sub_latest["Pct_Change"] <= 5.5)
            & (sub_latest["Trigger_Type"].isin(valid_triggers))
            & (sub_latest[score_col] >= 70)
            & (sub_latest["Diff_VWAP_Pct"] >= -1.0)
            & (sub_latest["Diff_VWAP_Pct"] <= 3.5)
        ]

        for cand in candidates.itertuples():
            ticker = str(cand.Ticker)
            score = int(getattr(cand, score_col)) if hasattr(cand, score_col) else 70
            trigger_type = str(cand.Trigger_Type) if hasattr(cand, "Trigger_Type") else "BIG_ACCUMULATION"

            # Ambil trading plan
            close_p = float(cand.Close)
            atr14 = float(cand.ATR14) if hasattr(cand, "ATR14") and not np.isnan(cand.ATR14) else max(1.0, close_p * 0.03)
            vwap_5d = float(cand.VWAP_5D) if hasattr(cand, "VWAP_5D") and not np.isnan(cand.VWAP_5D) else close_p
            pct_chg = float(cand.Pct_Change) if hasattr(cand, "Pct_Change") and not np.isnan(cand.Pct_Change) else 0.0
            diff_vwap = float(cand.Diff_VWAP_Pct) if hasattr(cand, "Diff_VWAP_Pct") and not np.isnan(cand.Diff_VWAP_Pct) else 0.0

            # Parameter 4: Titik Masuk (Entry) di Support Terdekat (Revisi ke support jika harga sudah terbang)
            ep_plan = compute_support_entry_plan(
                close_price=close_p,
                open_price=float(cand.Open) if hasattr(cand, "Open") else close_p,
                low_price=float(cand.Low) if hasattr(cand, "Low") else close_p,
                prev_close=float(cand.Prev_Close) if hasattr(cand, "Prev_Close") else close_p,
                pct_change=pct_chg,
                vwap_5d=vwap_5d,
                ma5=float(cand.MA5) if hasattr(cand, "MA5") else vwap_5d,
                ma10=float(cand.MA10) if hasattr(cand, "MA10") else vwap_5d,
                ma20=float(cand.MA20) if hasattr(cand, "MA20") else vwap_5d,
                prev_high_5d=float(cand.Prev_High_5D) if hasattr(cand, "Prev_High_5D") else close_p,
                atr14_val=atr14,
            )
            entry_high = float(ep_plan["entry_high"])
            entry_low = float(ep_plan["entry_low"])
            stop_loss = ep_plan["stop_loss"]
            risk = float(ep_plan["risk_idr"])
            tp1 = ep_plan["tp1"]
            tp2 = ep_plan["tp2"]

            # Klasifikasikan ke bucket (Semua wajib lolos skor >= 70)
            if score >= 80:
                bucket_key = "SCORE_80_PLUS"
            else:
                bucket_key = "SCORE_70_79"

            # Simulasi forward test mulai hari bursa berikutnya (curr_idx + 1)
            future_dates = unique_dates[curr_idx + 1 :]
            if not future_dates:
                continue

            ticker_prices = price_matrix.get(ticker, {})

            # Cek antrean entry maksimal 2 hari bursa (Pullback Retest Window)
            entry_bar_idx = None
            entry_bar = None
            gap_down_cancelled = False
            for wait_i in range(min(2, len(future_dates))):
                w_date = future_dates[wait_i]
                if w_date not in ticker_prices:
                    continue
                w_bar = ticker_prices[w_date]
                if w_bar["open"] <= stop_loss:
                    gap_down_cancelled = True
                    break
                if w_bar["low"] <= entry_high:
                    entry_bar_idx = wait_i
                    entry_bar = w_bar
                    break

            if gap_down_cancelled:
                trade_logs.append({
                    "ticker": ticker,
                    "date": date_str,
                    "score": score,
                    "bucket": bucket_key,
                    "entered": False,
                    "result": "EXPIRED_GAP_DOWN",
                    "pnl_pct": 0.0,
                    "bars_held": 0,
                })
                continue

            if entry_bar is None or entry_bar_idx is None:
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

            # Posisi berhasil terbuka (fill di harga open jika gap-down tipis di bawah entry_high, atau di entry_high)
            entry_price = min(entry_bar["open"], entry_high) if entry_bar["open"] <= entry_high else entry_high
            status = "TIMEOUT"
            exit_price = entry_price
            pnl_pct = 0.0
            bars_held = 0
            hit_tp2 = False

            active_future_dates = future_dates[entry_bar_idx : entry_bar_idx + max_holding_bars]

            # Pantau bar-by-bar mulai dari bar entry
            for b_idx, f_date in enumerate(active_future_dates):
                bars_held = b_idx + 1
                if f_date not in ticker_prices:
                    continue
                bar = ticker_prices[f_date]

                # Parameter 2: Evaluasi Stop Loss berbasis Closing Basis (close <= stop_loss) + Gap Down (open <= stop_loss) + Panic Crash (low <= stop_loss * 0.96)
                hit_sl = (bar["close"] <= stop_loss) or (bar["open"] <= stop_loss) or (bar["low"] <= stop_loss * 0.96)
                hit_tp = bar["high"] >= tp1

                # Gunakan harga realisasi sebenarnya (Open jika gap down di bawah SL, atau Close jika tembus SL closing basis)
                if b_idx == 0:
                    if hit_sl:
                        status = "LOSS"
                        exit_price = bar["open"] if bar["open"] <= stop_loss else (bar["close"] if bar["close"] <= stop_loss else stop_loss)
                        break
                    continue

                if bar["high"] >= tp2 and not hit_sl:
                    hit_tp2 = True

                if hit_sl and hit_tp:
                    status = "LOSS"
                    exit_price = bar["open"] if bar["open"] <= stop_loss else (bar["close"] if bar["close"] <= stop_loss else stop_loss)
                    break
                elif hit_tp:
                    status = "WIN"
                    exit_price = max(bar["open"], tp1)
                    break
                elif hit_sl:
                    status = "LOSS"
                    exit_price = bar["open"] if bar["open"] <= stop_loss else (bar["close"] if bar["close"] <= stop_loss else stop_loss)
                    break

            if status == "TIMEOUT" and bars_held > 0:
                last_bar_date = active_future_dates[min(bars_held - 1, len(active_future_dates) - 1)]
                if last_bar_date in ticker_prices:
                    exit_price = ticker_prices[last_bar_date]["close"]

            pnl_pct = round(((exit_price - entry_price) / max(entry_price, 1.0)) * 100.0, 2)
            tp2_pnl_pct = round(((tp2 - entry_price) / max(entry_price, 1.0)) * 100.0, 2) if hit_tp2 else pnl_pct
            trade_logs.append({
                "ticker": ticker,
                "date": date_str,
                "score": score,
                "bucket": bucket_key,
                "entered": True,
                "result": status,
                "pnl_pct": pnl_pct,
                "tp2_pnl_pct": tp2_pnl_pct,
                "hit_tp2": hit_tp2,
                "bars_held": bars_held,
            })

    # Rekapitulasi Metrik per Bucket Skor (Wajib Skor >= 70 Sesuai 6 Filter)
    buckets_summary: dict[str, dict[str, Any]] = {}
    bucket_order = [
        ("SCORE_80_PLUS", "Skor 80 - 100 (High Conviction)"),
        ("SCORE_70_79", "Skor 70 - 79 (Strong Accumulation)"),
    ]
    ROUNDTRIP_FEE_PCT = 0.40  # Estimasi fee sekuritas BEI beli (0.15%) + jual (0.25%)

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
        decided = n_win + n_loss + n_to

        # Win rate mencakup seluruh posisi yang tereksekusi (WIN + LOSS + TIMEOUT)
        win_rate = round((n_win / max(decided, 1)) * 100.0, 1) if decided > 0 else 0.0

        avg_win = round(float(np.mean([t["pnl_pct"] for t in wins])), 2) if wins else 0.0
        avg_loss = round(float(np.mean([t["pnl_pct"] for t in losses])), 2) if losses else 0.0

        total_gain = sum(t["pnl_pct"] for t in wins) + sum(t["pnl_pct"] for t in timeouts if t["pnl_pct"] > 0)
        total_loss_abs = abs(sum(t["pnl_pct"] for t in losses) + sum(t["pnl_pct"] for t in timeouts if t["pnl_pct"] < 0))
        profit_factor = round(total_gain / max(total_loss_abs, 1e-4), 2) if total_loss_abs > 0 else (99.0 if total_gain > 0 else 0.0)

        # Expectancy bersih mencakup seluruh trade yang masuk (WIN, LOSS, TIMEOUT) dikurangi biaya broker
        expectancy = (
            round(float(np.mean([t["pnl_pct"] - ROUNDTRIP_FEE_PCT for t in entered_trades])), 2)
            if entered_trades
            else 0.0
        )

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

    # Ringkasan Seluruh Sinyal Lolos 6 Filter
    all_entered = [t for t in trade_logs if t["entered"]]
    all_wins = [t for t in all_entered if t["result"] == "WIN"]
    all_losses = [t for t in all_entered if t["result"] == "LOSS"]
    all_timeouts = [t for t in all_entered if t["result"] == "TIMEOUT"]
    all_tp2 = [t for t in all_entered if t.get("hit_tp2")]

    n_all_w = len(all_wins)
    n_all_l = len(all_losses)
    n_all_to = len(all_timeouts)
    all_decided = n_all_w + n_all_l + n_all_to

    ov_win_rate = round((n_all_w / max(all_decided, 1)) * 100.0, 1) if all_decided > 0 else 0.0
    ov_loss_rate = round((n_all_l / max(all_decided, 1)) * 100.0, 1) if all_decided > 0 else 0.0
    ov_avg_win = round(float(np.mean([t["pnl_pct"] for t in all_wins])), 2) if all_wins else 0.0
    ov_avg_loss = round(float(np.mean([t["pnl_pct"] for t in all_losses])), 2) if all_losses else 0.0

    ov_gain = sum(t["pnl_pct"] for t in all_wins) + sum(t["pnl_pct"] for t in all_timeouts if t["pnl_pct"] > 0)
    ov_loss_abs = abs(sum(t["pnl_pct"] for t in all_losses) + sum(t["pnl_pct"] for t in all_timeouts if t["pnl_pct"] < 0))
    ov_pf = round(ov_gain / max(ov_loss_abs, 1e-4), 2) if ov_loss_abs > 0 else 0.0
    ov_rr = round(abs(ov_avg_win / max(abs(ov_avg_loss), 1e-4)), 2) if ov_avg_loss != 0 else 0.0

    total_emiten_count = int(df["Ticker"].nunique()) if "Ticker" in df.columns else 0
    total_candles_count = len(df)
    start_dt_str = str(unique_dates[0])
    end_dt_str = str(unique_dates[-1])
    n_trading_days = len(unique_dates)

    summary_6m = {
        "period_label": f"{start_dt_str} s/d {end_dt_str} ({n_trading_days} Hari Bursa)",
        "total_emiten": total_emiten_count,
        "total_candles": total_candles_count,
        "total_evaluated_dates": len(eval_dates),
        "total_signals_tested": len(trade_logs),
        "total_trades_entered": len(all_entered),
        "high_quality_signals": {
            "filter": "6 Filter Ketat (Skor >= 70, 4 Trigger Akumulasi, Jarak VWAP <= +3.5%, Turnover >= Rp 500 Juta)",
            "total_trades": len(all_entered),
            "tp1_wins": n_all_w,
            "tp1_win_rate_pct": ov_win_rate,
            "tp1_avg_win_pct": ov_avg_win,
            "tp2_wins": len(all_tp2),
            "tp2_win_rate_pct": round(len(all_tp2) / max(len(all_entered), 1) * 100.0, 1),
            "tp2_avg_win_pct": round(float(np.mean([t["tp2_pnl_pct"] for t in all_tp2])), 2) if all_tp2 else 0.0,
            "sl_losses": n_all_l,
            "sl_loss_pct": ov_loss_rate,
            "sl_avg_loss_pct": ov_avg_loss,
            "timeouts": n_all_to,
            "profit_factor": ov_pf,
            "risk_reward_ratio": f"1 : {ov_rr}",
            "sample_badge": f"Terverifikasi {total_emiten_count:,} Emiten BEI ({total_candles_count:,} Candle Riil - 6 Filter)".replace(",", "."),
        },
    }

    return {
        "status": "success",
        "total_evaluated_dates": len(eval_dates),
        "total_signals_tested": len(trade_logs),
        "total_trades_entered": sum(b["trades_entered"] for b in buckets_summary.values()),
        "buckets": buckets_summary,
        "summary_6m": summary_6m,
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
