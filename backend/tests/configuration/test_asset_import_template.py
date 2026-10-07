from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from openpyxl import load_workbook

from api import assets
from core.crypto import encrypt_credential
from database import get_db_connection


def _insert_credential(
    credential_id: str,
    name: str,
    credential_type: str,
    community: str = "",
    *,
    username: str = "",
    security_level: str = "authPriv",
    auth_protocol: str = "SHA",
    auth_password: str = "",
    priv_protocol: str = "AES",
    priv_password: str = "",
) -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO credentials (
                   id, credential_name, credential_type, username, snmp_community,
                   snmp_security_level, snmp_auth_protocol, snmp_auth_password,
                   snmp_priv_protocol, snmp_priv_password, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                credential_id,
                name,
                credential_type,
                username,
                encrypt_credential(community) if community else "",
                security_level,
                auth_protocol,
                encrypt_credential(auth_password) if auth_password else "",
                priv_protocol,
                encrypt_credential(priv_password) if priv_password else "",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def test_asset_import_template_lists_complete_snmpv2_and_snmpv3_profiles(isolated_db):
    _insert_credential("cred-template-v2", "template-snmp-v2", "snmpv2", "test-community")
    _insert_credential("cred-template-v2-formula", "=1+1", "snmpv2", "test-community")
    _insert_credential("cred-template-v2-empty", "template-snmp-v2-empty", "snmpv2")
    _insert_credential(
        "cred-template-v3", "template-snmp-v3", "snmpv3",
        username="snmp-user", security_level="authPriv", auth_password="auth-secret", priv_password="priv-secret",
    )
    _insert_credential(
        "cred-template-v3-incomplete", "template-snmp-v3-incomplete", "snmpv3",
        username="snmp-user", security_level="authPriv", auth_password="auth-secret",
    )
    _insert_credential(
        "cred-template-v3-bad-algorithm", "template-snmp-v3-bad-algorithm", "snmpv3",
        username="snmp-user", security_level="authPriv", auth_protocol="SHA-1024",
        auth_password="auth-secret", priv_password="priv-secret",
    )
    _insert_credential("cred-template-ssh", "template-ssh-only", "ssh_password")

    response = assets.download_asset_import_template(_user={"role": "Operator"})

    assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert response.headers["Cache-Control"] == "no-store"
    workbook = load_workbook(BytesIO(response.body), data_only=False)
    assert workbook.sheetnames[:6] == ["填写说明", "网络设备", "服务器", "管理入口", "参数可选值参考", "下拉选项"]

    network = workbook["网络设备"]
    helper = workbook["_SNMPCredentials"]
    assert helper.sheet_state == "hidden"
    names = [helper.cell(row=row, column=1).value for row in range(2, helper.max_row + 1)]
    assert names == sorted(names, key=str.casefold)
    assert "template-snmp-v2" in names
    assert "template-snmp-v2-empty" not in names
    assert "template-snmp-v3" in names
    assert "template-snmp-v3-incomplete" not in names
    assert "template-snmp-v3-bad-algorithm" not in names
    assert "template-ssh-only" not in names

    formula_name = next(cell for cell in helper['A'] if cell.value == "=1+1")
    assert formula_name.data_type == "s"
    assert workbook.defined_names["SNMPCredentialNames"].attr_text == (
        f"'_SNMPCredentials'!$A$2:$A${helper.max_row}"
    )
    validations = network.data_validations.dataValidation
    snmp_validation = next(validation for validation in validations if "AB2:AB2000" in str(validation.sqref))
    assert snmp_validation.formula1 == "=SNMPCredentialNames"
    assert snmp_validation.allow_blank is True
    assert snmp_validation.showErrorMessage is True


def test_asset_import_template_without_snmp_profiles_keeps_optional_column(isolated_db):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM credentials WHERE LOWER(COALESCE(credential_type, '')) IN ('snmpv2', 'snmpv3')")
        conn.commit()

    response = assets.download_asset_import_template(_user={"role": "Operator"})
    workbook = load_workbook(BytesIO(response.body), data_only=False)

    assert "_SNMPCredentials" not in workbook.sheetnames
    assert "SNMPCredentialNames" not in workbook.defined_names
    network = workbook["网络设备"]
    assert network["AB1"].value == "SNMP凭据名称（选填）"
    assert not any("AB2:AB2000" in str(validation.sqref) for validation in network.data_validations.dataValidation)
