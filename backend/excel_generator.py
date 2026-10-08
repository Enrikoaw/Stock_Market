"""
Generator Standar Template Excel (.xlsx) & Dataset Simulasi Realistis Saham IDX
(Termasuk generator 900 Emiten IDX Lengkap & 15 Saham Pilihan)
untuk Aplikasi SmartFlow IDX - Smart Money Screener.
"""

from __future__ import annotations

import io
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter


IDX_SAMPLE_PROFILES = [
    {
        "ticker": "BBCA",
        "sector": "PT Bank Central Asia Tbk (Banking)",
        "base_price": 9850,
        "avg_vol_lot": 650_000,
        "avg_freq": 26_000,
        "scenario": "MARKUP_BREAKOUT",
        "top_buyers": "ZP, AK, YU",
        "top_sellers": "YP, PD, XC",
    },
    {
        "ticker": "BREN",
        "sector": "PT Barito Renewables Energy Tbk (Energy)",
        "base_price": 6800,
        "avg_vol_lot": 820_000,
        "avg_freq": 42_000,
        "scenario": "MARKUP_BREAKOUT",
        "top_buyers": "MG, BK, AK",
        "top_sellers": "YP, XL, CC",
    },
    {
        "ticker": "AMMN",
        "sector": "PT Amman Mineral Internasional Tbk (Mining)",
        "base_price": 8400,
        "avg_vol_lot": 480_000,
        "avg_freq": 19_500,
        "scenario": "SILENT_ACCUM",
        "top_buyers": "AK, ZP, RX",
        "top_sellers": "PD, YP, NI",
    },
    {
        "ticker": "ADRO",
        "sector": "PT Alamtri Resources Indonesia Tbk (Coal)",
        "base_price": 3650,
        "avg_vol_lot": 950_000,
        "avg_freq": 28_000,
        "scenario": "BIG_ACCUM",
        "top_buyers": "YU, BK, ZP",
        "top_sellers": "YP, XC, PD",
    },
    {
        "ticker": "BBRI",
        "sector": "PT Bank Rakyat Indonesia Tbk (Banking)",
        "base_price": 4780,
        "avg_vol_lot": 1_450_000,
        "avg_freq": 54_000,
        "scenario": "FOREIGN_INFLOW",
        "top_buyers": "RX, ZP, KZ",
        "top_sellers": "YP, PD, SQ",
    },
    {
        "ticker": "BMRI",
        "sector": "PT Bank Mandiri (Persero) Tbk (Banking)",
        "base_price": 6950,
        "avg_vol_lot": 780_000,
        "avg_freq": 24_000,
        "scenario": "BIG_ACCUM",
        "top_buyers": "ZP, KZ, AK",
        "top_sellers": "CC, YP, NI",
    },
    {
        "ticker": "PGEO",
        "sector": "PT Pertamina Geothermal Energy Tbk (Energy)",
        "base_price": 1185,
        "avg_vol_lot": 520_000,
        "avg_freq": 14_500,
        "scenario": "MARKUP_BREAKOUT",
        "top_buyers": "MG, YU, CP",
        "top_sellers": "YP, XC, XL",
    },
    {
        "ticker": "BRIS",
        "sector": "PT Bank Syariah Indonesia Tbk (Banking)",
        "base_price": 2940,
        "avg_vol_lot": 610_000,
        "avg_freq": 21_000,
        "scenario": "SILENT_ACCUM",
        "top_buyers": "BK, AK, OD",
        "top_sellers": "YP, PD, KK",
    },
    {
        "ticker": "MDKA",
        "sector": "PT Merdeka Copper Gold Tbk (Mining)",
        "base_price": 2460,
        "avg_vol_lot": 720_000,
        "avg_freq": 23_000,
        "scenario": "BIG_ACCUM",
        "top_buyers": "ZP, YU, LG",
        "top_sellers": "YP, PD, XC",
    },
    {
        "ticker": "TLKM",
        "sector": "PT Telkom Indonesia (Persero) Tbk (Telecom)",
        "base_price": 2880,
        "avg_vol_lot": 910_000,
        "avg_freq": 31_000,
        "scenario": "FOREIGN_INFLOW",
        "top_buyers": "AK, ZP, BK",
        "top_sellers": "PD, YP, DR",
    },
    {
        "ticker": "ANTM",
        "sector": "PT Aneka Tambang Tbk (Mining)",
        "base_price": 1560,
        "avg_vol_lot": 880_000,
        "avg_freq": 29_000,
        "scenario": "SILENT_ACCUM",
        "top_buyers": "OD, YU, CC",
        "top_sellers": "YP, XL, XC",
    },
    {
        "ticker": "ASII",
        "sector": "PT Astra International Tbk (Automotive)",
        "base_price": 5125,
        "avg_vol_lot": 540_000,
        "avg_freq": 19_000,
        "scenario": "NEUTRAL",
        "top_buyers": "ZP, YP, CC",
        "top_sellers": "AK, PD, YU",
    },
    {
        "ticker": "PGAS",
        "sector": "PT Perusahaan Gas Negara Tbk (Energy)",
        "base_price": 1520,
        "avg_vol_lot": 630_000,
        "avg_freq": 17_500,
        "scenario": "DISTRIBUTION",
        "top_buyers": "YP, PD, XC",
        "top_sellers": "ZP, AK, BK",
    },
    {
        "ticker": "GOTO",
        "sector": "PT GoTo Gojek Tokopedia Tbk (Technology)",
        "base_price": 66,
        "avg_vol_lot": 18_500_000,
        "avg_freq": 38_000,
        "scenario": "DISTRIBUTION",
        "top_buyers": "YP, XL, XC",
        "top_sellers": "MG, ZP, YU",
    },
    {
        "ticker": "TPIA",
        "sector": "PT Chandra Asri Pacific Tbk (Basic Industry)",
        "base_price": 8750,
        "avg_vol_lot": 390_000,
        "avg_freq": 15_200,
        "scenario": "MARKUP_BREAKOUT",
        "top_buyers": "MG, YU, ZP",
        "top_sellers": "YP, PD, NI",
    },
]

# Daftar kode saham riil IDX untuk membangkitkan universe 900 Emiten IDX
REAL_IDX_TICKERS_SEED = [
    "AALI", "ABBA", "ABDA", "ABMM", "ACES", "ACRO", "ACST", "ADCP", "ADES", "ADHI",
    "ADMF", "ADMG", "ADMR", "ADRO", "AEGS", "AGAR", "AGII", "AGRO", "AGRS", "AHAP",
    "AIMS", "AISA", "AKKU", "AKPI", "AKRA", "AKSI", "ALDO", "ALII", "ALKA", "ALMI",
    "ALTO", "AMAG", "AMAN", "AMAR", "AMFG", "AMIN", "AMMN", "AMMS", "AMOR", "AMRT",
    "ANDI", "ANJT", "ANTM", "APEX", "APIC", "APII", "APLI", "APLN", "ARCI", "AREA",
    "ARGO", "ARII", "ARKA", "ARKO", "ARMY", "ARNA", "ARTA", "ARTI", "ARTO", "ASBI",
    "ASDM", "ASGR", "ASHA", "ASII", "ASJT", "ASLC", "ASLI", "ASMI", "ASPI", "ASRI",
    "ASRM", "ASSA", "ATAP", "ATIC", "ATLA", "AUTO", "AVIA", "AWAN", "AXIO", "AYAM",
    "AYLS", "BABP", "BABY", "BACA", "BAIK", "BAJA", "BALI", "BANK", "BAPA", "BAPI",
    "BATA", "BATR", "BAUT", "BAYU", "BBCA", "BBHI", "BBKP", "BBLD", "BBMD", "BBNI",
    "BBRI", "BBRM", "BBSI", "BBSS", "BBTN", "BBYB", "BCAP", "BCIC", "BCIP", "BDKR",
    "BDMN", "BEBS", "BEEF", "BEER", "BEKS", "BELI", "BELL", "BESS", "BEST", "BFIN",
    "BGTG", "BHAT", "BHIT", "BIKA", "BIKE", "BIMA", "BINA", "BINO", "BIPI", "BIPP",
    "BIRD", "BISI", "BJBR", "BJTM", "BKDP", "BKSL", "BKSW", "BLTA", "BLTZ", "BLUE",
    "BMAS", "BMBL", "BMHS", "BMRI", "BMSR", "BMTR", "BNBA", "BNBR", "BNGA", "BNII",
    "BNLI", "BOAT", "BOBA", "BOGA", "BOLA", "BOLT", "BOSS", "BPFI", "BPII", "BPTR",
    "BRAM", "BREN", "BRIS", "BRMS", "BRNA", "BRPT", "BSBK", "BSDE", "BSIM", "BSML",
    "BSSR", "BSWD", "BTEK", "BTEL", "BTON", "BTPN", "BTPS", "BUAH", "BUDI", "BUKA",
    "BUKK", "BULL", "BUMI", "BUVA", "BVIC", "BWPT", "BYAN", "CAKK", "CAMP", "CANI",
    "CARE", "CARS", "CASA", "CASH", "CASS", "CBMF", "CBPE", "CBRE", "CBUT", "CCSI",
    "CEKA", "CENT", "CFIN", "CGAS", "CHEK", "CHEM", "CHIP", "CINT", "CITA", "CITY",
    "CLAY", "CLEO", "CLPI", "CMNP", "CMNT", "CMPP", "CMRY", "CNKO", "CNMA", "CNTX",
    "COAL", "COCO", "COWL", "CPIN", "CPRI", "CPRO", "CRAB", "CRSN", "CSAP", "CSIS",
    "CSMI", "CSRA", "CTBN", "CTRA", "CTTH", "CUAN", "CYBR", "DAAZ", "DADA", "DART",
    "DATA", "DAYA", "DCII", "DEAL", "DEFI", "DEPO", "DEWA", "DEWI", "DFAM", "DGIK",
    "DGNS", "DIGI", "DILD", "DIVA", "DKFT", "DKHH", "DLTA", "DMAS", "DMMX", "DMND",
    "DNAR", "DNET", "DOID", "DOOH", "DOSS", "DPNS", "DPUM", "DRMA", "DSFI", "DSNG",
    "DSSA", "DUCK", "DUTI", "DVLA", "DWGL", "DYAN", "EAST", "ECII", "EDGE", "EKAD",
    "ELIT", "ELPI", "ELSA", "ELTY", "EMDE", "EMTK", "ENAK", "ENRG", "ENVY", "ENZO",
    "EPAC", "EPMT", "ERAA", "ERAL", "ERTX", "ESIP", "ESSA", "ESTA", "FAST", "FASW",
    "FILM", "FIMP", "FIRE", "FISH", "FITT", "FLMC", "FMII", "FOLK", "FOOD", "FORU",
    "FPNI", "FREN", "FUJI", "FUTR", "FWCT", "GAMA", "GDST", "GDYR", "GEMA", "GEMS",
    "GGRM", "GGRP", "GHON", "GIAA", "GJTL", "GLOB", "GLVA", "GMFI", "GMTD", "GOLD",
    "GOLF", "GOLL", "GOOD", "GOTO", "GPRA", "GRIA", "GRPH", "GRPM", "GSMF", "GTBO",
    "GTRA", "GTSI", "GULA", "GUNA", "GWSA", "GZCO", "HADE", "HAIS", "HAJJ", "HALO",
    "HATM", "HBAT", "HDFA", "HDIT", "HEAL", "HELI", "HERO", "HEXA", "HILL", "HITS",
    "HKMU", "HMSP", "HOKI", "HOME", "HOMI", "HOPE", "HOTL", "HRME", "HRTA", "HRUM",
    "HUMI", "HYGN", "IATA", "IBFN", "IBOS", "IBST", "ICBP", "ICON", "IDEA", "IDPR",
    "IFII", "IFSH", "IGAR", "IIKP", "IKAI", "IKAN", "IKBI", "IKPM", "IMAS", "IMJS",
    "IMPC", "INAF", "INAI", "INCF", "INCI", "INCO", "INDF", "INDO", "INDR", "INDS",
    "INDX", "INDY", "INET", "INKP", "INOV", "INPC", "INPP", "INPS", "INRU", "INTA",
    "INTD", "INTP", "IOTF", "IPAC", "IPCC", "IPCM", "IPOL", "IPPE", "IPTV", "IRRA",
    "IRSX", "ISAP", "ISAT", "ISEA", "ISSP", "ITIC", "ITMA", "ITMG", "JARR", "JAST",
    "JAWA", "JAYA", "JECC", "JGLE", "JIHD", "JKON", "JMAS", "JPFA", "JRPT", "JSKY",
    "JSMR", "JSPT", "JTPE", "KAEF", "KARW", "KAYU", "KBAG", "KBLI", "KBLM", "KBLV",
    "KBRI", "KDSI", "KDTN", "KEEN", "KEJU", "KENT", "KICI", "KIJA", "KING", "KINO",
    "KIOS", "KJEN", "KKES", "KKGI", "KLAS", "KLBF", "KLIN", "KMDS", "KMTR", "KOBX",
    "KOCI", "KOIN", "KOKA", "KONI", "KOPI", "KOTA", "KPIG", "KRAS", "KREN", "KRYA",
    "KSIX", "KUAS", "LABA", "LABS", "LAJU", "LAND", "LAPD", "LCGP", "LCKM", "LEAD",
    "LFLO", "LIFE", "LINK", "LION", "LIVE", "LMAS", "LMAX", "LMPI", "LMSH", "LOPI",
    "LPCK", "LPGI", "LPIN", "LPKR", "LPLI", "LPPF", "LPPS", "LRNA", "LSIP", "LTLS",
    "LUCK", "LUCY", "MABA", "MAGP", "MAHA", "MAIN", "MAMI", "MANG", "MAPA", "MAPB",
    "MAPI", "MARI", "MARK", "MASA", "MASB", "MAXI", "MAYA", "MBAP", "MBMA", "MBSS",
    "MBTO", "MCAS", "MCOL", "MCOR", "MDIA", "MDIY", "MDKA", "MDKI", "MDLA", "MDLN",
    "MDRN", "MEDC", "MEDS", "MEGA", "MEJA", "MENN", "MERK", "META", "MFIN", "MFMI",
    "MGLV", "MGNA", "MGRO", "MHKI", "MICE", "MIDI", "MIKA", "MINA", "MIRA", "MITI",
    "MKAP", "MKNT", "MKPI", "MKTR", "MLBI", "MLIA", "MLPL", "MLPT", "MMIX", "MMLP",
    "MNCN", "MOLI", "MORA", "MPIX", "MPMX", "MPOW", "MPPA", "MPRO", "MPXL", "MRAT",
    "MREI", "MSIE", "MSIN", "MSJA", "MSKY", "MSTI", "MTDL", "MTEL", "MTFN", "MTLA",
    "MTMH", "MTPS", "MTRA", "MTSM", "MTWI", "MUTU", "MYOH", "MYOR", "MYTX", "NANO",
    "NASA", "NASI", "NATO", "NAYZ", "NCKL", "NELY", "NEST", "NETV", "NFCX", "NICE",
    "NICK", "NICL", "NIKL", "NINE", "NIRO", "NISP", "NOBU", "NPGF", "NRCA", "NSSS",
    "NTBK", "NUSA", "NZIA", "OASA", "OBMD", "OCAP", "OILS", "OKAS", "OLIV", "OMED",
    "OMRE", "OPMS", "PACK", "PADA", "PADI", "PALM", "PAMG", "PANI", "PANR", "PANS",
    "PART", "PBID", "PBRX", "PBSA", "PCAR", "PDES", "PDPP", "PEGE", "PEHA", "PEVE",
    "PGAS", "PGEO", "PGJO", "PGLI", "PGUN", "PICO", "PIPA", "PJAA", "PKPK", "PLAN",
    "PLAS", "PLIN", "PMJS", "PMMP", "PMUI", "PNBN", "PNBS", "PNGO", "PNIN", "PNLF",
    "PNSE", "POLA", "POLI", "POLL", "POLU", "POLY", "POOL", "PORT", "POSA", "POWR",
    "PPGL", "PPRE", "PPRI", "PPRO", "PRAS", "PRAY", "PRDA", "PRIM", "PSAB", "PSDN",
    "PSGO", "PSKT", "PSSI", "PTBA", "PTDU", "PTIS", "PTMP", "PTMR", "PTPP", "PTPS",
    "PTRO", "PTSN", "PTSP", "PUDP", "PURA", "PURE", "PURI", "PWON", "PYFA", "PZZA",
    "RAAM", "RAFI", "RAJA", "RALS", "RANC", "RBMS", "RCCC", "RDTX", "REAL", "RELF",
    "RELI", "RGAS", "RICY", "RIGS", "RIMO", "RISE", "RMKE", "RMKO", "ROCK", "RODA",
    "RONY", "ROTI", "RSCH", "RSGK", "RUIS", "RUNS", "SAFE", "SAGE", "SAME", "SAMF",
    "SAPX", "SATU", "SBAT", "SBMA", "SCCO", "SCMA", "SCNP", "SCPI", "SDMU", "SDPC",
    "SDRA", "SEMA", "SFAN", "SGER", "SGRO", "SHID", "SHIP", "SICO", "SIDO", "SILO",
    "SIMA", "SIMP", "SINI", "SIPD", "SKBM", "SKLT", "SKRN", "SKYB", "SLIS", "SMAR",
    "SMBR", "SMCB", "SMDM", "SMDR", "SMGA", "SMGR", "SMIL", "SMKL", "SMKM", "SMLE",
    "SMMA", "SMMT", "SMRA", "SMRU", "SMSM", "SNLK", "SOCI", "SOFA", "SOHO", "SOLA",
    "SONA", "SOSS", "SOTS", "SOUL", "SPMA", "SPRE", "SPTO", "SQMI", "SRAJ", "SRIL",
    "SRSN", "SRTG", "SSIA", "SSMS", "SSTM", "STAA", "STAR", "STTP", "SUGI", "SULI",
    "SUNI", "SUPR", "SURE", "SURI", "SWAT", "SWID", "TALF", "TAMA", "TAMU", "TAPG",
    "TARA", "TAXI", "TAYS", "TBIG", "TBLA", "TBMS", "TCID", "TCPI", "TDPM", "TEBE",
    "TECH", "TELE", "TFAS", "TFCO", "TGKA", "TGRA", "TGUK", "TIFA", "TINS", "TIRA",
    "TIRT", "TKIM", "TLDN", "TLKM", "TMAS", "TMPO", "TNCA", "TOBA", "ZATA", "ZYRX",
]

SECTOR_POOL = [
    "Banking & Financials",
    "Energy & Coal Mining",
    "Minerals & Metals",
    "Consumer Non-Cyclicals",
    "Consumer Cyclicals",
    "Property & Real Estate",
    "Infrastructure & Telecom",
    "Basic Materials & Petrochem",
    "Healthcare & Pharma",
    "Technology & Digital",
    "Industrial & Logistics",
]

COLUMN_GUIDES = [
    ("Date", "Wajib", "Tanggal transaksi format YYYY-MM-DD (Contoh: 2026-10-08)."),
    ("Ticker", "Wajib", "Kode saham 4 huruf di BEI / IDX (Contoh: BBCA, BREN, ADRO)."),
    ("Sector", "Opsional", "Nama Perusahaan / Sektor industri emiten."),
    ("Open", "Opsional", "Harga pembukaan harian (IDR)."),
    ("High", "Opsional", "Harga tertinggi harian (IDR)."),
    ("Low", "Opsional", "Harga terendah harian (IDR)."),
    ("Close", "Opsional", "Harga penutupan harian (IDR). (Jika kosong/hanya daftar nama saham, sistem otomatis mengisi simulasi pasar)."),
    ("Volume_Lot", "Opsional", "Total volume transaksi harian dalam satuan Lot."),
    ("Value_IDR", "Opsional", "Total nilai transaksi harian dalam Rupiah."),
    ("Frequency", "Opsional", "Total frekuensi transaksi hari itu."),
    ("Top1_Buy_Lot", "Opsional", "Jumlah Lot beli bersih Broker Pembeli #1 terbesar."),
    ("Top3_Buy_Lot", "Opsional", "Total Lot beli bersih 3 Broker Pembeli terbesar."),
    ("Top5_Buy_Lot", "Opsional", "Total Lot beli bersih 5 Broker Pembeli terbesar."),
    ("Top1_Sell_Lot", "Opsional", "Jumlah Lot jual bersih Broker Penjual #1 terbesar."),
    ("Top3_Sell_Lot", "Opsional", "Total Lot jual bersih 3 Broker Penjual terbesar."),
    ("Top5_Sell_Lot", "Opsional", "Total Lot jual bersih 5 Broker Penjual terbesar."),
    ("Top_Buyer_Brokers", "Opsional", "Kode sekuritas Top 3 Pembeli (Contoh: ZP, AK, MG)."),
    ("Top_Seller_Brokers", "Opsional", "Kode sekuritas Top 3 Penjual (Contoh: YP, PD, XC)."),
    ("Bandar_Avg_Buy", "Opsional", "Rata-rata harga beli Top 3 Broker Pembeli."),
    ("Foreign_Buy_Val", "Opsional", "Nilai transaksi beli investor asing (IDR)."),
    ("Foreign_Sell_Val", "Opsional", "Nilai transaksi jual investor asing (IDR)."),
]


def _get_trading_dates(num_days: int = 25) -> list[str]:
    dates: list[str] = []
    cur = datetime(2026, 10, 8)
    while len(dates) < num_days:
        if cur.weekday() < 5:
            dates.append(cur.strftime("%Y-%m-%d"))
        cur -= timedelta(days=1)
    dates.reverse()
    return dates


def generate_900_idx_master_tickers_df() -> pd.DataFrame:
    """
    Menghasilkan DataFrame Master 900 Emiten IDX (Kode Saham + Nama Perusahaan + Sektor).
    """
    tickers = list(dict.fromkeys(REAL_IDX_TICKERS_SEED))
    rng = np.random.default_rng(900)
    alphabet = list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    while len(tickers) < 900:
        cand = "".join(rng.choice(alphabet, size=4))
        if cand not in tickers and cand not in {"KODE", "NAMA", "DATE", "OPEN", "HIGH", "LAST"}:
            tickers.append(cand)

    tickers = tickers[:900]
    sectors = [SECTOR_POOL[i % len(SECTOR_POOL)] for i in range(len(tickers))]
    names = [f"PT Emiten {t} Indonesia Tbk" for t in tickers]

    return pd.DataFrame(
        {
            "Ticker": tickers,
            "Company_Name": names,
            "Sector": sectors,
        }
    )


def generate_sample_dataframe(num_days: int = 25) -> pd.DataFrame:
    """Membuat DataFrame simulasi 15 saham unggulan IDX selama `num_days` hari bursa."""
    rng = np.random.default_rng(42)
    dates = _get_trading_dates(num_days)
    rows = []

    for prof in IDX_SAMPLE_PROFILES:
        ticker = prof["ticker"]
        sector = prof["sector"]
        price = float(prof["base_price"])
        base_vol = float(prof["avg_vol_lot"])
        base_freq = float(prof["avg_freq"])
        scenario = prof["scenario"]

        for d_idx, date_str in enumerate(dates):
            is_last_5 = d_idx >= (num_days - 5)
            is_last_2 = d_idx >= (num_days - 2)
            is_last_1 = d_idx == (num_days - 1)

            pct_move = rng.normal(0.0005, 0.011)
            vol_mult = rng.uniform(0.78, 1.22)
            freq_mult = rng.uniform(0.85, 1.15)
            top3_buy_share = rng.uniform(0.24, 0.32)
            top3_sell_share = rng.uniform(0.24, 0.32)
            foreign_buy_ratio = rng.uniform(0.18, 0.28)
            foreign_sell_ratio = rng.uniform(0.18, 0.28)
            close_pos = rng.uniform(0.35, 0.70)

            if scenario == "MARKUP_BREAKOUT":
                if is_last_5 and not is_last_2:
                    pct_move = rng.uniform(0.001, 0.009)
                    vol_mult = rng.uniform(1.15, 1.45)
                    freq_mult = rng.uniform(0.80, 0.95)
                    top3_buy_share = rng.uniform(0.36, 0.44)
                    top3_sell_share = rng.uniform(0.20, 0.25)
                    foreign_buy_ratio = rng.uniform(0.32, 0.42)
                    foreign_sell_ratio = rng.uniform(0.16, 0.22)
                    close_pos = rng.uniform(0.65, 0.82)
                elif is_last_2:
                    pct_move = rng.uniform(0.028, 0.052) if is_last_1 else rng.uniform(0.016, 0.032)
                    vol_mult = rng.uniform(2.65, 3.60) if is_last_1 else rng.uniform(1.85, 2.35)
                    freq_mult = rng.uniform(1.25, 1.55)
                    top3_buy_share = rng.uniform(0.45, 0.54)
                    top3_sell_share = rng.uniform(0.19, 0.24)
                    foreign_buy_ratio = rng.uniform(0.38, 0.48)
                    foreign_sell_ratio = rng.uniform(0.14, 0.20)
                    close_pos = rng.uniform(0.82, 0.96)

            elif scenario == "BIG_ACCUM":
                if is_last_5:
                    pct_move = rng.uniform(0.004, 0.018)
                    vol_mult = rng.uniform(1.55, 2.25) if is_last_1 else rng.uniform(1.25, 1.65)
                    freq_mult = rng.uniform(0.85, 1.05)
                    top3_buy_share = rng.uniform(0.46, 0.56)
                    top3_sell_share = rng.uniform(0.18, 0.23)
                    foreign_buy_ratio = rng.uniform(0.30, 0.40)
                    foreign_sell_ratio = rng.uniform(0.18, 0.24)
                    close_pos = rng.uniform(0.68, 0.88)

            elif scenario == "SILENT_ACCUM":
                if is_last_5:
                    pct_move = rng.uniform(-0.003, 0.009)
                    vol_mult = rng.uniform(1.25, 1.65)
                    freq_mult = rng.uniform(0.72, 0.88)
                    top3_buy_share = rng.uniform(0.41, 0.49)
                    top3_sell_share = rng.uniform(0.21, 0.26)
                    foreign_buy_ratio = rng.uniform(0.27, 0.35)
                    foreign_sell_ratio = rng.uniform(0.19, 0.24)
                    close_pos = rng.uniform(0.62, 0.80)

            elif scenario == "FOREIGN_INFLOW":
                if is_last_5:
                    pct_move = rng.uniform(0.006, 0.021)
                    vol_mult = rng.uniform(1.35, 1.95)
                    freq_mult = rng.uniform(0.95, 1.15)
                    top3_buy_share = rng.uniform(0.35, 0.42)
                    top3_sell_share = rng.uniform(0.24, 0.29)
                    foreign_buy_ratio = rng.uniform(0.48, 0.62)
                    foreign_sell_ratio = rng.uniform(0.18, 0.24)
                    close_pos = rng.uniform(0.70, 0.88)

            elif scenario == "DISTRIBUTION":
                if is_last_5:
                    pct_move = rng.uniform(-0.028, -0.006)
                    vol_mult = rng.uniform(1.50, 2.40)
                    freq_mult = rng.uniform(1.40, 1.90)
                    top3_buy_share = rng.uniform(0.17, 0.22)
                    top3_sell_share = rng.uniform(0.44, 0.55)
                    foreign_buy_ratio = rng.uniform(0.12, 0.18)
                    foreign_sell_ratio = rng.uniform(0.38, 0.52)
                    close_pos = rng.uniform(0.08, 0.28)

            prev_close = price
            close_price = max(50.0, round(prev_close * (1.0 + pct_move)))
            spread = max(2.0, round(close_price * rng.uniform(0.014, 0.032)))
            low_price = max(50.0, round(close_price - spread * close_pos))
            high_price = max(close_price, low_price + spread)
            open_price = round(low_price + (high_price - low_price) * (1.0 - close_pos * 0.7))
            open_price = min(max(open_price, low_price), high_price)
            price = close_price

            vol_lot = int(round(base_vol * vol_mult))
            freq = max(100, int(round(base_freq * freq_mult)))
            typical_price = (high_price + low_price + close_price) / 3.0
            value_idr = int(round(vol_lot * 100.0 * typical_price))

            top3_buy_lot = int(round(vol_lot * top3_buy_share))
            top1_buy_lot = int(round(top3_buy_lot * rng.uniform(0.45, 0.58)))
            top5_buy_lot = int(round(top3_buy_lot * rng.uniform(1.22, 1.35)))

            top3_sell_lot = int(round(vol_lot * top3_sell_share))
            top1_sell_lot = int(round(top3_sell_lot * rng.uniform(0.45, 0.58)))
            top5_sell_lot = int(round(top3_sell_lot * rng.uniform(1.22, 1.35)))

            bandar_avg_buy = round(typical_price * rng.uniform(0.993, 1.002))
            foreign_buy_val = int(round(value_idr * foreign_buy_ratio))
            foreign_sell_val = int(round(value_idr * foreign_sell_ratio))

            rows.append(
                {
                    "Date": date_str,
                    "Ticker": ticker,
                    "Sector": sector,
                    "Open": int(open_price),
                    "High": int(high_price),
                    "Low": int(low_price),
                    "Close": int(close_price),
                    "Volume_Lot": vol_lot,
                    "Value_IDR": value_idr,
                    "Frequency": freq,
                    "Top1_Buy_Lot": top1_buy_lot,
                    "Top3_Buy_Lot": top3_buy_lot,
                    "Top5_Buy_Lot": top5_buy_lot,
                    "Top1_Sell_Lot": top1_sell_lot,
                    "Top3_Sell_Lot": top3_sell_lot,
                    "Top5_Sell_Lot": top5_sell_lot,
                    "Top_Buyer_Brokers": prof["top_buyers"],
                    "Top_Seller_Brokers": prof["top_sellers"],
                    "Bandar_Avg_Buy": int(bandar_avg_buy),
                    "Foreign_Buy_Val": foreign_buy_val,
                    "Foreign_Sell_Val": foreign_sell_val,
                }
            )

    return pd.DataFrame(rows)


def build_excel_bytes(mode: Literal["sample", "blank"] = "sample") -> bytes:
    df = generate_sample_dataframe(25)
    if mode == "blank":
        df = df.tail(3).copy()

    wb = Workbook()
    ws_data = wb.active
    ws_data.title = "SmartMoney_Data"

    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    bandar_fill = PatternFill(start_color="064E3B", end_color="064E3B", fill_type="solid")
    foreign_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10, color="111827")
    thin_border = Border(
        left=Side(style="thin", color="CBD5E1"),
        right=Side(style="thin", color="CBD5E1"),
        top=Side(style="thin", color="CBD5E1"),
        bottom=Side(style="thin", color="CBD5E1"),
    )

    columns = list(df.columns)
    ws_data.append(columns)

    for col_idx, col_name in enumerate(columns, start=1):
        cell = ws_data.cell(row=1, column=col_idx)
        cell.font = header_font
        if "Top" in col_name or "Bandar" in col_name:
            cell.fill = bandar_fill
        elif "Foreign" in col_name:
            cell.fill = foreign_fill
        else:
            cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)

    for row_data in df.itertuples(index=False):
        ws_data.append(list(row_data))

    for row in ws_data.iter_rows(min_row=2, max_row=ws_data.max_row, min_col=1, max_col=len(columns)):
        for cell in row:
            cell.font = data_font
            cell.border = thin_border
            if isinstance(cell.value, (int, float)):
                cell.number_format = "#,##0"

    ws_data.freeze_panes = "C2"
    ws_data.row_dimensions[1].height = 28

    for col_idx, col_name in enumerate(columns, start=1):
        col_letter = get_column_letter(col_idx)
        ws_data.column_dimensions[col_letter].width = max(len(col_name) + 5, 14)

    ws_guide = wb.create_sheet(title="Panduan_Kolom")
    ws_guide.append(["Nama Kolom", "Status", "Penjelasan & Cara Mengambil Data"])
    for col_idx in range(1, 4):
        c = ws_guide.cell(row=1, column=col_idx)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center", vertical="center")

    for col_name, status, desc in COLUMN_GUIDES:
        ws_guide.append([col_name, status, desc])

    for row in ws_guide.iter_rows(min_row=2, max_row=ws_guide.max_row, min_col=1, max_col=3):
        for cell in row:
            cell.font = data_font
            cell.border = thin_border
            cell.alignment = Alignment(vertical="center", wrap_text=True)

    ws_guide.column_dimensions["A"].width = 24
    ws_guide.column_dimensions["B"].width = 18
    ws_guide.column_dimensions["C"].width = 85
    ws_guide.row_dimensions[1].height = 26

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def ensure_default_excel_files(base_dir: Path) -> Path:
    data_dir = base_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    sample_path = data_dir / "sample_smart_money_idx.xlsx"
    blank_path = data_dir / "blank_template_smart_money.xlsx"
    master_900_path = data_dir / "daftar_900_emiten_idx.xlsx"

    sample_path.write_bytes(build_excel_bytes("sample"))
    blank_path.write_bytes(build_excel_bytes("blank"))
    if not master_900_path.exists():
        df_900 = generate_900_idx_master_tickers_df()
        df_900.to_excel(master_900_path, index=False)
    return sample_path
