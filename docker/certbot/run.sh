#!/bin/sh
# Chứng chỉ HTTPS cho Nginx (backend_design 17.1).
# 1. Chưa có chứng chỉ: tạo chứng chỉ tự ký tạm để Nginx khởi động được. Demo LAN (DOMAIN trống) dùng luôn bản này.
# 2. Có DOMAIN: xin chứng chỉ Let's Encrypt qua webroot, sau đó gia hạn mỗi 12 giờ.
#    Mỗi lần cấp/gia hạn thành công, deploy hook chép chứng chỉ sang /certs; Nginx tự nạp lại khi file đổi.

trap 'exit 0' TERM

if [ ! -f /certs/fullchain.pem ]; then
  openssl req -x509 -nodes -newkey rsa:2048 -days 3650 -subj "/CN=${DOMAIN:-aqi.local}" \
    -keyout /certs/privkey.pem -out /certs/fullchain.pem
fi

if [ -z "$DOMAIN" ]; then
  echo "DOMAIN trống: dùng chứng chỉ tự ký."
  while :; do sleep 3600 & wait $!; done
fi

HOOK='cp -L "$RENEWED_LINEAGE/fullchain.pem" "$RENEWED_LINEAGE/privkey.pem" /certs/'

# Lần đầu: thử đến khi được (Nginx phải đang phục vụ cổng 80, DNS phải trỏ về VPS)
until [ -d "/etc/letsencrypt/live/$DOMAIN" ]; do
  certbot certonly --webroot -w /var/www/certbot -d "$DOMAIN" -m "$LETSENCRYPT_EMAIL" \
    --agree-tos --no-eff-email --non-interactive --deploy-hook "$HOOK" || { sleep 300 & wait $!; }
done

# Đảm bảo Nginx dùng chứng chỉ thật cả khi container khởi động lại
cp -L "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" "/etc/letsencrypt/live/$DOMAIN/privkey.pem" /certs/

while :; do
  sleep 43200 & wait $!
  certbot renew --webroot -w /var/www/certbot --deploy-hook "$HOOK"
done
