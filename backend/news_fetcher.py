"""
Modul Fetcher & Parser Berita Pasar Saham BEI / IDX
Mengambil berita emiten terkini secara real-time dari sumber finansial terpercaya,
mendeteksi kode ticker saham Indonesia (IDX), menganalisis sentimen fundamental/katalis,
dan menyelaraskannya dengan data teknikal 5-Pilar Smart Money & Trading Plan.
"""

from __future__ import annotations

import email.utils
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import Any, Optional


NEWS_CACHE: dict[str, Any] = {
    "timestamp": 0.0,
    "items": [],
}
CACHE_TTL_SECONDS = 600.0  # 10 menit


POSITIVE_KEYWORDS = [
    "laba", "naik", "tumbuh", "dividen", "melonjak", "menguat", "rekor", "akuisisi",
    "ekspansi", "net buy", "akumulasi", "kinerja positif", "surplus", "buyback",
    "prospek cerah", "target harga", "bullish", "lonjakan", "kontrak baru", "rebound",
    "kapitalisasi", "penjualan naik", "optimistis", "pendapatan naik", "dividen interim"
]

NEGATIVE_KEYWORDS = [
    "rugi", "turun", "anjlok", "melemah", "suspensi", "pailit", "gagal bayar", "utang",
    "penurunan", "tekanan", "merosot", "npl", "penjualan sepi", "peringatan", "bearish",
    "hsc", "fca", "gugatan", "defisit", "denda", "penyelidikan", "disclaimer", "delisting"
]


def _clean_text(raw: str) -> str:
    """Membersihkan emoji dan karakter aneh agar teks tampil profesional dan bersih."""
    if not raw:
        return ""
    # Hapus karakter emoji (rentang surrogate dan plane 1+)
    cleaned = re.sub(r"[\U00010000-\U0010ffff]", "", raw)
    # Hapus tag HTML jika ada
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # Normalkan spasi
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _parse_pub_date(raw_date: str) -> tuple[str, str, float]:
    """Mengonversi string pubDate RSS menjadi format tanggal lokal (WIB), waktu relatif, dan epoch timestamp."""
    wib_tz = timezone(timedelta(hours=7))
    if not raw_date:
        now_wib = datetime.now(wib_tz)
        return now_wib.strftime("%Y-%m-%d %H:%M"), "Baru saja", now_wib.timestamp()

    dt = None
    # 1. Coba parser RFC 2822 standar untuk RSS (paling presisi untuk pubDate)
    try:
        dt = email.utils.parsedate_to_datetime(raw_date.strip())
    except Exception:
        pass

    # 2. Coba ISO format
    if dt is None:
        try:
            clean_s = raw_date.strip().replace("Z", "+00:00")
            dt = datetime.fromisoformat(clean_s)
        except Exception:
            pass

    # 3. Fallback format manual
    if dt is None:
        formats = [
            "%a, %d %b %Y %H:%M:%S %Z",
            "%a, %d %b %Y %H:%M:%S %z",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(raw_date.strip(), fmt)
                break
            except Exception:
                pass

    if dt is None:
        now_wib = datetime.now(wib_tz)
        return now_wib.strftime("%Y-%m-%d %H:%M"), "Hari ini", now_wib.timestamp()

    # Jika timezone-naive, asumsikan UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    # Konversi ke WIB (UTC+7)
    dt_wib = dt.astimezone(wib_tz)
    ts = dt_wib.timestamp()
    formatted_date = dt_wib.strftime("%Y-%m-%d %H:%M")

    # Hitung waktu relatif
    now_wib = datetime.now(wib_tz)
    diff = (now_wib - dt_wib).total_seconds()

    if diff <= 90:
        rel = "Baru saja"
    elif diff < 3600:
        mins = max(1, int(diff / 60))
        rel = f"{mins} menit lalu"
    elif diff < 86400:
        hours = max(1, int(diff / 3600))
        rel = f"{hours} jam lalu"
    else:
        days = max(1, int(diff / 86400))
        rel = f"{days} hari lalu"

    return formatted_date, rel, ts


def _analyze_sentiment(text: str) -> tuple[str, str]:
    """Menganalisis sentimen judul/ringkasan berita menggunakan pencocokan kata kunci terbobot."""
    lower = text.lower()
    pos_score = sum(1 for kw in POSITIVE_KEYWORDS if kw in lower)
    neg_score = sum(1 for kw in NEGATIVE_KEYWORDS if kw in lower)

    if pos_score > neg_score:
        return "POSITIVE", "Katalis Positif"
    if neg_score > pos_score:
        return "NEGATIVE", "Sentimen Negatif"
    return "NEUTRAL", "Informasi Pasar"


def _extract_tickers(title: str, summary: str, known_tickers: set[str]) -> list[str]:
    """Mendeteksi kode ticker saham Indonesia (4 huruf kapital) dari teks berita."""
    content = f"{title} {summary}"
    # Cari pola saham 4 huruf kapital
    potential = re.findall(r"\b([A-Z]{4})\b", content)
    matched = []
    # Kata umum 4 huruf yang sering muncul tapi bukan ticker saham
    excluded_words = {
        "IHSG", "KSEI", "OJKK", "BURS", "BANK", "NEWS", "CORP", "POST", "INFO",
        "KOTA", "DANA", "ASIA", "MSCI", "LQ45", "IDX3", "YOYO", "EMIT", "RUPS", "APBN"
    }

    for p in potential:
        if p in excluded_words:
            continue
        if known_tickers and p in known_tickers:
            if p not in matched:
                matched.append(p)
        elif not known_tickers and p.isalpha() and p.isupper():
            if p not in matched:
                matched.append(p)

    return matched


def _fetch_rss_feed(url: str, default_source: str = "", timeout: int = 5) -> list[dict[str, Any]]:
    """Tarik dan parse dokumen RSS XML."""
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    raw_items = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        content = resp.read()
        root = ET.fromstring(content)

        ch_title = _clean_text(root.findtext(".//channel/title") or "")
        feed_source = default_source
        if not feed_source:
            lower_ch = ch_title.lower()
            if "kontan" in lower_ch:
                feed_source = "Kontan"
            elif "cnbc" in lower_ch:
                feed_source = "CNBC Indonesia"
            elif "bisnis" in lower_ch:
                feed_source = "Bisnis.com"
            else:
                feed_source = "IDX Market News"

        for item_node in root.findall(".//item"):
            title = _clean_text(item_node.findtext("title") or "")
            link = (item_node.findtext("link") or "").strip()
            pub_date = (item_node.findtext("pubDate") or "").strip()
            desc = _clean_text(item_node.findtext("description") or "")
            source = _clean_text(item_node.findtext("source") or "")

            # Jika judul memiliki akhiran sumber seperti 'Judul Berita - Bisnis.com'
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title = parts[0].strip()
                if not source:
                    source = parts[1].strip()

            if not source:
                source = feed_source

            raw_items.append({
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "description": desc,
                "source": source,
            })
    return raw_items



ACCUM_TRIGGERS = ("MARKUP_BREAKOUT", "BIG_ACCUMULATION", "SILENT_ACCUMULATION", "FOREIGN_INFLOW")


def validate_catalyst(sentiment: str, stock: dict[str, Any]) -> dict[str, Any]:
    """
    Event-Driven Re-Analysis: matriks validasi silang Sentimen Berita x Respons Smart Money
    (Volume VSA + Turnover riil + Closing Range + Akumulasi Broker).
    Membedakan Valid Catalyst Breakout dari jebakan Sell on News.
    """
    base = int(stock.get("smart_money_score") or 0)
    vr = float(stock.get("vol_ratio") or 0)
    val_b = float(stock.get("value_b_idr") or 0)
    cr = float(stock.get("closing_range_pct") or 0)
    pct = float(stock.get("pct_change") or 0)
    bdr = float(stock.get("bdr_pct") or 0)
    accum = stock.get("trigger_type") in ACCUM_TRIGGERS or bdr >= 5.0

    vol_spike = vr >= 1.5
    turnover_ok = val_b >= 1.0
    close_strong = cr >= 65
    close_weak = cr < 50

    factors = [
        {"label": f"Volume {vr:.1f}x MA20 (VSA)", "ok": vol_spike},
        {"label": f"Turnover Rp {val_b:.1f} M", "ok": turnover_ok},
        {"label": f"Closing Range {cr:.0f}%", "ok": close_strong},
        {"label": "Akumulasi Smart Money", "ok": accum},
    ]

    if sentiment == "POSITIVE":
        if vol_spike and turnover_ok and close_strong and accum:
            code, label, delta = "VALID_CATALYST", "Valid Catalyst Breakout", 8
            note = "Berita positif dikonfirmasi lonjakan volume, turnover riil, penutupan kuat, dan akumulasi broker."
        elif pct >= 4.0 and (close_weak or not accum):
            code, label, delta = "SELL_ON_NEWS", "Waspada Sell on News", -15
            note = "Harga sudah naik tajam namun penutupan lemah / tanpa akumulasi: indikasi distribusi saat berita keluar."
        elif not vol_spike or not turnover_ok:
            code, label, delta = "UNCONFIRMED", "Katalis Belum Terkonfirmasi", -3
            note = "Smart Money belum merespons (volume / turnover rendah). Tunggu konfirmasi sebelum antre."
        else:
            code, label, delta = "WAIT_CONFIRM", "Pantau Konfirmasi Penutupan", 0
            note = "Respons volume ada, namun penutupan atau akumulasi belum meyakinkan."
    elif sentiment == "NEGATIVE":
        if vol_spike and close_weak:
            code, label, delta = "NEGATIVE_CONFIRMED", "Tekanan Jual Terkonfirmasi", -12
            note = "Berita negatif disertai volume tinggi dan penutupan lemah. Hindari entry baru."
        elif vol_spike and close_strong and accum:
            code, label, delta = "ABSORBED", "Berita Negatif Diserap Smart Money", 3
            note = "Volume tinggi namun harga bertahan kuat dan diakumulasi: tekanan jual diserap."
        else:
            code, label, delta = "NEGATIVE_UNCONFIRMED", "Sentimen Negatif Belum Terkonfirmasi", -4
            note = "Belum ada respons volume yang menegaskan tekanan jual. Disiplin pada Stop Loss."
    else:
        code, label, delta = "NEUTRAL", "Tanpa Katalis Dominan", 0
        note = "Sentimen netral: keputusan bertumpu pada 5 Pilar kuantitatif."

    return {
        "code": code,
        "label": label,
        "note": note,
        "base_score": base,
        "adjusted_score": max(0, min(100, base + delta)),
        "delta": delta,
        "factors": factors,
        "is_valid": code in ("VALID_CATALYST", "ABSORBED"),
    }


def get_market_news(
    known_tickers: Optional[set[str]] = None,
    analysis_stocks: Optional[list[dict[str, Any]]] = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """
    Mengembalikan daftar berita pasar saham terkini yang sudah diperkaya dengan
    korelasi sinyal Smart Money dan Trading Plan.
    """
    now = time.time()
    if not force_refresh and NEWS_CACHE["items"] and (now - NEWS_CACHE["timestamp"] < CACHE_TTL_SECONDS):
        return NEWS_CACHE["items"]

    urls = [
        "https://investasi.kontan.co.id/rss",
        "https://www.cnbcindonesia.com/market/rss",
        "https://news.google.com/rss/search?q=saham+IHSG+BEI+OR+emiten+when:2d&hl=id&gl=ID&ceid=ID:id",
    ]

    raw_news = []
    for u in urls:
        try:
            feed_items = _fetch_rss_feed(u, timeout=5)
            raw_news.extend(feed_items[:30])
        except Exception as ex:
            print(f"[NewsFetcher] Gagal menarik RSS dari {u}: {ex}")

    if not raw_news and NEWS_CACHE["items"]:
        return NEWS_CACHE["items"]

    # Buat lookup saham analisa untuk penyesuaian sinyal cepat
    stocks_lookup = {}
    if analysis_stocks:
        for s in analysis_stocks:
            t = str(s.get("ticker", "")).upper().strip()
            if t:
                stocks_lookup[t] = s

    enriched_news = []
    seen_titles = set()

    for idx, item in enumerate(raw_news):
        title = item["title"]
        if not title or title.lower() in seen_titles:
            continue
        seen_titles.add(title.lower())

        dt_formatted, rel_time, pub_ts = _parse_pub_date(item["pub_date"])
        sentiment, sentiment_label = _analyze_sentiment(f"{title} {item['description']}")
        detected_tickers = _extract_tickers(title, item["description"], known_tickers or set())

        primary_ticker = detected_tickers[0] if detected_tickers else "IHSG"
        correlated_stock = stocks_lookup.get(primary_ticker)

        # Analisis korelasi sentimen berita dengan sinyal teknikal
        correlation_info = None
        if correlated_stock:
            score = correlated_stock.get("smart_money_score", 0)
            trigger_lbl = correlated_stock.get("trigger_label", "Neutral Flow")
            plan = correlated_stock.get("trading_plan", {})
            entry_p = plan.get("entry_price") or plan.get("entry_high") or correlated_stock.get("close", 0)
            sl_p = plan.get("stop_loss", 0)
            tp1_p = plan.get("target_1", 0)

            if sentiment == "POSITIVE":
                action_eval = f"Katalis fundamental sejalan dengan akumulasi Smart Money (Skor {score}). Area antre beli objektif: Rp {entry_p:,.0f}."
            elif sentiment == "NEGATIVE":
                action_eval = f"Perhatian: Terdapat sentimen negatif. Pastikan batas rugi (SL) Rp {sl_p:,.0f} terpasang ketat jika mengambil posisi."
            else:
                action_eval = f"Sentimen netral. Ikuti disiplin rencana trading: Beli Rp {entry_p:,.0f}, SL Rp {sl_p:,.0f}, TP1 Rp {tp1_p:,.0f}."

            catalyst = validate_catalyst(sentiment, correlated_stock)
            if catalyst["code"] == "VALID_CATALYST":
                action_eval = f"{catalyst['label']}: {catalyst['note']} Antre beli objektif di support Rp {entry_p:,.0f}."
            elif catalyst["code"] in ("SELL_ON_NEWS", "NEGATIVE_CONFIRMED"):
                action_eval = f"{catalyst['label']}: {catalyst['note']} Jika sudah hold, jaga SL Rp {sl_p:,.0f}."
            correlation_info = {
                "catalyst": catalyst,
                "adjusted_score": catalyst["adjusted_score"],
                "ticker": primary_ticker,
                "score": score,
                "trigger_label": trigger_lbl,
                "close": correlated_stock.get("close", 0),
                "pct_change": correlated_stock.get("pct_change", 0.0),
                "entry_price": entry_p,
                "stop_loss": sl_p,
                "target_1": tp1_p,
                "action_eval": action_eval,
            }
        else:
            if primary_ticker == "IHSG":
                action_eval = "Sentimen pergerakan indeks bursa secara makro. Pantau dampaknya pada saham berkapitalisasi besar."
            else:
                action_eval = f"Berita terkait #{primary_ticker}. Buka tab Jelajah untuk memeriksa struktur teknikal dan broker summary."

            correlation_info = {
                "ticker": primary_ticker,
                "score": None,
                "trigger_label": "Informasi Pasar",
                "close": None,
                "pct_change": None,
                "entry_price": None,
                "stop_loss": None,
                "target_1": None,
                "action_eval": action_eval,
            }

        enriched_news.append({
            "id": f"news_{idx}_{int(pub_ts)}",
            "title": title,
            "link": item["link"],
            "source": item["source"],
            "published_at": dt_formatted,
            "published_ts": pub_ts,
            "relative_time": rel_time,
            "ticker": primary_ticker,
            "other_tickers": detected_tickers[1:],
            "sentiment": sentiment,
            "sentiment_label": sentiment_label,
            "summary": item["description"][:160] + "..." if len(item["description"]) > 160 else item["description"],
            "is_pick": bool(correlated_stock),
            "catalyst_code": (correlation_info.get("catalyst") or {}).get("code"),
            "correlation": correlation_info,
        })

    # Urutkan secara absolut dari yang paling baru (published_ts terbesar / terbaru di atas)
    enriched_news.sort(key=lambda x: x.get("published_ts", 0), reverse=True)

    NEWS_CACHE["timestamp"] = now
    NEWS_CACHE["items"] = enriched_news
    return enriched_news
