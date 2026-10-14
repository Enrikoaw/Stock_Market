"""
SmartFlow IDX - Telegram Notifier Module
Menyaring saham akumulasi terbaik yang belum terbang (perubahan <= 2.5%)
dan mengirimkan rekomendasi lengkap beserta Trading Plan (Entry, TP, SL) ke Telegram Bot pengguna.
"""

from __future__ import annotations

import html
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def send_telegram_message(bot_token: str, chat_id: str, text: str, parse_mode: str = "HTML") -> tuple[bool, str]:
    """Mengirim pesan teks ke Telegram menggunakan Telegram Bot API."""
    clean_token = (bot_token or "").strip()
    clean_chat_id = (chat_id or "").strip()

    if not clean_token:
        return False, "Telegram Bot Token belum diisi. Buat bot via @BotFather di Telegram."
    if not clean_chat_id:
        return False, "Telegram Chat ID belum diisi. Dapatkan Chat ID Anda via @userinfobot di Telegram."

    url = f"https://api.telegram.org/bot{clean_token}/sendMessage"
    payload = {
        "chat_id": clean_chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=12) as response:
            res_body = json.loads(response.read().decode("utf-8"))
            if res_body.get("ok"):
                return True, "Pesan berhasil dikirim ke Telegram!"
            return False, f"Telegram API Error: {res_body.get('description', 'Unknown error')}"
    except urllib.error.HTTPError as exc:
        try:
            err_body = json.loads(exc.read().decode("utf-8"))
            err_desc = err_body.get("description", str(exc))
        except Exception:
            err_desc = str(exc)
        if "chat not found" in err_desc.lower() or "bot was blocked" in err_desc.lower():
            return False, f"Gagal: {err_desc}. Pastikan Anda sudah membuka bot di Telegram dan menekan tombol /start."
        return False, f"Gagal mengirim ke Telegram ({exc.code}): {err_desc}"
    except Exception as exc:
        return False, f"Koneksi ke Telegram gagal: {exc}"


def filter_smart_telegram_picks(
    stocks: list[dict],
    max_picks: int = 3,
    max_pct_change: float = 2.5,
    min_score: int = 70,
    min_value_b_idr: float = 1.0,
) -> list[dict]:
    """
    Menyaring saham-saham pilihan yang paling ideal untuk modal terbatas (misal 10 Juta):
    1. Sinyal Akumulasi Smart Money (Big Accum, Silent Accum, Breakout, Foreign Inflow).
    2. Skor Smart Money tinggi (>= min_score).
    3. Belum terbang tinggi (-1.5% <= perubahan harga <= max_pct_change, default +2.5%).
    4. Likuid (Nilai transaksi harian >= Rp 1.0 Miliar - Filter 6).
    5. Jarak ke modal bandar aman (-1.0% <= diff_bandar_avg_pct <= +3.5%).
    6. Bukan saham penny (< Rp 70) dan bukan Papan Pemantauan Khusus (FCA) / Akselerasi.
    7. Closing Range >= 0.65 (menolak candle jarum/distribusi).
    """
    valid_triggers = {"BIG_ACCUMULATION", "SILENT_ACCUMULATION", "MARKUP_BREAKOUT", "FOREIGN_INFLOW"}
    candidates = []

    for s in stocks:
        trig = s.get("trigger_type")
        if trig not in valid_triggers:
            continue

        close_p = float(s.get("close", 0))
        if close_p < 70:
            continue

        sec = str(s.get("sector", "")).lower()
        if "pemantauan khusus" in sec or "akselerasi" in sec:
            continue

        score = int(s.get("smart_money_score", 0))
        if score < min_score:
            continue

        pct = float(s.get("pct_change", 0))
        if pct > max_pct_change or pct < -1.5:
            continue

        val_b = float(s.get("value_b_idr", 0))
        if val_b < min_value_b_idr:
            continue

        cr = s.get("closing_range") or (float(s.get("closing_range_pct", 70)) / 100.0)
        if cr is not None and float(cr) < 0.65:
            continue

        plan = s.get("trading_plan") or {}
        e_low = plan.get("entry_low") or plan.get("entry_price")
        sl = plan.get("stop_loss")
        tp1 = plan.get("target_1")
        if not (e_low and sl and tp1):
            continue

        diff_bandar = float(plan.get("diff_bandar_avg_pct", s.get("diff_bandar_avg_pct", 0)))
        if diff_bandar > 3.5 or diff_bandar < -1.0:
            continue

        candidates.append(s)

    # Urutkan berdasarkan Smart Money Score tertinggi, lalu volume spike
    candidates.sort(
        key=lambda x: (
            int(x.get("smart_money_score", 0)),
            float(x.get("vol_ratio", 0)),
            float(x.get("top3_bsr", 0)),
        ),
        reverse=True,
    )

    return candidates[:max_picks]


def format_telegram_broadcast(picks: list[dict], market_date: str) -> str:
    """Memformat laporan rekomendasi SmartFlow IDX ke format HTML Telegram yang ringkas, rapi (< 3500 chars)."""
    date_str = market_date or "Hari Ini"

    if not picks:
        return (
            f"🎯 <b>SMARTFLOW IDX — SMART SIGNAL RADAR</b>\n"
            f"📅 <i>Sesi Bursa: {html.escape(date_str)}</i>\n\n"
            f"🛡️ <b>Hasil Saring Risiko Rendah:</b>\n"
            f"Saat ini <b>tidak ditemukan</b> saham akumulasi kuat yang berada di zona aman (kenaikan ≤ 2.5%).\n"
            f"Saham lain di bursa sudah melonjak terlalu tinggi atau belum memenuhi kriteria akumulasi.\n\n"
            f"💡 <b>Saran untuk Modal Terbatas (10 Juta):</b>\n"
            f"Disarankan <b>WAIT & SEE</b>. Jangan pernah FOMO mengejar harga saham yang sudah terbang tinggi demi keamanan modal Anda."
        )

    lines = [
        "🎯 <b>SMARTFLOW IDX — RADAR AKUMULASI & VSA</b>",
        f"📅 <i>Sesi Bursa: {html.escape(date_str)}</i>",
        "💡 <i>Kriteria: 6 Filter Kuantitatif (Turnover ≥ 1M, Akumulasi, Belum Terbang ≤ 2.5%, Jarak VWAP ≤ 5%)</i>",
        f"🔍 Ditemukan <b>{len(picks)} Saham Pilihan</b>:\n",
    ]

    for idx, s in enumerate(picks, start=1):
        ticker = html.escape(str(s.get("ticker", "")))
        sector = html.escape(str(s.get("sector", "IDX Emiten")))
        close = int(s.get("close", 0))
        pct = float(s.get("pct_change", 0))
        pct_sign = "+" if pct >= 0 else ""
        score = int(s.get("smart_money_score", 0))
        trigger_lbl = html.escape(str(s.get("trigger_label", s.get("trigger_type", ""))))
        vol_ratio = float(s.get("vol_ratio", 0))
        cr = int(s.get("closing_range_pct", 50))
        val_b = float(s.get("value_b_idr", 0))

        plan = s.get("trading_plan") or {}
        e_low = int(plan.get("entry_low", close))
        e_high = int(plan.get("entry_high", close))
        sl = int(plan.get("stop_loss", 0))
        sl_pct = float(plan.get("stop_loss_pct", 0))
        tp1 = int(plan.get("target_1", 0))
        tp1_pct = float(plan.get("target_1_pct", 0))
        tp2 = int(plan.get("target_2", tp1))
        tp2_pct = float(plan.get("target_2_pct", 0))
        vwap_5d = int(plan.get("bandar_avg_buy", close))
        diff_vwap = float(plan.get("diff_bandar_avg_pct", 0))

        tp1_win = int(round(plan.get("tp1_win_prob", 75)))
        tp1_loss = int(round(plan.get("tp1_loss_prob", 25)))
        tp2_win = int(round(plan.get("tp2_win_prob", 58)))

        card = (
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{idx}. #{ticker}</b> ({sector})\n"
            f"💰 <b>Harga:</b> Rp {close:,} (<b>{pct_sign}{pct:.2f}%</b>) | <b>VSA Score:</b> {score}/100\n"
            f"⚡ <b>Sinyal:</b> {trigger_lbl} | <b>Closing Range:</b> {cr}%\n"
            f"📊 <b>Vol Spike:</b> {vol_ratio:.1f}x MA20 | <b>Nilai Transaksi:</b> Rp {val_b:.2f}M\n\n"
            f"🎯 <b>TRADING PLAN (Take Profit Cepat):</b>\n"
            f"• <b>Harga Beli:</b> <code>Rp {e_high:,}</code>\n"
            f"• <b>Stop Loss (SL):</b> <code>Rp {sl:,} ({sl_pct:.1f}%)</code>\n"
            f"• <b>Target TP1 (+4%):</b> <code>Rp {tp1:,} (+{tp1_pct:.1f}%)</code> ➜ <b>{tp1_win}% Win / {tp1_loss}% Loss</b>\n"
            f"• <b>Target TP2 (+7%):</b> <code>Rp {tp2:,} (+{tp2_pct:.1f}%)</code> ➜ <b>{tp2_win}% Win</b>\n"
            f"• <b>VWAP 5 Hari:</b> Rp {vwap_5d:,} (Jarak: {diff_vwap:+.1f}%)\n"
        )
        lines.append(card)

    lines.append(
        "━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>Panduan Modal 10 Juta:</b>\n"
        "• Pilih maksimal 2 saham, porsi Rp 3–5 juta per saham.\n"
        "• Pasang Buy Limit di Harga Beli saat koreksi.\n"
        "• Take Profit Cepat: TP1 di +4% (Amankan modal), TP2 di +7% (Realisasi profit penuh).\n"
        "• Wajib pasang Automatic Stop Loss di aplikasi sekuritas."
    )

    result_text = "\n".join(lines)
    # Proteksi batas 4096 karakter Telegram
    if len(result_text) > 4000:
        result_text = result_text[:3980] + "\n\n<i>[Pesan dipersingkat demi batas limit Telegram]</i>"
    return result_text


def format_test_message() -> str:
    """Format pesan uji coba untuk memverifikasi bot telegram bekerja dengan normal."""
    return (
        "🔔 <b>TES KONEKSI SMARTFLOW IDX BERHASIL!</b>\n\n"
        "Bot Telegram Anda telah sukses terhubung dengan sistem SmartFlow IDX.\n"
        "Saat Anda menekan tombol <b>Kirim Sinyal Telegram</b> di web, saham-saham akumulasi terbaik "
        "yang belum terbang akan langsung dikirimkan ke chat ini secara otomatis.\n\n"
        "<i>Selamat trading & disiplin selalu dengan Trading Plan!</i>"
    )
