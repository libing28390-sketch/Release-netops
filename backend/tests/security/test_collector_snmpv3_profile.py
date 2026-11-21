from __future__ import annotations

import database.core as database_core
from services import vault_service


def test_collector_credentials_resolve_bound_snmpv3_profile(monkeypatch) -> None:
    credential_row = {
        "id": "credential-v3",
        "credential_type": "snmpv3",
        "username": "poller-user",
        "snmp_server": "192.0.2.30",
        "snmp_community": "",
        "snmp_security_level": "authPriv",
        "snmp_auth_protocol": "SHA-256",
        "snmp_auth_password": "encrypted-auth",
        "snmp_priv_protocol": "AES",
        "snmp_priv_password": "encrypted-privacy",
        "snmp_context_name": "tenant-a",
    }

    class Result:
        def fetchone(self):
            return credential_row

    class Connection:
        def execute(self, sql, _params=()):
            if "SELECT * FROM credentials" in sql:
                return Result()
            raise AssertionError(f"Unexpected query: {sql}")

        def close(self):
            pass

    monkeypatch.setattr(database_core, "get_db_connection", lambda: Connection())
    monkeypatch.setattr(
        "core.crypto.decrypt_credential",
        lambda value: {
            "encrypted-auth": "synthetic-auth-key",
            "encrypted-privacy": "synthetic-privacy-key",
        }.get(value, ""),
    )

    resolved = vault_service.resolve_collector_credentials({
        "id": "device-v3",
        "ip_address": "192.0.2.30",
        "snmp_credential_id": "credential-v3",
    })

    assert resolved["snmp"] == {
        "version": "3",
        "server": "192.0.2.30",
        "community": "",
        "port": 161,
        "credential_type": "snmpv3",
        "username": "poller-user",
        "security_level": "authPriv",
        "auth_protocol": "SHA-256",
        "auth_password": "synthetic-auth-key",
        "priv_protocol": "AES",
        "priv_password": "synthetic-privacy-key",
        "context_name": "tenant-a",
        "configured": True,
        "configuration_error": "",
    }
