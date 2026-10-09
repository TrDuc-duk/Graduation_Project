#!/bin/sh
# Sao lưu DB bằng pg_dump (định dạng custom), giữ 7 bản gần nhất trong backups/ ở gốc repo.
# Đặt cron trên VPS, ví dụ 02:30 hằng ngày:
#   30 2 * * * sh /opt/aqi/docker/backup.sh >> /var/log/aqi-backup.log 2>&1
# Nên chép thư mục backups/ ra ngoài VPS định kỳ (scp, rclone...).

set -eu
cd "$(dirname "$0")"
dir=${BACKUP_DIR:-../backups}
mkdir -p "$dir"

file="$dir/aqi-$(date +%Y%m%d-%H%M).dump"
docker compose exec -T db pg_dump -U postgres -Fc aqi > "$file.part"
mv "$file.part" "$file"

ls -1t "$dir"/aqi-*.dump | tail -n +8 | xargs -r rm --
echo "Đã sao lưu: $file"
