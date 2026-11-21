from __future__ import annotations

import logging

from services.operational_data_service import parse_device_cli_output


RUIJIE_V12_LLDP_BRIEF = """
show lldp neighbors
Capability codes:
    R - Router, T - Trans Bridge, B - Source Route Bridge
Device ID        Local Intf      Hold-time  Capability      Port ID
SW-CORE          Gi0/1           120        R               Gi0/24
"""


def test_ruijie_v12_parser_log_reports_selected_template(caplog) -> None:
    caplog.set_level(logging.INFO, logger='services.operational_data_service')

    result = parse_device_cli_output(
        {
            'id': 'ruijie-log-device',
            'vendor': 'Ruijie',
            'platform': 'ruijie_rgos',
            'profile_platform_code': 'ruijie_rgos_v12',
            'profile_parser_platform': 'ruijie_rgos',
            'profile_connection_driver': 'ruijie_os',
            'parser_template_version_id': 'db-template-version-1',
        },
        'show lldp neighbors',
        RUIJIE_V12_LLDP_BRIEF,
    )

    assert result['parser'] == 'textfsm:ruijie_rgos_v12_show_lldp_neighbors.textfsm'
    assert result['template_source'] == 'custom'
    assert result['parser_platform'] == 'ruijie_rgos_v12'
    assert result['parse_status'] == 'matched'
    assert result['count'] == 1
    assert 'event=parser_start' in caplog.text
    assert 'parser_platform=ruijie_rgos_v12' in caplog.text
    assert 'parser_template_version_id=db-template-version-1' in caplog.text
    assert 'event=parser_result' in caplog.text
    assert 'template=ruijie_rgos_v12_show_lldp_neighbors.textfsm' in caplog.text
    assert 'template_source=custom' in caplog.text
    assert 'parse_status=matched' in caplog.text
