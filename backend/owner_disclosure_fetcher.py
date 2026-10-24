"""
Radar Aksi Owner — Tracking Laporan Kepemilikan / Perubahan Kepemilikan Saham (KSEI via IDX).

Sumber data resmi:
    Pengumuman IDX berjudul "LAPORAN KEPEMILIKAN ATAU SETIAP PERUBAHAN KEPEMILIKAN SAHAM PERUSAHAAN TERBUKA"
    (dokumen PDF dari folder From_KSEI, diterbitkan via layanan AKSes KSEI sesuai POJK 4/2024).

Setiap laporan berisi: nama pihak pelapor, status Direksi/Komisaris, status pengendali,
jumlah saham & hak suara sebelum -> sesudah transaksi, serta rincian transaksi (jenis, lembar, harga, tanggal, tujuan).

Data disimpan ke data/owner_disclosures.json dan diperbarui otomatis oleh background worker.
Seluruh angka berasal 1:1 dari dokumen resmi — tidak ada data estimasi/karangan.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data" / "owner_disclosures.json"

IDX_LIST_URL = "https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
IDX_REFERER = "https://www.idx.co.id/id/berita/pengumuman/"
TITLE_KEY = "PERUBAHAN KEPEMILIKAN SAHAM"
RETENTION_DAYS = 120
BACKFILL_DAYS = 14

_LOCK = threading.Lock()
_STATUS: dict[str, Any] = {"last_run": None, "last_ok": None, "last_error": None, "added": 0, "running": False}

MONTHS_ID = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "may": 5, "jun": 6, "jul": 7,
    "agu": 8, "agt": 8, "aug": 8, "sep": 9, "okt": 10, "oct": 10, "nov": 11, "des": 12, "dec": 12,
}
TX_TYPES = (
    "Pembelian", "Penjualan", "Pelaksanaan", "Hibah", "Waris", "Lainnya", "Konversi",
    "Pengalihan", "Penerimaan", "Pemberian", "Penawaran Tender", "Pembagian", "Transfer",
)


# --------------------------------------------------------------------------- helpers
def _now_wib() -> datetime:
    return datetime.now(WIB)


def _num_id(s: str | None) -> float:
    """Konversi angka format Indonesia ('1.234.567,89') -> float."""
    if not s:
        return 0.0
    s = s.strip().replace(" ", "")
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _rx(pattern: str, text: str, flags: int = 0) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else ""


def _clean_purpose(p: str) -> str:
    """Buang header tabel yang terulang di halaman PDF berikutnya ('Jenis Transaksi ...')."""
    p = re.split(r"\s*Jenis\s+Transaksi\b", p or "")[0]
    return p.strip(" -,")[:120]


def _session():
    try:
        from curl_cffi import requests as cffi_requests  # Wajib: IDX dilindungi Cloudflare

        return cffi_requests.Session(impersonate="chrome")
    except Exception:
        import requests as std_requests

        s = std_requests.Session()
        s.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json, text/plain, */*",
            }
        )
        return s


# --------------------------------------------------------------------------- storage
def _load() -> dict:
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"updated_at": None, "items": {}}


def _save(db: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(DATA_FILE)


# --------------------------------------------------------------------------- parser
def parse_disclosure_text(full_text: str) -> dict | None:
    """Parse teks PDF laporan KSEI (bagian Bahasa Indonesia) menjadi record terstruktur."""
    txt = full_text.split("REPORT OF OWNERSHIP")[0]
    if "Jumlah Saham Sebelum Transaksi" not in txt:
        return None

    company_raw = _rx(r"Nama Perusahaan Tbk\s*:\s*(.+?)\n\s*Jumlah Saham", txt, re.S)
    company_raw = re.sub(r"\s+", " ", company_raw)
    m_code = re.match(r"([A-Z0-9]{4})\s*-\s*(.+)", company_raw)
    ticker = m_code.group(1) if m_code else ""
    company = m_code.group(2).strip().rstrip(",") if m_code else company_raw

    rec: dict[str, Any] = {
        "ticker": ticker,
        "company": company,
        "holder": re.sub(r"\s+", " ", _rx(r"Nama \(sesuai SID\)\s*:\s*(.+)", txt)),
        "is_insider": _rx(r"Anggota Direksi/Dewan Komisaris\s*:\s*(\w+)", txt).lower() == "ya",
        "position": _rx(r"Jabatan[ \t]*:[ \t]*([^\n]*)", txt),
        "citizenship": _rx(r"Kewarganegaraan[ \t]*:[ \t]*([^\n]*)", txt),
        "is_controller": _rx(r"Keterangan Pengendali\s*:\s*(\w+)", txt).lower() == "ya",
        "shares_before": _num_id(_rx(r"Jumlah Saham Sebelum Transaksi\s*:\s*([\d\.,]+)", txt)),
        "shares_after": _num_id(_rx(r"Jumlah Saham Setelah Transaksi\s*:\s*([\d\.,]+)", txt)),
        "pct_before": _num_id(_rx(r"Hak Suara Sebelum Transaksi\s*:\s*([\d\.,]+)\s*%", txt)),
        "pct_after": _num_id(_rx(r"Hak Suara Setelah Transaksi\s*:\s*([\d\.,]+)\s*%", txt)),
        "report_no": _rx(r"Nomor\s*:\s*(LK/\S+)", txt),
    }
    if rec["position"] in ("-", ""):
        rec["position"] = ""

    # Rincian transaksi (tabel: Jenis | Status | ... | Jumlah Saham | Klasifikasi | Harga | Tanggal | Tujuan)
    flat = re.sub(r"\s+", " ", txt)
    start = flat.find("Tujuan Transaksi")
    body = flat[start + len("Tujuan Transaksi"):] if start >= 0 else flat
    stop = re.search(r" (Saya bertanggung jawab|Pemberi Kuasa|Keterangan Pengendali)", body)
    if stop:
        body = body[: stop.start()]
    type_rx = re.compile(
        r"(" + "|".join(TX_TYPES) + r")(?: \(exercise\) Efek Bersifat Ekuitas)? (?:Ya|Tidak)\b"
    )
    tx_rx = re.compile(
        r"([\d\.]+,\d{2}) Saham (?:[A-Za-z]+ ){0,6}?(-|[\d\.]+,\d{2}) (\d{1,2})- ?([A-Za-z]{3})- ?(\d{4})"
    )
    type_hits = [(m.start(), m.group(1)) for m in type_rx.finditer(body)]
    matches = list(tx_rx.finditer(body))
    txs: list[dict] = []
    for i, m in enumerate(matches):
        prior = [t for pos, t in type_hits if pos < m.start()]
        tx_type = prior[-1] if prior else "Lainnya"
        mon = MONTHS_ID.get(m.group(4).lower()[:3], 0)
        tx_date = f"{m.group(5)}-{mon:02d}-{int(m.group(3)):02d}" if mon else ""
        # Tujuan transaksi: teks setelah tanggal hingga baris transaksi berikutnya
        nxt_types = [pos for pos, _ in type_hits if pos > m.end()]
        end_pos = min([matches[i + 1].start()] + nxt_types) if i + 1 < len(matches) else (nxt_types[0] if nxt_types else len(body))
        purpose = body[m.end():end_pos].strip(" -")
        purpose = _clean_purpose(re.sub(r"\s+", " ", purpose))
        txs.append({
            "type": tx_type,
            "shares": _num_id(m.group(1)),
            "price": 0.0 if m.group(2) == "-" else _num_id(m.group(2)),
            "date": tx_date,
            "purpose": purpose,
        })
    rec["transactions"] = txs

    delta = rec["shares_after"] - rec["shares_before"]
    rec["delta_shares"] = delta
    rec["delta_pct"] = round(rec["pct_after"] - rec["pct_before"], 4)
    rec["side"] = "BUY" if delta > 0 else ("SELL" if delta < 0 else "NEUTRAL")

    market_tx = [t for t in txs if t["type"] in ("Pembelian", "Penjualan") and t["price"] > 0]
    rec["is_market_trade"] = bool(market_tx)
    tot_sh = sum(t["shares"] for t in market_tx)
    rec["avg_price"] = round(sum(t["shares"] * t["price"] for t in market_tx) / tot_sh, 2) if tot_sh else 0.0
    if not rec["avg_price"]:
        priced = [t for t in txs if t["price"] > 0]
        sh = sum(t["shares"] for t in priced)
        rec["avg_price"] = round(sum(t["shares"] * t["price"] for t in priced) / sh, 2) if sh else 0.0
    rec["value_idr"] = round(abs(delta) * rec["avg_price"], 0) if rec["avg_price"] else 0.0
    dates = sorted(t["date"] for t in txs if t["date"])
    rec["tx_date"] = dates[-1] if dates else ""
    rec["tx_types"] = sorted({t["type"] for t in txs})
    rec["is_major"] = max(rec["pct_before"], rec["pct_after"]) >= 5.0
    rec["crossed_5pct"] = (rec["pct_before"] < 5.0 <= rec["pct_after"]) or (rec["pct_after"] < 5.0 <= rec["pct_before"])
    purposes = " ".join(t["purpose"] for t in txs).lower()
    # Repo / pinjam-meminjam saham / gadai bukan cerminan keyakinan owner (perpindahan sementara)
    rec["is_repo_or_loan"] = bool(re.search(r"repo|pinjam|meminjam|gadai|jaminan|free of payment", purposes))
    return rec


def _pdf_to_text(pdf_bytes: bytes) -> str:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((pg.extract_text() or "") for pg in reader.pages)


# --------------------------------------------------------------------------- fetcher
def _list_announcements(sess, date_from: str, date_to: str) -> list[dict]:
    """Ambil daftar pengumuman laporan kepemilikan pada rentang tanggal (format YYYYMMDD)."""
    out: list[dict] = []
    seen: set[str] = set()
    page_size = 50
    for page in range(0, 40):
        params = {
            # Catatan: indexFrom pada API IDX adalah NOMOR HALAMAN (0, 1, 2, ...), bukan offset baris
            "kodeEmiten": "", "emitenType": "*", "indexFrom": page, "pageSize": page_size,
            "dateFrom": date_from, "dateTo": date_to, "lang": "id", "keyword": "LAPORAN KEPEMILIKAN",
        }
        r = sess.get(IDX_LIST_URL, params=params, headers={"Referer": IDX_REFERER}, timeout=30)
        r.raise_for_status()
        js = r.json()
        replies = js.get("Replies") or []
        new_cnt = 0
        for it in replies:
            p = it.get("pengumuman") or {}
            if TITLE_KEY not in str(p.get("JudulPengumuman") or "").upper():
                continue
            no = str(p.get("NoPengumuman") or "").strip()
            if not no or no in seen:
                continue
            att = [a for a in (it.get("attachments") or []) if "From_KSEI" in str(a.get("FullSavePath") or "")]
            if not att:
                continue
            seen.add(no)
            new_cnt += 1
            out.append({
                "no": no,
                "code": str(p.get("Kode_Emiten") or "").strip(),
                "published": str(p.get("TglPengumuman") or ""),
                "pdf_url": att[0]["FullSavePath"],
            })
        total = int(js.get("ResultCount") or 0)
        if not replies or (page + 1) * page_size >= total:
            break
        time.sleep(0.2)
    return out


def sync_owner_disclosures(days: int = 2, max_new: int = 400) -> dict:
    """Tarik laporan kepemilikan terbaru dari IDX, parse PDF yang belum tersimpan, simpan ke disk."""
    if _STATUS["running"]:
        return {"ok": False, "reason": "already_running"}
    _STATUS["running"] = True
    _STATUS["last_run"] = _now_wib().strftime("%Y-%m-%d %H:%M:%S")
    added = 0
    failed = 0
    try:
        sess = _session()
        now = _now_wib()
        d_from = (now - timedelta(days=max(1, days))).strftime("%Y%m%d")
        d_to = now.strftime("%Y%m%d")
        listing = _list_announcements(sess, d_from, d_to)

        with _LOCK:
            db = _load()
        items: dict = db.setdefault("items", {})

        for ann in listing:
            if added >= max_new:
                break
            if ann["no"] in items:
                continue
            try:
                r = sess.get(ann["pdf_url"], headers={"Referer": IDX_REFERER}, timeout=30)
                r.raise_for_status()
                rec = parse_disclosure_text(_pdf_to_text(r.content))
            except Exception as exc:
                failed += 1
                print(f"[OwnerRadar] Gagal parse {ann['no']}: {exc}")
                continue
            if not rec:
                failed += 1
                continue
            rec["ticker"] = rec.get("ticker") or ann["code"]
            rec["announcement_no"] = ann["no"]
            rec["published"] = ann["published"]
            rec["pdf_url"] = ann["pdf_url"]
            items[ann["no"]] = rec
            added += 1
            time.sleep(0.25)

        # Retensi
        cutoff = (now - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
        for k in [k for k, v in items.items() if str(v.get("published", ""))[:10] < cutoff]:
            items.pop(k, None)

        db["updated_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
        with _LOCK:
            _save(db)
        _STATUS.update(last_ok=db["updated_at"], last_error=None, added=added)
        print(f"[OwnerRadar] Sinkron selesai: {len(listing)} laporan ditemukan, {added} baru, {failed} gagal.")
        return {"ok": True, "found": len(listing), "added": added, "failed": failed}
    except Exception as exc:
        _STATUS["last_error"] = str(exc)
        print(f"[OwnerRadar] Error sinkron: {exc}")
        return {"ok": False, "reason": str(exc)}
    finally:
        _STATUS["running"] = False


# --------------------------------------------------------------------------- query API
def _public_view(rec: dict) -> dict:
    keys = (
        "announcement_no", "published", "tx_date", "ticker", "company", "holder", "is_insider", "position",
        "is_controller", "citizenship", "shares_before", "shares_after", "pct_before", "pct_after",
        "delta_shares", "delta_pct", "side", "avg_price", "value_idr", "is_market_trade", "tx_types",
        "is_major", "crossed_5pct", "is_repo_or_loan", "transactions", "pdf_url",
    )
    out = {k: rec.get(k) for k in keys}
    out["transactions"] = [{**t, "purpose": _clean_purpose(t.get("purpose", ""))} for t in (rec.get("transactions") or [])]
    return out


def get_owner_actions(
    days: int = 7,
    ticker: str | None = None,
    scope: str = "major",
    side: str = "ALL",
    limit: int = 200,
) -> dict:
    """scope: 'major' (pemegang >= 5%), 'insider' (Direksi/Komisaris), 'all'. side: ALL/BUY/SELL."""
    with _LOCK:
        db = _load()
    items = list((db.get("items") or {}).values())
    cutoff = (_now_wib() - timedelta(days=max(1, days))).strftime("%Y-%m-%d")
    t_up = (ticker or "").upper().strip()
    side_up = (side or "ALL").upper()
    scope_l = (scope or "major").lower()

    rows = []
    for r in items:
        if str(r.get("published", ""))[:10] < cutoff and not t_up:
            continue
        if t_up and r.get("ticker") != t_up:
            continue
        if scope_l == "major" and not r.get("is_major"):
            continue
        if scope_l == "insider" and not r.get("is_insider"):
            continue
        if side_up in ("BUY", "SELL") and r.get("side") != side_up:
            continue
        if r.get("side") == "NEUTRAL" and scope_l != "all":
            continue
        rows.append(_public_view(r))

    rows.sort(key=lambda x: (str(x.get("published") or ""), abs(float(x.get("delta_shares") or 0))), reverse=True)
    rows = rows[: max(1, limit)]
    return {
        "updated_at": db.get("updated_at"),
        "count": len(rows),
        "emiten_count": len({r["ticker"] for r in rows}),
        "buy_count": sum(1 for r in rows if r["side"] == "BUY"),
        "sell_count": sum(1 for r in rows if r["side"] == "SELL"),
        "items": rows,
        "status": dict(_STATUS),
        "source": "KSEI via IDX — Laporan Kepemilikan atau Setiap Perubahan Kepemilikan Saham (POJK 4/2024)",
    }


def get_ticker_owner_summary(ticker: str, days: int = 30) -> dict:
    """Ringkasan aksi owner untuk satu emiten (dipakai panel saham, screener & chatbot)."""
    data = get_owner_actions(days=days, ticker=ticker, scope="all", limit=50)
    items = [r for r in data["items"] if r["side"] != "NEUTRAL"]
    cutoff = (_now_wib() - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = [r for r in items if str(r.get("published") or "")[:10] >= cutoff]
    buy_sh = sum(r["delta_shares"] for r in recent if r["side"] == "BUY")
    sell_sh = -sum(r["delta_shares"] for r in recent if r["side"] == "SELL")
    net = buy_sh - sell_sh
    signal = "NONE"
    if recent:
        def _key(r: dict, side_name: str) -> bool:
            return (
                r["side"] == side_name
                and (r["is_major"] or r["is_controller"] or r["is_insider"])
                and r["is_market_trade"]
                and not r.get("is_repo_or_loan")
            )

        key_buy = any(_key(r, "BUY") for r in recent)
        key_sell = any(_key(r, "SELL") for r in recent)
        if net > 0 and key_buy:
            signal = "ACCUMULATION"
        elif net < 0 and key_sell:
            signal = "DISTRIBUTION"
        else:
            signal = "MIXED"
    major_feed = get_owner_actions(days=7, scope="major", side="ALL", limit=30)
    return {
        "ticker": ticker.upper(),
        "days": days,
        "signal": signal,
        "net_shares": net,
        "buy_shares": buy_sh,
        "sell_shares": sell_sh,
        "reports": len(recent),
        "items": items[:12],
        "latest_major_items": major_feed.get("items", [])[:25],
        "major_changes_count": major_feed.get("count", 0),
        "major_emiten_count": major_feed.get("emiten_count", 0),
        "major_buy_count": major_feed.get("buy_count", 0),
        "major_sell_count": major_feed.get("sell_count", 0),
        "updated_at": data["updated_at"],
    }


def get_status() -> dict:
    with _LOCK:
        db = _load()
    return {**_STATUS, "total_cached": len(db.get("items") or {}), "updated_at": db.get("updated_at")}


# --------------------------------------------------------------------------- worker
async def background_owner_disclosure_worker() -> None:
    """Sinkron otomatis: backfill 14 hari saat start, lalu tiap 20 menit (06:00-23:30 WIB)."""
    print("[OwnerRadar] Background worker Radar Aksi Owner aktif.")
    await asyncio.sleep(15)
    try:
        await asyncio.to_thread(sync_owner_disclosures, BACKFILL_DAYS, 600)
    except Exception as exc:
        print(f"[OwnerRadar] Backfill error: {exc}")
    while True:
        try:
            h = _now_wib().hour
            if 6 <= h <= 23:
                await asyncio.to_thread(sync_owner_disclosures, 2, 200)
        except Exception as exc:
            print(f"[OwnerRadar] Worker error: {exc}")
        await asyncio.sleep(20 * 60)
