from core.textfsm import template_action_code
from services.operational_data_service import (
    parse_device_cli_output,
    resolve_device_platform_context,
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
