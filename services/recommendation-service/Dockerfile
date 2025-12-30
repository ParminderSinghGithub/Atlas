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
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/

# Create artifacts directory (will be mounted as volume)
RUN mkdir -p /artifacts/models /artifacts/features/retailrocket

# Expose service port
EXPOSE 5005

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5005/health')" || exit 1

# Start service
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5005"]
