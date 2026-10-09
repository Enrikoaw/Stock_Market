"""
FastAPI Backend Server untuk SmartFlow IDX - Smart Money Stock Screener (v4.0 - 24/7 Cloud & Auto-Sync Ready).
Fitur 24 Jam:
1. Background Auto-Sync Scheduler: Otomatis menarik data harga & volume terbaru dari BEI (Yahoo Finance .JK)
   secara berkala di latar belakang tanpa menghentikan layanan.
2. Siap Deploy 24/7 ke Cloud (Render, Railway, Hugging Face Spaces Docker, VPS) maupun Windows Service.
"""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Pastikan direktori backend masuk ke sys.path baik dijalankan dari root maupun folder backend/
BACKEND_DIR = Path(__file__).resolve().parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from excel_generator import (
    build_excel_bytes,
    ensure_default_excel_files,
    generate_900_idx_master_tickers_df,
)
from live_idx_fetcher import fetch_real_idx_market_data
from signal_tracker import SignalTracker
from screener_engine import (
    analyze_smart_money_dataframe,
    enrich_master_ticker_list,
    read_multiple_uploaded_files,
    read_uploaded_file,
)

BASE_DIR = BACKEND_DIR.parent
FRONTEND_DIR = BASE_DIR / "frontend"
USER_EXCEL_DIR = BASE_DIR / "data" / "user_excel"
REAL_CACHE_CSV = BASE_DIR / "data" / "real_idx_market_latest.csv"
MASTER_UPLOADED_CSV = BASE_DIR / "data" / "master_uploaded_tickers.csv"

# Interval Auto-Sync dalam detik (default: setiap 30 menit = 1800 detik)
AUTO_SYNC_INTERVAL_SECONDS = int(os.environ.get("AUTO_SYNC_INTERVAL", "1800"))

STATE: dict = {
    "source_name": "Daftar Saham IDX - REAL Market Data",
    "analysis": None,
    "last_sync_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "is_syncing": False,
    "auto_sync_interval_min": AUTO_SYNC_INTERVAL_SECONDS // 60,
    "is_real_market": False,
    "last_tracker_run": None,
}

TRACKER = SignalTracker(BASE_DIR / "data" / "tracker.db")


def _process_tracker(analysis: dict, sync_live_network: bool = False) -> dict:
    """Evaluasi sinyal aktif dengan candle baru, lalu catat sinyal akumulasi baru ke Watchlist.
    Hanya berjalan untuk data pasar REAL (bukan simulasi / upload manual)."""
    result = {"entered": 0, "win": 0, "loss": 0, "expired": 0, "timeout": 0, "added": 0, "skipped": False}
    if not STATE.get("is_real_market"):
        result["skipped"] = True
        return result
    try:
        # 1. Tarik live quotes intraday via network HANYA jika diminta eksplisit
        if sync_live_network:
            live_res = TRACKER.sync_active_signals_live()
            result.update(live_res)

        # 2. Evaluasi dataset analisis penuh (sudah berisi harga terbaru dari sync)
        if analysis and "details" in analysis:
            main_res = TRACKER.evaluate(analysis["details"])
            for k in ("entered", "win", "loss", "expired", "timeout"):
                result[k] = max(result.get(k, 0), main_res.get(k, 0))
            result["added"] = TRACKER.auto_track(analysis)

        STATE["last_tracker_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[Tracker] {result}")
    except Exception as exc:
        print(f"[Tracker] Error: {exc}")
    return result


class LocalPathRequest(BaseModel):
    path: str


def _run_fast_sync_job_blocking() -> dict:
    """Sync kilat (< 2-3 detik) khusus untuk evaluasi live Watchlist & Running (Entry, TP, SL)."""
    tracker_res = TRACKER.sync_active_signals_live()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    STATE["last_tracker_run"] = now_str

    if STATE["analysis"] is None:
        init_default_state()

    return {
        "status": "success",
        "tracker_res": tracker_res,
        "message": f"⚡ Sync Cepat selesai! {tracker_res.get('tickers_checked', 0)} saham aktif dievaluasi (Status: RUNNING/TP/SL ter-update).",
        "source_name": STATE["source_name"],
        "last_sync_time": STATE["last_sync_time"],
        "kpis": STATE["analysis"]["kpis"],
        "stocks": STATE["analysis"]["stocks"],
    }


def _run_sync_job_blocking() -> dict:
    """Fungsi sinkronisasi data pasar seluruh 844 saham BEI di background thread."""
    if MASTER_UPLOADED_CSV.exists():
        tickers_df = pd.read_csv(MASTER_UPLOADED_CSV)
    else:
        tickers_df = generate_900_idx_master_tickers_df()

    real_df = fetch_real_idx_market_data(tickers_df, output_csv_path=REAL_CACHE_CSV, period="auto", max_workers=2)
    analysis = analyze_smart_money_dataframe(real_df)
    del real_df
    import gc
    gc.collect()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    latest_dt = analysis["kpis"]["latest_date"]
    STATE["source_name"] = f"Live IDX On-Demand ({latest_dt})"
    STATE["analysis"] = analysis
    STATE["last_sync_time"] = now_str
    STATE["is_real_market"] = True
    _process_tracker(analysis, sync_live_network=False)
    return analysis


async def _background_fast_tracker_worker() -> None:
    """Worker ringan yang memantau saham aktif di Watchlist & Running secara live (hanya aktif jika ENABLE_BACKGROUND_TRACKER=true)."""
    while True:
        await asyncio.sleep(120)
        try:
            active_tickers = TRACKER.get_active_tickers()
            if active_tickers:
                res = await asyncio.to_thread(TRACKER.sync_active_signals_live)
                if any(res.get(k, 0) > 0 for k in ("entered", "win", "loss", "expired", "timeout")):
                    print(f"[TrackerLive] Status berubah: {res}")
                    STATE["last_tracker_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as exc:
            print(f"[TrackerLive] Error: {exc}")


async def _background_24h_auto_sync_worker() -> None:
    """Background worker 24 jam (hanya aktif jika ENABLE_AUTO_SYNC=true eksplisit diset di environment)."""
    while True:
        await asyncio.sleep(AUTO_SYNC_INTERVAL_SECONDS)
        if STATE["is_syncing"]:
            continue
        try:
            STATE["is_syncing"] = True
            print(f"[AutoSync] Memulai pembaruan otomatis data saham IDX pada {datetime.now()}...")
            await asyncio.to_thread(_run_sync_job_blocking)
        except Exception as exc:
            print(f"[AutoSync] Error saat auto-sync: {exc}")
        finally:
            STATE["is_syncing"] = False


# Mode On-Demand (Default: False agar hemat memori < 150MB dan tidak terkena limit Render Free)
ENABLE_AUTO_SYNC = os.environ.get("ENABLE_AUTO_SYNC", "false").lower() in ("true", "1")
ENABLE_BACKGROUND_TRACKER = os.environ.get("ENABLE_BACKGROUND_TRACKER", "false").lower() in ("true", "1")


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Mengelola siklus hidup server.
    Secara default PASIF & ON-DEMAND: tidak menyalakan background loop otomatis
    agar server sangat hemat memori (< 150MB RAM) dan tidak memicu restart limit di Render gratisan.
    Data hanya ditarik saat pengguna mengeklik tombol sinkronisasi.
    """
    tasks = []
    if ENABLE_AUTO_SYNC:
        print("[Lifespan] Mode Auto-Sync 24/7 aktif via environment.")
        tasks.append(asyncio.create_task(_background_24h_auto_sync_worker()))
    if ENABLE_BACKGROUND_TRACKER:
        print("[Lifespan] Mode Background Fast Tracker aktif via environment.")
        tasks.append(asyncio.create_task(_background_fast_tracker_worker()))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(
    title="SmartFlow IDX - On-Demand Smart Money Stock Screener API",
    description="API Backend On-Demand untuk deteksi pergerakan Smart Money dari seluruh saham IDX",
    version="4.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def init_default_state() -> None:
    """Memuat data pasar REAL terbaru dari cache hasil sinkronisasi seluruh saham IDX."""
    ensure_default_excel_files(BASE_DIR)
    USER_EXCEL_DIR.mkdir(parents=True, exist_ok=True)

    if REAL_CACHE_CSV.exists():
        real_df = pd.read_csv(REAL_CACHE_CSV)
        real_df["Has_Broker_Summary"] = True
        STATE["source_name"] = "Daftar Saham IDX - REAL Market Data (24/7 Active)"
        STATE["analysis"] = analyze_smart_money_dataframe(real_df)
        STATE["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        STATE["is_real_market"] = True
        _process_tracker(STATE["analysis"])
        return

    master_900 = generate_900_idx_master_tickers_df()
    enriched_900 = enrich_master_ticker_list(master_900, num_days=15)
    STATE["source_name"] = "daftar_900_emiten_idx.xlsx (900 Emiten IDX)"
    STATE["is_real_market"] = False
    STATE["analysis"] = analyze_smart_money_dataframe(enriched_900)
    STATE["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")


init_default_state()


@app.get("/api/health")
def health_check() -> dict:
    """Endpoint Health Check untuk pemantauan server Cloud 24 jam (UptimeRobot / Render / Railway)."""
    return {
        "status": "online",
        "mode": "24/7_auto_sync",
        "last_sync_time": STATE["last_sync_time"],
        "is_syncing": STATE["is_syncing"],
        "total_emiten": STATE["analysis"]["kpis"]["total_emiten"] if STATE["analysis"] else 0,
    }


@app.get("/api/screener")
def get_screener_data(
    trigger: Optional[str] = Query(default="ALL", description="Filter berdasarkan tipe trigger Smart Money"),
    min_score: int = Query(default=0, ge=0, le=100, description="Minimum Smart Money Score (0-100)"),
    min_vol_ratio: float = Query(default=0.0, ge=0.0, description="Minimum Volume Spike Ratio terhadap MA20"),
    search: Optional[str] = Query(default="", description="Cari kode Ticker atau Sektor"),
    sort_by: Literal["score", "vol_ratio", "top3_bsr", "foreign", "pct_change"] = Query(default="score"),
) -> dict:
    if STATE["analysis"] is None:
        init_default_state()

    analysis = STATE["analysis"]
    stocks = list(analysis["stocks"])

    if trigger and isinstance(trigger, str) and trigger.upper() != "ALL":
        if trigger.upper() == "ACCUM_ALL":
            stocks = [
                s
                for s in stocks
                if s["trigger_type"] in ("MARKUP_BREAKOUT", "BIG_ACCUMULATION", "SILENT_ACCUMULATION", "FOREIGN_INFLOW")
            ]
        else:
            stocks = [s for s in stocks if s["trigger_type"] == trigger.upper()]

    if isinstance(min_score, int) and min_score > 0:
        stocks = [s for s in stocks if s["smart_money_score"] >= min_score]

    if isinstance(min_vol_ratio, (int, float)) and min_vol_ratio > 0:
        stocks = [s for s in stocks if s["vol_ratio"] >= min_vol_ratio]

    if search and isinstance(search, str) and search.strip():
        q = search.strip().lower()
        stocks = [
            s
            for s in stocks
            if q in s["ticker"].lower()
            or q in s["sector"].lower()
            or q in s["trigger_label"].lower()
            or q in s["top_buyers"].lower()
        ]

    sort_key_map = {
        "score": lambda x: (x["smart_money_score"], x["vol_ratio"]),
        "vol_ratio": lambda x: (x["vol_ratio"], x["smart_money_score"]),
        "top3_bsr": lambda x: (x["top3_bsr"], x["smart_money_score"]),
        "foreign": lambda x: (x["net_foreign_pct"], x["smart_money_score"]),
        "pct_change": lambda x: (x["pct_change"], x["smart_money_score"]),
    }
    stocks.sort(key=sort_key_map.get(sort_by, sort_key_map["score"]), reverse=True)

    return {
        "source_name": STATE["source_name"],
        "last_sync_time": STATE["last_sync_time"],
        "is_syncing": STATE["is_syncing"],
        "auto_sync_interval_min": STATE["auto_sync_interval_min"],
        "kpis": analysis["kpis"],
        "count": len(stocks),
        "stocks": stocks,
    }


@app.get("/api/stock/{ticker}")
def get_stock_detail(ticker: str) -> dict:
    if STATE["analysis"] is None:
        init_default_state()

    key = ticker.strip().upper()
    details_map = STATE["analysis"]["details"]
    if key not in details_map:
        raise HTTPException(status_code=404, detail=f"Saham '{key}' tidak ditemukan pada dataset aktif.")
    return details_map[key]


async def _run_full_sync_background() -> None:
    try:
        await asyncio.to_thread(_run_sync_job_blocking)
    except Exception as exc:
        print(f"[FullSync Background] Error: {exc}")
    finally:
        STATE["is_syncing"] = False


@app.post("/api/sync-fast")
async def sync_fast_market_data() -> dict:
    """Sync kilat (< 2-3 detik) khusus untuk saham Watchlist & Running."""
    try:
        res = await asyncio.to_thread(_run_fast_sync_job_blocking)
        return res
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal sync cepat: {exc}") from exc


@app.post("/api/sync-live")
async def sync_live_idx_market_data() -> dict:
    """Menjalankan sinkronisasi seluruh 844 saham IDX secara non-blocking di background thread."""
    if STATE["is_syncing"]:
        return {
            "status": "already_running",
            "message": "Sinkronisasi seluruh 844 saham sedang berjalan di background...",
            "source_name": STATE["source_name"],
            "last_sync_time": STATE["last_sync_time"],
        }
    STATE["is_syncing"] = True
    asyncio.create_task(_run_full_sync_background())
    return {
        "status": "started",
        "message": "🚀 Sinkronisasi seluruh 844 saham IDX berjalan di background. Web tetap responsif!",
        "source_name": STATE["source_name"],
        "last_sync_time": STATE["last_sync_time"],
    }


@app.post("/api/upload")
async def upload_excel_files(
    files: Optional[list[UploadFile]] = File(default=None),
    file: Optional[UploadFile] = File(default=None),
) -> dict:
    upload_list: list[UploadFile] = []
    if files:
        upload_list.extend(files)
    if file:
        upload_list.append(file)

    if not upload_list:
        raise HTTPException(status_code=400, detail="Tidak ada file yang diunggah.")

    files_payload: list[tuple[bytes, str]] = []
    for uf in upload_list:
        if not uf.filename:
            continue
        ext = uf.filename.lower()
        if not (ext.endswith(".xlsx") or ext.endswith(".xls") or ext.endswith(".csv")):
            raise HTTPException(
                status_code=400,
                detail=f"Format file '{uf.filename}' tidak didukung. Gunakan .xlsx, .xls, atau .csv.",
            )
        raw_bytes = await uf.read()
        files_payload.append((raw_bytes, uf.filename))

    try:
        if len(files_payload) == 1:
            df = read_uploaded_file(files_payload[0][0], files_payload[0][1])
            src_label = f"{files_payload[0][1]} (Real Market Data)"
        else:
            df = read_multiple_uploaded_files(files_payload)
            src_label = f"{len(files_payload)} File Excel Digabung (Real Market Data)"

        analysis = analyze_smart_money_dataframe(df)
        STATE["source_name"] = src_label
        STATE["analysis"] = analysis
        STATE["is_real_market"] = False
        STATE["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "status": "success",
            "message": f"Berhasil memuat & menganalisis {analysis['kpis']['total_emiten']} saham aktif IDX dari {src_label}!",
            "source_name": STATE["source_name"],
            "last_sync_time": STATE["last_sync_time"],
            "kpis": analysis["kpis"],
            "stocks": analysis["stocks"],
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve)) from ve
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal memproses file Excel: {exc}") from exc


@app.post("/api/load-path")
def load_excel_from_local_path(req: LocalPathRequest) -> dict:
    raw_path = req.path.strip().strip('"').strip("'")
    target = Path(raw_path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Lokasi file/folder tidak ditemukan: {raw_path}")

    try:
        if target.is_dir():
            excel_files = sorted(
                [
                    p
                    for p in target.iterdir()
                    if p.is_file() and p.suffix.lower() in (".xlsx", ".xls", ".csv") and not p.name.startswith("~$")
                ]
            )
            if not excel_files:
                raise HTTPException(status_code=400, detail=f"Tidak ada file .xlsx/.xls/.csv di dalam folder {raw_path}")
            payload = [(p.read_bytes(), p.name) for p in excel_files]
            df = read_multiple_uploaded_files(payload)
            src_label = f"{target.name}/ ({len(excel_files)} file)"
        else:
            df = read_uploaded_file(target.read_bytes(), target.name)
            src_label = f"{target.name} (Real Market Data)"

        analysis = analyze_smart_money_dataframe(df)
        STATE["source_name"] = src_label
        STATE["analysis"] = analysis
        STATE["is_real_market"] = False
        STATE["last_sync_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "status": "success",
            "message": f"Berhasil memuat {analysis['kpis']['total_emiten']} saham IDX dari {src_label}!",
            "source_name": STATE["source_name"],
            "last_sync_time": STATE["last_sync_time"],
            "kpis": analysis["kpis"],
            "stocks": analysis["stocks"],
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Gagal membaca file dari path tersebut: {exc}") from exc


@app.post("/api/reset")
def reset_to_sample_data() -> dict:
    init_default_state()
    return {
        "status": "success",
        "source_name": STATE["source_name"],
        "last_sync_time": STATE["last_sync_time"],
        "kpis": STATE["analysis"]["kpis"],
        "stocks": STATE["analysis"]["stocks"],
    }


@app.get("/api/template")
def download_excel_template(mode: Literal["sample", "blank"] = Query(default="sample")) -> Response:
    excel_bytes = build_excel_bytes(mode=mode)
    filename = "smart_money_idx_sample_25days.xlsx" if mode == "sample" else "smart_money_blank_template.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ===================== SIGNAL TRACKER / FORWARD TEST =====================


@app.get("/api/tracker/stats")
def tracker_stats() -> dict:
    return {
        "config": TRACKER.config(),
        "stats": TRACKER.stats(),
        "last_tracker_run": STATE.get("last_tracker_run"),
        "is_real_market": STATE.get("is_real_market"),
    }


@app.get("/api/tracker/signals")
def tracker_signals(
    status: str = Query(default="ALL"),
    sort_by: str = Query(default="id_desc", description="Urutkan sinyal: pnl_desc, pnl_asc, score_desc, date_desc, ticker_asc"),
) -> dict:
    rows = TRACKER.list_signals(status=status, sort_by=sort_by)
    return {"count": len(rows), "signals": rows}


@app.post("/api/tracker/add/{ticker}")
def tracker_add(ticker: str) -> dict:
    key = ticker.strip().upper()
    details = STATE["analysis"]["details"] if STATE["analysis"] else {}
    if key not in details:
        raise HTTPException(status_code=404, detail=f"Saham '{key}' tidak ditemukan pada dataset aktif.")
    ok, msg = TRACKER.add_signal(details[key], source="MANUAL")
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg}


@app.post("/api/tracker/evaluate")
async def tracker_evaluate() -> dict:
    if STATE["analysis"] is None:
        init_default_state()
    result = await asyncio.to_thread(_process_tracker, STATE["analysis"])
    if result.get("skipped"):
        msg = "Evaluasi dilewati: dataset aktif bukan data pasar real. Klik 'Sync Harga Real' terlebih dahulu."
    else:
        msg = (
            f"Evaluasi selesai: {result['added']} sinyal baru, {result['entered']} entry, "
            f"{result['win']} win, {result['loss']} loss, {result['expired']} expired, {result['timeout']} timeout."
        )
    return {"status": "success", "result": result, "message": msg}


@app.delete("/api/tracker/signals/{signal_id}")
def tracker_delete(signal_id: int) -> dict:
    if not TRACKER.delete_signal(signal_id):
        raise HTTPException(status_code=404, detail="Sinyal tidak ditemukan.")
    return {"status": "success", "message": "Sinyal dihapus."}


@app.post("/api/tracker/reset")
def tracker_reset() -> dict:
    n = TRACKER.reset_all()
    return {"status": "success", "message": f"{n} catatan sinyal dihapus. Tracker dimulai dari nol."}


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def serve_dashboard() -> FileResponse:
    return FileResponse(str(FRONTEND_DIR / "index.html"))


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    uvicorn.run("main:app", host=host, port=port, reload=False)
