# ── Stage 1: Frontend Build ──────────────────────────────────────────
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --silent
COPY . .
RUN npm run build

# ── Stage 2: Python Runtime ──────────────────────────────────────────
# Pin to 3.10-slim to match the compiled .so files (cpython-310).
# If you change this version, re-run the release workflow to recompile .so files.
FROM python:3.10-slim
LABEL maintainer="NetOps Team"
LABEL python.version="3.10"
LABEL description="Nexora NetOps Platform"

# System dependencies
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        libffi-dev \
        libssl-dev \
        libcap2-bin && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (install before copying code for better layer caching)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend source
COPY backend/ /app/backend/

# Verify the license_auth .so is loadable with this Python version
RUN python -c "import sys; sys.path.insert(0, '/app/backend'); from license_auth.verifier import LicenseVerifier; print('[OK] license_auth.verifier loaded successfully')" || \
    (echo '[FAIL] license_auth .so is not compatible with Python '$(python --version)'. Re-run the release workflow to recompile.' && exit 1)

# Copy environment template
COPY .env.example /app/.env.example

# Copy built frontend from Stage 1
COPY --from=frontend-build /app/dist /app/dist

# Create runtime directories
RUN mkdir -p /app/data /app/backup /app/data/logs

# Runtime environment
ENV NODE_ENV=production
ENV PYTHONPATH=/app/backend
ENV ENVIRONMENT=production
ENV LICENSE_PUBLIC_KEY_PATH=/app/backend/license_auth/keys/public.pem
# CREDENTIAL_ENCRYPTION_KEY must be set via .env or docker-compose environment
# Do NOT hardcode secrets here

EXPOSE 8003

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8003/api/health')" || exit 1

# Non-root user for security
RUN useradd --create-home --shell /bin/bash --uid 1000 netops && \
    chown -R netops:netops /app
USER netops

# Persistent data volumes
VOLUME ["/app/data", "/app/backup"]

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "2"]
