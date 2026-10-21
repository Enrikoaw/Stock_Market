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


def load_env_file() -> None:
    """Memuat variabel dari file .env di root proyek ke os.environ jika belum disetel."""
    root_dir = Path(__file__).resolve().parent.parent
    possible_paths = [
        root_dir / ".env",
        Path.cwd() / ".env",
        root_dir / ".env.example",  # Fallback jika user mengedit .env.example langsung
        Path.cwd() / ".env.example",
    ]

    for p in possible_paths:
        if not p.exists():
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    if line.startswith("export "):
                        line = line[7:].strip()
                    key, val = line.split("=", 1)
                    key = key.strip()
                    # Bersihkan inline comment jika ada (misal KEY=val # komentar)
                    if "#" in val and not (val.startswith('"') or val.startswith("'")):
                        val = val.split("#", 1)[0]
                    val = val.strip().strip('"').strip("'")
                    # Abaikan teks placeholder bawaan template
                    if "your_invezgo" in val.lower() or "your_api_key" in val.lower():
                        continue
                    if key and (key not in os.environ or not os.environ[key].strip()):
                        os.environ[key] = val
        except Exception:
            pass


def load_broker_api_config() -> dict[str, Any]:
    """Memuat konfigurasi API broker dari .env atau file data/broker_api_config.json."""
    load_env_file()

    invezgo_key = ""
    for k in (
        "INVEZGO_API_KEY",
        "INVEZGO_TOKEN",
        "INVEZGO_KEY",
        "INVESTGO_API_KEY",
        "INVESTGO_TOKEN",
        "INVESTGO_KEY",
        "BROKER_API_KEY",
        "BROKER_TOKEN",
    ):
        v = os.environ.get(k, "").strip()
        if v and "your_invezgo" not in v.lower() and "your_api_key" not in v.lower():
            invezgo_key = v
            break

    cfg = {
        "provider": os.environ.get("BROKER_API_PROVIDER", "").strip().lower(),  # invezgo / stockbit / goapi / mock
        "invezgo_api_key": invezgo_key,
        "goapi_key": os.environ.get("GOAPI_KEY", "").strip(),
        "stockbit_token": os.environ.get("STOCKBIT_BEARER_TOKEN", "").strip(),
        "delay_ms": int(os.environ.get("BROKER_FETCH_DELAY_MS", "300")),
        "max_candidates": int(os.environ.get("BROKER_MAX_CANDIDATES", "30")),
    }
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    cfg.update({k: v for k, v in saved.items() if v is not None})
                    if not invezgo_key and saved.get("invezgo_api_key"):
                        cfg["invezgo_api_key"] = saved["invezgo_api_key"].strip()
        except Exception:
            pass

    # Otomatis pilih provider aktif jika belum disetel secara eksplisit
    if not cfg.get("provider"):
        if cfg.get("invezgo_api_key"):
            cfg["provider"] = "invezgo"
        elif cfg.get("stockbit_token"):
            cfg["provider"] = "stockbit"
        elif cfg.get("goapi_key"):
            cfg["provider"] = "goapi"
        else:
            cfg["provider"] = "invezgo"

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
    """Mengekstrak list buyer & seller dari berbagai format API (Invezgo, GoAPI, Stockbit, IPOT)."""
    if not payload:
        return [], []

    # 1. Format Invezgo: list langsung atau dict dengan key "data" yang bertipe list
    summary_list = None
    if isinstance(payload, list):
        summary_list = payload
    elif isinstance(payload, dict):
        d_val = payload.get("data")
        if isinstance(d_val, list):
            summary_list = d_val
        elif isinstance(payload.get("summary"), list):
            summary_list = payload["summary"]
        elif isinstance(d_val, dict) and isinstance(d_val.get("summary"), list):
            summary_list = d_val["summary"]

    if summary_list is not None:
        buyers_list = []
        sellers_list = []
        for item in summary_list:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or item.get("broker_code") or "").strip().upper()
            if len(code) != 2 or not code.isalpha():
                continue
            nv = float(item.get("net_value") or item.get("net_val") or 0.0)
            bv = float(item.get("buy_value") or 0.0)
            sv = float(item.get("sell_value") or 0.0)
            b_avg = float(item.get("buy_avg") or item.get("avg_price") or 0.0)
            s_avg = float(item.get("sell_avg") or item.get("avg_price") or 0.0)

            if nv > 0 or (nv == 0 and bv > sv):
                buyers_list.append({"code": code, "net_val": abs(nv) if nv != 0 else bv, "avg_price": b_avg, "name": item.get("name", "")})
            elif nv < 0 or (nv == 0 and sv > bv):
                sellers_list.append({"code": code, "net_val": abs(nv) if nv != 0 else sv, "avg_price": s_avg, "name": item.get("name", "")})

        buyers_list.sort(key=lambda x: x["net_val"], reverse=True)
        sellers_list.sort(key=lambda x: x["net_val"], reverse=True)
        return buyers_list, sellers_list

    # 2. Format Stockbit & GoAPI
    d = payload.get("data", payload) if isinstance(payload, dict) else payload
    bd = d.get("bandar_detector") if isinstance(d, dict) and isinstance(d.get("bandar_detector"), dict) else (d if isinstance(d, dict) else {})

    buyers = (
        bd.get("top_buyers") or
        bd.get("top_buyer") or
        bd.get("broker_buy") or
        bd.get("buyers") or
        bd.get("buy") or
        d.get("top_buyers") or
        d.get("top_buyer") or
        d.get("broker_buy") or
        d.get("buyers") or
        []
    )
    sellers = (
        bd.get("top_sellers") or
        bd.get("top_seller") or
        bd.get("broker_sell") or
        bd.get("sellers") or
        bd.get("sell") or
        d.get("top_sellers") or
        d.get("top_seller") or
        d.get("broker_sell") or
        d.get("sellers") or
        []
    )

    if not buyers and isinstance(bd.get("top3"), dict):
        buyers = bd["top3"].get("buyer") or bd["top3"].get("buyers") or []
        sellers = bd["top3"].get("seller") or bd["top3"].get("sellers") or []

    def _extract_code(item: dict) -> str:
        for k in ("broker_code", "broker", "code", "brokerCode", "b_code", "symbol"):
            c = str(item.get(k) or "").strip().upper()
            if len(c) == 2 and c.isalpha():
                return c
        return ""

    def _norm(item: dict, is_buyer: bool) -> dict:
        code = _extract_code(item)
        val = abs(float(
            item.get("net_value") or
            item.get("net_val") or
            item.get("nval") or
            (item.get("buy_value") if is_buyer else item.get("sell_value")) or
            item.get("val") or
            item.get("value") or
            0.0
        ))
        price = float(
            (item.get("buy_avg") if is_buyer else item.get("sell_avg")) or
            item.get("avg_price") or
            item.get("bavg" if is_buyer else "savg") or
            (item.get("buy_avg_price") if is_buyer else item.get("sell_avg_price")) or
            item.get("avg") or
            item.get("price") or
            0.0
        )
        return {"code": code, "net_val": val, "avg_price": price}

    norm_buyers = [_norm(b, True) for b in buyers if isinstance(b, dict) and _extract_code(b)]
    norm_sellers = [_norm(s, False) for s in sellers if isinstance(s, dict) and _extract_code(s)]
    return norm_buyers, norm_sellers


def fetch_broker_summary_invezgo(ticker: str, date_str: str, api_key: str) -> list | dict[str, Any] | None:
    """
    Mengambil data broker summary via API resmi Invezgo:
    GET https://api.invezgo.com/analysis/summary/stock/{code}?from={date_str}&to={date_str}&investor=all&market=RG
    """
    if not api_key:
        return None

    clean_key = api_key.replace("Bearer ", "").strip()
    clean_ticker = ticker.upper().strip()
    url = f"https://api.invezgo.com/analysis/summary/stock/{clean_ticker}?from={date_str}&to={date_str}&investor=all&market=RG"
    headers = {
        "Authorization": f"Bearer {clean_key}",
        "User-Agent": "SmartFlowIDX/93.0",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("data", data)
    except urllib.error.HTTPError as ex:
        print(f"[InvezgoAPI] HTTP {ex.code} fetch {clean_ticker} ({date_str}): {ex.reason}")
    except Exception as ex:
        print(f"[InvezgoAPI] Error fetch {clean_ticker}: {ex}")
    return None


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


def test_broker_connection(provider: str = "invezgo", token_or_key: str | None = None, ticker: str = "BBCA") -> dict[str, Any]:
    """Menguji koneksi ke endpoint Broker API (Invezgo / Stockbit / GoAPI) dengan 1 ticker tes."""
    from datetime import datetime, timedelta

    cfg = load_broker_api_config()
    provider_clean = (provider or cfg.get("provider", "invezgo")).strip().lower()

    if not token_or_key:
        if provider_clean == "invezgo":
            token_or_key = cfg.get("invezgo_api_key", "")
        elif provider_clean == "stockbit":
            token_or_key = cfg.get("stockbit_token", "")
        else:
            token_or_key = cfg.get("goapi_key", "")

    if not token_or_key:
        root_dir = Path(__file__).resolve().parent.parent
        env_exists = (root_dir / ".env").exists()
        example_exists = (root_dir / ".env.example").exists()
        return {
            "success": False,
            "error": (
                f"Token/API Key {provider_clean.upper()} belum terbaca atau masih teks placeholder.\n"
                f"- Status file .env: {'Ditemukan' if env_exists else 'TIDAK DITEMUKAN'}\n"
                f"- Status file .env.example: {'Ditemukan' if example_exists else 'TIDAK DITEMUKAN'}\n"
                f"Tips: Jika token dimasukkan di .env.example, salin ke .env dengan: cp .env.example .env"
            ),
        }

    dates_to_try = []
    now = datetime.now()
    for d in range(5):
        dt = now - timedelta(days=d)
        if dt.weekday() < 5:
            dates_to_try.append(dt.strftime("%Y-%m-%d"))

    raw = None
    last_err = ""
    used_date = ""

    for dt_str in dates_to_try:
        try:
            if provider_clean == "invezgo":
                raw = fetch_broker_summary_invezgo(ticker, dt_str, token_or_key)
            elif provider_clean == "stockbit":
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
            "error": last_err or f"Tidak ada data broker yang diterima untuk {ticker}. Pastikan Token/API Key {provider_clean.upper()} valid dan bursa memiliki data pada tanggal pengujian.",
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


def filter_stage1_funnel_candidates(stocks: list[dict[str, Any]], max_candidates: int = 30) -> list[dict[str, Any]]:
    """
    Stage 1 Funneling (Screening Awal Lokal Bebas Biaya API / 0 Kuota):
    Menyaring ~900 emiten bursa secara lokal untuk memilih 25 - 30 kandidat swing paling potensial
    yang layak diuji X-Ray Broker Summary di Stage 2.

    Kriteria Saringan Stage 1:
    1. Likuiditas & Keamanan: Transaksi >= Rp 1.0 Miliar, Harga >= 70, bukan papan akselerasi/khusus, fundamental & tape aman.
    2. Karakter Swing: Tidak sedang terbang pucuk (pct_change <= 5.0%), dalam area koreksi/retrace sehat atau konsolidasi.
    3. Volume Wajar: vol_ratio <= 1.80 atau ada letupan akumulasi awal.
    """
    if not stocks:
        return []

    candidates = []
    for s in stocks:
        c = float(s.get("close") or 0)
        val_b = float(s.get("value_b_idr") or (float(s.get("value_idr") or 0) / 1e9))
        sec = str(s.get("sector") or "").lower()
        if c < 70 or val_b < 1.0:
            continue
        if "pemantauan khusus" in sec or "akselerasi" in sec:
            continue

        fs = s.get("fundamental_safety")
        if isinstance(fs, dict) and fs.get("is_safe") is False:
            continue

        tq = s.get("tape_quality")
        if isinstance(tq, dict) and tq.get("is_organic") is False:
            continue

        pct = float(s.get("pct_change") or 0)
        vr = float(s.get("vol_ratio") or 1.0)
        score = int(s.get("smart_money_score") or 0)

        # Eliminasi saham yang terbang liar di pucuk
        if pct > 5.0:
            continue

        # Prioritaskan saham yang retrace sehat (-4.0% s/d +2.5%) atau konsolidasi akumulasi awal
        is_swing_pullback = (-4.0 <= pct <= 2.5) and (vr <= 1.80)
        is_early_setup = (score >= 60)

        if is_swing_pullback or is_early_setup:
            candidates.append(s)

    # Urutkan berdasarkan skor awal, likuiditas transaksi, dan kestabilan harga
    candidates.sort(
        key=lambda x: (
            int(x.get("smart_money_score") or 0),
            float(x.get("value_b_idr") or 0),
            -abs(float(x.get("pct_change") or 0))
        ),
        reverse=True
    )

    selected = candidates[:max_candidates]
    print(f"[SmartFunnel] Stage 1 Selesai: {len(selected)} kandidat swing terbaik disaring dari {len(stocks)} emiten untuk uji X-Ray Broksum.")
    return selected


def run_stage2_broker_enrichment(
    candidates: list[dict],
    date_str: str,
    cfg: dict[str, Any] | None = None,
    details_map: dict[str, Any] | None = None,
) -> list[dict]:
    """
    Stage 2 Pipeline (Uji X-Ray Broker Summary via Invezgo / API):
    Hanya memanggil API Broker Summary untuk saham potensial hasil Stage 1 Funneling (~25-30 saham).
    Sangat menghemat limit API (hanya memakan ~25-30 request dari 250 req/menit).
    """
    config = cfg or load_broker_api_config()
    provider = config.get("provider", "invezgo")
    delay_sec = max(0.1, config.get("delay_ms", 300) / 1000.0)
    max_cands = config.get("max_candidates", 30)

    filtered_cands = candidates[:max_cands]
    enriched = []

    print(f"[SmartFunnel] Memulai Stage 2 X-Ray Broksum untuk {len(filtered_cands)} saham terpilih (Provider: {provider.upper()}, Delay: {delay_sec}s)...")

    for idx, s in enumerate(filtered_cands, start=1):
        ticker = s.get("ticker", "").upper()
        if not ticker:
            continue

        raw_data = None
        # Coba date_str, jika kosong coba tanggal hari kerja terbaru
        dates_to_try = [date_str] if date_str else []
        from datetime import datetime, timedelta
        now = datetime.now()
        for d in range(5):
            dt = (now - timedelta(days=d)).strftime("%Y-%m-%d")
            if dt not in dates_to_try:
                dates_to_try.append(dt)

        for dt_candidate in dates_to_try:
            try:
                if provider == "invezgo" and config.get("invezgo_api_key"):
                    raw_data = fetch_broker_summary_invezgo(ticker, dt_candidate, config["invezgo_api_key"])
                elif provider == "goapi" and config.get("goapi_key"):
                    raw_data = fetch_broker_summary_goapi(ticker, dt_candidate, config["goapi_key"])
                elif provider == "stockbit" and config.get("stockbit_token"):
                    raw_data = fetch_broker_summary_stockbit(ticker, dt_candidate, config["stockbit_token"])
                if raw_data:
                    break
            except Exception as ex:
                print(f"[SmartFunnel] Warning fetch {ticker} on {dt_candidate}: {ex}")

        if raw_data:
            top_buyers, top_sellers = extract_brokers_from_payload(raw_data)
            metrics = analyze_broker_summary(top_buyers, top_sellers)
            s["broker_analysis"] = metrics
            s["has_broker_summary"] = True
            s["has_real_broker_summary"] = bool(metrics.get("top_buyers_list") or metrics.get("top_sellers_list"))
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
                print(f"[SmartFunnel] X-Ray Warning [{idx}/{len(filtered_cands)}]: {ticker} terdeteksi RETAIL TRAP (Buyer: {s['top_buyers']}, Seller: {s['top_sellers']})! Dieliminasi dari rekomendasi.")
            elif metrics.get("status") == "BIG_ACCUMULATION":
                s["trigger_type"] = "BIG_ACCUMULATION"
                s["trigger_label"] = "Akumulasi Broker"
                print(f"[SmartFunnel] X-Ray Lolos [{idx}/{len(filtered_cands)}]: {ticker} AKUMULASI BESAR SMART MONEY (BDR: +{metrics['bdr']}%, Buyer: {s['top_buyers']}, Avg: {metrics.get('bandar_avg')}).")
            else:
                print(f"[SmartFunnel] X-Ray Selesai [{idx}/{len(filtered_cands)}]: {ticker} (BDR: {metrics['bdr']}%, Buyer: {s['top_buyers']}, Seller: {s['top_sellers']}).")

            if metrics.get("bandar_avg") and s.get("trading_plan"):
                s["trading_plan"]["bandar_avg_buy"] = metrics["bandar_avg"]
                b_avg = float(metrics["bandar_avg"])
                c_val = float(s.get("close") or 0)
                if 0 < c_val * 0.915 <= b_avg < c_val * 1.01:
                    rev_ep = int(round(b_avg))
                    s["trading_plan"]["entry_price"] = rev_ep
                    s["trading_plan"]["entry_low"] = rev_ep
                    s["trading_plan"]["entry_high"] = rev_ep
                    s["trading_plan"]["support_label"] = "Support Avg Bandar"

            # Sinkronisasi ke details_map
            if details_map and ticker in details_map:
                detail = details_map[ticker]
                detail["broker_analysis"] = metrics
                detail["has_broker_summary"] = True
                detail["has_real_broker_summary"] = s["has_real_broker_summary"]
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
                    if "entry_price" in s.get("trading_plan", {}):
                        detail["trading_plan"]["entry_price"] = s["trading_plan"]["entry_price"]
                        detail["trading_plan"]["entry_low"] = s["trading_plan"]["entry_low"]
                        detail["trading_plan"]["entry_high"] = s["trading_plan"]["entry_high"]
                        detail["trading_plan"]["support_label"] = s["trading_plan"].get("support_label", "Support Avg Bandar")
        else:
            s["has_broker_summary"] = False

        enriched.append(s)
        time.sleep(delay_sec)

    print(f"[SmartFunnel] Stage 2 Selesai. {len(enriched)} saham berhasil diperkaya dengan data X-Ray Broker Summary.")
    return enriched


def enrich_candidates_and_watchlist(
    analysis: dict[str, Any],
    date_str: str,
    tracker: Any | None = None,
    cfg: dict[str, Any] | None = None,
    max_total_candidates: int = 40,
) -> list[dict]:
    """
    Funneling Terpadu Broker Summary (Pilihan Hari Ini + Watchlist + Top Screener):
    1. Pastikan seluruh 'Pilihan Saham Hari Ini' (today_candidates) WAJIB diperkaya broker summary.
    2. Pastikan seluruh saham aktif di 'Watchlist / Pantauan' (WATCHLIST + RUNNING) WAJIB diperkaya broker summary.
    3. Sisa kuota hingga max_total_candidates diisi oleh kandidat terbaik dari Stage 1 Funneling.
    
    Hasil:
    - Zero wasted API calls.
    - Semua saham yang dipantau user & rekomendasi hari ini 100% memiliki data broker summary terkini.
    - Sinkronisasi otomatis ke analysis['stocks'] dan analysis['details'].
    """
    if not analysis or "stocks" not in analysis:
        return []

    config = cfg or load_broker_api_config()
    has_api = bool(config.get("invezgo_api_key") or config.get("goapi_key") or config.get("stockbit_token"))
    if not has_api:
        print("[SmartFunnel] Token Broker API belum diatur. Melewati enrichment broker summary.")
        return []

    details_map = analysis.get("details", {})
    all_stocks = analysis.get("stocks", [])
    stock_by_ticker = {str(s.get("ticker", "")).upper(): s for s in all_stocks if s.get("ticker")}

    target_tickers: list[str] = []
    seen: set[str] = set()

    def _add(t: Any) -> None:
        clean_t = str(t or "").upper().strip()
        if clean_t and clean_t not in seen:
            seen.add(clean_t)
            target_tickers.append(clean_t)

    # 1. Pilihan Saham Hari Ini (PRIORITAS 1)
    for c in analysis.get("today_candidates", []):
        _add(c.get("ticker", ""))

    if tracker and hasattr(tracker, "get_today_candidates"):
        try:
            db_cands = tracker.get_today_candidates(date_str)
            for dc in db_cands:
                _add(dc.get("ticker", ""))
        except Exception:
            pass

    # 2. Watchlist & Sinyal Aktif di Pantauan (PRIORITAS 2)
    if tracker and hasattr(tracker, "get_active_tickers"):
        try:
            active_wl = tracker.get_active_tickers()
            for wt in active_wl:
                _add(wt)
        except Exception as exc:
            print(f"[SmartFunnel] Warning: Gagal mengambil active watchlist tickers: {exc}")

    # 3. Kandidat Swing Stage 1 dari Screener (PRIORITAS 3 - SISA KUOTA)
    stage1 = filter_stage1_funnel_candidates(all_stocks, max_candidates=max_total_candidates)
    for sc in stage1:
        if len(target_tickers) >= max_total_candidates:
            break
        _add(sc.get("ticker", ""))

    # Kumpulkan objek stock yang cocok
    target_stocks = []
    for t in target_tickers:
        if t in stock_by_ticker:
            target_stocks.append(stock_by_ticker[t])
        elif t in details_map:
            target_stocks.append(details_map[t])

    print(f"[SmartFunnel] Terpilih total {len(target_stocks)} saham untuk X-Ray Broksum ({len(seen)} unik: Today Candidates + Watchlist + Stage 1).")

    enriched = run_stage2_broker_enrichment(
        target_stocks,
        date_str=date_str,
        cfg=config,
        details_map=details_map,
    )

    # Sinkronisasi balik ke today_candidates jika ada
    if "today_candidates" in analysis and analysis["today_candidates"]:
        for cand in analysis["today_candidates"]:
            t_cand = str(cand.get("ticker", "")).upper()
            if t_cand in details_map:
                d_item = details_map[t_cand]
                for fld in (
                    "broker_analysis", "has_broker_summary", "has_real_broker_summary",
                    "bdr_pct", "top_buyers_list", "top_sellers_list", "top_buyers", "top_sellers",
                    "bandar_avg_buy", "diff_bandar_avg_pct", "retail_trap", "trigger_type", "trigger_label"
                ):
                    if fld in d_item:
                        cand[fld] = d_item[fld]

    return enriched


def enrich_single_stock_broker(s: dict, date_str: str, cfg: dict[str, Any] | None = None) -> dict:
    """Mengambil dan memperkaya data broker summary untuk 1 saham secara on-demand."""
    from datetime import datetime, timedelta

    config = cfg or load_broker_api_config()
    provider = config.get("provider", "invezgo")
    ticker = str(s.get("ticker", "")).upper().strip()
    if not ticker:
        return s

    raw_data = None
    dates_to_try = [date_str] if date_str else []
    now = datetime.now()
    for d in range(7):
        dt = (now - timedelta(days=d)).strftime("%Y-%m-%d")
        if dt not in dates_to_try:
            dates_to_try.append(dt)

    for dt_candidate in dates_to_try:
        try:
            if provider == "invezgo" and config.get("invezgo_api_key"):
                raw_data = fetch_broker_summary_invezgo(ticker, dt_candidate, config["invezgo_api_key"])
            elif provider == "stockbit" and config.get("stockbit_token"):
                raw_data = fetch_broker_summary_stockbit(ticker, dt_candidate, config["stockbit_token"])
            elif provider == "goapi" and config.get("goapi_key"):
                raw_data = fetch_broker_summary_goapi(ticker, dt_candidate, config["goapi_key"])
            if raw_data:
                break
        except Exception as ex:
            print(f"[BrokerOnDemand] Error fetch {ticker} on {dt_candidate}: {ex}")

    if raw_data:
        top_buyers, top_sellers = extract_brokers_from_payload(raw_data)
        metrics = analyze_broker_summary(top_buyers, top_sellers)

        s["broker_analysis"] = metrics
        s["has_broker_summary"] = True
        s["has_real_broker_summary"] = bool(metrics.get("top_buyers_list") or metrics.get("top_sellers_list"))
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
            s["trading_plan"]["bandar_avg_buy"] = metrics["bandar_avg"]
            b_avg = float(metrics["bandar_avg"])
            c_val = float(s.get("close") or 0)
            if 0 < c_val * 0.915 <= b_avg < c_val * 0.992:
                rev_ep = int(round(b_avg))
                s["trading_plan"]["entry_price"] = rev_ep
                s["trading_plan"]["entry_low"] = rev_ep
                s["trading_plan"]["entry_high"] = rev_ep
                s["trading_plan"]["support_label"] = "Support Avg Bandar"

    return s
