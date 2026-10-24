#!/bin/bash
# ==============================================================================
# SmartFlow IDX - Quick VPS Update Script
# Memperbarui kode dari GitHub, mengamankan cache lokal, & restart service
# ==============================================================================

set -e

echo "🔄 [1/4] Mengamankan file data/cache lokal agar tidak bentrok..."
git stash || true

echo "📥 [2/4] Menarik kode pembaruan terbaru dari GitHub (origin/main)..."
git pull origin main

echo "🐍 [3/4] Memeriksa dan memperbarui dependensi Python..."
if [ -d "venv" ]; then
    source venv/bin/activate
    pip install -r requirements.txt --quiet
fi

echo "🚀 [4/4] Me-restart service background SmartFlow IDX..."
sudo systemctl daemon-reload
sudo systemctl restart smartflow 2>/dev/null || true
sudo systemctl restart radarbandar 2>/dev/null || true

echo ""
echo "=============================================================================="
echo "🎉 PEMBARUAN SELESAI! SMARTFLOW IDX BERHASIL DIPERBARUI."
echo "=============================================================================="
(sudo systemctl is-active --quiet smartflow || sudo systemctl is-active --quiet radarbandar) && echo "✅ Service aktif & berjalan normal!" || echo "⚠️ Perhatian: Cek log dengan: sudo journalctl -u smartflow -f"
echo ""
echo "💡 Buka browser Anda dan tekan Ctrl + F5 (Hard Refresh) untuk memuat UI v98.7."
echo "=============================================================================="
