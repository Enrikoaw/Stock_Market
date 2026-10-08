# Dockerfile untuk Deploy 24/7 (Hugging Face Spaces, Railway, Render, Fly.io, VPS)
FROM python:3.11-slim

WORKDIR /app

# Install dependensi sistem dasar
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Buat direktori data & izin akses (kompatibel dengan Hugging Face Spaces non-root container)
RUN mkdir -p /app/data/user_excel && chmod -R 777 /app/data

ENV PORT=7860
ENV HOST=0.0.0.0
ENV AUTO_SYNC_INTERVAL=1800

EXPOSE 7860

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
