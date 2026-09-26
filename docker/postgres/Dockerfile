# PostgreSQL image with the extensions required by the Nexora migrations.
#
# The application Dockerfile builds the FastAPI/frontend image; PostgreSQL is
# built separately so the database image cannot silently fall back to the
# stock PostgreSQL Alpine image (which does not ship pgvector).
FROM pgvector/pgvector:0.8.6-pg18-bookworm

# pg_trgm is required alongside vector by migration 0104. Install it
# explicitly so the image remains self-contained.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-contrib-18 tzdata \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Shanghai
