"""SNMPv3 HMAC-SHA-512-384 authentication plugin (RFC 7860)."""

import hashlib

from puresnmp_plugins.auth.sha2_common import build_sha2_auth

IDENTIFIER = "sha512"
IANA_ID = 8

authenticate_incoming_message, authenticate_outgoing_message = build_sha2_auth(
    hashlib.sha512,
    key_length=64,
    digest_length=48,
)
