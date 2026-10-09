# Nginx + bản build frontend (theo nginx/Dockerfile của Base). Build context = gốc repo.
# Cấu hình không nằm trong image: mount từ docker/nginx/ khi chạy (docker-compose.yml).

# Bước 1: build frontend React (Vite) ra /app/dist
FROM node:22-alpine AS frontend
WORKDIR /app
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Bước 2: Nginx chỉ chứa file tĩnh đã build
FROM nginx:1.27-alpine
RUN rm /etc/nginx/conf.d/default.conf
COPY --from=frontend /app/dist /usr/share/nginx/html
