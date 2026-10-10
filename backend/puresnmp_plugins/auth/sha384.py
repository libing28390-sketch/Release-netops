"""SNMPv3 HMAC-SHA-384-256 authentication plugin (RFC 7860)."""

import hashlib

from puresnmp_plugins.auth.sha2_common import build_sha2_auth

IDENTIFIER = "sha384"
IANA_ID = 7

authenticate_incoming_message, authenticate_outgoing_message = build_sha2_auth(
    hashlib.sha384,
    key_length=48,
    digest_length=32,
)
