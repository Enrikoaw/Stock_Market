#!/bin/bash
# ==============================================================================
# SmartFlow IDX - Mengaktifkan Auto-Update Otomatis (Mirip Render CD)
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"
CURRENT_USER=$(whoami)

echo "⚙️ [1/3] Menyiapkan izin restart systemctl tanpa password..."
SUDOERS_FILE="/etc/sudoers.d/smartflow_restart"
echo "$CURRENT_USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart smartflow, /bin/systemctl restart smartflow" | sudo tee "$SUDOERS_FILE" > /dev/null
sudo chmod 0440 "$SUDOERS_FILE"

echo "🔧 [2/3] Memberikan izin eksekusi pada script auto-update..."
chmod +x "$APP_DIR/scripts/auto_update.sh"

echo "⏰ [3/3] Mendaftarkan cron job (cek GitHub setiap 5 menit)..."
CRON_JOB="*/5 * * * * $APP_DIR/scripts/auto_update.sh >> $APP_DIR/auto_update.log 2>&1"

# Check if cron job already exists
(crontab -l 2>/dev/null | grep -v "auto_update.sh" ; echo "$CRON_JOB") | crontab -

echo ""
echo "=============================================================================="
echo "🎉 AUTO-UPDATE SEPERTI RENDER BERHASIL DIAKTIFKAN!"
echo "Server akan mengecek GitHub setiap 5 menit."
echo "Setiap kali ada fitur/kode baru yang di-push, server otomatis git pull"
echo "dan me-restart aplikasi tanpa Anda perlu membuka terminal lagi!"
echo ""
echo "Log pembaruan dapat dilihat kapan saja dengan:"
echo "  tail -f $APP_DIR/auto_update.log"
echo "=============================================================================="
