#!/bin/sh
# Chạy Nginx. Mỗi phút kiểm tra chứng chỉ: file đổi (Certbot vừa cấp hoặc gia hạn) thì nạp lại cấu hình.

cert=/etc/nginx/certs/fullchain.pem

(
  last=$(stat -c %Y "$cert")
  while sleep 60; do
    now=$(stat -c %Y "$cert")
    if [ "$now" != "$last" ] && nginx -s reload; then
      last=$now
    fi
  done
) &

exec nginx -g 'daemon off;'
