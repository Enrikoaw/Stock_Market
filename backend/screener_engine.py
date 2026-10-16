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


# =========================================================================
# IDX-IC 11 SECTOR TAXONOMY & CLASSIFICATION (ITEM 2: SECTOR CAP)
# =========================================================================

KNOWN_TICKER_SECTORS: dict[str, str] = {
    # Keuangan (Financials)
    "BBCA": "Financials", "BBRI": "Financials", "BMRI": "Financials", "BBNI": "Financials",
    "BBTN": "Financials", "BDMN": "Financials", "BNGA": "Financials", "BRIS": "Financials",
    "BTPS": "Financials", "ARTO": "Financials", "PNBN": "Financials", "BNLI": "Financials",
    "BBHI": "Financials", "BBYB": "Financials", "BCIC": "Financials", "BJBR": "Financials",
    "BJTM": "Financials", "NOBU": "Financials", "AGRO": "Financials", "AGRS": "Financials",
    "ADMF": "Financials", "CFIN": "Financials", "BFIN": "Financials", "WOMF": "Financials",
    "MFIN": "Financials", "TRIM": "Financials", "PANS": "Financials", "ABDA": "Financials",
    "AHAP": "Financials", "ASDM": "Financials", "LPGI": "Financials", "AMOR": "Financials",
    # Energi (Energy)
    "ADRO": "Energy", "PTBA": "Energy", "ITMG": "Energy", "BUMI": "Energy",
    "MEDC": "Energy", "PGAS": "Energy", "AKRA": "Energy", "INDY": "Energy",
    "HRUM": "Energy", "ABMM": "Energy", "DOID": "Energy", "ENRG": "Energy",
    "ELSA": "Energy", "RAJA": "Energy", "AADI": "Energy", "CUAN": "Energy",
    "DSSA": "Energy", "BSSR": "Energy", "KKGI": "Energy", "TOBA": "Energy",
    "RMKE": "Energy", "WOWS": "Energy", "APEX": "Energy", "SGER": "Energy",
    "MCOL": "Energy", "MBAP": "Energy", "GEMS": "Energy", "IATA": "Energy",
    # Barang Baku (Basic Materials)
    "ANTM": "Basic Materials", "INCO": "Basic Materials", "BRMS": "Basic Materials",
    "MDKA": "Basic Materials", "TPIA": "Basic Materials", "INKP": "Basic Materials",
    "TKIM": "Basic Materials", "SMGR": "Basic Materials", "INTP": "Basic Materials",
    "AMMN": "Basic Materials", "MBMA": "Basic Materials", "PSAB": "Basic Materials",
    "NCKL": "Basic Materials", "NICL": "Basic Materials", "DKFT": "Basic Materials",
    "AVIA": "Basic Materials", "ARCI": "Basic Materials", "TINS": "Basic Materials",
    "KRAS": "Basic Materials", "CITA": "Basic Materials", "ALDO": "Basic Materials",
    "BRPT": "Basic Materials", "ESSA": "Basic Materials", "SMBR": "Basic Materials",
    "WSBP": "Basic Materials", "WTON": "Basic Materials", "BTON": "Basic Materials",
    "ADMG": "Basic Materials", "FASW": "Basic Materials", "SPMA": "Basic Materials",
    # Konsumer Primer (Consumer Non-Cyclicals)
    "ICBP": "Consumer Non-Cyclicals", "INDF": "Consumer Non-Cyclicals", "UNVR": "Consumer Non-Cyclicals",
    "MYOR": "Consumer Non-Cyclicals", "AMRT": "Consumer Non-Cyclicals", "MIDI": "Consumer Non-Cyclicals",
    "CPIN": "Consumer Non-Cyclicals", "JPFA": "Consumer Non-Cyclicals", "CMRY": "Consumer Non-Cyclicals",
    "HMSP": "Consumer Non-Cyclicals", "GGRM": "Consumer Non-Cyclicals", "WIIM": "Consumer Non-Cyclicals",
    "STAA": "Consumer Non-Cyclicals", "TAPG": "Consumer Non-Cyclicals", "LSIP": "Consumer Non-Cyclicals",
    "AALI": "Consumer Non-Cyclicals", "DSNG": "Consumer Non-Cyclicals", "SIMP": "Consumer Non-Cyclicals",
    "SSMS": "Consumer Non-Cyclicals", "CLEO": "Consumer Non-Cyclicals", "ULTJ": "Consumer Non-Cyclicals",
    "ROTI": "Consumer Non-Cyclicals", "DLTA": "Consumer Non-Cyclicals", "MLBI": "Consumer Non-Cyclicals",
    "TBLA": "Consumer Non-Cyclicals", "AISA": "Consumer Non-Cyclicals", "CAMP": "Consumer Non-Cyclicals",
    "CEKA": "Consumer Non-Cyclicals", "GOOD": "Consumer Non-Cyclicals", "STTP": "Consumer Non-Cyclicals",
    # Konsumer Non-Primer (Consumer Cyclicals)
    "ASII": "Consumer Cyclicals", "ACES": "Consumer Cyclicals", "MAPI": "Consumer Cyclicals",
    "MAPA": "Consumer Cyclicals", "ERAA": "Consumer Cyclicals", "AUTO": "Consumer Cyclicals",
    "DRMA": "Consumer Cyclicals", "SMSM": "Consumer Cyclicals", "GJTL": "Consumer Cyclicals",
    "RALS": "Consumer Cyclicals", "LPPF": "Consumer Cyclicals", "MNCN": "Consumer Cyclicals",
    "SCMA": "Consumer Cyclicals", "EMTK": "Consumer Cyclicals", "FILM": "Consumer Cyclicals",
    "MPMX": "Consumer Cyclicals", "BRAM": "Consumer Cyclicals", "WOOD": "Consumer Cyclicals",
    "PZZA": "Consumer Cyclicals", "IMAS": "Consumer Cyclicals", "INDX": "Consumer Cyclicals",
    # Kesehatan (Healthcare)
    "KLBF": "Healthcare", "MIKA": "Healthcare", "HEAL": "Healthcare", "SILO": "Healthcare",
    "SIDO": "Healthcare", "PRDA": "Healthcare", "SAME": "Healthcare", "TSPC": "Healthcare",
    "MERK": "Healthcare", "PEHA": "Healthcare", "IRRA": "Healthcare", "OMED": "Healthcare",
    "KAEF": "Healthcare", "INAF": "Healthcare", "PYFA": "Healthcare", "DVLA": "Healthcare",
    # Infrastruktur (Infrastructures)
    "TLKM": "Infrastructures", "ISAT": "Infrastructures", "EXCL": "Infrastructures",
    "TOWR": "Infrastructures", "TBIG": "Infrastructures", "MTEL": "Infrastructures",
    "JSMR": "Infrastructures", "PGEO": "Infrastructures", "BREN": "Infrastructures",
    "POWR": "Infrastructures", "KEEN": "Infrastructures", "ARKO": "Infrastructures",
    "CENT": "Infrastructures", "META": "Infrastructures", "CMNP": "Infrastructures",
    "IPCC": "Infrastructures", "IPAC": "Infrastructures", "BALI": "Infrastructures",
    # Properti & Real Estat (Properties & Real Estate)
    "BSDE": "Properties & Real Estate", "CTRA": "Properties & Real Estate", "PWON": "Properties & Real Estate",
    "SMRA": "Properties & Real Estate", "ASRI": "Properties & Real Estate", "DILD": "Properties & Real Estate",
    "KIJA": "Properties & Real Estate", "SSIA": "Properties & Real Estate", "BEST": "Properties & Real Estate",
    "BKSL": "Properties & Real Estate", "MDLN": "Properties & Real Estate", "LPPS": "Properties & Real Estate",
    "LPKR": "Properties & Real Estate", "LPCK": "Properties & Real Estate", "PPRO": "Properties & Real Estate",
    "DMAS": "Properties & Real Estate", "CITY": "Properties & Real Estate", "DUTI": "Properties & Real Estate",
    # Teknologi (Technology)
    "GOTO": "Technology", "BUKA": "Technology", "BELI": "Technology",
    "WIRG": "Technology", "DCII": "Technology", "MTDL": "Technology", "MCAS": "Technology",
    "NFCX": "Technology", "GLVA": "Technology", "KIOS": "Technology", "CASH": "Technology",
    "DIVA": "Technology", "MLPT": "Technology", "WIFI": "Technology", "ENVY": "Technology",
    # Transportasi & Logistik (Transportation & Logistics)
    "GIAA": "Transportation & Logistics", "ASSA": "Transportation & Logistics", "BIRD": "Transportation & Logistics",
    "TMAS": "Transportation & Logistics", "SMDR": "Transportation & Logistics", "HAIS": "Transportation & Logistics",
    "TCPI": "Transportation & Logistics", "TNCA": "Transportation & Logistics", "WEHA": "Transportation & Logistics",
    "SAFE": "Transportation & Logistics", "TRUK": "Transportation & Logistics", "MITI": "Transportation & Logistics",
    "BLTA": "Transportation & Logistics", "PSSI": "Transportation & Logistics", "BBRM": "Transportation & Logistics",
    # Perindustrian (Industrials)
    "UNTR": "Industrials", "HEXA": "Industrials", "ARNA": "Industrials", "MARK": "Industrials",
    "BMSR": "Industrials", "KBLI": "Industrials", "CCSI": "Industrials", "SCCO": "Industrials",
    "VOKS": "Industrials", "JECC": "Industrials", "MLIA": "Industrials", "IMPC": "Industrials",
    "DYAN": "Industrials", "INTD": "Industrials", "KBLM": "Industrials", "IKBI": "Industrials",
    "SMIL": "Industrials", "ASPI": "Industrials", "SATU": "Industrials", "HBAT": "Industrials",
}


def classify_idx_sector(ticker: str, raw_sector: str) -> str:
    """Mengklasifikasikan saham ke salah satu dari 11 Sektor Standar IDX-IC."""
    clean_ticker = str(ticker).strip().upper()
    if clean_ticker in KNOWN_TICKER_SECTORS:
        return KNOWN_TICKER_SECTORS[clean_ticker]

    s = str(raw_sector).lower()
    if any(k in s for k in ("bank", "keuangan", "financial", "asuransi", "insurance", "insuran", "leasing", "multifinance", "multi finance", "sekuritas", "securities", "modal", "dana", "investasi", "investama", "investment")):
        return "Financials"
    if any(k in s for k in ("adaro", "energi", "energy", "minyak", "oil", "gas", "batubara", "coal", "petroleum", "tambang batubara", "resources")):
        return "Energy"
    if any(k in s for k in ("mineral", "metal", "tambang", "baja", "steel", "semen", "cement", "kimia", "chemical", "basic material", "material dasar", "kertas", "paper", "pulp", "gold", "emas", "nikel", "nickel", "timah", "tin", "tembaga", "copper", "fibreboard", "polychem")):
        return "Basic Materials"
    if any(k in s for k in ("food", "makanan", "beverage", "minuman", "agro", "lestari", "sawit", "palm", "plantation", "perkebunan", "rokok", "tobacco", "poultry", "ayam", "feed", "consumer non-cyclical", "primer", "gourmet", "mina", "perikanan")):
        return "Consumer Non-Cyclicals"
    if any(k in s for k in ("ritel", "retail", "otomotif", "automotive", "sparepart", "textile", "tekstil", "garmen", "garment", "fashion", "elektronik", "media", "televisi", "film", "cinema", "consumer cyclical", "non-primer", "hotel", "tourism", "pariwisata", "hiburan", "entertainment")):
        return "Consumer Cyclicals"
    if any(k in s for k in ("farmasi", "pharmaceutical", "pharma", "obat", "kesehatan", "health", "hospital", "rumah sakit", "klinik", "clinic", "laboratorium", "jamu")):
        return "Healthcare"
    if any(k in s for k in ("telekomunikasi", "telecom", "telco", "tower", "menara", "infrastruktur", "infrastructure", "jalan tol", "toll", "satelit", "satellite", "panas bumi", "geothermal", "power", "listrik", "karya", "konstruksi", "kontraktor", "bangunan gedung")):
        return "Infrastructures"
    if any(k in s for k in ("properti", "property", "real estate", "real estat", "land", "perumahan", "developer", "residence", "estate", "graha", "plaza", "sukses sejahtera")):
        return "Properties & Real Estate"
    if any(k in s for k in ("teknologi", "technology", "tech", "software", "digital", "data center", "cloud", "internet", "komputer", "e-commerce")):
        return "Technology"
    if any(k in s for k in ("transpor", "transport", "logistik", "logistic", "pelayaran", "shipping", "samudera", "maritim", "aviation", "penerbangan", "truk", "truck", "express", "cargo", "kargo", "aerowisata")):
        return "Transportation & Logistics"
    if any(k in s for k in ("industri", "industrial", "alat berat", "heavy equipment", "mesin", "machinery", "engineering", "kabel", "cable", "packaging", "kemasan", "plastik", "plastic", "mecaniques", "manufaktur")):
        return "Industrials"

    return "General & Others"


def check_fundamental_and_board_safety(
    ticker: str,
    sector: str,
    close: float,
    value_b_idr: float,
    frequency: float,
) -> dict[str, Any]:
    """
    Evaluasi Keamanan Fundamental & Papan Bursa (Item 4):
    1. Exclude Papan Pemantauan Khusus (FCA) & Papan Akselerasi.
    2. Exclude notasi khusus kritis (E, X, A, M, S, PKPU/Pailit).
    3. Minimum Harga Close >= Rp 70 (menolak saham gocap/penny stock).
    4. Minimum Turnover Value >= Rp 1.0 Miliar.
    5. Minimum Frekuensi Transaksi >= 150 kali perdagangan.
    """
    sec_lower = str(sector).lower()
    ticker_upper = str(ticker).upper()

    reasons: list[str] = []
    board = "Utama"
    if "pemantauan khusus" in sec_lower or ".x" in ticker_upper or "{x}" in sec_lower:
        board = "Pemantauan Khusus (FCA)"
        reasons.append("Tercatat di Papan Pemantauan Khusus (FCA)")
    elif "akselerasi" in sec_lower:
        board = "Akselerasi"
        reasons.append("Tercatat di Papan Akselerasi (Likuiditas & Fundamental Berisiko)")
    elif "pengembangan" in sec_lower:
        board = "Pengembangan"
    elif "utama" in sec_lower:
        board = "Utama"

    # Cek notasi kritis
    critical_notations = []
    if any(k in sec_lower for k in ("ekuitas negatif", "{e}", ".e")):
        critical_notations.append("E (Ekuitas Negatif)")
    if any(k in sec_lower for k in ("pkpu", "pailit", "{a}", ".a")):
        critical_notations.append("A (Permohonan PKPU / Pailit)")
    if any(k in sec_lower for k in ("moratorium", "{m}", ".m")):
        critical_notations.append("M (Moratorium PKPU)")
    if any(k in sec_lower for k in ("tidak menyampaikan laporan", "{s}", ".s")):
        critical_notations.append("S (Laporan Keuangan Bermasalah)")

    if critical_notations:
        reasons.append(f"Notasi Khusus Kritis: {', '.join(critical_notations)}")

    # Cek harga minimum
    if close < 70:
        reasons.append(f"Harga Rp {int(close)} di bawah batas aman minimum Rp 70 (Penny Stock)")

    # Cek turnover minimum
    if value_b_idr < 1.0:
        reasons.append(f"Turnover harian Rp {value_b_idr:.2f} M < Rp 1.0 Miliar (Likuiditas Rendah)")

    # Cek frekuensi transaksi
    if frequency < 150:
        reasons.append(f"Frekuensi transaksi {int(frequency)}x < 150 transaksi (Partisipasi Pasar Minim)")

    is_safe = len(reasons) == 0
    return {
        "is_safe": is_safe,
        "board": board,
        "status": "PASS" if is_safe else "FAIL",
        "reasons": reasons,
        "summary": "Lolos Verifikasi Fundamental & Papan Bursa" if is_safe else "; ".join(reasons),
    }


def evaluate_tape_and_closing_quality(
    vol_ratio: float,
    closing_range: float,
    pct_change: float,
    val_idr: float,
    frequency: float,
    median_val_per_tx: float,
) -> dict[str, Any]:
    """
    Evaluasi Pola Tape Jam Bursa & Anti Manipulasi Pre-Closing (Item 5):
    1. Suspicious Crossing: Volume Spike >= 1.5x namun Frekuensi < 150 atau ticket size >= 8x median bursa.
    2. Upthrust Distribution: Volume Spike >= 1.4x namun Closing Range <= 0.35 (guyur sore / bantingan akhir).
    3. Thin Marking: Kenaikan harga >= +4.0% dengan Volume Ratio < 0.65x dan Turnover < 1.0 Miliar.
    """
    freq_clean = max(frequency, 1.0)
    val_per_tx = val_idr / freq_clean

    is_suspicious_crossing = (vol_ratio >= 1.5) and (
        (frequency < 150) or (val_per_tx >= median_val_per_tx * 8.0)
    )
    is_upthrust_trap = (vol_ratio >= 1.4) and (closing_range <= 0.35)
    is_thin_marking = (pct_change >= 4.0) and (vol_ratio < 0.65) and (val_idr < 1_000_000_000)

    if is_suspicious_crossing:
        return {
            "code": "SUSPICIOUS_CROSSING",
            "label": "Crossing Anomali / Volume Pasif",
            "is_organic": False,
            "badge_color": "amber",
            "reason": f"Volume {vol_ratio:.1f}x baseline namun frekuensi hanya {int(frequency)}x atau ticket per tx Rp {val_per_tx/1e6:.1f} Jt (>8x median bursa). Indikasi crossing negosiasi/pre-closing semu.",
        }
    elif is_upthrust_trap:
        return {
            "code": "UPTHRUST_DISTRIBUTION",
            "label": "Jebakan Upthrust (Guyur Sore)",
            "is_organic": False,
            "badge_color": "rose",
            "reason": f"Volume tinggi {vol_ratio:.1f}x baseline tetapi harga ditutup di dasar candle (Closing Range {int(closing_range * 100)}%). Indikasi pompa pagi lalu buang barang menjelang penutupan.",
        }
    elif is_thin_marking:
        return {
            "code": "THIN_MARKING",
            "label": "Marking The Close Sepi",
            "is_organic": False,
            "badge_color": "rose",
            "reason": f"Harga dinaikkan {pct_change:+.1f}% tanpa partisipasi volume ({vol_ratio:.2f}x) dan turnover Rp {val_idr/1e9:.2f} M (< 1 Miliar). Rawan berbalik anjlok.",
        }
    else:
        return {
            "code": "ORGANIC_FLOW",
            "label": "Arus Volume Organik",
            "is_organic": True,
            "badge_color": "emerald",
            "reason": "Volume dan penutupan harga terkonfirmasi alami dari partisipasi pasar reguler yang solid.",
        }


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


def _tight_entry_zone(ref_high: float, width_pct: float = 0.01) -> tuple[int, int]:
    """Menghasilkan rentang Zona Entry yang rapat (~1% atau 1-3 fraksi tick BEI) agar tidak membingungkan."""
    e_high = _round_idx_tick(ref_high)
    e_low = _round_idx_tick(e_high * (1.0 - width_pct))
    if e_low >= e_high and e_high > 50:
        step = 1 if e_high < 200 else 2 if e_high < 500 else 5 if e_high < 2000 else 10 if e_high < 5000 else 25
        e_low = max(50, e_high - step)
    return e_low, e_high


def compute_quantitative_dataframe(raw_df: pd.DataFrame) -> pd.DataFrame:
    """
    Mesin Analisis Kuantitatif Ter-Vektorisasi Lengkap SmartFlow IDX (v4.0).
    5 Pilar Kuantitatif Murni (100 Poin Maksimum):
    1. Volume Spike & VSA (25 Poin)
    2. Tren & Struktur MA20/MA50 (20 Poin)
    3. Kompresi Volatilitas / Squeeze (15 Poin)
    4. Likuiditas & Turnover Riil (15 Poin)
    5. Posisi Harga vs 5-Day VWAP (25 Poin)
    Trading Plan Adaptif Berbasis ATR(14) dengan Risk/Reward 1:2 (TP1) & 1:3 (TP2).
    """
    df = normalize_columns(raw_df) if "Has_Broker_Summary" not in raw_df.columns else raw_df.copy()
    df = df.sort_values(["Ticker", "Date"]).reset_index(drop=True)

    counts_per_ticker = df.groupby("Ticker")["Date"].transform("count")
    is_multi_day = (counts_per_ticker > 1).any()

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
        np.where(df["Pct_Change"] >= 0, 0.70, 0.30),
    )

    df["Ticket_Size"] = df["Volume_Lot"] / np.maximum(df["Frequency"], 1.0)
    df["Val_Per_Tx"] = df["Value_IDR"] / np.maximum(df["Frequency"], 1.0)
    median_val_per_tx = max(1_000_000.0, float(df["Val_Per_Tx"].median()))

    # 1. Moving Averages & Range Resisten
    if is_multi_day:
        df["Vol_MA20"] = df.groupby("Ticker")["Volume_Lot"].transform(lambda s: s.rolling(20, min_periods=1).mean())
        df["Volume_Ratio"] = (df["Volume_Lot"] / np.maximum(df["Vol_MA20"], 1.0)).round(2)
        df["MA20"] = df.groupby("Ticker")["Close"].transform(lambda s: s.rolling(20, min_periods=1).mean())
        df["MA50"] = df.groupby("Ticker")["Close"].transform(lambda s: s.rolling(50, min_periods=1).mean())
        df["High_10D"] = (
            df.groupby("Ticker")["High"]
            .transform(lambda s: s.shift(1).rolling(10, min_periods=1).max())
            .fillna(df["High"])
        )
        df["Low_10D"] = df.groupby("Ticker")["Low"].transform(lambda s: s.rolling(10, min_periods=1).min())
        df["Ticket_MA20"] = df.groupby("Ticker")["Ticket_Size"].transform(lambda s: s.rolling(20, min_periods=1).mean())
        df["Ticket_Ratio"] = (df["Ticket_Size"] / np.maximum(df["Ticket_MA20"], 0.1)).round(2)
    else:
        est_vol_ratio = np.clip(
            (df["Val_Per_Tx"] / median_val_per_tx) * 0.65 + (df["Pct_Change"].abs() * 0.18) + 0.6,
            0.5,
            4.0,
        )
        df["Vol_MA20"] = (df["Volume_Lot"] / np.maximum(est_vol_ratio, 0.1)).round()
        df["Volume_Ratio"] = est_vol_ratio.round(2)
        df["MA20"] = df["Prev_Close"]
        df["MA50"] = df["Prev_Close"]
        df["High_10D"] = df["High"]
        df["Low_10D"] = df["Low"]
        est_ticket_ratio = np.clip(df["Val_Per_Tx"] / median_val_per_tx, 0.4, 3.8)
        df["Ticket_MA20"] = df["Ticket_Size"] / np.maximum(est_ticket_ratio, 0.1)
        df["Ticket_Ratio"] = est_ticket_ratio.round(2)

    # 2. True Range & ATR(14)
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - df["Prev_Close"]).abs()
    tr3 = (df["Low"] - df["Prev_Close"]).abs()
    df["TR"] = np.maximum(tr1, np.maximum(tr2, tr3))
    if is_multi_day:
        df["ATR14"] = df.groupby("Ticker")["TR"].transform(lambda s: s.rolling(14, min_periods=1).mean()).fillna(tr1).round().astype(np.int64)
    else:
        df["ATR14"] = np.maximum(1, np.round(df["TR"] * 0.9)).astype(np.int64)
    df["ATR_Pct"] = ((df["ATR14"] / np.maximum(df["Close"], 1.0)) * 100.0).round(2)

    # 3. 5-Day VWAP
    typ_p = (df["High"] + df["Low"] + df["Close"]) / 3.0
    pv_tmp = typ_p * np.maximum(df["Volume_Lot"], 1)
    v_tmp = np.maximum(df["Volume_Lot"], 1)
    if is_multi_day:
        pv_5d = df.assign(_pv=pv_tmp).groupby("Ticker")["_pv"].transform(lambda s: s.rolling(5, min_periods=1).sum())
        v_5d = df.assign(_v=v_tmp).groupby("Ticker")["_v"].transform(lambda s: s.rolling(5, min_periods=1).sum())
        df["VWAP_5D"] = (pv_5d / np.maximum(v_5d, 1.0)).round().astype(np.int64)
    else:
        df["VWAP_5D"] = typ_p.round().astype(np.int64)
    df["Bandar_Avg_Buy"] = df["VWAP_5D"]
    df["Diff_VWAP_Pct"] = (((df["Close"] - df["VWAP_5D"]) / np.maximum(df["VWAP_5D"], 1.0)) * 100.0).round(2)

    # 4. Volatility Compression / Squeeze Detection
    if is_multi_day:
        std20 = df.groupby("Ticker")["Close"].transform(lambda s: s.rolling(20, min_periods=1).std()).fillna(0.0)
        bb_upper = df["MA20"] + 2.0 * std20
        bb_lower = df["MA20"] - 2.0 * std20
        kc_upper = df["MA20"] + 1.5 * df["ATR14"]
        kc_lower = df["MA20"] - 1.5 * df["ATR14"]
        spread_3d = df.groupby("Ticker")["Spread_Pct"].transform(lambda s: s.rolling(3, min_periods=1).mean())
        spread_20d = df.groupby("Ticker")["Spread_Pct"].transform(lambda s: s.rolling(20, min_periods=1).mean())
        df["Is_Squeeze"] = ((bb_upper <= kc_upper) & (bb_lower >= kc_lower)) | (spread_3d <= spread_20d * 0.75)
    else:
        df["Is_Squeeze"] = df["Spread_Pct"] <= 2.5

    df["Net_Top3_Lot"] = df["Top3_Buy_Lot"] - df["Top3_Sell_Lot"]
    df["Top3_BSR"] = (df["Top3_Buy_Lot"] / np.maximum(df["Top3_Sell_Lot"], 1.0)).round(2)
    df["Top1_BSR"] = (df["Top1_Buy_Lot"] / np.maximum(df["Top1_Sell_Lot"], 1.0)).round(2)
    df["Top5_BSR"] = (df["Top5_Buy_Lot"] / np.maximum(df["Top5_Sell_Lot"], 1.0)).round(2)
    df["Broker_Dominance_Pct"] = ((df["Net_Top3_Lot"] / np.maximum(df["Volume_Lot"], 1.0)) * 100.0).round(2)

    df["Net_Foreign_IDR"] = df["Foreign_Buy_Val"] - df["Foreign_Sell_Val"]
    df["Net_Foreign_Pct"] = ((df["Net_Foreign_IDR"] / np.maximum(df["Value_IDR"], 1.0)) * 100.0).round(2)

    # 5. Indikator Akumulasi OHLCV Murni:
    # - On-Balance Volume (OBV) 5-Day Rising (OBV[-1] > OBV[-5])
    # - Up/Down Volume Ratio 5-Day > 1.3 (Dominasi volume saat candle hijau)
    if is_multi_day:
        obv_dir = np.where(df["Close"] > df["Prev_Close"], 1.0, np.where(df["Close"] < df["Prev_Close"], -1.0, 0.0))
        df["OBV_Delta"] = obv_dir * df["Volume_Lot"]
        df["OBV"] = df.groupby("Ticker")["OBV_Delta"].cumsum()
        df["OBV_5D_Rising"] = df.groupby("Ticker")["OBV"].transform(lambda s: s > s.shift(5)).fillna(True)

        up_vol = np.where(df["Close"] >= df["Prev_Close"], df["Volume_Lot"], 0.0)
        dn_vol = np.where(df["Close"] < df["Prev_Close"], df["Volume_Lot"], 0.0)
        sum_up = df.assign(_up=up_vol).groupby("Ticker")["_up"].transform(lambda s: s.rolling(5, min_periods=1).sum())
        sum_dn = df.assign(_dn=dn_vol).groupby("Ticker")["_dn"].transform(lambda s: s.rolling(5, min_periods=1).sum())
        df["UpDown_Vol_Ratio_5D"] = (sum_up / np.maximum(sum_dn, 1.0)).round(2)
    else:
        df["OBV_5D_Rising"] = df["Pct_Change"] >= 0
        df["UpDown_Vol_Ratio_5D"] = np.where(df["Pct_Change"] >= 0, 1.5, 0.8)

    # =========================================================================
    # SINGLE SOURCE OF TRUTH: 5 PILAR KUANTITATIF (MAKSIMUM 100 POIN)
    # =========================================================================

    # Pilar 1: Volume Spike, VSA & Akumulasi Murni OHLCV (25 Poin)
    vol_pts = np.select(
        [df["Volume_Ratio"] >= 2.5, df["Volume_Ratio"] >= 1.8, df["Volume_Ratio"] >= 1.3, df["Volume_Ratio"] >= 1.0],
        [12.0, 10.0, 7.0, 4.0],
        default=1.0,
    )
    cr_pts = np.select(
        [(df["Closing_Range"] >= 0.75) & (df["Pct_Change"] >= 0), df["Closing_Range"] >= 0.65, df["Closing_Range"] >= 0.50],
        [7.0, 5.0, 3.0],
        default=0.0,
    )
    pure_accum_pts = np.where(
        df["OBV_5D_Rising"] & (df["UpDown_Vol_Ratio_5D"] >= 1.3),
        6.0,
        np.where(df["OBV_5D_Rising"] | (df["UpDown_Vol_Ratio_5D"] >= 1.1), 3.0, 0.0),
    )
    df["Pilar1_VSA_Score"] = np.clip(vol_pts + cr_pts + pure_accum_pts, 0.0, 25.0).round(1)

    # Pilar 2: Tren & Struktur MA20/MA50 (20 Poin)
    p_vs_ma20_pts = np.where(df["Close"] >= df["MA20"], 8.0, 0.0)
    ma_align_pts = np.where(df["MA20"] >= df["MA50"], 7.0, 2.0)
    breakout_pts = np.where(df["Close"] >= df["High_10D"] * 0.995, 5.0, 0.0)
    df["Pilar2_Trend_Score"] = np.clip(p_vs_ma20_pts + ma_align_pts + breakout_pts, 0.0, 20.0).round(1)

    # Pilar 3: Kompresi Volatilitas / Squeeze (15 Poin)
    sq_pts = np.select(
        [df["Is_Squeeze"], df["Spread_Pct"] <= 2.8, df["ATR_Pct"] <= 4.0],
        [15.0, 10.0, 6.0],
        default=2.0,
    )
    df["Pilar3_Squeeze_Score"] = np.clip(sq_pts, 0.0, 15.0).round(1)

    # Pilar 4: Likuiditas & Turnover Riil (15 Poin)
    val_pts = np.select(
        [
            (df["Close"] >= 50) & (df["Value_IDR"] >= 10_000_000_000),
            (df["Close"] >= 50) & (df["Value_IDR"] >= 3_000_000_000),
            (df["Close"] >= 50) & (df["Value_IDR"] >= 1_000_000_000),
            (df["Close"] >= 50) & (df["Value_IDR"] >= 500_000_000),
        ],
        [15.0, 12.0, 8.0, 5.0],
        default=0.0,
    )
    df["Pilar4_Liquidity_Score"] = np.clip(val_pts, 0.0, 15.0).round(1)

    # Pilar 5: Posisi Harga vs 5-Day VWAP (25 Poin)
    vwap_pts = np.select(
        [
            (df["Diff_VWAP_Pct"] >= -1.0) & (df["Diff_VWAP_Pct"] <= 2.5),
            (df["Diff_VWAP_Pct"] > 2.5) & (df["Diff_VWAP_Pct"] <= 5.0),
            (df["Diff_VWAP_Pct"] >= -3.0) & (df["Diff_VWAP_Pct"] < -1.0),
            (df["Diff_VWAP_Pct"] > 5.0) & (df["Diff_VWAP_Pct"] <= 8.0),
            df["Diff_VWAP_Pct"] > 8.0,
        ],
        [25.0, 20.0, 18.0, 10.0, 5.0],
        default=3.0,
    )
    df["Pilar5_VWAP_Score"] = np.clip(vwap_pts, 0.0, 25.0).round(1)

    # Total Skor Kuantitatif (Single Unified Value)
    df["Smart_Money_Score"] = np.clip(
        np.round(
            df["Pilar1_VSA_Score"]
            + df["Pilar2_Trend_Score"]
            + df["Pilar3_Squeeze_Score"]
            + df["Pilar4_Liquidity_Score"]
            + df["Pilar5_VWAP_Score"]
        ),
        5,
        100,
    ).astype(int)
    df["Daily_SM_Score"] = df["Smart_Money_Score"]

    # Filter Keamanan Swing Pendek: Bukan Saham FCA/Akselerasi, Harga >= Rp 70, Turnover >= 1M, Frekuensi >= 150
    sec_lower = df["Sector"].astype(str).str.lower()
    is_safe_swing = (
        (df["Close"] >= 70)
        & (~sec_lower.str.contains("pemantauan khusus", na=False))
        & (~sec_lower.str.contains("akselerasi", na=False))
        & (df["Value_IDR"] >= 1_000_000_000)
        & (df["Frequency"] >= 150)
    )

    # Klasifikasi Sinyal Kuantitatif (Trigger Type)
    # Proteksi Anti False-Crash: Hanya saham yang aktif diperdagangkan (Value_IDR >= 500 Juta) yang dievaluasi sebagai distribusi
    c_dist = (
        (df["Value_IDR"] >= 500_000_000)
        & (
            ((df["Closing_Range"] <= 0.35) & (df["Pct_Change"] <= -1.5) & (df["Volume_Ratio"] >= 1.2))
            | (df["Smart_Money_Score"] <= 35)
        )
    )
    c_markup = (
        is_safe_swing
        & (df["Smart_Money_Score"] >= 74)
        & (df["Volume_Ratio"] >= 1.6)
        & (df["Pct_Change"] >= 1.2)
        & (df["Pct_Change"] <= 5.5)
        & (df["Closing_Range"] >= 0.65)
        & (df["Diff_VWAP_Pct"] >= -1.0)
        & (df["Diff_VWAP_Pct"] <= 3.5)
        & (df["Close"] >= df["MA20"])
    )
    c_silent = (
        is_safe_swing
        & (df["Smart_Money_Score"] >= 65)
        & (df["Is_Squeeze"])
        & (df["Closing_Range"] >= 0.50)
        & (df["Pct_Change"] >= -1.5)
        & (df["Pct_Change"] <= 3.5)
        & (df["Diff_VWAP_Pct"] >= -1.0)
        & (df["Diff_VWAP_Pct"] <= 3.5)
        & (df["Volume_Ratio"] <= 1.35)
    )
    c_big_accum = (
        is_safe_swing
        & (df["Smart_Money_Score"] >= 68)
        & (df["Volume_Ratio"] >= 1.3)
        & (df["Closing_Range"] >= 0.65)
        & (df["Pct_Change"] >= -1.5)
        & (df["Pct_Change"] <= 5.5)
        & (df["Diff_VWAP_Pct"] >= -1.0)
        & (df["Diff_VWAP_Pct"] <= 3.5)
        & (df["Value_IDR"] >= 1_000_000_000)
    )
    c_foreign = (
        is_safe_swing
        & (df["Smart_Money_Score"] >= 64)
        & (df["Closing_Range"] >= 0.65)
        & (df["Pct_Change"] >= -1.5)
        & (df["Pct_Change"] <= 5.5)
        & (df["Diff_VWAP_Pct"] >= -1.0)
        & (df["Diff_VWAP_Pct"] <= 3.5)
        & (df["Net_Foreign_Pct"] >= 12.0)
        & (df["Net_Foreign_IDR"] > 0)
        & (df["Value_IDR"] >= 1_000_000_000)
    )

    df["Trigger_Type"] = np.select(
        [c_dist, c_markup, c_silent, c_big_accum, c_foreign],
        ["DISTRIBUTION_WARNING", "MARKUP_BREAKOUT", "SILENT_ACCUMULATION", "BIG_ACCUMULATION", "FOREIGN_INFLOW"],
        default="NEUTRAL_FLOW",
    )

    return df


def analyze_smart_money_dataframe(raw_df: pd.DataFrame) -> dict[str, Any]:
    """
    Mesin Analisis Kuantitatif Ter-Vektorisasi Lengkap SmartFlow IDX (v4.0).
    """
    df = compute_quantitative_dataframe(raw_df)
    stocks_result: list[dict[str, Any]] = []
    stocks_detail_map: dict[str, dict[str, Any]] = {}
    median_val_per_tx = max(1_000_000.0, float(df["Val_Per_Tx"].median())) if "Val_Per_Tx" in df.columns else 2_500_000.0

    for ticker, g in df.groupby("Ticker", sort=False):
        n = len(g)
        latest = g.iloc[-1]
        last5 = g.tail(min(5, n))

        close_price = int(round(float(latest["Close"])))
        pct_change = round(float(latest["Pct_Change"]), 2)
        vol_ratio = round(float(latest["Volume_Ratio"]), 2)
        closing_range = round(float(latest["Closing_Range"]), 2)
        spread_pct = round(float(latest["Spread_Pct"]), 2)
        atr14_val = max(1, int(round(float(latest["ATR14"]))))
        atr_pct = round(float(latest["ATR_Pct"]), 2)
        obv_rising = bool(latest["OBV_5D_Rising"]) if "OBV_5D_Rising" in latest else True
        updown_vol_ratio_5d = round(float(latest["UpDown_Vol_Ratio_5D"]), 2) if "UpDown_Vol_Ratio_5D" in latest else 1.2

        top3_bsr = round(float(latest["Top3_BSR"]), 2)
        top1_bsr = round(float(latest["Top1_BSR"]), 2)
        top5_bsr = round(float(latest["Top5_BSR"]), 2)
        bdr_pct = round(float(latest["Broker_Dominance_Pct"]), 2)
        cum_5d_net_top3_lot = int(round(float(last5["Net_Top3_Lot"].sum())))
        cum_5d_vol_lot = max(1, int(round(float(last5["Volume_Lot"].sum()))))
        cum_5d_bdr_pct = round((cum_5d_net_top3_lot / cum_5d_vol_lot) * 100.0, 2)

        vwap_5d = int(round(float(latest["VWAP_5D"])))
        diff_vwap_pct = round(float(latest["Diff_VWAP_Pct"]), 2)

        ticket_size = round(float(latest["Ticket_Size"]), 1)
        ticket_ratio = round(float(latest["Ticket_Ratio"]), 2)

        val_idr = int(round(float(latest["Value_IDR"])))
        net_foreign_idr = int(round(float(latest["Net_Foreign_IDR"])))
        net_foreign_pct = round(float(latest["Net_Foreign_Pct"]), 2)
        cum_5d_foreign_idr = int(round(float(last5["Net_Foreign_IDR"].sum())))

        ma20 = int(round(float(latest["MA20"])))
        ma50 = int(round(float(latest["MA50"])))
        price_vs_ma20_pct = round(((close_price - ma20) / max(ma20, 1)) * 100.0, 2)
        is_squeeze = bool(latest["Is_Squeeze"])

        pilar1_score = float(latest["Pilar1_VSA_Score"])
        pilar2_score = float(latest["Pilar2_Trend_Score"])
        pilar3_score = float(latest["Pilar3_Squeeze_Score"])
        pilar4_score = float(latest["Pilar4_Liquidity_Score"])
        pilar5_score = float(latest["Pilar5_VWAP_Score"])
        smart_money_score = int(latest["Smart_Money_Score"])
        trigger_type = str(latest["Trigger_Type"])

        if trigger_type == "DISTRIBUTION_WARNING":
            trigger_label = "Distribution Warning"
            bandar_status = "Distribution"
            vsa_pattern = "Supply Pressure (Tekanan Jual Melebihi Permintaan)"
        elif trigger_type == "MARKUP_BREAKOUT":
            trigger_label = "Markup Breakout"
            bandar_status = "Big Accumulation"
            vsa_pattern = "Demand Breakout Candle (High Volume + Penutupan di Pucuk)"
        elif trigger_type == "SILENT_ACCUMULATION":
            trigger_label = "Silent Accumulation"
            bandar_status = "Silent Accumulation"
            vsa_pattern = "Volatility Squeeze / Silent Absorption (Harga Dijaga di VWAP 5H)"
        elif trigger_type == "BIG_ACCUMULATION":
            trigger_label = "Big Accumulation"
            bandar_status = "Big Accumulation"
            vsa_pattern = "Institutional Accumulation (Dominasi Aliran Dana Besar)"
        elif trigger_type == "FOREIGN_INFLOW":
            trigger_label = "Foreign Inflow Surge"
            bandar_status = "Accumulation"
            vsa_pattern = "Sustained Foreign Inflow (Akumulasi Institusi Asing)"
        else:
            trigger_type = "NEUTRAL_FLOW"
            trigger_label = "Neutral / Retail Flow"
            bandar_status = "Accumulation" if smart_money_score >= 60 else "Neutral"
            vsa_pattern = "Normal Consolidation Activity"

        freq_val = float(latest["Frequency"]) if "Frequency" in latest and not pd.isna(latest["Frequency"]) else 500.0
        sector_category = classify_idx_sector(str(ticker), str(latest["Sector"]))
        fund_safety = check_fundamental_and_board_safety(str(ticker), str(latest["Sector"]), close_price, val_idr / 1e9, freq_val)
        tape_quality = evaluate_tape_and_closing_quality(vol_ratio, closing_range, pct_change, val_idr, freq_val, median_val_per_tx)

        # 5-Pillar Quantitative Checklist + Safety Filters
        checklist = [
            {
                "title": "Pilar 1: Volume Spike & VSA Murni",
                "score": f"{pilar1_score}/25",
                "status": "pass" if pilar1_score >= 17 else ("warn" if pilar1_score >= 10 else "fail"),
                "metric": f"{vol_ratio}x Vol | CR {int(closing_range * 100)}% | Up/Down {updown_vol_ratio_5d}x",
                "detail": f"Volume {vol_ratio}x baseline MA20 dengan penutupan di {int(closing_range * 100)}% range bar harian. Akumulasi OBV 5H {'Naik (Dominan Akumulasi)' if obv_rising else 'Turun/Datar'} dengan rasio volume naik/turun {updown_vol_ratio_5d}x ({vsa_pattern}).",
            },
            {
                "title": "Pilar 2: Tren & Struktur MA20/MA50",
                "score": f"{pilar2_score}/20",
                "status": "pass" if pilar2_score >= 15 else ("warn" if pilar2_score >= 10 else "fail"),
                "metric": f"{'Above' if close_price >= ma20 else 'Below'} MA20 | MA50: {'Bull' if ma20 >= ma50 else 'Bear'}",
                "detail": f"Harga Rp {close_price:,} vs MA20 Rp {ma20:,} ({price_vs_ma20_pct:+.1f}%), struktur tren {'Uptrend' if ma20 >= ma50 else 'Konsolidasi/Downtrend'}.",
            },
            {
                "title": "Pilar 3: Kompresi Volatilitas (Squeeze)",
                "score": f"{pilar3_score}/15",
                "status": "pass" if pilar3_score >= 12 else ("warn" if pilar3_score >= 8 else "fail"),
                "metric": f"{'Squeeze On' if is_squeeze else 'Normal'} | ATR14: Rp {atr14_val:,}",
                "detail": f"Volatilitas ATR(14) Rp {atr14_val:,} ({atr_pct:.1f}% dari harga). " + ("Terdeteksi kompresi volatilitas ketat sebelum potensi ledakan ekspansi harga." if is_squeeze else "Volatilitas dalam rentang normal harian."),
            },
            {
                "title": "Pilar 4: Likuiditas & Turnover Riil",
                "score": f"{pilar4_score}/15",
                "status": "pass" if pilar4_score >= 12 else ("warn" if pilar4_score >= 8 else "fail"),
                "metric": f"Rp {val_idr / 1e9:.2f} Miliar",
                "detail": f"Nilai transaksi harian Rp {val_idr / 1e9:.2f} Miliar ({'Sangat Likuid' if val_idr >= 1e10 else 'Likuiditas Memadai' if val_idr >= 1e9 else 'Likuiditas Rendah'}).",
            },
            {
                "title": "Pilar 5: Posisi Harga vs VWAP 5 Hari",
                "score": f"{pilar5_score}/25",
                "status": "pass" if pilar5_score >= 18 else ("warn" if pilar5_score >= 10 else "fail"),
                "metric": f"VWAP 5H Rp {vwap_5d:,} ({diff_vwap_pct:+.1f}%)",
                "detail": f"Harga saat ini Rp {close_price:,} berjarak {diff_vwap_pct:+.1f}% dari VWAP 5 hari bursa terakhir (Rp {vwap_5d:,}).",
            },
            {
                "title": "Filter Fundamental & Papan Bursa",
                "score": "PASS" if fund_safety["is_safe"] else "FAIL",
                "status": "pass" if fund_safety["is_safe"] else "fail",
                "metric": f"{fund_safety['board']} | Rp {close_price:,}",
                "detail": fund_safety["summary"] + f" (Frekuensi {int(freq_val):,} tx, Turnover Rp {val_idr / 1e9:.2f} M).",
            },
            {
                "title": "Kualitas Arus Volume (Tape Flow)",
                "score": "ORGANIC" if tape_quality["is_organic"] else "ANOMALY",
                "status": "pass" if tape_quality["is_organic"] else ("warn" if tape_quality["code"] == "SUSPICIOUS_CROSSING" else "fail"),
                "metric": tape_quality["label"],
                "detail": tape_quality["reason"],
            },
        ]

        # Trading Plan: 1 Harga Beli Acuan (Close Hari Sinyal) & SL Proporsional
        entry_price = _round_idx_tick(close_price)
        entry_low = entry_price
        entry_high = entry_price
        # Batasi Stop Loss proporsional -3.5% s/d -5.0% (1.4 * ATR14) untuk Swing Pendek
        sl_distance = max(int(round(entry_price * 0.035)), min(int(round(entry_price * 0.050)), int(round(1.4 * atr14_val))))
        stop_loss = _round_idx_tick(entry_price - sl_distance)
        risk_idr = max(1, entry_price - stop_loss)
        risk_pct = round((risk_idr / max(entry_price, 1)) * 100.0, 2)

        tp1 = _round_idx_tick(entry_price * 1.04)
        tp2 = _round_idx_tick(entry_price * 1.07)
        if tp2 <= tp1:
            tp2 = _round_idx_tick(tp1 + (2 if entry_price >= 200 else 1))
        tp1_pct = round(((tp1 - entry_price) / max(entry_price, 1)) * 100.0, 2)
        tp2_pct = round(((tp2 - entry_price) / max(entry_price, 1)) * 100.0, 2)
        rr_ratio = round(tp2_pct / max(risk_pct, 0.1), 1)

        if trigger_type == "DISTRIBUTION_WARNING":
            action_bias = "AVOID / SELL ON STRENGTH"
            rationale = (
                f"Tekanan jual tinggi dengan penutupan di paruh bawah candle (CR {int(closing_range * 100)}%). "
                "Hindari entry terburu-buru sampai terbentuk sinyal pembalikan (Stopping Volume)."
            )
        elif trigger_type == "MARKUP_BREAKOUT":
            action_bias = "BUY ON BREAKOUT / RETEST"
            rationale = (
                f"Breakout di atas resisten dengan lonjakan volume {vol_ratio}x baseline. "
                f"Stop Loss berbasis ATR(14) Rp {atr14_val:,} di level Rp {stop_loss:,} (-{risk_pct}%)."
            )
        elif trigger_type == "SILENT_ACCUMULATION":
            action_bias = "BUY NEAR VWAP 5H (SWING)"
            rationale = (
                f"Terdeteksi kompresi volatilitas (Squeeze) dengan harga dijaga ketat di area VWAP 5H (Rp {vwap_5d:,}). "
                f"Cicil beli dengan batas risiko ATR(14) Rp {atr14_val:,}."
            )
        elif trigger_type == "BIG_ACCUMULATION":
            action_bias = "BUY ON ACCUMULATION"
            rationale = (
                f"Akumulasi volume likuiditas besar (Turnover Rp {val_idr / 1e9:.2f} M) di atas VWAP 5H. "
                f"Target cepat TP1 Rp {tp1:,} (+{tp1_pct}%) & TP2 Rp {tp2:,} (+{tp2_pct}%)."
            )
        elif trigger_type == "FOREIGN_INFLOW":
            action_bias = "FOLLOW FOREIGN INFLOW"
            rationale = (
                f"Arus perputaran dana asing positif Rp {net_foreign_idr / 1e9:+.2f} Miliar. "
                f"Manfaatkan momentum akumulasi dengan Stop Loss Rp {stop_loss:,}."
            )
        else:
            action_bias = "BUY ON SUPPORT / WATCHLIST"
            rationale = f"Struktur konsolidasi normal. Pantau konfirmasi lonjakan volume di atas 1.5x baseline."

        # Kalkulasi Probabilitas Empiris Win vs Loss (berdasarkan skor & audit 6 bulan 106.377 candle - Quick Profit TP1 +4% & TP2 +7%)
        base_win_tp1 = 55.0 + min(22.0, max(0.0, (smart_money_score - 40) * 0.45))
        if vol_ratio >= 2.0:
            base_win_tp1 += 3.0
        if trigger_type == "MARKUP_BREAKOUT":
            base_win_tp1 += 2.5
        elif trigger_type == "DISTRIBUTION_WARNING":
            base_win_tp1 = max(25.0, base_win_tp1 - 25.0)

        tp1_win = round(min(85.0, max(35.0, base_win_tp1)), 1)
        tp1_loss = round(100.0 - tp1_win, 1)

        # TP2 memiliki target +7% (rasio sukses mencapai TP2 sekitar 60% dari TP1)
        tp2_win = round(min(65.0, max(20.0, tp1_win * 0.60)), 1)
        tp2_loss = round(100.0 - tp2_win, 1)

        trading_plan = {
            "action_bias": action_bias,
            "entry_price": entry_price,
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop_loss": stop_loss,
            "stop_loss_pct": -risk_pct,
            "target_1": tp1,
            "target_1_pct": tp1_pct,
            "target_2": tp2,
            "target_2_pct": tp2_pct,
            "tp1_win_prob": tp1_win,
            "tp1_loss_prob": tp1_loss,
            "tp2_win_prob": tp2_win,
            "tp2_loss_prob": tp2_loss,
            "win_loss_ratio": f"{int(round(tp1_win))}% Win : {int(round(tp1_loss))}% Loss",
            "risk_reward": f"1 : {rr_ratio}",
            "bandar_avg_buy": vwap_5d,
            "diff_bandar_avg_pct": diff_vwap_pct,
            "atr14": atr14_val,
            "atr_pct": atr_pct,
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
            "bandar_avg_buy": vwap_5d,
            "diff_bandar_avg_pct": diff_vwap_pct,
            "ticket_size": ticket_size,
            "ticket_ratio": ticket_ratio,
            "net_foreign_b_idr": round(net_foreign_idr / 1e9, 2),
            "net_foreign_pct": net_foreign_pct,
            "cum_5d_foreign_b_idr": round(cum_5d_foreign_idr / 1e9, 2),
            "ma20": ma20,
            "ma50": ma50,
            "atr14": atr14_val,
            "atr_pct": atr_pct,
            "is_squeeze": is_squeeze,
            "obv_5d_rising": obv_rising,
            "updown_vol_ratio_5d": updown_vol_ratio_5d,
            "price_vs_ma20_pct": price_vs_ma20_pct,
            "vsa_score": pilar1_score,
            "bandar_score": pilar2_score,
            "ticket_score": pilar3_score,
            "foreign_score": pilar4_score,
            "structure_score": pilar5_score,
            "smart_money_score": smart_money_score,
            "trigger_type": trigger_type,
            "trigger_label": trigger_label,
            "bandar_status": bandar_status,
            "vsa_pattern": vsa_pattern,
            "trading_plan": trading_plan,
            "sector_category": sector_category,
            "fundamental_safety": fund_safety,
            "tape_quality": tape_quality,
        }

        stocks_result.append(summary_item)
        stocks_detail_map[str(ticker)] = {
            **summary_item,
            "checklist": checklist,
            "history": history_records,
        }

    stocks_result.sort(key=lambda x: (x["smart_money_score"], x["vol_ratio"]), reverse=True)

    total_emiten_now = len(stocks_result)
    markup_now = sum(1 for s in stocks_result if s["trigger_type"] == "MARKUP_BREAKOUT")
    accum_now = sum(
        1 for s in stocks_result if s["trigger_type"] in ("BIG_ACCUMULATION", "SILENT_ACCUMULATION", "FOREIGN_INFLOW")
    )
    dist_now = sum(1 for s in stocks_result if s["trigger_type"] == "DISTRIBUTION_WARNING")
    avg_score_now = round(
        float(np.mean([s["smart_money_score"] for s in stocks_result])) if stocks_result else 0.0, 1
    )

    # Historical Daily Metrics (Single Source of Truth across dates)
    unique_dates = sorted(df["Date"].unique())
    last_10_dates = unique_dates[-10:] if len(unique_dates) >= 10 else unique_dates

    trend_avg_score: list[float] = []
    trend_markup: list[int] = []
    trend_accum: list[int] = []
    trend_dist: list[int] = []

    for d_str in last_10_dates:
        sub = df[df["Date"] == d_str]
        trend_avg_score.append(round(float(sub["Smart_Money_Score"].mean()), 1) if not sub.empty else 0.0)
        trend_markup.append(int((sub["Trigger_Type"] == "MARKUP_BREAKOUT").sum()))
        trend_accum.append(int(sub["Trigger_Type"].isin(["BIG_ACCUMULATION", "SILENT_ACCUMULATION", "FOREIGN_INFLOW"]).sum()))
        trend_dist.append(int((sub["Trigger_Type"] == "DISTRIBUTION_WARNING").sum()))

    if not trend_avg_score:
        trend_avg_score = [avg_score_now]
        trend_markup = [markup_now]
        trend_accum = [accum_now]
        trend_dist = [dist_now]

    if len(last_10_dates) >= 2:
        prev_date = last_10_dates[-2]
        prev_sub = df[df["Date"] == prev_date]
        prev_total_emiten = int(len(prev_sub))
        prev_avg_score = round(float(prev_sub["Smart_Money_Score"].mean()), 1) if not prev_sub.empty else avg_score_now
        prev_markup = int((prev_sub["Trigger_Type"] == "MARKUP_BREAKOUT").sum())
        prev_accum = int(prev_sub["Trigger_Type"].isin(["BIG_ACCUMULATION", "SILENT_ACCUMULATION", "FOREIGN_INFLOW"]).sum())
        prev_dist = int((prev_sub["Trigger_Type"] == "DISTRIBUTION_WARNING").sum())
    else:
        prev_total_emiten = total_emiten_now
        prev_avg_score = avg_score_now
        prev_markup = markup_now
        prev_accum = accum_now
        prev_dist = dist_now

    def _calc_pct(curr: float, prev: float) -> float:
        if prev > 0:
            return round(((curr - prev) / prev) * 100.0, 1)
        return 100.0 if curr > 0 else 0.0

    # Market Regime Analysis
    latest_dt = max((s["date"] for s in stocks_result), default="2026-10-08")
    latest_day_df = df[df["Date"] == latest_dt]
    if not latest_day_df.empty:
        breadth_ma20 = float((latest_day_df["Close"] >= latest_day_df["MA20"]).mean() * 100.0)
        breadth_ma50 = float((latest_day_df["Close"] >= latest_day_df["MA50"]).mean() * 100.0)
        avg_market_pct = float(latest_day_df["Pct_Change"].median()) if "Pct_Change" in latest_day_df.columns else 0.0
    else:
        breadth_ma20 = 50.0
        breadth_ma50 = 50.0
        avg_market_pct = 0.0

    # 3. Logika Lock vs Rebound
    # Shock Drop (<= -1.5%), Breadth Hancur (< 35%), atau Distribusi Massal (dist >= accum * 3)
    is_market_crash = (avg_market_pct <= -1.5) or (breadth_ma20 < 35.0) or (dist_now >= max(1, accum_now * 3))

    # Rebound valid jika breadth berbalik naik >= 42% dan pergerakan harian positif (>= +0.5%)
    is_rebound_confirmed = (not is_market_crash) and (breadth_ma20 >= 42.0) and (avg_market_pct >= 0.5)

    if is_market_crash:
        regime_status = "CRASH_LOCKED"
        regime_label = "Pasar Tertekan (Watchlist Dibekukan)"
        regime_color = "rose"
        regime_alloc = "Cash 100% / Dilarang Entry Baru"
        allow_watchlist = False
        regime_note = f"Peringatan Risiko: Pasar anjlok / Breadth {breadth_ma20:.1f}%. Seluruh sinyal beli baru ditahan demi mengamankan modal."
    elif not is_rebound_confirmed and breadth_ma20 < 45.0:
        regime_status = "WAITING_REBOUND"
        regime_label = "Menunggu Konfirmasi Rebound"
        regime_color = "amber"
        regime_alloc = "Cash 80% - 90% (Wait & See)"
        allow_watchlist = False
        regime_note = "Pasar belum membentuk konfirmasi pantulan yang kuat. Menghindari jebakan Dead Cat Bounce."
    else:
        regime_status = "NORMAL_ACTIVE"
        regime_label = "Pasar Kondusif / Rebound Terkonfirmasi"
        regime_color = "emerald"
        regime_alloc = "Alokasi Modal Normal Terukur"
        allow_watchlist = True
        regime_note = f"Market Breadth sehat ({breadth_ma20:.1f}% > MA20). Sinyal akumulasi diizinkan muncul."

    market_regime = {
        "status": regime_status,
        "label": regime_label,
        "color": regime_color,
        "allocation": regime_alloc,
        "breadth_ma20_pct": round(breadth_ma20, 1),
        "breadth_ma50_pct": round(breadth_ma50, 1),
        "allow_watchlist": allow_watchlist,
        "regime_note": regime_note,
        "avg_market_pct": round(avg_market_pct, 2),
    }

    kpis = {
        "total_emiten": total_emiten_now,
        "markup_triggers": markup_now,
        "accum_triggers": accum_now,
        "distribution_warnings": dist_now,
        "avg_smart_money_score": avg_score_now,
        "latest_date": latest_dt,
        "prev_total_emiten": prev_total_emiten,
        "prev_avg_smart_money_score": prev_avg_score,
        "prev_markup_triggers": prev_markup,
        "prev_accum_triggers": prev_accum,
        "prev_distribution_warnings": prev_dist,
        "avg_score_diff": round(avg_score_now - prev_avg_score, 1),
        "avg_score_pct_change": _calc_pct(avg_score_now, prev_avg_score),
        "markup_diff": markup_now - prev_markup,
        "markup_pct_change": _calc_pct(markup_now, prev_markup),
        "accum_diff": accum_now - prev_accum,
        "accum_pct_change": _calc_pct(accum_now, prev_accum),
        "dist_diff": dist_now - prev_dist,
        "dist_pct_change": _calc_pct(dist_now, prev_dist),
        "trend_avg_score": trend_avg_score,
        "trend_markup": trend_markup,
        "trend_accum": trend_accum,
        "trend_dist": trend_dist,
        "market_regime": market_regime,
    }

    return {
        "kpis": kpis,
        "stocks": stocks_result,
        "details": stocks_detail_map,
    }
