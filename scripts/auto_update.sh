#!/bin/bash
# ==============================================================================
# SmartFlow IDX - Auto Update Script (Runs via Cron every 5 minutes)
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(dirname "$SCRIPT_DIR")"

cd "$APP_DIR" || exit 1

# Fetch changes from remote
git fetch origin main > /dev/null 2>&1

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

# Check if there are new commits
if [ "$LOCAL" != "$REMOTE" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🚀 Mendeteksi commit baru di GitHub ($REMOTE). Memperbarui aplikasi..."
    
    # Check if requirements.txt changed
    REQ_CHANGED=$(git diff --name-only "$LOCAL" "$REMOTE" | grep "requirements.txt" || true)
    
    # Pull latest code
    git pull origin main
    
    # If requirements changed, install new packages
    if [ -n "$REQ_CHANGED" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 📦 Memperbarui dependensi Python..."
        "$APP_DIR/venv/bin/pip" install -r requirements.txt
    fi
    
    # Restart the smartflow service
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🔄 Me-restart service smartflow..."
    sudo systemctl restart smartflow
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Pembaruan selesai! SmartFlow IDX berjalan di versi terbaru."
fi
