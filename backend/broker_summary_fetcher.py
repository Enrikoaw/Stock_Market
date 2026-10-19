"""
SmartFlow IDX - Broker Summary Fetcher & Bandarmology Quant Engine
Mengambil data broker summary real-time/EOD via API (GoAPI / Stockbit / IPOT)
dan mengkuantifikasikannya menjadi:
1. BDR (Bandar Detector Ratio / Top 3 Concentration)
2. Filter Broker Ritel vs Institusi (Smart Money Check)
3. Bandar Weighted Average Price (Buy Limit Optimizer)
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# Klasifikasi Broker Bursa Efek Indonesia (IDX)
RETAIL_BROKERS = {"YP", "PD", "XC", "XL", "KK", "NI", "SQ", "BQ"}
INST_FOREIGN_BROKERS = {"AK", "BK", "ZP", "KZ", "RX", "YU", "CC", "CS", "MG", "DX", "LG", "OD"}

CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "broker_api_config.json"


def load_broker_api_config() -> dict[str, Any]:
    """Memuat konfigurasi API broker dari file data/broker_api_config.json atau environment variables."""
    cfg = {
        "provider": os.environ.get("BROKER_API_PROVIDER", "goapi").strip().lower(),  # goapi / stockbit / mock
        "goapi_key": os.environ.get("GOAPI_KEY", "").strip(),
        "stockbit_token": os.environ.get("STOCKBIT_BEARER_TOKEN", "").strip(),
        "delay_ms": int(os.environ.get("BROKER_FETCH_DELAY_MS", "1000")),
        "max_candidates": int(os.environ.get("BROKER_MAX_CANDIDATES", "60")),
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    cfg.update({k: v for k, v in saved.items() if v is not None})
        except Exception:
            pass
    return cfg


def save_broker_api_config(cfg: dict[str, Any]) -> bool:
    """Menyimpan konfigurasi API broker ke data/broker_api_config.json."""
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        return True
    except Exception:
        return False


def analyze_broker_summary(top_buyers: list[dict], top_sellers: list[dict]) -> dict[str, Any]:
    """
    Rumus Kuantifikasi Broker Summary ke Sistem Skor:
    A. Rasio Dominasi Top 3 (BDR / Bandar Detector Ratio)
    B. Filter Broker Ritel vs Institusi (Smart Money Check)
    C. Harga Rata-Rata Bandar (Weighted Average Top 3 Buyer)
    """
    if not top_buyers or not top_sellers:
        return {
            "bdr": 0.0,
            "score_modifier": 0,
            "status": "NEUTRAL",
            "bandar_avg": None,
            "top_buyer_code": "-",
            "top_seller_code": "-",
            "top_buyers_list": [],
            "top_sellers_list": [],
            "retail_trap": False,
        }

    buy3 = top_buyers[:3]
    sell3 = top_sellers[:3]

    sum_buy3_val = sum(float(b.get("net_val", b.get("val", 0))) for b in buy3)
    sum_sell3_val = sum(abs(float(s.get("net_val", s.get("val", 0)))) for s in sell3)
    total_val = sum_buy3_val + sum_sell3_val

    # 1. Rasio Dominasi Top 3 (BDR: -100% s/d +100%)
    if total_val > 0:
        bdr = round(((sum_buy3_val - sum_sell3_val) / total_val) * 100.0, 2)
    else:
        bdr = 0.0

    # 2. Harga Rata-Rata Top 3 Buyer (Volume Weighted Average Price)
    weighted_buy_sum = sum(float(b.get("net_val", b.get("val", 0))) * float(b.get("avg_price", b.get("price", 0))) for b in buy3)
    bandar_avg = int(round(weighted_buy_sum / sum_buy3_val)) if sum_buy3_val > 0 else None

    # 3. Smart Money Check: Dominasi Ritel vs Institusi
    buyer_codes = [str(b.get("code", "")).upper() for b in buy3 if b.get("code")]
    seller_codes = [str(s.get("code", "")).upper() for s in sell3 if s.get("code")]

    retail_buying_count = sum(1 for c in buyer_codes if c in RETAIL_BROKERS)
    inst_selling_count = sum(1 for c in seller_codes if c in INST_FOREIGN_BROKERS)

    score_modifier = 0
    status = "NEUTRAL"
    retail_trap = False

    # Logika Penilaian
    if retail_buying_count >= 2 and inst_selling_count >= 1:
        # Bahaya: Ritel FOMO menampung buangan sekuritas institusi/asing
        score_modifier = -20
        status = "DISTRIBUTION_WARNING"
        retail_trap = True
    elif bdr >= 25.0:
        score_modifier = 15
        status = "BIG_ACCUMULATION"
    elif bdr >= 10.0:
        score_modifier = 8
        status = "NORMAL_ACCUMULATION"
    elif bdr <= -15.0:
        score_modifier = -20
        status = "DISTRIBUTION_WARNING"

    return {
        "bdr": bdr,
        "score_modifier": score_modifier,
        "status": status,
        "bandar_avg": bandar_avg,
        "top_buyer_code": buyer_codes[0] if buyer_codes else "-",
        "top_seller_code": seller_codes[0] if seller_codes else "-",
        "top_buyers_list": buyer_codes,
        "top_sellers_list": seller_codes,
        "retail_trap": retail_trap,
        "sum_buy3_val": sum_buy3_val,
        "sum_sell3_val": sum_sell3_val,
    }


def extract_brokers_from_payload(payload: Any) -> tuple[list[dict], list[dict]]:
    """Mengekstrak list buyer & seller dari berbagai format API (GoAPI, Stockbit, IPOT)."""
    if not isinstance(payload, dict):
        return [], []

    d = payload.get("data", payload) if isinstance(payload.get("data"), dict) else payload

    # Format Stockbit marketdetectors
    if isinstance(d, dict) and "bandar_detector" in d and isinstance(d["bandar_detector"], dict):
        d = d["bandar_detector"]

    buyers = (
        d.get("top_buyers") or
        d.get("broker_buy") or
        d.get("buyers") or
        d.get("buy") or
        []
    )
    sellers = (
        d.get("top_sellers") or
        d.get("broker_sell") or
        d.get("sellers") or
        d.get("sell") or
        []
    )

    def _norm(item: dict, is_buyer: bool) -> dict:
        code = str(item.get("broker_code") or item.get("code") or item.get("broker") or "").upper().strip()
        val = abs(float(
            item.get("net_val") or
            item.get("nval") or
            (item.get("buy_value") if is_buyer else item.get("sell_value")) or
            item.get("val") or
            item.get("value") or
            0.0
        ))
        price = float(
            item.get("avg_price") or
            item.get("bavg" if is_buyer else "savg") or
            (item.get("buy_avg_price") if is_buyer else item.get("sell_avg_price")) or
            item.get("avg") or
            item.get("price") or
            0.0
        )
        return {"code": code, "net_val": val, "avg_price": price}

    norm_buyers = [_norm(b, True) for b in buyers if isinstance(b, dict) and (b.get("broker_code") or b.get("code") or b.get("broker"))]
    norm_sellers = [_norm(s, False) for s in sellers if isinstance(s, dict) and (s.get("broker_code") or s.get("code") or s.get("broker"))]
    return norm_buyers, norm_sellers


def fetch_broker_summary_goapi(ticker: str, date_str: str, api_key: str) -> dict[str, Any] | None:
    """Mengambil data broker summary via API resmi GoAPI.io."""
    if not api_key:
        return None
    url = f"https://api.goapi.io/stock/idx/{ticker.upper()}/broker_summary?from={date_str}&to={date_str}&api_key={api_key}"
    req = urllib.request.Request(url, headers={"User-Agent": "SmartFlowIDX/68.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("status") == "success" and "data" in data:
                return data["data"]
    except Exception as ex:
        print(f"[BrokerGoAPI] Error fetch {ticker}: {ex}")
    return None


def fetch_broker_summary_stockbit(ticker: str, date_str: str, bearer_token: str) -> dict[str, Any] | None:
    """Mengambil data broker summary via endpoint Exodus Stockbit (membutuhkan Bearer Token)."""
    if not bearer_token:
        return None
    url = f"https://exodus.stockbit.com/marketdetectors/{ticker.upper()}?from={date_str}&to={date_str}&transaction_type=TRANSACTION_TYPE_NET"
    clean_token = bearer_token.replace("Bearer ", "").strip()
    headers = {
        "Authorization": f"Bearer {clean_token}",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as ex:
        print(f"[BrokerStockbit] Error fetch {ticker}: {ex}")
    return None


def test_broker_connection(provider: str, token_or_key: str, ticker: str = "BBCA") -> dict[str, Any]:
    """Menguji koneksi ke endpoint Broker API (Stockbit / GoAPI) dengan 1 ticker tes."""
    from datetime import datetime, timedelta

    dates_to_try = []
    now = datetime.now()
    for d in range(5):
        dt = now - timedelta(days=d)
        if dt.weekday() < 5:
            dates_to_try.append(dt.strftime("%Y-%m-%d"))

    provider_clean = (provider or "stockbit").strip().lower()
    raw = None
    last_err = ""
    used_date = ""

    for dt_str in dates_to_try:
        try:
            if provider_clean == "stockbit":
                raw = fetch_broker_summary_stockbit(ticker, dt_str, token_or_key)
            else:
                raw = fetch_broker_summary_goapi(ticker, dt_str, token_or_key)
            if raw:
                used_date = dt_str
                break
        except Exception as ex:
            last_err = str(ex)

    if not raw:
        return {
            "success": False,
            "error": last_err or f"Tidak ada data broker yang diterima untuk {ticker}. Pastikan Token/API Key valid dan belum kedaluwarsa.",
        }

    buyers, sellers = extract_brokers_from_payload(raw)
    metrics = analyze_broker_summary(buyers, sellers)
    return {
        "success": True,
        "ticker": ticker.upper(),
        "date": used_date,
        "provider": provider_clean,
        "metrics": metrics,
        "top_buyers": [b.get("code") for b in buyers[:3]],
        "top_sellers": [s.get("code") for s in sellers[:3]],
    }


def run_stage2_broker_enrichment(
    candidates: list[dict],
    date_str: str,
    cfg: dict[str, Any] | None = None,
    details_map: dict[str, Any] | None = None,
) -> list[dict]:
    """
    Stage 2 Pipeline:
    Hanya memanggil API Broker Summary untuk saham potensial hasil Stage 1 (Skor >= 50 & Nilai Transaksi >= 1M).
    Menerapkan jeda (delay) antar-request agar aman dari rate limit/blokir.
    """
    config = cfg or load_broker_api_config()
    provider = config.get("provider", "stockbit")
    delay_sec = max(0.2, config.get("delay_ms", 1000) / 1000.0)
    max_cands = config.get("max_candidates", 60)

    filtered_cands = candidates[:max_cands]
    enriched = []

    print(f"[BrokerPipeline] Memulai Stage 2 Fetcher untuk {len(filtered_cands)} saham terpilih (Provider: {provider})...")

    for idx, s in enumerate(filtered_cands, start=1):
        ticker = s.get("ticker", "").upper()
        if not ticker:
            continue

        raw_data = None
        if provider == "goapi" and config.get("goapi_key"):
            raw_data = fetch_broker_summary_goapi(ticker, date_str, config["goapi_key"])
        elif provider == "stockbit" and config.get("stockbit_token"):
            raw_data = fetch_broker_summary_stockbit(ticker, date_str, config["stockbit_token"])

        if raw_data:
            top_buyers, top_sellers = extract_brokers_from_payload(raw_data)
            metrics = analyze_broker_summary(top_buyers, top_sellers)
            s["broker_analysis"] = metrics
            s["has_broker_summary"] = True
            s["bdr_pct"] = metrics["bdr"]
            s["top_buyers_list"] = metrics.get("top_buyers_list", [b["code"] for b in top_buyers[:3]])
            s["top_sellers_list"] = metrics.get("top_sellers_list", [sel["code"] for sel in top_sellers[:3]])
            s["top_buyers"] = ", ".join(s["top_buyers_list"])
            s["top_sellers"] = ", ".join(s["top_sellers_list"])

            if metrics.get("bandar_avg"):
                s["bandar_avg_buy"] = metrics["bandar_avg"]
                if s.get("close") and s["close"] > 0:
                    s["diff_bandar_avg_pct"] = round(((s["close"] - s["bandar_avg_buy"]) / s["bandar_avg_buy"]) * 100.0, 2)

            if metrics.get("score_modifier"):
                s["smart_money_score"] = min(100, max(5, int(s.get("smart_money_score", 50) + metrics["score_modifier"])))

            if metrics.get("retail_trap"):
                s["retail_trap"] = True
                s["trigger_type"] = "DISTRIBUTION_WARNING"
                s["trigger_label"] = "Distribusi (Ritel Trap)"

            if metrics.get("bandar_avg") and s.get("trading_plan"):
                orig_entry = s["trading_plan"].get("entry_high", s.get("close", 0))
                s["trading_plan"]["bandar_avg_buy"] = metrics["bandar_avg"]
                s["trading_plan"]["entry_high"] = min(orig_entry, metrics["bandar_avg"])

            # Sinkronisasi ke details_map
            if details_map and ticker in details_map:
                detail = details_map[ticker]
                detail["broker_analysis"] = metrics
                detail["has_broker_summary"] = True
                detail["bdr_pct"] = s["bdr_pct"]
                detail["top_buyers_list"] = s["top_buyers_list"]
                detail["top_sellers_list"] = s["top_sellers_list"]
                detail["top_buyers"] = s["top_buyers"]
                detail["top_sellers"] = s["top_sellers"]
                if metrics.get("bandar_avg"):
                    detail["bandar_avg_buy"] = metrics["bandar_avg"]
                    if "diff_bandar_avg_pct" in s:
                        detail["diff_bandar_avg_pct"] = s["diff_bandar_avg_pct"]
                if metrics.get("score_modifier"):
                    detail["smart_money_score"] = s["smart_money_score"]
                if metrics.get("retail_trap"):
                    detail["retail_trap"] = True
                    detail["trigger_type"] = "DISTRIBUTION_WARNING"
                    detail["trigger_label"] = "Distribusi (Ritel Trap)"
                if metrics.get("bandar_avg") and detail.get("trading_plan"):
                    detail["trading_plan"]["bandar_avg_buy"] = metrics["bandar_avg"]
                    detail["trading_plan"]["entry_high"] = min(detail["trading_plan"].get("entry_high", detail.get("close", 0)), metrics["bandar_avg"])
        else:
            s["has_broker_summary"] = False

        enriched.append(s)
        time.sleep(delay_sec)

    print(f"[BrokerPipeline] Stage 2 Selesai. {len(enriched)} saham berhasil diperkaya dengan data Broker Summary.")
    return enriched
