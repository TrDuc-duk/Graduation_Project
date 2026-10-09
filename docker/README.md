# Hạ tầng Docker

Toàn bộ hệ thống chạy bằng Docker Compose trên một VPS (tham chiếu 2 vCPU / 4 GB RAM / 80 GB SSD). Thiết kế: [backend_design §17](../docs/design/backend_design.md#17-triển-khai), [database_design §12](../docs/design/database_design.md#12-vai-trò-db-kết-nối-phiên).

## Thành phần

| Service | Image | Vai trò | Cổng | RAM tối đa |
|---|---|---|---|---|
| `db` | `timescale/timescaledb-ha:pg16` | PostgreSQL 16 + TimescaleDB + PostGIS | Không mở ra ngoài | 2 GB |
| `api` | build `backend/Dockerfile` | FastAPI, chạy cả job nền (`APP_ROLE=all`) | Chỉ trong mạng Docker | 1 GB |
| `nginx` | build `docker/nginx/Dockerfile` (frontend build sẵn bên trong) | HTTPS, file tĩnh, chuyển `/api` và SSE tới `api` | 80, 443 | 256 MB |
| `certbot` | `certbot/certbot:v5.8.0` | Chứng chỉ tự ký tạm, rồi cấp và gia hạn Let's Encrypt | — | — |
| `xiaozhi-bridge` | build `xiaozhi-bridge/` | Cầu nối Xiaozhi, chỉ chạy với `--profile xiaozhi` | Chỉ kết nối ra ngoài | 256 MB |

| File | Nội dung |
|---|---|
| `docker-compose.yml` | Môi trường chạy thật |
| `docker-compose.dev.yml` | Dev: `db` + `api` tự nạp lại code, mở cổng trên `127.0.0.1` |
| `.env.example` | Mọi biến cấu hình; chép thành `.env` |
| `db/100_aqi_roles.sh` | Khởi tạo DB một lần: PostGIS, vai trò `aqi_migrator` và `aqi_app` |
| `nginx/nginx.conf`, `nginx/default.conf` | Cấu hình cấp main (có `events`) và các server |
| `nginx/start.sh`, `certbot/run.sh` | Nginx tự nạp lại khi chứng chỉ đổi; Certbot tạo, cấp, gia hạn chứng chỉ |
| `backup.sh` | Sao lưu DB, giữ 7 bản |

Volume: `pg_data` (dữ liệu DB), `certs`, `certbot_conf`, `certbot_www`. Thư mục trên host: `models/xgb/` (model, chỉ đọc), `backups/`.

## Chạy lần đầu trên VPS

```bash
curl -fsSL https://get.docker.com | sh                       # Docker + Compose plugin
ufw allow 22/tcp && ufw allow 80/tcp && ufw allow 443/tcp && ufw --force enable
git clone <repo> /opt/aqi && cd /opt/aqi

cp docker/.env.example docker/.env && chmod 600 docker/.env
for k in DB_SUPERUSER_PASSWORD DB_MIGRATOR_PASSWORD DB_APP_PASSWORD JWT_SECRET ASSISTANT_TOKEN; do
  sed -i "s/^$k=.*/$k=$(openssl rand -hex 24)/" docker/.env
done
nano docker/.env                            # điền DOMAIN, LETSENCRYPT_EMAIL, PUBLIC_BASE_URL

# Model: mỗi phiên bản một thư mục, không ghi đè (backend_design 8.1)
mkdir -p models/xgb/v1-no_fill && cp ml/ml_xgb/models/xgb_AQI_h*.json models/xgb/v1-no_fill/

cd docker
docker compose up -d db                                       # lần đầu tự chạy db/100_aqi_roles.sh
docker compose run --rm api alembic upgrade head              # tạo bảng (dùng MIGRATION_DATABASE_URL)
docker compose run --rm api python -m scripts.create_admin    # tài khoản admin đầu tiên
docker compose up -d --build
docker compose run --rm nginx nginx -t                        # kiểm tra cấu hình Nginx
```

- DNS của `DOMAIN` phải trỏ về VPS trước khi chạy. Certbot tự thử lại mỗi 5 phút đến khi xin được chứng chỉ, trong lúc đó Nginx dùng chứng chỉ tự ký.
- Demo trong mạng LAN không có domain: để `DOMAIN` trống, hệ thống dùng chứng chỉ tự ký (firmware dùng `setInsecure()` nên vẫn gửi được).
- Firmware gửi tới địa chỉ đã nạp sẵn; kiểm tra theo [backend_design §17.3](../docs/design/backend_design.md#173-kiểm-tra-firmware-đang-trỏ-về-đâu).

## Cập nhật phiên bản mới

```bash
cd /opt/aqi && git pull
cd docker
docker compose run --rm api alembic upgrade head
docker compose up -d --build && docker image prune -f
```

Sửa cấu hình Nginx thì không cần build lại: `docker compose exec nginx nginx -t && docker compose exec nginx nginx -s reload`.

## Dev trên máy cá nhân

```bash
cp docker/.env.example docker/.env          # điền mật khẩu bất kỳ
cd docker && docker compose -f docker-compose.dev.yml up
```

API ở `http://127.0.0.1:8000` (có `/api/docs`; cổng đổi bằng `API_PORT` nếu đã bận), DB ở `127.0.0.1:5432`. Frontend chạy `npm run dev` trong `frontend/`, Vite proxy `/api` tới cổng 8000.

## HTTPS

- `certbot` tạo chứng chỉ tự ký vào volume `certs` nếu chưa có. Nginx chỉ khởi động sau bước này (healthcheck), nên không bao giờ thiếu chứng chỉ.
- Có `DOMAIN`: xin chứng chỉ Let's Encrypt qua webroot (`/.well-known/acme-challenge/` ở cổng 80), gia hạn mỗi 12 giờ. Deploy hook chép chứng chỉ sang `certs`.
- `nginx/start.sh` kiểm tra file chứng chỉ mỗi phút, file đổi thì `nginx -s reload`.
- Thử gia hạn: `docker compose exec certbot certbot renew --dry-run --webroot -w /var/www/certbot`.

## Sao lưu và khôi phục

```bash
sh docker/backup.sh                         # tạo backups/aqi-YYYYMMDD-HHMM.dump, giữ 7 bản
# cron hằng ngày: 30 2 * * * sh /opt/aqi/docker/backup.sh >> /var/log/aqi-backup.log 2>&1
```

`pg_dump` in cảnh báo "circular foreign-key constraints … continuous_agg". Đây là cảnh báo bình thường với bảng nội bộ của TimescaleDB, bản dump vẫn khôi phục được.

Khôi phục vào DB trống. Volume mới tự chạy `100_aqi_roles.sh` nên đã có extension và vai trò:

```bash
cd docker
docker compose stop api
docker compose exec -T db psql -U postgres -d aqi -c "SELECT timescaledb_pre_restore();"
docker compose exec -T db pg_restore -U postgres -d aqi < ../backups/<file>.dump   # giữ chủ bảng aqi_migrator và quyền của aqi_app
docker compose exec -T db psql -U postgres -d aqi -c "SELECT timescaledb_post_restore();"
docker compose start api
```

## Lệnh thường dùng

| Việc | Lệnh (trong `docker/`) |
|---|---|
| Trạng thái, sức khỏe | `docker compose ps` |
| Log | `docker compose logs -f api` (thay `api` bằng service khác) |
| Vào DB | `docker compose exec db psql -U postgres -d aqi` |
| Bật Xiaozhi | `docker compose --profile xiaozhi up -d` |
| Dừng tất cả | `docker compose down` (giữ dữ liệu; **không** thêm `-v`) |
