from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from openpyxl import load_workbook

from api import assets
from core.crypto import encrypt_credential
from database import get_db_connection


def _insert_credential(credential_id: str, name: str, credential_type: str, community: str = "") -> None:
    with get_db_connection() as conn:
        conn.execute(
            """INSERT INTO credentials (
                   id, credential_name, credential_type, snmp_community, created_at
               ) VALUES (?, ?, ?, ?, ?)""",
            (
                credential_id,
                name,
                credential_type,
                encrypt_credential(community) if community else "",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def test_asset_import_template_lists_only_current_snmpv2_names(isolated_db):
    _insert_credential("cred-template-v2", "template-snmp-v2", "snmpv2", "test-community")
    _insert_credential("cred-template-v2-formula", "=1+1", "snmpv2", "test-community")
    _insert_credential("cred-template-v2-empty", "template-snmp-v2-empty", "snmpv2")
    _insert_credential("cred-template-v3", "template-snmp-v3", "snmpv3")
    _insert_credential("cred-template-ssh", "template-ssh-only", "ssh_password")

    response = assets.download_asset_import_template(_user={"role": "Operator"})

    assert response.media_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert response.headers["Cache-Control"] == "no-store"
    workbook = load_workbook(BytesIO(response.body), data_only=False)
    assert workbook.sheetnames[:6] == ["填写说明", "网络设备", "服务器", "管理入口", "参数可选值参考", "下拉选项"]

    network = workbook["网络设备"]
    helper = workbook["_SNMPv2Credentials"]
    assert helper.sheet_state == "hidden"
    names = [helper.cell(row=row, column=1).value for row in range(2, helper.max_row + 1)]
    assert names == sorted(names, key=str.casefold)
    assert "template-snmp-v2" in names
    assert "template-snmp-v2-empty" not in names
    assert "template-snmp-v3" not in names
    assert "template-ssh-only" not in names

    formula_name = next(cell for cell in helper['A'] if cell.value == "=1+1")
    assert formula_name.data_type == "s"
    assert workbook.defined_names["SNMPv2CredentialNames"].attr_text == (
        f"'_SNMPv2Credentials'!$A$2:$A${helper.max_row}"
    )
    validations = network.data_validations.dataValidation
    snmp_validation = next(validation for validation in validations if "AB2:AB2000" in str(validation.sqref))
    assert snmp_validation.formula1 == "=SNMPv2CredentialNames"
    assert snmp_validation.allow_blank is True
    assert snmp_validation.showErrorMessage is True


def test_asset_import_template_without_snmpv2_credentials_keeps_optional_column(isolated_db):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM credentials WHERE LOWER(COALESCE(credential_type, '')) = 'snmpv2'")
        conn.commit()

    response = assets.download_asset_import_template(_user={"role": "Operator"})
    workbook = load_workbook(BytesIO(response.body), data_only=False)

    assert "_SNMPv2Credentials" not in workbook.sheetnames
    assert "SNMPv2CredentialNames" not in workbook.defined_names
    network = workbook["网络设备"]
    assert network["AB1"].value == "SNMPv2凭据名称（选填）"
    assert not any("AB2:AB2000" in str(validation.sqref) for validation in network.data_validations.dataValidation)
