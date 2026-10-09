#!/bin/bash
# Chạy MỘT LẦN khi khởi tạo volume DB trống, sau script cài TimescaleDB có sẵn của image (000–010).
# Tạo PostGIS và hai vai trò (database_design 12):
#   aqi_migrator: chủ DB, Alembic dùng để tạo bảng, hypertable, policy;
#   aqi_app: ứng dụng dùng, chỉ đọc/ghi dữ liệu, không được đổi schema.

psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -v db="$POSTGRES_DB" -v migrator_pw="$DB_MIGRATOR_PASSWORD" -v app_pw="$DB_APP_PASSWORD" <<'SQL'
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE ROLE aqi_migrator LOGIN PASSWORD :'migrator_pw';
CREATE ROLE aqi_app LOGIN PASSWORD :'app_pw';

ALTER DATABASE :"db" OWNER TO aqi_migrator;
ALTER SCHEMA public OWNER TO aqi_migrator;
GRANT USAGE ON SCHEMA public TO aqi_app;

-- Bảng và sequence do aqi_migrator tạo về sau tự cấp quyền đọc/ghi cho aqi_app
ALTER DEFAULT PRIVILEGES FOR ROLE aqi_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO aqi_app;
ALTER DEFAULT PRIVILEGES FOR ROLE aqi_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO aqi_app;
SQL
