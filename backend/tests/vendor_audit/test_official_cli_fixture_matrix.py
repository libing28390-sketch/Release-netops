from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.textfsm import smart_parse_cli  # noqa: E402

FIXTURE_ROOT = BACKEND_ROOT / 'tests' / 'fixtures' / 'cli'
METADATA_FILES = sorted(FIXTURE_ROOT.rglob('*.meta.json'))
REQUIRED_METADATA_FIELDS = (
    'source_type',
    'source_url',
    'vendor',
    'platform',
    'command',
    'source_title',
    'source_section',
    'source_note',
    'model_family',
    'parser_platform',
    'platform_version',
    'software_version',
    'expected_record_count',
    'expected_fields',
    'expected_template',
)


def _parser_platform(metadata_path: Path, metadata: dict[str, object]) -> str:
    parser_platform = str(metadata.get('parser_platform') or '').strip()
    assert parser_platform, f'{metadata_path.name} has no explicit parser_platform'
    return parser_platform


def test_junos_spanning_tree_preserves_scope_across_mixed_sections():
    fixtures = FIXTURE_ROOT / "juniper/juniper_junos/show_spanning_tree_interface"
    instance = (fixtures / "ex_series.txt").read_text(encoding="utf-8")
    vlan = (fixtures / "vstp_vlan10.txt").read_text(encoding="utf-8")
    result = smart_parse_cli(
        "\n".join((instance, vlan, vlan.replace("VLAN 10", "VLAN 20"))),
        "show spanning-tree interface",
        platform="juniper_junos",
    )

    assert result["success"] is True
    assert [(row["INSTANCE_TYPE"], row["INSTANCE"]) for row in result["data"]] == [
        ("instance", "2"), ("instance", "2"),
        ("VLAN", "10"), ("VLAN", "10"),
        ("VLAN", "20"), ("VLAN", "20"),
    ]


@pytest.mark.parametrize('metadata_path', METADATA_FILES, ids=lambda path: str(path.relative_to(FIXTURE_ROOT)))
def test_official_cli_fixture_matches_parser_record_and_field_contracts(metadata_path: Path):
    metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
    output_path = metadata_path.with_suffix('').with_suffix('.txt')
    assert output_path.is_file(), f'Missing CLI sample paired with {metadata_path.name}'

    missing_metadata = [
        field for field in REQUIRED_METADATA_FIELDS
        if metadata.get(field) in (None, '', [])
    ]
    assert not missing_metadata, f'{metadata_path.name} misses metadata: {missing_metadata}'
    assert metadata['source_type'] in {'official_vendor_documentation', 'vendor_documentation_mirror'}
    parsed_source_url = urlparse(str(metadata['source_url']))
    assert parsed_source_url.scheme == 'https'
    official_domains = {
        'arista': ('.arista.com',),
        'cisco': ('.cisco.com',),
        'h3c': ('.h3c.com',),
        'huawei': ('.huawei.com',),
        'juniper': ('.juniper.net', 'networkingdocs.hpe.com'),
        'hillstone': ('.hillstonenet.com', '.hillstone.com'),
        'ruijie': ('.ruijie.com.cn',),
        'maipu': ('.maipu.com',),
        'zte': ('.zte.com.cn',),
        'dptech': ('.dptech.com',),
    }
    mirror_domains = {'maipu': ('support.marvel.ru',), 'dptech': ('oss.scwysa.com',)}
    domains = official_domains if metadata['source_type'] == 'official_vendor_documentation' else mirror_domains
    vendor = str(metadata['vendor']).strip().lower()
    hostname = parsed_source_url.hostname or ''
    assert any(
        hostname == domain.removeprefix('.') or hostname.endswith(domain)
        for domain in domains.get(vendor, ())
    ), f'{metadata_path.name} source host is not an approved {vendor} domain: {hostname}'
    assert int(metadata['expected_record_count']) > 0
    assert isinstance(metadata['expected_fields'], list) and metadata['expected_fields']

    platform = _parser_platform(metadata_path, metadata)
    result = smart_parse_cli(
        output_path.read_text(encoding='utf-8', errors='replace'),
        str(metadata.get('command') or ''),
        platform=platform,
        version=str(metadata.get('software_version') or ''),
        model=str(metadata.get('model') or ''),
    )

    assert result.get('success') is True, f"{platform}/{metadata.get('command')}: {result.get('message')}"
    records = result.get('data') or []
    assert records, f"{platform}/{metadata.get('command')} matched no records"
    expected_count = metadata.get('expected_record_count')
    if expected_count is not None:
        assert len(records) == int(expected_count)
    expected_fields = {str(field).upper() for field in (metadata.get('expected_fields') or [])}
    actual_fields = {str(field).upper() for record in records for field in record}
    assert expected_fields.issubset(actual_fields), sorted(expected_fields - actual_fields)

    expected_values = metadata.get('expected_values') or {}
    if expected_values:
        record_index = int(metadata.get('expected_record_index', 0))
        assert 0 <= record_index < len(records)
        for field, expected_value in expected_values.items():
            assert str(records[record_index].get(str(field).upper()) or '') == str(expected_value)

    assert result.get('template') == metadata['expected_template']
