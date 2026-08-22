# ── Stage 1: Frontend Build ──────────────────────────────────────────
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY package.json package-lock.json* ./
# The frontend build uses devDependencies such as Vite and cross-env.
# Install them explicitly even when the build environment sets NODE_ENV=production.
RUN npm ci --include=dev --silent
COPY . .
RUN npm run build

# ── Stage 2: Python Runtime ──────────────────────────────────────────
# Pin the production runtime to Python 3.11.  The backend uses the standard
# library StrEnum contract and CI/release gates are already aligned to 3.11;
# local Python 3.10 tooling remains supported through core.enum_compat.
FROM python:3.11-slim
LABEL maintainer="NetOps Team"
LABEL python.version="3.11"
LABEL description="Nexora NetOps Platform"

# System dependencies. Build images on a connected build host, then transfer
# the resulting images to isolated/offline deployment hosts when required.
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        build-essential \
        python3-dev \
        libcairo2-dev \
        pkg-config \
        libffi-dev \
        libssl-dev \
        libcap2-bin \
        tzdata && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (install before copying code for better layer caching)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend source
COPY backend/ /app/backend/

# Copy environment template
COPY .env.example /app/.env.example

# Keep the loopback Terminal Agent available for Docker/Ubuntu users to
# download and run on their own workstation. It is never started in the
# backend container.
COPY scripts/terminal_agent.py /app/scripts/terminal_agent.py
COPY scripts/install-terminal-agent.sh /app/scripts/install-terminal-agent.sh
COPY scripts/sync-frontend-dist.sh /app/scripts/sync-frontend-dist.sh
RUN chmod +x /app/scripts/sync-frontend-dist.sh
# This Windows binary is a download-only artifact. It is never executed in
# the Linux container; the browser workstation downloads it as an attachment.
COPY NexoraTerminalAgent.exe /app/NexoraTerminalAgent.exe

# Keep release-owned TextFSM templates outside the persistent /app/data volume.
# The parser checks this directory after user templates, so every rebuilt image
# receives the latest public-repository templates without overwriting user edits.
COPY data/textfsm_templates/ /app/release-textfsm-templates/

# Keep an immutable copy in the image, then seed the shared frontend volume.
# The runtime sync copies hashed assets before publishing index.html and keeps
# old assets available for browsers that still have a previous HTML snapshot.
COPY --from=frontend-build /app/dist /app/frontend-dist
RUN mkdir -p /app/dist && cp -a /app/frontend-dist/. /app/dist/

# Create runtime directories
RUN mkdir -p /app/data /app/backup /app/data/logs

# Runtime environment
ENV NODE_ENV=production
ENV PYTHONPATH=/app/backend
ENV ENVIRONMENT=production
ENV TZ=Asia/Shanghai
# CREDENTIAL_ENCRYPTION_KEY must be set via .env or docker-compose environment
# Do NOT hardcode secrets here

EXPOSE 8003

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8003/api/health/live', timeout=3)" || exit 1

# Non-root user for security
RUN useradd --create-home --shell /bin/bash --uid 1000 netops && \
    chown -R netops:netops /app
USER netops

# Persistent data volumes
VOLUME ["/app/data", "/app/backup"]

# Keep one worker by default because the lifespan-owned telemetry loops must
# run once per deployment, not once per Uvicorn worker process. Set WORKERS to
# override this deliberately for API-only scaling scenarios.
CMD ["/app/scripts/sync-frontend-dist.sh"]
