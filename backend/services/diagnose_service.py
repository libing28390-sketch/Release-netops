import logging
import asyncio
import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from database import get_db_connection
from services.ip_locator_service import (
    locate_ip_async_with_options,
    _send_command,
    _check_local_device_ip,
    _build_ssh_params,
    lookup_neighbor_device
)
from services.connectivity_service import run_probe_async, _load_device
from netmiko import ConnectHandler
from core.interface_utils import normalize_interface_name

class DeviceConnectionError(Exception):
    pass

logger = logging.getLogger(__name__)


async def _execute_registry_diagnostic_action(
    device: dict,
    action_code: str,
    *,
    parameters: dict | None = None,
    include_raw_output: bool = False,
) -> dict | None:
    """Run a diagnostic read through the published registry for bound devices."""
    if not device.get('id') or not device.get('platform_profile_id'):
        return None
    from services.platform_registry_service import execute_platform_action

    user = {
        'id': f'diagnose:{device.get("id")}',
        'username': 'diagnose-service',
        'role': 'Operator',
        'tenant_id': device.get('tenant_id') or '',
    }
    try:
        return await asyncio.to_thread(
            execute_platform_action,
            str(device['id']),
            action_code,
            user=user,
            parameters=parameters,
            include_raw_output=include_raw_output,
        )
    except Exception as exc:
        logger.debug("Registry diagnostic action failed device=%s action=%s: %s", device.get('id'), action_code, exc)
        return {
            'success': False,
            'error_code': 'REGISTRY_ACTION_FAILED',
            'error': str(exc),
            'records': [],
        }


def _normalize_link_status(value: object) -> str:
    """Normalize collector/CLI status values to the diagnostic state model."""
    raw = str(value or '').strip().lower()
    if not raw:
        return 'unknown'
    if any(token in raw for token in ('administratively down', 'admin down', 'shutdown', 'disabled', 'inactive', 'err-disabled')):
        return 'down'
    if raw in {'down', 'notconnect', 'not connected', 'unconnected', 'dead'} or 'down' in raw:
        return 'down'
    if raw in {'up', 'connected', 'forwarding', 'selected', 'active'} or raw.startswith('up'):
        return 'up'
    return 'unknown'


def _counter_value(value: object) -> int:
    try:
        return max(0, int(float(str(value or '0').strip() or '0')))
    except (TypeError, ValueError):
        return 0


def _interface_health(raw_phy: str, raw_protocol: str, admin_status: str, oper_status: str) -> tuple[str, list[str]]:
    """Classify live interface health without treating historical counters as link-up."""
    reasons: list[str] = []
    phy = str(raw_phy or '').strip().lower()
    protocol = str(raw_protocol or '').strip().lower()
    if admin_status == 'down':
        reasons.append('PHY/admin 状态为 down（可能是 shutdown）' if '*' in phy or 'admin' in phy else 'PHY 状态为 down')
    if oper_status == 'down':
        reasons.append('Protocol/oper 状态为 down')
    if phy and phy not in {'up', 'down'}:
        reasons.append(f'PHY 状态异常：{raw_phy}')
    if protocol and protocol not in {'up', 'down'}:
        reasons.append(f'Protocol 状态异常：{raw_protocol}')
    if admin_status == 'down' or oper_status == 'down':
        return 'down', reasons
    return ('degraded' if reasons else 'up'), reasons


def _record_value(record: dict, *keys: str) -> str:
    normalized = {
        str(key).strip().replace('-', '_').upper(): value
        for key, value in (record or {}).items()
    }
    for key in keys:
        value = normalized.get(str(key).strip().replace('-', '_').upper())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ''


def _endpoint_attachment(conn, target_ip: str) -> dict | None:
    """Return the persisted endpoint attachment, if one exists.

    This is deliberately treated as a locator hint only.  ``last_seen`` and
    ``is_active`` identify the record, but do not prove that the access port
    is currently forwarding.
    """
    try:
        row = conn.execute(
            """
            SELECT ip, mac, hostname, switch_id, switch_port, last_seen, is_active
            FROM network_endpoints
            WHERE TRIM(ip) = ? AND COALESCE(is_active, 1) = 1
            ORDER BY last_seen DESC
            LIMIT 1
            """,
            (target_ip.strip(),),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def _resolve_endpoint_device(conn, endpoint: dict | None) -> dict | None:
    if not endpoint:
        return None
    endpoint_id = str(endpoint.get('switch_id') or '').strip()
    if not endpoint_id:
        return None
    try:
        row = conn.execute(
            "SELECT id, hostname, ip_address, platform FROM devices WHERE id = ? OR hostname = ? LIMIT 1",
            (endpoint_id, endpoint_id),
        ).fetchone()
        return dict(row) if row else None
    except Exception:
        return None


def _persisted_interface_state(conn, device_id: str, interface_name: str) -> dict:
    """Read the latest persisted interface state using the shared alias key."""
    wanted = normalize_interface_name(interface_name).lower()
    if not wanted:
        return {'state': 'unknown', 'source': 'none'}

    candidates: list[dict] = []
    try:
        rows = conn.execute(
            """
            SELECT interface_name, admin_status, oper_status, last_seen
            FROM interfaces
            WHERE device_id = ?
            """,
            (device_id,),
        ).fetchall()
        for row in rows:
            item = dict(row)
            if normalize_interface_name(item.get('interface_name')).lower() == wanted:
                candidates.append({
                    'interface_name': item.get('interface_name') or interface_name,
                    'admin_status': _normalize_link_status(item.get('admin_status')),
                    'oper_status': _normalize_link_status(item.get('oper_status')),
                    'last_seen': item.get('last_seen') or '',
                    'source': 'interfaces',
                })
    except Exception:
        pass

    # The monitor has a fresher per-interface snapshot than the CMDB row when
    # it is enabled.  Only the matching interface is selected by canonical key.
    try:
        rows = conn.execute(
            """
            SELECT interface_name, status, ts
            FROM interface_telemetry_raw
            WHERE device_id = ?
            ORDER BY ts DESC
            """,
            (device_id,),
        ).fetchall()
        for row in rows:
            item = dict(row)
            if normalize_interface_name(item.get('interface_name')).lower() == wanted:
                candidates.append({
                    'interface_name': item.get('interface_name') or interface_name,
                    'admin_status': _normalize_link_status(item.get('status')),
                    'oper_status': _normalize_link_status(item.get('status')),
                    'last_seen': item.get('ts') or '',
                    'source': 'interface_telemetry_raw',
                })
                break
    except Exception:
        pass

    if not candidates:
        return {'state': 'unknown', 'source': 'none', 'interface_name': interface_name}

    # A down observation wins over an older up observation.  Otherwise prefer
    # the newest source (telemetry rows are ordered by timestamp).
    if any(item['admin_status'] == 'down' or item['oper_status'] == 'down' for item in candidates):
        selected = next(item for item in candidates if item['admin_status'] == 'down' or item['oper_status'] == 'down')
        return {'state': 'down', **selected}
    selected = next(
        (item for item in candidates if item['admin_status'] == 'up' or item['oper_status'] == 'up'),
        candidates[-1],
    )
    state = 'up' if selected['admin_status'] == 'up' or selected['oper_status'] == 'up' else 'unknown'
    return {'state': state, **selected}


async def _refresh_device_interface_state(device_id: str, interface_name: str) -> dict:
    """Collect one device's interface brief live and normalize its state."""
    device_id = str(device_id or '').strip()
    interface_name = str(interface_name or '').strip()
    if not device_id or not interface_name:
        return {'state': 'unknown', 'source': 'interface_target_incomplete'}
    try:
        device = await asyncio.to_thread(_load_device, device_id)
        if not device:
            return {'state': 'unknown', 'source': 'endpoint_device_not_found'}
        from services.operational_data_service import collect_operational_data

        payload = await asyncio.to_thread(
            collect_operational_data,
            device,
            categories=['interfaces'],
            auth_role='auto',
        )
        category = next((item for item in payload.get('categories') or [] if item.get('key') == 'interfaces'), {})
        for record in category.get('records') or []:
            raw_name = _record_value(record, 'INTERFACE', 'NAME', 'PORT', 'IFNAME')
            if normalize_interface_name(raw_name).lower() != normalize_interface_name(interface_name).lower():
                continue
            raw_phy = _record_value(record, 'PHY', 'STATUS', 'LINK', 'ADMIN_STATUS', 'LINK_STATUS')
            raw_protocol = _record_value(record, 'PROTO', 'PROTOCOL', 'OPER_STATUS', 'OPERATE_STATUS')
            admin = _normalize_link_status(raw_phy)
            oper = _normalize_link_status(raw_protocol)
            input_errors = _counter_value(_record_value(record, 'INERRORS', 'IN_ERRORS', 'INPUT_ERRORS'))
            output_errors = _counter_value(_record_value(record, 'OUTERRORS', 'OUT_ERRORS', 'OUTPUT_ERRORS'))
            health, anomaly_reasons = _interface_health(raw_phy, raw_protocol, admin, oper)
            if input_errors or output_errors:
                anomaly_reasons.append(f'错误计数非零：in={input_errors}, out={output_errors}')
                if health == 'up':
                    health = 'degraded'
            state = 'down' if health == 'down' else ('up' if health in {'up', 'degraded'} else 'unknown')
            return {
                'state': state,
                'health': health,
                'anomaly': bool(anomaly_reasons or input_errors or output_errors),
                'anomaly_reasons': anomaly_reasons,
                'source': 'live_textfsm',
                'device_id': device_id,
                'device_name': device.get('hostname') or device_id,
                'interface_name': raw_name or interface_name,
                'admin_status': admin,
                'oper_status': oper,
                'physical_status': raw_phy or 'unknown',
                'protocol_status': raw_protocol or 'unknown',
                'error_counters': {
                    'input_errors': input_errors,
                    'output_errors': output_errors,
                },
                'last_seen': payload.get('collected_at') or '',
            }
        return {'state': 'unknown', 'source': 'live_textfsm_no_matching_interface', 'device_id': device_id, 'interface_name': interface_name}
    except Exception as exc:
        logger.info('Interface refresh failed for %s %s: %s', device_id, interface_name, exc)
        return {'state': 'unknown', 'source': 'live_textfsm_error', 'error': str(exc), 'device_id': device_id, 'interface_name': interface_name}


async def _refresh_endpoint_interface_state(endpoint: dict | None) -> dict:
    """Refresh the endpoint switch's access port through the live TextFSM path."""
    endpoint_device_id = str((endpoint or {}).get('switch_id') or '').strip()
    endpoint_port = str((endpoint or {}).get('switch_port') or '').strip()
    if not endpoint_device_id or not endpoint_port:
        return {'state': 'unknown', 'source': 'endpoint_cache_incomplete'}
    result = await _refresh_device_interface_state(endpoint_device_id, endpoint_port)
    result['endpoint_source'] = (endpoint or {}).get('source_type') or 'network_endpoints'
    return result


async def _validate_path_interfaces(hops: list[dict], endpoint_state: dict | None = None) -> dict:
    """Refresh route egress interfaces concurrently and return path evidence."""
    targets: dict[tuple[str, str], dict] = {}
    for hop in hops or []:
        device_id = str(hop.get('device_id') or '').strip()
        interfaces = hop.get('egress_interfaces') or [hop.get('interface_name')]
        for raw_interface_name in interfaces:
            interface_name = str(raw_interface_name or '').strip()
            if not device_id or not interface_name:
                continue
            targets[(device_id, normalize_interface_name(interface_name).lower())] = {
                'device_id': device_id,
                'interface_name': interface_name,
                'device_name': hop.get('device_name') or device_id,
                'hop': hop.get('hop'),
                'kind': 'path_egress',
            }
    if endpoint_state and endpoint_state.get('source') != 'live_textfsm' and endpoint_state.get('device_id') and endpoint_state.get('interface_name'):
        key = (str(endpoint_state['device_id']), normalize_interface_name(endpoint_state['interface_name']).lower())
        targets.setdefault(key, {
            'device_id': str(endpoint_state['device_id']),
            'interface_name': endpoint_state['interface_name'],
            'device_name': endpoint_state.get('device_name') or endpoint_state['device_id'],
            'kind': 'target_access',
        })

    async def collect(item: dict) -> dict:
        try:
            result = await asyncio.wait_for(
                _refresh_device_interface_state(item['device_id'], item['interface_name']),
                timeout=20,
            )
        except Exception as exc:
            result = {'state': 'unknown', 'source': 'live_textfsm_timeout', 'error': str(exc)}
        return {**item, **result, 'collected_at': _beijing_now_iso(), 'is_cached': False}

    records = []
    if endpoint_state and endpoint_state.get('source') == 'live_textfsm':
        records.append({**endpoint_state, 'kind': 'target_access', 'collected_at': endpoint_state.get('last_seen') or _beijing_now_iso(), 'is_cached': False})
    if targets:
        records.extend(await asyncio.gather(*(collect(item) for item in targets.values())))
    return {
        'records': records,
        'down': [item for item in records if item.get('state') == 'down'],
        'degraded': [item for item in records if item.get('health') == 'degraded'],
        'unknown': [item for item in records if item.get('state') == 'unknown'],
        'source': 'live_textfsm',
        'collected_at': _beijing_now_iso(),
        'is_cached': False,
    }


async def _evaluate_endpoint_attachment(conn, target_ip: str) -> dict:
    endpoint = _endpoint_attachment(conn, target_ip)
    if not endpoint:
        return {'state': 'unknown', 'source': 'endpoint_not_found'}

    endpoint_device = _resolve_endpoint_device(conn, endpoint)
    refresh_endpoint = endpoint
    if endpoint_device and str(endpoint_device.get('id')) != str(endpoint.get('switch_id')):
        refresh_endpoint = {**endpoint, 'switch_id': endpoint_device['id']}
    live_state = await _refresh_endpoint_interface_state(refresh_endpoint)
    if live_state.get('state') in {'up', 'down'}:
        return {**live_state, 'endpoint': endpoint}

    if endpoint_device:
        persisted = _persisted_interface_state(conn, endpoint_device['id'], endpoint.get('switch_port') or '')
        if persisted.get('state') in {'up', 'down'}:
            return {
                **persisted,
                'source': f"{persisted.get('source')}_fallback",
                'device_id': endpoint_device['id'],
                'device_name': endpoint_device.get('hostname') or endpoint_device['id'],
                'endpoint': endpoint,
            }
    return {**live_state, 'endpoint': endpoint, 'device_id': endpoint_device.get('id') if endpoint_device else endpoint.get('switch_id')}


def _mark_endpoint_down(hops: list[dict], target_ip: str, endpoint_state: dict) -> list[dict]:
    """Project a live last-hop DOWN observation onto the route result."""
    endpoint_name = endpoint_state.get('device_name') or endpoint_state.get('device_id') or '最后一跳接入交换机'
    endpoint_port = endpoint_state.get('interface_name') or '接入端口'
    detail = (
        f"最后一跳 {endpoint_name} {endpoint_port} 当前为 DOWN "
        f"（admin={endpoint_state.get('admin_status', 'unknown')}, oper={endpoint_state.get('oper_status', 'unknown')}）"
    )
    target_hop = next((hop for hop in reversed(hops) if str(hop.get('ip') or '').strip() == target_ip.strip()), None)
    if target_hop:
        target_hop['status'] = 'timeout'
        target_hop['detail'] = f"{detail}；历史 ARP/MAC 记录不代表当前可达"
        previous_hops = hops[:hops.index(target_hop)]
        if previous_hops:
            previous_hops[-1]['status'] = 'blocked'
            previous_hops[-1]['detail'] = detail
        return hops

    if hops:
        hops[-1]['status'] = 'blocked'
        hops[-1]['detail'] = detail
    hops.append({
        'hop': (hops[-1].get('hop', 0) + 1) if hops else 1,
        'ip': target_ip,
        'device_name': '目标主机',
        'device_id': None,
        'device_type': 'unknown',
        'status': 'timeout',
        'detail': f"{detail}；历史 ARP/MAC 记录不代表当前可达",
    })
    return hops


def _classify_acl_evidence(
    output: str,
    source_ip: str,
    target_ip: str,
    protocol: str,
    port: int,
    *,
    direction: str = 'egress',
) -> dict:
    """Classify collected ACL attachment evidence without assuming an empty result is safe.

    The interface commands used by the path walker prove whether a policy is
    attached, but most vendors require a second command to retrieve the complete
    rule body.  Therefore an attached policy is ``review_required`` unless the
    collected text contains an explicit matching permit/deny statement.
    """
    raw = str(output or '').strip()
    lowered = raw.lower()
    evidence = {
        'direction': direction,
        'source_ip': source_ip,
        'target_ip': target_ip,
        'protocol': str(protocol or '').upper(),
        'port': int(port or 0),
        'decision': 'unknown',
        'reason': 'ACL 命令无有效输出，不能据此判定未配置或放行。',
    }
    if not raw:
        return evidence

    unsupported_markers = (
        'invalid input',
        'unrecognized command',
        'unknown command',
        'error:',
        'permission denied',
        'timed out',
    )
    if any(marker in lowered for marker in unsupported_markers):
        evidence['reason'] = 'ACL 命令执行失败或设备不支持，策略状态未知。'
        return evidence

    not_configured_markers = (
        'not configured',
        'not applied',
        'no access list',
        'no access-list',
        'no traffic policy',
        'traffic policy is not',
    )
    if any(marker in lowered for marker in not_configured_markers):
        evidence.update({
            'decision': 'not_configured',
            'reason': f'{direction} 方向未发现已应用的 ACL/流量策略。',
        })
        return evidence

    flow_tokens = [source_ip.lower(), target_ip.lower(), str(protocol or '').lower()]
    if port:
        flow_tokens.append(str(port))
    flow_match = bool(source_ip and target_ip) and source_ip.lower() in lowered and target_ip.lower() in lowered
    if flow_match and re.search(r'\b(deny|drop|discard|reject)\b', lowered):
        evidence.update({
            'decision': 'deny',
            'reason': f'{direction} 方向发现与当前五元组相关的显式拒绝规则。',
        })
        return evidence
    if flow_match and re.search(r'\b(permit|allow|accept)\b', lowered):
        evidence.update({
            'decision': 'permit',
            'reason': f'{direction} 方向发现与当前五元组相关的显式放行规则。',
        })
        return evidence

    attachment_markers = (
        'access-group',
        'access-list',
        'traffic-policy',
        'traffic policy',
        'firewall filter',
        'filter input',
        'filter output',
    )
    if any(marker in lowered for marker in attachment_markers):
        evidence.update({
            'decision': 'review_required',
            'reason': (
                f'{direction} 方向检测到策略绑定，但当前输出不足以完成规则级五元组模拟；'
                f'待补采规则体后再判定。检索键：{", ".join(token for token in flow_tokens if token)}'
            ),
        })
        return evidence

    evidence['reason'] = 'ACL 输出未包含可识别的未配置声明、策略绑定或五元组匹配结果。'
    return evidence


def _derive_evidence_quality(
    diag_context: dict,
    path_interface_evidence: dict,
    *,
    return_path_status: str,
) -> dict:
    """Return evidence gaps and a confidence cap for one diagnosis run."""
    gaps: list[str] = []
    if not (path_interface_evidence or {}).get('records'):
        gaps.append('未采集到路径接口实时状态')
    elif (path_interface_evidence or {}).get('unknown'):
        gaps.append('部分路径接口实时状态未知')
    if diag_context.get('cef_verified') is None:
        gaps.append('FIB/CEF 转发面证据未知')
    if diag_context.get('acl_verified') is None:
        gaps.append('ACL/策略五元组判定未知')
    if diag_context.get('perf_warning') is None:
        gaps.append('接口计数器或设备性能证据未知')
    if diag_context.get('ha_verified') is None:
        gaps.append('HA 状态未知')
    if return_path_status != 'collected':
        gaps.append('回程路径未完成实时验证')
    return {
        'gaps': gaps,
        'confidence_cap': 70 if gaps else 100,
        'status': 'unknown' if gaps else 'complete',
    }


def _managed_device_by_ip(conn, ip_address: str) -> dict | None:
    """Resolve a managed device through management, IPAM, or inventory address."""
    normalized = str(ip_address or '').strip()
    if not normalized:
        return None
    queries = (
        (
            "SELECT id, hostname, role FROM devices WHERE TRIM(ip_address) = ? LIMIT 1",
            (normalized,),
        ),
        (
            "SELECT d.id, d.hostname, d.role FROM ip_addresses ip "
            "JOIN devices d ON ip.device_id = d.id WHERE TRIM(ip.address) = ? LIMIT 1",
            (normalized,),
        ),
        (
            "SELECT d.id, d.hostname, d.role FROM ip_inventory inv "
            "JOIN devices d ON inv.device_id = d.id WHERE TRIM(inv.ip) = ? LIMIT 1",
            (normalized,),
        ),
    )
    for query, params in queries:
        try:
            row = conn.execute(query, params).fetchone()
        except Exception:
            continue
        if row:
            return dict(row)
    return None


def _annotate_hop_interfaces(hops: list[dict]) -> list[dict]:
    """Expose ingress/egress fields explicitly, retaining unknown as unknown."""
    annotated: list[dict] = []
    for hop in hops or []:
        item = dict(hop)
        egress = item.get('egress_interface') or item.get('interface_name') or ''
        item['ingress_interface'] = item.get('ingress_interface') or ''
        item['egress_interface'] = egress
        item['interface_evidence_status'] = (
            'complete'
            if item['ingress_interface'] and item['egress_interface']
            else 'partial'
            if item['ingress_interface'] or item['egress_interface']
            else 'unknown'
        )
        annotated.append(item)
    return annotated


async def _collect_target_endpoint_state(target_ip: str) -> dict:
    conn = get_db_connection()
    try:
        return await _evaluate_endpoint_attachment(conn, target_ip)
    finally:
        conn.close()

def parse_route_output(output: str, platform: str) -> list[tuple[str, str]]:
    platform = platform.lower()
    paths = []

    if "huawei" in platform or "vrp" in platform or "comware" in platform or "h3c" in platform:
        for line in output.splitlines():
            m = re.search(r'(\d+\.\d+\.\d+\.\d+/\d+)\s+(\w+)\s+\d+\s+\d+\s+\w*\s+(\S+)\s+(\S+)', line)
            if m:
                proto = m.group(2).lower()
                next_hop = "directly connected" if proto == 'direct' else m.group(3)
                interface = m.group(4)
                paths.append((next_hop.strip(), normalize_interface_name(interface)))
                continue
            
            # Match subsequent ECMP rows (which might omit the destination IP/mask)
            # E.g.: "                    OSPF    10   20          D   10.254.2.2      GigabitEthernet0/2"
            m2 = re.search(r'^\s+(?:OSPF|Static|RIP|BGP|Direct|Comware|HP)\s+\d+\s+\d+\s+\w*\s+(\S+)\s+(\S+)', line, re.I)
            if m2:
                next_hop = m2.group(1)
                interface = m2.group(2)
                paths.append((next_hop.strip(), normalize_interface_name(interface)))
                continue
                
            m3 = re.search(r'^\s+(\d+\.\d+\.\d+\.\d+)\s+(\S+)\s*$', line)
            if m3:
                next_hop = m3.group(1)
                interface = m3.group(2)
                paths.append((next_hop.strip(), normalize_interface_name(interface)))
    elif "juniper" in platform or "junos" in platform:
        for line in output.splitlines():
            m = re.search(r'(?:to\s+(\S+)\s+via\s+(\S+)|via\s+(\S+))', line)
            if m:
                if m.group(1) and m.group(2):
                    next_hop = m.group(1)
                    interface = m.group(2)
                else:
                    next_hop = "directly connected"
                    interface = m.group(3)
                paths.append((next_hop.strip(), normalize_interface_name(interface)))
    else:
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            if any(h in line.lower() for h in ("routing entry for", "known via", "routing descriptor blocks", "is subnetted")):
                continue
            
            # Check for directly connected
            if 'directly connected' in line:
                interface = ""
                m_intf = re.search(r'via\s+(\S+)', line)
                if m_intf:
                    interface = normalize_interface_name(m_intf.group(1))
                else:
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) > 1:
                        last_part = parts[-1]
                        if last_part and last_part[0].isalpha():
                            interface = normalize_interface_name(last_part)
                paths.append(("directly connected", interface))
                continue
            
            # Check if it has "via"
            if 'via' in line:
                pre_via, post_via = line.split('via', 1)
                pre_via = pre_via.strip()
                post_via = post_via.strip()
                
                # Check if pre_via contains an IP next-hop at the start (Format A: "* 10.1.69.9, from 8.8.8.8, ... via Ethernet0/2")
                m_ip_pre = re.search(r'^(?:\*\s*)?([\d\.]+)', pre_via)
                if m_ip_pre and ',' in pre_via:
                    next_hop = m_ip_pre.group(1)
                    # Interface is the first token of post_via
                    m_intf = re.match(r'^(\S+)', post_via)
                    interface = normalize_interface_name(m_intf.group(1)) if m_intf else ""
                    paths.append((next_hop, interface))
                else:
                    # Format B: "via 10.1.69.9, 00:02:55, Ethernet0/2"
                    parts = [p.strip() for p in post_via.split(',')]
                    if parts:
                        next_hop = parts[0]
                        interface = ""
                        if len(parts) > 1:
                            last_part = parts[-1]
                            if last_part and last_part[0].isalpha():
                                interface = normalize_interface_name(last_part)
                        paths.append((next_hop, interface))
                continue

    # Remove duplicates while preserving order
    seen = set()
    unique_paths = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique_paths.append(p)

    return unique_paths

def parse_neighbors_output(output: str, local_intf: str, platform: str) -> str:
    norm_local = normalize_interface_name(local_intf).lower()
    if not norm_local:
        return ""

    platform_lower = platform.lower()
    
    # 1. Huawei/H3C Verbose Multi-line block parser
    if "huawei" in platform_lower or "vrp" in platform_lower or "comware" in platform_lower or "h3c" in platform_lower:
        blocks = re.split(r'-{20,}|(?=LLDP neighbor-information of port|LLDP neighbor-information of)', output)
        for block in blocks:
            if not block.strip():
                continue
            local_intf_match = re.search(r'(?:Local\s+Int(?:f|erface)\s*[:\-]\s*(.+?)$|of port\s+(\S+?)(?:\s*:|\[))', block, re.IGNORECASE | re.MULTILINE)
            if not local_intf_match:
                continue
            parsed_local = local_intf_match.group(1) or local_intf_match.group(2) or ""
            if '[' in parsed_local and ']' in parsed_local:
                parsed_local = parsed_local.split('[')[1].split(']')[0]
            parsed_local = parsed_local.strip(':').strip()
            
            if normalize_interface_name(parsed_local).lower() == norm_local:
                sys_name_match = re.search(r'(?:System\s*Name|SysName)\s*[:\-]\s*(.+?)$', block, re.IGNORECASE | re.MULTILINE)
                if sys_name_match:
                    neighbor_host = sys_name_match.group(1).strip()
                    return neighbor_host.split('.')[0]
        return ""

    # 2. Juniper Table Parser (local interface is parts[0], neighbor host is parts[-1])
    if "juniper" in platform_lower or "junos" in platform_lower:
        for line in output.splitlines():
            line = line.strip()
            if not line or line.startswith(('Local Interface', '---', 'Parent Interface')):
                continue
            parts = line.split()
            if len(parts) >= 2:
                norm_joined = normalize_interface_name(parts[0]).lower()
                if norm_joined == norm_local:
                    neighbor_host = parts[-1]
                    return neighbor_host.split('.')[0]
        return ""

    # 3. Cisco/Default Table Parser (neighbor name at parts[0], local interface at parts[1])
    for line in output.splitlines():
        line = line.strip()
        if not line or line.startswith(('Device ID', 'Capability', 'System Name', 'Local Intf')):
            continue
        parts = line.split()
        if len(parts) >= 2:
            for i in range(1, len(parts)):
                joined_intf = "".join(parts[1:i+1])
                norm_joined = normalize_interface_name(joined_intf).lower()
                if norm_joined and norm_joined == norm_local:
                    neighbor_host = parts[0]
                    return neighbor_host.split('.')[0]
                    
    return ""




def parse_interface_counters(output: str, platform: str) -> dict:
    counters = {"input_errors": 0, "crc": 0, "input_drops": 0, "output_drops": 0}
    
    # 1. Input errors
    # Juniper: "Input errors:\n        Errors: 7"
    m_err = re.search(r'Input errors:\s*Errors:\s*(\d+)', output, re.I)
    if not m_err:
        m_err = re.search(r'(\d+)[^\S\r\n]+(?:input errors|errors\b)', output, re.I)
    if not m_err:
        m_err = re.search(r'Input errors:\s*(\d+)', output, re.I)
    if m_err:
        counters["input_errors"] = int(m_err.group(1))
        
    # 2. CRC errors
    m_crc = re.search(r'(\d+)[^\S\r\n]+CRC', output, re.I)
    if m_crc:
        counters["crc"] = int(m_crc.group(1))
        
    # 3. Input drops
    # Cisco: "Input queue: 0/75/0/0 (size/max/drops/flushes)"
    m_drops1 = re.search(r'Input queue:.*?(\d+)/(\d+)/(\d+)/(\d+)\s*\(size/max/drops/flushes\)', output)
    if m_drops1:
        counters["input_drops"] = int(m_drops1.group(3))
    else:
        # Juniper: "Input errors:\n        Errors: 7, Drops: 0"
        m_drops_j = re.search(r'Input errors:.*?\bDrops:\s*(\d+)', output, re.S | re.I)
        if not m_drops_j:
            m_drops_j = re.search(r'Input drops:\s*(\d+)', output, re.I)
        if m_drops_j:
            counters["input_drops"] = int(m_drops_j.group(1))

    # 4. Output drops
    # Cisco: "Total output drops: 0"
    m_drops2 = re.search(r'Total output drops:\s*(\d+)', output, re.I)
    if not m_drops2:
        # Juniper: "Output errors:\n        Carrier transitions: 0, Errors: 0, Drops: 31"
        m_drops2 = re.search(r'Output errors:.*?\bDrops:\s*(\d+)', output, re.S | re.I)
    if not m_drops2:
        # Search specifically inside the "Output:" section if it exists (H3C/Huawei format)
        out_match = re.search(r'\bOutput:\s*(.*)', output, re.S | re.I)
        if out_match:
            m_drops2 = re.search(r'(\d+)[^\S\r\n]+discarded', out_match.group(1), re.I)
            if not m_drops2:
                m_drops2 = re.search(r'discarded:\s*(\d+)', out_match.group(1), re.I)
    if not m_drops2:
        # Juniper: "Output drops: 0"
        m_drops2 = re.search(r'Output drops:\s*(\d+)', output, re.I)
    if not m_drops2:
        m_drops2 = re.search(r'(\d+)[^\S\r\n]+discarded', output, re.I)
    if not m_drops2:
        m_drops2 = re.search(r'discarded:\s*(\d+)', output, re.I)
    if m_drops2:
        counters["output_drops"] = int(m_drops2.group(1))

    # Fallback for Cisco hardware packet output line
    if counters["input_errors"] == 0:
        m_hw_errs = re.search(r'Input:\s*\d+\s+packets,\s*\d+\s+bytes,\s*\d+\s+buffers,\s*(\d+)\s+errors', output, re.I)
        if m_hw_errs:
             counters["input_errors"] = int(m_hw_errs.group(1))

    return counters

def parse_cpu_utilization(output: str) -> int:
    m = re.search(r'CPU utilization for five seconds:\s*(\d+)\%', output)
    if m:
        return int(m.group(1))
    m_hw = re.search(r'CPU [Uu]sage\s*:\s*(\d+)\%', output)
    if m_hw:
        return int(m_hw.group(1))
    return 0

import ipaddress

def get_device_vrf_for_ip(conn, device_id: str, ip: str) -> str:
    try:
        row = conn.execute(
            "SELECT vrf_id FROM ip_addresses WHERE device_id = ? AND address = ?",
            (device_id, ip.strip())
        ).fetchone()
        if row and row['vrf_id']:
            vrf_row = conn.execute(
                "SELECT vrf_name FROM vrfs WHERE id = ?",
                (row['vrf_id'],)
            ).fetchone()
            if vrf_row:
                return vrf_row['vrf_name']
    except Exception:
        pass
    return 'default'


def match_route_offline(device_id: str, target_ip: str, vrf_name: str = 'default', conn=None) -> list[dict]:
    """
    在本地 route_table 数据库中执行最长前缀匹配 (LPM)，寻找匹配的路由条目。
    如果有多条等价路由 (ECMP)，则全部返回。
    """
    try:
        ip_obj = ipaddress.ip_address(target_ip.strip())
    except Exception:
        return []

    owns_connection = conn is None
    if owns_connection:
        conn = get_db_connection()

    def lookup_in_vrf(vrf: str) -> list[dict]:
        rows = conn.execute(
            "SELECT destination, next_hop, protocol, outgoing_interface, metric, vrf_name "
            "FROM route_table WHERE device_id = ? AND vrf_name = ?",
            (device_id, vrf)
        ).fetchall()
        matched = []
        for row in rows:
            dest = row['destination'].strip()
            try:
                net = ipaddress.ip_network(dest, strict=False)
                if ip_obj in net:
                    prefix, mask_len_str = dest.split('/')
                    mask_len = int(mask_len_str)
                    mask_int = (0xffffffff >> (32 - mask_len)) << (32 - mask_len)
                    mask = f"{(mask_int >> 24) & 0xff}.{(mask_int >> 16) & 0xff}.{(mask_int >> 8) & 0xff}.{mask_int & 0xff}"
                    
                    matched.append({
                        'prefix': prefix,
                        'mask': mask,
                        'prefix_len': net.prefixlen,
                        'next_hop': row['next_hop'],
                        'protocol': row['protocol'],
                        'interface': row['outgoing_interface'],
                        'metric': row['metric'],
                        'vrf_name': row['vrf_name']
                    })
            except Exception:
                continue
        return matched

    try:
        matched_routes = lookup_in_vrf(vrf_name)
        if not matched_routes and vrf_name != 'default':
            # Fallback/leak check
            matched_routes = lookup_in_vrf('default')

        if not matched_routes:
            return []

        max_len = max(r['prefix_len'] for r in matched_routes)
        return [r for r in matched_routes if r['prefix_len'] == max_len]
    finally:
        if owns_connection:
            conn.close()


async def trace_route_path_async(
    conn,
    start_device_id: str,
    target_ip: str,
    vrf: str = None,
    *,
    source_ip: str = '',
    protocol: str = '',
    port: int = 0,
) -> tuple[list[dict], str, str, dict]:
    last_log = ""
    
    diag_context = {
        "cef_verified": None,
        "cef_logs": "",
        "bgp_verified": None,
        "bgp_logs": "",
        "ha_verified": None,
        "ha_logs": "",
        "perf_logs": "",
        "perf_warning": None,
        "perf_details": [],
        "route_sources": [],
        "vrf_logs": "",
        "acl_logs": "",
        "acl_verified": None,
        "acl_evidence": [],
        "endpoint_state": {},
        "force_live_route": True,
        "route_cache_hits": 0,
        "command_cache_hits": 0,
        "live_commands": [],
        "path_interface_states": [],
    }
    device_cache: dict[str, dict] = {}

    def load_trace_device(device_id: str):
        key = str(device_id)
        if key not in device_cache:
            device = _load_device(device_id)
            if device:
                device_cache[key] = device
        return device_cache.get(key)

    def merge_hops(hops_a: list[dict], hops_b: list[dict]) -> list[dict]:
        merged = []
        max_len = max(len(hops_a), len(hops_b))
        for i in range(max_len):
            if i < len(hops_a) and i < len(hops_b):
                ha = hops_a[i]
                hb = hops_b[i]
                if ha["ip"] == hb["ip"] and ha["device_name"] == hb["device_name"]:
                    merged.append(ha)
                else:
                    status = "active"
                    if ha["status"] == "blocked" or hb["status"] == "blocked":
                        status = "blocked"
                    elif ha["status"] == "timeout" or hb["status"] == "timeout":
                        status = "timeout"
                    elif ha["status"] == "warning" or hb["status"] == "warning":
                        status = "warning"
                    
                    merged.append({
                        "hop": ha["hop"],
                        "ip": f"{ha['ip']} | {hb['ip']}",
                        "device_name": f"{ha['device_name']} | {hb['device_name']}",
                        "device_id": None,
                        "device_type": ha["device_type"] if ha["device_type"] == hb["device_type"] else "router",
                        "status": status,
                        "detail": f"Path 1: {ha['detail']} || Path 2: {hb['detail']}",
                        "is_ecmp": True,
                        "paths": [ha, hb]
                    })
            elif i < len(hops_a):
                merged.append(hops_a[i])
            else:
                merged.append(hops_b[i])
        return merged

    async def trace_recursive(current_device_id: str, hop_count: int, visited_ids: set, current_vrf: str = 'default') -> tuple[list[dict], str]:
        nonlocal last_log
        
        if hop_count > 15:
            return [{
                "hop": hop_count,
                "ip": "*",
                "device_name": "超时节点",
                "device_type": "unknown",
                "status": "timeout",
                "detail": "超出最大诊断跳数 (TTL Exceeded)"
            }], "interrupted"

        dev = load_trace_device(current_device_id)
        if not dev:
            return [], "interrupted"

        dev_label = dev.get('hostname') or dev.get('ip_address')
        visited_ids = visited_ids | {dev['id']}
        
        platform = dev.get('platform') or 'cisco_ios'
        platform_lower = platform.lower()

        # Try offline route matching first
        offline_matches = [] if diag_context.get('force_live_route') else match_route_offline(
            current_device_id, target_ip, current_vrf, conn=conn
        )
        if offline_matches:
            diag_context['route_cache_hits'] = int(diag_context.get('route_cache_hits') or 0) + 1
        
        if offline_matches:
            matched_vrf = offline_matches[0].get('vrf_name', 'default')
            if current_vrf != matched_vrf:
                diag_context["vrf_logs"] += f"[{dev_label}] Route matched in vrf {matched_vrf} (leaked from {current_vrf})\n"
            unique_paths = []
            route_output_lines = [f"[路由缓存命中] 最长前缀匹配 (LPM) 结果:"]
            route_source = "Static/Connected"
            for r in offline_matches:
                nh = r['next_hop']
                egress = r['interface']
                unique_paths.append((nh, egress))
                route_output_lines.append(f"  * {r['prefix']}/{r['prefix_len']} via {nh} ({egress}) [Protocol: {r['protocol']}]")
                proto_lower = r['protocol'].lower()
                if 'ospf' in proto_lower:
                    route_source = "OSPF"
                elif 'bgp' in proto_lower:
                    route_source = "BGP"
                elif 'rip' in proto_lower:
                    route_source = "RIP"
                elif 'eigrp' in proto_lower:
                    route_source = "EIGRP"
            route_output = "\n".join(route_output_lines)
            last_log += f"\n[{dev_label}] (本地缓存匹配)\n" + route_output + "\n"
            diag_context["route_sources"].append({"device": dev_label, "source": route_source})
            
            # Fill other diag logs with mock verified info
            diag_context["cef_logs"] += f"[{dev_label}]# CEF Status (Cached/Verified)\n"
            diag_context["cef_verified"] = True
            if route_source == "BGP":
                diag_context["bgp_logs"] += f"[{dev_label}]# BGP Status (Cached/Verified)\n"
                diag_context["bgp_verified"] = True
            
            # Now determine next hops
            is_direct = any(nh == "directly connected" or not nh or nh == "local" or "loopback" in intf.lower() for nh, intf in unique_paths)
            if is_direct:
                is_local_ip = False
                if target_ip.strip() == dev.get('ip_address', '').strip():
                    is_local_ip = True
                else:
                    try:
                        conn_db = get_db_connection()
                        try:
                            row_db = conn_db.execute(
                                "SELECT ip.address FROM ip_addresses ip WHERE ip.device_id = ? AND ip.address = ?",
                                (dev['id'], target_ip.strip())
                            ).fetchone()
                            if row_db:
                                is_local_ip = True
                            else:
                                row_inv = conn_db.execute(
                                    "SELECT ip FROM ip_inventory WHERE device_id = ? AND ip = ?",
                                    (dev['id'], target_ip.strip())
                                ).fetchone()
                                if row_inv:
                                    is_local_ip = True
                        finally:
                            conn_db.close()
                    except Exception:
                        pass
                
                if is_local_ip:
                    return [{
                        "hop": hop_count,
                        "ip": dev.get('ip_address'),
                        "device_name": dev_label,
                        "device_id": dev['id'],
                        "device_type": dev.get('role') or 'router',
                        "status": "active",
                        "detail": f"Reached target local interface",
                        "cpu_usage": dev.get('cpu_usage', 0),
                        "memory_usage": dev.get('memory_usage', 0)
                    }, {
                        "hop": hop_count + 1,
                        "ip": target_ip,
                        "device_name": "目标主机",
                        "device_id": None,
                        "device_type": "unknown",
                        "status": "active",
                        "detail": "到达目标 (环回口/本地接口)"
                    }], "reachable"
                
                from services.ip_locator_service import _get_cached_arp, _get_cached_endpoint
                cached_arp = _get_cached_arp(target_ip)
                cached_ep = _get_cached_endpoint(target_ip)
                mac_str = None
                if cached_arp:
                    mac_str = cached_arp['mac']
                elif cached_ep:
                    mac_str = cached_ep['mac']
                
                current_hop = {
                    "hop": hop_count,
                    "ip": dev.get('ip_address'),
                    "device_name": dev_label,
                    "device_id": dev['id'],
                    "device_type": dev.get('role') or 'router',
                    "status": "active",
                    "detail": "directly connected",
                    "interface_name": unique_paths[0][1] if unique_paths else "",
                    "cpu_usage": dev.get('cpu_usage', 0),
                    "memory_usage": dev.get('memory_usage', 0)
                }

                if mac_str:
                    return [current_hop, {
                        "hop": hop_count + 1,
                        "ip": target_ip,
                        "device_name": "目标主机",
                        "device_id": None,
                        "device_type": "unknown",
                        "status": "active",
                        "detail": f"到达目标 (MAC: {mac_str})"
                    }], "reachable"
                else:
                    return [current_hop, {
                        "hop": hop_count + 1,
                        "ip": target_ip,
                        "device_name": "目标主机",
                        "device_id": None,
                        "device_type": "unknown",
                        "status": "timeout",
                        "detail": "主机无响应 (ARP Missing)"
                    }], "interrupted"

            current_hop_detail = "ECMP Paths: " + ", ".join([f"{nh} via {intf}" for nh, intf in unique_paths]) if len(unique_paths) > 1 else f"Next-hop: {unique_paths[0][0]} via {unique_paths[0][1]}"
            current_hop = {
                "hop": hop_count,
                "ip": dev.get('ip_address'),
                "device_name": dev_label,
                "device_id": dev['id'],
                "device_type": dev.get('role') or 'router',
                "status": "active",
                "detail": current_hop_detail,
                "interface_name": unique_paths[0][1] if len(unique_paths) == 1 else "",
                "egress_interfaces": [intf for _, intf in unique_paths],
                "cpu_usage": dev.get('cpu_usage', 0),
                "memory_usage": dev.get('memory_usage', 0)
            }
            
            branches_results = []
            conn_db = get_db_connection()
            try:
                for nh, egress_intf in unique_paths[:2]:
                    neighbor_name = None
                    port_norm = normalize_interface_name(egress_intf).lower()
                    row_link = conn_db.execute(
                        "SELECT target_device_id, target_hostname "
                        "FROM topology_links WHERE source_device_id = ? AND LOWER(source_port_normalized) = ?",
                        (dev['id'], port_norm)
                    ).fetchone()
                    if not row_link:
                        row_link = conn_db.execute(
                            "SELECT source_device_id, source_hostname "
                            "FROM topology_links WHERE target_device_id = ? AND LOWER(target_port_normalized) = ?",
                            (dev['id'], port_norm)
                        ).fetchone()
                        if row_link:
                            neighbor_name = row_link['source_hostname']
                    else:
                        neighbor_name = row_link['target_hostname']
                    
                    neighbor_dev = lookup_neighbor_device(conn_db, neighbor_name, nh)
                    
                    if not neighbor_dev:
                        branches_results.append(([current_hop, {
                            "hop": hop_count + 1,
                            "ip": nh,
                            "device_name": neighbor_name or f"未知网关 ({nh})",
                            "device_id": None,
                            "device_type": "unknown",
                            "status": "timeout",
                            "detail": "无法跳转：未在系统资产中发现下一跳邻居设备"
                        }], "interrupted"))
                    elif neighbor_dev['id'] in visited_ids:
                        branches_results.append(([current_hop, {
                            "hop": hop_count + 1,
                            "ip": neighbor_dev.get('ip_address'),
                            "device_name": neighbor_dev.get('hostname'),
                            "device_id": neighbor_dev['id'],
                            "device_type": neighbor_dev.get('role') or 'router',
                            "status": "blocked",
                            "detail": "检测到路由环路 (Routing loop detected)"
                        }], "interrupted"))
                    else:
                        next_vrf = get_device_vrf_for_ip(conn_db, neighbor_dev['id'], nh)
                        if next_vrf != current_vrf:
                            diag_context["vrf_logs"] += f"[{dev_label}] (Offline) Path crossed VRF boundary from {current_vrf} to {next_vrf} on neighbor {neighbor_dev.get('hostname')}\n"
                        sub_hops, sub_conclusion = await trace_recursive(neighbor_dev['id'], hop_count + 1, visited_ids, next_vrf)
                        branches_results.append(([current_hop] + sub_hops, sub_conclusion))
            finally:
                conn_db.close()
                
            if not branches_results:
                return [current_hop], "interrupted"
            elif len(branches_results) == 1:
                return branches_results[0][0], branches_results[0][1]
            else:
                merged = merge_hops(branches_results[0][0], branches_results[1][0])
                conclusion = "reachable" if all(c == "reachable" for _, c in branches_results) else "interrupted"
                return merged, conclusion

        conn_params = _build_ssh_params(dev)
        client = None

        async def run_cmd(command: str) -> str:
            nonlocal client
            device_ip = dev.get('ip_address') or dev.get('hostname') or 'unknown'
            # Route/FIB/ARP/LLDP/interface data is volatile and must be live in
            # a diagnosis. Do not let the generic command cache decide reachability.
            diag_context['live_commands'].append({
                'device_id': dev.get('id'),
                'device_name': dev_label,
                'command': command,
                'collected_at': _beijing_now_iso(),
                'source': 'live_cli',
                'is_cached': False,
            })

            if dev.get('platform_profile_id'):
                normalized_command = str(command or '').lower()
                action_code = None
                if 'bgp' in normalized_command:
                    action_code = 'get_bgp_neighbors_vrf' if current_vrf and current_vrf != 'default' else 'get_bgp_neighbors'
                elif 'arp' in normalized_command:
                    action_code = 'get_arp_table_vrf' if current_vrf and current_vrf != 'default' else 'get_arp_table'
                elif 'mac' in normalized_command:
                    action_code = 'get_mac_table_vrf' if current_vrf and current_vrf != 'default' else 'get_mac_table'
                elif 'route' in normalized_command or 'routing-table' in normalized_command:
                    action_code = 'get_route_table_vrf' if current_vrf and current_vrf != 'default' else 'get_route_table'
                elif 'lldp' in normalized_command:
                    action_code = 'get_lldp_neighbors'
                elif 'interface' in normalized_command:
                    action_code = 'get_interface_brief'
                elif 'cpu' in normalized_command:
                    action_code = 'get_cpu'
                elif 'memory' in normalized_command:
                    action_code = 'get_memory'
                if not action_code:
                    raise DeviceConnectionError('platform_registry:UNSUPPORTED_ACTION: diagnostic command is not a registered action')
                registry_result = await _execute_registry_diagnostic_action(
                    dev,
                    action_code,
                    parameters={'vrf': current_vrf} if action_code.endswith('_vrf') else None,
                    include_raw_output=True,
                )
                if not registry_result or not registry_result.get('success'):
                    raise DeviceConnectionError(
                        f"platform_registry:{(registry_result or {}).get('error_code') or 'ACTION_FAILED'}:"
                        f"{(registry_result or {}).get('error') or 'registered diagnostic action failed'}"
                    )
                return str(registry_result.get('raw_output') or '')

            if client is None:
                port = int(dev.get('port') or dev.get('management_port') or 22)
                from drivers.ssh_compat import is_ssh_port_open
                if not is_ssh_port_open(device_ip, port):
                    raise DeviceConnectionError(f"SSH port {port} is closed/unreachable")
                try:
                    client = await asyncio.to_thread(ConnectHandler, **conn_params)
                    if conn_params.get('secret'):
                        try:
                            await asyncio.to_thread(client.enable)
                        except Exception:
                            pass
                except Exception as conn_err:
                    raise DeviceConnectionError(str(conn_err))

            output = await asyncio.to_thread(
                client.send_command,
                command,
                cmd_verify=False,
                strip_prompt=True,
                strip_command=True,
                read_timeout=30
            )
            return output

        try:
            if hop_count == 1:
                if platform_lower in ('huawei_vrp', 'h3c_comware'):
                    cmd_vrf = "display ip vpn-instance"
                elif platform_lower in ('juniper_junos',):
                    cmd_vrf = "show instance"
                else:
                    cmd_vrf = "show vrf"
                try:
                    vrf_out = await run_cmd(cmd_vrf)
                    diag_context["vrf_logs"] += f"[{dev_label}]# {cmd_vrf}\n{vrf_out}\n"
                except Exception as e:
                    diag_context["vrf_logs"] += f"[{dev_label}]# {cmd_vrf}\nError: {e}\n"

            if current_vrf and current_vrf != 'default':
                if platform_lower in ('huawei_vrp', 'h3c_comware'):
                    cmd_route = f"display ip routing-table vpn-instance {current_vrf} {target_ip}"
                elif platform_lower in ('juniper_junos',):
                    cmd_route = f"show route table {current_vrf}.inet.0 {target_ip}"
                else:
                    cmd_route = f"show ip route vrf {current_vrf} {target_ip}"
            else:
                if platform_lower in ('huawei_vrp', 'h3c_comware'):
                    cmd_route = f"display ip routing-table {target_ip}"
                elif platform_lower in ('juniper_junos',):
                    cmd_route = f"show route {target_ip}"
                else:
                    cmd_route = f"show ip route {target_ip}"

            last_log += f"\n[{dev_label}]# {cmd_route}\n"
            try:
                route_output = await run_cmd(cmd_route)
                last_log += route_output + "\n"
            except Exception as e:
                last_log += f"Error executing route check: {e}\n"
                return [{
                    "hop": hop_count,
                    "ip": dev.get('ip_address'),
                    "device_name": dev_label,
                    "device_id": dev['id'],
                    "device_type": dev.get('role') or 'router',
                    "status": "blocked",
                    "detail": f"执行路由查询失败: {e}"
                }], "interrupted"

            unique_paths = parse_route_output(route_output, platform)
            
            route_source = "Static/Connected"
            if "ospf" in route_output.lower():
                route_source = "OSPF"
            elif "bgp" in route_output.lower() or " b " in route_output.lower() or "ibgp" in route_output.lower() or "ebgp" in route_output.lower():
                route_source = "BGP"
            elif "rip" in route_output.lower():
                route_source = "RIP"
            elif "eigrp" in route_output.lower():
                route_source = "EIGRP"
            diag_context["route_sources"].append({"device": dev_label, "source": route_source})

            cmd_cef = None
            if platform_lower == 'ruijie_rgos':
                diag_context["cef_logs"] += f"[{dev_label}]# (CEF check skipped on Ruijie RGOS)\n"
            else:
                if current_vrf and current_vrf != 'default':
                    if platform_lower in ('huawei_vrp', 'h3c_comware'):
                        cmd_cef = f"display fib vpn-instance {current_vrf} {target_ip}"
                    elif platform_lower in ('juniper_junos',):
                        cmd_cef = f"show route forwarding-table destination {target_ip} table {current_vrf}"
                    else:
                        cmd_cef = f"show ip cef vrf {current_vrf} {target_ip}"
                else:
                    if platform_lower in ('huawei_vrp', 'h3c_comware'):
                        cmd_cef = f"display fib {target_ip}"
                    elif platform_lower in ('juniper_junos',):
                        cmd_cef = f"show route forwarding-table destination {target_ip}"
                    else:
                        cmd_cef = f"show ip cef {target_ip}"

            if cmd_cef:
                diag_context["cef_logs"] += f"[{dev_label}]# {cmd_cef}\n"
                try:
                    cef_out = await run_cmd(cmd_cef)
                    diag_context["cef_logs"] += cef_out + "\n"
                    cef_l = cef_out.lower()
                    if "no route" in cef_l or "not found" in cef_l or "drop" in cef_l or "not in table" in cef_l or (len(cef_out.strip()) < 10 and "0.0.0.0" not in target_ip):
                        diag_context["cef_verified"] = False
                    elif cef_out.strip():
                        diag_context["cef_verified"] = True
                except Exception as e:
                    diag_context["cef_logs"] += f"Error: {e}\n"

            if route_source == "BGP":
                if platform_lower in ('huawei_vrp', 'h3c_comware'):
                    if current_vrf and current_vrf != 'default':
                        cmd_bgp = f"display bgp ipv4 unicast vpn-instance {current_vrf} routing-table {target_ip}"
                    else:
                        cmd_bgp = f"display bgp ipv4 unicast routing-table {target_ip}"
                elif platform_lower in ('juniper_junos',):
                    if current_vrf and current_vrf != 'default':
                        cmd_bgp = f"show route table {current_vrf} protocol bgp {target_ip}"
                    else:
                        cmd_bgp = f"show route protocol bgp {target_ip}"
                else:
                    if current_vrf and current_vrf != 'default':
                        cmd_bgp = f"show ip bgp vrf {current_vrf} {target_ip}"
                    else:
                        cmd_bgp = f"show ip bgp {target_ip}"

                diag_context["bgp_logs"] += f"[{dev_label}]# {cmd_bgp}\n"
                try:
                    bgp_out = await run_cmd(cmd_bgp)
                    diag_context["bgp_logs"] += bgp_out + "\n"
                    bgp_l = bgp_out.lower()
                    if any(term in bgp_l for term in ("not in table", "not active", "not found", "no such", "inactive")):
                        diag_context["bgp_verified"] = False
                    elif bgp_out.strip():
                        diag_context["bgp_verified"] = True
                except Exception as e:
                    diag_context["bgp_logs"] += f"Error: {e}\n"

            if platform_lower in ('huawei_vrp', 'h3c_comware'):
                cmd_ha = "display vrrp brief"
            elif platform_lower in ('juniper_junos',):
                cmd_ha = "show vrrp summary"
            elif platform_lower == 'ruijie_rgos':
                cmd_ha = "show vrrp brief"
            else:
                cmd_ha = "show standby brief"
            diag_context["ha_logs"] += f"[{dev_label}]# {cmd_ha}\n"
            try:
                ha_out = await run_cmd(cmd_ha)
                diag_context["ha_logs"] += ha_out + "\n"
                if "master" in ha_out.lower() and ha_out.lower().count("master") >= 2:
                    diag_context["ha_verified"] = False
                    diag_context["ha_logs"] += "WARNING: Dual Master split-brain state detected!\n"
                elif ha_out.strip() and any(
                    token in ha_out.lower()
                    for token in ('master', 'backup', 'active', 'standby', 'vrrp', 'hsrp')
                ):
                    diag_context["ha_verified"] = True
            except Exception as e:
                diag_context["ha_logs"] += f"Error: {e}\n"

            for nh, egress_intf in unique_paths:
                if egress_intf:
                    if platform_lower in ('huawei_vrp', 'h3c_comware'):
                        cmd_intf = f"display interface {egress_intf}"
                        cmd_cpu = "display cpu-usage"
                        cmd_mem = "display memory-usage"
                    elif platform_lower in ('juniper_junos',):
                        cmd_intf = f"show interfaces {egress_intf}"
                        cmd_cpu = "show system statistics"
                        cmd_mem = "show system memory"
                    else:
                        cmd_intf = f"show interface {egress_intf}"
                        cmd_cpu = "show processes cpu"
                        cmd_mem = "show memory"

                    try:
                        intf_out = await run_cmd(cmd_intf)
                        counters = parse_interface_counters(intf_out, platform)
                        cpu_val = parse_cpu_utilization(await run_cmd(cmd_cpu))
                        await run_cmd(cmd_mem)

                        status_str = "HEALTHY"
                        if diag_context["perf_warning"] is None:
                            diag_context["perf_warning"] = False
                        if counters["crc"] > 0 or counters["input_errors"] > 0 or cpu_val > 80:
                            status_str = "WARNING"
                            diag_context["perf_warning"] = True

                        diag_context["perf_logs"] += (
                            f"[{dev_label}] Performance Telemetry Summary:\n"
                            f"  - Egress Interface: {egress_intf}\n"
                            f"  - Input Errors: {counters['input_errors']} | CRC Errors: {counters['crc']}\n"
                            f"  - Input Queue Drops: {counters['input_drops']} | Output Queue Drops: {counters['output_drops']}\n"
                            f"  - CPU Utilization: {cpu_val}%\n"
                            f"  - Status: {status_str}\n"
                        )
                        diag_context["perf_details"].append({
                            "device": dev_label,
                            "interface": egress_intf,
                            "counters": counters,
                            "cpu": cpu_val
                        })
                    except Exception as e:
                        diag_context["perf_logs"] += f"Error gathering perf: {e}\n"

                    if platform_lower in ('huawei_vrp', 'h3c_comware'):
                        cmd_acl = f"display traffic-policy applied interface {egress_intf}"
                    elif platform_lower in ('juniper_junos',):
                        cmd_acl = f"show configuration interfaces {egress_intf}"
                    else:
                        cmd_acl = f"show ip interface {egress_intf} | include access-list"
                    diag_context["acl_logs"] += f"[{dev_label}]# {cmd_acl}\n"
                    try:
                        acl_out = await run_cmd(cmd_acl)
                        diag_context["acl_logs"] += acl_out + "\n"
                        acl_evidence = _classify_acl_evidence(
                            acl_out,
                            source_ip,
                            target_ip,
                            protocol,
                            port,
                            direction='egress',
                        )
                        acl_evidence.update({
                            'device': dev_label,
                            'device_id': dev.get('id'),
                            'interface': egress_intf,
                            'command': cmd_acl,
                        })
                        diag_context["acl_evidence"].append(acl_evidence)
                        if acl_evidence['decision'] == 'deny':
                            diag_context["acl_verified"] = False
                        elif (
                            acl_evidence['decision'] in {'permit', 'not_configured'}
                            and diag_context["acl_verified"] is not False
                        ):
                            diag_context["acl_verified"] = True
                    except Exception as e:
                        diag_context["acl_logs"] += f"Error: {e}\n"

            if not unique_paths:
                return [{
                    "hop": hop_count,
                    "ip": dev.get('ip_address'),
                    "device_name": dev_label,
                    "device_id": dev['id'],
                    "device_type": dev.get('role') or 'router',
                    "status": "blocked",
                    "detail": "无目标路由 (Routing blackhole)"
                }], "interrupted"

            is_direct = any(nh == "directly connected" or not nh or nh == "local" or "loopback" in intf.lower() for nh, intf in unique_paths)
            if is_direct:
                is_local_ip = False
                if target_ip.strip() == dev.get('ip_address', '').strip():
                    is_local_ip = True
                else:
                    try:
                        row_db = conn.execute(
                            "SELECT ip.address FROM ip_addresses ip WHERE ip.device_id = ? AND ip.address = ?",
                            (dev['id'], target_ip.strip())
                        ).fetchone()
                        if row_db:
                            is_local_ip = True
                        else:
                            row_inv = conn.execute(
                                "SELECT ip FROM ip_inventory WHERE device_id = ? AND ip = ?",
                                (dev['id'], target_ip.strip())
                            ).fetchone()
                            if row_inv:
                                is_local_ip = True
                    except Exception:
                        pass
                    
                    if not is_local_ip:
                        try:
                            local_hit = _check_local_device_ip(dev, target_ip, vrf)
                            if local_hit:
                                is_local_ip = True
                        except Exception:
                            pass
                
                if is_local_ip:
                    return [{
                        "hop": hop_count,
                        "ip": dev.get('ip_address'),
                        "device_name": dev_label,
                        "device_id": dev['id'],
                        "device_type": dev.get('role') or 'router',
                        "status": "active",
                        "detail": f"Reached target local interface"
                    }, {
                        "hop": hop_count + 1,
                        "ip": target_ip,
                        "device_name": "目标主机",
                        "device_id": None,
                        "device_type": "unknown",
                        "status": "active",
                        "detail": "到达目标 (环回口/本地接口)"
                    }], "reachable"

                use_vrf_arp = current_vrf if (current_vrf and current_vrf != 'default') else None
                if platform_lower in ('huawei_vrp', 'h3c_comware'):
                    cmd_arp = f"display arp vpn-instance {use_vrf_arp} | include {target_ip}" if use_vrf_arp else f"display arp | include {target_ip}"
                elif platform_lower in ('juniper_junos',):
                    cmd_arp = f"show arp table {use_vrf_arp} no-resolve | match {target_ip}" if use_vrf_arp else f"show arp no-resolve | match {target_ip}"
                else:
                    cmd_arp = f"show ip arp vrf {use_vrf_arp} {target_ip}" if use_vrf_arp else f"show ip arp {target_ip}"
                
                last_log += f"[{dev_label}]# {cmd_arp}\n"
                try:
                    arp_output = await run_cmd(cmd_arp)
                    last_log += arp_output + "\n"
                except Exception as e:
                    last_log += f"Error executing ARP check: {e}\n"
                    return [{
                        "hop": hop_count,
                        "ip": dev.get('ip_address'),
                        "device_name": dev_label,
                        "device_id": dev['id'],
                        "device_type": dev.get('role') or 'router',
                        "status": "blocked",
                        "detail": f"ARP查询失败: {e}"
                    }], "interrupted"

                current_hop = {
                    "hop": hop_count,
                    "ip": dev.get('ip_address'),
                    "device_name": dev_label,
                    "device_id": dev['id'],
                    "device_type": dev.get('role') or 'router',
                    "status": "active",
                    "detail": "directly connected",
                    "interface_name": unique_paths[0][1] if unique_paths else "",
                }

                if re.search(r'\b' + re.escape(target_ip) + r'\b', arp_output):
                    mac_m = re.search(r'([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}|[0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2})', arp_output)
                    mac_str = mac_m.group(1) if mac_m else "Unknown MAC"
                    return [current_hop, {
                        "hop": hop_count + 1,
                        "ip": target_ip,
                        "device_name": "目标主机",
                        "device_id": None,
                        "device_type": "unknown",
                        "status": "active",
                        "detail": f"到达目标 (MAC: {mac_str})"
                    }], "reachable"
                else:
                    return [current_hop, {
                        "hop": hop_count + 1,
                        "ip": target_ip,
                        "device_name": "目标主机",
                        "device_id": None,
                        "device_type": "unknown",
                        "status": "timeout",
                        "detail": "主机无响应 (ARP Missing)"
                    }], "interrupted"

            current_hop_detail = "ECMP Paths: " + ", ".join([f"{nh} via {intf}" for nh, intf in unique_paths]) if len(unique_paths) > 1 else f"Next-hop: {unique_paths[0][0]} via {unique_paths[0][1]}"
            current_hop = {
                "hop": hop_count,
                "ip": dev.get('ip_address'),
                "device_name": dev_label,
                "device_id": dev['id'],
                "device_type": dev.get('role') or 'router',
                "status": "active",
                "detail": current_hop_detail,
                "interface_name": unique_paths[0][1] if len(unique_paths) == 1 else "",
                "egress_interfaces": [intf for _, intf in unique_paths]
            }

            if platform_lower in ('huawei_vrp', 'h3c_comware'):
                cmd_neighbor = "display lldp neighbor"
            elif platform_lower in ('juniper_junos',):
                cmd_neighbor = "show lldp neighbors"
            else:
                cmd_neighbor = "show lldp neighbors"

            last_log += f"[{dev_label}]# {cmd_neighbor}\n"
            try:
                neighbor_output = await run_cmd(cmd_neighbor)
                last_log += neighbor_output + "\n"
            except Exception as e:
                last_log += f"Error executing neighbor check: {e}\n"
                neighbor_output = ""
                
            if "not enabled" in neighbor_output.lower() or "% lldp is not enabled" in neighbor_output.lower():
                # LLDP is the single neighbor protocol. Preserve the explicit
                # disabled state instead of silently switching to CDP.
                last_log += f"[{dev_label}]# LLDP disabled; neighbor discovery stopped\n"

            branches_results = []
            for nh, egress_intf in unique_paths[:2]:
                neighbor_host = parse_neighbors_output(neighbor_output, egress_intf, platform)
                neighbor_dev = lookup_neighbor_device(conn, neighbor_host, nh)
                
                if not neighbor_dev:
                    branches_results.append(([current_hop, {
                        "hop": hop_count + 1,
                        "ip": nh,
                        "device_name": neighbor_host or f"未知网关 ({nh})",
                        "device_id": None,
                        "device_type": "unknown",
                        "status": "timeout",
                        "detail": "无法跳转：未在系统资产中发现下一跳邻居设备"
                    }], "interrupted"))
                elif neighbor_dev['id'] in visited_ids:
                    branches_results.append(([current_hop, {
                        "hop": hop_count + 1,
                        "ip": neighbor_dev.get('ip_address'),
                        "device_name": neighbor_dev.get('hostname'),
                        "device_id": neighbor_dev['id'],
                        "device_type": neighbor_dev.get('role') or 'router',
                        "status": "blocked",
                        "detail": "检测到路由环路 (Routing loop detected)"
                    }], "interrupted"))
                else:
                    next_vrf = get_device_vrf_for_ip(conn, neighbor_dev['id'], nh)
                    if next_vrf != current_vrf:
                        diag_context["vrf_logs"] += f"[{dev_label}] (Online) Path crossed VRF boundary from {current_vrf} to {next_vrf} on neighbor {neighbor_dev.get('hostname')}\n"
                    sub_hops, sub_conclusion = await trace_recursive(neighbor_dev['id'], hop_count + 1, visited_ids, next_vrf)
                    branches_results.append(([current_hop] + sub_hops, sub_conclusion))

            if not branches_results:
                return [current_hop], "interrupted"
            elif len(branches_results) == 1:
                return branches_results[0][0], branches_results[0][1]
            else:
                merged = merge_hops(branches_results[0][0], branches_results[1][0])
                conclusion = "reachable" if all(c == "reachable" for _, c in branches_results) else "interrupted"
                return merged, conclusion

        except DeviceConnectionError as conn_err:
            last_log += f"Connection failed to {dev_label}: {conn_err}\n"
            return [{
                "hop": hop_count,
                "ip": dev.get('ip_address'),
                "device_name": dev_label,
                "device_id": dev['id'],
                "device_type": dev.get('role') or 'router',
                "status": "blocked",
                "detail": f"连接设备失败: {conn_err}"
            }], "interrupted"
        finally:
            if client is not None:
                try:
                    await asyncio.to_thread(client.disconnect)
                except Exception:
                    pass

    visited_ids = set()
    hops, conclusion = await trace_recursive(start_device_id, 1, visited_ids, vrf or 'default')
    return hops, conclusion, last_log, diag_context


_BEIJING_TZ = timezone(timedelta(hours=8))

def _beijing_now_iso() -> str:
    return datetime.now(_BEIJING_TZ).isoformat(timespec='seconds')


def _new_diagnosis_run_id() -> str:
    now = datetime.now(_BEIJING_TZ).strftime('%Y%m%d-%H%M%S')
    return f"NPA-{now}-{uuid.uuid4().hex[:4].upper()}"


def _snapshot_meta(run_id: str, source: str, collected_at: str | None = None, is_cached: bool = False, age_seconds: int = 0) -> dict:
    return {
        'run_id': run_id,
        'source': source,
        'collected_at': collected_at or _beijing_now_iso(),
        'age_seconds': max(0, int(age_seconds or 0)),
        'is_cached': bool(is_cached),
    }


async def _run_stabilized_probe(probe_args: dict, max_attempts: int = 3) -> tuple[dict, list[dict]]:
    """Run a probe immediately, then retry only after failure to observe convergence."""
    attempts: list[dict] = []
    last_result: dict = {'tests': {}}
    delays = (0, 2, 3)
    for attempt_no in range(max(1, max_attempts)):
        if attempt_no:
            await asyncio.sleep(delays[min(attempt_no, len(delays) - 1)])
        collected_at = _beijing_now_iso()
        try:
            last_result = await run_probe_async(**probe_args)
        except Exception as exc:
            last_result = {'tests': {}, 'error': str(exc)}
        ping_result = last_result.get('tests', {}).get('ping', {})
        tcp_results = last_result.get('tests', {}).get('tcp', [])
        tcp_result = tcp_results[0] if tcp_results else {}
        result = ping_result if 'ping' in probe_args.get('tests', []) else tcp_result
        success = bool(result.get('success'))
        attempts.append({
            'attempt': attempt_no + 1,
            'success': success,
            'loss_percent': result.get('loss_percent'),
            'latency_ms': result.get('rtt', {}).get('avg') if isinstance(result.get('rtt'), dict) else result.get('latency_ms'),
            'detail': result.get('detail') or last_result.get('error') or '',
            'collected_at': collected_at,
            'source': 'live_probe',
            'is_cached': False,
        })
        if success:
            break
    return last_result, attempts
async def run_diagnose_async(
    source_ip: str, 
    target_ip: str, 
    port: int = 443, 
    protocol: str = 'TCP',
    vrf: str = None,
    src_vrf: str = None
) -> dict:
    active_vrf = vrf or src_vrf
    diagnosis_run_id = _new_diagnosis_run_id()
    diagnosis_started_at = _beijing_now_iso()
    
    steps = []
    hops = []
    
    steps.append({"name": "P0. VRF 发现 (VRF Discovery)", "status": "pending", "message": "正在探测设备 VRF 上下文配置...", "log": ""})
    if active_vrf:
        steps[0].update({"status": "success", "message": f"已使用用户指定 VRF 路由上下文: {active_vrf}", "log": f"VRF Context Specified: {active_vrf}"})
    else:
        steps[0].update({"status": "success", "message": "未指定 VRF 上下文，默认使用全局路由表 (Global Table)。", "log": "No VRF context specified. Fallback to global table."})

    steps.append({"name": "P1. 资产发现 (Asset Discovery)", "status": "pending", "message": "正在查询源主机连接的物理资产与端口...", "log": ""})
    source_located = False
    locate_res = None
    source_dev_id = None
    source_dev_hostname = None

    # 先检查源 IP 是否为已知网络设备自身的管理 IP 或 IPAM 中的接口 IP
    conn = get_db_connection()
    try:
        # 1. 检查管理 IP
        row = conn.execute("SELECT id, hostname FROM devices WHERE TRIM(ip_address) = ?", (source_ip.strip(),)).fetchone()
        if row:
            source_dev_id = row['id']
            source_dev_hostname = row['hostname']
        else:
            # 2. 检查 IPAM 登记的设备接口 IP
            row_ip = conn.execute(
                "SELECT d.id, d.hostname FROM ip_addresses ip "
                "JOIN devices d ON ip.device_id = d.id "
                "WHERE TRIM(ip.address) = ?", (source_ip.strip(),)
            ).fetchone()
            if row_ip:
                source_dev_id = row_ip['id']
                source_dev_hostname = row_ip['hostname']
            else:
                row_inv = conn.execute(
                    "SELECT d.id, d.hostname FROM ip_inventory inv "
                    "JOIN devices d ON inv.device_id = d.id "
                    "WHERE TRIM(inv.ip) = ?", (source_ip.strip(),)
                ).fetchone()
                if row_inv:
                    source_dev_id = row_inv['id']
                    source_dev_hostname = row_inv['hostname']
    except Exception as e:
        logger.warning(f"Error pre-checking source_ip in DB: {e}")
    finally:
        conn.close()

    if source_dev_id:
        source_located = True
        steps[1].update({
            "status": "success",
            "message": f"定位成功：源 IP {source_ip} 为设备 {source_dev_hostname} 的本地接口/环回口，跳过接入交换机定位。",
            "log": f"Source IP {source_ip} is a local/loopback IP of network device {source_dev_hostname} (ID: {source_dev_id})."
        })
    else:
        try:
            # 不强刷新缓存，利用缓存提升性能并减少并发 SSH 风暴
            locate_res = await locate_ip_async_with_options(source_ip, force_refresh=False)
            if locate_res and locate_res.get('found') and locate_res.get('locations'):
                source_located = True
                locations = locate_res['locations']
                primary = next((l for l in locations if not l.get('is_uplink')), locations[0])
                steps[1].update({"status": "success", "message": f"定位成功：源主机 {source_ip} 接入交换机 {primary.get('switch_name')}:{primary.get('port')}", "log": f"Locate Result:\n{locate_res}"})
            else:
                steps[1].update({"status": "warning", "message": f"定位警告：未能在交换机 MAC 表中精确定位到 {source_ip}，将从默认网关发起追踪。", "log": "Locate Result: Not Found in MAC table. Proceeding via gateway route."})
        except Exception as e:
            steps[1].update({"status": "warning", "message": f"定位失败: {e}。将从服务器侧直接开始路径分析。", "log": f"Error: {e}"})

    steps.append({"name": "P2. 目标分类 (Target Classification)", "status": "pending", "message": "正在分析目标网段归属及类型...", "log": ""})

    # 如果前面定位或 IPAM 查询已经得出 source_dev_id，就不再重复查设备表
    if not source_dev_id and locate_res and locate_res.get('found') and locate_res.get('locations'):
        locations = locate_res['locations']
        primary = next((l for l in locations if not l.get('is_uplink')), locations[0])
        switch_name = primary.get('switch_name')
        if switch_name:
            conn = get_db_connection()
            try:
                row = conn.execute("SELECT id FROM devices WHERE hostname = ? OR TRIM(ip_address) = ?", (switch_name, switch_name.strip())).fetchone()
                if row:
                    source_dev_id = row['id']
            except Exception:
                pass
            finally:
                conn.close()

    arp_found = False
    arp_row = None
    if not source_dev_id:
        conn = get_db_connection()
        try:
            arp_row = conn.execute("SELECT * FROM arp_table WHERE TRIM(ip_address) = ? LIMIT 1", (source_ip.strip(),)).fetchone()
            if arp_row:
                arp_row = dict(arp_row)
                arp_row['target_ip'] = arp_row.get('ip_address')
                arp_row['mac'] = arp_row.get('mac_address')
                arp_row['arp_source'] = json.dumps({
                    'device_id': arp_row.get('device_id'),
                    'interface': arp_row.get('interface_name')
                })
                arp_found = True
                source_dev_id = arp_row.get('device_id')
        except Exception:
            pass
        finally:
            conn.close()

    is_direct_subnet = False
    if source_dev_id:
        dev = _load_device(source_dev_id)
        if dev:
            registry_result = await _execute_registry_diagnostic_action(
                dev,
                'get_route_table_vrf' if active_vrf else 'get_route_table',
                parameters={'vrf': active_vrf} if active_vrf else None,
            )
            if registry_result is not None:
                if registry_result.get('success'):
                    try:
                        target_obj = ipaddress.ip_address(target_ip)
                    except ValueError:
                        target_obj = None
                    for record in registry_result.get('records') or []:
                        prefix = str(record.get('prefix') or '').strip()
                        if not target_obj or not prefix:
                            continue
                        try:
                            network = ipaddress.ip_network(prefix, strict=False)
                        except ValueError:
                            continue
                        protocol = str(record.get('protocol') or record.get('route_type') or '').lower()
                        if target_obj in network and (not protocol or protocol in {'connected', 'local', 'direct'}):
                            is_direct_subnet = True
                            break
            else:
                platform = dev.get('platform') or 'cisco_ios'
                cmd = f"show ip route vrf {active_vrf} {target_ip}" if active_vrf else f"show ip route {target_ip}"
                if "huawei" in platform.lower() or "vrp" in platform.lower():
                    cmd = f"display ip routing-table vpn-instance {active_vrf} {target_ip}" if active_vrf else f"display ip routing-table {target_ip}"
                try:
                    route_out = await asyncio.to_thread(_send_command, dev, cmd, True)
                    if "directly connected" in route_out.lower() or "connected" in route_out.lower():
                        is_direct_subnet = True
                except Exception:
                    pass

    steps[2].update({"status": "success", "message": f"目标分类完成：目标 IP {target_ip} 属于 {'直连' if is_direct_subnet else '远程'} 网段。", "log": f"Subnet Classification: {'DIRECT_SUBNET' if is_direct_subnet else 'REMOTE_SUBNET'}"})

    steps.append({"name": "P3. ARP 分析 (ARP Analysis)", "status": "pending", "message": "正在获取双端 ARP 表项绑定记录...", "log": ""})
    arp_log = ""
    target_mac = ""
    if source_dev_id:
        dev = _load_device(source_dev_id)
        if dev:
            registry_result = await _execute_registry_diagnostic_action(
                dev,
                'get_arp_table_vrf' if active_vrf else 'get_arp_table',
                parameters={'vrf': active_vrf} if active_vrf else None,
            )
            if registry_result is not None:
                records = registry_result.get('records') or [] if registry_result.get('success') else []
                for record in records:
                    if str(record.get('ip') or record.get('ip_address') or '').strip() != target_ip:
                        continue
                    target_mac = str(record.get('mac') or record.get('mac_address') or '').strip()
                    break
                arp_log = f"[{dev.get('hostname')}] registry get_arp_table returned {len(records)} normalized record(s)\n"
            else:
                platform = dev.get('platform') or 'cisco_ios'
                cmd = f"show ip arp vrf {active_vrf} {target_ip}" if active_vrf else f"show ip arp {target_ip}"
                if "huawei" in platform.lower() or "vrp" in platform.lower():
                    cmd = f"display arp vpn-instance {active_vrf} | include {target_ip}" if active_vrf else f"display arp | include {target_ip}"
                try:
                    arp_out = await asyncio.to_thread(_send_command, dev, cmd, True)
                    arp_log += f"[{dev.get('hostname')}]# {cmd}\n{arp_out}\n"
                    if re.search(r'\b' + re.escape(target_ip) + r'\b', arp_out):
                        mac_m = re.search(r'([0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}|[0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2}[:\-][0-9a-fA-F]{2})', arp_out)
                        if mac_m:
                            target_mac = mac_m.group(1)
                except Exception as e:
                    arp_log += f"Error executing ARP check: {e}\n"

    if arp_found or target_mac:
        mac_to_show = target_mac or (arp_row.get('mac') if arp_row else 'N/A')
        steps[3].update({"status": "success", "message": f"ARP 分析成功：在网关上获取到 IP 对应的 MAC 绑定 ({mac_to_show})。", "log": arp_log or f"ARP Cache entry found in database: MAC={mac_to_show}"})
    else:
        if is_direct_subnet:
            arp_message = "ARP 缺失：直连网段未获取到目标 MAC，目标可能静默或离线。"
        else:
            arp_message = "ARP 未发现：目标属于远程网段，源设备未持有目标主机 ARP；该结果仅作辅助证据，不判定二层正常或异常。"
        steps[3].update({"status": "warning", "message": arp_message, "log": arp_log or "No ARP cache entry found in database or real-time query.", "snapshot": _snapshot_meta(diagnosis_run_id, 'live_cli', _beijing_now_iso())})

    steps.append({"name": "P4. MAC 定位 (MAC Analysis)", "status": "pending", "message": "正在交换机 MAC 转发表中跟踪物理端口与 STP...", "log": ""})
    mac_norm = target_mac.replace('.', '').replace(':', '').replace('-', '').lower() if target_mac else ""
    mac_log = ""
    if mac_norm and source_dev_id:
        dev = _load_device(source_dev_id)
        if dev and (dev.get('role') or '').lower() in ('switch', 'access', 'distribution', 'core', 'l2', 'l3switch'):
            registry_result = await _execute_registry_diagnostic_action(
                dev,
                'get_mac_table_vrf' if active_vrf else 'get_mac_table',
                parameters={'vrf': active_vrf} if active_vrf else None,
            )
            if registry_result is not None:
                records = registry_result.get('records') or [] if registry_result.get('success') else []
                matching_records = [
                    record for record in records
                    if str(record.get('mac') or record.get('mac_address') or '').replace('.', '').replace(':', '').replace('-', '').lower() == mac_norm
                ]
                if matching_records:
                    mac_log = f"[{dev.get('hostname')}] registry get_mac_table matched {len(matching_records)} normalized record(s)\n"
            else:
                cmd = f"show mac address-table address {target_mac}"
                try:
                    mac_out = await asyncio.to_thread(_send_command, dev, cmd, True)
                    mac_log += f"[{dev.get('hostname')}]# {cmd}\n{mac_out}\n"
                except Exception as e:
                    mac_log += f"MAC Check Error: {e}\n"
    
    steps[4].update({"status": "success" if mac_log else "warning", "message": "MAC 定位查询已执行，结果需结合实时接口状态确认。" if mac_log else "未定位到目标主机的二层物理交换机端口，不能据此判定二层链路正常。", "log": mac_log or "No switch port tracking needed for remote subnet route hops.", "snapshot": _snapshot_meta(diagnosis_run_id, 'live_cli' if mac_log else 'derived')})

    steps.append({"name": "P4.5. 实时接口链路验证 (Live Interface Validation)", "status": "pending", "message": "正在实时核验路径出接口及目标接入接口状态...", "log": ""})
    endpoint_state_task = (
        asyncio.create_task(_collect_target_endpoint_state(target_ip))
        if source_dev_id else None
    )

    steps.append({"name": "P5. 路由递归 (Route Recursion)", "status": "pending", "message": "正在执行多跳路由路径递归追踪...", "log": ""})
    trace_success = False
    trace_conclusion = "interrupted"
    trace_log = ""
    diag_context = {}
    return_hops: list[dict] = []
    return_trace_log = ""
    return_path_status = 'unavailable'
    return_path_reason = '目标 IP 未映射到可执行设备侧路由查询的受管网络设备。'
    return_trace_conclusion = 'unknown'
    target_managed_device = None
    
    if source_dev_id:
        conn = get_db_connection()
        try:
            target_managed_device = _managed_device_by_ip(conn, target_ip)
            hops, trace_conclusion, trace_log, diag_context = await trace_route_path_async(
                conn,
                source_dev_id,
                target_ip,
                active_vrf,
                source_ip=source_ip,
                protocol=protocol,
                port=port,
            )
            trace_success = True
            if target_managed_device and str(target_managed_device.get('id')) != str(source_dev_id):
                try:
                    (
                        return_hops,
                        return_trace_conclusion,
                        return_trace_log,
                        _return_diag_context,
                    ) = await trace_route_path_async(
                        conn,
                        str(target_managed_device['id']),
                        source_ip,
                        active_vrf,
                        source_ip=target_ip,
                        protocol=protocol,
                        port=port,
                    )
                    return_path_status = 'collected'
                    return_path_reason = (
                        f"已从受管目标设备 {target_managed_device.get('hostname') or target_managed_device['id']} "
                        f"执行回程路由递归。"
                    )
                except Exception as exc:
                    return_path_status = 'failed'
                    return_path_reason = f'回程设备侧路由递归失败：{exc}'
                    return_trace_log = f'Error during return-path recursive trace: {exc}'
            elif target_managed_device:
                return_path_status = 'same_device'
                return_path_reason = '源与目标映射到同一受管设备，不执行独立回程递归。'
        except Exception as e:
            trace_log = f"Error during recursive trace: {e}\n"
        finally:
            conn.close()

    hops = _annotate_hop_interfaces(hops)
    return_hops = _annotate_hop_interfaces(return_hops)

    if trace_success:
        if trace_conclusion == "reachable":
            steps[6].update({
                "status": "success",
                "message": f"路径连通：路径递归成功，共跳转 {len(hops)} 个三层中继节点。",
                "log": trace_log
            })
        else:
            interrupted_reason = "中间中继节点断开"
            if hops:
                last_h = hops[-1]
                interrupted_reason = f"路径停止在第 {last_h['hop']} 跳: {last_h['device_name']} ({last_h['detail']})"
            steps[6].update({
                "status": "warning",
                "message": f"路径中断：{interrupted_reason}。",
                "log": trace_log
            })
    else:
        steps[6].update({
            "status": "warning",
            "message": "未能执行设备侧递归路由跟踪，回退到全局默认路由表寻路。",
            "log": "Recursive routing trace skipped / failed."
        })

    endpoint_state = {}
    if endpoint_state_task:
        try:
            endpoint_state = await endpoint_state_task
        except Exception as exc:
            endpoint_state = {'state': 'unknown', 'source': 'endpoint_refresh_error', 'error': str(exc)}
    path_interface_evidence = await _validate_path_interfaces(hops, endpoint_state)
    diag_context['endpoint_state'] = endpoint_state
    diag_context['path_interface_states'] = path_interface_evidence.get('records', [])
    interface_down = path_interface_evidence.get('down', [])
    interface_degraded = path_interface_evidence.get('degraded', [])
    interface_unknown = path_interface_evidence.get('unknown', [])
    if interface_down:
        for item in interface_down:
            matching_hop = next(
                (hop for hop in hops if str(hop.get('device_id') or '') == str(item.get('device_id') or '')
                 and normalize_interface_name(hop.get('interface_name')).lower() == normalize_interface_name(item.get('interface_name')).lower()),
                None,
            )
            if matching_hop:
                matching_hop['status'] = 'blocked'
                matching_hop['detail'] = f"实时接口验证失败：{item.get('device_name')} {item.get('interface_name')} 当前 DOWN"
    p45_lines = [
        f"[{item.get('device_name')}] {item.get('interface_name')} "
        f"admin={item.get('admin_status', 'unknown')} oper={item.get('oper_status', 'unknown')} "
        f"health={item.get('health', item.get('state', 'unknown'))} "
        f"source={item.get('source', 'unknown')} collected_at={item.get('collected_at', '')}"
        for item in path_interface_evidence.get('records', [])
    ]
    if interface_down:
        p45_status = 'failed'
        p45_message = f"实时接口验证失败：发现 {len(interface_down)} 个接口 DOWN，已覆盖历史拓扑/路由可达结论。"
    elif interface_unknown:
        p45_status = 'warning'
        p45_message = f"实时接口验证不完整：{len(interface_unknown)} 个接口无法确认当前状态。"
    elif interface_degraded:
        p45_status = 'warning'
        p45_message = f"实时接口验证完成：接口 UP，但发现 {len(interface_degraded)} 个接口存在错误计数或异常标志。"
    elif path_interface_evidence.get('records'):
        p45_status = 'success'
        p45_message = "实时接口验证完成：路径出接口和目标接入接口状态均已实时确认。"
    else:
        p45_status = 'warning'
        p45_message = "未找到可验证的路径接口，不能把历史拓扑状态当作实时链路结论。"
    steps[5].update({
        'status': p45_status,
        'message': p45_message,
        'log': '\n'.join(p45_lines) or 'No live path interface evidence collected.',
        'evidence': path_interface_evidence,
    })

    # ── P5.5: FIB 验证 ──
    steps.append({"name": "P5.5. FIB 验证 (FIB Verification)", "status": "pending", "message": "正在验证控制面路由与转发面 CEF/FIB 的一致性...", "log": ""})
    cef_ok = diag_context.get("cef_verified")
    cef_logs = diag_context.get("cef_logs") or "No CEF/FIB evidence collected."
    if cef_ok is True:
        cef_status = 'success'
        cef_message = "FIB 转发面校验成功：已采集的控制面路由与转发面条目一致。"
    elif cef_ok is False:
        cef_status = 'failed'
        cef_message = "FIB 转发故障：检测到软硬件路由表项失配或硬件转发面缺失该路由。"
    else:
        cef_status = 'warning'
        cef_message = "FIB 转发面状态未知：未采集到足够的实时 CEF/FIB 证据，不能默认判定正常。"
    steps[7].update({
        "status": cef_status,
        "message": cef_message,
        "log": cef_logs
    })

    # ── P6: 策略分析 ──
    steps.append({"name": "P6. 策略分析 (Policy Analysis)", "status": "pending", "message": "正在匹配链路上的 ACL/NAT/QoS 安全过滤策略...", "log": ""})
    acl_logs = diag_context.get("acl_logs") or "No ACL attachment evidence collected."
    acl_ok = diag_context.get("acl_verified")
    acl_evidence = diag_context.get("acl_evidence") or []
    if acl_ok is False:
        acl_status = 'failed'
        acl_message = "安全策略阻断：实时证据中发现与当前五元组相关的显式拒绝规则。"
    elif acl_ok is True:
        acl_status = 'success'
        acl_message = "安全策略校验完成：已采集的出方向证据未发现阻断当前五元组的规则。"
    else:
        acl_status = 'warning'
        acl_message = "安全策略状态未知：策略未采集、命令失败或仅发现绑定关系但尚未完成规则级五元组模拟。"
    steps[8].update({
        "status": acl_status,
        "message": acl_message,
        "log": acl_logs,
        "evidence": acl_evidence,
    })

    # ── P6.5: BGP 分析 ──
    steps.append({"name": "P6.5. BGP 分析 (BGP Analysis)", "status": "pending", "message": "正在检查 BGP 路由传导及控制策略状态...", "log": ""})
    bgp_ok = diag_context.get("bgp_verified")
    bgp_logs = diag_context.get("bgp_logs") or "No BGP evidence collected."
    is_bgp_route = any(r.get("source") == "BGP" for r in diag_context.get("route_sources", []))
    
    if is_bgp_route:
        steps[9].update({
            "status": "success" if bgp_ok is True else "failed" if bgp_ok is False else "warning",
            "message": (
                "BGP 控制平面分析完成：已采集证据显示路由在边界自治系统正常安装。"
                if bgp_ok is True
                else "BGP 路由异常：检测到路由未激活、未安装或被策略过滤。"
                if bgp_ok is False
                else "BGP 状态未知：未采集到足够的实时 BGP 路由证据。"
            ),
            "log": bgp_logs
        })
    else:
        steps[9].update({
            "status": "success",
            "message": "目标网段不是 BGP 路由，跳过 BGP 控制策略校验。",
            "log": "Route source is OSPF/Static. BGP verification skipped."
        })

    # ── P7: Overlay 分析 ──
    steps.append({"name": "P7. Overlay 分析 (Overlay Analysis)", "status": "pending", "message": "正在检查底层 VXLAN/IPsec 等隧道封装状态...", "log": ""})
    steps[10].update({
        "status": "warning",
        "message": "Overlay 状态未知：本次路径采集未包含足以排除 VXLAN/IPsec/GRE 封装的实时隧道证据。",
        "log": "Overlay/tunnel evidence was not collected; absence of evidence is not treated as native forwarding."
    })

    # ── P7.5: HA 分析 ──
    steps.append({"name": "P7.5. HA 分析 (HA Analysis)", "status": "pending", "message": "正在校验设备冗余双机(HSRP/VRRP)健康状态...", "log": ""})
    ha_ok = diag_context.get("ha_verified")
    ha_logs = diag_context.get("ha_logs") or "No HA evidence collected."
    steps[11].update({
        "status": "success" if ha_ok is True else "failed" if ha_ok is False else "warning",
        "message": (
            "HA 状态校验完成：已采集证据显示网关冗余角色正常。"
            if ha_ok is True
            else "HA 状态异常：检测到双 Master 脑裂或冗余组异常。"
            if ha_ok is False
            else "HA 状态未知：未采集到足够的实时冗余协议证据。"
        ),
        "log": ha_logs
    })

    # ── P8: 验证探测 ──
    icmp_success = False
    tcp_success = False
    icmp_attempts: list[dict] = []
    tcp_attempts: list[dict] = []
    if protocol.upper() == 'ICMP':
        steps.append({"name": "P8. ICMP 验证 (ICMP Validation)", "status": "pending", "message": f"正在向目标 {target_ip} 发起 ICMP Ping 验证探测...", "log": ""})
        icmp_detail = ""
        ping_log = ""
        try:
            probe_args = {
                "target": target_ip,
                "tests": ['ping'],
                "source_device_id": source_dev_id,
                "source_interface": source_ip if source_dev_id else '',
            }
            icmp_probe, icmp_attempts = await _run_stabilized_probe(probe_args)
            ping_res = icmp_probe.get('tests', {}).get('ping', {})
            icmp_success = ping_res.get('success', False)
            loss_percent = ping_res.get('loss_percent', 100)
            avg_rtt = ping_res.get('rtt', {}).get('avg', None)
            rtt_str = f"延迟 {avg_rtt} ms" if avg_rtt is not None else ""
            icmp_detail = f"丢包率 {loss_percent}%" + (f", {rtt_str}" if rtt_str else "")
            ping_log = ping_res.get('output', '')
        except Exception as e:
            icmp_detail = f"Probe Error: {e}"
            ping_log = f"Error: {e}"

        if icmp_success:
            steps[12].update({
                "status": "success",
                "message": f"ICMP 探测成功：目标主机 {target_ip} Ping 响应正常 ({icmp_detail})，共执行 {len(icmp_attempts)} 轮实时验证。",
                "log": (ping_log or f"Ping to {target_ip} -> Success ({icmp_detail})") + f"\nProbe attempts: {json.dumps(icmp_attempts, ensure_ascii=False)}",
                "probe_attempts": icmp_attempts,
                "snapshot": _snapshot_meta(diagnosis_run_id, 'live_probe', icmp_attempts[-1].get('collected_at') if icmp_attempts else None)
            })
        else:
            steps[12].update({
                "status": "failed",
                "message": f"ICMP 验证失败：Ping 探测未收到响应 ({icmp_detail})。已以源设备 {source_ip} 的设备侧探测结果为准，不能用历史路由/ARP 记录判定目标当前可达。",
                "log": (ping_log or f"Ping to {target_ip} -> Failed ({icmp_detail})") + f"\nProbe attempts: {json.dumps(icmp_attempts, ensure_ascii=False)}",
                "probe_attempts": icmp_attempts,
                "snapshot": _snapshot_meta(diagnosis_run_id, 'live_probe', icmp_attempts[-1].get('collected_at') if icmp_attempts else None)
            })
    else:
        steps.append({"name": f"P8. {protocol} 验证 ({protocol} Validation)", "status": "pending", "message": f"正在向目标发起 {protocol} 端口 {port} 验证探测...", "log": ""})
        tcp_detail = ""
        try:
            tcp_probe, tcp_attempts = await _run_stabilized_probe({
                'target': target_ip,
                'tests': ['tcp'],
                'tcp_ports': [port],
            })
            tcp_res_list = tcp_probe.get('tests', {}).get('tcp', [])
            tcp_success = tcp_res_list and tcp_res_list[0].get('success')
            tcp_detail = tcp_res_list[0].get('detail', 'Connection timed out') if tcp_res_list else 'Connection timed out'
        except Exception as e:
            tcp_detail = f"Probe Error: {e}"

        if tcp_success:
            steps[12].update({
                "status": "success",
                "message": f"{protocol} 探测成功：已顺利完成与目标 {target_ip}:{port} 的连接建立，共执行 {len(tcp_attempts)} 轮实时验证。",
                "log": f"{protocol} Probe to {target_ip}:{port} -> Success\nProbe attempts: {json.dumps(tcp_attempts, ensure_ascii=False)}",
                "probe_attempts": tcp_attempts,
                "snapshot": _snapshot_meta(diagnosis_run_id, 'live_probe', tcp_attempts[-1].get('collected_at') if tcp_attempts else None)
            })
        else:
            steps[12].update({
                "status": "failed",
                "message": f"{protocol} 验证失败：未能建立 {protocol} 连接 ({tcp_detail})。当前探测未收到响应，不能据此判断物理链路正常。",
                "log": f"{protocol} Probe to {target_ip}:{port} -> Failed ({tcp_detail})\nProbe attempts: {json.dumps(tcp_attempts, ensure_ascii=False)}",
                "probe_attempts": tcp_attempts,
                "snapshot": _snapshot_meta(diagnosis_run_id, 'live_probe', tcp_attempts[-1].get('collected_at') if tcp_attempts else None)
            })

    if endpoint_state.get('state') == 'down':
        hops = _mark_endpoint_down(hops, target_ip, endpoint_state)
        trace_conclusion = "interrupted"

    # ── P8.5: 性能分析 ──
    steps.append({"name": "P8.5. 性能分析 (Performance Analysis)", "status": "pending", "message": "正在收集出接口计数器错包与 CPU 负荷...", "log": ""})
    # P5 is a control-plane/path inference step. P8 is the current data-plane
    # observation. A failed probe must downgrade the rendered target hop even
    # when an old route/ARP snapshot made P5 look reachable.
    probe_success = icmp_success if protocol.upper() == 'ICMP' else tcp_success
    if not probe_success and hops:
        target_hop = next(
            (hop for hop in reversed(hops) if str(hop.get('ip') or '').strip() == target_ip.strip()),
            None,
        )
        if target_hop:
            target_hop['status'] = 'timeout'
            target_hop['detail'] = (
                f"当前 {protocol.upper()} 探测未收到响应；控制平面路径或历史 ARP/MAC 命中不代表目标端当前可达。"
            )

    perf_logs = diag_context.get("perf_logs") or "No live performance evidence collected."
    perf_warning = diag_context.get("perf_warning")
    if perf_warning is True:
        perf_status = 'warning'
        perf_message = "端口性能校验警告：路径接口存在错包、丢包或 CPU 过载。"
    elif perf_warning is False:
        perf_status = 'success'
        perf_message = "性能校验完成：已采集接口计数器和 CPU 证据，未发现设定阈值异常。"
    else:
        perf_status = 'warning'
        perf_message = "性能状态未知：未采集到完整的实时接口计数器或设备负载证据。"
    steps[13].update({
        "status": perf_status,
        "message": perf_message,
        "log": perf_logs
    })
    evidence_quality = _derive_evidence_quality(
        diag_context,
        path_interface_evidence,
        return_path_status=return_path_status,
    )
    evidence_gaps = evidence_quality['gaps']

    # ── P9: AI 根因推导 ──
    steps.append({"name": "P9. AI 根因推导 (AI Root Cause Engine)", "status": "pending", "message": "正在对比网络专家库推导核心故障点...", "log": ""})
    
    confidence = "95%"
    evidence = []
    
    has_success = icmp_success if protocol.upper() == 'ICMP' else tcp_success
    endpoint_state = diag_context.get("endpoint_state") or {}
    endpoint_down = endpoint_state.get("state") == "down"
    has_success = bool(has_success)
    p3_arp_missing = steps[3].get('status') == 'warning'
    p4_mac_missing = steps[4].get('status') == 'warning'
    p8_desc = f"P8 {protocol} 探测"
    p3_evidence = "P3 ARP：缺失/未知（不作为当前二层正常结论）" if p3_arp_missing else "P3 ARP：已获取或对远程目标不适用"
    p4_evidence = "P4 MAC：未完成精确定位" if p4_mac_missing else "P4 MAC：已执行定位或对远程目标不适用"
    if endpoint_down:
        confidence = "99%"
        endpoint_name = endpoint_state.get('device_name') or endpoint_state.get('device_id') or '最后一跳接入交换机'
        endpoint_port = endpoint_state.get('interface_name') or '接入端口'
        evidence = [
            "P5 路由递归仅证明控制平面存在路径",
            f"最后一跳 {endpoint_name} {endpoint_port} 已通过实时 TextFSM 接口快照确认 DOWN",
            f"P8 {protocol} 探测失败",
        ]
    elif trace_conclusion == "reachable" and has_success:
        confidence = "95%"
        evidence = [p3_evidence, p4_evidence, "P5 路由递归路径可达", f"{p8_desc}当前实时探测正常"]
    elif trace_conclusion == "reachable" and not has_success:
        confidence = "90%"
        evidence = [
            "P5 路由递归仅提供控制面路径线索，不能证明当前数据面连通",
            f"{p8_desc}未收到响应（以源设备实时探测结果为准）",
            "应优先核查最后一跳接口、上下联链路及 VLAN/Trunk 状态",
        ]
    elif cef_ok is False:
        confidence = "95%"
        evidence = ["P5.5 FIB 验证控制面与 ASIC 转发项失配 (硬件路由黑洞)"]
    elif trace_conclusion == "interrupted":
        confidence = "97%"
        evidence = ["P5 路由中间节点超时丢包 / 无回程路由", p3_evidence, p4_evidence]
        
    steps[14].update({
        "status": "success",
        "message": f"AI 根因推导完成：判定置信度为 {confidence}。推导证据链已生成。",
        "log": f"[AI Engine] Analyzing Telemetry...\nEvidence Checklist:\n" + "\n".join([f"- {e}" for e in evidence]) + f"\nConfidence: {confidence}"
    })

    live_interface_down = bool(endpoint_state.get('state') == 'down' or interface_down)
    evidence_conflicts: list[str] = []
    if has_success and live_interface_down:
        evidence_conflicts.append('P8 当前实时探测成功，但 P4.5 实时接口状态发现 DOWN；需要核对目标 IP 到接口的绑定关系。')
    if has_success and trace_conclusion != 'reachable':
        evidence_conflicts.append('P8 当前实时探测成功，但 P5 路径递归未得出可达结论；不能把任一历史结果单独作为根因。')
    if has_success and is_direct_subnet and p3_arp_missing:
        evidence_conflicts.append('直连网段的 P3 ARP 未发现目标，但 P8 当前实时探测成功；ARP 采集或目标接口定位需要复核。')

    # Every step receives the same run identity.  Older cache/telemetry can be
    # retained as auxiliary evidence, but it cannot silently enter this run's
    # primary conclusion.
    finished_at = _beijing_now_iso()
    for step in steps:
        step.setdefault('snapshot', _snapshot_meta(diagnosis_run_id, 'derived', finished_at, is_cached=False))
        step.setdefault('run_id', diagnosis_run_id)
    if evidence_conflicts:
        confidence = '40%'
        evidence = evidence_conflicts + [
            f'P8 当前结果：{"成功" if has_success else "失败"}',
            f'P3 ARP：{"缺失/未知" if p3_arp_missing else "已获取或不适用"}',
            f'P4 MAC：{"未完成" if p4_mac_missing else "已执行或不适用"}',
            'P4.5 已执行实时接口复核，冲突状态要求重新刷新关键节点后再确认。',
        ]
        steps[14].update({
            'status': 'warning',
            'message': '证据一致性检查发现冲突：已降低置信度，禁止生成确定性根因。',
            'log': '[Evidence Conflict]\n' + '\n'.join(evidence),
            'evidence_conflicts': evidence_conflicts,
        })
    elif evidence_gaps:
        numeric_confidence = int(str(confidence).rstrip('%') or 0)
        confidence = f"{min(numeric_confidence, evidence_quality['confidence_cap'])}%"
        evidence = evidence + [f"证据缺口：{gap}" for gap in evidence_gaps]
        steps[14].update({
            'status': 'warning',
            'message': f"根因推导仅形成候选结论：证据不完整，置信度上限为 {confidence}。",
            'log': (
                '[Incomplete Evidence]\n'
                + '\n'.join(f'- {item}' for item in evidence_gaps)
                + f'\nConfidence cap: {confidence}'
            ),
            'evidence_gaps': evidence_gaps,
        })

    steps.append({"name": "P9.5. 证据一致性检查 (Evidence Consistency)", "status": "pending", "message": "正在核对本次实时探测、接口、ARP 与路径证据...", "log": ""})
    steps[15].update({
        'status': 'warning' if evidence_conflicts or evidence_gaps else 'success',
        'message': (
            '存在证据冲突，已阻止高置信度根因输出。'
            if evidence_conflicts
            else '证据链不完整，未知项已显式列出并限制置信度。'
            if evidence_gaps
            else '证据一致性检查通过：本次诊断结果使用同一运行快照。'
        ),
        'log': (
            '\n'.join(evidence_conflicts)
            if evidence_conflicts
            else '\n'.join(evidence_gaps)
            if evidence_gaps
            else 'No evidence conflicts or gaps detected.'
        ),
        'evidence_conflicts': evidence_conflicts,
        'evidence_gaps': evidence_gaps,
        'snapshot': _snapshot_meta(diagnosis_run_id, 'derived', finished_at),
    })

    # ── P10: 智能报告 ──
    steps.append({"name": "P10. 智能报告 (Smart Report)", "status": "pending", "message": "正在汇总报告输出...", "log": ""})
    steps[16].update({
        "status": "success",
        "message": "智能诊断报告已成功生成。",
        "log": "Smart NPA Report formatted."
    })
    for step in steps:
        step.setdefault('snapshot', _snapshot_meta(diagnosis_run_id, 'derived', finished_at, is_cached=False))
        step.setdefault('run_id', diagnosis_run_id)

    blocked_hop = next((h for h in hops if h["status"] == "blocked"), None)
    arp_missing_hop = next((h for h in hops if h["status"] == "timeout" and "ARP Missing" in h["detail"]), None)
    diagnostic_status = 'incomplete_evidence' if evidence_gaps else 'confirmed'
    
    if evidence_conflicts:
        diagnostic_status = 'evidence_conflict'
        interrupted_at = '证据一致性检查'
        conclusion = 'interrupted'
        reason = '；'.join(evidence_conflicts)
        impact = '当前诊断证据互相矛盾，暂时不能确认唯一根因'
        suggestion = '请强制刷新路径设备、最后一跳接口和 ARP/MAC 后重新诊断；在冲突消除前，不执行面向主机或策略层的确定性修复。'
        repair_commands = '# Evidence conflict: refresh live interface/route/ARP/MAC evidence and rerun diagnosis.'
    elif endpoint_down:
        endpoint_name = endpoint_state.get('device_name') or endpoint_state.get('device_id') or '最后一跳接入交换机'
        endpoint_port = endpoint_state.get('interface_name') or '接入端口'
        interrupted_at = f"{endpoint_name} {endpoint_port}"
        conclusion = "interrupted"
        reason = (
            f"最后一跳接口 {interrupted_at} 当前为 DOWN（admin={endpoint_state.get('admin_status', 'unknown')}, "
            f"oper={endpoint_state.get('oper_status', 'unknown')}）。此前的 ARP/MAC/拓扑记录属于定位线索，不能证明当前物理链路正常。"
        )
        impact = f"目标 {target_ip} 的 {protocol.upper()} 探测被最后一跳接入端口阻断"
        suggestion = f"请登录 {endpoint_name} 检查 {endpoint_port}，确认是否误执行 shutdown，并恢复接口后重新执行诊断。"
        repair_commands = f"interface {endpoint_port}\nundo shutdown  # Huawei VRP\nno shutdown    # Cisco/H3C"
    elif interface_down:
        failed_interface = interface_down[0]
        endpoint_name = failed_interface.get('device_name') or failed_interface.get('device_id') or '路径设备'
        endpoint_port = failed_interface.get('interface_name') or '出接口'
        interrupted_at = f"{endpoint_name} {endpoint_port}"
        conclusion = 'interrupted'
        reason = f"P4.5 实时接口验证确认 {interrupted_at} 当前 DOWN；该实时结果优先于历史路由、ARP 和拓扑记录。"
        impact = f"路径在 {interrupted_at} 处无法继续转发"
        suggestion = f"请登录 {endpoint_name} 检查 {endpoint_port} 的 admin/oper 状态、对端接口、VLAN/Trunk 和接口告警，恢复后重新执行三轮验证。"
        repair_commands = f"interface {endpoint_port}\ndisplay interface {endpoint_port}\nundo shutdown  # Huawei VRP\nno shutdown    # Cisco/H3C"
    elif blocked_hop:
        interrupted_at = blocked_hop["device_name"]
        conclusion = "interrupted"
        reason = f"在路径节点 {interrupted_at} 处路由不可达 ({blocked_hop['detail']})"
        if protocol.upper() == 'ICMP':
            impact = f"无法对目标主机 {target_ip} 进行 Ping 探测"
        else:
            impact = f"无法访问 {target_ip} 的 {port} 端口服务"
        suggestion = f"请登录设备 {interrupted_at}，检查路由表配置，确保拥有到达目标网段 {target_ip} 的有效静态或动态路由条目。"
        repair_commands = f"configure terminal\n ip route {target_ip} 255.255.255.255 <下一跳地址>\n end\n write memory"
    elif not has_success:
        # P8 is the current data-plane observation. It must override a stale
        # route/ARP snapshot and must never produce a reachable conclusion.
        last_hop = next((hop for hop in reversed(hops) if hop.get("device_name")), None)
        endpoint_name = endpoint_state.get('device_name') or (last_hop or {}).get('device_name') or '最后一跳接入链路'
        endpoint_port = endpoint_state.get('interface_name') or (last_hop or {}).get('interface_name') or '接入接口'
        interrupted_at = f"{endpoint_name} {endpoint_port}" if endpoint_port else endpoint_name
        conclusion = "interrupted"
        if protocol.upper() == 'ICMP':
            reason = (
                f"P8 源设备侧 ICMP 探测未收到 {target_ip} 的响应（100% 丢包或超时）。"
                "P5 路由递归及 ARP/MAC 记录只能作为控制面定位线索，不能覆盖当前数据面失败结果。"
            )
            impact = f"目标 {target_ip} 当前不可达，ICMP 探测失败"
        else:
            reason = (
                f"P8 源设备侧 {protocol} {port} 探测未建立连接。"
                "P5 路由递归及 ARP/MAC 记录只能作为控制面定位线索，不能覆盖当前数据面失败结果。"
            )
            impact = f"目标 {target_ip}:{port} 当前不可达或服务未响应"
        if arp_missing_hop:
            reason += f" 最后一跳未发现目标主机 {target_ip} 的实时 ARP 记录。"
        if cef_ok is False:
            reason += " 同时，P5.5 实时证据显示控制面路由与 FIB/CEF 转发表不一致。"
        suggestion = (
            f"1. 先登录最后一跳设备 {endpoint_name}，检查 {endpoint_port} 的 admin/oper 状态，确认没有误执行 shutdown；"
            "\n2. 检查该接口上下联、VLAN/Trunk、MAC/ARP 学习及链路告警，恢复链路后重新执行诊断；"
            "\n3. 只有确认链路恢复且探测仍失败时，再检查目标主机防火墙或应用端口监听。"
        )
        repair_commands = f"# 请先在最后一跳设备核对接口状态\ninterface {endpoint_port}\ndisplay interface {endpoint_port}\nundo shutdown  # Huawei VRP\nno shutdown    # Cisco/H3C"
    elif arp_missing_hop:
        interrupted_at = "直连网段"
        conclusion = "interrupted"
        reason = f"最后一跳路由网关成功转发，但直连网络中未发现目标主机 {target_ip} 的 ARP 记录"
        impact = f"由于目标主机未开机或网络断开，导致业务无法连通"
        suggestion = f"1. 请检查目标主机 {target_ip} 是否已开机，网卡是否启用，IP 地址配置是否正确。\n2. 检查直连交换机/路由器接口的 VLAN 和 Trunk 配置，确保广播包可正常传输。"
        repair_commands = f"# 建议检查直连交换机接口配置：\ninterface <interface_name>\n switchport access vlan <vlan_id>\n no shutdown"
    elif trace_conclusion == "reachable":
        conclusion = "reachable"
        interrupted_at = ""
        reason = "P8 当前源设备实时探测成功；P5 路径递归未发现实时阻断。"
        if p3_arp_missing:
            reason += " P3 未获取目标 ARP，当前仅作为未知/辅助证据，不能表述为 ARP 正常。"
        impact = "物理及逻辑网络已连通"
        suggestion = "当前实时探测可达；若业务仍异常，请结合目标端口、应用层响应和策略日志继续核查，不把历史 ARP/MAC 快照作为当前结论。"
        repair_commands = "# 链路状态完好，无需配置修复建议。"
    else:
        interrupted_at = "网络核心网关"
        conclusion = "interrupted"
        reason = f"路径递归跟踪未完成，或中间跳超时"
        if protocol.upper() == 'ICMP':
            impact = f"无法对目标主机 {target_ip} 进行 Ping 探测"
        else:
            impact = f"无法访问 {target_ip} 的 {port} 端口服务"
        suggestion = f"请根据第 5 步路径跟踪日志排查中间节点的可达性和配置。"
        repair_commands = "# 无法自动给出具体修复建议，请结合跟踪日志排障。"

    # ── 回填最终探测的真实往返延迟 (RTT) ──
    final_latency = None
    if protocol.upper() == 'ICMP':
        if 'icmp_success' in locals() and icmp_success and 'avg_rtt' in locals() and avg_rtt is not None:
            final_latency = avg_rtt
    else:
        if 'tcp_success' in locals() and tcp_success and 'tcp_res_list' in locals() and tcp_res_list:
            final_latency = tcp_res_list[0].get('latency_ms', None)
            
    if final_latency is not None and hops:
        hops[-1]['rtt_ms'] = [final_latency]

    return {
        "success": True,
        "timestamp": _beijing_now_iso(),
        "diagnosis_run_id": diagnosis_run_id,
        "snapshot": {
            "run_id": diagnosis_run_id,
            "started_at": diagnosis_started_at,
            "finished_at": _beijing_now_iso(),
            "primary_sources": {
                "probe": "live_probe",
                "interfaces": "live_textfsm",
                "route": "live_cli" if diag_context.get('force_live_route') else "route_cache",
                "arp": "live_cli" if source_dev_id else "unknown",
                "return_path": "live_cli" if return_path_status == 'collected' else "unknown",
            },
            "route_cache_hits": diag_context.get('route_cache_hits', 0),
            "command_cache_hits": diag_context.get('command_cache_hits', 0),
            "evidence_conflicts": evidence_conflicts,
            "evidence_gaps": evidence_gaps,
            "is_cached": False,
        },
        "source_ip": source_ip,
        "target_ip": target_ip,
        "port": port,
        "protocol": protocol,
        "steps": steps,
        "hops": hops,
        "forward_path": {
            "status": "collected" if trace_success else "failed",
            "conclusion": trace_conclusion,
            "hops": hops,
            "log": trace_log,
        },
        "return_path": {
            "status": return_path_status,
            "conclusion": return_trace_conclusion,
            "hops": return_hops,
            "reason": return_path_reason,
            "log": return_trace_log,
            "source_device": (
                {
                    "id": target_managed_device.get('id'),
                    "hostname": target_managed_device.get('hostname'),
                }
                if target_managed_device
                else None
            ),
        },
        "report": {
            "conclusion": conclusion,
            "interrupted_at": interrupted_at if conclusion == "interrupted" else "",
            "reason": reason,
            "impact": impact,
            "suggestion": suggestion,
            "confidence": confidence,
            "evidence": evidence,
            "diagnostic_status": diagnostic_status,
            "evidence_conflicts": evidence_conflicts,
            "evidence_gaps": evidence_gaps,
            "evidence_quality": evidence_quality,
            "acl_evidence": diag_context.get('acl_evidence', []),
            "interface_states": diag_context.get('path_interface_states', []),
            "probe_attempts": icmp_attempts if protocol.upper() == 'ICMP' else tcp_attempts,
            "repair_commands": repair_commands
        }
    }
