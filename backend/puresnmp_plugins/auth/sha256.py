"""SNMPv3 HMAC-SHA-256-192 authentication plugin (RFC 7860)."""

import hashlib

from puresnmp_plugins.auth.sha2_common import build_sha2_auth

IDENTIFIER = "sha256"
IANA_ID = 6

authenticate_incoming_message, authenticate_outgoing_message = build_sha2_auth(
    hashlib.sha256,
    key_length=32,
    digest_length=24,
)
