# ── Build stage: Frontend ──
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --silent
COPY . .
RUN npm run build

# ── Runtime stage: Python backend ──
FROM python:3.10-slim
LABEL maintainer="NetOps Team"

# System dependencies
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        libffi-dev libssl-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend code
COPY backend/ /app/backend/

# Copy .env file if it exists at project root
COPY .env* /app/

# Copy built frontend from build stage
COPY --from=frontend-build /app/dist /app/dist

# Create data directories
RUN mkdir -p /app/data /app/backup /app/data/logs

# Runtime configuration
ENV NODE_ENV=production
ENV PYTHONPATH=/app/backend
ENV CREDENTIAL_ENCRYPTION_KEY=change-me-to-a-random-secret
ENV ENVIRONMENT=production
ENV LICENSE_PUBLIC_KEY_PATH=/app/backend/license_auth/keys/public.pem

EXPOSE 8003

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8003/api/health')" || exit 1

# Non-root user
RUN useradd --create-home --shell /bin/bash netops && \
    chown -R netops:netops /app
# USER netops

# Volumes for persistent data
VOLUME ["/app/data", "/app/backup"]

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "4"]
