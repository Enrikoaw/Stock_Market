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
from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Any

try:
    from backend.screener_engine import _round_idx_tick
except ImportError:
    from screener_engine import _round_idx_tick

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
        Path("/home/ubuntu/Stock_Market/.env"),
        Path("/home/ubuntu/Stock_Market/backend/.env"),
        Path("/root/Stock_Market/.env"),
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
                    if val.startswith("Bearer "):
                        val = val[7:].strip()
                    # Abaikan teks placeholder bawaan template
                    if "your_invezgo" in val.lower() or "your_api_key" in val.lower():
                        continue
                    if not val:
                        continue

                    # Deteksi otomatis token Invezgo (format resmi awalan invz_ atau nama variabel varian)
                    k_upper = key.upper()
                    if val.startswith("invz_") or any(x in k_upper for x in ("INVEZGO", "INVESTGO", "NINVESTGO", "NINVEST", "BROKSUM")):
                        os.environ["INVEZGO_API_KEY"] = val
                        os.environ["BROKER_API_PROVIDER"] = "invezgo"

                    # Selalu sinkronkan ke os.environ
                    os.environ[key] = val
        except Exception as e:
            print(f"[EnvLoader] Warning membaca {p}: {e}")


def load_broker_api_config() -> dict[str, Any]:
    """Memuat konfigurasi API broker dari .env atau file data/broker_api_config.json."""
    load_env_file()

    invezgo_key = ""
    for k in (
        "INVEZGO_API_KEY",
        "INVEZGO_TOKEN",
        "INVEZGO_KEY",
        "NINVESTGO_API_KEY",
        "NINVESTGO_TOKEN",
        "NINVESTGO_KEY",
        "NINVEST_API_KEY",
        "INVESTGO_API_KEY",
        "INVESTGO_TOKEN",
        "INVESTGO_KEY",
        "BROKER_API_KEY",
        "BROKER_TOKEN",
        "BROKSUM_API_KEY",
        "BROKSUM_TOKEN",
        "INVEZGO_SECRET",
        "INVESTGO_SECRET",
    ):
        v = os.environ.get(k, "").strip().strip('"').strip("'")
        if v and "your_invezgo" not in v.lower() and "your_api_key" not in v.lower():
            invezgo_key = v
            break

    # Jika belum ditemukan, periksa apakah ada environment variable yang nilainya berawalan invz_
    if not invezgo_key:
        for k, v in os.environ.items():
            clean_v = str(v).strip().strip('"').strip("'")
            if clean_v.startswith("invz_"):
                invezgo_key = clean_v
                break

    provider = os.environ.get("BROKER_API_PROVIDER", "").strip().lower()
    if invezgo_key:
        provider = "invezgo"

    cfg = {
        "provider": provider or "invezgo",  # invezgo / stockbit / goapi / mock
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
                    if invezgo_key:
                        cfg["invezgo_api_key"] = invezgo_key
                        cfg["provider"] = "invezgo"
        except Exception:
            pass

    # Otomatis pastikan invezgo aktif jika API key tersedia
    if cfg.get("invezgo_api_key"):
        cfg["provider"] = "invezgo"
    elif not cfg.get("provider"):
        if cfg.get("stockbit_token"):
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


SYNC_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "broker_sync_state.json"

# Daftar Hari Libur Resmi Bursa Efek Indonesia (BEI / IDX) 2025 - 2027
IDX_HOLIDAYS: set[str] = {
    # 2025
    "2025-01-01", "2025-01-27", "2025-01-28", "2025-01-29", "2025-03-28", "2025-03-31",
    "2025-04-01", "2025-04-02", "2025-04-03", "2025-04-04", "2025-04-07", "2025-04-18",
    "2025-05-01", "2025-05-12", "2025-05-29", "2025-05-30", "2025-06-06", "2025-06-09",
    "2025-06-27", "2025-08-18", "2025-09-05", "2025-12-24", "2025-12-25", "2025-12-26", "2025-12-31",
    # 2026
    "2026-01-01", "2026-01-16", "2026-02-17", "2026-03-19", "2026-03-20", "2026-03-23",
    "2026-03-24", "2026-03-25", "2026-04-03", "2026-05-01", "2026-05-14", "2026-05-27",
    "2026-05-28", "2026-06-01", "2026-06-16", "2026-07-16", "2026-08-17", "2026-08-25",
    "2026-12-24", "2026-12-25", "2026-12-31",
    # 2027
    "2027-01-01", "2027-02-08", "2027-02-09", "2027-03-09", "2027-03-10", "2027-03-26",
    "2027-04-09", "2027-05-03", "2027-05-06", "2027-05-17", "2027-05-20", "2027-06-01",
    "2027-08-17", "2027-12-24", "2027-12-25", "2027-12-31",
}


def get_now_wib() -> datetime:
    """Mengembalikan waktu saat ini dalam zona waktu Jakarta (WIB / UTC+7)."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Jakarta"))
    except Exception:
        from datetime import timezone, timedelta
        return datetime.now(timezone(timedelta(hours=7)))


def load_broker_sync_state() -> dict[str, Any]:
    """Memuat histori sinkronisasi broker summary (Sesi 1 & Sesi 2) dari file data/broker_sync_state.json."""
    if SYNC_STATE_PATH.exists():
        try:
            with open(SYNC_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
    return {
        "sesi1_last_date": None,
        "sesi1_last_ts": None,
        "sesi2_last_date": None,
        "sesi2_last_ts": None,
        "daily_calls_count": {},
    }


MAX_DAILY_BROKSUM_REQUESTS = 70  # Kuota hard cap: maks 35 saham x 2 sesi = 70 request/hari


def get_today_broker_call_count(date_str: str | None = None) -> int:
    dt = date_str or get_now_wib().strftime("%Y-%m-%d")
    st = load_broker_sync_state()
    counts = st.get("daily_calls_count", {})
    return int(counts.get(dt, 0))


def increment_broker_call_count(date_str: str | None = None) -> int:
    dt = date_str or get_now_wib().strftime("%Y-%m-%d")
    st = load_broker_sync_state()
    counts = st.setdefault("daily_calls_count", {})
    counts[dt] = int(counts.get(dt, 0)) + 1
    if len(counts) > 14:
        sorted_keys = sorted(counts.keys())
        for k in sorted_keys[:-14]:
            del counts[k]
    save_broker_sync_state(st)
    return counts[dt]


def save_broker_sync_state(state: dict[str, Any]) -> bool:
    """Menyimpan histori sinkronisasi broker summary ke data/broker_sync_state.json."""
    try:
        SYNC_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SYNC_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        return True
    except Exception as exc:
        print(f"[BrokerSyncState] Gagal menyimpan sync state: {exc}")
        return False


def record_broker_sync_done(session_type: str, date_str: str) -> None:
    """Mencatat sesi (sesi1 / sesi2) telah berhasil disinkronisasi ke data/broker_sync_state.json."""
    st = load_broker_sync_state()
    now_str = get_now_wib().strftime("%Y-%m-%d %H:%M:%S")
    if session_type == "sesi1":
        st["sesi1_last_date"] = str(date_str)
        st["sesi1_last_ts"] = now_str
    elif session_type == "sesi2":
        st["sesi2_last_date"] = str(date_str)
        st["sesi2_last_ts"] = now_str
    save_broker_sync_state(st)


def can_run_broker_sync_now(now_dt: datetime | None = None) -> tuple[bool, str, str | None]:
    """
    Evaluasi Aturan Ketat Penarikan Broker Summary Invezgo (Maksimal 2x Sehari):
    1. Sesi 1 Selesai di Jam Bursa:
       - Jumat: 11:30 WIB s/d 13:45 WIB
       - Senin - Kamis: 12:00 WIB s/d 13:15 WIB
       - Hanya boleh 1x sehari (jika belum pernah dijalankan untuk tanggal hari ini).
    2. Sesi 2 Selesai Sekitar Jam 6 Sore WIB:
       - Senin - Jumat: 18:00 WIB s/d 22:00 WIB
       - Hanya boleh 1x sehari (jika belum pernah dijalankan untuk tanggal hari ini).
    3. Di luar kedua jendela ini: DILARANG memanggil API Invezgo untuk proteksi kuota token.

    Returns:
        (is_allowed: bool, reason_message: str, session_type: Optional[str] ['sesi1', 'sesi2', or None])
    """
    now = now_dt or get_now_wib()
    today_str = now.strftime("%Y-%m-%d")

    # Cek Hari Bursa (Senin - Jumat)
    if now.weekday() >= 5:
        return False, "Hari libur akhir pekan (Sabtu/Minggu). Penarikan broksum ditiadakan.", None

    if today_str in IDX_HOLIDAYS:
        return False, f"Hari libur resmi bursa BEI ({today_str}). Penarikan broksum ditiadakan.", None

    cur_time = now.time()
    is_jumat = (now.weekday() == 4)
    st = load_broker_sync_state()

    # Cek Hard Cap Harian: Jika hari ini sudah mencapai 70 request, blokir total!
    calls_today = get_today_broker_call_count(today_str)
    if calls_today >= MAX_DAILY_BROKSUM_REQUESTS:
        return (
            False,
            f"Batas Hard Cap harian ({calls_today}/{MAX_DAILY_BROKSUM_REQUESTS} request) untuk {today_str} sudah tercapai. Penarikan diblokir total demi melindungi kuota bulanan.",
            None,
        )

    # Jendela Waktu Sesi 1:
    sesi1_start = dtime(11, 30) if is_jumat else dtime(12, 0)
    sesi1_end = dtime(13, 45) if is_jumat else dtime(13, 15)

    # Jendela Waktu Sesi 2 (sekitar jam 6 sore WIB):
    sesi2_start = dtime(18, 0)
    sesi2_end = dtime(22, 0)

    # 1. Evaluasi Jendela Sesi 1
    if sesi1_start <= cur_time <= sesi1_end:
        if st.get("sesi1_last_date") == today_str:
            return (
                False,
                f"Broksum Sesi 1 sudah berhasil diambil hari ini ({today_str} pk {st.get('sesi1_last_ts', '-')}). Jadwal berikutnya: Pasca Sesi 2 jam 18:00 WIB.",
                "sesi1",
            )
        return True, f"Jadwal Penarikan 1/2: Pasca Sesi 1 Bursa ({today_str})", "sesi1"

    # 2. Evaluasi Jendela Sesi 2 (Jam 18:00 WIB)
    if sesi2_start <= cur_time <= sesi2_end:
        if st.get("sesi2_last_date") == today_str:
            return (
                False,
                f"Broksum Sesi 2 sudah berhasil diambil hari ini ({today_str} pk {st.get('sesi2_last_ts', '-')}). Kuota harian 2x selesai.",
                "sesi2",
            )
        return True, f"Jadwal Penarikan 2/2: Pasca Sesi 2 Bursa Sekitar Jam 6 Sore WIB ({today_str})", "sesi2"

    # 3. Di luar jadwal
    if cur_time < sesi1_start:
        return (
            False,
            f"Bursa masih berjalan di Sesi 1 ({cur_time.strftime('%H:%M')} WIB). Penarikan Broksum Invezgo dijadwalkan tepat setelah Sesi 1 selesai ({sesi1_start.strftime('%H:%M')} WIB).",
            None,
        )
    elif cur_time < sesi2_start:
        return (
            False,
            f"Bursa Sesi 2 / Sore ({cur_time.strftime('%H:%M')} WIB). Penarikan Broksum Invezgo dijadwalkan sekitar jam 6 sore WIB ({sesi2_start.strftime('%H:%M')} WIB) saat data resmi IDX diterbitkan Invezgo.",
            None,
        )
    else:
        return (
            False,
            f"Melewati jendela penarikan harian broksum ({cur_time.strftime('%H:%M')} WIB).",
            None,
        )


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

    # 4. Siapa yang menampung barang (akumulasi 3 hari bursa): Smart Money / Ritel / Campuran
    inst_buying_count = sum(1 for c in buyer_codes if c in INST_FOREIGN_BROKERS)
    if retail_trap or retail_buying_count >= 2:
        holder_type = "RETAIL"
    elif inst_buying_count >= 1 and bdr >= 10.0:
        holder_type = "SMART_MONEY"
    else:
        holder_type = "MIXED"

    return {
        "holder_type": holder_type,
        "lookback_days": BROKSUM_LOOKBACK_DAYS,
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


BROKSUM_LOOKBACK_DAYS = 3  # Jendela akumulasi broksum: 3 hari bursa terakhir (termasuk hari target)


def broksum_range_start(date_str: str, n_days: int = BROKSUM_LOOKBACK_DAYS) -> str:
    """Tanggal awal rentang n hari bursa (Senin-Jumat, di luar libur BEI) yang berakhir di date_str."""
    try:
        from datetime import timedelta
        cur = datetime.strptime(date_str, "%Y-%m-%d")
        counted = 1
        while counted < max(1, n_days):
            cur -= timedelta(days=1)
            if cur.weekday() < 5 and cur.strftime("%Y-%m-%d") not in IDX_HOLIDAYS:
                counted += 1
        return cur.strftime("%Y-%m-%d")
    except Exception:
        return date_str


def fetch_broker_summary_invezgo(ticker: str, date_str: str, api_key: str, force: bool = False, is_manual: bool = False) -> list | dict[str, Any] | None:
    """
    Mengambil data broker summary via API resmi Invezgo:
    GET https://api.invezgo.com/analysis/summary/stock/{code}?from={date_str}&to={date_str}&investor=all&market=RG
    Jika is_manual=True, maka request ini adalah aksi langsung pengguna via tombol 'Cek Broksum' untuk analisa pribadi,
    sehingga diberikan pengecualian langsung (bypass batasan 2 sesi dan hard cap otomatis).
    """
    if not api_key:
        return None

    today_str = get_now_wib().strftime("%Y-%m-%d")
    calls_today = get_today_broker_call_count(today_str)
    if not is_manual and calls_today >= MAX_DAILY_BROKSUM_REQUESTS:
        print(f"[InvezgoAPI] 🛑 Hard Cap Harian Tercapai ({calls_today}/{MAX_DAILY_BROKSUM_REQUESTS} request). Request #{ticker} diblokir total.")
        return None

    # Proteksi jadwal 2x sehari jika tidak dipanggil dalam sesi yang diverifikasi dan bukan manual check
    if not force and not is_manual:
        allowed, reason, _ = can_run_broker_sync_now()
        if not allowed:
            print(f"[InvezgoAPI] 🛑 Penarikan #{ticker} ditolak: {reason}")
            return None

    clean_key = api_key.replace("Bearer ", "").strip()
    clean_ticker = ticker.upper().strip()
    # Akumulasi 3 hari bursa ke belakang dalam 1 request (rentang from..to) untuk melihat siapa yang menampung barang
    from_date = broksum_range_start(date_str, BROKSUM_LOOKBACK_DAYS)
    url = f"https://api.invezgo.com/analysis/summary/stock/{clean_ticker}?from={from_date}&to={date_str}&investor=all&market=RG"
    headers = {
        "Authorization": f"Bearer {clean_key}",
        "User-Agent": "SmartFlowIDX/94.4",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            new_cnt = increment_broker_call_count(today_str)
            tag = f"[MANUAL #{new_cnt}]" if is_manual else f"[{new_cnt}/{MAX_DAILY_BROKSUM_REQUESTS}]"
            print(f"[InvezgoAPI] {tag} Berhasil ambil #{clean_ticker} ({date_str})")
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return data.get("data", data)
    except urllib.error.HTTPError as ex:
        increment_broker_call_count(today_str)
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
        # Hanya tembak 1 tanggal (target date) agar hemat kuota API dan tidak looping multi-hari
        from datetime import datetime
        target_dt = date_str or datetime.now().strftime("%Y-%m-%d")
        try:
            if config.get("invezgo_api_key"):
                raw_data = fetch_broker_summary_invezgo(ticker, target_dt, config["invezgo_api_key"], force=True)
            elif provider == "goapi" and config.get("goapi_key"):
                raw_data = fetch_broker_summary_goapi(ticker, target_dt, config["goapi_key"])
            elif provider == "stockbit" and config.get("stockbit_token"):
                raw_data = fetch_broker_summary_stockbit(ticker, target_dt, config["stockbit_token"])
        except Exception as ex:
            print(f"[SmartFunnel] Warning fetch {ticker} on {target_dt}: {ex}")

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
                tp_obj = s["trading_plan"]
                tp_obj["bandar_avg_buy"] = metrics["bandar_avg"]
                b_avg = float(metrics["bandar_avg"])
                c_val = float(s.get("close") or 0)
                if 0 < c_val * 0.915 <= b_avg < c_val * 0.995:
                    rev_ep = _round_idx_tick(b_avg)
                    atr_v = float(tp_obj.get("atr14") or (rev_ep * 0.03))
                    sl_dist = max(int(round(rev_ep * 0.035)), min(int(round(rev_ep * 0.045)), int(round(1.5 * atr_v))))
                    new_sl = _round_idx_tick(rev_ep - sl_dist)
                    risk_rp = max(1, rev_ep - new_sl)
                    new_tp1 = _round_idx_tick(rev_ep + 2 * risk_rp)
                    new_tp2 = _round_idx_tick(rev_ep + int(round(3.5 * risk_rp)))

                    tp_obj["entry_price"] = rev_ep
                    tp_obj["entry_low"] = rev_ep
                    tp_obj["entry_high"] = rev_ep
                    tp_obj["stop_loss"] = new_sl
                    tp_obj["stop_loss_pct"] = -round((risk_rp / rev_ep) * 100.0, 2)
                    tp_obj["target_1"] = new_tp1
                    tp_obj["target_1_pct"] = round(((new_tp1 - rev_ep) / rev_ep) * 100.0, 2)
                    tp_obj["target_2"] = new_tp2
                    tp_obj["target_2_pct"] = round(((new_tp2 - rev_ep) / rev_ep) * 100.0, 2)
                    tp_obj["support_label"] = "Support Avg Bandar"

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
                if detail.get("trading_plan"):
                    if metrics.get("bandar_avg"):
                        detail["trading_plan"]["bandar_avg_buy"] = metrics["bandar_avg"]
                    if "entry_price" in s.get("trading_plan", {}):
                        detail["trading_plan"]["entry_price"] = s["trading_plan"]["entry_price"]
                        detail["trading_plan"]["entry_low"] = s["trading_plan"]["entry_low"]
                        detail["trading_plan"]["entry_high"] = s["trading_plan"]["entry_high"]
                        detail["trading_plan"]["support_label"] = s["trading_plan"].get("support_label", "Support Avg Bandar")
                    detail["trading_plan"]["top_buyers"] = s.get("top_buyers", "")
                    detail["trading_plan"]["top_buyers_list"] = s.get("top_buyers_list", [])
                    detail["trading_plan"]["bdr_pct"] = s.get("bdr_pct")
                    detail["trading_plan"]["has_real_broker_summary"] = s.get("has_real_broker_summary", False)
                if s.get("trading_plan"):
                    s["trading_plan"]["top_buyers"] = s.get("top_buyers", "")
                    s["trading_plan"]["top_buyers_list"] = s.get("top_buyers_list", [])
                    s["trading_plan"]["bdr_pct"] = s.get("bdr_pct")
                    s["trading_plan"]["has_real_broker_summary"] = s.get("has_real_broker_summary", False)
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
    force: bool = False,
) -> list[dict]:
    """
    Funneling Terpadu Broker Summary (Pilihan Hari Ini + Watchlist + Top Screener):
    HANYA dijalankan maksimal 2x sehari sesuai aturan bursa IDX:
    1. Pasca Sesi 1 bursa selesai (11:30 WIB Jumat / 12:00 WIB Senin-Kamis).
    2. Pasca Sesi 2 bursa selesai sekitar jam 6 sore WIB (18:00 WIB).

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

    # Validasi jadwal 2x sehari (proteksi kuota token Invezgo)
    session_name = None
    if not force:
        allowed, reason, session_name = can_run_broker_sync_now()
        if not allowed:
            print(f"[SmartFunnel] 🛑 Proteksi Kuota Invezgo: {reason}")
            return []
    else:
        _, _, session_name = can_run_broker_sync_now()

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

    if session_name:
        record_broker_sync_done(session_name, str(date_str))
        print(f"[SmartFunnel] 💾 Catatan sinkronisasi tersimpan untuk sesi: {session_name} ({date_str}).")

    return enriched


def enrich_single_stock_broker(s: dict, date_str: str, cfg: dict[str, Any] | None = None, force: bool = False, is_manual: bool = False) -> dict:
    """Mengambil dan memperkaya data broker summary untuk 1 saham secara on-demand.
    Jika is_manual=True, request ini dipicu tombol manual pengguna untuk analisa pribadi dan bebas dari batasan 2 sesi."""
    from datetime import datetime, timedelta

    config = cfg or load_broker_api_config()
    provider = config.get("provider", "invezgo")
    ticker = str(s.get("ticker", "")).upper().strip()
    if not ticker:
        return s

    if config.get("invezgo_api_key") and not force and not is_manual:
        allowed, reason, _ = can_run_broker_sync_now()
        if not allowed:
            print(f"[BrokerOnDemand] Proteksi Token Invezgo: Fetch on-demand #{ticker} di-skip ({reason}).")
            return s

    target_dt = date_str or get_now_wib().strftime("%Y-%m-%d")
    dates_to_try = [target_dt]
    try:
        cur = datetime.strptime(target_dt, "%Y-%m-%d")
        for i in range(1, 5):
            prev = cur - timedelta(days=i)
            if prev.weekday() < 5:
                dates_to_try.append(prev.strftime("%Y-%m-%d"))
    except Exception:
        pass

    raw_data = None
    actual_date = target_dt
    for dt_candidate in dates_to_try:
        try:
            if config.get("invezgo_api_key"):
                raw_data = fetch_broker_summary_invezgo(
                    ticker,
                    dt_candidate,
                    config["invezgo_api_key"],
                    force=force,
                    is_manual=is_manual,
                )
            elif provider == "stockbit" and config.get("stockbit_token"):
                raw_data = fetch_broker_summary_stockbit(ticker, dt_candidate, config["stockbit_token"])
            elif provider == "goapi" and config.get("goapi_key"):
                raw_data = fetch_broker_summary_goapi(ticker, dt_candidate, config["goapi_key"])
        except Exception as ex:
            print(f"[BrokerOnDemand] Error fetch {ticker} on {dt_candidate}: {ex}")

        if raw_data:
            tb, ts = extract_brokers_from_payload(raw_data)
            if tb or ts:
                actual_date = dt_candidate
                break
            else:
                raw_data = None

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
        s["broker_date"] = actual_date
        s["broker_range_from"] = broksum_range_start(actual_date, BROKSUM_LOOKBACK_DAYS)
        s["broker_holder_type"] = metrics.get("holder_type", "MIXED")

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
            tp_obj = s["trading_plan"]
            tp_obj["bandar_avg_buy"] = metrics["bandar_avg"]
            b_avg = float(metrics["bandar_avg"])
            c_val = float(s.get("close") or 0)
            if 0 < c_val * 0.915 <= b_avg < c_val * 0.995:
                rev_ep = _round_idx_tick(b_avg)
                atr_v = float(tp_obj.get("atr14") or (rev_ep * 0.03))
                sl_dist = max(int(round(rev_ep * 0.035)), min(int(round(rev_ep * 0.045)), int(round(1.5 * atr_v))))
                new_sl = _round_idx_tick(rev_ep - sl_dist)
                risk_rp = max(1, rev_ep - new_sl)
                new_tp1 = _round_idx_tick(rev_ep + 2 * risk_rp)
                new_tp2 = _round_idx_tick(rev_ep + int(round(3.5 * risk_rp)))

                tp_obj["entry_price"] = rev_ep
                tp_obj["entry_low"] = rev_ep
                tp_obj["entry_high"] = rev_ep
                tp_obj["stop_loss"] = new_sl
                tp_obj["stop_loss_pct"] = -round((risk_rp / rev_ep) * 100.0, 2)
                tp_obj["target_1"] = new_tp1
                tp_obj["target_1_pct"] = round(((new_tp1 - rev_ep) / rev_ep) * 100.0, 2)
                tp_obj["target_2"] = new_tp2
                tp_obj["target_2_pct"] = round(((new_tp2 - rev_ep) / rev_ep) * 100.0, 2)
                tp_obj["support_label"] = "Support Avg Bandar"

        if s.get("trading_plan"):
            s["trading_plan"]["top_buyers"] = s.get("top_buyers", "")
            s["trading_plan"]["top_buyers_list"] = s.get("top_buyers_list", [])
            s["trading_plan"]["bdr_pct"] = s.get("bdr_pct")
            s["trading_plan"]["has_real_broker_summary"] = s.get("has_real_broker_summary", False)

    return s


def filter_and_purge_watchlist_by_smart_money(
    tracker: Any,
    analysis: dict[str, Any] | None = None,
    date_str: str | None = None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Menyeleksi seluruh sinyal antrean 'WATCHLIST' (Menunggu) dengan uji X-Ray Smart Money Invezgo Broker Summary.
    Kriteria Eliminasi:
    1. Terdeteksi Retail Trap (sekuritas ritel menampung jualan sekuritas institusi).
    2. BDR < 3.0% (Distribusi / tidak ada dominasi akumulasi).
    3. Mayoritas pembeli adalah sekuritas ritel (>= 2 dari Top 3 Buyer adalah sekuritas ritel YP, PD, XC, XL, KK, NI, SQ, BQ).
    4. Tidak ada satupun sekuritas institusi di Top 3 Buyer dan BDR < 10.0%.

    Saham yang tidak memenuhi kriteria di atas langsung DIHAPUS dari Watchlist.
    Saham yang lolos diperbarui dengan catatan konfirmasi smart money dan level antre entry rata-rata bandar.
    """
    config = cfg or load_broker_api_config()
    provider = config.get("provider", "invezgo")
    token = config.get("invezgo_api_key") or config.get("stockbit_token") or config.get("goapi_key")
    if not token:
        print("[SmartPurge] Token API broker belum disetel. Melewati filter eliminasi ritel.")
        return {"total": 0, "retained": [], "eliminated": [], "message": "Token API broker tidak ditemukan."}

    from datetime import datetime
    target_dt = date_str or datetime.now().strftime("%Y-%m-%d")
    dates_to_try = [target_dt]

    wl_signals = tracker.list_signals(status="WATCHLIST")
    if not wl_signals:
        print("[SmartPurge] Tidak ada sinyal WATCHLIST yang sedang menunggu.")
        return {"total": 0, "retained": [], "eliminated": []}

    print(f"[SmartPurge] Memulai audit Smart Money untuk {len(wl_signals)} saham antrean Watchlist...")

    details_map = analysis.get("details", {}) if analysis else {}
    eliminated = []
    retained = []

    for s in wl_signals:
        ticker = str(s.get("ticker", "")).upper().strip()
        sig_id = s.get("id")
        if not ticker:
            continue

        metrics = None
        top_buyers = []
        top_sellers = []

        # Cek apakah sudah ada di details_map dengan data real
        if details_map and ticker in details_map and details_map[ticker].get("has_real_broker_summary"):
            d_item = details_map[ticker]
            metrics = d_item.get("broker_analysis")
            top_buyers = d_item.get("top_buyers_list", [])
            top_sellers = d_item.get("top_sellers_list", [])

        # Jika belum ada data real, fetch langsung ke Invezgo API HANYA jika jadwal mengizinkan
        if not metrics or not top_buyers:
            if config.get("invezgo_api_key"):
                allowed_purge, _, _ = can_run_broker_sync_now()
                if not allowed_purge:
                    continue
            time.sleep(max(0.2, config.get("delay_ms", 300) / 1000.0))
            raw_data = None
            for dt_c in dates_to_try:
                try:
                    if config.get("invezgo_api_key"):
                        raw_data = fetch_broker_summary_invezgo(ticker, dt_c, config["invezgo_api_key"], force=True)
                    elif provider == "stockbit" and config.get("stockbit_token"):
                        raw_data = fetch_broker_summary_stockbit(ticker, dt_c, config["stockbit_token"])
                    elif provider == "goapi" and config.get("goapi_key"):
                        raw_data = fetch_broker_summary_goapi(ticker, dt_c, config["goapi_key"])
                    if raw_data:
                        break
                except Exception as ex:
                    print(f"[SmartPurge] Error fetch {ticker} on {dt_c}: {ex}")

            if raw_data:
                b_list, s_list = extract_brokers_from_payload(raw_data)
                metrics = analyze_broker_summary(b_list, s_list)
                top_buyers = [b["code"] for b in b_list[:3]]
                top_sellers = [s["code"] for s in s_list[:3]]

                # Update detail & stock di analysis jika ada
                if details_map and ticker in details_map:
                    details_map[ticker]["broker_analysis"] = metrics
                    details_map[ticker]["has_broker_summary"] = True
                    details_map[ticker]["has_real_broker_summary"] = True
                    details_map[ticker]["bdr_pct"] = metrics["bdr"]
                    details_map[ticker]["top_buyers_list"] = top_buyers
                    details_map[ticker]["top_sellers_list"] = top_sellers
                    details_map[ticker]["top_buyers"] = ", ".join(top_buyers)
                    details_map[ticker]["top_sellers"] = ", ".join(top_sellers)
                    if metrics.get("bandar_avg"):
                        details_map[ticker]["bandar_avg_buy"] = metrics["bandar_avg"]

        if not metrics:
            print(f"[SmartPurge] {ticker}: Tidak ada data broker summary dari API. Dieliminasi demi kehati-hatian.")
            tracker.delete_signal(sig_id)
            eliminated.append({"ticker": ticker, "reason": "Data API Broker Kosong / Tidak Tersedia", "bdr": 0.0})
            continue

        bdr = float(metrics.get("bdr", 0.0))
        is_retail_trap = bool(metrics.get("retail_trap", False))
        retail_count = sum(1 for c in top_buyers if c in RETAIL_BROKERS)
        inst_count = sum(1 for c in top_buyers if c in INST_FOREIGN_BROKERS)
        bandar_avg = metrics.get("bandar_avg")

        # Logika Eliminasi:
        reason_elim = None
        if is_retail_trap:
            reason_elim = f"Jebakan Ritel / Ritel Trap (Buyer: {', '.join(top_buyers)}, Seller: {', '.join(top_sellers)})"
        elif bdr < 3.0:
            reason_elim = f"Distribusi / BDR Rendah ({bdr:.1f}%)"
        elif retail_count >= 2:
            reason_elim = f"Pembeli didominasi broker ritel ({retail_count} dari 3: {', '.join(top_buyers)})"
        elif inst_count == 0 and bdr < 10.0:
            reason_elim = f"Tidak ada jejak broker institusi di Top 3 Buyer ({', '.join(top_buyers)})"
        elif metrics.get("holder_type") == "RETAIL":
            reason_elim = f"Barang ditampung ritel dalam {BROKSUM_LOOKBACK_DAYS} hari bursa terakhir ({', '.join(top_buyers)})"

        if reason_elim:
            print(f"[SmartPurge] [ELIMINASI] {ticker} DIELIMINASI DARI WATCHLIST -> {reason_elim}")
            tracker.delete_signal(sig_id)
            eliminated.append({
                "ticker": ticker,
                "reason": reason_elim,
                "bdr": bdr,
                "buyers": top_buyers,
                "sellers": top_sellers,
            })
            # Bersihkan juga dari today_candidates jika ada
            if analysis and "today_candidates" in analysis:
                analysis["today_candidates"] = [c for c in analysis["today_candidates"] if str(c.get("ticker", "")).upper() != ticker]
        else:
            # Saham LOLOS kriteria Smart Money!
            print(f"[SmartPurge] [LOLOS] {ticker} LOLOS SMART MONEY (BDR: +{bdr:.1f}%, Buyer: {', '.join(top_buyers)}, Bandar Avg: {bandar_avg})")
            upd_values = {
                "score": min(100, max(5, int(s.get("score", 70) + metrics.get("score_modifier", 10)))),
                "note": f"Smart Money Terkonfirmasi ({BROKSUM_LOOKBACK_DAYS} hari bursa): BDR +{bdr:.1f}% (Buyer: {', '.join(top_buyers)}) · Avg Bandar: Rp {bandar_avg or '-'}",
            }
            if bandar_avg and bandar_avg > 0:
                rev_ep = float(_round_idx_tick(float(bandar_avg)))
                new_sl = float(_round_idx_tick(rev_ep * 0.965))
                risk_rp = max(1.0, rev_ep - new_sl)
                upd_values["entry_low"] = rev_ep
                upd_values["entry_high"] = rev_ep
                upd_values["stop_loss"] = new_sl
                upd_values["target"] = float(_round_idx_tick(rev_ep + 2.0 * risk_rp))
                upd_values["target_2"] = float(_round_idx_tick(rev_ep + 3.5 * risk_rp))

                # Sinkronkan juga langsung ke trading_plan di memory (details_map)
                if details_map and ticker in details_map and details_map[ticker].get("trading_plan"):
                    tp_obj = details_map[ticker]["trading_plan"]
                    tp_obj["entry_price"] = rev_ep
                    tp_obj["entry_high"] = rev_ep
                    tp_obj["entry_low"] = rev_ep
                    tp_obj["stop_loss"] = new_sl
                    tp_obj["target_1"] = upd_values["target"]
                    tp_obj["target_2"] = upd_values["target_2"]
                    tp_obj["support_label"] = "Support Avg Bandar"

            try:
                from sqlalchemy import update
                from signal_tracker import signals_table, _now_str
                upd_values["updated_at"] = _now_str()
                with tracker._lock, tracker.engine.begin() as conn:
                    conn.execute(update(signals_table).where(signals_table.c.id == sig_id).values(**upd_values))
            except Exception as ex:
                print(f"[SmartPurge] Warning update signal {ticker}: {ex}")

            retained.append({
                "ticker": ticker,
                "bdr": bdr,
                "buyers": top_buyers,
                "sellers": top_sellers,
                "bandar_avg": bandar_avg,
            })

    print(f"[SmartPurge] Selesai. {len(retained)} saham lolos Smart Money, {len(eliminated)} saham ritel/distribusi dihapus dari Watchlist.")
    return {
        "total_initial": len(wl_signals),
        "retained_count": len(retained),
        "eliminated_count": len(eliminated),
        "retained": retained,
        "eliminated": eliminated,
    }
