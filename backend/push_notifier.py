"""
SmartFlow IDX - Push Notifier ke HP (Telegram Bot dan/atau ntfy.sh)
Mengirim alert HANYA untuk berita POSITIF yang terkait emiten (bukan berita IHSG/makro).
Berjalan di server (tidak butuh browser terbuka), sehingga notifikasi sampai ke HP.
Kanal utama: Web Push (PWA) -> muncul di bar notifikasi HP, tanpa aplikasi tambahan.

Konfigurasi opsional lewat .env (kanal tambahan):
    TELEGRAM_BOT_TOKEN=...   TELEGRAM_CHAT_ID=...
    NTFY_TOPIC=...           (opsional, aplikasi ntfy di HP)
    NEWS_ALERT_ENABLED=true
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

try:
    from backend.broker_summary_fetcher import load_env_file
except ImportError:
    from broker_summary_fetcher import load_env_file

SENT_PATH = Path(__file__).resolve().parent.parent / "data" / "news_alert_sent.json"
MAX_AGE_SECONDS = 12 * 3600  # hanya berita <= 12 jam terakhir
MAX_PER_CYCLE = 5


def get_push_config() -> dict[str, Any]:
    load_env_file()
    return {
        "enabled": os.environ.get("NEWS_ALERT_ENABLED", "true").strip().lower() not in ("false", "0", "no"),
        "tg_token": os.environ.get("TELEGRAM_BOT_TOKEN", "").strip(),
        "tg_chat": os.environ.get("TELEGRAM_CHAT_ID", "").strip(),
        "ntfy_topic": os.environ.get("NTFY_TOPIC", "").strip(),
        "ntfy_server": os.environ.get("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/"),
    }


def is_push_configured(cfg: dict[str, Any] | None = None) -> bool:
    c = cfg or get_push_config()
    return bool((c["tg_token"] and c["tg_chat"]) or c["ntfy_topic"] or has_web_push_subscribers())


def _send_telegram(cfg: dict, text: str) -> bool:
    url = f"https://api.telegram.org/bot{cfg['tg_token']}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": cfg["tg_chat"],
        "text": text,
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10) as r:
            return r.status == 200
    except Exception as ex:
        print(f"[PushNotifier] Telegram gagal: {ex}")
        return False


def _send_ntfy(cfg: dict, title: str, text: str, link: str = "") -> bool:
    url = f"{cfg['ntfy_server']}/{urllib.parse.quote(cfg['ntfy_topic'])}"
    headers = {"Title": title.encode("utf-8").decode("latin-1", "ignore") or "SmartFlow", "Tags": "chart_with_upwards_trend"}
    if link:
        headers["Click"] = link
    try:
        req = urllib.request.Request(url, data=text.encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status == 200
    except Exception as ex:
        print(f"[PushNotifier] ntfy gagal: {ex}")
        return False


def send_push(title: str, text: str, link: str = "", cfg: dict[str, Any] | None = None) -> bool:
    """Kirim ke semua kanal yang terkonfigurasi. True jika minimal satu berhasil."""
    c = cfg or get_push_config()
    ok = send_web_push(title, text, link) > 0
    if c["tg_token"] and c["tg_chat"]:
        ok = _send_telegram(c, f"{title}\n{text}" + (f"\n{link}" if link else "")) or ok
    if c["ntfy_topic"]:
        ok = _send_ntfy(c, title, text, link) or ok
    return ok


def _load_sent() -> dict[str, Any]:
    if SENT_PATH.exists():
        try:
            with open(SENT_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, dict) and isinstance(d.get("sent"), dict):
                    return d
        except Exception:
            pass
    return {"initialized": False, "sent": {}}


def _save_sent(state: dict[str, Any]) -> None:
    try:
        SENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SENT_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f)
    except Exception as ex:
        print(f"[PushNotifier] Gagal simpan state: {ex}")


def is_positive_emiten_news(item: dict[str, Any]) -> bool:
    """Berita positif yang terkait emiten spesifik (ticker bukan IHSG/makro)."""
    ticker = str(item.get("ticker") or "").upper()
    return item.get("sentiment") == "POSITIVE" and bool(ticker) and ticker != "IHSG"


def process_positive_news_alerts(news_items: list[dict[str, Any]]) -> int:
    """Kirim push untuk berita positif emiten baru. Mengembalikan jumlah terkirim.
    Eksekusi pertama hanya menandai berita yang ada (tanpa kirim) agar HP tidak kebanjiran."""
    cfg = get_push_config()
    if not cfg["enabled"] or not is_push_configured(cfg):
        return 0

    state = _load_sent()
    sent: dict[str, float] = state["sent"]
    now = time.time()
    candidates = [n for n in news_items if is_positive_emiten_news(n)]

    if not state.get("initialized"):
        # Tandai berita yang sudah tua (> 12 jam) agar tidak membanjiri, tetapi biarkan berita hari ini terkirim
        for n in candidates:
            pub_ts = float(n.get("published_ts") or 0)
            if now - pub_ts > 12 * 3600:
                sent[n["title"].lower()] = now
        state["initialized"] = True
        _save_sent(state)
        print(f"[PushNotifier] Inisialisasi: Berita positif emiten siap dipantau untuk bar HP.")

    fresh = [
        n for n in candidates
        if n["title"].lower() not in sent
        and (now - float(n.get("published_ts") or now)) <= MAX_AGE_SECONDS
    ]
    fresh.sort(key=lambda x: x.get("published_ts", 0), reverse=True)

    count = 0
    for n in fresh[:MAX_PER_CYCLE]:
        corr = n.get("correlation") or {}
        lines = [n["title"]]
        if corr.get("close"):
            pct = corr.get("pct_change")
            lines.append(f"Harga: Rp {corr['close']:,.0f}" + (f" ({pct:+.2f}%)" if pct is not None else ""))
        if corr.get("action_eval"):
            lines.append(corr["action_eval"])
        lines.append(f"Sumber: {n.get('source', '-')} | {n.get('relative_time', '')}")
        title = f"📈 Katalis Positif: #{n['ticker']}"
        body_text = "\n".join(lines)
        target_link = f"/?ticker={n['ticker']}"
        if send_push(title, body_text, target_link, cfg):
            sent[n["title"].lower()] = now
            count += 1

    # Tandai sisanya (di luar batas per siklus) sebagai terkirim agar tidak menumpuk
    for n in fresh[MAX_PER_CYCLE:]:
        sent[n["title"].lower()] = now

    # Bersihkan entri lama (> 3 hari)
    state["sent"] = {k: v for k, v in sent.items() if now - v < 3 * 86400}
    _save_sent(state)
    if count:
        print(f"[PushNotifier] {count} alert berita positif emiten terkirim ke HP.")
    return count


# ===================== WEB PUSH (notifikasi bar HP via PWA) =====================
VAPID_PATH = Path(__file__).resolve().parent.parent / "data" / "vapid_keys.json"
SUBS_PATH = Path(__file__).resolve().parent.parent / "data" / "push_subscriptions.json"


def _b64u(b: bytes) -> str:
    import base64
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def get_vapid_keys() -> dict[str, str]:
    """Ambil VAPID key dari env (disarankan untuk Render) atau file; buat otomatis jika belum ada."""
    load_env_file()
    pub = os.environ.get("VAPID_PUBLIC_KEY", "").strip()
    priv = os.environ.get("VAPID_PRIVATE_KEY", "").strip()
    if pub and priv:
        return {"public": pub, "private": priv}
    if VAPID_PATH.exists():
        try:
            with open(VAPID_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                if d.get("public") and d.get("private"):
                    return d
        except Exception:
            pass
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    key = ec.generate_private_key(ec.SECP256R1())
    raw_priv = key.private_numbers().private_value.to_bytes(32, "big")
    raw_pub = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    d = {"public": _b64u(raw_pub), "private": _b64u(raw_priv)}
    try:
        VAPID_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(VAPID_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception as ex:
        print(f"[WebPush] Gagal simpan VAPID key: {ex}")
    return d


def _load_subs() -> list[dict[str, Any]]:
    if SUBS_PATH.exists():
        try:
            with open(SUBS_PATH, "r", encoding="utf-8") as f:
                d = json.load(f)
                if isinstance(d, list):
                    return d
        except Exception:
            pass
    return []


def _save_subs(subs: list[dict[str, Any]]) -> None:
    try:
        SUBS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SUBS_PATH, "w", encoding="utf-8") as f:
            json.dump(subs, f)
    except Exception as ex:
        print(f"[WebPush] Gagal simpan subscription: {ex}")


def add_subscription(sub: dict[str, Any]) -> int:
    if not sub.get("endpoint") or not (sub.get("keys") or {}).get("p256dh"):
        raise ValueError("Subscription tidak valid")
    subs = [s for s in _load_subs() if s.get("endpoint") != sub["endpoint"]]
    subs.append(sub)
    _save_subs(subs)
    return len(subs)


def remove_subscription(endpoint: str) -> None:
    _save_subs([s for s in _load_subs() if s.get("endpoint") != endpoint])


def has_web_push_subscribers() -> bool:
    return bool(_load_subs())


def send_web_push(title: str, body: str, link: str = "") -> int:
    """Kirim ke semua perangkat terdaftar (muncul di bar notifikasi HP). Return jumlah sukses."""
    subs = _load_subs()
    if not subs:
        return 0
    try:
        from pywebpush import webpush, WebPushException
    except ImportError:
        print("[WebPush] pywebpush belum terpasang (pip install pywebpush).")
        return 0
    keys = get_vapid_keys()
    payload = json.dumps({"title": title, "body": body, "url": link or "/"})
    sent, alive = 0, []
    for s in subs:
        try:
            webpush(
                subscription_info=s,
                data=payload,
                vapid_private_key=keys["private"],
                vapid_claims={"sub": os.environ.get("VAPID_SUBJECT", "mailto:admin@smartflow-idx.local")},
                ttl=6 * 3600,
            )
            sent += 1
            alive.append(s)
        except WebPushException as ex:
            code = getattr(getattr(ex, "response", None), "status_code", None)
            if code in (404, 410):
                print("[WebPush] Subscription kedaluwarsa, dihapus.")
                continue
            print(f"[WebPush] Gagal kirim: {ex}")
            alive.append(s)
        except Exception as ex:
            print(f"[WebPush] Error: {ex}")
            alive.append(s)
    if len(alive) != len(subs):
        _save_subs(alive)
    return sent
