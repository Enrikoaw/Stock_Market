#!/bin/bash
# ==============================================================================
# SmartFlow IDX - Automated VPS Setup Script (Ubuntu 22.04 / 24.04 LTS)
# Menyiapkan Python, dependensi, Nginx Reverse Proxy, dan Systemd Service 24/7
# ==============================================================================

set -e

echo "🚀 [1/6] Memperbarui sistem Ubuntu & menginstal paket esensial..."
sudo apt update -y
sudo apt install -y python3 python3-pip python3-venv git curl ufw nginx

REPO_DIR=$(pwd)
echo "📁 Direktori aplikasi: $REPO_DIR"

echo "🐍 [2/6] Menyiapkan Virtual Environment Python & menginstal dependensi..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "⚙️ [3/6] Mengonfigurasi Nginx Reverse Proxy (Port 80 -> Port 8000)..."
sudo tee /etc/nginx/sites-available/smartflow > /dev/null <<EOF
server {
    listen 80;
    server_name _;

    client_max_body_size 64M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 180s;
        proxy_connect_timeout 60s;
    }
}
EOF

sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/smartflow /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx

echo "🛡️ [4/6] Mengonfigurasi Firewall (UFW: Port 22, 80, 443)..."
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
echo "y" | sudo ufw enable || true

echo "🔄 [5/6] Mendaftarkan Systemd Service 24/7 (Auto-Restart jika server reboot)..."
sudo tee /etc/systemd/system/smartflow.service > /dev/null <<EOF
[Unit]
Description=SmartFlow IDX FastAPI Screener Service
After=network.target

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$REPO_DIR
ExecStart=$REPO_DIR/venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable smartflow
sudo systemctl restart smartflow

echo "✅ [6/6] Memeriksa status service..."
sleep 2
sudo systemctl is-active --quiet smartflow && echo "-> Service smartflow aktif & berjalan lancar!" || echo "-> Perhatian: Periksa log dengan: sudo journalctl -u smartflow -f"

IP_ADDR=$(curl -s https://api.ipify.org || echo "IP_VPS_ANDA")

echo ""
echo "=============================================================================="
echo "🎉 DEPLOYMENT SMARTFLOW IDX SELESAI!"
echo "Aplikasi Anda sekarang berjalan 24/7 di: http://$IP_ADDR"
echo "=============================================================================="
echo "Perintah berguna:"
echo "  - Cek log live   : sudo journalctl -u smartflow -f"
echo "  - Restart service: sudo systemctl restart smartflow"
echo "  - Update kode    : git pull && sudo systemctl restart smartflow"
echo "=============================================================================="
