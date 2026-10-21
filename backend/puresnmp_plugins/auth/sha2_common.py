"""Shared SHA-2 authentication helpers for the local puresnmp plugin namespace."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Any

from puresnmp.util import password_to_key


def build_sha2_auth(hash_function: Callable[[bytes], Any], key_length: int, digest_length: int):
    """Build RFC 7860 SHA-2 USM authentication handlers."""
    localized_key = password_to_key(hash_function, key_length)
    algorithm = hash_function().name

    def authenticate_outgoing_message(auth_key: bytes, data: bytes, engine_id: bytes) -> bytes:
        key = localized_key(auth_key, engine_id)
        return hmac.new(key, data, algorithm).digest()[:digest_length]

    def authenticate_incoming_message(
        auth_key: bytes,
        data: bytes,
        received_digest: bytes,
        engine_id: bytes,
    ) -> bool:
        expected = authenticate_outgoing_message(auth_key, data, engine_id)
        return hmac.compare_digest(received_digest, expected)

    return authenticate_incoming_message, authenticate_outgoing_message
