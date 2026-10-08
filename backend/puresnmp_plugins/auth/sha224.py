"""SNMPv3 HMAC-SHA-224-128 authentication plugin (RFC 7860)."""

import hashlib

from puresnmp_plugins.auth.sha2_common import build_sha2_auth

IDENTIFIER = "sha224"
IANA_ID = 5

authenticate_incoming_message, authenticate_outgoing_message = build_sha2_auth(
    hashlib.sha224,
    key_length=28,
    digest_length=16,
)
