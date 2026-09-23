from __future__ import annotations

import io

import pytest

from services.storage_service import LocalStorageBackend, StorageNotFound, normalize_object_key


def test_local_backend_put_get_stat_delete_is_atomic(tmp_path):
    backend = LocalStorageBackend(tmp_path / "objects")
    payload = b"encrypted config or recording bytes"

    stored = backend.put_stream("config/2026/09/snap-1.cfg.enc", io.BytesIO(payload), "application/octet-stream")

    assert stored.backend == "local"
    assert stored.size == len(payload)
    assert stored.sha256
    assert backend.stat(stored.object_key).size == len(payload)
    with backend.get_stream(stored.object_key) as handle:
        assert handle.read() == payload

    backend.delete(stored.object_key)
    assert not backend.exists(stored.object_key)
    with pytest.raises(StorageNotFound):
        backend.get_stream(stored.object_key)


@pytest.mark.parametrize("value", ["../escape", "/absolute", "C:/absolute", "", "a/../../b"])
def test_object_keys_reject_traversal(value):
    with pytest.raises(ValueError):
        normalize_object_key(value)


def test_local_backend_does_not_expose_real_path(tmp_path):
    backend = LocalStorageBackend(tmp_path / "objects")
    stored = backend.put_stream("pam/session.cast", b"cast")
    assert stored.object_key == "pam/session.cast"
    assert str(tmp_path) not in stored.object_key
