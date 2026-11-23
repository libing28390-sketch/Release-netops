"""Nexora semantic embedding sidecar (bge-m3, ONNX Runtime, CPU).

A small HTTP service that turns text into dense vectors.  It runs in its own
container on an internal Docker network, loads an offline model directory and
never opens outbound connections.

Endpoints
---------
GET  /healthz          liveness + readiness (503 until the model is loaded)
GET  /v1/info          model contract: model_id, dimensions, version, sha256
POST /v1/embeddings    {"input": [str, ...], "kind": "query" | "document"}
                       -> {"model", "dimensions", "data": [[float, ...], ...]}

Model directory (``EMBEDDING_MODEL_DIR``, default /models/bge-m3)
------------------------------------------------------------------
model.onnx       exported + int8-quantized by ``export_model.py``
tokenizer.json   HuggingFace fast tokenizer
manifest.json    {"model_id", "dimensions", "version", "max_length", "files": {name: sha256}}

bge-m3 dense vectors are the normalized [CLS] hidden state; queries need no
instruction prefix.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import os
import threading
import time
from pathlib import Path
from typing import Any, List, Literal, Sequence

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("nexora.embedding_sidecar")
logging.basicConfig(level=os.environ.get("EMBEDDING_LOG_LEVEL", "INFO"))

MODEL_DIR = Path(os.environ.get("EMBEDDING_MODEL_DIR", "/models/bge-m3"))
MAX_BATCH = max(1, min(int(os.environ.get("EMBEDDING_MAX_BATCH", "64")), 256))
MAX_TEXT_CHARS = max(16, min(int(os.environ.get("EMBEDDING_MAX_TEXT_CHARS", "8192")), 65536))
INFER_BATCH = max(1, min(int(os.environ.get("EMBEDDING_INFER_BATCH", "16")), MAX_BATCH))
VERIFY_SHA256 = str(os.environ.get("EMBEDDING_VERIFY_SHA256", "1")).lower() in {"1", "true", "yes"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class Encoder:
    """ONNX Runtime encoder; heavy imports happen only when it is built."""

    def __init__(self, model_dir: Path) -> None:
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        manifest = json.loads((model_dir / "manifest.json").read_text(encoding="utf-8"))
        if VERIFY_SHA256:
            for name, expected in (manifest.get("files") or {}).items():
                actual = _sha256(model_dir / name)
                if actual != expected:
                    raise RuntimeError(f"model file checksum mismatch: {name}")
        self.np = np
        self.model_id = str(manifest["model_id"])
        self.dimensions = int(manifest["dimensions"])
        self.version = str(manifest.get("version") or "v1")
        self.max_length = int(os.environ.get("EMBEDDING_MAX_TOKENS", manifest.get("max_length", 512)))
        self.manifest_sha256 = _sha256(model_dir / "manifest.json")

        self.tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=self.max_length)
        self.tokenizer.enable_padding(pad_id=self.tokenizer.token_to_id("<pad>") or 1, pad_token="<pad>")

        options = ort.SessionOptions()
        threads = int(os.environ.get("EMBEDDING_THREADS", "0") or 0)
        if threads > 0:
            options.intra_op_num_threads = threads
            options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.session = ort.InferenceSession(str(model_dir / "model.onnx"), options, providers=["CPUExecutionProvider"])
        self.input_names = {item.name for item in self.session.get_inputs()}
        # ONNX Runtime sessions are thread-safe, but serializing keeps peak
        # memory bounded to one batch inside the container limit.
        self._lock = threading.Lock()

    def encode(self, texts: Sequence[str]) -> List[List[float]]:
        np = self.np
        vectors: List[List[float]] = []
        for start in range(0, len(texts), INFER_BATCH):
            batch = self.tokenizer.encode_batch(list(texts[start:start + INFER_BATCH]))
            feeds = {
                "input_ids": np.asarray([item.ids for item in batch], dtype=np.int64),
                "attention_mask": np.asarray([item.attention_mask for item in batch], dtype=np.int64),
            }
            if "token_type_ids" in self.input_names:
                feeds["token_type_ids"] = np.zeros_like(feeds["input_ids"])
            with self._lock:
                hidden = self.session.run(None, {k: v for k, v in feeds.items() if k in self.input_names})[0]
            cls = hidden[:, 0, :].astype(np.float32)
            norms = np.linalg.norm(cls, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            vectors.extend((cls / norms).tolist())
        return vectors


class _State:
    encoder: Any = None
    error: str | None = None
    loaded_at: float | None = None


state = _State()
app = FastAPI(title="Nexora embedding sidecar", docs_url=None, redoc_url=None, openapi_url=None)


def load_encoder(factory=Encoder) -> None:
    try:
        started = time.perf_counter()
        state.encoder = factory(MODEL_DIR)
        state.error = None
        state.loaded_at = time.time()
        logger.info(
            "embedding model loaded model=%s dims=%s in %.1fs",
            state.encoder.model_id, state.encoder.dimensions, time.perf_counter() - started,
        )
    except Exception as exc:  # keep serving /healthz with the reason
        state.encoder = None
        state.error = type(exc).__name__
        logger.exception("embedding model failed to load")


@app.on_event("startup")
def _startup() -> None:
    if state.encoder is None and os.environ.get("EMBEDDING_SKIP_LOAD") != "1":
        load_encoder()


def require_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("EMBEDDING_SIDECAR_TOKEN", "")
    if not expected:
        return
    supplied = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="unauthorized")


def _ready():
    if state.encoder is None:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "error": state.error})
    return state.encoder


class EmbeddingRequest(BaseModel):
    input: List[str] = Field(min_length=1, max_length=MAX_BATCH)
    kind: Literal["query", "document"] = "document"

    @field_validator("input")
    @classmethod
    def _bounded(cls, values: List[str]) -> List[str]:
        cleaned = []
        for value in values:
            text = str(value or "")
            if not text.strip():
                raise ValueError("input texts must not be empty")
            cleaned.append(text[:MAX_TEXT_CHARS])
        return cleaned


@app.get("/healthz")
def healthz():
    encoder = _ready()
    return {"status": "ok", "model": encoder.model_id, "dimensions": encoder.dimensions}


@app.get("/v1/info", dependencies=[Depends(require_token)])
def info():
    encoder = _ready()
    return {
        "model_id": encoder.model_id,
        "dimensions": encoder.dimensions,
        "version": encoder.version,
        "max_tokens": encoder.max_length,
        "max_batch": MAX_BATCH,
        "manifest_sha256": encoder.manifest_sha256,
    }


@app.post("/v1/embeddings", dependencies=[Depends(require_token)])
def embeddings(request: EmbeddingRequest):
    encoder = _ready()
    started = time.perf_counter()
    vectors = encoder.encode(request.input)
    if len(vectors) != len(request.input) or any(
        len(vector) != encoder.dimensions or not all(math.isfinite(value) for value in vector) for vector in vectors
    ):
        logger.error("encoder produced an invalid batch")
        raise HTTPException(status_code=500, detail="invalid_embedding_output")
    # Never log the texts themselves.
    logger.info(
        "embedded kind=%s count=%d chars=%d in %.0fms",
        request.kind, len(vectors), sum(len(t) for t in request.input), (time.perf_counter() - started) * 1000,
    )
    return {"model": encoder.model_id, "dimensions": encoder.dimensions, "data": vectors}
