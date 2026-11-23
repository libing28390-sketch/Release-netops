"""Batch 1 security close-out: M14 provider-key encryption, M16 provider audit, M12 vault."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import os
import sys
import time
import uuid
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from core.config import settings
from ai.security import crypto


# ── M14: ciphertext format ───────────────────────────────────────────────


def test_new_ciphertexts_are_versioned_and_bound_to_the_provider():
    token = crypto.encrypt_api_key("sk-test-1234567890abcd", provider_id="prov_a")
    assert token.startswith(f"aik:v2:{crypto.current_kid()}:")
    assert crypto.decrypt_api_key(token, provider_id="prov_a") == "sk-test-1234567890abcd"
    with pytest.raises(crypto.ProviderKeyDecryptError):
        crypto.decrypt_api_key(token, provider_id="prov_b")


def test_two_encryptions_differ_and_none_means_no_key():
    first = crypto.encrypt_api_key("sk-test-1234567890abcd", provider_id="p")
    assert first != crypto.encrypt_api_key("sk-test-1234567890abcd", provider_id="p")
    assert crypto.encrypt_api_key(None, provider_id="p") is None
    assert crypto.decrypt_api_key(None, provider_id="p") is None


def _legacy_token(plain: str) -> str:
    raw = settings.CREDENTIAL_ENCRYPTION_KEY or settings.SECRET_KEY
    key = hashlib.sha256(str(raw).encode("utf-8")).digest()
    nonce = os.urandom(12)
    return base64.b64encode(nonce + AESGCM(key).encrypt(nonce, plain.encode("utf-8"), None)).decode("ascii")


def test_legacy_ciphertexts_still_decrypt_and_are_upgraded():
    legacy = _legacy_token("sk-legacy-1234567890")
    assert crypto.decrypt_api_key(legacy, provider_id="any") == "sk-legacy-1234567890"
    upgraded, changed = crypto.reencrypt_if_needed(legacy, provider_id="prov_x")
    assert changed and crypto.is_current_format(upgraded)
    assert crypto.decrypt_api_key(upgraded, provider_id="prov_x") == "sk-legacy-1234567890"
    assert crypto.reencrypt_if_needed(upgraded, provider_id="prov_x") == (upgraded, False)


def test_wrong_master_key_raises_instead_of_looking_like_no_key(monkeypatch):
    token = crypto.encrypt_api_key("sk-test-1234567890abcd", provider_id="p")
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "another-master-key-0123456789")
    with pytest.raises(crypto.ProviderKeyDecryptError) as exc_info:
        crypto.decrypt_api_key(token, provider_id="p")
    assert exc_info.value.code == "AI_KEY_DECRYPT_FAILED"
    with pytest.raises(crypto.ProviderKeyDecryptError):
        crypto.decrypt_api_key("not-base64-%%%", provider_id="p")


def test_master_key_rotation_keeps_old_kid_readable(monkeypatch):
    old = crypto.encrypt_api_key("sk-test-1234567890abcd", provider_id="p")
    assert old.startswith("aik:v2:c1:")
    monkeypatch.setattr(settings, "AI_PROVIDER_KEY_ENCRYPTION_KEYS", "k2:a-brand-new-master-key-0123456789", raising=False)
    monkeypatch.setattr(settings, "AI_PROVIDER_KEY_ID", "k2", raising=False)
    assert crypto.current_kid() == "k2"
    new = crypto.encrypt_api_key("sk-test-1234567890abcd", provider_id="p")
    assert new.startswith("aik:v2:k2:")
    assert crypto.decrypt_api_key(old, provider_id="p") == crypto.decrypt_api_key(new, provider_id="p")
    assert crypto.reencrypt_if_needed(old, provider_id="p")[1] is True


def test_secret_key_alone_is_not_a_master_key(monkeypatch):
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "")
    monkeypatch.setattr(settings, "AI_PROVIDER_KEY_ENCRYPTION_KEYS", "", raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY", "a-session-signing-secret-123456")
    assert crypto.has_configured_master_key() is False
    with pytest.raises(RuntimeError):
        crypto.encrypt_api_key("sk-test-1234567890abcd", provider_id="p")


def test_mask_shows_only_the_last_four_characters():
    assert crypto.mask_api_key("sk-test-1234567890abcd") == "****abcd"
    assert crypto.mask_api_key("short-key") == "********"
    assert crypto.mask_api_key(None) is None


# ── M16: provider API ────────────────────────────────────────────────────

USER = {"username": "admin", "role": "Administrator", "user_id": "u-admin"}


def _create(**overrides):
    from ai.api.providers import create_provider
    from ai.schemas.provider import AIProviderCreate

    values = {"name": f"Compat-{uuid.uuid4().hex[:6]}", "provider_type": "openai_compatible", "base_url": "https://api.example-a.com/v1"}
    values.update(overrides)
    return create_provider(AIProviderCreate(**values), user=USER)


def _audit(conn, provider_id: str):
    return [
        row[0]
        for row in conn.execute(
            "SELECT event_type FROM audit_events WHERE target_type = 'ai_provider' AND target_id = ? ORDER BY created_at",
            (provider_id,),
        ).fetchall()
    ]


def test_create_without_a_model_code_creates_no_guessed_models(isolated_db):
    from database.core import get_db_connection

    created = _create(provider_type="openai")
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ai_model WHERE provider_id = ?", (created.id,)).fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ai_model_route").fetchone()[0] == 0
        assert _audit(conn, created.id) == ["ai_provider.created"]


def test_create_with_a_model_code_creates_only_that_model(isolated_db):
    from database.core import get_db_connection

    created = _create(default_model_code="my-model-1")
    with get_db_connection() as conn:
        codes = [row[0] for row in conn.execute("SELECT model_code FROM ai_model WHERE provider_id = ?", (created.id,)).fetchall()]
        assert codes == ["my-model-1"]
        assert conn.execute("SELECT COUNT(*) FROM ai_model_route").fetchone()[0] == 5


def test_key_given_at_creation_is_versioned_encrypted_and_never_audited(isolated_db):
    from database.core import get_db_connection

    created = _create(api_key="sk-test-1234567890abcd")
    assert created.api_key_masked == "****abcd"
    with get_db_connection() as conn:
        stored = conn.execute("SELECT api_key_encrypted, adapter_key_version FROM ai_provider WHERE id = ?", (created.id,)).fetchone()
        assert crypto.decrypt_api_key(stored[0], provider_id=created.id) == "sk-test-1234567890abcd"
        assert stored[1] == 1
        rotation = conn.execute("SELECT key_version, status FROM ai_provider_key_rotation WHERE provider_id = ?", (created.id,)).fetchall()
        assert [tuple(row) for row in rotation] == [(1, "active")]
        details = conn.execute("SELECT details_json, after_json FROM audit_events WHERE target_id = ?", (created.id,)).fetchall()
        assert all("1234567890" not in str(row[0]) + str(row[1]) for row in details)


def test_edit_with_a_new_key_goes_through_rotation(isolated_db):
    from ai.api.providers import update_provider
    from ai.schemas.provider import AIProviderUpdate
    from database.core import get_db_connection

    created = _create(api_key="sk-first-1234567890aaaa")
    updated = update_provider(created.id, AIProviderUpdate(api_key="sk-second-1234567890bbbb"), user=USER)
    assert updated.api_key_masked == "****bbbb"
    with get_db_connection() as conn:
        rotation = conn.execute(
            "SELECT key_version, status FROM ai_provider_key_rotation WHERE provider_id = ? ORDER BY key_version", (created.id,)
        ).fetchall()
        assert [tuple(row) for row in rotation] == [(1, "retired"), (2, "active")]
        actions = conn.execute("SELECT action FROM ai_provider_key_audit WHERE provider_id = ?", (created.id,)).fetchall()
        assert [row[0] for row in actions].count("rotate") == 2
        assert "ai_provider.updated" in _audit(conn, created.id)


def test_enable_toggle_and_delete_are_audited(isolated_db):
    from ai.api.providers import delete_provider, update_provider
    from ai.schemas.provider import AIProviderUpdate
    from database.core import get_db_connection

    created = _create()
    update_provider(created.id, AIProviderUpdate(enabled=False), user=USER)
    update_provider(created.id, AIProviderUpdate(timeout=45), user=USER)
    delete_provider(created.id, user=USER)
    with get_db_connection() as conn:
        events = _audit(conn, created.id)
    assert events == ["ai_provider.created", "ai_provider.disabled", "ai_provider.updated", "ai_provider.deleted"]


def test_invalidated_and_expired_history_drops_ciphertexts(isolated_db, monkeypatch):
    from ai.api.providers import invalidate_provider_key, provider_key_history, rotate_provider_key
    from api.knowledge_contracts import ProviderKeyRotationRequest
    from database.core import get_db_connection

    created = _create(api_key="sk-first-1234567890aaaa")
    rotate_provider_key(created.id, ProviderKeyRotationRequest(api_key="sk-second-1234567890bbbb"), user=USER)
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE ai_provider_key_rotation SET retired_at = '2000-01-01T00:00:00+00:00' WHERE provider_id = ? AND status = 'retired'",
            (created.id,),
        )
        conn.commit()
    rotate_provider_key(created.id, ProviderKeyRotationRequest(api_key="sk-third-1234567890cccc"), user=USER)
    invalidate_provider_key(created.id, None, user=USER)
    history = provider_key_history(created.id, user=USER)
    by_version = {item["key_version"]: item for item in history["versions"]}
    assert by_version[1]["ciphertext_retained"] is False      # retired long ago
    assert by_version[2]["ciphertext_retained"] is True       # retired just now, inside the window
    assert by_version[3]["status"] == "invalidated" and by_version[3]["ciphertext_retained"] is False
    assert all("api_key_encrypted" not in item for item in history["versions"])
    assert any(entry["action"] == "invalidate" for entry in history["audit"])


def test_gateway_reports_an_undecryptable_key(isolated_db, monkeypatch):
    from ai.gateway.exceptions import AIKeyDecryptException
    from ai.gateway.llm_gateway import LLMGateway
    from database.core import get_db_connection

    created = _create(api_key="sk-first-1234567890aaaa")
    monkeypatch.setattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "another-master-key-0123456789")
    gateway = LLMGateway()
    getter = next(getattr(gateway, name) for name in ("_get_provider_instance", "_provider_instance", "_build_provider") if hasattr(gateway, name))
    with pytest.raises(AIKeyDecryptException) as exc_info:
        getter(created.id)
    assert exc_info.value.code == "AI_KEY_DECRYPT_FAILED"
    with get_db_connection() as conn:
        assert conn.execute("SELECT api_key_encrypted FROM ai_provider WHERE id = ?", (created.id,)).fetchone()[0]


def test_reencrypt_script_upgrades_legacy_rows(isolated_db):
    from database.core import get_db_connection

    created = _create()
    with get_db_connection() as conn:
        conn.execute("UPDATE ai_provider SET api_key_encrypted = ? WHERE id = ?", (_legacy_token("sk-legacy-1234567890"), created.id))
        conn.commit()
    path = Path(__file__).resolve().parents[3] / "scripts" / "ai_provider_key_reencrypt.py"
    spec = importlib.util.spec_from_file_location("nexora_ai_provider_key_reencrypt", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    dry = module.run(dry_run=True)
    assert dry["tables"]["ai_provider"]["upgraded"] == 1
    report = module.run(dry_run=False)
    assert report["status"] == "PASS"
    with get_db_connection() as conn:
        token = conn.execute("SELECT api_key_encrypted FROM ai_provider WHERE id = ?", (created.id,)).fetchone()[0]
    assert crypto.is_current_format(token)
    assert crypto.decrypt_api_key(token, provider_id=created.id) == "sk-legacy-1234567890"


# ── M12: vault and provider user id ──────────────────────────────────────


def test_vault_purge_is_heap_based_and_consistent():
    from ai.security.tokenization import ScopedTokenVault

    vault = ScopedTokenVault(ttl_seconds=1, max_entries=1000)
    tokens = [vault.put(f"10.0.0.{index}", kind="IP", tenant_id="t", task_id="k") for index in range(50)]
    assert len(vault._entries) == len(vault._reverse) == 50
    vault.purge(now=time.monotonic() + 5)
    assert vault._entries == {} and vault._reverse == {} and vault._raw_by_key == {}
    assert vault.resolve_token(tokens[0], tenant_id="t", task_id="k") is None
    vault.put("10.0.0.1", kind="IP", tenant_id="t", task_id="a")
    vault.put("10.0.0.2", kind="IP", tenant_id="t", task_id="b")
    vault.clear_scope(tenant_id="t", task_id="a")
    assert [key[1] for key in vault._entries] == ["b"] and len(vault._reverse) == 1


def test_provider_user_id_is_keyed_and_differs_from_the_storage_key(monkeypatch):
    from ai.security.tokenization import opaque_user_id, provider_user_id

    unkeyed = "nxa_user_" + hashlib.sha256(b"tenant-default:task-1:alice").hexdigest()[:32]
    assert opaque_user_id("alice", tenant_id="tenant-default", task_id="task-1") == unkeyed
    keyed = provider_user_id("alice", tenant_id="tenant-default", task_id="task-1")
    assert keyed != unkeyed and keyed.startswith("nxa_user_")
    assert keyed == provider_user_id("alice", tenant_id="tenant-default", task_id="task-1")
    monkeypatch.setattr(settings, "AI_HASH_SALT", "a-dedicated-hash-salt-123456", raising=False)
    assert provider_user_id("alice", tenant_id="tenant-default", task_id="task-1") != keyed


def test_conversation_history_survives_a_vault_reset(isolated_db):
    from ai.security.tokenization import token_vault
    from ai.services import conversation_service as service
    from database.core import get_db_connection

    conversation = service.create_conversation(tenant_id="tenant-default", user_id="alice", title="t")
    conversation_id = conversation.get("id") or conversation.get("conversation", {}).get("id")
    service.append_message(conversation_id=conversation_id, tenant_id="tenant-default", user_id="alice", role="user", content="10.10.20.15 接在哪台交换机")
    with get_db_connection() as conn:
        stored = conn.execute("SELECT content_safe FROM ai_messages WHERE conversation_id = ?", (conversation_id,)).fetchone()[0]
    assert "10.10.20.15" not in stored and stored.startswith("afc:v1:")
    token_vault._entries.clear(); token_vault._reverse.clear(); token_vault._raw_by_key.clear(); token_vault._expiry_heap.clear()
    messages = service.get_context(conversation_id=conversation_id, tenant_id="tenant-default", user_id="alice")["messages"]
    assert messages[0]["content"] == "10.10.20.15 接在哪台交换机"
    found = service.list_conversations(tenant_id="tenant-default", user_id="alice", search="10.10.20.15")
    assert [item["id"] for item in found["items"]] == [conversation_id]
    assert service.list_conversations(tenant_id="tenant-default", user_id="alice", search="不存在的词")["total"] == 0


def test_explicit_null_clears_retention_days_but_omitted_keeps_it(isolated_db):
    from ai.api.providers import update_provider
    from ai.schemas.provider import AIProviderUpdate
    from database.core import get_db_connection

    created = _create()
    update_provider(created.id, AIProviderUpdate(retention_days=30), user=USER)
    update_provider(created.id, AIProviderUpdate(timeout=40), user=USER)
    with get_db_connection() as conn:
        assert conn.execute("SELECT retention_days FROM ai_provider WHERE id = ?", (created.id,)).fetchone()[0] == 30
    update_provider(created.id, AIProviderUpdate.model_validate({"retention_days": None}), user=USER)
    with get_db_connection() as conn:
        assert conn.execute("SELECT retention_days FROM ai_provider WHERE id = ?", (created.id,)).fetchone()[0] is None
