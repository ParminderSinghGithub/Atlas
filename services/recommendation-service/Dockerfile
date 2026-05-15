# Multi-stage build for Recommendation Service
FROM python:3.11-slim AS base

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY services/recommendation-service/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY services/recommendation-service/app/ ./app/

# Copy ML artifacts from notebooks
COPY notebooks/artifacts/ /artifacts/

# Expose service port
EXPOSE 5005

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; port = os.getenv('PORT') or os.getenv('SERVICE_PORT') or '5005'; urllib.request.urlopen(f'http://127.0.0.1:{port}/health')" || exit 1

# Start service
CMD ["sh", "-c", "PORT=\"${PORT:-${SERVICE_PORT:-5005}}\"; exec uvicorn app.main:app --host 0.0.0.0 --port \"$PORT\""]
