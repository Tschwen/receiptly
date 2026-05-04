#!/bin/sh
# ─────────────────────────────────────────────────────────────────────────────
# Receiptly Setup · Alpine LXC
# Run as root inside a fresh Alpine container
# ─────────────────────────────────────────────────────────────────────────────
set -e

echo "→ Updating system..."
apk update && apk upgrade

echo "→ Installing packages..."
apk add python3 py3-pip nginx curl

echo "→ Installing Python dependencies..."
pip3 install fastapi uvicorn reportlab python-multipart --break-system-packages

echo "→ Creating directories..."
mkdir -p /app/static
mkdir -p /data
mkdir -p /var/log/nginx
mkdir -p /run/nginx

echo "→ Configuring nginx as reverse proxy..."
cat > /etc/nginx/http.d/receiptly.conf << 'EOF'
server {
    listen 80;
    server_name _;

    add_header X-Frame-Options "SAMEORIGIN";
    add_header X-Content-Type-Options "nosniff";

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        client_max_body_size 10M;
    }

    access_log /var/log/nginx/receiptly.log;
    error_log  /var/log/nginx/receiptly_error.log;
}
EOF

rm -f /etc/nginx/http.d/default.conf

echo "→ Registering FastAPI as an OpenRC service..."
cat > /etc/init.d/receiptly << 'EOF'
#!/sbin/openrc-run

name="receiptly"
description="Receiptly FastAPI server"
command="/usr/bin/python3"
command_args="-m uvicorn app.main:app --host 127.0.0.1 --port 8000"
directory="/app"
pidfile="/run/receiptly.pid"
command_background=true
output_log="/var/log/receiptly.log"
error_log="/var/log/receiptly_error.log"

depend() {
    need net
    after nginx
}
EOF

chmod +x /etc/init.d/receiptly

echo "→ Enabling services at boot..."
rc-update add nginx default
rc-update add receiptly default

echo ""
echo "✓ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Upload files:"
echo "     scp -r app    root@<IP>:/app/"
echo "     scp -r static root@<IP>:/app/"
echo ""
echo "  2. Start services:"
echo "     rc-service nginx start"
echo "     rc-service receiptly start"
echo ""
echo "  3. Test:"
echo "     curl http://localhost/api/receipts"
echo ""
echo "  Admin: http://<IP>/admin.html"
