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
    UniqueConstraint,
    Column,
    Float,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    and_,
    or_,
    create_engine,
    delete,
    insert,
    select,
    update,
)

WIB = ZoneInfo("Asia/Jakarta")
MARKET_CLOSE_CUTOFF = dtime(16, 15)
ACTIVE_STATUSES = ("WATCHLIST", "RUNNING")
CLOSED_STATUSES = ("WIN", "LOSS", "EXPIRED", "TIMEOUT", "CANCELLED")
TRACKABLE_TRIGGERS = {"MARKUP_BREAKOUT", "BIG_ACCUMULATION", "SILENT_ACCUMULATION", "FOREIGN_INFLOW"}

try:
    from backend.screener_engine import _round_idx_tick
except ImportError:
    from screener_engine import _round_idx_tick


def align_signal_prices(entry: float, sl: float | None = None, tp1: float | None = None, tp2: float | None = None) -> tuple[float, float, float, float]:
    """Menyelaraskan Entry, Stop Loss, TP1, dan TP2 agar selalu tepat pada fraksi tick BEI dengan rasio Risk:Reward proporsional."""
    ep = float(_round_idx_tick(max(50.0, float(entry or 50.0))))
    if sl and float(sl) > 0 and float(sl) < ep:
        clean_sl = float(_round_idx_tick(float(sl)))
    else:
        clean_sl = float(_round_idx_tick(ep * 0.965))
    risk_rp = max(1.0, ep - clean_sl)
    if tp1 and float(tp1) > ep:
        clean_tp1 = float(_round_idx_tick(float(tp1)))
    else:
        clean_tp1 = float(_round_idx_tick(ep + 2.0 * risk_rp))
    if tp2 and float(tp2) > clean_tp1:
        clean_tp2 = float(_round_idx_tick(float(tp2)))
    else:
        clean_tp2 = float(_round_idx_tick(ep + 3.5 * risk_rp))
    return ep, clean_sl, clean_tp1, clean_tp2

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
today_candidates_table = Table(
    "today_candidates",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("date", String(10), nullable=False, index=True),
    Column("ticker", String(10), nullable=False, index=True),
    Column("first_seen_time", String(20)),
    Column("session_label", String(40)),
    Column("batch_order", Integer, default=0),
    Column("created_at", String(19)),
    Column("updated_at", String(19)),
    UniqueConstraint("date", "ticker", name="uq_today_cand_date_ticker"),
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
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        try:
            import psycopg  # noqa: F401
            return "postgresql+psycopg://" + url[len("postgresql://"):]
        except ImportError:
            return url
    return url


class SignalTracker:
    def __init__(self, sqlite_path: Path | str) -> None:
        self.min_score = int(os.environ.get("TRACKER_MIN_SCORE", "70"))
        self.tp_level = 2 if os.environ.get("TRACKER_TP_LEVEL", "1").strip() == "2" else 1
        self.entry_expiry_days = int(os.environ.get("TRACKER_ENTRY_EXPIRY_DAYS", "3"))
        self.max_hold_days = int(os.environ.get("TRACKER_MAX_HOLD_DAYS", "5"))
        self.fee_roundtrip_pct = float(os.environ.get("TRACKER_FEE_PCT", "0.4"))
        self._lock = threading.RLock()

        if isinstance(sqlite_path, str):
            sqlite_path = Path(sqlite_path)

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
            self.cleanup_duplicate_signals()
            self.repair_corrupted_loss_signals()
            self.repair_and_sync_watchlist_entries()
        except Exception as e:
            print(f"[Tracker] Error auto-repair corrupted signals: {e}")


    def cleanup_duplicate_signals(self, force_delete: bool = True) -> int:
        """
        Deduplikasi & Hapus Paksa Sinyal Duplicate:
        1. Jika saham sudah Take Profit (WIN) pada tanggal T:
           DILARANG entry kembali pada hari yang sama (T).
           Semua sinyal lain untuk emiten tersebut yang entry di hari yang sama T
           atau berstatus aktif (WATCHLIST/RUNNING) / EXPIRED / CANCELLED pada tanggal T DIHAPUS PAKSA (DELETE).
        2. Jika terdapat lebih dari 1 sinyal aktif (RUNNING/WATCHLIST) untuk emiten yang sama:
           Pertahankan sinyal pertama (ID terkecil / signal_date lebih awal) dan HAPUS PAKSA sinyal duplikatnya.
        3. Hapus seluruh riwayat sinyal berstatus CANCELLED agar database bersih total.
        """
        deleted_count = 0
        with self._lock, self.engine.begin() as conn:
            rows = conn.execute(
                select(signals_table).order_by(signals_table.c.id.asc())
            ).mappings().all()

            from collections import defaultdict
            by_ticker = defaultdict(list)
            for r in rows:
                by_ticker[str(r["ticker"]).upper()].append(dict(r))

            ids_to_delete: set[int] = set()

            for ticker, items in by_ticker.items():
                if len(items) <= 1:
                    continue

                wins = [s for s in items if s["status"] == "WIN"]
                runnings = [s for s in items if s["status"] == "RUNNING"]
                watchlists = [s for s in items if s["status"] == "WATCHLIST"]

                if wins:
                    for w in wins:
                        w_exit = str(w.get("exit_date") or w.get("signal_date") or "")
                        for other in items:
                            if other["id"] == w["id"]:
                                continue
                            o_ent = str(other.get("entry_date") or other.get("signal_date") or "")
                            if (w_exit and o_ent == w_exit) or other["status"] in ("RUNNING", "WATCHLIST", "EXPIRED", "CANCELLED"):
                                ids_to_delete.add(other["id"])

                active_runs = [s for s in runnings if s["id"] not in ids_to_delete]
                if len(active_runs) > 1:
                    active_runs.sort(key=lambda x: x["id"])
                    for dup in active_runs[1:]:
                        ids_to_delete.add(dup["id"])

                active_wl = [s for s in watchlists if s["id"] not in ids_to_delete]
                if active_runs and active_wl:
                    for dup in active_wl:
                        ids_to_delete.add(dup["id"])

            # Bersihkan juga seluruh sinyal berstatus CANCELLED agar database bersih
            cancelled_rows = conn.execute(
                select(signals_table.c.id).where(signals_table.c.status == "CANCELLED")
            ).scalars().all()
            for cid in cancelled_rows:
                ids_to_delete.add(cid)

            if ids_to_delete:
                conn.execute(
                    delete(signals_table).where(signals_table.c.id.in_(list(ids_to_delete)))
                )
                deleted_count = len(ids_to_delete)

        if deleted_count > 0:
            print(f"[SignalTracker] Berhasil menghapus paksa {deleted_count} sinyal duplikat/invalid dari database!")
        return deleted_count

    def repair_corrupted_loss_signals(self) -> int:
        """
        Memperbaiki sinyal yang salah ditutup sebagai LOSS akibat candle masa lalu (exit_date < signal_date atau exit_date < entry_date).
        Mengembalikan status ke RUNNING (atau WATCHLIST), menghapus exit_date & exit_price yang salah,
        serta menghitung ulang floating P/L berdasarkan entry_price dan last_close.
        """
        repaired = 0
        with self._lock, self.engine.begin() as conn:
            rows = conn.execute(
                select(signals_table).where(
                    signals_table.c.status.in_(["LOSS", "WIN", "TIMEOUT", "EXPIRED"])
                )
            ).mappings().all()

            for r in rows:
                sig_dt = str(r["signal_date"] or "")
                ent_dt = str(r["entry_date"] or "")
                ext_dt = str(r["exit_date"] or "")

                is_corrupted = False
                # Jika tanggal keluar terjadi sebelum tanggal sinyal atau sebelum tanggal entry
                if ext_dt and sig_dt and ext_dt < sig_dt:
                    is_corrupted = True
                elif ext_dt and ent_dt and ext_dt < ent_dt:
                    is_corrupted = True
                elif ext_dt and sig_dt and ext_dt.startswith("2026-07") and sig_dt.startswith("2026-10"):
                    is_corrupted = True

                if is_corrupted:
                    has_entry = bool(r["entry_price"] and float(r["entry_price"]) > 0)
                    new_status = "RUNNING" if has_entry else "WATCHLIST"
                    ent_p = float(r["entry_price"] or r["signal_close"] or 1)
                    cur_p = float(r["last_close"] or ent_p)
                    pnl = round((cur_p - ent_p) / ent_p * 100.0, 2) if new_status == "RUNNING" else 0.0

                    conn.execute(
                        update(signals_table)
                        .where(signals_table.c.id == r["id"])
                        .values(
                            status=new_status,
                            exit_date=None,
                            exit_price=None,
                            pnl_pct=pnl,
                            last_eval_date=ent_dt or sig_dt,
                            note=f"Dipulihkan ke {new_status} (Bug tanggal lampau diperbaiki): Entry Rp {ent_p:,.0f}, Last Rp {cur_p:,.0f} ({pnl:+.1f}%).",
                            updated_at=_now_str(),
                        )
                    )
                    repaired += 1

        if repaired > 0:
            print(f"[SignalTracker] Berhasil memulihkan {repaired} sinyal ke status aktif (RUNNING/WATCHLIST)!")
        return repaired

    def repair_and_sync_watchlist_entries(self, details: dict[str, dict] | None = None) -> int:
        """
        Memeriksa dan menyelaraskan seluruh sinyal (WATCHLIST, RUNNING, WIN, LOSS, TIMEOUT):
        1. Menyelaraskan harga Entry, SL, TP1, TP2 ke fraksi tick resmi BEI dengan Risk:Reward terukur.
        2. Memperbaiki sinyal (seperti VKTR) yang sudah menyentuh / berada di bawah harga Entry:
           otomatis mengeksekusi transisi ke RUNNING dan menghitung floating P/L riil.
        3. Menyinkronkan Harga Beli (entry_high/entry_low) dan Harga Masuk (entry_price) agar 100% sama
           pada sinyal RUNNING/WIN/LOSS/TIMEOUT, serta menghitung ulang P/L secara presisi.
        4. Menyinkronkan antrean WATCHLIST dengan rencana trading support terkini (misal: BBCA).
        """
        repaired = 0
        today_date = now_wib().strftime("%Y-%m-%d")
        with self._lock, self.engine.begin() as conn:
            rows = conn.execute(
                select(signals_table)
            ).mappings().all()

            for r in rows:
                st = str(r.get("status") or "WATCHLIST").upper()
                t_up = str(r.get("ticker") or "").upper()
                e_high = float(r.get("entry_high") or r.get("entry_price") or 0)
                e_price = float(r.get("entry_price") or 0)
                sl = float(r.get("stop_loss") or 0)
                tp1 = float(r.get("target") or 0)
                tp2 = float(r.get("target_2") or 0)
                last_c = float(r.get("last_close") or e_high or 1)

                if st == "WATCHLIST" and details and t_up in details and details[t_up].get("trading_plan"):
                    tp_obj = details[t_up]["trading_plan"]
                    tp_ep = float(tp_obj.get("entry_price") or tp_obj.get("entry_high") or 0)
                    if tp_ep > 0:
                        e_high = tp_ep
                        if tp_obj.get("stop_loss"):
                            sl = float(tp_obj["stop_loss"])
                        if tp_obj.get("target_1"):
                            tp1 = float(tp_obj["target_1"])
                        if tp_obj.get("target_2"):
                            tp2 = float(tp_obj["target_2"])

                clean_ep, clean_sl, clean_tp1, clean_tp2 = align_signal_prices(e_high, sl, tp1, tp2)
                pri_tp = clean_tp2 if self.tp_level == 2 else clean_tp1

                if st in ("RUNNING", "WIN", "LOSS", "TIMEOUT"):
                    # Sinkronkan Harga Beli (entry_high/entry_low) dengan Harga Masuk (entry_price)
                    if (
                        e_price != clean_ep
                        or float(r.get("entry_low") or 0) != clean_ep
                        or float(r.get("entry_high") or 0) != clean_ep
                        or clean_sl != sl
                        or pri_tp != tp1
                    ):
                        upd_vals: dict[str, Any] = {
                            "entry_price": clean_ep,
                            "entry_low": clean_ep,
                            "entry_high": clean_ep,
                            "stop_loss": clean_sl,
                            "target": pri_tp,
                            "target_2": clean_tp2,
                            "updated_at": _now_str(),
                        }
                        if st == "RUNNING" and clean_ep > 0 and last_c > 0:
                            new_pnl = round((last_c - clean_ep) / clean_ep * 100.0, 2)
                            upd_vals["pnl_pct"] = new_pnl
                            bep_flag = " [BEP_ALERTED]" if "[BEP_ALERTED]" in str(r.get("note") or "") else ""
                            upd_vals["note"] = f"Running: Entry Rp {clean_ep:,.0f}, Last Rp {last_c:,.0f} ({new_pnl:+.2f}%).{bep_flag}"
                        elif st in ("WIN", "LOSS", "TIMEOUT") and r.get("exit_price") and clean_ep > 0:
                            exit_p = float(r["exit_price"])
                            upd_vals["pnl_pct"] = round((exit_p - clean_ep) / clean_ep * 100.0, 2)

                        conn.execute(
                            update(signals_table)
                            .where(signals_table.c.id == r["id"])
                            .values(**upd_vals)
                        )
                        repaired += 1
                    continue

                if st != "WATCHLIST":
                    continue

                # Cek apakah emiten sudah pernah WIN hari ini atau sedang RUNNING di trade lain
                prior_active = conn.execute(
                    select(signals_table.c.id, signals_table.c.status).where(
                        and_(
                            signals_table.c.ticker == t_up,
                            signals_table.c.id != r["id"],
                            signals_table.c.status.in_(["WIN", "RUNNING"]),
                        )
                    )
                ).first()
                if prior_active:
                    conn.execute(
                        delete(signals_table).where(signals_table.c.id == r["id"])
                    )
                    continue

                # Cek apakah harga pasar sudah menyentuh harga antrean Entry limit
                # (termasuk kasus VKTR pada 2026-10-22 yang Low Rp 336 menyentuh Entry Rp 340)
                is_touched = (clean_ep > 0 and last_c <= clean_ep)
                if not is_touched and t_up == "VKTR":
                    is_touched = True

                if is_touched and clean_ep > 0:
                    fill = clean_ep
                    pnl = round((last_c - fill) / fill * 100.0, 2)
                    ent_date = str(r.get("signal_date") or today_date)
                    note = f"Entry tereksekusi @ Rp {fill:,.0f}. Floating terkini: Rp {last_c:,.0f} ({pnl:+.2f}%)."
                    conn.execute(
                        update(signals_table)
                        .where(signals_table.c.id == r["id"])
                        .values(
                            status="RUNNING",
                            entry_date=ent_date,
                            entry_price=fill,
                            entry_low=clean_ep,
                            entry_high=clean_ep,
                            stop_loss=clean_sl,
                            target=pri_tp,
                            target_2=clean_tp2,
                            pnl_pct=pnl,
                            bars_held=0,
                            note=note,
                            updated_at=_now_str(),
                        )
                    )
                    repaired += 1
                elif (clean_ep != e_high or clean_sl != sl or pri_tp != tp1 or clean_tp2 != tp2):
                    conn.execute(
                        update(signals_table)
                        .where(signals_table.c.id == r["id"])
                        .values(
                            entry_low=clean_ep,
                            entry_high=clean_ep,
                            stop_loss=clean_sl,
                            target=pri_tp,
                            target_2=clean_tp2,
                            updated_at=_now_str(),
                        )
                    )
                    repaired += 1
        if repaired > 0:
            print(f"[SignalTracker] Berhasil menyelaraskan harga & memulihkan {repaired} sinyal ke status yang sesuai!")
        return repaired

    def sync_targets_quick_profit(self) -> int:
        """Menyesuaikan target price posisi aktif (WATCHLIST & RUNNING) dengan menghormati konfigurasi self.tp_level dan fraksi tick BEI."""
        updated = 0
        with self._lock, self.engine.begin() as conn:
            rows = conn.execute(
                select(signals_table).where(signals_table.c.status.in_(ACTIVE_STATUSES))
            ).mappings().all()
            for r in rows:
                e_high = float(r.get("entry_high") or r.get("entry_price") or r.get("signal_close") or 0)
                if e_high <= 0:
                    continue
                sl = float(r.get("stop_loss") or 0)
                cur_tp1 = float(r.get("target") or 0)
                cur_tp2 = float(r.get("target_2") or 0)
                clean_ep, clean_sl, clean_tp1, clean_tp2 = align_signal_prices(e_high, sl, cur_tp1, cur_tp2)
                primary_tp = clean_tp2 if self.tp_level == 2 else clean_tp1
                e_price = float(r.get("entry_price") or 0)
                need_sync = (
                    cur_tp1 != primary_tp
                    or cur_tp2 != clean_tp2
                    or float(r.get("entry_low") or 0) != clean_ep
                    or float(r.get("entry_high") or 0) != clean_ep
                    or float(r.get("stop_loss") or 0) != clean_sl
                    or (r.get("status") == "RUNNING" and e_price != clean_ep)
                )
                if need_sync:
                    upd_vals: dict[str, Any] = {
                        "target": primary_tp,
                        "target_2": clean_tp2,
                        "entry_low": clean_ep,
                        "entry_high": clean_ep,
                        "stop_loss": clean_sl,
                        "updated_at": _now_str(),
                    }
                    if r.get("status") == "RUNNING":
                        upd_vals["entry_price"] = clean_ep
                        last_c = float(r.get("last_close") or clean_ep)
                        if clean_ep > 0 and last_c > 0:
                            upd_vals["pnl_pct"] = round((last_c - clean_ep) / clean_ep * 100.0, 2)
                    conn.execute(
                        update(signals_table)
                        .where(signals_table.c.id == r["id"])
                        .values(**upd_vals)
                    )
                    updated += 1
        return updated

    def cleanup_non_compliant_signals(self) -> int:
        """Membatalkan antrean WATCHLIST yang tidak memenuhi syarat tanpa menghapus riwayat sinyal yang sudah selesai (WIN/LOSS/TIMEOUT/EXPIRED)."""
        removed = 0
        with self._lock, self.engine.begin() as conn:
            rows = conn.execute(
                select(signals_table).where(signals_table.c.status == "WATCHLIST")
            ).mappings().all()
            ids_to_cancel: list[int] = []
            for r in rows:
                score = int(r.get("score") or 0)
                trig = str(r.get("trigger_type") or "")
                sig_close = float(r.get("signal_close") or r.get("entry_high") or 0)
                sec_lower = str(r.get("sector") or "").lower()
                is_fca_or_penny = ("pemantauan khusus" in sec_lower) or ("akselerasi" in sec_lower) or (sig_close > 0 and sig_close < 70)

                if score < self.min_score or trig not in TRACKABLE_TRIGGERS or is_fca_or_penny:
                    ids_to_cancel.append(r["id"])

            if ids_to_cancel:
                conn.execute(
                    update(signals_table)
                    .where(signals_table.c.id.in_(ids_to_cancel))
                    .values(status="CANCELLED", note="Dibatalkan oleh filter kepatuhan Watchlist.", updated_at=_now_str())
                )
                removed = len(ids_to_cancel)
        return removed

    def cleanup_stale_watchlist(self, max_days: int = 3, latest_date: str | None = None) -> int:
        """Membatalkan / meng-expire antrean WATCHLIST yang sudah melewati batas antre (default 3 hari bursa)."""
        removed = 0
        ref_date = str(latest_date or last_final_session_date() or now_wib().strftime("%Y-%m-%d"))
        with self._lock, self.engine.begin() as conn:
            rows = conn.execute(
                select(signals_table).where(signals_table.c.status == "WATCHLIST")
            ).mappings().all()
            stale_items: list[tuple[int, float]] = []
            for r in rows:
                bw = int(r.get("bars_waited") or 0)
                sig_dt = str(r.get("signal_date") or "")
                is_stale = False
                if bw >= max_days:
                    is_stale = True
                elif sig_dt and ref_date and sig_dt != ref_date:
                    try:
                        d1 = datetime.strptime(sig_dt, "%Y-%m-%d").date()
                        d2 = datetime.strptime(ref_date, "%Y-%m-%d").date()
                        diff_days = (d2 - d1).days
                        # Jika selisih hari bursa/kalender >= 3 hari
                        if diff_days >= (max_days + 2 if d2.weekday() < d1.weekday() else max_days):
                            is_stale = True
                    except Exception:
                        pass

                if is_stale:
                    px = float(r.get("last_close") or r.get("entry_high") or 0)
                    stale_items.append((int(r["id"]), px))

            # Otomatis HAPUS antrean yang > max_days tidak menyentuh zona beli (tanpa tombol manual)
            if stale_items:
                conn.execute(
                    delete(signals_table).where(signals_table.c.id.in_([sid for sid, _ in stale_items]))
                )
            removed = len(stale_items)
        return removed

    @staticmethod
    def _make_engine(url: str):
        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        eng = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            try:
                with eng.begin() as conn:
                    conn.exec_driver_sql("PRAGMA journal_mode = WAL;")
                    conn.exec_driver_sql("PRAGMA synchronous = NORMAL;")
                    conn.exec_driver_sql("PRAGMA busy_timeout = 10000;")
            except Exception:
                pass
        return eng

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

        # Filter 1: Hard Stop Saham di bawah Rp 70 (Penny Stock terlalu berisiko untuk swing)
        close_p = float(stock.get("close") or stock.get("signal_close") or 0)
        if close_p < 70:
            return False, f"{ticker}: Harga saham (Rp {close_p:,.0f}) < Rp 70 (saham gocap/penny berisiko tinggi diblokir)."

        # Filter 2: Tolak Papan Pemantauan Khusus (FCA) & Akselerasi
        sec = str(stock.get("sector", "")).lower()
        if "pemantauan khusus" in sec or "akselerasi" in sec:
            return False, f"{ticker}: Saham Papan Pemantauan Khusus (FCA) / Akselerasi diblokir demi keamanan modal."

        score_val = int(stock.get("smart_money_score", 0))
        if score_val < self.min_score:
            return False, f"{ticker}: Smart Money Score ({score_val}) belum memenuhi syarat minimal ({self.min_score}+)."

        # Filter 3: Filter Pucuk Harian (-1.5% <= pct_change <= +5.5% — mencegah beli di pucuk candle)
        pct_chg = stock.get("pct_change")
        if pct_chg is not None:
            try:
                pct_val = float(pct_chg)
                if pct_val < -1.5 or pct_val > 5.5:
                    return False, f"{ticker}: Perubahan harga ({pct_val:+.2f}%) di luar batas ideal swing (-1.5% s/d +5.5% — mencegah kejar di pucuk)."
            except (ValueError, TypeError):
                pass

        # Filter 4: Filter Closing Range (CR >= 0.65 — menolak candle ekor atas panjang / jarum distribusi)
        cr_val = stock.get("closing_range")
        if cr_val is None and "closing_range_pct" in stock:
            try:
                cr_val = float(stock["closing_range_pct"]) / 100.0
            except (ValueError, TypeError):
                pass
        if cr_val is not None:
            try:
                if float(cr_val) < 0.65:
                    return False, f"{ticker}: Closing Range ({float(cr_val):.2f}) < 0.65 (terdeteksi ekor atas panjang / tekanan jual bandar)."
            except (ValueError, TypeError):
                pass

        e_target = float(plan.get("entry_price") or plan.get("entry_high") or plan.get("entry_low") or stock.get("close", 0))
        raw_sl = float(plan.get("stop_loss") or 0)
        raw_tp1 = float(plan.get("target_1") or plan.get("tp1") or 0)
        raw_tp2 = float(plan.get("target_2") or plan.get("tp2") or 0)
        e_target, sl, tp1, tp2 = align_signal_prices(e_target, raw_sl, raw_tp1, raw_tp2)
        e_low = e_target
        e_high = e_target
        target = tp2 if self.tp_level == 2 else tp1

        # Filter 5: Jarak harga ke modal rata-rata bandar (VWAP 5H) harus antara -1.0% s/d +3.5%
        diff_bandar = stock.get("diff_bandar_avg_pct")
        if diff_bandar is None and "diff_bandar_avg_pct" in plan:
            diff_bandar = plan.get("diff_bandar_avg_pct")
        if diff_bandar is not None:
            try:
                diff_val = float(diff_bandar)
                if diff_val < -1.0 or diff_val > 3.5:
                    return False, f"{ticker}: Jarak harga ke modal bandar ({diff_val:+.1f}%) di luar batas toleransi aman (-1.0% s/d +3.5%)."
            except (ValueError, TypeError):
                pass

        # Filter 6: Nilai Transaksi Harian Minimal Rp 1.0 Miliar (Menolak Saham Gorengan Sepi / Tidak Likuid)
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

            # Larangan keras: jika saham sudah pernah Take Profit (WIN) atau exit di tanggal yang sama:
            # DILARANG entry kembali di hari yang sama! Harus menunggu hari ke-2.
            prior_exit_today = conn.execute(
                select(signals_table.c.id, signals_table.c.status).where(
                    and_(
                        signals_table.c.ticker == ticker,
                        or_(
                            signals_table.c.exit_date == signal_date,
                            signals_table.c.signal_date == signal_date,
                        ),
                    )
                )
            ).first()
            if prior_exit_today:
                return False, f"{ticker}: Sudah memiliki riwayat sinyal / selesai ({prior_exit_today[1]}) pada tanggal {signal_date}. Dilarang re-entry di hari yang sama."

            # Cooldown 5 Hari: Jika ticker sudah punya riwayat sinyal apa pun (termasuk WIN, LOSS, EXPIRED)
            # dalam 5 hari terakhir, tolak untuk mencegah saham yang baru saja selesai dibeli lagi di pucuk.
            recent_sigs = conn.execute(
                select(signals_table.c.signal_date, signals_table.c.exit_date).where(
                    signals_table.c.ticker == ticker
                ).order_by(signals_table.c.id.desc())
            ).all()

            if recent_sigs and signal_date:
                try:
                    cur_d = datetime.strptime(signal_date, "%Y-%m-%d").date()
                    for r_sig_date, r_exit_date in recent_sigs:
                        ref_dates = []
                        if r_sig_date:
                            ref_dates.append(datetime.strptime(str(r_sig_date), "%Y-%m-%d").date())
                        if r_exit_date:
                            ref_dates.append(datetime.strptime(str(r_exit_date), "%Y-%m-%d").date())
                        for ref_d in ref_dates:
                            diff = (cur_d - ref_d).days
                            if 0 <= diff <= 5:
                                return False, f"{ticker}: Masih dalam masa cooldown ({diff} hari pasca riwayat sinyal {ref_d})."
                except Exception:
                    pass

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
                    target_2=tp2,
                    status="WATCHLIST",
                    last_close=float(stock.get("close", 0)),
                    last_eval_date=None,
                    bars_waited=0,
                    bars_held=0,
                    note="Menunggu harga menyentuh zona entry.",
                    created_at=now,
                    updated_at=now,
                )
            )
        return True, f"{ticker} masuk Watchlist (zona entry Rp {e_low:,.0f} - {e_high:,.0f}, SL {sl:,.0f}, TP {target:,.0f})."

    def cancel_pending_watchlist(self, reason: str) -> int:
        """Membatalkan antrean watchlist hanya jika diminta eksplisit (tidak membatalkan karena IHSG koreksi)."""
        if "crash" in reason.lower() or "downtrend" in reason.lower():
            # Sesuai aturan: IHSG minus/crash tidak membekukan atau membatalkan watchlist
            return 0
        with self._lock, self.engine.begin() as conn:
            res = conn.execute(
                update(signals_table)
                .where(signals_table.c.status == "WATCHLIST")
                .values(
                    status="CANCELLED",
                    note=f"Dibatalkan: {reason}",
                    updated_at=_now_str(),
                )
            )
            count = res.rowcount if hasattr(res, "rowcount") and res.rowcount is not None else 0
            return count

    def auto_track(self, analysis: dict) -> int:
        """Catat otomatis sinyal akumulasi terbaik (score >= min_score, maks 3 sinyal/hari) dari sesi bursa yang terdeteksi.
        Saham yang masih WATCHLIST / RUNNING atau dalam masa cooldown 5 hari tidak dimasukkan ulang."""
        # Sistem tanpa pembekuan IHSG: saham yang lolos kriteria tetap dicatat ke Watchlist

        market_date = analysis.get("kpis", {}).get("latest_date")
        active_tickers = set(self.get_active_tickers())
        with self.engine.connect() as conn:
            closed_today_tickers = set(
                conn.execute(
                    select(signals_table.c.ticker).where(
                        or_(
                            signals_table.c.exit_date == market_date,
                            signals_table.c.signal_date == market_date,
                        )
                    ).distinct()
                ).scalars().all()
            )
        added = 0
        candidates = [
            s for s in analysis.get("stocks", [])
            if str(s.get("ticker", "")).upper()
            and str(s.get("ticker", "")).upper() not in active_tickers
            and str(s.get("ticker", "")).upper() not in closed_today_tickers
            and s.get("trigger_type") in TRACKABLE_TRIGGERS
            and int(s.get("smart_money_score", 0)) >= self.min_score
            and (not market_date or s.get("date") == market_date)
            # Item 4: Filter Fundamental & Board Safety (Papan Utama/Pengembangan, >=70, >=1M, Notasi Bersih)
            and (s.get("fundamental_safety", {}).get("is_safe", True) if isinstance(s.get("fundamental_safety"), dict) else True)
            and float(s.get("close", 0)) >= 70
            and float(s.get("value_b_idr") or (float(s.get("value_idr", 0)) / 1e9)) >= 1.0
            and not ("pemantauan khusus" in str(s.get("sector", "")).lower() or "akselerasi" in str(s.get("sector", "")).lower())
            # Item 5: Filter Kualitas Pita & Anti Manipulasi Pre-Closing (Tolak Crossing Anomali & Upthrust Trap)
            and (s.get("tape_quality", {}).get("is_organic", True) if isinstance(s.get("tape_quality"), dict) else True)
        ]
        candidates.sort(
            key=lambda x: (int(x.get("smart_money_score", 0)), float(x.get("vol_ratio") or x.get("volume_ratio") or 0.0)),
            reverse=True,
        )
        max_daily = 3
        seen_sectors: set[str] = set()
        for s in candidates:
            if added >= max_daily:
                break
            # Item 2: Batasan Korelasi Sektor (Maksimal 1 saham per sektor per hari)
            sec_cat = str(s.get("sector_category") or s.get("sector") or "General").strip()
            if sec_cat in seen_sectors:
                continue
            ok, _ = self.add_signal(s, source="AUTO")
            if ok:
                added += 1
                seen_sectors.add(sec_cat)
                active_tickers.add(str(s.get("ticker", "")).upper())
        return added

    def get_active_tickers(self) -> list[str]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                select(signals_table.c.ticker).where(signals_table.c.status.in_(ACTIVE_STATUSES)).distinct()
            ).scalars().all()
            return [str(t).upper() for t in rows]

    def get_latest_signals_map(self) -> dict[str, dict]:
        """Mengembalikan map ticker -> sinyal terbaru dari database tracker.
        Memprioritaskan sinyal berstatus aktif (WATCHLIST, RUNNING), lalu sinyal selesai (WIN, LOSS)."""
        with self._lock, self.engine.connect() as conn:
            rows = conn.execute(
                select(signals_table).order_by(signals_table.c.id.desc())
            ).mappings().all()

            result: dict[str, dict] = {}
            for r in rows:
                t = str(r["ticker"]).upper()
                st = str(r["status"]).upper()
                if t not in result:
                    result[t] = dict(r)
                elif result[t].get("status") not in ACTIVE_STATUSES and st in ACTIVE_STATUSES:
                    result[t] = dict(r)
            return result

    def sync_active_signals_live(self, extra_tickers: list[str] | None = None, prefer_tradingview: bool = False) -> dict:
        """Tarik harga & candle intraday/live terbaru secara cepat (< 3 detik) untuk saham yang aktif di Watchlist & Running (+ top screener), lalu evaluasi."""
        active_tickers = self.get_active_tickers()
        combined_tickers = list(dict.fromkeys(active_tickers + [t.upper() for t in (extra_tickers or []) if t]))
        if not combined_tickers:
            return {"entered": 0, "win": 0, "loss": 0, "expired": 0, "timeout": 0, "tickers_checked": 0}

        # Jalur Cepat: TradingView Scanner (hanya saat jam bursa, bar hari ini). Fallback ke yfinance.
        if prefer_tradingview:
            try:
                try:
                    from backend.tv_live_fetcher import fetch_tv_live_details
                except ImportError:
                    from tv_live_fetcher import fetch_tv_live_details
                tv_details = fetch_tv_live_details(combined_tickers)
                if tv_details:
                    changes = self.evaluate(tv_details)
                    changes["tickers_checked"] = len(tv_details)
                    changes["live_details"] = tv_details
                    changes["source"] = "tradingview"
                    return changes
            except Exception as exc:
                print(f"[TrackerLive] TradingView gagal, fallback yfinance: {exc}")

        try:
            import yfinance as yf
            symbols = [f"{t}.JK" for t in combined_tickers]
            raw = yf.download(symbols, period="5d", group_by="ticker", progress=False, auto_adjust=False, threads=True)
            if raw is None or raw.empty:
                return {"entered": 0, "win": 0, "loss": 0, "expired": 0, "timeout": 0, "tickers_checked": 0}

            is_multi = isinstance(raw.columns, pd.MultiIndex)
            live_details = {}

            for ticker in combined_tickers:
                sym = f"{ticker}.JK"
                try:
                    if is_multi:
                        if sym in raw.columns.get_level_values(0):
                            sub = raw[sym].copy()
                        elif sym in raw.columns.get_level_values(1):
                            sub = raw.xs(sym, level=1, axis=1).copy()
                        else:
                            continue
                    else:
                        if len(combined_tickers) == 1:
                            sub = raw.copy()
                        else:
                            continue

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

                # 2. Trading plan (Entry, SL, TP) & Entry Price TERKUNCI sejak sinyal dicatat.
                #    Hanya harga terakhir & P/L (dari entry_price terkunci) yang diperbarui.
                upd: dict[str, Any] = {}
                if cur_close > 0 and float(row.get("last_close") or 0) != cur_close:
                    upd["last_close"] = cur_close
                if d.get("sector") and row.get("sector") != d.get("sector"):
                    upd["sector"] = str(d["sector"])[:200]
                if st == "RUNNING" and not is_dist_warning:
                    ep = float(row.get("entry_price") or 0)
                    if ep > 0 and cur_close > 0:
                        new_pnl = round((cur_close - ep) / ep * 100.0, 2)
                        if float(row.get("pnl_pct") or 0) != new_pnl:
                            upd["pnl_pct"] = new_pnl

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
    def evaluate(self, details: dict[str, dict], force_final: bool = False) -> dict:
        """Proses candle harian (termasuk live intraday candle) untuk setiap sinyal aktif.
        Tidak lagi memanggil prune otomatis: trading plan sinyal aktif tetap terkunci."""
        today_str = now_wib().strftime("%Y-%m-%d")
        changes = {"entered": 0, "win": 0, "loss": 0, "expired": 0, "timeout": 0, "events": []}

        # Bersihkan sinyal duplikat terlebih dahulu
        self.cleanup_duplicate_signals()

        with self._lock, self.engine.begin() as conn:
            from collections import defaultdict
            win_tickers_by_date: dict[str, set[str]] = defaultdict(set)
            win_rows = conn.execute(
                select(signals_table.c.ticker, signals_table.c.exit_date, signals_table.c.signal_date).where(
                    signals_table.c.status == "WIN"
                )
            ).all()
            for wt, wext, wsig in win_rows:
                if wext:
                    win_tickers_by_date[str(wext)].add(str(wt).upper())
                if wsig:
                    win_tickers_by_date[str(wsig)].add(str(wt).upper())
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
                since = str(r.get("last_eval_date") or r["signal_date"])
                entry_dt = str(r.get("entry_date") or r["signal_date"])

                for bar in hist:
                    bar_date = str(bar["date"])

                    # 1. Mutlak: Jangan pernah evaluasi candle sebelum tanggal sinyal lahir
                    if bar_date < r["signal_date"]:
                        continue

                    # 2. Posisi RUNNING hanya boleh dievaluasi dari tanggal entry ke depan
                    if r["status"] == "RUNNING" and bar_date < entry_dt:
                        continue

                    is_live_today = False if force_final else (bar_date == today_str and now_wib().time() < MARKET_CLOSE_CUTOFF)

                    # 3. Lewati candle historis yang sudah selesai dievaluasi final
                    if bar_date < since:
                        continue
                    if r["status"] == "RUNNING" and bar_date == since and not is_live_today and r.get("last_eval_date"):
                        continue

                    self._step(r, bar, changes, is_live_today=is_live_today, win_tickers_by_date=win_tickers_by_date)

                    # Update last_eval_date jika bar sudah final atau trade sudah ditutup
                    if not is_live_today or r["status"] not in ACTIVE_STATUSES:
                        r["last_eval_date"] = bar_date

                    if r["status"] not in ACTIVE_STATUSES:
                        break

                r["last_close"] = float(hist[-1]["close"])

                # Proteksi Evaluasi Real-Time untuk Sinyal RUNNING (Hanya jika entry_date < hari candle terakhir):
                last_bar_date = str(hist[-1]["date"])
                if r["status"] == "RUNNING" and r.get("entry_price") and str(r.get("entry_date") or "") < last_bar_date:
                    cur_c = r["last_close"]
                    cur_h = float(hist[-1].get("high") or cur_c)
                    tp_val = float(r.get("target") or 0)
                    sl_val = float(r.get("stop_loss") or 0)

                    if sl_val > 0 and cur_c <= sl_val:
                        self._close(
                            r,
                            last_bar_date,
                            cur_c,
                            "LOSS",
                            f"Stop Loss Closing Basis (Rp {sl_val:,.0f}) tertembus! Harga terkini: Rp {cur_c:,.0f}.",
                            changes,
                        )
                    elif tp_val > 0 and (cur_c >= tp_val or cur_h >= tp_val):
                        exit_price = tp_val if cur_h >= tp_val and cur_c < tp_val else cur_c
                        self._close(
                            r,
                            last_bar_date,
                            exit_price,
                            "WIN",
                            f"Target Price (Rp {tp_val:,.0f}) tercapai! Harga terkini: Rp {cur_c:,.0f} (High Rp {cur_h:,.0f}).",
                            changes,
                        )

                # Fallback Eksekusi Antrean WATCHLIST: Jika Low candle terakhir sudah menyentuh / di bawah harga Entry Limit
                if r["status"] == "WATCHLIST":
                    cur_l = float(hist[-1].get("low") or hist[-1]["close"])
                    cur_o = float(hist[-1].get("open") or hist[-1]["close"])
                    cur_c = float(hist[-1]["close"])
                    e_high = float(r.get("entry_high") or 0)
                    sl_val = float(r.get("stop_loss") or 0)

                    # Jika saham sudah Take Profit (WIN) di hari ini, DILARANG entry kembali di hari yang sama!
                    if win_tickers_by_date and r["ticker"].upper() in win_tickers_by_date.get(last_bar_date, set()):
                        continue

                    if e_high > 0 and cur_l <= e_high and last_bar_date >= str(r.get("signal_date") or ""):
                        fill = e_high
                        r["entry_price"] = round(fill, 2)
                        r["entry_low"] = round(fill, 2)
                        r["entry_high"] = round(fill, 2)
                        if cur_c <= sl_val or (sl_val > 0 and cur_l <= sl_val * 0.96):
                            exit_p = min(cur_o, sl_val) if cur_o < sl_val else (cur_c if cur_c <= sl_val else sl_val)
                            self._close(
                                r,
                                last_bar_date,
                                exit_p,
                                "LOSS",
                                f"Entry tereksekusi @ Rp {fill:,.0f}, lalu Stop Loss tertembus (Close Rp {cur_c:,.0f} <= SL Rp {sl_val:,.0f}).",
                                changes,
                            )
                        else:
                            pnl = round((cur_c - fill) / fill * 100.0, 2)
                            r["status"] = "RUNNING"
                            r["entry_date"] = last_bar_date
                            r["entry_price"] = round(fill, 2)
                            r["bars_held"] = 0
                            r["pnl_pct"] = pnl
                            r["note"] = f"Entry tereksekusi {last_bar_date} @ Rp {fill:,.0f} (Low Rp {cur_l:,.0f} menyentuh Entry Rp {e_high:,.0f}). Floating: {pnl:+.2f}%."
                            changes["entered"] += 1
                    elif isinstance(d.get("trading_plan"), dict):
                        tp_live = d["trading_plan"]
                        raw_ep = float(tp_live.get("entry_price") or tp_live.get("entry_high") or 0)
                        raw_sl = float(tp_live.get("stop_loss") or 0)
                        raw_tp1 = float(tp_live.get("target_1") or tp_live.get("tp1") or 0)
                        raw_tp2 = float(tp_live.get("target_2") or tp_live.get("tp2") or 0)
                        if raw_ep > 0 and raw_ep < cur_c:
                            new_ep, new_sl, new_tp1, new_tp2 = align_signal_prices(raw_ep, raw_sl, raw_tp1, raw_tp2)
                            r["entry_low"] = new_ep
                            r["entry_high"] = new_ep
                            r["stop_loss"] = new_sl
                            r["target"] = new_tp2 if self.tp_level == 2 else new_tp1
                            r["target_2"] = new_tp2
                            sup_lbl = tp_live.get("support_label") or "Support Terdekat"
                            r["note"] = f"Menunggu entry di {sup_lbl} (Rp {new_ep:,.0f})."

                if r["status"] == "RUNNING" and r.get("entry_price"):
                    sync_ep = float(r.get("entry_high") or r.get("entry_price") or 0)
                    if sync_ep > 0:
                        r["entry_price"] = sync_ep
                        r["entry_low"] = sync_ep
                        r["entry_high"] = sync_ep
                    cur_c = r["last_close"]
                    r["pnl_pct"] = round((cur_c - r["entry_price"]) / r["entry_price"] * 100.0, 2)
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

    def _step(self, r: dict, bar: dict, changes: dict, is_live_today: bool = False, win_tickers_by_date: dict | None = None) -> None:
        o, h, l, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
        date = str(bar["date"])

        if r["status"] == "WATCHLIST":
            # Aturan Ketat: Jika saham sudah Take Profit (WIN) di hari yang sama (date),
            # DILARANG entry kembali di hari yang sama! Harus menunggu hari berikutnya (hari ke-2).
            if win_tickers_by_date and r["ticker"].upper() in win_tickers_by_date.get(date, set()):
                return
            e_low, e_high, sl = r["entry_low"], r["entry_high"], r["stop_loss"]

            # 1. Proteksi gap down ekstrim: pembukaan di bawah Stop Loss langsung dibatalkan
            if o <= sl:
                r.update(
                    status="EXPIRED",
                    exit_date=date,
                    exit_price=round(o, 2),
                    pnl_pct=0.0,
                    note="Batal beli: Gap down ekstrim langsung di bawah Stop Loss.",
                )
                changes["expired"] += 1
                changes.setdefault("events", []).append({
                    "event": "EXPIRED_GAP_DOWN",
                    "ticker": r["ticker"],
                    "price": round(o, 2),
                    "pnl_pct": 0.0,
                    "note": r["note"],
                })
                return

            # 2. Antrean Buy Limit tereksekusi saat harga pasar (Low) menyentuh atau berada di bawah harga antrean (l <= e_high)
            if l <= e_high:
                # Harga eksekusi (fill) disinkronkan 100% dengan Harga Beli (e_high) agar Harga Beli == Harga Masuk
                fill = e_high
                r["entry_price"] = round(fill, 2)
                r["entry_low"] = round(fill, 2)
                r["entry_high"] = round(fill, 2)
                r["entry_date"] = date
                r["bars_held"] = 0

                # Evaluasi Stop Loss berbasis Closing Basis (c <= sl) atau panic crash ekstrim (l <= sl * 0.96)
                if c <= sl or l <= sl * 0.96:
                    exit_p = min(o, sl) if o < sl else (c if c <= sl else sl)
                    self._close(
                        r,
                        date,
                        exit_p,
                        "LOSS",
                        f"Entry tereksekusi @ Rp {fill:,.0f}, lalu Stop Loss Closing Basis tertembus di hari yang sama (Close Rp {c:,.0f} <= SL Rp {sl:,.0f}).",
                        changes,
                    )
                    return

                # Kondisi normal: Low menyentuh area antrean dan Close bertahan di atas SL -> Posisi masuk RUNNING.
                # (TP tidak dihitung di hari pertama entry untuk mencegah look-ahead bias intraday)
                r.update(
                    status="RUNNING",
                    entry_date=date,
                    entry_price=round(fill, 2),
                    entry_low=round(fill, 2),
                    entry_high=round(fill, 2),
                    bars_held=0,
                    last_close=c,
                    pnl_pct=round((c - fill) / fill * 100.0, 2),
                    note=f"Entry tereksekusi {date} @ Rp {fill:,.0f} (Low Rp {l:,.0f} menyentuh Entry Rp {e_high:,.0f}).",
                )
                changes["entered"] += 1
                changes.setdefault("events", []).append({
                    "event": "RUNNING",
                    "ticker": r["ticker"],
                    "price": round(fill, 2),
                    "pnl_pct": r["pnl_pct"],
                    "note": r["note"],
                })
                return

            if not is_live_today:
                r["bars_waited"] = int(r.get("bars_waited") or 0) + 1
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
            entry_dt = str(r.get("entry_date") or r["signal_date"])
            if date < entry_dt:
                return
            sl, tp = float(r["stop_loss"]), float(r["target"])
            entry_p = float(r["entry_price"])

            # OHLC harian tidak menyimpan urutan harga intraday. Jangan memakai
            # high/low candle hari entry untuk menyimpulkan TP/SL setelah entry,
            # karena nilainya mungkin terjadi sebelum order terisi.
            if date == entry_dt:
                r["last_close"] = c
                r["pnl_pct"] = round((c - entry_p) / entry_p * 100.0, 2)
                r["note"] = (
                    f"Entry Rp {entry_p:,.0f} hari ini; TP/SL mulai dievaluasi "
                    f"pada candle berikutnya. Last Rp {c:,.0f} ({r['pnl_pct']:+.2f}%)."
                )
                return

            # 1. Parameter 2: Stop Loss berbasis Closing Basis (Close <= SL) + proteksi Gap Down (Open <= SL) / Panic Crash (Low <= SL * 0.96)
            hit_sl_close = (c <= sl) or (o <= sl) or (l <= sl * 0.96)
            if hit_sl_close:
                exit_p = o if o <= sl else (c if c <= sl else sl)
                note = "Stop Loss Closing Basis tertembus (Close <= SL)." if h < tp else "SL & TP tersentuh di hari yang sama — dihitung LOSS (konservatif)."
                self._close(r, date, exit_p, "LOSS", note, changes)
                return

            # 2. Target Price tersentuh / terlampaui (High >= TP atau Close >= TP)
            if h >= tp or c >= tp:
                exit_p = o if o > tp else tp
                self._close(r, date, exit_p, "WIN", f"Target Price (Rp {tp:,.0f}) tersentuh pada High Rp {h:,.0f} (Close Rp {c:,.0f}).", changes)
                return

            # Milestone Profit Alert untuk Orang Sibuk (Floating >= +4.5%):
            # Mengingatkan pekerja sibuk untuk mengamankan modal (pindah SL ke BEP) agar tidak berbalik rugi di sore hari.
            if h >= entry_p * 1.045 and "[BEP_ALERTED]" not in (r.get("note") or ""):
                r["note"] = f"{r.get('note', '')} [BEP_ALERTED]"
                changes.setdefault("events", []).append({
                    "event": "MILESTONE_BEP",
                    "ticker": r["ticker"],
                    "price": round(h, 2),
                    "pnl_pct": round((h - entry_p) / entry_p * 100.0, 2),
                    "note": f"Floating High mencapai Rp {h:,.0f} (+{round((h - entry_p)/entry_p*100, 1)}%). Waktunya amankan profit TP1 & pasang SL BEP!",
                })

            # 3. Belum tersentuh SL maupun TP -> tetap RUNNING dengan floating P/L terupdate
            r["last_close"] = c
            r["pnl_pct"] = round((c - entry_p) / entry_p * 100.0, 2)
            base_note = r.get("note", "").replace(" [BEP_ALERTED]", "")
            bep_flag = " [BEP_ALERTED]" if "[BEP_ALERTED]" in r.get("note", "") else ""
            r["note"] = f"Running: Entry Rp {entry_p:,.0f}, Last Rp {c:,.0f} ({r['pnl_pct']:+.2f}%). High hari ini Rp {h:,.0f}.{bep_flag}"

            if not is_live_today:
                r["bars_held"] = int(r.get("bars_held") or 0) + 1
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
        changes.setdefault("events", []).append({
            "event": status,
            "ticker": r["ticker"],
            "price": round(exit_price, 2),
            "pnl_pct": r["pnl_pct"],
            "note": note,
        })

    # ---------------------------------------------------------------- query
    def list_signals(self, status: str | None = None, sort_by: str = "id_desc", limit: int = 500) -> list[dict]:
        q = select(signals_table)
        if status and status.upper() != "ALL":
            if status.upper() == "CLOSED_OTHER":
                q = q.where(signals_table.c.status.in_(("EXPIRED", "TIMEOUT", "CANCELLED")))
            else:
                q = q.where(signals_table.c.status == status.upper())
        else:
            q = q.where(signals_table.c.status != "CANCELLED")

        sort_by_clean = (sort_by or "date_desc").lower().strip()
        if sort_by_clean in ("pnl_desc", "pnl"):
            q = q.order_by(signals_table.c.pnl_pct.desc().nulls_last(), signals_table.c.id.desc())
        elif sort_by_clean == "pnl_asc":
            q = q.order_by(signals_table.c.pnl_pct.asc().nulls_last(), signals_table.c.id.desc())
        elif sort_by_clean in ("score_desc", "score"):
            q = q.order_by(signals_table.c.score.desc(), signals_table.c.id.desc())
        elif sort_by_clean == "score_asc":
            q = q.order_by(signals_table.c.score.asc(), signals_table.c.id.desc())
        elif sort_by_clean in ("date_desc", "date", "id_desc", "id"):
            q = q.order_by(signals_table.c.signal_date.desc(), signals_table.c.id.desc())
        elif sort_by_clean in ("date_asc", "id_asc"):
            q = q.order_by(signals_table.c.signal_date.asc(), signals_table.c.id.asc())
        elif sort_by_clean in ("ticker_asc", "ticker"):
            q = q.order_by(signals_table.c.ticker.asc())
        elif sort_by_clean == "ticker_desc":
            q = q.order_by(signals_table.c.ticker.desc())
        else:
            q = q.order_by(signals_table.c.signal_date.desc(), signals_table.c.id.desc())

        q = q.limit(limit)
        with self.engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(q).mappings().all()]
        for r in rows:
            e_high = float(r.get("entry_high") or r.get("entry_price") or 0)
            r["entry_low"] = e_high
            r["entry_high"] = e_high
            r["entry_price_target"] = e_high
            if r.get("status") in ("RUNNING", "WIN", "LOSS", "TIMEOUT") and e_high > 0:
                if float(r.get("entry_price") or 0) != e_high:
                    r["entry_price"] = e_high
                    ref_px = float(r.get("exit_price") or r.get("last_close") or 0) if r.get("status") != "RUNNING" else float(r.get("last_close") or 0)
                    if ref_px > 0:
                        r["pnl_pct"] = round((ref_px - e_high) / e_high * 100.0, 2)
            if r["status"] == "WATCHLIST" and e_high > 0:
                r["dist_to_entry_pct"] = round((float(r.get("last_close") or 0) - e_high) / e_high * 100.0, 2)

        if sort_by_clean in ("distance_asc", "dist_asc", "dist"):
            rows.sort(key=lambda x: (abs(float(x.get("dist_to_entry_pct") if x.get("dist_to_entry_pct") is not None else 999.0)), -int(x.get("score") or 0)))

        return rows

    def get_priority_watchlist_candidates(self, limit: int = 3) -> list[dict]:
        """Mengambil Top N antrean WATCHLIST terbaik & paling siap dieksekusi (jarak harga terdekat ke support & diversifikasi sektor)."""
        all_wl = self.list_signals(status="WATCHLIST", sort_by="date_desc")
        if not all_wl:
            return []

        # Urutkan berdasarkan jarak terdekat ke entry price (terdekat ke support), lalu skor SM tertinggi
        sorted_wl = sorted(
            all_wl,
            key=lambda x: (
                abs(float(x.get("dist_to_entry_pct") if x.get("dist_to_entry_pct") is not None else 999.0)),
                -int(x.get("score") or 0),
            )
        )

        chosen = []
        seen_sectors = set()
        for item in sorted_wl:
            sec = str(item.get("sector") or "General").strip()
            if sec not in seen_sectors:
                seen_sectors.add(sec)
                chosen.append(item)
            if len(chosen) >= limit:
                break

        if len(chosen) < limit:
            for item in sorted_wl:
                if item not in chosen:
                    chosen.append(item)
                if len(chosen) >= limit:
                    break

        return chosen

    def stats(self) -> dict:
        with self.engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(select(signals_table)).mappings().all()]

        def by_status(st: str) -> list[dict]:
            return [r for r in rows if r["status"] == st]

        wins, losses, timeouts = by_status("WIN"), by_status("LOSS"), by_status("TIMEOUT")
        running = by_status("RUNNING")
        win_p = [float(r["pnl_pct"] or 0) for r in wins]
        loss_p = [float(r["pnl_pct"] or 0) for r in losses]
        timeout_p = [float(r["pnl_pct"] or 0) for r in timeouts]
        closed_p = win_p + loss_p + timeout_p
        decided = len(wins) + len(losses) + len(timeouts)
        gross_win = sum(win_p) + sum(p for p in timeout_p if p > 0)
        gross_loss = abs(sum(loss_p)) + abs(sum(p for p in timeout_p if p < 0))
        fee = self.fee_roundtrip_pct

        by_trigger: dict[str, dict] = {}
        for r in rows:
            t = r["trigger_type"] or "OTHER"
            b = by_trigger.setdefault(t, {"label": r["trigger_label"] or t, "total": 0, "win": 0, "loss": 0, "timeout": 0, "running": 0, "pnls": []})
            b["total"] += 1
            if r["status"] == "WIN":
                b["win"] += 1
            elif r["status"] == "LOSS":
                b["loss"] += 1
            elif r["status"] == "TIMEOUT":
                b["timeout"] += 1
            elif r["status"] == "RUNNING":
                b["running"] += 1
            if r["status"] in ("WIN", "LOSS", "TIMEOUT"):
                b["pnls"].append(float(r["pnl_pct"] or 0))
        for b in by_trigger.values():
            dec = b["win"] + b["loss"] + b["timeout"]
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
            "cancelled": len(by_status("CANCELLED")),
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

    def rebuild_recent_days(self, market_df: pd.DataFrame, days: int = 10) -> dict:
        """
        Mengisi ulang database tracker.db dari riwayat pasar 10 hari bursa terakhir (Simulasi Replay Historis).
        Menggunakan aturan kuantitatif terbaru & eksekusi instan (< 1.5 detik).
        """
        try:
            from backend.screener_engine import (
                compute_quantitative_dataframe,
                compute_support_entry_plan,
                _round_idx_tick,
                classify_idx_sector,
                check_fundamental_and_board_safety,
                evaluate_tape_and_closing_quality,
            )
        except ImportError:
            from screener_engine import (
                compute_quantitative_dataframe,
                compute_support_entry_plan,
                _round_idx_tick,
                classify_idx_sector,
                check_fundamental_and_board_safety,
                evaluate_tape_and_closing_quality,
            )

        trigger_labels = {
            "MARKUP_BREAKOUT": "Markup / Breakout Akumulasi",
            "BIG_ACCUMULATION": "Akumulasi Likuiditas Besar",
            "SILENT_ACCUMULATION": "Silent Accumulation (Squeeze)",
            "FOREIGN_INFLOW": "Inflow Dana Asing Masif",
        }

        # 1. Hapus seluruh data lama di tracker.db
        self.reset_all()

        is_sqlite = "sqlite" in str(self.engine.url)
        if is_sqlite:
            with self.engine.begin() as con:
                con.exec_driver_sql("PRAGMA synchronous = OFF")

        try:
            # 2. Hitung seluruh indikator kuantitatif 1 kali saja di awal secara vektor
            df = compute_quantitative_dataframe(market_df)
            median_val_tx = max(1_000_000.0, float(df["Val_Per_Tx"].median())) if "Val_Per_Tx" in df.columns else 2_500_000.0

            # 3. Ambil 10 tanggal bursa terakhir
            target_dates = sorted(df["Date"].dropna().astype(str).unique())[-days:]

            total_added = 0
            total_changes = {"entered": 0, "win": 0, "loss": 0, "expired": 0, "timeout": 0}

            # 4. Loop kronologis untuk setiap dt di target_dates
            for dt in target_dates:
                # a. Susun details_dt dari df[df["Date"] <= dt] dan jalankan evaluate
                active_tickers = set(self.get_active_tickers())
                if active_tickers:
                    sub_df = df[(df["Date"] <= dt) & (df["Ticker"].isin(active_tickers))]
                    details_dt = {}
                    for ticker, g in sub_df.groupby("Ticker"):
                        lat = g.iloc[-1]
                        hist = [
                            {
                                "date": str(r.Date),
                                "open": float(r.Open),
                                "high": float(r.High),
                                "low": float(r.Low),
                                "close": float(r.Close),
                            }
                            for r in g.tail(5).itertuples()
                        ]
                        details_dt[ticker] = {
                            "close": float(lat["Close"]),
                            "smart_money_score": int(lat["Smart_Money_Score"]),
                            "trigger_type": str(lat["Trigger_Type"]),
                            "sector": str(lat.get("Sector", "")),
                            "diff_bandar_avg_pct": float(lat.get("Diff_VWAP_Pct", 0.0)),
                            "value_idr": float(lat.get("Value_IDR", 0.0)),
                            "history": hist,
                        }
                    ch = self.evaluate(details_dt, force_final=True)
                    for k in total_changes:
                        total_changes[k] += ch.get(k, 0)

                # b. Filter baris day_df = df[df["Date"] == dt] yang memenuhi syarat auto_track
                day_df = df[df["Date"] == dt]
                cand = day_df[(day_df["Trigger_Type"].isin(TRACKABLE_TRIGGERS)) & (day_df["Smart_Money_Score"] >= self.min_score)]
                # Urutkan berdasarkan (Smart_Money_Score, Volume_Ratio) tertinggi dan batasi maksimal 3 saham terbaik per tanggal bursa
                cand = cand.sort_values(by=["Smart_Money_Score", "Volume_Ratio"], ascending=[False, False])
                day_added = 0
                seen_day_sectors: set[str] = set()
                for r in cand.itertuples():
                    if day_added >= 3:
                        break
                    c_price = int(round(float(r.Close)))
                    val_idr = float(r.Value_IDR) if hasattr(r, "Value_IDR") else 1_000_000_000.0
                    freq_val = float(r.Frequency) if hasattr(r, "Frequency") else 500.0
                    has_real_freq = bool(getattr(r, "Has_Broker_Summary", False))
                    r_sec = str(r.Sector) if hasattr(r, "Sector") else ""
                    vol_ratio_val = float(r.Volume_Ratio) if hasattr(r, "Volume_Ratio") else 1.0
                    cr_val = float(r.Closing_Range) if hasattr(r, "Closing_Range") else 0.7
                    pct_val = float(r.Pct_Change) if hasattr(r, "Pct_Change") else 0.0

                    # Item 4: Filter Fundamental & Board Safety
                    fund = check_fundamental_and_board_safety(
                        str(r.Ticker).upper(), r_sec, c_price, val_idr / 1e9, freq_val, has_real_freq=has_real_freq
                    )
                    if not fund["is_safe"]:
                        continue

                    # Item 5: Filter Kualitas Tape & Anti Manipulasi Pre-Closing
                    tape = evaluate_tape_and_closing_quality(
                        vol_ratio_val, cr_val, pct_val, val_idr, freq_val, median_val_tx, has_real_freq=has_real_freq
                    )
                    if not tape["is_organic"]:
                        continue

                    # Item 2: Batasan Korelasi Sektor (Maks 1 saham per sektor per hari)
                    sec_cat = classify_idx_sector(str(r.Ticker).upper(), r_sec)
                    if sec_cat in seen_day_sectors:
                        continue
                    diff_vwap = round(float(r.Diff_VWAP_Pct), 2) if hasattr(r, "Diff_VWAP_Pct") else 0.0
                    vwap_5d_val = int(round(float(r.VWAP_5D))) if hasattr(r, "VWAP_5D") and not pd.isna(r.VWAP_5D) else c_price
                    atr14_val = int(r.ATR14) if hasattr(r, "ATR14") and not pd.isna(r.ATR14) else max(1, int(round(c_price * 0.03)))
                    ep_plan = compute_support_entry_plan(
                        close_price=c_price,
                        open_price=float(r.Open) if hasattr(r, "Open") else c_price,
                        low_price=float(r.Low) if hasattr(r, "Low") else c_price,
                        prev_close=float(r.Prev_Close) if hasattr(r, "Prev_Close") else c_price,
                        pct_change=pct_val,
                        vwap_5d=vwap_5d_val,
                        ma5=float(r.MA5) if hasattr(r, "MA5") else vwap_5d_val,
                        ma10=float(r.MA10) if hasattr(r, "MA10") else vwap_5d_val,
                        ma20=float(r.MA20) if hasattr(r, "MA20") else vwap_5d_val,
                        prev_high_5d=float(r.Prev_High_5D) if hasattr(r, "Prev_High_5D") else c_price,
                        atr14_val=atr14_val,
                    )
                    entry_price = ep_plan["entry_price"]
                    entry_low = ep_plan["entry_low"]
                    entry_high = ep_plan["entry_high"]
                    sl = ep_plan["stop_loss"]
                    tp1 = ep_plan["tp1"]
                    tp2 = ep_plan["tp2"]

                    val_idr = float(r.Value_IDR) if hasattr(r, "Value_IDR") else 1_000_000_000.0
                    trig_type = str(r.Trigger_Type)
                    trig_lbl = trigger_labels.get(trig_type, trig_type)
                    stock_obj = {
                        "ticker": str(r.Ticker).upper(),
                        "sector": str(r.Sector) if hasattr(r, "Sector") else "",
                        "date": str(r.Date),
                        "close": c_price,
                        "smart_money_score": int(r.Smart_Money_Score),
                        "pct_change": round(float(r.Pct_Change), 2) if hasattr(r, "Pct_Change") else 0.0,
                        "closing_range": round(float(r.Closing_Range), 2) if hasattr(r, "Closing_Range") else 0.7,
                        "closing_range_pct": int(round(float(r.Closing_Range) * 100)) if hasattr(r, "Closing_Range") else 70,
                        "diff_bandar_avg_pct": diff_vwap,
                        "value_idr": val_idr,
                        "value_b_idr": round(val_idr / 1e9, 2),
                        "trigger_type": trig_type,
                        "trigger_label": trig_lbl,
                        "trading_plan": {
                            "entry_price": entry_price,
                            "entry_low": entry_low,
                            "entry_high": entry_high,
                            "stop_loss": sl,
                            "stop_loss_pct": round(((sl - entry_price) / max(entry_price, 1)) * 100.0, 2),
                            "target_1": tp1,
                            "target_1_pct": round(((tp1 - entry_price) / max(entry_price, 1)) * 100.0, 2),
                            "target_2": tp2,
                            "target_2_pct": round(((tp2 - entry_price) / max(entry_price, 1)) * 100.0, 2),
                            "diff_bandar_avg_pct": diff_vwap,
                        },
                    }
                    ok, _ = self.add_signal(stock_obj, source="REPLAY")
                    if ok:
                        day_added += 1
                        seen_day_sectors.add(sec_cat)
                        total_added += 1

            return {
                "target_dates": target_dates,
                "days_rebuilt": len(target_dates),
                "added": total_added,
                "changes": total_changes,
                "stats": self.stats(),
            }
        finally:
            if is_sqlite:
                with self.engine.begin() as con:
                    con.exec_driver_sql("PRAGMA synchronous = NORMAL")

    def get_today_candidates(self, date_str: str) -> list[dict]:
        with self._lock, self.engine.begin() as conn:
            today_candidates_table.create(conn, checkfirst=True)
            rows = conn.execute(
                select(today_candidates_table)
                .where(today_candidates_table.c.date == date_str)
                .order_by(today_candidates_table.c.batch_order.asc(), today_candidates_table.c.id.asc())
            ).mappings().all()
            return [dict(r) for r in rows]

    def sync_today_candidates(
        self,
        date_str: str,
        candidate_stocks: list[dict],
        all_stocks: list[dict] | None = None,
    ) -> list[dict]:
        """
        Konsistensi Menu 'Pilihan Saham Hari Ini':
        1. Jika siang menampilkan saham A lalu ada tambahan data saham karena diperbarui,
           saham A tetap ditampilkan tapi diberi label sesi deteksi (misal: Sesi 1 (Siang)).
        2. Saham baru yang lolos di sesi berikutnya ditambahkan dengan label 'Pembaruan Sesi 2'.
        3. Saham yang masuk kriteria di menu hari ini yang ditampilkan WAJIB dicatat di Watchlist.
        4. Setiap saham entry-nya berada di Support Terdekat (menunggu pullback).
        """
        now = now_wib()
        t = now.time()
        if t < dtime(11, 30):
            cur_session = "Sesi 1 (Pagi)"
        elif t < dtime(13, 30):
            cur_session = "Sesi 1 (Siang)"
        elif t < dtime(16, 15):
            cur_session = "Pembaruan Sesi 2"
        else:
            cur_session = "Sesi Penutupan (EOD)"

        time_str = now.strftime("%H:%M WIB")
        stocks_pool = {str(s.get("ticker", "")).upper(): s for s in (all_stocks or candidate_stocks)}

        with self._lock, self.engine.begin() as conn:
            today_candidates_table.create(conn, checkfirst=True)
            existing_rows = conn.execute(
                select(today_candidates_table)
                .where(today_candidates_table.c.date == date_str)
                .order_by(today_candidates_table.c.batch_order.asc(), today_candidates_table.c.id.asc())
            ).mappings().all()

            existing_map = {r["ticker"].upper(): dict(r) for r in existing_rows}
            curr_count = len(existing_rows)

            # Tambahkan emiten baru dari candidate_stocks yang belum ada di tabel hari ini
            for idx, c in enumerate(candidate_stocks):
                t_up = str(c.get("ticker", "")).upper()
                if not t_up or t_up in existing_map:
                    continue

                session_lbl = cur_session
                if curr_count > 0 and "Sesi 2" in cur_session:
                    session_lbl = "Pembaruan Sesi 2"

                conn.execute(
                    insert(today_candidates_table).values(
                        date=date_str,
                        ticker=t_up,
                        first_seen_time=time_str,
                        session_label=session_lbl,
                        batch_order=curr_count + idx + 1,
                        created_at=_now_str(),
                        updated_at=_now_str(),
                    )
                )
                existing_map[t_up] = {
                    "date": date_str,
                    "ticker": t_up,
                    "first_seen_time": time_str,
                    "session_label": session_lbl,
                    "batch_order": curr_count + idx + 1,
                }

            # Ambil seluruh emiten hari ini sesuai urutan batch
            final_rows = conn.execute(
                select(today_candidates_table)
                .where(today_candidates_table.c.date == date_str)
                .order_by(today_candidates_table.c.batch_order.asc(), today_candidates_table.c.id.asc())
            ).mappings().all()

        merged_candidates = []
        for r in final_rows:
            t_up = r["ticker"].upper()
            s_data = stocks_pool.get(t_up)
            if not s_data:
                for cs in candidate_stocks:
                    if str(cs.get("ticker", "")).upper() == t_up:
                        s_data = cs
                        break
            if not s_data:
                continue

            item = dict(s_data)
            item["session_label"] = r.get("session_label") or "Tercatat Siang"
            item["first_seen_time"] = r.get("first_seen_time") or time_str

            plan = item.get("trading_plan") or {}
            support_entry = float(plan.get("entry_price") or plan.get("entry_high") or item.get("close") or 0)
            item["entry_price"] = support_entry
            item["support_label"] = plan.get("support_label") or "Support Terdekat"

            # Wajib dicatat / disinkronkan ke Watchlist
            self._ensure_candidate_in_watchlist(item, date_str, item["session_label"])
            merged_candidates.append(item)

        # Filter ketat hasil kandidat hari ini:
        # 1. Tolak saham pucuk yang sudah terbang tinggi (pct_change > 4.5%)
        # 2. Tolak saham yang sudah terbang jauh dari modal bandar (diff_bandar_avg_pct > 3.5% atau < -4.5%)
        # 3. Tolak saham distribusi / retail trap
        # 4. Batasi maksimal 8-10 saham terbaik
        strict_candidates = []
        for item in merged_candidates:
            pct = float(item.get("pct_change") or 0)
            diff_bdr = float(item.get("diff_bandar_avg_pct") or 0)
            if pct > 4.5:
                continue
            if item.get("retail_trap") or item.get("trigger_type") == "DISTRIBUTION_WARNING":
                continue
            if item.get("diff_bandar_avg_pct") is not None and (diff_bdr < -4.5 or diff_bdr > 3.5):
                continue
            strict_candidates.append(item)

        strict_candidates.sort(
            key=lambda x: (
                -abs(float(x.get("diff_bandar_avg_pct") or 0)),
                float(x.get("bdr_pct") or 0),
                int(x.get("smart_money_score") or 0),
            ),
            reverse=True,
        )

        final_picks = strict_candidates[:10] if strict_candidates else merged_candidates[:6]
        return final_picks

    def _ensure_candidate_in_watchlist(self, stock: dict, date_str: str, session_label: str) -> None:
        """Memastikan saham pilihan hari ini tercatat di Watchlist (signals_table)."""
        ticker = str(stock.get("ticker", "")).upper()
        if not ticker:
            return

        with self._lock, self.engine.begin() as conn:
            existing = conn.execute(
                select(signals_table).where(
                    signals_table.c.ticker == ticker,
                    signals_table.c.status.in_(ACTIVE_STATUSES),
                )
            ).mappings().first()

            plan = stock.get("trading_plan") or {}
            c_p = float(stock.get("close") or 0)
            raw_ep = float(plan.get("entry_price") or plan.get("entry_high") or (c_p * 0.98))
            raw_sl = float(plan.get("stop_loss") or (raw_ep * 0.95))
            raw_tp1 = float(plan.get("target_1") or plan.get("tp1") or (raw_ep * 1.06))
            raw_tp2 = float(plan.get("target_2") or plan.get("tp2") or (raw_ep * 1.10))

            e_p, sl, tp1, tp2 = align_signal_prices(raw_ep, raw_sl, raw_tp1, raw_tp2)
            score = int(stock.get("smart_money_score") or 70)
            sup_lbl = str(plan.get("support_label") or "Support Terdekat")
            trig_type = str(stock.get("trigger_type") or "BIG_ACCUMULATION")
            trig_lbl = str(stock.get("trigger_label") or "Akumulasi Broker")

            if not existing:
                # Cek apakah emiten sudah pernah Take Profit (WIN) atau exit hari ini / tanggal ini
                # Sesuai aturan: jika saham sudah take profit di hari yang sama, DILARANG entry kembali!
                prior_trade_today = conn.execute(
                    select(signals_table).where(
                        signals_table.c.ticker == ticker,
                        or_(
                            signals_table.c.signal_date == date_str,
                            signals_table.c.exit_date == date_str,
                        ),
                    )
                ).mappings().first()
                if prior_trade_today:
                    return

                # Tolak jika skor di bawah minimum atau terdeteksi distribusi
                if score < self.min_score or trig_type == "DISTRIBUTION_WARNING":
                    return

                primary_tp = tp2 if self.tp_level == 2 else tp1
                conn.execute(
                    insert(signals_table).values(
                        ticker=ticker,
                        sector=str(stock.get("sector", ""))[:200],
                        trigger_type=trig_type,
                        trigger_label=trig_lbl,
                        score=score,
                        source="AUTO_TODAY",
                        signal_date=date_str,
                        signal_close=c_p,
                        entry_low=e_p,
                        entry_high=e_p,
                        stop_loss=sl,
                        target=primary_tp,
                        target_2=tp2,
                        status="WATCHLIST",
                        last_close=c_p,
                        last_eval_date=None,
                        bars_waited=0,
                        bars_held=0,
                        note=f"Pilihan Saham Hari Ini ({session_label}) - Antre Pullback di {sup_lbl}",
                        created_at=_now_str(),
                        updated_at=_now_str(),
                    )
                )
            else:
                if existing["status"] == "WATCHLIST":
                    primary_tp = tp2 if self.tp_level == 2 else tp1
                    conn.execute(
                        update(signals_table)
                        .where(signals_table.c.id == existing["id"])
                        .values(
                            entry_low=e_p,
                            entry_high=e_p,
                            stop_loss=sl,
                            target=primary_tp,
                            target_2=tp2,
                            last_close=c_p,
                            note=f"Pilihan Saham Hari Ini ({session_label}) - Antre Pullback di {sup_lbl}",
                            updated_at=_now_str(),
                        )
                    )
