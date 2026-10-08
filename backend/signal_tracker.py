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

        e_low, e_high = sorted([float(plan["entry_low"]), float(plan["entry_high"])])
        sl = float(plan["stop_loss"])
        target = float(plan["target_2"] if self.tp_level == 2 else plan["target_1"])
        if not (sl < e_low and target > e_high):
            return False, f"{ticker}: trading plan tidak valid (SL harus di bawah entry & TP di atas entry)."

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
                    score=int(stock.get("smart_money_score", 0)),
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
        """Catat otomatis sinyal akumulasi (score >= min_score) dari sesi bursa yang sudah final."""
        final_date = last_final_session_date()
        market_date = analysis.get("kpis", {}).get("latest_date")
        added = 0
        for s in analysis.get("stocks", []):
            if s.get("trigger_type") not in TRACKABLE_TRIGGERS:
                continue
            if int(s.get("smart_money_score", 0)) < self.min_score:
                continue
            # Abaikan saham yang tidak aktif hari itu & candle hari ini yang belum final
            if s.get("date") != market_date or str(s.get("date")) > final_date:
                continue
            ok, _ = self.add_signal(s, source="AUTO")
            if ok:
                added += 1
        return added

    # ------------------------------------------------------------- evaluate
    def evaluate(self, details: dict[str, dict]) -> dict:
        """Proses candle harian baru (yang sudah final) untuk setiap sinyal aktif."""
        final_date = last_final_session_date()
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
                r = dict(row)
                since = r["last_eval_date"] or r["signal_date"]
                new_bars = [b for b in hist if since < str(b["date"]) <= final_date]

                for bar in new_bars:
                    self._step(r, bar, changes)
                    r["last_eval_date"] = str(bar["date"])
                    if r["status"] not in ACTIVE_STATUSES:
                        break

                if hist:
                    r["last_close"] = float(hist[-1]["close"])
                if r["status"] == "RUNNING" and r["entry_price"]:
                    r["pnl_pct"] = round((r["last_close"] - r["entry_price"]) / r["entry_price"] * 100.0, 2)
                r["updated_at"] = _now_str()
                values = {k: v for k, v in r.items() if k != "id"}
                conn.execute(update(signals_table).where(signals_table.c.id == r["id"]).values(**values))
        return changes

    def _step(self, r: dict, bar: dict, changes: dict) -> None:
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        date = str(bar["date"])

        if r["status"] == "WATCHLIST":
            r["bars_waited"] = int(r["bars_waited"] or 0) + 1
            e_low, e_high, sl = r["entry_low"], r["entry_high"], r["stop_loss"]

            if o <= sl:
                r.update(status="EXPIRED", exit_date=date, note="Gap down di bawah Stop Loss — entry dibatalkan.")
                changes["expired"] += 1
                return

            if l <= e_high and h >= e_low:  # zona entry tersentuh
                fill = e_high if o > e_high else o
                r.update(status="RUNNING", entry_date=date, entry_price=round(fill, 2), bars_held=0,
                         note=f"Zona entry tersentuh {date} @ Rp {fill:,.0f}.")
                changes["entered"] += 1
                if l <= sl:  # konservatif: SL di hari entry tetap dihitung
                    self._close(r, date, sl, "LOSS", "SL tersentuh di hari yang sama dengan entry.", changes)
                return

            if r["bars_waited"] >= self.entry_expiry_days:
                r.update(status="EXPIRED", exit_date=date,
                         note=f"Zona entry tidak tersentuh dalam {self.entry_expiry_days} hari bursa.")
                changes["expired"] += 1
            return

        if r["status"] == "RUNNING":
            r["bars_held"] = int(r["bars_held"] or 0) + 1
            sl, tp = r["stop_loss"], r["target"]
            if l <= sl:  # jika SL & TP sama-sama tersentuh -> dianggap LOSS (konservatif)
                exit_p = o if o < sl else sl
                note = "Stop Loss tersentuh." if h < tp else "SL & TP tersentuh di hari yang sama — dihitung LOSS (konservatif)."
                self._close(r, date, exit_p, "LOSS", note, changes)
            elif h >= tp:
                exit_p = o if o > tp else tp
                self._close(r, date, exit_p, "WIN", "Target Price tersentuh.", changes)
            elif r["bars_held"] >= self.max_hold_days:
                self._close(r, date, c, "TIMEOUT", f"Melewati batas {self.max_hold_days} hari — ditutup di harga close.", changes)

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
    def list_signals(self, status: str | None = None, limit: int = 500) -> list[dict]:
        q = select(signals_table).order_by(signals_table.c.id.desc()).limit(limit)
        if status and status.upper() != "ALL":
            q = q.where(signals_table.c.status == status.upper())
        with self.engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(q).mappings().all()]
        for r in rows:
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
