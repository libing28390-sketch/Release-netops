#!/bin/sh
set -eu

readonly SOURCE_DIST=/app/frontend-dist
readonly SHARED_DIST=/app/dist

mkdir -p "$SHARED_DIST/assets"

# Hashed assets are copied first and never deleted. This keeps an old
# index.html usable while a rolling restart is updating the shared volume.
if [ -d "$SOURCE_DIST/assets" ]; then
    cp -a "$SOURCE_DIST/assets/." "$SHARED_DIST/assets/"
fi

# Vite currently emits only index.html and assets/, but preserve any future
# root-level output files as well. Publish index.html last and atomically.
find "$SOURCE_DIST" -mindepth 1 -maxdepth 1 ! -name assets ! -name index.html -exec cp -a {} "$SHARED_DIST/" \;
index_tmp="$SHARED_DIST/.index.html.$$"
cp -a "$SOURCE_DIST/index.html" "$index_tmp"
mv -f "$index_tmp" "$SHARED_DIST/index.html"

exec uvicorn backend.main:app \
    --host 0.0.0.0 \
    --port 8003 \
    --workers "${WORKERS:-1}" \
    --timeout-graceful-shutdown 20
