"""
Signal Tracker — Forward Test Otomatis untuk SmartFlow IDX.

Siklus hidup sinyal:
    WATCHLIST  -> sinyal akumulasi tercatat, menunggu harga menyentuh zona entry
    RUNNING    -> zona entry tersentuh (posisi dianggap terbuka)
    WIN        -> harga menyentuh Target (TP)
    LOSS       -> harga menyentuh Stop Loss (SL)
    EXPIRED    -> zona entry tidak tersentuh dalam N hari / gap down di bawah SL
    TIMEOUT    -> posisi running melewati batas maksimal hari tahan (ditutup di harga close)

Aturan evaluasi (sengaja KONSERVATIF agar win rate tidak "terlalu indah"):
    1. Hanya candle HARIAN YANG SUDAH FINAL (setelah 16:15 WIB) yang dievaluasi.
    2. Entry hanya bisa terjadi mulai hari bursa SETELAH tanggal sinyal (tanpa look-ahead).
    3. Jika SL & TP tersentuh di candle yang sama -> dianggap LOSS (urutan intraday tidak diketahui).
    4. Di hari entry, SL tetap dihitung, tapi TP tidak dihitung.
    5. Gap: jika open sudah melewati SL/TP, harga exit memakai harga open (lebih realistis).

Penyimpanan:
    - Default: SQLite (data/tracker.db)
    - Jika env DATABASE_URL diisi (PostgreSQL Neon/Supabase), data tersimpan permanen di cloud.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from sqlalchemy import (
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    create_engine,
    delete,
    insert,
    select,
    update,
)

WIB = ZoneInfo("Asia/Jakarta")
MARKET_CLOSE_CUTOFF = dtime(16, 15)
ACTIVE_STATUSES = ("WATCHLIST", "RUNNING")
CLOSED_STATUSES = ("WIN", "LOSS", "EXPIRED", "TIMEOUT")
TRACKABLE_TRIGGERS = {"MARKUP_BREAKOUT", "BIG_ACCUMULATION", "SILENT_ACCUMULATION", "FOREIGN_INFLOW"}

metadata = MetaData()

signals_table = Table(
    "signals",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ticker", String(10), nullable=False, index=True),
    Column("sector", String(200)),
    Column("trigger_type", String(40)),
    Column("trigger_label", String(60)),
    Column("score", Integer),
    Column("source", String(10)),  # AUTO / MANUAL
    Column("signal_date", String(10), index=True),
    Column("signal_close", Float),
    Column("entry_low", Float),
    Column("entry_high", Float),
    Column("stop_loss", Float),
    Column("target", Float),
    Column("target_2", Float),
    Column("status", String(12), index=True),
    Column("entry_date", String(10)),
    Column("entry_price", Float),
    Column("exit_date", String(10)),
    Column("exit_price", Float),
    Column("pnl_pct", Float),
    Column("last_close", Float),
    Column("last_eval_date", String(10)),
    Column("bars_waited", Integer, default=0),
    Column("bars_held", Integer, default=0),
    Column("note", Text),
    Column("created_at", String(19)),
    Column("updated_at", String(19)),
)


def now_wib() -> datetime:
    return datetime.now(WIB)


def _now_str() -> str:
    return now_wib().strftime("%Y-%m-%d %H:%M:%S")


def last_final_session_date() -> str:
    """Tanggal candle harian terakhir yang dianggap FINAL (bursa sudah tutup)."""
    now = now_wib()
    if now.time() >= MARKET_CLOSE_CUTOFF:
        return now.strftime("%Y-%m-%d")
    return (now - timedelta(days=1)).strftime("%Y-%m-%d")


def _resolve_db_url(sqlite_path: Path) -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{sqlite_path.as_posix()}"
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


class SignalTracker:
    def __init__(self, sqlite_path: Path) -> None:
        self.min_score = int(os.environ.get("TRACKER_MIN_SCORE", "70"))
        self.tp_level = 2 if os.environ.get("TRACKER_TP_LEVEL", "1").strip() == "2" else 1
        self.entry_expiry_days = int(os.environ.get("TRACKER_ENTRY_EXPIRY_DAYS", "5"))
        self.max_hold_days = int(os.environ.get("TRACKER_MAX_HOLD_DAYS", "20"))
        self.fee_roundtrip_pct = float(os.environ.get("TRACKER_FEE_PCT", "0.4"))
        self._lock = threading.RLock()

        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        url = _resolve_db_url(sqlite_path)
        try:
            self.engine = self._make_engine(url)
            metadata.create_all(self.engine)
        except Exception as exc:  # DB cloud gagal -> tetap jalan dengan SQLite
            print(f"[Tracker] Gagal konek database ({exc}). Fallback ke SQLite lokal.")
            url = f"sqlite:///{sqlite_path.as_posix()}"
            self.engine = self._make_engine(url)
            metadata.create_all(self.engine)
        self.db_backend = "PostgreSQL (permanen)" if url.startswith("postgresql") else "SQLite (file lokal)"
        try:
            self.cleanup_non_compliant_signals()
            self.sync_targets_quick_profit()
        except Exception as e:
            print(f"[Tracker] Notice saat pembersihan sinyal 6 filter / sync TP: {e}")

    def sync_targets_quick_profit(self) -> int:
        """Menyesuaikan target price posisi aktif (WATCHLIST & RUNNING) ke formula Quick Profit TP1 (+4%) dan TP2 (+7%)."""
        from backend.screener_engine import _round_idx_tick
        updated = 0
        with self._lock, self.engine.begin() as conn:
            rows = conn.execute(
                select(signals_table).where(signals_table.c.status.in_(ACTIVE_STATUSES))
            ).mappings().all()
            for r in rows:
                e_high = float(r.get("entry_high") or r.get("entry_price") or r.get("signal_close") or 0)
                if e_high <= 0:
                    continue
                new_tp1 = _round_idx_tick(e_high * 1.04)
                new_tp2 = _round_idx_tick(e_high * 1.07)
                if new_tp2 <= new_tp1:
                    new_tp2 = _round_idx_tick(new_tp1 + (2 if e_high >= 200 else 1))
                cur_tp1 = float(r.get("target") or 0)
                cur_tp2 = float(r.get("target_2") or 0)
                if cur_tp1 != new_tp1 or cur_tp2 != new_tp2:
                    conn.execute(
                        update(signals_table)
                        .where(signals_table.c.id == r["id"])
                        .values(target=new_tp1, target_2=new_tp2, updated_at=_now_str())
                    )
                    updated += 1
        if updated > 0:
            print(f"[Tracker] Berhasil memperbarui {updated} sinyal aktif ke target TP1 (+4%) & TP2 (+7%).")
        return updated

    def cleanup_non_compliant_signals(self) -> int:
        """Menghapus seluruh sinyal (WATCHLIST, RUNNING, WIN, LOSS) yang melanggar 6 filter kuantitatif."""
        data_dir = Path(__file__).resolve().parent.parent / "data"
        val_map: dict[tuple[str, str], float] = {}
        for fn in ["real_idx_market_latest.csv", "real_idx_market_6mo.csv"]:
            p = data_dir / fn
            if p.exists():
                try:
                    df = pd.read_csv(p, usecols=["Ticker", "Date", "Value_IDR"])
                    for _, r in df.iterrows():
                        val_map[(str(r["Ticker"]).upper(), str(r["Date"]))] = float(r["Value_IDR"])
                except Exception:
                    pass

        removed = 0
        with self._lock, self.engine.begin() as conn:
            rows = conn.execute(select(signals_table)).mappings().all()
            ids_to_del: list[int] = []
            for r in rows:
                score = int(r.get("score") or 0)
                trig = str(r.get("trigger_type") or "")
                ticker = str(r.get("ticker") or "").upper()
                s_date = str(r.get("signal_date") or "")
                val_idr = val_map.get((ticker, s_date), 1_000_000_000.0)

                # 6 Filter: Skor >= 70, Sinyal Akumulasi Sah, Nilai Transaksi >= 1 Miliar
                if score < self.min_score or trig not in TRACKABLE_TRIGGERS or val_idr < 1_000_000_000:
                    ids_to_del.append(r["id"])

            if ids_to_del:
                conn.execute(delete(signals_table).where(signals_table.c.id.in_(ids_to_del)))
                removed = len(ids_to_del)
                print(f"[Tracker] Berhasil membersihkan {removed} sinyal yang melanggar 6 filter kuantitatif.")
        return removed

    @staticmethod
    def _make_engine(url: str):
        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        return create_engine(url, **kwargs)

    def config(self) -> dict:
        return {
            "min_score": self.min_score,
            "tp_level": self.tp_level,
            "entry_expiry_days": self.entry_expiry_days,
            "max_hold_days": self.max_hold_days,
            "fee_roundtrip_pct": self.fee_roundtrip_pct,
            "min_value_b_idr": 1.0,
            "db_backend": self.db_backend,
            "final_session_date": last_final_session_date(),
            "trackable_triggers": sorted(TRACKABLE_TRIGGERS),
        }

    # ------------------------------------------------------------------ add
    def add_signal(self, stock: dict, source: str = "MANUAL") -> tuple[bool, str]:
        plan = stock.get("trading_plan") or {}
        ticker = str(stock.get("ticker", "")).upper()
        signal_date = str(stock.get("date", ""))
        if not plan:
            return False, f"{ticker}: trading plan tidak tersedia."

        score_val = int(stock.get("smart_money_score", 0))
        if score_val < self.min_score:
            return False, f"{ticker}: Smart Money Score ({score_val}) belum memenuhi syarat minimal ({self.min_score}+)."

        e_low, e_high = sorted([float(plan["entry_low"]), float(plan["entry_high"])])
        sl = float(plan["stop_loss"])
        target = float(plan["target_2"] if self.tp_level == 2 else plan["target_1"])
        # Filter Tambahan: Jarak harga ke modal rata-rata bandar tidak boleh lebih dari +5.0%
        diff_bandar = stock.get("diff_bandar_avg_pct")
        if diff_bandar is None and "diff_bandar_avg_pct" in plan:
            diff_bandar = plan.get("diff_bandar_avg_pct")
        if diff_bandar is not None:
            try:
                diff_val = float(diff_bandar)
                if diff_val > 5.0:
                    return False, f"{ticker}: Jarak harga ke modal bandar ({diff_val:+.1f}%) melebihi batas toleransi aman (maks +5.0%)."
            except (ValueError, TypeError):
                pass

        # Filter ke-6: Nilai Transaksi Harian Minimal Rp 1.0 Miliar (Menolak Saham Gorengan Sepi / Tidak Likuid)
        val_b = stock.get("value_b_idr")
        if val_b is None and "value_idr" in stock:
            try:
                val_b = float(stock["value_idr"]) / 1e9
            except (ValueError, TypeError):
                val_b = 0.0
        if val_b is not None:
            try:
                val_num = float(val_b)
                if val_num < 1.0:
                    return False, f"{ticker}: Nilai transaksi harian (Rp {val_num:.2f} M) di bawah batas minimal likuiditas (Rp 1.0 Miliar)."
            except (ValueError, TypeError):
                pass

        with self._lock, self.engine.begin() as conn:
            active = conn.execute(
                select(signals_table.c.id).where(
                    and_(signals_table.c.ticker == ticker, signals_table.c.status.in_(ACTIVE_STATUSES))
                )
            ).first()
            if active:
                return False, f"{ticker} sudah ada di Watchlist/Running."
            dup = conn.execute(
                select(signals_table.c.id).where(
                    and_(signals_table.c.ticker == ticker, signals_table.c.signal_date == signal_date)
                )
            ).first()
            if dup:
                return False, f"Sinyal {ticker} tanggal {signal_date} sudah pernah dicatat."

            now = _now_str()
            conn.execute(
                insert(signals_table).values(
                    ticker=ticker,
                    sector=str(stock.get("sector", ""))[:200],
                    trigger_type=str(stock.get("trigger_type", "")),
                    trigger_label=str(stock.get("trigger_label", "")),
                    score=score_val,
                    source=source,
                    signal_date=signal_date,
                    signal_close=float(stock.get("close", 0)),
                    entry_low=e_low,
                    entry_high=e_high,
                    stop_loss=sl,
                    target=target,
                    target_2=float(plan.get("target_2", target)),
                    status="WATCHLIST",
                    last_close=float(stock.get("close", 0)),
                    last_eval_date=signal_date,
                    bars_waited=0,
                    bars_held=0,
                    note="Menunggu harga menyentuh zona entry.",
                    created_at=now,
                    updated_at=now,
                )
            )
        return True, f"{ticker} masuk Watchlist (zona entry Rp {e_low:,.0f} - {e_high:,.0f}, SL {sl:,.0f}, TP {target:,.0f})."

    def auto_track(self, analysis: dict) -> int:
        """Catat otomatis sinyal akumulasi (score >= min_score) dari sesi bursa yang terdeteksi."""
        market_date = analysis.get("kpis", {}).get("latest_date")
        added = 0
        for s in analysis.get("stocks", []):
            if s.get("trigger_type") not in TRACKABLE_TRIGGERS:
                continue
            if int(s.get("smart_money_score", 0)) < self.min_score:
                continue
            # Hanya catat sinyal dari tanggal analisis aktif
            if s.get("date") != market_date:
                continue
            ok, _ = self.add_signal(s, source="AUTO")
            if ok:
                added += 1
        return added

    def get_active_tickers(self) -> list[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(signals_table.c.ticker).where(signals_table.c.status.in_(ACTIVE_STATUSES)).distinct()
            ).scalars().all()
            return [str(t).upper() for t in rows]

    def sync_active_signals_live(self, extra_tickers: list[str] | None = None) -> dict:
        """Tarik harga & candle intraday/live terbaru secara cepat (< 3 detik) untuk saham yang aktif di Watchlist & Running (+ top screener), lalu evaluasi."""
        active_tickers = self.get_active_tickers()
        combined_tickers = list(dict.fromkeys(active_tickers + [t.upper() for t in (extra_tickers or []) if t]))
        if not combined_tickers:
            return {"entered": 0, "win": 0, "loss": 0, "expired": 0, "timeout": 0, "tickers_checked": 0}

        try:
            import yfinance as yf
            symbols = [f"{t}.JK" for t in combined_tickers]
            raw = yf.download(symbols, period="5d", progress=False, auto_adjust=False, threads=True)
            if raw is None or raw.empty:
                return {"entered": 0, "win": 0, "loss": 0, "expired": 0, "timeout": 0, "tickers_checked": 0}

            is_multi = isinstance(raw.columns, pd.MultiIndex)
            live_details = {}

            for ticker in combined_tickers:
                sym = f"{ticker}.JK"
                try:
                    if is_multi:
                        if sym in raw.columns.get_level_values(1):
                            sub = raw.xs(sym, level=1, axis=1).copy()
                        elif sym in raw.columns.get_level_values(0):
                            sub = raw.xs(sym, level=0, axis=1).copy()
                        else:
                            continue
                    else:
                        sub = raw.copy()

                    sub = sub.dropna(subset=["Close"]).copy()
                    if sub.empty:
                        continue

                    sub = sub.reset_index()
                    date_col = "Date" if "Date" in sub.columns else sub.columns[0]
                    sub["date"] = pd.to_datetime(sub[date_col]).dt.strftime("%Y-%m-%d")

                    history = []
                    for _, row_b in sub.iterrows():
                        history.append({
                            "date": str(row_b["date"]),
                            "open": float(row_b.get("Open", row_b["Close"])),
                            "high": float(row_b.get("High", row_b["Close"])),
                            "low": float(row_b.get("Low", row_b["Close"])),
                            "close": float(row_b["Close"]),
                            "volume": float(row_b.get("Volume", 0)),
                        })

                    live_details[ticker] = {
                        "ticker": ticker,
                        "close": float(history[-1]["close"]),
                        "history": history,
                    }
                except Exception as ex:
                    print(f"[TrackerLive] Error parsing {ticker}: {ex}")
                    continue

            changes = self.evaluate(live_details)
            changes["tickers_checked"] = len(live_details)
            changes["live_details"] = live_details
            return changes
        except Exception as exc:
            print(f"[TrackerLive] Error saat sync live: {exc}")
            return {"entered": 0, "win": 0, "loss": 0, "expired": 0, "timeout": 0, "tickers_checked": 0, "error": str(exc), "live_details": {}}

    def prune_over_bandar_signals(self, details: dict[str, dict]) -> int:
        """
        Solusi Proteksi Pintar (Watchlist vs Running/Win/Loss):
        1. Pintu Masuk Awal wajib Score >= 70 & Avg Bandar <= 5.0%.
        2. Jika masih di WATCHLIST:
           - Otomatis batalkan/hapus jika skor anjlok parah (<= 35) atau muncul DISTRIBUTION_WARNING (bandar guyur),
             atau jika harga sudah lari > 5.0% di atas Avg Bandar sebelum terbeli.
           - PERTAHANKAN di Watchlist jika skor turun moderat (36-69) karena koreksi sehat volume sepi (menjemput Zona Entry).
        3. Jika sudah di RUNNING, WIN, atau LOSS:
           - Kunci posisi (JANGAN dihapus otomatis saat besoknya skor berfluktuasi atau harga naik > 5% menuju TP).
           - Jika saat RUNNING tiba-tiba skor anjlok (<= 35) atau muncul DISTRIBUTION_WARNING, pasang peringatan
             '⚠️ AWAS DISTRIBUSI BANDAR' pada catatan posisi (Early Exit Warning).
        """
        if not details:
            return 0
        removed = 0
        with self._lock, self.engine.begin() as conn:
            rows = conn.execute(select(signals_table)).mappings().all()
            ids_to_delete: list[int] = []
            for row in rows:
                d = details.get(row["ticker"])
                if not d:
                    continue
                if "trading_plan" not in d or "smart_money_score" not in d:
                    continue

                st = str(row.get("status") or "WATCHLIST")
                cur_score = int(d.get("smart_money_score") or 0)
                row_score = int(row.get("score") or 0)
                cur_trigger = str(d.get("trigger_type") or "")
                is_dist_warning = cur_score <= 35 or cur_trigger == "DISTRIBUTION_WARNING"

                # Filter 6 Aturan Wajib: Turnover >= 1.0 Miliar, Skor >= 70, dan Trigger Akumulasi
                val_b = d.get("value_b_idr")
                if val_b is None and "value_idr" in d:
                    try:
                        val_b = float(d["value_idr"]) / 1e9
                    except (ValueError, TypeError):
                        val_b = 0.0
                try:
                    val_num = float(val_b) if val_b is not None else 1.0
                except (ValueError, TypeError):
                    val_num = 1.0

                # Jika tidak memenuhi 6 filter (misal likuiditas < 1M, skor < 70, atau bukan akumulasi), hapus dari sistem
                if val_num < 1.0 or cur_score < self.min_score or cur_trigger not in TRACKABLE_TRIGGERS:
                    ids_to_delete.append(row["id"])
                    continue

                diff_b = d.get("diff_bandar_avg_pct")
                if diff_b is None and isinstance(d.get("trading_plan"), dict):
                    diff_b = d["trading_plan"].get("diff_bandar_avg_pct")
                try:
                    diff_val = float(diff_b) if diff_b is not None else 0.0
                except (ValueError, TypeError):
                    diff_val = 0.0

                cur_close = float(d.get("close") or row.get("last_close") or 0)

                # 1. Aturan khusus WATCHLIST (belum terbeli):
                #    Jika terdeteksi distribusi volume atau harga sudah lari > 5% di atas VWAP 5H,
                #    tandai status sebagai CANCELLED (jangan hapus agar riwayat evaluasi jujur & transparan)
                if st == "WATCHLIST":
                    if is_dist_warning or diff_val > 5.0:
                        reason = "Distribusi Volume / Tekanan Jual" if is_dist_warning else f"Harga lari (+{diff_val:.1f}% di atas VWAP 5H)"
                        upd = {
                            "status": "CANCELLED",
                            "note": f"Dibatalkan otomatis ({reason}).",
                            "last_close": cur_close if cur_close > 0 else float(row.get("last_close") or 0),
                            "updated_at": _now_str(),
                        }
                        conn.execute(update(signals_table).where(signals_table.c.id == row["id"]).values(**upd))
                        continue

                # 2. Sinkronkan Zona Entry, SL, TP dengan Auto Trading Plan (kecuali bila berubah jadi DISTRIBUTION_WARNING saat RUNNING)
                plan = d.get("trading_plan") or {}
                if not plan:
                    continue

                upd: dict[str, Any] = {}
                if cur_close > 0 and float(row.get("last_close") or 0) != cur_close:
                    upd["last_close"] = cur_close
                if d.get("sector") and row.get("sector") != d.get("sector"):
                    upd["sector"] = str(d["sector"])[:200]

                if not is_dist_warning:
                    p_low, p_high = sorted([float(plan["entry_low"]), float(plan["entry_high"])])
                    p_sl = float(plan["stop_loss"])
                    p_tp = float(plan["target_2"] if self.tp_level == 2 else plan["target_1"])
                    p_tp2 = float(plan.get("target_2", p_tp))

                    if float(row.get("entry_low") or 0) != p_low:
                        upd["entry_low"] = p_low
                    if float(row.get("entry_high") or 0) != p_high:
                        upd["entry_high"] = p_high
                    if float(row.get("stop_loss") or 0) != p_sl:
                        upd["stop_loss"] = p_sl
                    if float(row.get("target") or 0) != p_tp:
                        upd["target"] = p_tp
                    if float(row.get("target_2") or 0) != p_tp2:
                        upd["target_2"] = p_tp2
                    if cur_score >= self.min_score and row_score != cur_score:
                        upd["score"] = cur_score
                    if d.get("trigger_type") in TRACKABLE_TRIGGERS and row.get("trigger_type") != d.get("trigger_type"):
                        upd["trigger_type"] = str(d["trigger_type"])
                        upd["trigger_label"] = str(d.get("trigger_label", d["trigger_type"]))

                    if st in ("RUNNING", "WIN", "LOSS"):
                        ep = float(row.get("entry_price") or p_high)
                        if ep < p_low or ep > p_high:
                            ep = p_high
                            upd["entry_price"] = ep
                        if st == "RUNNING" and ep > 0 and cur_close > 0:
                            new_pnl = round((cur_close - ep) / ep * 100.0, 2)
                            if float(row.get("pnl_pct") or 0) != new_pnl:
                                upd["pnl_pct"] = new_pnl
                        elif st == "WIN" and ep > 0:
                            upd["exit_price"] = p_tp
                            upd["pnl_pct"] = round((p_tp - ep) / ep * 100.0, 2)
                        elif st == "LOSS" and ep > 0:
                            upd["exit_price"] = p_sl
                            upd["pnl_pct"] = round((p_sl - ep) / ep * 100.0, 2)

                # 3. Peringatan Dini (Early Exit Warning) bila saham RUNNING mendadak didistribusi
                if st == "RUNNING" and is_dist_warning:
                    ep = float(row.get("entry_price") or row.get("entry_high") or cur_close or 1)
                    new_pnl = round((cur_close - ep) / ep * 100.0, 2) if ep > 0 and cur_close > 0 else 0.0
                    upd["pnl_pct"] = new_pnl
                    warn_note = (
                        f"⚠️ AWAS DISTRIBUSI VOLUME (Skor turun ke {cur_score}) — "
                        f"Pertimbangkan Early Exit / Ketatkan Stop Loss! (P/L {new_pnl:+.2f}%)"
                    )
                    if row.get("note") != warn_note:
                        upd["note"] = warn_note
                elif st == "WATCHLIST" and cur_score < self.min_score and not is_dist_warning:
                    pullback_note = (
                        f"Koreksi sehat volume sepi (Skor harian: {cur_score}, Baseline 5H aman) — "
                        "tetap antre di Zona Entry."
                    )
                    if row.get("note") != pullback_note:
                        upd["note"] = pullback_note

                if upd:
                    upd["updated_at"] = _now_str()
                    conn.execute(update(signals_table).where(signals_table.c.id == row["id"]).values(**upd))

            if ids_to_delete:
                conn.execute(delete(signals_table).where(signals_table.c.id.in_(ids_to_delete)))
                removed = len(ids_to_delete)

        return removed

    # ------------------------------------------------------------- evaluate
    def evaluate(self, details: dict[str, dict]) -> dict:
        """Proses candle harian (termasuk live intraday candle) untuk setiap sinyal aktif."""
        self.prune_over_bandar_signals(details)
        today_str = now_wib().strftime("%Y-%m-%d")
        changes = {"entered": 0, "win": 0, "loss": 0, "expired": 0, "timeout": 0}

        with self._lock, self.engine.begin() as conn:
            rows = conn.execute(
                select(signals_table).where(signals_table.c.status.in_(ACTIVE_STATUSES))
            ).mappings().all()

            for row in rows:
                d = details.get(row["ticker"])
                if not d:
                    continue
                hist = d.get("history") or []
                if not hist:
                    continue

                r = dict(row)
                since = r["last_eval_date"] or r["signal_date"]

                for bar in hist:
                    bar_date = str(bar["date"])
                    if bar_date <= r["signal_date"]:
                        continue

                    is_live_today = (bar_date == today_str and now_wib().time() < MARKET_CLOSE_CUTOFF)

                    # Jika bar historis yang sudah pernah dievaluasi dan bukan live today -> lewati
                    if bar_date <= since and not is_live_today:
                        continue

                    self._step(r, bar, changes, is_live_today=is_live_today)

                    # Update last_eval_date jika bar sudah final atau trade sudah ditutup
                    if not is_live_today or r["status"] not in ACTIVE_STATUSES:
                        r["last_eval_date"] = bar_date

                    if r["status"] not in ACTIVE_STATUSES:
                        break

                r["last_close"] = float(hist[-1]["close"])
                if r["status"] == "RUNNING" and r.get("entry_price"):
                    r["pnl_pct"] = round((r["last_close"] - r["entry_price"]) / r["entry_price"] * 100.0, 2)
                    # Pertahankan peringatan distribusi bila terdeteksi pada analisis terbaru
                    if "smart_money_score" in d:
                        c_score = int(d.get("smart_money_score") or 0)
                        c_trig = str(d.get("trigger_type") or "")
                        if c_score <= 35 or c_trig == "DISTRIBUTION_WARNING":
                            r["note"] = (
                                f"⚠️ AWAS DISTRIBUSI BANDAR (Skor turun ke {c_score}) — "
                                f"Pertimbangkan Early Exit / Ketatkan Stop Loss! (P/L {r['pnl_pct']:+.2f}%)"
                            )

                r["updated_at"] = _now_str()
                values = {k: v for k, v in r.items() if k != "id"}
                conn.execute(update(signals_table).where(signals_table.c.id == r["id"]).values(**values))

        return changes

    def _step(self, r: dict, bar: dict, changes: dict, is_live_today: bool = False) -> None:
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        date = str(bar["date"])

        if r["status"] == "WATCHLIST":
            e_low, e_high, sl = r["entry_low"], r["entry_high"], r["stop_loss"]

            # 1. Proteksi gap down di bawah Stop Loss pada pembukaan
            if o <= sl:
                r.update(
                    status="EXPIRED",
                    exit_date=date,
                    exit_price=round(o, 2),
                    pnl_pct=0.0,
                    note=f"Gap down @ Rp {o:,.0f} di bawah Stop Loss (Rp {sl:,.0f}) — entry dibatalkan demi keamanan modal.",
                )
                changes["expired"] += 1
                return

            # 2. Cek apakah zona entry tersentuh: Low menyentuh zona (l <= e_high) dan High >= e_low
            if l <= e_high and h >= e_low:
                if o > e_high:
                    fill = e_high
                elif o < e_low:
                    fill = e_low
                else:
                    fill = o

                r.update(
                    status="RUNNING",
                    entry_date=date,
                    entry_price=round(fill, 2),
                    bars_held=0,
                    last_close=c,
                    pnl_pct=round((c - fill) / fill * 100.0, 2),
                    note=f"Zona entry tersentuh {date} @ Rp {fill:,.0f} (Low Rp {l:,.0f}, High Rp {h:,.0f}).",
                )
                changes["entered"] += 1

                # Konservatif: Cek SL di hari yang sama
                if l <= sl:
                    self._close(r, date, sl, "LOSS", "SL tersentuh di hari yang sama dengan entry.", changes)
                    return

                # Cek TP di hari yang sama
                if h >= r["target"]:
                    self._close(r, date, r["target"], "WIN", f"Target Price (Rp {r['target']:,.0f}) tersentuh di hari yang sama dengan entry (High Rp {h:,.0f}).", changes)
                    return

                return

            if not is_live_today:
                r["bars_waited"] = int(r["bars_waited"] or 0) + 1
                if r["bars_waited"] >= self.entry_expiry_days:
                    r.update(
                        status="EXPIRED",
                        exit_date=date,
                        exit_price=round(c, 2),
                        pnl_pct=0.0,
                        note=f"Zona entry tidak tersentuh dalam {self.entry_expiry_days} hari bursa.",
                    )
                    changes["expired"] += 1
            return

        if r["status"] == "RUNNING":
            sl, tp = r["stop_loss"], r["target"]

            # 1. Stop Loss tersentuh
            if l <= sl:
                exit_p = o if o < sl else sl
                note = "Stop Loss tersentuh." if h < tp else "SL & TP tersentuh di hari yang sama — dihitung LOSS (konservatif)."
                self._close(r, date, exit_p, "LOSS", note, changes)
                return

            # 2. Target Price tersentuh
            if h >= tp:
                exit_p = o if o > tp else tp
                self._close(r, date, exit_p, "WIN", f"Target Price (Rp {tp:,.0f}) tersentuh pada High Rp {h:,.0f}.", changes)
                return

            # 3. Belum tersentuh SL maupun TP -> tetap RUNNING dengan floating P/L terupdate
            entry_p = float(r["entry_price"])
            r["last_close"] = c
            r["pnl_pct"] = round((c - entry_p) / entry_p * 100.0, 2)
            r["note"] = f"Running: Entry Rp {entry_p:,.0f}, Last Rp {c:,.0f} ({r['pnl_pct']:+.2f}%). High hari ini Rp {h:,.0f}."

            if not is_live_today:
                r["bars_held"] = int(r["bars_held"] or 0) + 1
                if r["bars_held"] >= self.max_hold_days:
                    self._close(r, date, c, "TIMEOUT", f"Melewati batas tahan {self.max_hold_days} hari — ditutup di harga close Rp {c:,.0f}.", changes)
            return

    @staticmethod
    def _close(r: dict, date: str, exit_price: float, status: str, note: str, changes: dict) -> None:
        entry = float(r["entry_price"])
        r.update(
            status=status,
            exit_date=date,
            exit_price=round(exit_price, 2),
            pnl_pct=round((exit_price - entry) / entry * 100.0, 2),
            note=note,
        )
        changes[status.lower()] = changes.get(status.lower(), 0) + 1

    # ---------------------------------------------------------------- query
    def list_signals(self, status: str | None = None, sort_by: str = "id_desc", limit: int = 500) -> list[dict]:
        q = select(signals_table)
        if status and status.upper() != "ALL":
            q = q.where(signals_table.c.status == status.upper())

        sort_by_clean = (sort_by or "id_desc").lower().strip()
        if sort_by_clean == "pnl_desc":
            q = q.order_by(signals_table.c.pnl_pct.desc().nulls_last(), signals_table.c.id.desc())
        elif sort_by_clean == "pnl_asc":
            q = q.order_by(signals_table.c.pnl_pct.asc().nulls_last(), signals_table.c.id.desc())
        elif sort_by_clean == "score_desc":
            q = q.order_by(signals_table.c.score.desc(), signals_table.c.id.desc())
        elif sort_by_clean == "score_asc":
            q = q.order_by(signals_table.c.score.asc(), signals_table.c.id.desc())
        elif sort_by_clean == "date_desc":
            q = q.order_by(signals_table.c.signal_date.desc(), signals_table.c.id.desc())
        elif sort_by_clean == "date_asc":
            q = q.order_by(signals_table.c.signal_date.asc(), signals_table.c.id.asc())
        elif sort_by_clean == "ticker_asc":
            q = q.order_by(signals_table.c.ticker.asc())
        elif sort_by_clean == "ticker_desc":
            q = q.order_by(signals_table.c.ticker.desc())
        else:
            q = q.order_by(signals_table.c.id.desc())

        q = q.limit(limit)
        with self.engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(q).mappings().all()]
        for r in rows:
            e_high = float(r.get("entry_high") or 0)
            e_low = float(r.get("entry_low") or 0)
            if e_high > 0 and (e_high - e_low) / e_high > 0.015:
                step = 1 if e_high < 200 else 2 if e_high < 500 else 5 if e_high < 2000 else 10 if e_high < 5000 else 25
                tight_low = max(50, int(round((e_high * 0.99) / step) * step))
                if tight_low >= e_high and e_high > 50:
                    tight_low = max(50, int(e_high - step))
                r["entry_low"] = float(tight_low)
            if r["status"] == "WATCHLIST" and r["entry_high"]:
                r["dist_to_entry_pct"] = round((r["last_close"] - r["entry_high"]) / r["entry_high"] * 100.0, 2)
        return rows

    def stats(self) -> dict:
        with self.engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(select(signals_table)).mappings().all()]

        def by_status(st: str) -> list[dict]:
            return [r for r in rows if r["status"] == st]

        wins, losses, timeouts = by_status("WIN"), by_status("LOSS"), by_status("TIMEOUT")
        running = by_status("RUNNING")
        win_p = [float(r["pnl_pct"] or 0) for r in wins]
        loss_p = [float(r["pnl_pct"] or 0) for r in losses]
        closed_p = win_p + loss_p + [float(r["pnl_pct"] or 0) for r in timeouts]
        decided = len(wins) + len(losses)
        gross_win, gross_loss = sum(win_p), abs(sum(loss_p))
        fee = self.fee_roundtrip_pct

        by_trigger: dict[str, dict] = {}
        for r in rows:
            t = r["trigger_type"] or "OTHER"
            b = by_trigger.setdefault(t, {"label": r["trigger_label"] or t, "total": 0, "win": 0, "loss": 0, "running": 0, "pnls": []})
            b["total"] += 1
            if r["status"] == "WIN":
                b["win"] += 1
            elif r["status"] == "LOSS":
                b["loss"] += 1
            elif r["status"] == "RUNNING":
                b["running"] += 1
            if r["status"] in ("WIN", "LOSS", "TIMEOUT"):
                b["pnls"].append(float(r["pnl_pct"] or 0))
        for b in by_trigger.values():
            dec = b["win"] + b["loss"]
            b["win_rate"] = round(b["win"] / dec * 100.0, 1) if dec else None
            b["avg_pnl"] = round(mean(b["pnls"]), 2) if b["pnls"] else None
            del b["pnls"]

        return {
            "total": len(rows),
            "watchlist": len(by_status("WATCHLIST")),
            "running": len(running),
            "win": len(wins),
            "loss": len(losses),
            "expired": len(by_status("EXPIRED")),
            "timeout": len(timeouts),
            "decided": decided,
            "win_rate": round(len(wins) / decided * 100.0, 1) if decided else None,
            "avg_win_pct": round(mean(win_p), 2) if win_p else None,
            "avg_loss_pct": round(mean(loss_p), 2) if loss_p else None,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
            "expectancy_pct": round(mean(closed_p), 2) if closed_p else None,
            "expectancy_net_pct": round(mean(closed_p) - fee, 2) if closed_p else None,
            "total_return_pct": round(sum(closed_p), 2),
            "total_return_net_pct": round(sum(p - fee for p in closed_p), 2),
            "running_avg_pnl_pct": round(mean([float(r["pnl_pct"] or 0) for r in running]), 2) if running else None,
            "by_trigger": by_trigger,
        }

    def delete_signal(self, signal_id: int) -> bool:
        with self._lock, self.engine.begin() as conn:
            res = conn.execute(delete(signals_table).where(signals_table.c.id == signal_id))
            return res.rowcount > 0

    def reset_all(self) -> int:
        with self._lock, self.engine.begin() as conn:
            return conn.execute(delete(signals_table)).rowcount
