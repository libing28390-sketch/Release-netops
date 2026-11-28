from core.textfsm import template_action_code
from services.operational_data_service import (
    parse_device_cli_output,
    resolve_device_platform_context,
    resolve_textfsm_template_for_command,
)


BFD_OUTPUT = """--- S6850_1 ---
[display bfd session]
 Total sessions: 1     Up sessions: 0     Init mode: Active

 IPv4 session working in control packet mode:

 LD/RD            SourceAddr      DestAddr        State  Holdtime    Interface
 32833/0          10.254.12.1     10.254.12.2     Down      /        Vlan112
"""


def _h3c_device(profile_code: str) -> dict[str, str]:
    return {
        'id': f'device-{profile_code}',
        'platform': 'h3c_comware',
        'vendor': 'h3c',
        'profile_platform_code': profile_code,
        'profile_parser_platform': 'h3c_comware',
        'profile_connection_driver': 'hp_comware',
    }


def test_h3c_profiles_share_hp_comware_transport_but_select_concrete_parser_namespace():
    expected = {
        'h3c_comware_v3': 'h3c_comware_v3',
        'hp_comware': 'h3c_comware_v5',
        'h3c_comware': 'h3c_comware_v7',
        'h3c_comware9': 'h3c_comware_v9',
    }

    for profile_code, parser_platform in expected.items():
        context = resolve_device_platform_context(_h3c_device(profile_code))
        assert context['connection_driver'] == 'hp_comware'
        assert context['public_platform'] == 'h3c_comware'
        assert context['parser_platform'] == parser_platform


def test_bound_ruijie_profile_version_overrides_stale_inventory_software_version():
    cases = (
        ('ruijie_eg_rgos11', '12.5(1)', 'ruijie_rgos_v11'),
        ('ruijie_s6k_rgos12', '11.9(6)B13P1', 'ruijie_rgos_v12'),
    )

    for profile_code, stale_version, expected_parser in cases:
        context = resolve_device_platform_context({
            'id': f'device-{profile_code}',
            'platform': 'ruijie_rgos',
            'vendor': 'Ruijie',
            'version': stale_version,
            'profile_platform_code': profile_code,
            'profile_parser_platform': 'ruijie_rgos',
            'profile_connection_driver': 'ruijie_os',
        })

        assert context['parser_platform'] == expected_parser


def test_bound_maipu_s3330_profile_uses_declared_v9_parser_with_stale_inventory_version():
    context = resolve_device_platform_context({
        'id': 'device-maipu-s3330',
        'platform': 'maipu',
        'vendor': 'Maipu',
        'version': '8.3.0',
        'profile_platform_code': 'maipu_s3330_v9',
        'profile_parser_platform': 'maipu',
        'profile_connection_driver': 'maipu',
    })

    assert context['parser_platform'] == 'maipu_mypower_v9'


def test_bound_generic_huawei_vrp_profile_uses_its_declared_v5_variant():
    context = resolve_device_platform_context({
        'id': 'device-huawei-vrp-v5',
        'platform': 'huawei_vrp',
        'vendor': 'Huawei',
        'version': '8.180',
        'profile_platform_code': 'huawei_vrp',
        'profile_parser_platform': 'huawei_vrp',
        'profile_connection_driver': 'huawei_vrp',
    })

    assert context['parser_platform'] == 'huawei_vrp5'


def test_huawei_legacy_ntc_filename_alias_is_cataloged_only_for_vrp_v5():
    from core.textfsm import list_templates

    templates = list_templates(vendor_filter='huawei')
    command = 'display arp'
    v5 = {
        'platform': 'huawei_vrp',
        'vendor': 'Huawei',
        'profile_platform_code': 'huawei_vrp5',
        'profile_parser_platform': 'huawei_vrp',
        'profile_connection_driver': 'huawei_vrp',
    }
    unknown = {
        'platform': 'huawei_vrp',
        'vendor': 'Huawei',
        'profile_platform_code': 'huawei_vrp_unknown',
        'profile_parser_platform': 'huawei_vrp',
        'profile_connection_driver': 'huawei_vrp',
    }

    match = resolve_textfsm_template_for_command(
        v5, command, action_code='get_arp_table', templates_catalog=templates,
    )
    assert match is not None
    assert match['textfsm_template'] == 'huawei_vrp5_display_arp_all.textfsm'
    assert resolve_textfsm_template_for_command(
        unknown, command, action_code='get_arp_table', templates_catalog=templates,
    ) is None


def test_unbound_ruijie_device_still_uses_detected_software_version():
    context = resolve_device_platform_context({
        'id': 'unbound-ruijie-v11',
        'platform': 'ruijie_rgos',
        'vendor': 'Ruijie',
        'version': '11.9(6)B13P1',
    })

    assert context['parser_platform'] == 'ruijie_rgos_v11'


def test_unversioned_ruijie_parser_never_selects_a_release_specific_namespace():
    from core.textfsm import _template_platform_candidates

    assert _template_platform_candidates('ruijie_rgos') == ['ruijie_rgos']
    assert _template_platform_candidates('ruijie_rgos_unknown') == [
        'ruijie_rgos_unknown',
        'ruijie_rgos',
    ]


def test_ruijie_unknown_version_official_sample_uses_unknown_scoped_template():
    from pathlib import Path
    from core.textfsm import smart_parse_cli

    fixture = Path(__file__).resolve().parents[1] / 'fixtures' / 'cli' / 'ruijie' / 'ruijie_rgos' / 'show_ip_interface_brief' / 'rgos_rsr.txt'
    output = fixture.read_text(encoding='utf-8')
    result = smart_parse_cli(output, 'show ip interface brief', platform='ruijie_rgos_unknown')

    assert result['success'] is True
    assert result['template'] == 'ruijie_rgos_unknown_show_ip_interface_brief.textfsm'
    assert result['data'] == [{
        'INTERFACE': 'Async 1',
        'IP_ADDRESS_PRI': '10.10.0.2',
        'IP_ADDRESS_SEC': 'no address',
        'STATUS': 'up',
        'PROTOCOL': 'up',
    }]


def test_v7_action_command_uses_exact_template_without_registry_binding():
    result = parse_device_cli_output(
        _h3c_device('h3c_comware'),
        'display bfd session',
        BFD_OUTPUT,
    )

    assert result['parse_status'] == 'matched'
    assert result['parser_platform'] == 'h3c_comware_v7'
    assert result['template'] == 'h3c_comware_v7_display_bfd_session.textfsm'
    assert result['records'][0]['interface'] == 'Vlan112'


def test_action_metadata_is_optional_and_is_not_required_for_parsing():
    assert template_action_code('Value PORT (\\S+)\n\nStart\n  ^Port: ${PORT} -> Record\n') == ''
    assert template_action_code('# nexora-action-code: get_bfd_sessions\nValue PORT (\\S+)') == 'get_bfd_sessions'


# Adapted from the H3C MSR 50-06 command reference, sections 1.1.8 and 1.1.12.
# https://www.h3c.com/cn/d_200809/615821_30005_0.htm
def test_comware_v3_msr_version_uses_the_v3_template():
    output = (
        "<H3C> display version\n"
        "H3C Comware Software\n"
        "Comware software, Version 3.40, Beta 6113\n"
        "H3C MSR50-06 uptime is 0 week, 1 day, 2 hours, 3 minutes\n"
        " BootROM Version:15.05\n"
    )
    result = parse_device_cli_output(_h3c_device('h3c_comware_v3'), 'display version', output)

    assert result['template'] == 'h3c_comware_v3_display_version.textfsm'
    assert result['parse_status'] == 'matched'
    assert result['count'] == 1
    assert result['records'][0]['software_version'] == '3.40'
    assert result['records'][0]['device'] == 'MSR50-06'


def test_comware_v3_msr_cpu_reads_system_usage_only():
    output = (
        "[H3C] display cpu-usage\n"
        "CPU Usage Stat. Cycle: 1 (Second)\n"
        "CPU Usage            : 1%\n"
        "TaskName        CPU        Runtime\n"
        "VIDL            99%        0/ 12345\n"
    )
    result = parse_device_cli_output(_h3c_device('h3c_comware_v3'), 'display cpu-usage', output)

    assert result['template'] == 'h3c_comware_v3_display_cpu_usage.textfsm'
    assert result['parse_status'] == 'matched'
    assert result['records'] == [{'usage': '1%'}]
