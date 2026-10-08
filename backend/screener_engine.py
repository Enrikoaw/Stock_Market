"""
SmartFlow IDX - Smart Money Screener Quantitative Engine (v3.0)
Mendukung penuh:
1. Upload File Excel "Daftar Nama Saham IDX (900+ Emiten)" (hanya berisi Kode Saham & Nama Perusahaan)
   -> Otomatis mengenali 900+ kode saham dari Excel & mengisi simulasi/data pasar Smart Money!
2. Sinkronisasi Harga & Volume Asli Bursa (BEI / IDX) via Yahoo Finance (.JK) untuk daftar saham di Excel!
3. Upload File Excel Ringkasan Saham BEI (OHLCV + Foreign) maupun Broker Summary Sekuritas.
4. Komputasi Ter-Vektorisasi (menganalisis 900+ saham x 15 hari dalam < 0.5 detik).
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd


COLUMN_ALIASES: dict[str, list[str]] = {
    "Date": [
        "date",
        "tanggal",
        "tgl",
        "tanggal_perdagangan_terakhir",
        "last_trading_date",
        "trading_date",
        "time",
        "datetime",
    ],
    "Ticker": [
        "ticker",
        "kode_saham",
        "kode",
        "stock_code",
        "stock",
        "emiten",
        "symbol",
        "code",
        "saham",
        "kode_emiten",
    ],
    "Company_Name": [
        "company_name",
        "nama_perusahaan",
        "nama_emiten",
        "nama_saham",
        "nama",
        "name",
        "perusahaan",
        "issuer_name",
    ],
    "Sector": [
        "sector",
        "sektor",
        "industri",
        "industry",
        "papan_pencatatan",
        "listing_board",
        "papan",
        "remarks",
    ],
    "Prev_Close": [
        "prev_close",
        "sebelumnya",
        "previous",
        "prev",
        "harga_sebelumnya",
        "previous_price",
    ],
    "Open": ["open", "open_price", "pembukaan", "harga_pembukaan", "first_trade", "o"],
    "High": ["high", "tertinggi", "high_price", "harga_tertinggi", "h"],
    "Low": ["low", "terendah", "low_price", "harga_terendah", "l"],
    "Close": [
        "close",
        "penutupan",
        "last",
        "harga",
        "harga_penutupan",
        "close_price",
        "closing_price",
        "price",
        "c",
    ],
    "Change": ["change", "selisih", "chg", "perubahan", "point_change"],
    "Pct_Change_Raw": ["pct_change", "%_change", "%chg", "chg_%", "persentase", "pct"],
    "Volume_Lot": [
        "volume_lot",
        "volume",
        "vol",
        "lot",
        "total_lot",
        "vol_lot",
        "total_volume",
    ],
    "Value_IDR": [
        "value_idr",
        "nilai",
        "value",
        "val",
        "turnover",
        "nilai_transaksi",
        "total_value",
    ],
    "Frequency": [
        "frequency",
        "frekuensi",
        "freq",
        "tx",
        "transactions",
        "total_frequency",
    ],
    "Top1_Buy_Lot": ["top1_buy_lot", "top1_buy", "b1_lot", "top1_buyer_lot"],
    "Top3_Buy_Lot": [
        "top3_buy_lot",
        "top3_buy",
        "b3_lot",
        "top3_buyer_lot",
        "bandar_buy_lot",
        "big_buy_lot",
    ],
    "Top5_Buy_Lot": ["top5_buy_lot", "top5_buy", "b5_lot", "top5_buyer_lot"],
    "Top1_Sell_Lot": ["top1_sell_lot", "top1_sell", "s1_lot", "top1_seller_lot"],
    "Top3_Sell_Lot": [
        "top3_sell_lot",
        "top3_sell",
        "s3_lot",
        "top3_seller_lot",
        "bandar_sell_lot",
        "big_sell_lot",
    ],
    "Top5_Sell_Lot": ["top5_sell_lot", "top5_sell", "s5_lot", "top5_seller_lot"],
    "Top_Buyer_Brokers": ["top_buyer_brokers", "top_buyers", "buyer_brokers", "broker_buy", "top_buyer"],
    "Top_Seller_Brokers": ["top_seller_brokers", "top_sellers", "seller_brokers", "broker_sell", "top_seller"],
    "Bandar_Avg_Buy": ["bandar_avg_buy", "avg_buy", "bandar_avg", "average_buy", "vwap"],
    "Foreign_Buy_Val": ["foreign_buy_val", "foreign_buy", "f_buy", "nb_val", "beli_asing"],
    "Foreign_Sell_Val": ["foreign_sell_val", "foreign_sell", "f_sell", "ns_val", "jual_asing"],
    "Net_Foreign_Raw": ["net_foreign", "foreign_net", "nforeign", "net_foreign_val", "net_foreign_buy"],
    "Bid_Vol": ["bid_volume", "bid_vol", "volume_bid"],
    "Offer_Vol": ["offer_volume", "offer_vol", "ask_volume", "volume_offer"],
    "Non_Reg_Vol": ["non_regular_volume", "non_reg_vol", "nego_volume"],
    "Non_Reg_Val": ["non_regular_value", "non_reg_val", "nego_value"],
    "Listed_Shares": ["listed_shares", "jumlah_saham", "shares", "tradeble_shares", "saham_tercatat"],
}

RESERVED_UPPER_WORDS = {
    "KODE",
    "NAMA",
    "DATE",
    "OPEN",
    "HIGH",
    "LOWS",
    "LAST",
    "CODE",
    "TYPE",
    "NULL",
    "NONE",
    "TRUE",
    "MAIN",
    "BOARD",
    "UTAMA",
}

INST_BROKERS_POOL = [
    "ZP, AK, YU",
    "MG, BK, AK",
    "AK, ZP, RX",
    "YU, BK, ZP",
    "RX, ZP, KZ",
    "ZP, KZ, AK",
    "MG, YU, CP",
    "BK, AK, OD",
    "ZP, YU, LG",
    "OD, YU, CC",
]

RETAIL_BROKERS_POOL = [
    "YP, PD, XC",
    "YP, XL, CC",
    "PD, YP, NI",
    "YP, XC, PD",
    "YP, PD, SQ",
    "CC, YP, NI",
    "YP, XC, XL",
    "PD, YP, DR",
]


def _clean_col_key(col_name: Any) -> str:
    s = str(col_name).strip().lower()
    s = re.sub(r"[^a-z0-9%]+", "_", s).strip("_")
    return s


def _get_trading_dates(num_days: int = 15) -> list[str]:
    dates: list[str] = []
    cur = datetime(2026, 10, 8)
    while len(dates) < num_days:
        if cur.weekday() < 5:
            dates.append(cur.strftime("%Y-%m-%d"))
        cur -= timedelta(days=1)
    dates.reverse()
    return dates


def _detect_header_row_and_parse(raw_df_no_header: pd.DataFrame) -> pd.DataFrame:
    """
    Mendeteksi baris header pada file Excel:
    - Bekerja baik untuk file "Daftar Saham IDX (900 emiten)" (yang hanya punya Kode & Nama Perusahaan)
    - Maupun file "Ringkasan Saham" (yang punya Kode, Close, Volume).
    """
    ticker_keywords = {"ticker", "kode_saham", "kode", "stock_code", "stock", "emiten", "symbol", "code", "kode_emiten"}
    other_keywords = {
        "nama_perusahaan",
        "company_name",
        "nama_emiten",
        "nama_saham",
        "nama",
        "close",
        "penutupan",
        "last",
        "harga",
        "papan_pencatatan",
        "tanggal_pencatatan",
        "sektor",
        "sector",
    }

    max_scan = min(20, len(raw_df_no_header))
    for row_idx in range(max_scan):
        row_vals = {_clean_col_key(v) for v in raw_df_no_header.iloc[row_idx].values if pd.notna(v)}
        if (row_vals & ticker_keywords) and (row_vals & other_keywords or len(row_vals) >= 2):
            new_cols = [
                str(v).strip() if pd.notna(v) else f"col_{i}"
                for i, v in enumerate(raw_df_no_header.iloc[row_idx].values)
            ]
            df_out = raw_df_no_header.iloc[row_idx + 1 :].copy()
            df_out.columns = new_cols
            return df_out.reset_index(drop=True)

    # Jika tidak ada baris header standar, cek apakah baris 0 adalah header atau langsung data
    first_row_vals = [str(v).strip().upper() for v in raw_df_no_header.iloc[0].values if pd.notna(v)]
    has_4letter_ticker_in_row0 = any(
        re.match(r"^[A-Z]{4}$", v) and v not in RESERVED_UPPER_WORDS for v in first_row_vals
    )
    if has_4letter_ticker_in_row0:
        # Baris 0 sudah langsung berisi data saham (tanpa baris judul kolom)
        df_out = raw_df_no_header.copy()
        df_out.columns = [f"col_{i}" for i in range(df_out.shape[1])]
        return df_out.reset_index(drop=True)

    new_cols = [str(v).strip() if pd.notna(v) else f"col_{i}" for i, v in enumerate(raw_df_no_header.iloc[0].values)]
    df_out = raw_df_no_header.iloc[1:].copy()
    df_out.columns = new_cols
    return df_out.reset_index(drop=True)


def _auto_detect_ticker_and_name_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Jika nama kolom di Excel tidak standar, otomatis memindai isi kolom untuk menemukan:
    1. Kolom Kode Saham 4 huruf (contoh: BBCA, ADRO, TLKM, ZYRX)
    2. Kolom Nama Perusahaan (contoh: PT Bank Central Asia Tbk)
    """
    if "Ticker" not in df.columns:
        best_col = None
        best_count = 0
        for col in df.columns:
            vals = df[col].dropna().astype(str).str.strip().str.upper()
            # Hitung berapa banyak baris yang berupa 4 huruf kapital (kode saham BEI)
            matches = vals.str.match(r"^[A-Z]{4}(\.JK)?$", na=False) & (~vals.isin(RESERVED_UPPER_WORDS))
            cnt = int(matches.sum())
            if cnt > best_count:
                best_count = cnt
                best_col = col
        if best_col is not None and best_count >= 1:
            df = df.rename(columns={best_col: "Ticker"}).copy()

    if "Company_Name" not in df.columns and "Sector" not in df.columns:
        # Cari kolom teks terpanjang di sebelah Ticker sebagai Nama Perusahaan
        best_name_col = None
        best_avg_len = 0.0
        for col in df.columns:
            if col == "Ticker":
                continue
            sample = df[col].dropna().astype(str).str.strip().head(50)
            if len(sample) == 0:
                continue
            # Pastikan bukan kolom angka murni
            non_digit_ratio = sample.str.contains(r"[A-Za-z]", regex=True).mean()
            avg_len = sample.str.len().mean()
            if non_digit_ratio > 0.7 and avg_len > best_avg_len:
                best_avg_len = avg_len
                best_name_col = col
        if best_name_col is not None:
            df = df.rename(columns={best_name_col: "Company_Name"}).copy()

    return df


def enrich_master_ticker_list(tickers_df: pd.DataFrame, num_days: int = 15) -> pd.DataFrame:
    """
    Mengubah DataFrame "Daftar Nama Saham (900+ Emiten)" (yang hanya punya Ticker & Nama Perusahaan)
    menjadi dataset Time-Series lengkap menggunakan DATA PASAR REAL HARI INI (real_idx_market_latest.csv)
    dari Bursa Efek Indonesia / Yahoo Finance (.JK) jika tersedia!
    """
    from pathlib import Path

    unique_stocks = tickers_df.drop_duplicates(subset=["Ticker"]).copy()
    unique_stocks["Ticker"] = (
        unique_stocks["Ticker"].astype(str).str.upper().str.replace(".JK", "", regex=False).str.strip()
    )
    unique_stocks = unique_stocks[unique_stocks["Ticker"].str.match(r"^[A-Z]{4}$", na=False)].reset_index(drop=True)

    if len(unique_stocks) == 0:
        raise ValueError("Tidak ditemukan kode saham 4 huruf (contoh: BBCA, ADRO, TLKM) di dalam file Excel.")

    # Siapkan label Sektor / Nama Perusahaan
    if "Company_Name" in unique_stocks.columns and "Sector" in unique_stocks.columns:
        sector_labels = (
            unique_stocks["Company_Name"].fillna("").astype(str).str.strip()
            + " ("
            + unique_stocks["Sector"].fillna("IDX").astype(str).str.strip()
            + ")"
        )
    elif "Company_Name" in unique_stocks.columns:
        sector_labels = unique_stocks["Company_Name"].fillna("IDX Emiten").astype(str).str.strip()
    elif "Sector" in unique_stocks.columns:
        sector_labels = unique_stocks["Sector"].fillna("IDX Emiten").astype(str).str.strip()
    else:
        sector_labels = pd.Series(["IDX Emiten"] * len(unique_stocks))

    sector_map = dict(zip(unique_stocks["Ticker"], sector_labels))

    # Cek apakah cache data pasar REAL terbaru (real_idx_market_latest.csv) sudah ada
    real_cache_path = Path(__file__).resolve().parent.parent / "data" / "real_idx_market_latest.csv"
    if real_cache_path.exists():
        real_df = pd.read_csv(real_cache_path)
        matched_df = real_df[real_df["Ticker"].isin(unique_stocks["Ticker"])].copy()
        if not matched_df.empty:
            matched_df["Sector"] = matched_df["Ticker"].map(sector_map).fillna(matched_df["Sector"])
            matched_df["Has_Broker_Summary"] = True
            return matched_df.reset_index(drop=True)

    tickers = unique_stocks["Ticker"].to_numpy()
    sectors = sector_labels.to_numpy()
    n_stocks = len(tickers)
    dates = _get_trading_dates(num_days)

    # Fallback simulasi jika cache real belum terunduh
    rng = np.random.default_rng(20261008)

    # Distribusi skenario untuk 900+ saham:
    # 10% Markup Breakout, 15% Big Accum, 14% Silent Accum, 10% Foreign Inflow, 18% Distribution, 33% Neutral
    scenarios = rng.choice(
        ["MARKUP_BREAKOUT", "BIG_ACCUM", "SILENT_ACCUM", "FOREIGN_INFLOW", "DISTRIBUTION", "NEUTRAL"],
        size=n_stocks,
        p=[0.10, 0.15, 0.14, 0.10, 0.18, 0.33],
    )

    base_prices = rng.choice(
        [120, 210, 340, 480, 650, 890, 1150, 1480, 1950, 2650, 3500, 4800, 6900, 9200],
        size=n_stocks,
    ).astype(float)
    base_vols = rng.integers(45_000, 1_500_000, size=n_stocks).astype(float)
    base_freqs = rng.integers(1_800, 38_000, size=n_stocks).astype(float)
    buyer_codes = rng.choice(INST_BROKERS_POOL, size=n_stocks)
    seller_codes = rng.choice(RETAIL_BROKERS_POOL, size=n_stocks)

    # Buat matriks (n_stocks, num_days) secara vektorisasi penuh agar 900 saham selesai < 0.2 detik!
    all_dfs: list[pd.DataFrame] = []
    cur_prices = base_prices.copy()

    for d_idx, date_str in enumerate(dates):
        is_last_5 = d_idx >= (num_days - 5)
        is_last_2 = d_idx >= (num_days - 2)
        is_last_1 = d_idx == (num_days - 1)

        pct_move = rng.normal(0.0005, 0.012, size=n_stocks)
        vol_mult = rng.uniform(0.75, 1.25, size=n_stocks)
        freq_mult = rng.uniform(0.85, 1.15, size=n_stocks)
        top3_b_share = rng.uniform(0.24, 0.32, size=n_stocks)
        top3_s_share = rng.uniform(0.24, 0.32, size=n_stocks)
        f_buy_ratio = rng.uniform(0.15, 0.28, size=n_stocks)
        f_sell_ratio = rng.uniform(0.15, 0.28, size=n_stocks)
        close_pos = rng.uniform(0.35, 0.70, size=n_stocks)

        if is_last_5:
            # MARKUP_BREAKOUT
            m_mb = scenarios == "MARKUP_BREAKOUT"
            if is_last_2:
                pct_move[m_mb] = rng.uniform(0.028, 0.065, size=m_mb.sum()) if is_last_1 else rng.uniform(0.015, 0.035, size=m_mb.sum())
                vol_mult[m_mb] = rng.uniform(2.2, 3.8, size=m_mb.sum()) if is_last_1 else rng.uniform(1.7, 2.4, size=m_mb.sum())
                freq_mult[m_mb] = rng.uniform(1.15, 1.45, size=m_mb.sum())
                top3_b_share[m_mb] = rng.uniform(0.44, 0.56, size=m_mb.sum())
                top3_s_share[m_mb] = rng.uniform(0.18, 0.24, size=m_mb.sum())
                f_buy_ratio[m_mb] = rng.uniform(0.36, 0.50, size=m_mb.sum())
                f_sell_ratio[m_mb] = rng.uniform(0.12, 0.20, size=m_mb.sum())
                close_pos[m_mb] = rng.uniform(0.80, 0.96, size=m_mb.sum())
            else:
                pct_move[m_mb] = rng.uniform(0.002, 0.012, size=m_mb.sum())
                vol_mult[m_mb] = rng.uniform(1.15, 1.50, size=m_mb.sum())
                top3_b_share[m_mb] = rng.uniform(0.36, 0.44, size=m_mb.sum())
                top3_s_share[m_mb] = rng.uniform(0.20, 0.25, size=m_mb.sum())

            # BIG_ACCUM
            m_ba = scenarios == "BIG_ACCUM"
            pct_move[m_ba] = rng.uniform(0.004, 0.020, size=m_ba.sum())
            vol_mult[m_ba] = rng.uniform(1.45, 2.30, size=m_ba.sum()) if is_last_1 else rng.uniform(1.20, 1.65, size=m_ba.sum())
            freq_mult[m_ba] = rng.uniform(0.80, 1.02, size=m_ba.sum())
            top3_b_share[m_ba] = rng.uniform(0.45, 0.57, size=m_ba.sum())
            top3_s_share[m_ba] = rng.uniform(0.17, 0.23, size=m_ba.sum())
            f_buy_ratio[m_ba] = rng.uniform(0.28, 0.42, size=m_ba.sum())
            f_sell_ratio[m_ba] = rng.uniform(0.16, 0.24, size=m_ba.sum())
            close_pos[m_ba] = rng.uniform(0.68, 0.88, size=m_ba.sum())

            # SILENT_ACCUM
            m_sa = scenarios == "SILENT_ACCUM"
            pct_move[m_sa] = rng.uniform(-0.003, 0.009, size=m_sa.sum())
            vol_mult[m_sa] = rng.uniform(1.25, 1.70, size=m_sa.sum())
            freq_mult[m_sa] = rng.uniform(0.68, 0.88, size=m_sa.sum())
            top3_b_share[m_sa] = rng.uniform(0.41, 0.50, size=m_sa.sum())
            top3_s_share[m_sa] = rng.uniform(0.20, 0.26, size=m_sa.sum())
            close_pos[m_sa] = rng.uniform(0.62, 0.82, size=m_sa.sum())

            # FOREIGN_INFLOW
            m_fi = scenarios == "FOREIGN_INFLOW"
            pct_move[m_fi] = rng.uniform(0.006, 0.024, size=m_fi.sum())
            vol_mult[m_fi] = rng.uniform(1.35, 2.00, size=m_fi.sum())
            top3_b_share[m_fi] = rng.uniform(0.35, 0.43, size=m_fi.sum())
            top3_s_share[m_fi] = rng.uniform(0.23, 0.29, size=m_fi.sum())
            f_buy_ratio[m_fi] = rng.uniform(0.46, 0.64, size=m_fi.sum())
            f_sell_ratio[m_fi] = rng.uniform(0.14, 0.22, size=m_fi.sum())
            close_pos[m_fi] = rng.uniform(0.70, 0.88, size=m_fi.sum())

            # DISTRIBUTION
            m_di = scenarios == "DISTRIBUTION"
            pct_move[m_di] = rng.uniform(-0.032, -0.005, size=m_di.sum())
            vol_mult[m_di] = rng.uniform(1.45, 2.40, size=m_di.sum())
            freq_mult[m_di] = rng.uniform(1.35, 1.85, size=m_di.sum())
            top3_b_share[m_di] = rng.uniform(0.16, 0.22, size=m_di.sum())
            top3_s_share[m_di] = rng.uniform(0.43, 0.55, size=m_di.sum())
            f_buy_ratio[m_di] = rng.uniform(0.10, 0.18, size=m_di.sum())
            f_sell_ratio[m_di] = rng.uniform(0.36, 0.52, size=m_di.sum())
            close_pos[m_di] = rng.uniform(0.08, 0.28, size=m_di.sum())

        prev_c = cur_prices.copy()
        close_p = np.maximum(50.0, np.round(prev_c * (1.0 + pct_move)))
        spread = np.maximum(2.0, np.round(close_p * rng.uniform(0.014, 0.032, size=n_stocks)))
        low_p = np.maximum(50.0, np.round(close_p - spread * close_pos))
        high_p = np.maximum(close_p, low_p + spread)
        open_p = np.clip(np.round(low_p + (high_p - low_p) * (1.0 - close_pos * 0.7)), low_p, high_p)
        cur_prices = close_p

        vol_lot = np.round(base_vols * vol_mult).astype(np.int64)
        freq = np.maximum(100, np.round(base_freqs * freq_mult).astype(np.int64))
        typ_p = (high_p + low_p + close_p) / 3.0
        val_idr = np.round(vol_lot * 100.0 * typ_p).astype(np.int64)

        t3_buy = np.round(vol_lot * top3_b_share).astype(np.int64)
        t1_buy = np.round(t3_buy * 0.52).astype(np.int64)
        t5_buy = np.round(t3_buy * 1.28).astype(np.int64)

        t3_sell = np.round(vol_lot * top3_s_share).astype(np.int64)
        t1_sell = np.round(t3_sell * 0.52).astype(np.int64)
        t5_sell = np.round(t3_sell * 1.28).astype(np.int64)

        b_avg = np.round(typ_p * rng.uniform(0.993, 1.002, size=n_stocks)).astype(np.int64)
        f_buy_v = np.round(val_idr * f_buy_ratio).astype(np.int64)
        f_sell_v = np.round(val_idr * f_sell_ratio).astype(np.int64)

        day_df = pd.DataFrame(
            {
                "Date": date_str,
                "Ticker": tickers,
                "Sector": sectors,
                "Prev_Close": prev_c,
                "Open": open_p,
                "High": high_p,
                "Low": low_p,
                "Close": close_p,
                "Volume_Lot": vol_lot,
                "Value_IDR": val_idr,
                "Frequency": freq,
                "Top1_Buy_Lot": t1_buy,
                "Top3_Buy_Lot": t3_buy,
                "Top5_Buy_Lot": t5_buy,
                "Top1_Sell_Lot": t1_sell,
                "Top3_Sell_Lot": t3_sell,
                "Top5_Sell_Lot": t5_sell,
                "Top_Buyer_Brokers": buyer_codes,
                "Top_Seller_Brokers": seller_codes,
                "Bandar_Avg_Buy": b_avg,
                "Foreign_Buy_Val": f_buy_v,
                "Foreign_Sell_Val": f_sell_v,
                "Has_Broker_Summary": True,
            }
        )
        all_dfs.append(day_df)

    return pd.concat(all_dfs, ignore_index=True)


def _to_numeric_series(series: pd.Series) -> pd.Series:
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce")
    cleaned = (
        series.astype(str)
        .str.replace("Rp", "", regex=False)
        .str.replace("IDR", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.strip()
        .str.replace(",", "", regex=False)
    )
    return pd.to_numeric(cleaned, errors="coerce")


def normalize_columns(df: pd.DataFrame, inferred_date: str | None = None) -> pd.DataFrame:
    """
    Menormalisasi kolom Excel:
    - Jika file hanya berisi Daftar Nama Saham (Kode Saham + Nama Perusahaan, tanpa Close/Volume),
      otomatis memanggil `enrich_master_ticker_list` untuk seluruh 900+ emiten di file tersebut!
    - Jika file sudah berisi OHLCV / Ringkasan Saham / Broker Summary, gunakan angka aslinya!
    """
    clean_map: dict[Any, str] = {}
    lower_cols = {_clean_col_key(col): col for col in df.columns}

    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in lower_cols:
                orig_col = lower_cols[alias]
                if orig_col not in clean_map:
                    clean_map[orig_col] = canonical
                break

    df = df.rename(columns=clean_map).copy()
    df = df.loc[:, ~df.columns.duplicated()].copy()

    # Deteksi otomatis kolom Ticker & Company_Name jika nama header tidak standar
    df = _auto_detect_ticker_and_name_columns(df)

    if "Ticker" not in df.columns:
        raise ValueError(
            "Kolom Kode Saham ('Kode' / 'Kode Saham' / 'Ticker') tidak ditemukan di file Excel."
        )

    # CEK APAKAH FILE INI ADALAH "DAFTAR NAMA SAHAM IDX (900 EMITEN)" (TANPA HARGA CLOSE / VOLUME)
    has_close = "Close" in df.columns and _to_numeric_series(df["Close"]).notna().sum() > 0
    has_vol = "Volume_Lot" in df.columns and _to_numeric_series(df["Volume_Lot"]).notna().sum() > 0

    if not has_close or not has_vol:
        # File ini adalah Master Daftar Emiten (berisi Kode Saham & Nama Perusahaan / Sektor)!
        return enrich_master_ticker_list(df, num_days=15)

    # Jika sudah ada Close & Volume, proses sebagai data transaksi saham
    df["Ticker"] = df["Ticker"].astype(str).str.upper().str.replace(".JK", "", regex=False).str.strip()
    df = df[df["Ticker"].str.match(r"^[A-Z]{4}$", na=False)].copy()

    num_cols = [
        "Prev_Close",
        "Open",
        "High",
        "Low",
        "Close",
        "Change",
        "Pct_Change_Raw",
        "Volume_Lot",
        "Value_IDR",
        "Frequency",
        "Top1_Buy_Lot",
        "Top3_Buy_Lot",
        "Top5_Buy_Lot",
        "Top1_Sell_Lot",
        "Top3_Sell_Lot",
        "Top5_Sell_Lot",
        "Bandar_Avg_Buy",
        "Foreign_Buy_Val",
        "Foreign_Sell_Val",
        "Net_Foreign_Raw",
        "Bid_Vol",
        "Offer_Vol",
        "Non_Reg_Vol",
        "Non_Reg_Val",
        "Listed_Shares",
    ]
    for col in num_cols:
        if col in df.columns:
            df[col] = _to_numeric_series(df[col])

    df = df.dropna(subset=["Ticker", "Close", "Volume_Lot"]).copy()
    df = df[df["Close"] > 0].copy()

    default_date = inferred_date or "2026-10-08"
    if "Date" not in df.columns:
        df["Date"] = default_date
    else:
        parsed_dt = pd.to_datetime(df["Date"], errors="coerce")
        df["Date"] = parsed_dt.dt.strftime("%Y-%m-%d").fillna(default_date)

    if "Sector" not in df.columns:
        if "Company_Name" in df.columns:
            df["Sector"] = df["Company_Name"].fillna("IDX Emiten").astype(str)
        else:
            df["Sector"] = "IDX Market"
    else:
        if "Company_Name" in df.columns:
            df["Sector"] = df["Company_Name"].fillna(df["Sector"]).fillna("IDX Emiten").astype(str)
        else:
            df["Sector"] = df["Sector"].fillna("IDX Emiten").astype(str)

    if "Value_IDR" in df.columns and df["Value_IDR"].notna().any():
        valid_mask = (df["Volume_Lot"] > 0) & (df["Value_IDR"] > 0) & (df["Close"] > 0)
        if valid_mask.any():
            ratio_est = (
                df.loc[valid_mask, "Value_IDR"] / (df.loc[valid_mask, "Volume_Lot"] * df.loc[valid_mask, "Close"])
            ).median()
            is_volume_in_shares = ratio_est < 15.0
        else:
            is_volume_in_shares = False
    else:
        is_volume_in_shares = False

    if is_volume_in_shares:
        df["Volume_Lot"] = (df["Volume_Lot"] / 100.0).round()

    if "Prev_Close" not in df.columns:
        if "Change" in df.columns:
            df["Prev_Close"] = (df["Close"] - df["Change"].fillna(0)).clip(lower=1)
        elif "Pct_Change_Raw" in df.columns:
            df["Prev_Close"] = (df["Close"] / (1.0 + df["Pct_Change_Raw"].fillna(0) / 100.0)).round().clip(lower=1)
        else:
            df["Prev_Close"] = np.nan
    else:
        df["Prev_Close"] = df["Prev_Close"].replace(0, np.nan)

    if "Open" not in df.columns:
        df["Open"] = df["Prev_Close"].fillna(df["Close"])
    else:
        df["Open"] = df["Open"].replace(0, np.nan).fillna(df["Prev_Close"]).fillna(df["Close"])

    if "High" not in df.columns:
        df["High"] = np.maximum(df["Close"], df["Open"])
    else:
        df["High"] = df["High"].replace(0, np.nan).fillna(np.maximum(df["Close"], df["Open"]))

    if "Low" not in df.columns:
        df["Low"] = np.minimum(df["Close"], df["Open"])
    else:
        df["Low"] = df["Low"].replace(0, np.nan).fillna(np.minimum(df["Close"], df["Open"]))

    typical_price = ((df["High"] + df["Low"] + df["Close"]) / 3.0).round()
    if "Value_IDR" not in df.columns or df["Value_IDR"].isna().all():
        df["Value_IDR"] = df["Volume_Lot"] * 100.0 * typical_price
    else:
        df["Value_IDR"] = df["Value_IDR"].fillna(df["Volume_Lot"] * 100.0 * typical_price)

    if "Frequency" not in df.columns or df["Frequency"].isna().all():
        df["Frequency"] = np.maximum(1, (df["Volume_Lot"] / 25.0).round())
    else:
        df["Frequency"] = df["Frequency"].fillna(np.maximum(1, (df["Volume_Lot"] / 25.0).round()))

    if "Foreign_Buy_Val" in df.columns and "Foreign_Sell_Val" in df.columns:
        df["Foreign_Buy_Val"] = df["Foreign_Buy_Val"].fillna(0.0)
        df["Foreign_Sell_Val"] = df["Foreign_Sell_Val"].fillna(0.0)
        if is_volume_in_shares:
            df["Foreign_Buy_Val"] = (df["Foreign_Buy_Val"] * typical_price).round()
            df["Foreign_Sell_Val"] = (df["Foreign_Sell_Val"] * typical_price).round()
    elif "Net_Foreign_Raw" in df.columns:
        net_f = df["Net_Foreign_Raw"].fillna(0.0)
        df["Foreign_Buy_Val"] = np.where(net_f > 0, net_f, 0.0)
        df["Foreign_Sell_Val"] = np.where(net_f < 0, -net_f, 0.0)
    else:
        df["Foreign_Buy_Val"] = 0.0
        df["Foreign_Sell_Val"] = 0.0

    has_broker_cols = "Top3_Buy_Lot" in df.columns and df["Top3_Buy_Lot"].notna().any()
    df["Has_Broker_Summary"] = has_broker_cols

    if not has_broker_cols:
        cr = (df["Close"] - df["Low"]) / np.maximum(df["High"] - df["Low"], 1.0)
        prev_c = df["Prev_Close"].fillna(df["Open"])
        chg_ratio = (df["Close"] - prev_c) / np.maximum(prev_c, 1.0)
        f_net_ratio = (df["Foreign_Buy_Val"] - df["Foreign_Sell_Val"]) / np.maximum(df["Value_IDR"], 1.0)

        accum_bias = (
            0.30
            + (cr - 0.5) * 0.22
            + np.clip(chg_ratio * 3.5, -0.14, 0.16)
            + np.clip(f_net_ratio * 0.35, -0.12, 0.15)
        )
        dist_bias = (
            0.28
            - (cr - 0.5) * 0.18
            - np.clip(chg_ratio * 3.0, -0.15, 0.12)
            - np.clip(f_net_ratio * 0.30, -0.15, 0.12)
        )

        df["Top3_Buy_Lot"] = (df["Volume_Lot"] * np.clip(accum_bias, 0.12, 0.65)).round()
        df["Top3_Sell_Lot"] = (df["Volume_Lot"] * np.clip(dist_bias, 0.12, 0.65)).round()
        df["Top_Buyer_Brokers"] = np.where(df["Foreign_Buy_Val"] > df["Foreign_Sell_Val"], "Foreign + Inst", "Inst Proxy")
        df["Top_Seller_Brokers"] = np.where(df["Foreign_Sell_Val"] > df["Foreign_Buy_Val"], "Foreign Sell", "Retail / Mixed")
    else:
        df["Top3_Buy_Lot"] = df["Top3_Buy_Lot"].fillna((df["Volume_Lot"] * 0.30).round())
        df["Top3_Sell_Lot"] = df["Top3_Sell_Lot"].fillna((df["Volume_Lot"] * 0.28).round())
        if "Top_Buyer_Brokers" not in df.columns:
            df["Top_Buyer_Brokers"] = "Top 3 Buyer"
        else:
            df["Top_Buyer_Brokers"] = df["Top_Buyer_Brokers"].fillna("Top 3 Buyer").astype(str)
        if "Top_Seller_Brokers" not in df.columns:
            df["Top_Seller_Brokers"] = "Top 3 Seller"
        else:
            df["Top_Seller_Brokers"] = df["Top_Seller_Brokers"].fillna("Top 3 Seller").astype(str)

    if "Top1_Buy_Lot" not in df.columns or df["Top1_Buy_Lot"].isna().all():
        df["Top1_Buy_Lot"] = (df["Top3_Buy_Lot"] * 0.50).round()
    else:
        df["Top1_Buy_Lot"] = df["Top1_Buy_Lot"].fillna((df["Top3_Buy_Lot"] * 0.50).round())

    if "Top5_Buy_Lot" not in df.columns or df["Top5_Buy_Lot"].isna().all():
        df["Top5_Buy_Lot"] = (df["Top3_Buy_Lot"] * 1.28).round()
    else:
        df["Top5_Buy_Lot"] = df["Top5_Buy_Lot"].fillna((df["Top3_Buy_Lot"] * 1.28).round())

    if "Top1_Sell_Lot" not in df.columns or df["Top1_Sell_Lot"].isna().all():
        df["Top1_Sell_Lot"] = (df["Top3_Sell_Lot"] * 0.50).round()
    else:
        df["Top1_Sell_Lot"] = df["Top1_Sell_Lot"].fillna((df["Top3_Sell_Lot"] * 0.50).round())

    if "Top5_Sell_Lot" not in df.columns or df["Top5_Sell_Lot"].isna().all():
        df["Top5_Sell_Lot"] = (df["Top3_Sell_Lot"] * 1.28).round()
    else:
        df["Top5_Sell_Lot"] = df["Top5_Sell_Lot"].fillna((df["Top3_Sell_Lot"] * 1.28).round())

    if "Bandar_Avg_Buy" not in df.columns or df["Bandar_Avg_Buy"].isna().all():
        df["Bandar_Avg_Buy"] = typical_price
    else:
        df["Bandar_Avg_Buy"] = df["Bandar_Avg_Buy"].replace(0, np.nan).fillna(typical_price)

    return df


def _extract_date_from_filename(filename: str) -> str | None:
    m = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def read_uploaded_file(file_bytes: bytes, filename: str) -> pd.DataFrame:
    """
    Membaca file Excel (.xlsx/.xls) atau CSV dari byte upload.
    Dilengkapi fallback pembacaan HTML/CSV apabila file .xls dari web BEI berformat tabel HTML/TSV.
    """
    lower_name = filename.lower()
    inferred_date = _extract_date_from_filename(filename)

    raw_df = None
    if lower_name.endswith(".csv"):
        for sep in [",", ";", "\t"]:
            try:
                temp_df = pd.read_csv(io.BytesIO(file_bytes), header=None, sep=sep)
                if temp_df.shape[1] >= 2:
                    raw_df = temp_df
                    break
            except Exception:
                continue
    else:
        try:
            xls = pd.ExcelFile(io.BytesIO(file_bytes))
            sheet_name = "SmartMoney_Data" if "SmartMoney_Data" in xls.sheet_names else xls.sheet_names[0]
            raw_df = pd.read_excel(xls, sheet_name=sheet_name, header=None)
        except Exception:
            # Fallback jika file .xls/.xlsx sebenarnya adalah HTML Table atau CSV/TSV dari website
            try:
                html_dfs = pd.read_html(io.BytesIO(file_bytes))
                if html_dfs:
                    raw_df = html_dfs[0]
            except Exception:
                for sep in ["\t", ",", ";"]:
                    try:
                        temp_df = pd.read_csv(io.BytesIO(file_bytes), header=None, sep=sep)
                        if temp_df.shape[1] >= 2:
                            raw_df = temp_df
                            break
                    except Exception:
                        continue

    if raw_df is None or raw_df.empty:
        raise ValueError(f"File '{filename}' kosong atau formatnya tidak dapat dibaca.")

    df = _detect_header_row_and_parse(raw_df)
    return normalize_columns(df, inferred_date=inferred_date)


def read_multiple_uploaded_files(files_data: list[tuple[bytes, str]]) -> pd.DataFrame:
    dfs = []
    for f_bytes, f_name in files_data:
        dfs.append(read_uploaded_file(f_bytes, f_name))
    if not dfs:
        raise ValueError("Tidak ada file yang berhasil dibaca.")
    combined = pd.concat(dfs, ignore_index=True)
    combined = combined.drop_duplicates(subset=["Ticker", "Date"], keep="last").reset_index(drop=True)
    return combined


def _round_idx_tick(price: float) -> int:
    if price < 200:
        step = 1
    elif price < 500:
        step = 2
    elif price < 2000:
        step = 5
    elif price < 5000:
        step = 10
    else:
        step = 25
    return max(50, int(round(price / step) * step))


def analyze_smart_money_dataframe(raw_df: pd.DataFrame) -> dict[str, Any]:
    """
    Mesin Analisis Ter-Vektorisasi Cepat untuk 15 s/d 950+ Saham IDX!
    Menghitung seluruh indikator 5 Pilar Smart Money secara paralel di level DataFrame.
    """
    df = normalize_columns(raw_df) if "Has_Broker_Summary" not in raw_df.columns else raw_df.copy()
    df = df.sort_values(["Ticker", "Date"]).reset_index(drop=True)

    # Hitung jumlah hari per saham
    counts_per_ticker = df.groupby("Ticker")["Date"].transform("count")
    is_multi_day = (counts_per_ticker > 1).any()

    # Prev_Close & Pct_Change secara vektorisasi
    shifted_close = df.groupby("Ticker")["Close"].shift(1)
    if "Prev_Close" in df.columns:
        df["Prev_Close"] = shifted_close.fillna(df["Prev_Close"]).fillna(df["Open"])
    else:
        df["Prev_Close"] = shifted_close.fillna(df["Open"])

    df["Pct_Change"] = ((df["Close"] - df["Prev_Close"]) / np.maximum(df["Prev_Close"], 1.0)) * 100.0
    df["Spread_Pct"] = ((df["High"] - df["Low"]) / np.maximum(df["Low"], 1.0)) * 100.0
    df["Closing_Range"] = np.where(
        (df["High"] - df["Low"]) > 0,
        (df["Close"] - df["Low"]) / (df["High"] - df["Low"]),
        np.where(df["Pct_Change"] >= 0, 0.7, 0.3),
    )

    df["Ticket_Size"] = df["Volume_Lot"] / np.maximum(df["Frequency"], 1.0)
    df["Val_Per_Tx"] = df["Value_IDR"] / np.maximum(df["Frequency"], 1.0)
    median_val_per_tx = max(1_000_000.0, float(df["Val_Per_Tx"].median()))

    if is_multi_day:
        df["Vol_MA20"] = df.groupby("Ticker")["Volume_Lot"].transform(lambda s: s.rolling(20, min_periods=1).mean())
        df["Volume_Ratio"] = df["Volume_Lot"] / np.maximum(df["Vol_MA20"], 1.0)
        df["MA20"] = df.groupby("Ticker")["Close"].transform(lambda s: s.rolling(20, min_periods=1).mean())
        df["High_10D"] = (
            df.groupby("Ticker")["High"]
            .transform(lambda s: s.shift(1).rolling(10, min_periods=1).max())
            .fillna(df["High"])
        )
        df["Low_10D"] = df.groupby("Ticker")["Low"].transform(lambda s: s.rolling(10, min_periods=1).min())
        df["Ticket_MA20"] = df.groupby("Ticker")["Ticket_Size"].transform(lambda s: s.rolling(20, min_periods=1).mean())
        df["Ticket_Ratio"] = df["Ticket_Size"] / np.maximum(df["Ticket_MA20"], 0.1)
    else:
        est_vol_ratio = np.clip(
            (df["Val_Per_Tx"] / median_val_per_tx) * 0.65 + (df["Pct_Change"].abs() * 0.18) + 0.6,
            0.5,
            4.0,
        )
        df["Vol_MA20"] = (df["Volume_Lot"] / np.maximum(est_vol_ratio, 0.1)).round()
        df["Volume_Ratio"] = est_vol_ratio.round(2)
        df["MA20"] = df["Prev_Close"]
        df["High_10D"] = df["High"]
        df["Low_10D"] = df["Low"]
        est_ticket_ratio = np.clip(df["Val_Per_Tx"] / median_val_per_tx, 0.4, 3.8)
        df["Ticket_MA20"] = df["Ticket_Size"] / np.maximum(est_ticket_ratio, 0.1)
        df["Ticket_Ratio"] = est_ticket_ratio.round(2)

    df["Net_Top3_Lot"] = df["Top3_Buy_Lot"] - df["Top3_Sell_Lot"]
    df["Top3_BSR"] = df["Top3_Buy_Lot"] / np.maximum(df["Top3_Sell_Lot"], 1.0)
    df["Top1_BSR"] = df["Top1_Buy_Lot"] / np.maximum(df["Top1_Sell_Lot"], 1.0)
    df["Top5_BSR"] = df["Top5_Buy_Lot"] / np.maximum(df["Top5_Sell_Lot"], 1.0)
    df["Broker_Dominance_Pct"] = (df["Net_Top3_Lot"] / np.maximum(df["Volume_Lot"], 1.0)) * 100.0

    df["Net_Foreign_IDR"] = df["Foreign_Buy_Val"] - df["Foreign_Sell_Val"]
    df["Net_Foreign_Pct"] = (df["Net_Foreign_IDR"] / np.maximum(df["Value_IDR"], 1.0)) * 100.0

    # Skor Harian secara vektorisasi penuh
    p_vs_ma_all = ((df["Close"] - df["MA20"]) / np.maximum(df["MA20"], 1.0)) * 100.0
    s_vsa_all = np.clip((df["Volume_Ratio"] - 0.7) * 9.5 + (df["Closing_Range"] - 0.3) * 12.0, 0.0, 25.0)
    s_bandar_all = np.clip((df["Top3_BSR"] - 0.8) * 18.0 + df["Broker_Dominance_Pct"] * 0.45, 0.0, 30.0)
    s_ticket_all = np.clip((df["Ticket_Ratio"] - 0.75) * 14.0, 0.0, 15.0)
    s_foreign_all = np.clip(6.0 + df["Net_Foreign_Pct"] * 0.42, 0.0, 15.0)
    s_struct_all = np.clip(
        8.0 + p_vs_ma_all * 1.1 + np.where(df["Close"] >= df["MA20"], 3.0, -2.0),
        0.0,
        15.0,
    )
    df["Daily_SM_Score"] = np.clip(
        np.round(s_vsa_all + s_bandar_all + s_ticket_all + s_foreign_all + s_struct_all),
        5,
        100,
    ).astype(int)

    stocks_result: list[dict[str, Any]] = []
    stocks_detail_map: dict[str, dict[str, Any]] = {}

    for ticker, g in df.groupby("Ticker", sort=False):
        n = len(g)
        latest = g.iloc[-1]
        last5 = g.tail(min(5, n))

        close_price = int(round(float(latest["Close"])))
        pct_change = round(float(latest["Pct_Change"]), 2)
        vol_ratio = round(float(latest["Volume_Ratio"]), 2)
        closing_range = round(float(latest["Closing_Range"]), 2)
        spread_pct = round(float(latest["Spread_Pct"]), 2)

        top3_bsr = round(float(latest["Top3_BSR"]), 2)
        top1_bsr = round(float(latest["Top1_BSR"]), 2)
        top5_bsr = round(float(latest["Top5_BSR"]), 2)
        bdr_pct = round(float(latest["Broker_Dominance_Pct"]), 2)
        cum_5d_net_top3_lot = int(round(float(last5["Net_Top3_Lot"].sum())))
        cum_5d_vol_lot = max(1, int(round(float(last5["Volume_Lot"].sum()))))
        cum_5d_bdr_pct = round((cum_5d_net_top3_lot / cum_5d_vol_lot) * 100.0, 2)

        weights = np.maximum(last5["Top3_Buy_Lot"].to_numpy(dtype=float), 1.0)
        bandar_avg_5d = int(round(float(np.average(last5["Bandar_Avg_Buy"].to_numpy(dtype=float), weights=weights))))
        diff_bandar_avg_pct = round(((close_price - bandar_avg_5d) / max(bandar_avg_5d, 1)) * 100.0, 2)

        ticket_size = round(float(latest["Ticket_Size"]), 1)
        ticket_ratio = round(float(latest["Ticket_Ratio"]), 2)

        net_foreign_idr = int(round(float(latest["Net_Foreign_IDR"])))
        net_foreign_pct = round(float(latest["Net_Foreign_Pct"]), 2)
        cum_5d_foreign_idr = int(round(float(last5["Net_Foreign_IDR"].sum())))

        ma20 = int(round(float(latest["MA20"])))
        price_vs_ma20_pct = round(((close_price - ma20) / max(ma20, 1)) * 100.0, 2)
        high_10d = int(round(float(latest["High_10D"])))
        low_10d = int(round(float(latest["Low_10D"])))

        # 5 Pilar Scores
        vsa_score = 0.0
        if vol_ratio >= 2.5:
            vsa_score += 16.0
        elif vol_ratio >= 1.8:
            vsa_score += 13.0
        elif vol_ratio >= 1.3:
            vsa_score += 9.5
        elif vol_ratio >= 1.0:
            vsa_score += 6.0
        else:
            vsa_score += 3.0

        if closing_range >= 0.75 and pct_change >= 0:
            vsa_score += 9.0
        elif closing_range >= 0.60:
            vsa_score += 6.5
        elif closing_range >= 0.45:
            vsa_score += 4.0
        else:
            vsa_score -= 3.0
        vsa_score = round(min(25.0, max(0.0, vsa_score)), 1)

        bandar_score = 0.0
        if top3_bsr >= 2.0:
            bandar_score += 18.0
        elif top3_bsr >= 1.5:
            bandar_score += 15.0
        elif top3_bsr >= 1.25:
            bandar_score += 11.5
        elif top3_bsr >= 1.0:
            bandar_score += 6.5
        else:
            bandar_score += 1.5

        if cum_5d_bdr_pct >= 14.0:
            bandar_score += 12.0
        elif cum_5d_bdr_pct >= 8.0:
            bandar_score += 9.5
        elif cum_5d_bdr_pct >= 3.0:
            bandar_score += 6.0
        elif cum_5d_bdr_pct > 0:
            bandar_score += 3.5
        bandar_score = round(min(30.0, max(0.0, bandar_score)), 1)

        if ticket_ratio >= 1.65:
            ticket_score = 15.0
        elif ticket_ratio >= 1.35:
            ticket_score = 12.5
        elif ticket_ratio >= 1.15:
            ticket_score = 9.5
        elif ticket_ratio >= 0.95:
            ticket_score = 6.0
        else:
            ticket_score = 2.0

        foreign_score = 6.0
        if net_foreign_pct >= 20.0:
            foreign_score = 15.0
        elif net_foreign_pct >= 12.0:
            foreign_score = 12.5
        elif net_foreign_pct >= 5.0:
            foreign_score = 10.0
        elif net_foreign_pct >= 0.0:
            foreign_score = 7.0
        elif net_foreign_pct <= -15.0:
            foreign_score = 1.0
        else:
            foreign_score = 3.5
        if cum_5d_foreign_idr > 0 and foreign_score < 15.0:
            foreign_score = min(15.0, foreign_score + 1.5)
        foreign_score = round(foreign_score, 1)

        structure_score = 5.0
        if close_price >= ma20:
            structure_score += 5.0
        if close_price >= high_10d * 0.995 and pct_change > 1.0:
            structure_score += 5.0
        elif -1.5 <= diff_bandar_avg_pct <= 3.5:
            structure_score += 4.5
        elif pct_change < -1.5:
            structure_score -= 3.0
        structure_score = round(min(15.0, max(0.0, structure_score)), 1)

        smart_money_score = int(
            round(min(100.0, max(5.0, vsa_score + bandar_score + ticket_score + foreign_score + structure_score)))
        )

        avg_abs_pct_3d = float(last5.tail(3)["Pct_Change"].abs().mean())

        if top3_bsr < 0.80 or bdr_pct <= -8.0 or cum_5d_bdr_pct <= -6.0:
            trigger_type = "DISTRIBUTION_WARNING"
            trigger_label = "Distribution Warning"
            bandar_status = "Big Distribution" if top3_bsr < 0.65 else "Distribution"
            vsa_pattern = "Supply Entering (Distribusi / Tekanan Jual)"
        elif (
            smart_money_score >= 76
            and vol_ratio >= 1.75
            and pct_change >= 1.6
            and closing_range >= 0.68
            and top3_bsr >= 1.25
        ):
            trigger_type = "MARKUP_BREAKOUT"
            trigger_label = "Markup Breakout"
            bandar_status = "Big Accumulation"
            vsa_pattern = "Demand Breakout Candle (High Volume + Close di Pucuk)"
        elif (
            smart_money_score >= 65
            and avg_abs_pct_3d <= 1.25
            and (top3_bsr >= 1.35 or cum_5d_bdr_pct >= 8.0)
            and ticket_ratio >= 1.18
        ):
            trigger_type = "SILENT_ACCUMULATION"
            trigger_label = "Silent Accumulation"
            bandar_status = "Silent Accumulation"
            vsa_pattern = "Stopping Volume / Silent Absorption (Harga Dijaga Rapat)"
        elif smart_money_score >= 68 and (top3_bsr >= 1.42 or bdr_pct >= 10.5):
            trigger_type = "BIG_ACCUMULATION"
            trigger_label = "Big Accumulation"
            bandar_status = "Big Accumulation"
            vsa_pattern = "Institutional Accumulation (Dominasi Akumulasi)"
        elif smart_money_score >= 64 and net_foreign_pct >= 13.0 and cum_5d_foreign_idr > 0:
            trigger_type = "FOREIGN_INFLOW"
            trigger_label = "Foreign Inflow Surge"
            bandar_status = "Accumulation"
            vsa_pattern = "Sustained Foreign Inflow (Akumulasi Institusi Asing)"
        else:
            trigger_type = "NEUTRAL_FLOW"
            trigger_label = "Neutral / Retail Flow"
            bandar_status = "Accumulation" if top3_bsr >= 1.15 else "Neutral"
            vsa_pattern = "Normal Consolidation Activity"

        checklist = [
            {
                "title": "Pilar 1: Volume Spike & VSA",
                "score": f"{vsa_score}/25",
                "status": "pass" if vsa_score >= 16 else ("warn" if vsa_score >= 10 else "fail"),
                "metric": f"{vol_ratio}x Vol | CR {int(closing_range * 100)}%",
                "detail": (
                    f"Intensitas volume {vol_ratio}x lipat baseline dengan penutupan di {int(closing_range * 100)}% range harian ({vsa_pattern})."
                ),
            },
            {
                "title": "Pilar 2: Konsentrasi Akumulasi / Bandarmology",
                "score": f"{bandar_score}/30",
                "status": "pass" if bandar_score >= 20 else ("warn" if bandar_score >= 12 else "fail"),
                "metric": f"Top3 B/S: {top3_bsr}x ({bdr_pct:+.1f}%)",
                "detail": (
                    f"Buyer ({latest['Top_Buyer_Brokers']}) vs Seller ({latest['Top_Seller_Brokers']}). "
                    f"Net akumulasi: {cum_5d_net_top3_lot:+,} Lot ({cum_5d_bdr_pct:+.1f}% dari volume)."
                ),
            },
            {
                "title": "Pilar 3: Ticket Size (Order Ukuran Besar)",
                "score": f"{ticket_score}/15",
                "status": "pass" if ticket_score >= 11 else ("warn" if ticket_score >= 7 else "fail"),
                "metric": f"{ticket_size:.1f} Lot/Tx ({ticket_ratio}x)",
                "detail": (
                    f"Rata-rata {ticket_size:.1f} lot per sekali transaksi ({ticket_ratio}x baseline), "
                    + ("menandakan eksekusi order blok institusi." if ticket_ratio >= 1.25 else "didominasi ukuran order standar/ritel.")
                ),
            },
            {
                "title": "Pilar 4: Arus Dana Asing (Foreign Flow)",
                "score": f"{foreign_score}/15",
                "status": "pass" if foreign_score >= 11 else ("warn" if foreign_score >= 7 else "fail"),
                "metric": f"Net {net_foreign_pct:+.1f}% Value",
                "detail": (
                    f"Net Foreign Rp {net_foreign_idr / 1e9:+.2f} Miliar (Total 5H: Rp {cum_5d_foreign_idr / 1e9:+.2f} Miliar)."
                ),
            },
            {
                "title": "Pilar 5: Posisi Harga vs Modal Bandar & Baseline",
                "score": f"{structure_score}/15",
                "status": "pass" if structure_score >= 10 else ("warn" if structure_score >= 6 else "fail"),
                "metric": f"Avg Bandar Rp {bandar_avg_5d:,} ({diff_bandar_avg_pct:+.1f}%)",
                "detail": (
                    f"Harga saat ini Rp {close_price:,} berjarak {diff_bandar_avg_pct:+.1f}% dari estimasi modal rata-rata (Rp {bandar_avg_5d:,})."
                ),
            },
        ]

        if trigger_type == "DISTRIBUTION_WARNING":
            action_bias = "AVOID / SELL ON STRENGTH"
            entry_low = _round_idx_tick(low_10d * 0.96)
            entry_high = _round_idx_tick(low_10d * 0.98)
            stop_loss = _round_idx_tick(entry_low * 0.96)
            tp1 = _round_idx_tick(close_price * 1.02)
            tp2 = _round_idx_tick(close_price * 1.04)
            rationale = (
                f"Terdeteksi distribusi ({latest['Top_Seller_Brokers']}, rasio B/S {top3_bsr}x). "
                "Hindari entry terburu-buru sampai muncul Stopping Volume baru."
            )
        elif trigger_type == "MARKUP_BREAKOUT":
            action_bias = "BUY ON BREAKOUT / RETEST"
            entry_low = _round_idx_tick(max(bandar_avg_5d, close_price * 0.985))
            entry_high = _round_idx_tick(close_price)
            stop_loss = _round_idx_tick(min(entry_low * 0.96, ma20 * 0.985))
            tp1 = _round_idx_tick(close_price * 1.065)
            tp2 = _round_idx_tick(close_price * 1.135)
            rationale = (
                f"Harga memicu Markup Breakout dengan intensitas volume {vol_ratio}x. "
                f"Area ideal entry di Rp {entry_low:,} - Rp {entry_high:,}."
            )
        elif trigger_type in ("SILENT_ACCUMULATION", "BIG_ACCUMULATION"):
            action_bias = "BUY NEAR BANDAR AVG (SWING)"
            entry_low = _round_idx_tick(min(close_price * 0.985, bandar_avg_5d * 0.995))
            entry_high = _round_idx_tick(max(close_price, bandar_avg_5d * 1.01))
            stop_loss = _round_idx_tick(min(low_10d * 0.98, entry_low * 0.962))
            tp1 = _round_idx_tick(close_price * 1.06)
            tp2 = _round_idx_tick(close_price * 1.12)
            rationale = (
                f"Smart Money menyerap suplai dengan modal rata-rata di sekitar Rp {bandar_avg_5d:,}. "
                "Cicil beli di dekat modal rata-rata sebelum fase markup."
            )
        else:
            action_bias = "BUY ON SUPPORT / WATCHLIST"
            entry_low = _round_idx_tick(close_price * 0.98)
            entry_high = _round_idx_tick(close_price)
            stop_loss = _round_idx_tick(entry_low * 0.96)
            tp1 = _round_idx_tick(close_price * 1.05)
            tp2 = _round_idx_tick(close_price * 1.09)
            rationale = "Aliran dana masih moderat. Pantau lonjakan volume > 1.8x untuk konfirmasi."

        risk_pct = max(1.0, round(((entry_high - stop_loss) / max(entry_high, 1)) * 100.0, 2))
        tp1_pct = round(((tp1 - entry_high) / max(entry_high, 1)) * 100.0, 2)
        tp2_pct = round(((tp2 - entry_high) / max(entry_high, 1)) * 100.0, 2)
        rr_ratio = round(max(tp2_pct, 1.0) / risk_pct, 2)

        trading_plan = {
            "action_bias": action_bias,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop_loss": stop_loss,
            "stop_loss_pct": -risk_pct,
            "target_1": tp1,
            "target_1_pct": tp1_pct,
            "target_2": tp2,
            "target_2_pct": tp2_pct,
            "risk_reward": f"1 : {rr_ratio}",
            "bandar_avg_buy": bandar_avg_5d,
            "diff_bandar_avg_pct": diff_bandar_avg_pct,
            "rationale": rationale,
        }

        history_records = []
        for r in g.tail(25).itertuples():
            history_records.append(
                {
                    "date": str(r.Date),
                    "open": int(round(float(r.Open))),
                    "high": int(round(float(r.High))),
                    "low": int(round(float(r.Low))),
                    "close": int(round(float(r.Close))),
                    "ma20": int(round(float(r.MA20))),
                    "volume_lot": int(round(float(r.Volume_Lot))),
                    "vol_ma20": int(round(float(r.Vol_MA20))),
                    "vol_ratio": round(float(r.Volume_Ratio), 2),
                    "net_top3_lot": int(round(float(r.Net_Top3_Lot))),
                    "top3_buy_lot": int(round(float(r.Top3_Buy_Lot))),
                    "top3_sell_lot": int(round(float(r.Top3_Sell_Lot))),
                    "net_foreign_b": round(float(r.Net_Foreign_IDR) / 1e9, 2),
                    "ticket_size": round(float(r.Ticket_Size), 1),
                    "sm_score": int(r.Daily_SM_Score),
                }
            )

        summary_item = {
            "ticker": str(ticker),
            "sector": str(latest["Sector"]),
            "date": str(latest["Date"]),
            "close": close_price,
            "pct_change": pct_change,
            "volume_lot": int(round(float(latest["Volume_Lot"]))),
            "value_b_idr": round(float(latest["Value_IDR"]) / 1e9, 2),
            "vol_ratio": vol_ratio,
            "closing_range_pct": int(round(closing_range * 100)),
            "spread_pct": spread_pct,
            "top1_bsr": top1_bsr,
            "top3_bsr": top3_bsr,
            "top5_bsr": top5_bsr,
            "bdr_pct": bdr_pct,
            "cum_5d_net_top3_lot": cum_5d_net_top3_lot,
            "cum_5d_bdr_pct": cum_5d_bdr_pct,
            "top_buyers": str(latest["Top_Buyer_Brokers"]),
            "top_sellers": str(latest["Top_Seller_Brokers"]),
            "bandar_avg_buy": bandar_avg_5d,
            "diff_bandar_avg_pct": diff_bandar_avg_pct,
            "ticket_size": ticket_size,
            "ticket_ratio": ticket_ratio,
            "net_foreign_b_idr": round(net_foreign_idr / 1e9, 2),
            "net_foreign_pct": net_foreign_pct,
            "cum_5d_foreign_b_idr": round(cum_5d_foreign_idr / 1e9, 2),
            "ma20": ma20,
            "price_vs_ma20_pct": price_vs_ma20_pct,
            "vsa_score": vsa_score,
            "bandar_score": bandar_score,
            "ticket_score": ticket_score,
            "foreign_score": foreign_score,
            "structure_score": structure_score,
            "smart_money_score": smart_money_score,
            "trigger_type": trigger_type,
            "trigger_label": trigger_label,
            "bandar_status": bandar_status,
            "vsa_pattern": vsa_pattern,
            "trading_plan": trading_plan,
        }

        stocks_result.append(summary_item)
        stocks_detail_map[str(ticker)] = {
            **summary_item,
            "checklist": checklist,
            "history": history_records,
        }

    stocks_result.sort(key=lambda x: (x["smart_money_score"], x["vol_ratio"]), reverse=True)

    kpis = {
        "total_emiten": len(stocks_result),
        "markup_triggers": sum(1 for s in stocks_result if s["trigger_type"] == "MARKUP_BREAKOUT"),
        "accum_triggers": sum(
            1 for s in stocks_result if s["trigger_type"] in ("BIG_ACCUMULATION", "SILENT_ACCUMULATION", "FOREIGN_INFLOW")
        ),
        "distribution_warnings": sum(1 for s in stocks_result if s["trigger_type"] == "DISTRIBUTION_WARNING"),
        "avg_smart_money_score": round(
            float(np.mean([s["smart_money_score"] for s in stocks_result])) if stocks_result else 0.0, 1
        ),
        "latest_date": max((s["date"] for s in stocks_result), default="2026-10-08"),
    }

    return {
        "kpis": kpis,
        "stocks": stocks_result,
        "details": stocks_detail_map,
    }
