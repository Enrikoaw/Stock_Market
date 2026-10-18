"""
SmartFlow IDX — Portfolio Tracker (Jurnal Trading & Portofolio Riil)
Melacak transaksi riil pengguna (beli & jual di sekuritas) secara terpisah dari Paper Tracker sistem.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
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
    create_engine,
    delete,
    insert,
    select,
    update,
)

WIB = ZoneInfo("Asia/Jakarta")
portfolio_metadata = MetaData()

portfolio_table = Table(
    "portfolio",
    portfolio_metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ticker", String(10), nullable=False, index=True),
    Column("sector", String(200)),
    Column("entry_date", String(10), nullable=False),
    Column("entry_price", Float, nullable=False),
    Column("lots", Integer, nullable=False),
    Column("stop_loss", Float),
    Column("target_price", Float),
    Column("broker", String(50)),
    Column("status", String(20), default="HOLDING"),  # HOLDING, CLOSED
    Column("exit_date", String(10)),
    Column("exit_price", Float),
    Column("notes", Text),
    Column("created_at", String(30)),
    Column("updated_at", String(30)),
)


def _now_str() -> str:
    return datetime.now(WIB).strftime("%Y-%m-%d %H:%M:%S")


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


class PortfolioTracker:
    def __init__(self, sqlite_path: Path | str) -> None:
        self._lock = threading.RLock()
        if isinstance(sqlite_path, str):
            sqlite_path = Path(sqlite_path)
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        url = _resolve_db_url(sqlite_path)

        kwargs: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}

        try:
            self.engine = create_engine(url, **kwargs)
            if url.startswith("sqlite"):
                with self.engine.begin() as conn:
                    conn.exec_driver_sql("PRAGMA journal_mode = WAL;")
                    conn.exec_driver_sql("PRAGMA synchronous = NORMAL;")
                    conn.exec_driver_sql("PRAGMA busy_timeout = 10000;")
            portfolio_metadata.create_all(self.engine)
        except Exception:
            url = f"sqlite:///{sqlite_path.as_posix()}"
            self.engine = create_engine(url, **kwargs)
            portfolio_metadata.create_all(self.engine)

    def add_trade(
        self,
        ticker: str,
        entry_price: float,
        lots: int,
        entry_date: str | None = None,
        stop_loss: float | None = None,
        target_price: float | None = None,
        broker: str | None = "Sekuritas",
        notes: str | None = "",
        sector: str | None = "",
    ) -> dict[str, Any]:
        ticker_clean = str(ticker or "").strip().upper()
        if not ticker_clean:
            raise ValueError("Kode ticker saham tidak boleh kosong.")
        if entry_price <= 0:
            raise ValueError("Harga beli harus lebih dari 0.")
        if lots <= 0:
            raise ValueError("Jumlah lot harus minimal 1 lot.")

        date_str = entry_date or datetime.now(WIB).strftime("%Y-%m-%d")
        now = _now_str()

        with self._lock, self.engine.begin() as conn:
            res = conn.execute(
                insert(portfolio_table).values(
                    ticker=ticker_clean,
                    sector=str(sector or "")[:200],
                    entry_date=date_str,
                    entry_price=float(entry_price),
                    lots=int(lots),
                    stop_loss=float(stop_loss) if stop_loss else None,
                    target_price=float(target_price) if target_price else None,
                    broker=str(broker or "Sekuritas")[:50],
                    status="HOLDING",
                    notes=str(notes or ""),
                    created_at=now,
                    updated_at=now,
                )
            )
            trade_id = res.inserted_primary_key[0] if res.inserted_primary_key else None

        return {
            "id": trade_id,
            "ticker": ticker_clean,
            "entry_price": entry_price,
            "lots": lots,
            "total_capital": entry_price * lots * 100,
            "status": "HOLDING",
            "message": f"Transaksi beli {lots} lot {ticker_clean} @ Rp {entry_price:,.0f} berhasil dicatat di Portofolio.",
        }

    # Estimasi standar fee sekuritas BEI: Beli 0.15%, Jual 0.25%
    BUY_FEE_RATE = 0.0015
    SELL_FEE_RATE = 0.0025

    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        exit_date: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        if exit_price <= 0:
            raise ValueError("Harga jual harus lebih dari 0.")

        date_str = (exit_date or datetime.now(WIB).strftime("%Y-%m-%d")).strip()
        now = _now_str()

        with self._lock, self.engine.begin() as conn:
            row = conn.execute(
                select(portfolio_table).where(portfolio_table.c.id == trade_id)
            ).mappings().first()

            if not row:
                raise ValueError("Data transaksi tidak ditemukan.")

            if str(row.get("status") or "").upper() == "CLOSED":
                raise ValueError("Transaksi ini sudah ditutup (CLOSED) sebelumnya.")

            entry_dt_str = str(row.get("entry_date") or "").strip()
            if len(entry_dt_str) == 10 and len(date_str) == 10 and date_str < entry_dt_str:
                raise ValueError(f"Tanggal jual ({date_str}) tidak boleh lebih awal dari tanggal beli ({entry_dt_str}).")

            upd: dict[str, Any] = {
                "status": "CLOSED",
                "exit_date": date_str,
                "exit_price": float(exit_price),
                "updated_at": now,
            }
            if notes:
                prev_note = str(row.get("notes") or "")
                upd["notes"] = f"{prev_note} | Jual: {notes}".strip(" |")

            conn.execute(
                update(portfolio_table)
                .where(portfolio_table.c.id == trade_id)
                .values(**upd)
            )

        entry = float(row["entry_price"])
        lots = int(row["lots"])
        gross_buy = entry * lots * 100.0
        gross_sell = float(exit_price) * lots * 100.0
        total_fee_rp = (gross_buy * self.BUY_FEE_RATE) + (gross_sell * self.SELL_FEE_RATE)
        pnl_rp = round(gross_sell - gross_buy - total_fee_rp, 0)
        pnl_pct = round((pnl_rp / max(gross_buy, 1.0)) * 100.0, 2)

        return {
            "id": trade_id,
            "ticker": row["ticker"],
            "entry_price": entry,
            "exit_price": exit_price,
            "lots": lots,
            "fee_rp": round(total_fee_rp, 0),
            "pnl_rp": pnl_rp,
            "pnl_pct": pnl_pct,
            "message": f"Posisi {row['ticker']} ditutup @ Rp {exit_price:,.0f} (Net P/L: Rp {pnl_rp:+,.0f} / {pnl_pct:+.2f}% setelah fee broker).",
        }

    def delete_trade(self, trade_id: int) -> bool:
        with self._lock, self.engine.begin() as conn:
            res = conn.execute(delete(portfolio_table).where(portfolio_table.c.id == trade_id))
            return res.rowcount > 0

    def list_trades(
        self,
        status: str = "ALL",
        live_prices_map: dict[str, float] | None = None,
    ) -> list[dict[str, Any]]:
        live_prices = live_prices_map or {}
        q = select(portfolio_table)
        st_clean = (status or "ALL").upper().strip()
        if st_clean != "ALL":
            q = q.where(portfolio_table.c.status == st_clean)
        q = q.order_by(portfolio_table.c.id.desc())

        with self.engine.connect() as conn:
            rows = [dict(r) for r in conn.execute(q).mappings().all()]

        result = []
        for r in rows:
            entry_p = float(r["entry_price"])
            lots = int(r["lots"])
            capital = entry_p * lots * 100.0
            st = str(r["status"]).upper()

            item = dict(r)
            item["total_capital"] = capital

            if st == "HOLDING":
                curr_p = float(live_prices.get(str(r["ticker"]).upper(), entry_p))
                curr_val = curr_p * lots * 100.0
                est_fee = (capital * self.BUY_FEE_RATE) + (curr_val * self.SELL_FEE_RATE)
                float_pnl_rp = round(curr_val - capital - est_fee, 0)
                float_pnl_pct = round((float_pnl_rp / max(capital, 1.0)) * 100.0, 2)

                item["current_price"] = curr_p
                item["current_value"] = curr_val
                item["fee_rp"] = round(est_fee, 0)
                item["pnl_rp"] = float_pnl_rp
                item["pnl_pct"] = float_pnl_pct
            else:
                exit_p = float(r.get("exit_price") or entry_p)
                exit_val = exit_p * lots * 100.0
                realized_fee = (capital * self.BUY_FEE_RATE) + (exit_val * self.SELL_FEE_RATE)
                pnl_rp = round(exit_val - capital - realized_fee, 0)
                pnl_pct = round((pnl_rp / max(capital, 1.0)) * 100.0, 2)
                item["current_price"] = exit_p
                item["current_value"] = exit_val
                item["fee_rp"] = round(realized_fee, 0)
                item["pnl_rp"] = pnl_rp
                item["pnl_pct"] = pnl_pct

            result.append(item)

        return result

    def summary(self, live_prices_map: dict[str, float] | None = None) -> dict[str, Any]:
        all_trades = self.list_trades(status="ALL", live_prices_map=live_prices_map)
        holdings = [t for t in all_trades if t["status"] == "HOLDING"]
        closed = [t for t in all_trades if t["status"] == "CLOSED"]

        total_capital_holding = sum(t["total_capital"] for t in holdings)
        total_value_holding = sum(t.get("current_value", t["total_capital"]) for t in holdings)
        floating_pnl_rp = sum(t.get("pnl_rp", 0.0) for t in holdings)
        floating_pnl_pct = round((floating_pnl_rp / total_capital_holding * 100.0), 2) if total_capital_holding > 0 else 0.0

        realized_pnl_rp = sum(t.get("pnl_rp", 0.0) for t in closed)
        wins = [t for t in closed if t.get("pnl_rp", 0) > 0]
        losses = [t for t in closed if t.get("pnl_rp", 0) < 0]
        win_rate = round(len(wins) / len(closed) * 100.0, 1) if closed else None

        return {
            "holding_count": len(holdings),
            "closed_count": len(closed),
            "total_trades": len(all_trades),
            "total_capital_holding": round(total_capital_holding, 0),
            "total_value_holding": round(total_value_holding, 0),
            "floating_pnl_rp": round(floating_pnl_rp, 0),
            "floating_pnl_pct": floating_pnl_pct,
            "realized_pnl_rp": round(realized_pnl_rp, 0),
            "win_trades": len(wins),
            "loss_trades": len(losses),
            "win_rate": win_rate,
        }
