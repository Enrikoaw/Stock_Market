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
}


class LocalPathRequest(BaseModel):
    path: str


def _run_sync_job_blocking() -> dict:
    """Fungsi sinkronisasi data pasar BEI yang dijalankan di background thread agar tidak memblokir API."""
    if MASTER_UPLOADED_CSV.exists():
        tickers_df = pd.read_csv(MASTER_UPLOADED_CSV)
    else:
        tickers_df = generate_900_idx_master_tickers_df()

    real_df = fetch_real_idx_market_data(tickers_df, output_csv_path=REAL_CACHE_CSV, period="1mo")
    analysis = analyze_smart_money_dataframe(real_df)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    latest_dt = analysis["kpis"]["latest_date"]
    STATE["source_name"] = f"Live IDX 24/7 Auto-Sync ({latest_dt})"
    STATE["analysis"] = analysis
    STATE["last_sync_time"] = now_str
    return analysis


async def _background_24h_auto_sync_worker() -> None:
    """Background worker 24 jam yang menyinkronkan data bursa secara otomatis setiap interval waktu."""
    while True:
        await asyncio.sleep(AUTO_SYNC_INTERVAL_SECONDS)
        if STATE["is_syncing"]:
            continue
        try:
            STATE["is_syncing"] = True
            print(f"[AutoSync 24/7] Memulai pembaruan otomatis data saham IDX pada {datetime.now()}...")
            await asyncio.to_thread(_run_sync_job_blocking)
            print(f"[AutoSync 24/7] Pembaruan otomatis selesai pada {STATE['last_sync_time']}.")
        except Exception as exc:
            print(f"[AutoSync 24/7] Error saat auto-sync: {exc}")
        finally:
            STATE["is_syncing"] = False


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    """Mengelola siklus hidup server 24/7 dan menyalakan worker Auto-Sync di background."""
    task = asyncio.create_task(_background_24h_auto_sync_worker())
    yield
    task.cancel()


app = FastAPI(
    title="SmartFlow IDX - 24/7 Smart Money Stock Screener API",
    description="API Backend 24/7 untuk deteksi pergerakan Smart Money dari seluruh saham IDX",
    version="4.0.0",
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
        return

    master_900 = generate_900_idx_master_tickers_df()
    enriched_900 = enrich_master_ticker_list(master_900, num_days=15)
    STATE["source_name"] = "daftar_900_emiten_idx.xlsx (900 Emiten IDX)"
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


@app.post("/api/sync-live")
async def sync_live_idx_market_data() -> dict:
    """Menarik data harga & volume REAL terbaru hari ini dari Yahoo Finance (.JK) di background thread."""
    if STATE["is_syncing"]:
        return {
            "status": "busy",
            "message": "Sinkronisasi sedang berjalan di latar belakang, mohon tunggu sebentar.",
            "source_name": STATE["source_name"],
            "kpis": STATE["analysis"]["kpis"],
            "stocks": STATE["analysis"]["stocks"],
        }
    try:
        STATE["is_syncing"] = True
        analysis = await asyncio.to_thread(_run_sync_job_blocking)
        latest_dt = analysis["kpis"]["latest_date"]
        return {
            "status": "success",
            "message": f"Berhasil sinkronisasi harga REAL terbaru ({latest_dt}) untuk {analysis['kpis']['total_emiten']} saham aktif IDX!",
            "source_name": STATE["source_name"],
            "last_sync_time": STATE["last_sync_time"],
            "kpis": analysis["kpis"],
            "stocks": analysis["stocks"],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal sinkronisasi live data: {exc}") from exc
    finally:
        STATE["is_syncing"] = False


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
