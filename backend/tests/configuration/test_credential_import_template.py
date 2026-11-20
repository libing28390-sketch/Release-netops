from __future__ import annotations

import io
import openpyxl

from api.credentials import (
    CREDENTIAL_TEMPLATE_VERSION,
    _build_credential_import_template,
    api_download_credential_import_template,
)


def test_credential_import_template_keeps_headers_visible_in_excel() -> None:
    content = _build_credential_import_template()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    try:
        assert wb.sheetnames == ["SSH", "SNMP"]

        ws_ssh = wb["SSH"]
        ssh_headers = [cell.value for cell in ws_ssh[1]]
        assert ssh_headers == [
            "凭据名称", "类型", "用户名", "账号角色", "密码", "Enable 密码",
        ]

        ws_snmp = wb["SNMP"]
        snmp_headers = [cell.value for cell in ws_snmp[1]]
        assert snmp_headers == [
            "凭据名称", "类型", "SNMP 团体字", "SNMP 服务器地址",
        ]

        for ws in (ws_ssh, ws_snmp):
            cell = ws["A1"]
            assert cell.fill.fill_type == "solid"
            assert cell.fill.fgColor.rgb == "FF007D9D"
            assert cell.font.bold is True
            assert cell.font.color.rgb == "FFFFFFFF"
            assert ws.freeze_panes == "A2"
    finally:
        wb.close()


def test_credential_template_download_advertises_current_format() -> None:
    response = api_download_credential_import_template(None)

    assert response.headers["X-Credential-Template-Version"] == CREDENTIAL_TEMPLATE_VERSION
    assert response.headers["Cache-Control"] == "no-store"

