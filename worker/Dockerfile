# =============================================================================
# TransformIQ Worker — Dockerfile
# =============================================================================
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY worker/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY worker/*.py /app/
COPY backend/app /backend/app

# Create storage directory (shared volume with backend)
RUN mkdir -p /app/storage

# Worker does not expose HTTP ports.
# Health is monitored via RQ's built-in worker heartbeat.

CMD ["python", "worker.py"]
