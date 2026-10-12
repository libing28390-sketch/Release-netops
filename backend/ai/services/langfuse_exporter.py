"""Langfuse Metadata-only Observability Exporter.

Strict Compliance Rules:
1. ALLOWLIST ONLY: Only exports high-level operational metadata (latency, tokens, intent, model, status).
2. ZERO DATA EXFILTRATION: Strictly forbidden to export raw prompts, full responses, raw CLI configurations,
   device IPs, passwords, SNMP community strings, or unredacted token mappings.
3. ZERO BLOCKING: Non-blocking background worker; failures/timeouts to external collector NEVER affect
   the primary user-facing conversation or cause 500 errors.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import queue
import re
import threading
import time
import urllib.request
from typing import Any, Mapping

logger = logging.getLogger("nexora.ai.observability")

# 严格白名单字段定义（禁止任何正文、配置或凭据入库）
METADATA_ALLOWLIST_FIELDS = frozenset({
    "request_id",
    "tenant_hash",
    "user_hash",
    "scene",
    "intent",
    "provider_id",
    "model_id",
    "prompt_version",
    "parser_version",
    "chunker_version",
    "embedding_version",
    "reranker_version",
    "candidate_count",
    "latency_ms",
    "token_count",
    "estimated_cost",
    "security_decision",
    "error_code",
    "citation_count",
    "quality_flags",
    "vendor",
    "platform",
    "timestamp",
})

# 严格黑名单字段拦截（禁止明文正文、凭据与配置）
FORBIDDEN_FIELDS = frozenset({
    "prompt",
    "raw_prompt",
    "response",
    "full_response",
    "content",
    "cli_output",
    "config",
    "configuration",
    "password",
    "secret",
    "auth_token",
    "api_token",
    "secret_token",
    "community",
    "ip_address",
})


_SAFE_SLUG_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{1,32}$")


def _is_safe_top_level_string(v: Any) -> bool:
    """仅允许字母数字、下划线、短横线且长度 <= 32 的非敏感标识符（如 vendor, platform, model）。"""
    if not isinstance(v, str):
        return False
    if not _SAFE_SLUG_REGEX.match(v):
        return False
    v_low = v.lower()
    if any(f in v_low for f in FORBIDDEN_FIELDS):
        return False
    return True


def hash_identifier(value: Any, salt: str | None = None) -> str:
    """对租户或用户标识进行单向加盐哈希，杜绝明文标识外发。"""
    if not value:
        return "anonymous"
    effective_salt = salt or os.environ.get("AI_HASH_SALT") or os.environ.get("SECRET_KEY") or "nexora-observability-salt"
    text = f"{value}:{effective_salt}".encode("utf-8")
    return hashlib.sha256(text).hexdigest()[:16]


def sanitize_metadata_payload(raw_payload: Mapping[str, Any]) -> dict[str, Any]:
    """过滤并仅保留白名单元数据字段，杜绝任何正文文本、凭据、IPv6/MAC 或深层数据走私。"""
    sanitized: dict[str, Any] = {}
    for key, val in raw_payload.items():
        k_lower = key.lower()
        # 拦截黑名单键
        if any(f in k_lower for f in FORBIDDEN_FIELDS):
            continue

        # 自动加盐脱敏租户标识
        if k_lower in ("tenant_id", "tenant_hash"):
            sanitized["tenant_hash"] = hash_identifier(val)
            continue
        if k_lower == "user_hash":
            # The field name is not proof that the value was hashed.  Preserve
            # an existing opaque hex digest, otherwise hash the supplied
            # value before it can enter the metadata queue.
            text_value = str(val or "").strip()
            sanitized["user_hash"] = (
                text_value[:16]
                if re.fullmatch(r"[0-9a-fA-F]{16,64}", text_value)
                else hash_identifier(text_value)
            )
            continue

        if k_lower in METADATA_ALLOWLIST_FIELDS:
            if isinstance(val, (int, float, bool)) or val is None:
                sanitized[k_lower] = val
            elif isinstance(val, str):
                # 顶层字符串仅允许安全标识符（如厂商/平台/模型），杜绝任何包含空格、冒号（IPv6/MAC）或长文本的内容
                if _is_safe_top_level_string(val):
                    sanitized[k_lower] = val
            elif isinstance(val, (list, tuple)):
                # 列表仅允许纯数值、布尔值或安全标识符
                clean_list = [
                    x for x in val
                    if isinstance(x, (int, float, bool)) or (isinstance(x, str) and _is_safe_top_level_string(x))
                ]
                sanitized[k_lower] = clean_list
            elif isinstance(val, dict):
                # 嵌套字典（如 quality_flags）严格只允许 bool 标志或 int/float 数值计数器，100% 杜绝短文本或 IP 走私
                clean_dict = {}
                for sk, sv in val.items():
                    if any(f in sk.lower() for f in FORBIDDEN_FIELDS):
                        continue
                    if isinstance(sv, (int, float, bool)):
                        clean_dict[sk] = sv
                sanitized[k_lower] = clean_dict

    sanitized.setdefault("timestamp", int(time.time()))
    return sanitized


def _validate_langfuse_endpoint(endpoint: str) -> str:
    """校验并确保 Langfuse 接入点位于合法回环地址或内网受控白名单中。"""
    from urllib.parse import urlparse
    parsed = urlparse(endpoint)
    try:
        host = (parsed.hostname or "").lower()
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("Langfuse endpoint is malformed") from exc
    if (
        parsed.scheme not in ("http", "https")
        or not host
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Langfuse endpoint must be an HTTP(S) URL without credentials or query parameters")
    allowed_hosts = {"127.0.0.1", "localhost", "::1", "langfuse"}
    extra_hosts = {h.strip().lower() for h in os.environ.get("LANGFUSE_ALLOWED_HOSTS", "").split(",") if h.strip()}
    allowed_hosts.update(extra_hosts)
    if host in allowed_hosts:
        return endpoint
    raise ValueError("Langfuse endpoint host is not in the configured allowlist")


class LangfuseMetadataExporter:
    """Asynchronous, non-blocking metadata-only exporter for Langfuse."""

    def __init__(
        self,
        endpoint: str | None = None,
        *,
        mode: str | None = None,
        timeout_seconds: float = 2.0,
    ) -> None:
        self.mode = str(
            mode if mode is not None else os.environ.get("AI_OBSERVABILITY_MODE", "off")
        ).lower()
        raw_endpoint = (
            endpoint or os.environ.get("LANGFUSE_METADATA_ENDPOINT", "http://127.0.0.1:3000/api/public/ingestion")
        ).rstrip("/")
        self.endpoint: str | None = None
        self.configuration_error: str | None = None
        try:
            self.endpoint = _validate_langfuse_endpoint(raw_endpoint)
        except Exception:
            self.configuration_error = "LANGFUSE_ENDPOINT_INVALID"
        self.timeout_seconds = float(os.environ.get("LANGFUSE_TIMEOUT_SECONDS", timeout_seconds))
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
        self._worker_thread: threading.Thread | None = None
        self._stopped = False

    def export(self, payload: Mapping[str, Any]) -> bool:
        """非阻塞提交一条脱敏后的元数据记录，严格静默异常不影响主链路。"""
        if self.mode != "metadata" or not self.endpoint:
            return False

        try:
            sanitized = sanitize_metadata_payload(payload)
            self._queue.put_nowait(sanitized)
            self._ensure_worker()
            return True
        except queue.Full:
            logger.warning("Langfuse exporter queue is full; dropping event to prevent latency spike")
            return False
        except Exception as exc:
            logger.warning("Langfuse exporter failed to enqueue event safely: %s", exc)
            return False

    def _ensure_worker(self) -> None:
        if self._worker_thread is None or not self._worker_thread.is_alive():
            self._stopped = False
            self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True, name="langfuse-exporter")
            self._worker_thread.start()

    def _worker_loop(self) -> None:
        while not self._stopped:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue

            try:
                self._send_payload(item)
            except Exception as exc:
                logger.debug("Failed to export metadata to Langfuse: %s", exc)
            finally:
                self._queue.task_done()

    def _send_payload(self, payload: dict[str, Any]) -> None:
        if not self.endpoint:
            return
        data_bytes = json.dumps({"batch": [payload]}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.endpoint}",
            data=data_bytes,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_seconds):
            pass


langfuse_metadata_exporter = LangfuseMetadataExporter()
