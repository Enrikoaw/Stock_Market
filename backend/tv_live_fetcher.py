"""
TradingView Scanner Fast Quote Fetcher (IDX).
Menarik harga OHLCV hari ini untuk daftar saham kecil (Watchlist/Running) dalam < 1 detik,
sebagai pengganti yfinance untuk polling cepat (1 menit sekali).
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone

TV_SCAN_URL = "https://scanner.tradingview.com/indonesia/scan"
_COLUMNS = ["name", "open", "high", "low", "close", "volume"]


def _today_wib() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=7)).strftime("%Y-%m-%d")


def fetch_tv_live_details(tickers: list[str], timeout: float = 8.0) -> dict[str, dict]:
    """Return {TICKER: {"ticker", "close", "history": [bar_hari_ini]}} atau {} bila gagal."""
    symbols = sorted({str(t).upper().strip() for t in tickers if t})
    if not symbols:
        return {}
    payload = {
        "filter": [{"left": "name", "operation": "in_range", "right": symbols}],
        "options": {"lang": "en"},
        "symbols": {"query": {"types": []}, "tickers": []},
        "columns": _COLUMNS,
        "range": [0, len(symbols) + 10],
    }
    req = urllib.request.Request(
        TV_SCAN_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        print(f"[TVLive] Gagal fetch TradingView: {exc}")
        return {}

    date_str = _today_wib()
    out: dict[str, dict] = {}
    for item in res.get("data", []):
        try:
            sym = str(item["s"]).split(":")[-1].upper()
            name, o, h, l, c, v = item["d"]
            if c is None or float(c) <= 0:
                continue
            c = float(c)
            bar = {
                "date": date_str,
                "open": float(o if o is not None else c),
                "high": float(h if h is not None else c),
                "low": float(l if l is not None else c),
                "close": c,
                "volume": float(v or 0),
            }
            out[sym] = {"ticker": sym, "close": c, "history": [bar]}
        except Exception:
            continue
    return out
