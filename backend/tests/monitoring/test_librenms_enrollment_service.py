from __future__ import annotations

import asyncio

from services import librenms_enrollment_service as enrollment
from services.librenms_runtime_client import LibreNMSAPIError


def _target(**overrides):
    return {
        "id": "device-1",
        "asset_id": "asset-1",
        "asset_type": "network_device",
        "management_ip": "192.0.2.40",
        "snmp_port": 1161,
        "credential_type": "snmpv2",
        "snmp_community": "private-v2-community",
        "asset_snmp_community": "",
        "username": "",
        "snmp_security_level": "authPriv",
        "snmp_auth_protocol": "SHA",
        "snmp_auth_password": "",
        "snmp_priv_protocol": "AES",
        "snmp_priv_password": "",
        "snmp_context_name": "",
        **overrides,
    }


def _instance():
    return {
        "id": "instance-1",
        "base_url": "https://librenms.example",
        "health_state": "healthy",
        "credential_type": "api_token",
        "encrypted_password": "encrypted-token",
    }


def _match():
    return {
        "instance_id": "instance-1",
        "native_device_id": "42",
        "native_hostname": "192.0.2.40",
        "poller_group": "0",
        "base_url": "https://librenms.example",
    }


def test_no_external_instance_leaves_device_on_nexora_local_snmp(monkeypatch):
    monkeypatch.setattr(enrollment, "_load_asset_enrollment_context", lambda _device_id: _target())
    monkeypatch.setattr(enrollment, "_load_enabled_instances", lambda: [])

    result = asyncio.run(enrollment.enroll_imported_network_device("device-1"))

    assert result["status"] == "local_snmp"
    assert "Nexora 本地 SNMP 采集器" in result["message"]
    assert result["profile_applied"] is False


def test_snmp_parameters_maps_asset_local_v2_and_v3_profiles(monkeypatch):
    monkeypatch.setattr(enrollment, "decrypt_credential", lambda value: value or "")

    v2, v2_error = enrollment._snmp_parameters(_target())
    assert v2_error == ""
    assert v2 == {"snmpver": "v2c", "community": "private-v2-community"}

    v3, v3_error = enrollment._snmp_parameters(_target(
        credential_type="snmpv3",
        snmp_community="",
        username="snmpv3-user",
        snmp_security_level="authPriv",
        snmp_auth_password="auth-secret",
        snmp_priv_password="privacy-secret",
    ))
    assert v3_error == ""
    assert v3 == {
        "snmpver": "v3",
        "authlevel": "authPriv",
        "authname": "snmpv3-user",
        "authpass": "auth-secret",
        "authalgo": "SHA",
        "cryptopass": "privacy-secret",
        "cryptoalgo": "AES",
    }

    local_v2, local_error = enrollment._snmp_parameters(_target(
        credential_type="",
        snmp_community="",
        asset_snmp_community="legacy-community",
    ))
    assert local_error == ""
    assert local_v2 == {"snmpver": "v2c", "community": "legacy-community"}


def test_snmp_parameters_rejects_undecryptable_community_and_unknown_v3_algorithms(monkeypatch):
    monkeypatch.setattr(enrollment, "decrypt_credential", lambda value: None if str(value).startswith("enc:v2:") else value or "")

    encrypted_community, community_error = enrollment._snmp_parameters(_target(
        snmp_community="enc:v2:corrupt-ciphertext",
    ))
    assert encrypted_community == {}
    assert community_error == "snmp_community_unavailable"

    unsupported_auth, auth_error = enrollment._snmp_parameters(_target(
        credential_type="snmpv3",
        snmp_community="",
        username="snmpv3-user",
        snmp_security_level="authNoPriv",
        snmp_auth_password="auth-secret",
        snmp_auth_protocol="made-up-auth",
    ))
    assert unsupported_auth == {}
    assert auth_error == "snmpv3_auth_algorithm_unsupported"

    unsupported_privacy, privacy_error = enrollment._snmp_parameters(_target(
        credential_type="snmpv3",
        snmp_community="",
        username="snmpv3-user",
        snmp_security_level="authPriv",
        snmp_auth_password="auth-secret",
        snmp_priv_password="privacy-secret",
        snmp_priv_protocol="made-up-privacy",
    ))
    assert unsupported_privacy == {}
    assert privacy_error == "snmpv3_priv_algorithm_unsupported"


def test_selected_but_unavailable_profile_never_falls_back_to_legacy_community(monkeypatch):
    monkeypatch.setattr(enrollment, "decrypt_credential", lambda value: value or "")
    parameters, error = enrollment._snmp_parameters(_target(
        credential_type="",
        snmp_credential_id="missing-profile-id",
        asset_snmp_community="legacy-community",
    ))

    assert parameters == {}
    assert error == "snmp_profile_unavailable"


def test_add_response_does_not_match_disabled_or_ignored_native_devices():
    assert enrollment._match_from_add_response(_instance(), {
        "status": "ok",
        "devices": [{"device_id": "42", "hostname": "192.0.2.40", "disabled": True}],
    }, "192.0.2.40") == []
    assert enrollment._match_from_add_response(_instance(), {
        "status": "ok",
        "devices": [{"device_id": "43", "hostname": "192.0.2.40", "ignore": "1"}],
    }, "192.0.2.40") == []


def test_existing_librenms_device_gets_selected_profile_before_local_binding(monkeypatch):
    calls = []
    target = _target()
    context = {"status": "ready", "id": "device-1", "asset_id": "asset-1", "tenant_id": "tenant-1"}
    monkeypatch.setattr(enrollment, "_load_asset_enrollment_context", lambda _device_id: target)
    monkeypatch.setattr(enrollment, "_load_auto_binding_context", lambda *_args: context)
    monkeypatch.setattr(enrollment, "_load_enabled_instances", lambda: [_instance()])
    monkeypatch.setattr(enrollment, "_instance_matches", lambda *_args: asyncio.sleep(0, result=[_match()]))
    monkeypatch.setattr(enrollment, "preflight_auto_binding", lambda *_args: {"status": "ready"})
    monkeypatch.setattr(enrollment, "decrypt_credential", lambda value: "api-token" if value == "encrypted-token" else value or "")
    monkeypatch.setattr(enrollment, "_audit_enrollment", lambda **_kwargs: None)

    class FakeClient:
        def __init__(self, base_url, token):
            assert base_url == "https://librenms.example"
            assert token == "api-token"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def update_device_snmp_profile(self, **kwargs):
            calls.append(("patch", kwargs))

        async def add_device(self, **kwargs):
            calls.append(("post", kwargs))

    def persist(binding_context, match):
        calls.append(("bind", binding_context, match))
        return {"status": "bound", "binding": {"id": "binding-1"}}

    monkeypatch.setattr(enrollment, "LibreNMSRuntimeClient", FakeClient)
    monkeypatch.setattr(enrollment, "_persist_auto_binding", persist)

    result = asyncio.run(enrollment.enroll_imported_network_device("device-1"))

    assert result["status"] == "profile_updated_and_bound"
    assert result["profile_applied"] is True
    assert [call[0] for call in calls] == ["patch", "bind"]
    assert calls[0][1] == {
        "native_device_id": "42",
        "snmp_parameters": {"snmpver": "v2c", "community": "private-v2-community"},
        "port": 1161,
    }
    assert calls[1][1] is context


def test_new_librenms_device_uses_ip_and_selected_profile_then_exactly_binds(monkeypatch):
    calls = []
    target = _target()
    context = {"status": "ready", "id": "device-1", "asset_id": "asset-1", "tenant_id": "tenant-1"}
    query_results = [[], [_match()]]
    monkeypatch.setattr(enrollment, "_load_asset_enrollment_context", lambda _device_id: target)
    monkeypatch.setattr(enrollment, "_load_auto_binding_context", lambda *_args: context)
    monkeypatch.setattr(enrollment, "_load_enabled_instances", lambda: [_instance()])
    monkeypatch.setattr(
        enrollment,
        "_instance_matches",
        lambda *_args: asyncio.sleep(0, result=query_results.pop(0)),
    )
    monkeypatch.setattr(enrollment, "preflight_auto_binding", lambda *_args: {"status": "ready"})
    monkeypatch.setattr(enrollment, "decrypt_credential", lambda value: "api-token" if value == "encrypted-token" else value or "")
    monkeypatch.setattr(enrollment, "_audit_enrollment", lambda **_kwargs: None)

    class FakeClient:
        def __init__(self, _base_url, _token):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def add_device(self, **kwargs):
            calls.append(("post", kwargs))
            return None

        async def update_device_snmp_profile(self, **kwargs):
            calls.append(("patch", kwargs))

    def persist(binding_context, match):
        calls.append(("bind", binding_context, match))
        return {"status": "bound", "binding": {"id": "binding-1"}}

    monkeypatch.setattr(enrollment, "LibreNMSRuntimeClient", FakeClient)
    monkeypatch.setattr(enrollment, "_persist_auto_binding", persist)

    result = asyncio.run(enrollment.enroll_imported_network_device("device-1"))

    assert result["status"] == "added_and_bound"
    assert result["profile_applied"] is True
    assert [call[0] for call in calls] == ["post", "bind"]
    assert calls[0][1] == {
        "hostname": "192.0.2.40",
        "snmp_parameters": {"snmpver": "v2c", "community": "private-v2-community"},
        "port": 1161,
    }


def test_new_device_binds_from_exact_add_response_before_port_ip_is_indexed(monkeypatch):
    calls = []
    target = _target()
    context = {"status": "ready", "id": "device-1", "asset_id": "asset-1", "tenant_id": "tenant-1"}

    async def find_matches(*_args):
        return []

    monkeypatch.setattr(enrollment, "_load_asset_enrollment_context", lambda _device_id: target)
    monkeypatch.setattr(enrollment, "_load_auto_binding_context", lambda *_args: context)
    monkeypatch.setattr(enrollment, "_load_enabled_instances", lambda: [_instance()])
    monkeypatch.setattr(enrollment, "_instance_matches", find_matches)
    monkeypatch.setattr(enrollment, "preflight_auto_binding", lambda *_args: {"status": "ready"})
    monkeypatch.setattr(enrollment, "decrypt_credential", lambda value: "api-token" if value == "encrypted-token" else value or "")
    monkeypatch.setattr(enrollment, "_audit_enrollment", lambda **_kwargs: None)

    class FakeClient:
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def add_device(self, **kwargs):
            calls.append(("post", kwargs))
            return {
                "status": "ok",
                "devices": [{"device_id": "77", "hostname": "192.0.2.40"}],
            }

    def persist(binding_context, match):
        calls.append(("bind", binding_context, match))
        return {"status": "bound", "binding": {"id": "binding-77"}}

    monkeypatch.setattr(enrollment, "LibreNMSRuntimeClient", FakeClient)
    monkeypatch.setattr(enrollment, "_persist_auto_binding", persist)

    result = asyncio.run(enrollment.enroll_imported_network_device("device-1"))

    assert result["status"] == "added_and_bound"
    assert [call[0] for call in calls] == ["post", "bind"]
    assert calls[1][2]["native_device_id"] == "77"
    assert calls[1][2]["native_hostname"] == "192.0.2.40"


def test_exact_successful_add_response_can_bind_when_followup_lookup_is_unavailable(monkeypatch):
    calls = []
    target = _target()
    context = {"status": "ready", "id": "device-1", "asset_id": "asset-1", "tenant_id": "tenant-1"}
    query_count = 0

    async def find_matches(*_args):
        nonlocal query_count
        query_count += 1
        if query_count == 1:
            return []
        raise LibreNMSAPIError("timeout")

    monkeypatch.setattr(enrollment, "_load_asset_enrollment_context", lambda _device_id: target)
    monkeypatch.setattr(enrollment, "_load_auto_binding_context", lambda *_args: context)
    monkeypatch.setattr(enrollment, "_load_enabled_instances", lambda: [_instance()])
    monkeypatch.setattr(enrollment, "_instance_matches", find_matches)
    monkeypatch.setattr(enrollment, "preflight_auto_binding", lambda *_args: {"status": "ready"})
    monkeypatch.setattr(enrollment, "decrypt_credential", lambda value: "api-token" if value == "encrypted-token" else value or "")
    monkeypatch.setattr(enrollment, "_audit_enrollment", lambda **_kwargs: None)

    class FakeClient:
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def add_device(self, **kwargs):
            calls.append(("post", kwargs))
            return {
                "status": "ok",
                "devices": [{"device_id": "78", "hostname": "192.0.2.40"}],
            }

    monkeypatch.setattr(enrollment, "LibreNMSRuntimeClient", FakeClient)
    monkeypatch.setattr(
        enrollment,
        "_persist_auto_binding",
        lambda binding_context, match: calls.append(("bind", binding_context, match)) or {
            "status": "bound", "binding": {"id": "binding-78"},
        },
    )

    result = asyncio.run(enrollment.enroll_imported_network_device("device-1"))

    assert result["status"] == "added_and_bound"
    assert [call[0] for call in calls] == ["post", "bind"]
    assert calls[1][2]["native_device_id"] == "78"


def test_timed_out_add_without_readback_is_reported_as_uncertain_without_binding(monkeypatch):
    target = _target()
    context = {"status": "ready", "id": "device-1", "asset_id": "asset-1", "tenant_id": "tenant-1"}
    query_results = [[], []]
    persisted = []
    monkeypatch.setattr(enrollment, "_load_asset_enrollment_context", lambda _device_id: target)
    monkeypatch.setattr(enrollment, "_load_auto_binding_context", lambda *_args: context)
    monkeypatch.setattr(enrollment, "_load_enabled_instances", lambda: [_instance()])
    monkeypatch.setattr(
        enrollment,
        "_instance_matches",
        lambda *_args: asyncio.sleep(0, result=query_results.pop(0)),
    )
    monkeypatch.setattr(enrollment, "decrypt_credential", lambda value: "api-token" if value == "encrypted-token" else value or "")
    monkeypatch.setattr(enrollment, "_audit_enrollment", lambda **_kwargs: None)

    class FakeClient:
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def add_device(self, **_kwargs):
            raise LibreNMSAPIError("timeout")

    monkeypatch.setattr(enrollment, "LibreNMSRuntimeClient", FakeClient)
    monkeypatch.setattr(enrollment, "_persist_auto_binding", lambda *_args: persisted.append(True))

    result = asyncio.run(enrollment.enroll_imported_network_device("device-1"))

    assert result["status"] == "address_unverified"
    assert not persisted


def test_definite_add_rejection_is_not_converted_to_success_by_later_address_match(monkeypatch):
    target = _target()
    context = {"status": "ready", "id": "device-1", "asset_id": "asset-1", "tenant_id": "tenant-1"}
    query_results = [[], [_match()]]
    profile_updates = []
    persisted = []
    monkeypatch.setattr(enrollment, "_load_asset_enrollment_context", lambda _device_id: target)
    monkeypatch.setattr(enrollment, "_load_auto_binding_context", lambda *_args: context)
    monkeypatch.setattr(enrollment, "_load_enabled_instances", lambda: [_instance()])
    monkeypatch.setattr(
        enrollment,
        "_instance_matches",
        lambda *_args: asyncio.sleep(0, result=query_results.pop(0)),
    )
    monkeypatch.setattr(enrollment, "preflight_auto_binding", lambda *_args: {"status": "ready"})
    monkeypatch.setattr(enrollment, "decrypt_credential", lambda value: "api-token" if value == "encrypted-token" else value or "")
    monkeypatch.setattr(enrollment, "_audit_enrollment", lambda **_kwargs: None)

    class FakeClient:
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def add_device(self, **_kwargs):
            raise LibreNMSAPIError("upstream_error", http_status=400)

        async def update_device_snmp_profile(self, **kwargs):
            profile_updates.append(kwargs)

    monkeypatch.setattr(enrollment, "LibreNMSRuntimeClient", FakeClient)
    monkeypatch.setattr(enrollment, "_persist_auto_binding", lambda *_args: persisted.append(True))

    result = asyncio.run(enrollment.enroll_imported_network_device("device-1"))

    assert result["status"] == "remote_rejected"
    assert profile_updates == []
    assert persisted == []


def test_profile_field_update_retries_idempotently_after_timeout():
    class FlakyClient:
        calls = 0

        async def update_device_snmp_profile(self, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                raise LibreNMSAPIError("timeout")

    client = FlakyClient()
    asyncio.run(enrollment._apply_profile_with_retry(
        client,
        native_device_id="42",
        snmp_parameters={"snmpver": "v2c", "community": "test-community"},
        port=161,
    ))

    assert client.calls == 2


def test_existing_device_is_not_bound_if_librenms_profile_update_fails(monkeypatch):
    target = _target()
    context = {"status": "ready", "id": "device-1", "asset_id": "asset-1", "tenant_id": "tenant-1"}
    monkeypatch.setattr(enrollment, "_load_asset_enrollment_context", lambda _device_id: target)
    monkeypatch.setattr(enrollment, "_load_auto_binding_context", lambda *_args: context)
    monkeypatch.setattr(enrollment, "_load_enabled_instances", lambda: [_instance()])
    monkeypatch.setattr(enrollment, "_instance_matches", lambda *_args: asyncio.sleep(0, result=[_match()]))
    monkeypatch.setattr(enrollment, "preflight_auto_binding", lambda *_args: {"status": "ready"})
    monkeypatch.setattr(enrollment, "decrypt_credential", lambda value: "api-token" if value == "encrypted-token" else value or "")
    monkeypatch.setattr(enrollment, "_audit_enrollment", lambda **_kwargs: None)
    persisted = []

    class FakeClient:
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def update_device_snmp_profile(self, **_kwargs):
            raise LibreNMSAPIError("forbidden", http_status=403)

    monkeypatch.setattr(enrollment, "LibreNMSRuntimeClient", FakeClient)
    monkeypatch.setattr(enrollment, "_persist_auto_binding", lambda *_args: persisted.append(True))

    result = asyncio.run(enrollment.enroll_imported_network_device("device-1"))

    assert result["status"] == "profile_update_permission_denied"
    assert not persisted


def test_existing_device_binding_conflict_stops_before_remote_profile_update(monkeypatch):
    target = _target()
    context = {"status": "ready", "id": "device-1", "asset_id": "asset-1", "tenant_id": "tenant-1"}
    monkeypatch.setattr(enrollment, "_load_asset_enrollment_context", lambda _device_id: target)
    monkeypatch.setattr(enrollment, "_load_auto_binding_context", lambda *_args: context)
    monkeypatch.setattr(enrollment, "_load_enabled_instances", lambda: [_instance()])
    monkeypatch.setattr(enrollment, "_instance_matches", lambda *_args: asyncio.sleep(0, result=[_match()]))
    monkeypatch.setattr(enrollment, "preflight_auto_binding", lambda *_args: {"status": "conflict"})
    monkeypatch.setattr(enrollment, "decrypt_credential", lambda value: "api-token" if value == "encrypted-token" else value or "")
    monkeypatch.setattr(enrollment, "_audit_enrollment", lambda **_kwargs: None)
    remote_updates = []

    class FakeClient:
        def __init__(self, *_args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def update_device_snmp_profile(self, **kwargs):
            remote_updates.append(kwargs)

    monkeypatch.setattr(enrollment, "LibreNMSRuntimeClient", FakeClient)
    result = asyncio.run(enrollment.enroll_imported_network_device("device-1"))

    assert result["status"] == "conflict"
    assert remote_updates == []


def test_snmpv3_context_name_is_reported_as_unsupported_by_add_device_api(monkeypatch):
    monkeypatch.setattr(enrollment, "decrypt_credential", lambda value: value or "")
    params, error = enrollment._snmp_parameters(_target(
        credential_type="snmpv3",
        snmp_community="",
        username="snmpv3-user",
        snmp_security_level="noAuthNoPriv",
        snmp_context_name="vlan-10",
    ))
    assert params == {}
    assert error == "snmpv3_context_unsupported"
