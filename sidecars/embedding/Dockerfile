# Nexora semantic embedding sidecar (bge-m3 ONNX int8, CPU only).
#
# Build on a connected host after exporting the model:
#   python sidecars/embedding/export_model.py --output sidecars/embedding/models/bge-m3
#   docker compose --profile semantic-embedding build embedding-sidecar
# Then `docker save nexora-embedding-sidecar` for offline hosts.  The image
# contains the model, so the container needs no network access at runtime.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EMBEDDING_MODEL_DIR=/models/bge-m3 \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Fails the build early when the model has not been exported.
COPY models/bge-m3/manifest.json models/bge-m3/tokenizer.json models/bge-m3/model.onnx /models/bge-m3/
COPY app.py /app/app.py

RUN useradd --system --uid 10001 --no-create-home embedding && chown -R embedding /app
USER 10001

EXPOSE 8005
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8005/healthz', timeout=3)"

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8005", "--workers", "1", "--no-access-log"]
