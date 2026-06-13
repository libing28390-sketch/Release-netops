"""
Tests for password-rotation → credential-vault synchronization.

After the credential decoupling, login/backup reads the `credentials` vault.
Rotation must mirror the new secret into the vault so the two don't drift apart.
"""

import pytest

from database import get_db_connection
from core.config import settings
from core.crypto import encrypt_credential, decrypt_credential
from services.password_rotation_service import _sync_credential_vault


@pytest.fixture()
def crypto_key(monkeypatch):
    import core.crypto as crypto
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY",
                        "unit-test-master-key-0123456789abcdef", raising=False)
    monkeypatch.setattr(crypto, "_aes_key", None, raising=False)
    monkeypatch.setattr(crypto, "_fernet", None, raising=False)
    yield crypto


def _seed_cred(conn, cred_id, username, pwd_plain, enable_plain=''):
    conn.execute(
        "INSERT INTO credentials (id, credential_name, credential_type, username, "
        "encrypted_password, enable_password, snmp_community, created_at) "
        "VALUES (?, ?, 'ssh_password', ?, ?, ?, '', '2026-01-01')",
        (cred_id, f"c-{cred_id}", username,
         encrypt_credential(pwd_plain) or '', encrypt_credential(enable_plain) or ''),
    )
    conn.commit()


def test_admin_rotation_updates_vault_when_account_matches(isolated_db, crypto_key):
    conn = get_db_connection()
    try:
        _seed_cred(conn, "cred-a1", "admin", "oldpass")
        device = {"credential_id": "cred-a1", "admin_username": "admin", "username": "admin"}
        new_enc = encrypt_credential("NEWadminPass1-")
        _sync_credential_vault(device, "admin", new_enc)

        row = conn.execute("SELECT encrypted_password FROM credentials WHERE id='cred-a1'").fetchone()
        assert decrypt_credential(row[0]) == "NEWadminPass1-"
    finally:
        conn.close()


def test_normal_rotation_does_not_clobber_admin_vault(isolated_db, crypto_key):
    """Vault represents the 'admin' account; rotating the 'normal' account must
    NOT overwrite the vault's admin password."""
    conn = get_db_connection()
    try:
        _seed_cred(conn, "cred-b1", "admin", "adminpass")
        device = {"credential_id": "cred-b1", "admin_username": "admin",
                  "username": "admin", "normal_username": "user"}
        _sync_credential_vault(device, "normal", encrypt_credential("someNormalPass1-"))

        row = conn.execute("SELECT encrypted_password FROM credentials WHERE id='cred-b1'").fetchone()
        assert decrypt_credential(row[0]) == "adminpass"  # unchanged
    finally:
        conn.close()


def test_enable_rotation_updates_vault_enable_secret(isolated_db, crypto_key):
    conn = get_db_connection()
    try:
        _seed_cred(conn, "cred-c1", "admin", "adminpass", enable_plain="")
        device = {"credential_id": "cred-c1", "admin_username": "admin", "username": "admin"}
        _sync_credential_vault(device, "enable", encrypt_credential("EnableSecret1-"))

        row = conn.execute("SELECT enable_password FROM credentials WHERE id='cred-c1'").fetchone()
        assert decrypt_credential(row[0]) == "EnableSecret1-"
    finally:
        conn.close()


def test_no_credential_id_is_noop(isolated_db, crypto_key):
    # Should not raise when device has no credential_id
    _sync_credential_vault({"admin_username": "admin"}, "admin", encrypt_credential("x"))
