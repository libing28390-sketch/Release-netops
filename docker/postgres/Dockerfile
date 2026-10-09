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

# Create the extension automatically for newly initialized data directories.
# Existing persistent volumes need CREATE EXTENSION once after the server is
# restarted with pg_stat_statements in shared_preload_libraries.
COPY 20-pg-stat-statements.sql /docker-entrypoint-initdb.d/20-pg-stat-statements.sql
COPY --chmod=0755 21-postgres-exporter-role.sh /docker-entrypoint-initdb.d/21-postgres-exporter-role.sh

ENV TZ=Asia/Shanghai
