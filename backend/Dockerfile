# Image backend: FastAPI + code ML dùng chung (ml/ml_xgb/src, backend_design 8.2). Build context = gốc repo.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/aqi_ml

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ml/ml_xgb/src /opt/aqi_ml/src
COPY backend/ .

RUN useradd --uid 1000 --no-create-home app
USER app

# Một tiến trình (backend_design 2.4). Chỉ Nginx gọi tới nên tin X-Forwarded-* từ mọi nguồn trong mạng Docker.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
