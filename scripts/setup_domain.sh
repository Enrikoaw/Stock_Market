#!/bin/bash
# ==============================================================================
# SmartFlow IDX - Setup Custom Domain & Free SSL HTTPS (Let's Encrypt)
# Penggunaan: bash scripts/setup_domain.sh namadomain.com
# ==============================================================================

set -e

DOMAIN=$1

if [ -z "$DOMAIN" ]; then
    echo "⚠️ Mohon sertakan nama domain Anda."
    echo "Contoh penggunaan: bash scripts/setup_domain.sh saham-analisa.com"
    exit 1
fi

echo "🚀 [1/3] Mengonfigurasi Nginx untuk domain: $DOMAIN..."
sudo tee /etc/nginx/sites-available/smartflow > /dev/null <<EOF
server {
    listen 80;
    server_name $DOMAIN;

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

sudo nginx -t
sudo systemctl restart nginx

echo "🔒 [2/3] Menginstal Certbot untuk SSL HTTPS Gratis (Let's Encrypt)..."
sudo apt update -y
sudo apt install -y certbot python3-certbot-nginx

echo "📜 [3/3] Menerbitkan sertifikat SSL HTTPS untuk $DOMAIN..."
sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email || sudo certbot --nginx -d "$DOMAIN"

echo ""
echo "=============================================================================="
echo "🎉 DOMAIN & HTTPS BERHASIL DIAKTIFKAN!"
echo "Aplikasi Anda sekarang dapat diakses secara aman di: https://$DOMAIN"
echo "=============================================================================="
