"""
license/crypto.py — RSA 签名与验证工具
========================================
Uses RSA-PSS with SHA-256 for tamper-proof license signing.
Private key is used ONLY by the generator (offline tool).
Public key is bundled with the server for verification.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.exceptions import InvalidSignature

logger = logging.getLogger("license.crypto")

# RSA key size
RSA_KEY_SIZE = 2048

# PSS padding config (deterministic, industry standard)
_PSS_PADDING = padding.PSS(
    mgf=padding.MGF1(hashes.SHA256()),
    salt_length=padding.PSS.MAX_LENGTH,
)
_HASH_ALGO = hashes.SHA256()


# ── Key Generation ────────────────────────────────────────────────────

def generate_key_pair(
    private_key_path: Optional[str] = None,
    public_key_path: Optional[str] = None,
) -> Tuple[bytes, bytes]:
    """
    Generate a fresh RSA-2048 key pair.
    Returns (private_key_pem, public_key_pem).
    Optionally writes to files.
    """
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=RSA_KEY_SIZE,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    if private_key_path:
        Path(private_key_path).parent.mkdir(parents=True, exist_ok=True)
        Path(private_key_path).write_bytes(private_pem)
        logger.info(f"Private key written to {private_key_path}")
    if public_key_path:
        Path(public_key_path).parent.mkdir(parents=True, exist_ok=True)
        Path(public_key_path).write_bytes(public_pem)
        logger.info(f"Public key written to {public_key_path}")

    return private_pem, public_pem


# ── Signing (used by generator only) ─────────────────────────────────

def sign_payload(payload_dict: dict, private_key_pem: bytes) -> str:
    """
    Sign a JSON-serializable dict with an RSA private key.
    Returns base64-encoded signature string.
    
    CRITICAL: The payload is serialized with sorted keys and no
    extra whitespace to ensure deterministic signing.
    """
    private_key = serialization.load_pem_private_key(private_key_pem, password=None)
    # Canonical JSON: sorted keys, no indent, ensure_ascii for reproducibility
    canonical = json.dumps(payload_dict, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    canonical_bytes = canonical.encode("utf-8")

    signature = private_key.sign(
        canonical_bytes,
        _PSS_PADDING,
        _HASH_ALGO,
    )
    return base64.b64encode(signature).decode("ascii")


# ── Verification (used by server) ────────────────────────────────────

def verify_signature(payload_dict: dict, signature_b64: str, public_key_pem: bytes) -> bool:
    """
    Verify a payload's RSA-PSS signature using the public key.
    Returns True if valid, False otherwise.
    """
    try:
        public_key = serialization.load_pem_public_key(public_key_pem)
        canonical = json.dumps(payload_dict, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        canonical_bytes = canonical.encode("utf-8")
        signature = base64.b64decode(signature_b64)

        public_key.verify(
            signature,
            canonical_bytes,
            _PSS_PADDING,
            _HASH_ALGO,
        )
        return True
    except InvalidSignature:
        logger.warning("License signature verification FAILED — possible tampering")
        return False
    except Exception as e:
        logger.error(f"License signature verification error: {e}")
        return False


def load_public_key_from_file(path: str) -> bytes:
    """Load a PEM public key from disk."""
    return Path(path).read_bytes()


def load_private_key_from_file(path: str) -> bytes:
    """Load a PEM private key from disk."""
    return Path(path).read_bytes()
