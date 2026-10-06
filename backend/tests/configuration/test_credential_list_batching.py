from __future__ import annotations

import database
from services import credential_service


class _RecordingConnection:
    """Count service SQL while delegating to the real isolated PostgreSQL connection."""

    def __init__(self, connection):
        self._connection = connection
        self.statements: list[str] = []

    def execute(self, statement, params=None):
        self.statements.append(statement)
        return self._connection.execute(statement, params)

    def __getattr__(self, name):
        return getattr(self._connection, name)


def _insert_credential(connection, credential_id: str, name: str, username: str) -> None:
    connection.execute(
        """INSERT INTO credentials
           (id, credential_name, credential_type, username, account_role,
            encrypted_password, created_at)
           VALUES (?, ?, 'ssh_password', ?, 'unbound', ?, '2026-10-06T00:00:00+08:00')""",
        (credential_id, name, username, "test-only-credential-secret"),
    )


def _insert_device(
    connection,
    *,
    device_id: str,
    hostname: str,
    credential_id: str = "",
    admin_credential_id: str = "",
    normal_username: str = "",
    admin_username: str = "",
    auth_model: str = "single",
) -> None:
    connection.execute(
        """INSERT INTO devices
           (id, hostname, ip_address, username, password, normal_username,
            admin_username, auth_model, credential_id, admin_credential_id)
           VALUES (?, ?, ?, 'device-global-user', ?, ?, ?, ?, ?, ?)""",
        (
            device_id,
            hostname,
            "192.0.2.250",
            "test-only-device-secret",
            normal_username,
            admin_username,
            auth_model,
            credential_id,
            admin_credential_id,
        ),
    )


def test_list_credentials_batches_associations_and_preserves_safe_role_preview(isolated_db) -> None:
    connection = database.get_db_connection()
    try:
        empty_connection = _RecordingConnection(connection)
        assert credential_service.list_credentials(empty_connection) == []
        assert len(empty_connection.statements) == 1

        _insert_credential(connection, "cred-many", "A many", "legacy-normal")
        _insert_credential(connection, "cred-admin", "B admin", "legacy-admin")
        _insert_credential(connection, "cred-shared", "C shared", "legacy-shared")
        _insert_credential(connection, "cred-mixed", "D mixed", "legacy-mixed")
        _insert_credential(connection, "cred-empty", "E empty", "unused")

        for number in range(6):
            _insert_device(
                connection,
                device_id=f"dev-many-{number}",
                hostname=f"many-{number:02d}",
                credential_id="cred-many",
                normal_username="operator",
                auth_model="dual",
            )
        _insert_device(
            connection,
            device_id="dev-admin-1",
            hostname="admin-only",
            admin_credential_id="cred-admin",
            admin_username="root",
            auth_model="dual",
        )
        _insert_device(
            connection,
            device_id="dev-shared-1",
            hostname="both-slots",
            credential_id="cred-shared",
            admin_credential_id="cred-shared",
            normal_username="operator",
            admin_username="admin",
            auth_model="dual",
        )
        _insert_device(
            connection,
            device_id="dev-mixed-1",
            hostname="mixed-a-normal",
            credential_id="cred-mixed",
            normal_username="operator",
            auth_model="dual",
        )
        _insert_device(
            connection,
            device_id="dev-mixed-2",
            hostname="mixed-b-admin",
            admin_credential_id="cred-mixed",
            admin_username="root",
            auth_model="dual",
        )
        _insert_device(
            connection,
            device_id="dev-unrelated-1",
            hostname="unrelated-host",
            credential_id="cred-unrelated",
        )
        connection.commit()

        recorded_connection = _RecordingConnection(connection)
        credentials = credential_service.list_credentials(recorded_connection)

        assert len(recorded_connection.statements) == 2
        assert "FROM credentials" in recorded_connection.statements[0]
        device_query = recorded_connection.statements[1]
        assert "FROM devices" in device_query
        assert "ANY(?)" in device_query
        assert "normal_username" in device_query
        assert "admin_username" in device_query
        assert "auth_model" in device_query
        assert "password" not in device_query.lower()

        by_id = {item["id"]: item for item in credentials}
        assert [item["credential_name"] for item in credentials] == [
            "A many",
            "B admin",
            "C shared",
            "D mixed",
            "E empty",
        ]

        many = by_id["cred-many"]
        assert many["device_count"] == 6
        assert many["devices_truncated"] is True
        assert [item["hostname"] for item in many["devices"]] == [
            "many-00",
            "many-01",
            "many-02",
            "many-03",
            "many-04",
        ]
        assert {item["binding_role"] for item in many["devices"]} == {"normal"}
        assert many["account_role"] == "normal"
        assert many["username"] == "operator"

        admin = by_id["cred-admin"]
        assert admin["device_count"] == 1
        assert admin["devices"][0]["hostname"] == "admin-only"
        assert admin["devices"][0]["binding_role"] == "admin"
        assert admin["account_role"] == "admin"
        assert admin["username"] == "root"

        shared = by_id["cred-shared"]
        assert shared["device_count"] == 1
        assert shared["devices"] == [
            {
                "id": "dev-shared-1",
                "hostname": "both-slots",
                "ip_address": "192.0.2.250",
                "binding_role": "admin",
            }
        ]
        assert shared["account_role"] == "admin"
        assert shared["username"] == "admin"

        mixed = by_id["cred-mixed"]
        assert mixed["device_count"] == 2
        assert [item["hostname"] for item in mixed["devices"]] == [
            "mixed-a-normal",
            "mixed-b-admin",
        ]
        assert mixed["account_role"] == "mixed"

        empty = by_id["cred-empty"]
        assert empty["device_count"] == 0
        assert empty["devices"] == []
        assert empty["devices_truncated"] is False
        assert empty["account_role"] == "unbound"

        serialized = repr(credentials)
        assert "unrelated-host" not in serialized
        assert "test-only-credential-secret" not in serialized
        assert "test-only-device-secret" not in serialized
        assert all("password" not in item for item in credentials)
    finally:
        connection.close()
