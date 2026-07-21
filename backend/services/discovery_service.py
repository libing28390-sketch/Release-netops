"""Read-only multi-vendor discovery producing observations and findings.

Discovery never writes authoritative CMDB/IPAM fields. Confirmed changes are
applied only by reconciliation actions.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from database.core import get_db_connection
from drivers.factory import DriverFactory
from services.normalizers.factory import NormalizerFactory
from services.reconciliation_service import (
    complete_discovery_run,
    create_discovery_run,
    create_reconciliation_run,
    record_observation,
)


_logger = logging.getLogger(__name__)


COMMAND_PROFILES = {
    'cisco_ios': {
        'version': 'show version', 'interfaces': 'show interfaces',
        'brief': 'show ip interface brief', 'neighbors': 'show lldp neighbors',
        'normalizer': 'cisco_ios',
    },
    'huawei_vrp': {
        'version': 'display version', 'interfaces': 'display interface',
        'brief': 'display ip interface brief', 'neighbors': 'display lldp neighbor verbose',
        'normalizer': 'huawei_vrp',
    },
    'huawei_vrpv8': {
        'version': 'display version', 'interfaces': 'display interface',
        'brief': 'display ip interface brief', 'neighbors': 'display lldp neighbor verbose',
        'normalizer': 'huawei_vrp',
    },
    'hp_comware': {
        'version': 'display version', 'interfaces': 'display interface',
        'brief': 'display ip interface brief', 'neighbors': 'display lldp neighbor-information verbose',
        'normalizer': 'h3c_comware',
    },
    'h3c_comware': {
        'version': 'display version', 'interfaces': 'display interface',
        'brief': 'display ip interface brief', 'neighbors': 'display lldp neighbor-information verbose',
        'normalizer': 'h3c_comware',
    },
    'h3c_comware9': {
        'version': 'display version', 'interfaces': 'display interface',
        'brief': 'display ip interface brief', 'neighbors': 'display lldp neighbor-information verbose',
        'normalizer': 'h3c_comware',
    },
    'juniper_junos': {
        'version': 'show version', 'interfaces': 'show interfaces detail',
        'brief': 'show interfaces terse', 'neighbors': 'show lldp neighbors detail',
        'normalizer': 'juniper_junos',
    },
    'arista_eos': {
        'version': 'show version', 'interfaces': 'show interfaces',
        'brief': 'show ip interface brief', 'neighbors': 'show lldp neighbors detail',
        'normalizer': 'arista_eos',
    },
    'ruijie_rgos': {
        'version': 'show version', 'interfaces': 'show interfaces',
        'brief': 'show ip interface brief', 'neighbors': 'show lldp neighbors detail',
        'normalizer': 'ruijie_rgos',
    },
}

PLATFORM_ALIASES = {
    'huawei': 'huawei_vrp', 'vrp': 'huawei_vrp', 'huawei_v8': 'huawei_vrpv8',
    'h3c': 'h3c_comware', 'comware': 'h3c_comware', 'comware9': 'h3c_comware9',
    'cisco': 'cisco_ios', 'ios': 'cisco_ios',
    'juniper': 'juniper_junos', 'junos': 'juniper_junos',
    'arista': 'arista_eos', 'eos': 'arista_eos',
    'ruijie': 'ruijie_rgos', 'ruijie_os': 'ruijie_rgos', 'rgos': 'ruijie_rgos',
}


def resolve_discovery_profile(platform: str) -> tuple[str, dict]:
    key = str(platform or '').strip().lower()
    key = PLATFORM_ALIASES.get(key, key)
    if key not in COMMAND_PROFILES:
        raise ValueError(f"Unsupported discovery platform '{platform}'. Refusing Cisco command fallback.")
    return key, COMMAND_PROFILES[key]


class DiscoveryService:
    def discover_device(self, device_id: str, *, requested_by: str = 'system') -> dict:
        conn = get_db_connection()
        run_id = create_discovery_run(
            run_type='device_cli', requested_by=requested_by,
            scope={'device_ids': [device_id]}, conn=conn,
        )
        conn.commit()
        try:
            row = conn.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
            if not row:
                raise ValueError(f"Device {device_id} not found in CMDB")
            device_info = dict(row)
            platform_key, profile = resolve_discovery_profile(device_info.get('platform') or '')
            driver_type = device_info.get('connection_method') or 'netmiko'

            outputs: dict[str, str] = {}
            driver = DriverFactory.get_driver(driver_type, device_info)
            with driver:
                for output_key in ('version', 'interfaces', 'brief', 'neighbors'):
                    command = profile[output_key]
                    result = driver.send_command(command)
                    outputs[output_key] = result.output if result.success else ''
                    record_observation(
                        run_id, source_device_id=device_id, source_type='cli',
                        observed_type='cli_output', observed_key=f'{device_id}:{output_key}',
                        payload={'command': command, 'platform': platform_key,
                                 'success': bool(result.success), 'output': outputs[output_key]},
                        confidence=0.9 if result.success else 0.2, conn=conn,
                    )

            findings: list[dict[str, Any]] = []
            parsed_summary = {'device': 0, 'interfaces': 0, 'neighbors': 0, 'raw_only': profile['normalizer'] is None}
            if profile['normalizer']:
                normalizer = NormalizerFactory.get_normalizer(profile['normalizer'])
                device_obj = normalizer.parse_device_info(device_id, outputs['version'])
                device_payload = {
                    'hostname': device_obj.hostname, 'vendor': device_obj.vendor,
                    'platform': device_obj.platform or platform_key,
                    'serial_number': device_obj.sn, 'model': device_obj.model,
                    'os_version': device_obj.version, 'uptime': device_obj.uptime,
                }
                observation_id = record_observation(
                    run_id, source_device_id=device_id, source_type='normalized_cli',
                    observed_type='device', observed_key=device_id, payload=device_payload,
                    confidence=0.9, conn=conn,
                )
                proposed = {
                    key: value for key, value in device_payload.items()
                    if value not in (None, '') and str(device_info.get(key) or '') != str(value)
                }
                if proposed:
                    findings.append({
                        'observation_id': observation_id, 'finding_type': 'device_fact_mismatch',
                        'risk_level': 'high', 'target_type': 'device', 'target_id': device_id,
                        'tenant_id': device_info.get('tenant_id'), 'site_id': device_info.get('site_id'),
                        'observed': device_payload,
                        'current': {key: device_info.get(key) for key in proposed},
                        'proposed': proposed,
                    })
                parsed_summary['device'] = 1

                interfaces = normalizer.parse_interfaces(device_id, outputs['interfaces'], outputs['brief'])
                for interface in interfaces:
                    payload = asdict(interface)
                    payload['interface_name'] = interface.name_display or interface.name_raw
                    observation_id = record_observation(
                        run_id, source_device_id=device_id, source_type='normalized_cli',
                        observed_type='interface', observed_key=f"{device_id}:{payload['interface_name']}",
                        payload=payload, confidence=0.85, conn=conn,
                    )
                    existing = conn.execute(
                        "SELECT * FROM interfaces WHERE device_id = ? AND interface_name = ?",
                        (device_id, payload['interface_name']),
                    ).fetchone()
                    if not existing:
                        findings.append({
                            'observation_id': observation_id, 'finding_type': 'undocumented_interface',
                            'risk_level': 'medium', 'target_type': 'interface',
                            'target_id': f"{device_id}:{payload['interface_name']}",
                            'tenant_id': device_info.get('tenant_id'), 'site_id': device_info.get('site_id'),
                            'observed': payload, 'proposed': payload,
                        })
                parsed_summary['interfaces'] = len(interfaces)

                neighbors = normalizer.parse_neighbors(device_id, outputs['neighbors'])
                for neighbor in neighbors:
                    payload = asdict(neighbor)
                    observation_id = record_observation(
                        run_id, source_device_id=device_id, source_type='lldp',
                        observed_type='topology',
                        observed_key=f"{device_id}:{neighbor.local_interface}:{neighbor.remote_device}:{neighbor.remote_interface}",
                        payload=payload, confidence=0.85, conn=conn,
                    )
                    findings.append({
                        'observation_id': observation_id, 'finding_type': 'topology_candidate',
                        'risk_level': 'low', 'target_type': 'topology_link',
                        'target_id': None, 'observed': payload, 'proposed': payload,
                    })
                parsed_summary['neighbors'] = len(neighbors)

            reconciliation = create_reconciliation_run(
                discovery_run_id=run_id, requested_by=requested_by, findings=findings, conn=conn,
            )
            complete_discovery_run(run_id, status='succeeded', summary={
                **parsed_summary, 'findings': reconciliation['total_findings'],
                'platform': platform_key,
            }, conn=conn)
            conn.commit()
            return {
                'success': True, 'device_id': device_id, 'platform': platform_key,
                'discovery_run_id': run_id,
                'reconciliation_run_id': reconciliation['id'],
                'observations': 4 + parsed_summary['device'] + parsed_summary['interfaces'] + parsed_summary['neighbors'],
                'findings': reconciliation['total_findings'],
                'authoritative_write': False,
            }
        except Exception as exc:
            conn.rollback()
            try:
                complete_discovery_run(run_id, status='failed', summary={'error': str(exc)}, conn=conn)
                conn.commit()
            except Exception:
                conn.rollback()
            _logger.error("Discovery failed on device %s: %s", device_id, exc, exc_info=True)
            return {'success': False, 'device_id': device_id, 'discovery_run_id': run_id, 'error': str(exc)}
        finally:
            conn.close()
