# ── Stage 1: Frontend Build ──────────────────────────────────────────
FROM node:20-alpine AS frontend-build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm config set registry https://registry.npmmirror.com && npm ci --silent
COPY . .
RUN npm run build

# ── Stage 2: Python Runtime ──────────────────────────────────────────
# Pin to 3.10-slim to match the compiled .so files (cpython-310).
# If you change this version, re-run the release workflow to recompile .so files.
FROM python:3.10-slim
LABEL maintainer="NetOps Team"
LABEL python.version="3.10"
LABEL description="Nexora NetOps Platform"

# System dependencies (use mirror in China for speed)
RUN sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list 2>/dev/null || true && \
    sed -i 's/security.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list 2>/dev/null || true && \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's/deb.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources && \
        sed -i 's/security.debian.org/mirrors.ustc.edu.cn/g' /etc/apt/sources.list.d/debian.sources; \
    fi && \
    apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        build-essential \
        python3-dev \
        libcairo2-dev \
        pkg-config \
        libffi-dev \
        libssl-dev \
        libcap2-bin && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (install before copying code for better layer caching)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip -i https://mirrors.aliyun.com/pypi/simple/ && \
    pip install --no-cache-dir -r /app/backend/requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

# Copy backend source
COPY backend/ /app/backend/

# Compile license modules using Cython during container build to match Python runtime version
# If Python source files are present (development environment), compile them.
# If they are absent (release repository), skip compiling and use precompiled .so files.
RUN if [ -f /app/backend/license_auth/verifier.py ]; then \
        echo "[INFO] verifier.py found. Compiling license modules using Cython..." && \
        pip install --no-cache-dir cython -i https://mirrors.aliyun.com/pypi/simple/ && \
        echo 'from setuptools import setup, Extension' > /app/compile.py && \
        echo 'from Cython.Build import cythonize' >> /app/compile.py && \
        echo 'extensions = [' >> /app/compile.py && \
        echo '    Extension("backend.license_auth.verifier", ["backend/license_auth/verifier.py"]),' >> /app/compile.py && \
        echo '    Extension("backend.license_auth.crypto", ["backend/license_auth/crypto.py"]),' >> /app/compile.py && \
        echo '    Extension("backend.license_auth.middleware", ["backend/license_auth/middleware.py"]),' >> /app/compile.py && \
        echo ']' >> /app/compile.py && \
        echo 'setup(ext_modules=cythonize(extensions, compiler_directives={"language_level": "3", "always_allow_keywords": True}), script_args=["build_ext", "--inplace"])' >> /app/compile.py && \
        python /app/compile.py && \
        rm -f /app/compile.py && \
        rm -f /app/backend/license_auth/verifier.py /app/backend/license_auth/crypto.py /app/backend/license_auth/middleware.py && \
        rm -f /app/backend/license_auth/*.c && \
        rm -rf /app/build && \
        pip uninstall -y cython; \
    else \
        echo "[INFO] verifier.py not found. Skipping Cython compilation, using pre-compiled .so files."; \
    fi

# Verify the compiled modules can be imported
RUN python -c "import sys; sys.path.insert(0, '/app/backend'); from license_auth.verifier import get_license_verifier, bootstrap_license_protection; print('[OK] license_auth compiled modules loaded successfully')" || \
    (echo '[FAIL] license_auth compiled modules are not compatible or import failed.' && exit 1)

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
