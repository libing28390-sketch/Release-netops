"""
CMDB Phase 1 — Credential Vault decoupling tests.

Covers:
  - AES-256-GCM encryption round-trip (matches cmdb_design.md spec)
  - Backward-compatible decryption of legacy Fernet (enc:v1:) tokens
  - Plaintext pass-through for un-prefixed legacy values
  - credential_service CRUD: secrets encrypted at rest, masked on read
  - Foreign-key safety: cannot delete a credential still bound to a device
"""

import base64
import pytest

from core.config import settings


@pytest.fixture()
def crypto_key(monkeypatch):
    """Configure a real encryption key and reset cached key material."""
    import core.crypto as crypto
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY",
                        "unit-test-master-key-0123456789abcdef", raising=False)
    monkeypatch.setattr(crypto, "_aes_key", None, raising=False)
    monkeypatch.setattr(crypto, "_fernet", None, raising=False)
    yield crypto
    monkeypatch.setattr(crypto, "_aes_key", None, raising=False)
    monkeypatch.setattr(crypto, "_fernet", None, raising=False)


def test_aes_gcm_round_trip(crypto_key):
    crypto = crypto_key
    plaintext = "S3cr3t-P@ssw0rd!"
    token = crypto.encrypt_credential(plaintext)
    assert token is not None
    assert token.startswith("enc:v2:"), "new ciphertext must use AES-256-GCM (enc:v2:)"
    assert plaintext not in token
    assert crypto.decrypt_credential(token) == plaintext


def test_aes_gcm_nonce_is_random(crypto_key):
    crypto = crypto_key
    t1 = crypto.encrypt_credential("same-value")
    t2 = crypto.encrypt_credential("same-value")
    # Different nonces => different ciphertext for identical plaintext
    assert t1 != t2
    assert crypto.decrypt_credential(t1) == "same-value"
    assert crypto.decrypt_credential(t2) == "same-value"


def test_double_encrypt_is_noop(crypto_key):
    crypto = crypto_key
    once = crypto.encrypt_credential("hello")
    twice = crypto.encrypt_credential(once)
    assert once == twice


def test_legacy_fernet_token_still_decrypts(crypto_key):
    """enc:v1: Fernet tokens written by the old implementation must still decrypt."""
    crypto = crypto_key
    from cryptography.fernet import Fernet
    key = base64.urlsafe_b64encode(crypto._get_aes_key())
    legacy_token = "enc:v1:" + Fernet(key).encrypt(b"legacy-pass").decode("ascii")
    assert crypto.decrypt_credential(legacy_token) == "legacy-pass"


def test_plaintext_passthrough(crypto_key):
    crypto = crypto_key
    # Un-prefixed legacy plaintext returned unchanged
    assert crypto.decrypt_credential("plain-legacy") == "plain-legacy"


def test_empty_values(crypto_key):
    crypto = crypto_key
    assert crypto.encrypt_credential("") == ""
    assert crypto.encrypt_credential(None) is None
    assert crypto.decrypt_credential("") == ""
    assert crypto.decrypt_credential(None) is None


def test_corrupted_token_returns_none(crypto_key):
    crypto = crypto_key
    assert crypto.decrypt_credential("enc:v2:not-valid-base64-or-tag") is None


# ─── credential_service CRUD ────────────────────────────

def test_credential_crud_encrypts_and_masks(isolated_db, crypto_key):
    from database import get_db_connection
    from services import credential_service

    conn = get_db_connection()
    try:
        created = credential_service.create_credential(
            conn,
            credential_name="core-switches",
            credential_type="ssh_password",
            username="netadmin",
            password="P@ss-core",
            enable_password="EnableMe",
            snmp_community="public-ro",
        )
        cred_id = created["id"]

        # Read view must be masked — no secret material leaks
        assert created["has_password"] is True
        assert created["has_enable_password"] is True
        assert created["has_snmp_community"] is True
        assert created["has_private_key"] is False
        assert "password" not in created
        assert "encrypted_password" not in created

        # Secrets are encrypted at rest (AES-256-GCM)
        row = conn.execute("SELECT * FROM credentials WHERE id = ?", (cred_id,)).fetchone()
        assert row["encrypted_password"].startswith("enc:v2:")
        assert "P@ss-core" not in row["encrypted_password"]
        assert crypto_key.decrypt_credential(row["encrypted_password"]) == "P@ss-core"

        # Update: rename + rotate password, leave enable_password untouched
        old_enable = row["enable_password"]
        credential_service.update_credential(
            conn, cred_id, credential_name="core-switches-v2", password="NewP@ss"
        )
        row2 = conn.execute("SELECT * FROM credentials WHERE id = ?", (cred_id,)).fetchone()
        assert row2["credential_name"] == "core-switches-v2"
        assert crypto_key.decrypt_credential(row2["encrypted_password"]) == "NewP@ss"
        assert row2["enable_password"] == old_enable  # untouched

        # Duplicate name rejected
        with pytest.raises(ValueError):
            credential_service.create_credential(conn, credential_name="core-switches-v2")
    finally:
        conn.close()


def test_cannot_delete_credential_in_use(isolated_db, crypto_key):
    from database import get_db_connection
    from services import credential_service

    conn = get_db_connection()
    try:
        cred = credential_service.create_credential(conn, credential_name="bound-cred")
        cred_id = cred["id"]

        conn.execute(
            "INSERT INTO devices (id, hostname, ip_address, status, credential_id) "
            "VALUES (?, ?, ?, ?, ?)",
            ("dev-bound-1", "router-x", "10.9.9.1", "online", cred_id),
        )
        conn.commit()

        assert credential_service.count_devices_using(conn, cred_id) == 1
        with pytest.raises(ValueError):
            credential_service.delete_credential(conn, cred_id)

        # After unbinding, deletion succeeds
        conn.execute("UPDATE devices SET credential_id = NULL WHERE id = 'dev-bound-1'")
        conn.commit()
        credential_service.delete_credential(conn, cred_id)
        assert conn.execute("SELECT 1 FROM credentials WHERE id = ?", (cred_id,)).fetchone() is None
    finally:
        conn.close()
