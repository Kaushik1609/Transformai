# =============================================================================
# TransformIQ Backend — Dockerfile
# =============================================================================
FROM python:3.11-slim

# Install system dependencies required by document processing libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy and install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Create storage directory for local filesystem adapter
RUN mkdir -p /app/storage

# Expose API port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=15s --timeout=10s --start-period=20s --retries=5 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the FastAPI application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
