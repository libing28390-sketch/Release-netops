import sys
import os
import asyncio
import json
import uuid
import logging
from datetime import datetime, timedelta, timezone
from urllib import request as urlrequest
from urllib import error as urlerror
from ping3 import ping
from database import get_db_connection
from core.config import settings
from services import notification_service
from services import alert_maintenance_service
from services import alert_rule_service
import re as _re
import time as _time
from services.snmp_service import collect_device_metrics, collect_device_info, collect_interface_data
from services.operational_data_service import collect_operational_data
from api.topology import discover_lldp_neighbors
from core.crypto import decrypt_credential

logger = logging.getLogger(__name__)

def _db_quick(sql, params=(), fetch=False, fetchall=False):
    """Execute a quick DB operation with its own connection (no long locks)."""
    conn = get_db_connection()
    try:
        if fetchall:
            return conn.execute(sql, params).fetchall()
        elif fetch:
            return conn.execute(sql, params).fetchone()
        else:
            conn.execute(sql, params)
            conn.commit()
    finally:
        conn.close()

def _db_many(sql, rows):
    if not rows:
        return
    conn = get_db_connection()
    try:
        conn.executemany(sql, rows)
        conn.commit()
    finally:
        conn.close()


def _as_dict(row):
    if isinstance(row, dict):
        return row
    return dict(row)

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

_CST = timezone(timedelta(hours=8))

def _local_now_str() -> str:
    """返回 CST 本地时间字符串，用于通知显示。"""
    return datetime.now(_CST).strftime('%Y-%m-%d %H:%M:%S')

def _send_webhook_notification(payload: dict):
    webhook = (settings.ALERT_NOTIFY_WEBHOOK_URL or '').strip()
    if not webhook:
        return
    data = json.dumps(payload).encode('utf-8')
    req = urlrequest.Request(
        webhook,
        data=data,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urlrequest.urlopen(req, timeout=5) as resp:
            if resp.status >= 400:
                logger.warning(f"[Alert] Webhook responded with status {resp.status}")
    except urlerror.URLError as exc:
        logger.warning(f"[Alert] Webhook send failed: {exc}")

def _create_alert_event(
    dedupe_key: str,
    severity: str,
    title: str,
    message: str,
    device_id: str,
    interface_name: str | None = None,
    workflow_status: str = 'open',
    note: str = '',
):
    alert_id = str(uuid.uuid4())
    now_utc = _utc_now_iso()
    now_local = _local_now_str()
    _db_quick('''
        INSERT INTO alert_events (
            id, dedupe_key, source, severity, title, message, device_id, interface_name,
            created_at, resolved_at, workflow_status, note, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
    ''', (alert_id, dedupe_key, 'network_monitor', severity, title, message, device_id, interface_name, now_utc, workflow_status, note, now_utc))
    return alert_id, now_local

def _resolve_alert_event(dedupe_key: str):
    now = _utc_now_iso()
    _db_quick('''
        UPDATE alert_events
        SET resolved_at = ?, workflow_status = 'resolved', updated_at = ?
        WHERE dedupe_key = ? AND resolved_at IS NULL
    ''', (now, now, dedupe_key))

def _run_telemetry_maintenance():
    # Roll up raw 5s telemetry to 1-minute table and enforce retention windows.
    now = datetime.now(timezone.utc)
    raw_cutoff = (now - timedelta(hours=max(1, settings.TELEMETRY_RAW_RETENTION_HOURS))).replace(microsecond=0).isoformat()
    rollup_cutoff = (now - timedelta(days=max(1, settings.TELEMETRY_ROLLUP_RETENTION_DAYS))).replace(microsecond=0).isoformat()
    recent_window = (now - timedelta(hours=2)).replace(microsecond=0).isoformat()

    _db_quick('''
        INSERT INTO interface_telemetry_1m (
            ts_minute, device_id, interface_name, samples,
            avg_in_bps, max_in_bps, avg_out_bps, max_out_bps,
            avg_bw_in_pct, max_bw_in_pct, avg_bw_out_pct, max_bw_out_pct,
            in_pkts_sum, out_pkts_sum,
            err_delta_sum, discard_delta_sum
        )
        SELECT
            substr(ts, 1, 16) || ':00+00:00' AS ts_minute,
            device_id,
            interface_name,
            COUNT(*) AS samples,
            AVG(in_bps),
            MAX(in_bps),
            AVG(out_bps),
            MAX(out_bps),
            AVG(bw_in_pct),
            MAX(bw_in_pct),
            AVG(bw_out_pct),
            MAX(bw_out_pct),
            SUM(COALESCE(in_pkts, 0)),
            SUM(COALESCE(out_pkts, 0)),
            SUM(COALESCE(in_errors, 0) + COALESCE(out_errors, 0)),
            SUM(COALESCE(in_discards, 0) + COALESCE(out_discards, 0))
        FROM interface_telemetry_raw
        WHERE ts >= ?
        GROUP BY ts_minute, device_id, interface_name
        ON CONFLICT (ts_minute, device_id, interface_name) DO UPDATE SET
          samples=excluded.samples,
          avg_in_bps=excluded.avg_in_bps, max_in_bps=excluded.max_in_bps,
          avg_out_bps=excluded.avg_out_bps, max_out_bps=excluded.max_out_bps,
          avg_bw_in_pct=excluded.avg_bw_in_pct, max_bw_in_pct=excluded.max_bw_in_pct,
          avg_bw_out_pct=excluded.avg_bw_out_pct, max_bw_out_pct=excluded.max_bw_out_pct,
          in_pkts_sum=excluded.in_pkts_sum, out_pkts_sum=excluded.out_pkts_sum,
          err_delta_sum=excluded.err_delta_sum, discard_delta_sum=excluded.discard_delta_sum
    ''', (recent_window,))

    _db_quick('DELETE FROM interface_telemetry_raw WHERE ts < ?', (raw_cutoff,))
    _db_quick('DELETE FROM interface_telemetry_1m WHERE ts_minute < ?', (rollup_cutoff,))
    # Keep resolved alerts for one year while preserving open alerts.
    alert_cutoff = (now - timedelta(days=365)).replace(microsecond=0).isoformat()
    _db_quick('DELETE FROM alert_events WHERE resolved_at IS NOT NULL AND resolved_at < ?', (alert_cutoff,))

    # Prune stale topology links not refreshed in the last 24 hours.
    link_stale_cutoff = (now - timedelta(hours=24)).replace(microsecond=0).isoformat()
    try:
        deleted = _db_quick(
            'SELECT COUNT(*) AS cnt FROM topology_links WHERE last_seen IS NOT NULL AND last_seen < ?',
            (link_stale_cutoff,), fetch=True,
        )
        stale_count = deleted['cnt'] if deleted else 0
        if stale_count > 0:
            _db_quick('DELETE FROM topology_links WHERE last_seen IS NOT NULL AND last_seen < ?', (link_stale_cutoff,))
            logger.info(f"[Maintenance] Pruned {stale_count} stale topology link(s) older than 24 hours")
    except Exception as exc:
        logger.warning(f"[Maintenance] Failed to prune stale links: {exc}")

# --- GLOBAL TELEMETRY STATE ---
open_alerts = {}
protocol_peer_cache = {}
protocol_transition_history = {}
protocol_notify_suppressed_until = {}
protocol_flap_window_secs = 600
protocol_flap_threshold = 5
protocol_flap_silence_secs = 1800
snmp_failure_streak = {}
intf_flap_history = {}
prev_intf_octets = {}
webhook_last_sent = {}
current_alert_rules = []
role_poll_profiles = {
    'core': {
        'interface': 1,
        'info': 10,
        'protocol': 2,
    },
    'distribution': {
        'interface': 1,
        'info': 10,
        'protocol': 5,
    },
    'access': {
        'interface': 1,
        'info': 10,
        'protocol': 10,
    },
    'default': {
        'interface': 1,
        'info': 10,
        'protocol': 5,
    }
}
FLAP_WINDOW_SECS = 600
FLAP_THRESHOLD = 4
protocol_aggregate_threshold = 3
protocol_aggregate_sample_size = 3
COUNTER32_MAX = 2**32
COUNTER64_MAX = 2**64
monitor_concurrency = 20 if sys.platform != "win32" else 2
_sem = None
def _get_semaphore():
    global _sem
    if _sem is None:
        _sem = asyncio.Semaphore(monitor_concurrency)
    return _sem
def _init_telemetry_state():
    global current_alert_rules
    from services import alert_rule_service
    try:
        _open_rows = _db_quick("SELECT dedupe_key, created_at FROM alert_events WHERE resolved_at IS NULL", fetchall=True)
        if _open_rows:
            for _row in _open_rows:
                _ts_raw = _row["created_at"]
                try:
                    from datetime import datetime
                    _dt = datetime.fromisoformat(_ts_raw).astimezone(_CST)
                    _ts_local = _dt.strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    _ts_local = _ts_raw
                open_alerts[_row["dedupe_key"]] = _ts_local
    except Exception as e:
        pass
    try:
        _protocol_rows = _db_quick("SELECT metric_type, device_id, peer, object_name FROM protocol_peer_state", fetchall=True)
        for _row in _protocol_rows or []:
            _cache_key = (str(_row["metric_type"] or ""), str(_row["device_id"] or ""))
            protocol_peer_cache.setdefault(_cache_key, {})[str(_row["peer"] or "")] = str(_row["object_name"] or _row["peer"] or "")
    except Exception:
        pass
    current_alert_rules = alert_rule_service.get_runtime_rules()
_init_telemetry_state()
def resolve_alert_rule(metric_type: str, *, device_row=None, ip_address: str = '', interface_name: str | None = None):
    context = {
        'device_id': device_row['id'] if device_row else '',
        'hostname': device_row['hostname'] if device_row else '',
        'ip_address': ip_address,
        'site': device_row['site'] if device_row else '',
        'interface_name': interface_name or '',
    }
    return alert_rule_service.select_rule(current_alert_rules, metric_type, context)

def metric_type_from_dedupe_key(dedupe_key: str) -> str | None:
    if dedupe_key.startswith('cpu_high:'):
        return 'cpu'
    if dedupe_key.startswith('mem_high:'):
        return 'memory'
    if dedupe_key.startswith('if_util:'):
        return 'interface_util'
    if dedupe_key.startswith('temp_high:'):
        return 'temperature_high'
    if dedupe_key.startswith('snmp_unreachable:'):
        return 'snmp_unreachable'
    if dedupe_key.startswith('lldp_neighbor_lost:'):
        return 'lldp_neighbor_lost'
    if dedupe_key.startswith('fan_failure:'):
        return 'fan_failure'
    if dedupe_key.startswith('psu_failure:'):
        return 'power_supply_failure'
    if dedupe_key.startswith('if_error_rate:'):
        return 'interface_error_rate_high'
    if dedupe_key.startswith('if_flap:'):
        return 'interface_flap'
    if dedupe_key.startswith('bgp_neighbor_down:'):
        return 'bgp_neighbor_down'
    if dedupe_key.startswith('ospf_neighbor_down:'):
        return 'ospf_neighbor_down'
    if dedupe_key.startswith('bfd_session_down:'):
        return 'bfd_session_down'
    if dedupe_key.startswith('interconnect_down:'):
        return 'interconnect_down'
    if dedupe_key.startswith('if_down:'):
        return 'interface_down'
    return None

def _device_role_bucket(device_row: dict) -> str:
    role_haystack = ' '.join(
        str(device_row.get(field) or '').strip().lower()
        for field in ('role', 'hostname', 'platform', 'site')
    )
    if any(token in role_haystack for token in ('core', 'border', 'edge', 'spine')):
        return 'core'
    if any(token in role_haystack for token in ('distribution', 'dist', 'aggregation', 'agg', 'leaf')):
        return 'distribution'
    if any(token in role_haystack for token in ('access', 'l2')):
        return 'access'
    return 'default'

def _device_poll_profile(device_row: dict) -> dict[str, int]:
    return role_poll_profiles.get(_device_role_bucket(device_row), role_poll_profiles['default'])

def _should_collect(cycle_tick: int, every_cycles: int) -> bool:
    return every_cycles <= 1 or cycle_tick % every_cycles == 0

def _is_protocol_peer_alert_key(dedupe_key: str) -> bool:
    return any(dedupe_key.startswith(f'{metric}:') for metric in ('bgp_neighbor_down', 'ospf_neighbor_down', 'bfd_session_down')) and ':summary:' not in dedupe_key and ':flap:' not in dedupe_key

def _protocol_metric_label(metric_type: str) -> str:
    return {
        'bgp_neighbor_down': 'BGP 邻居',
        'ospf_neighbor_down': 'OSPF 邻居',
        'bfd_session_down': 'BFD 会话',
    }.get(metric_type, metric_type)

def _protocol_transition_notify_allowed(dedupe_key: str) -> bool:
    if not _is_protocol_peer_alert_key(dedupe_key):
        return True
    now_ts = datetime.now(timezone.utc).timestamp()
    suppressed_until = protocol_notify_suppressed_until.get(dedupe_key, 0)
    history = [ts for ts in protocol_transition_history.get(dedupe_key, []) if now_ts - ts <= protocol_flap_window_secs]
    history.append(now_ts)
    protocol_transition_history[dedupe_key] = history
    if len(history) >= protocol_flap_threshold:
        next_until = now_ts + protocol_flap_silence_secs
        protocol_notify_suppressed_until[dedupe_key] = max(suppressed_until, next_until)
        logger.warning(
            f"[Protocol Monitor] Suppressing notifications for {dedupe_key} until {datetime.fromtimestamp(protocol_notify_suppressed_until[dedupe_key], timezone.utc).isoformat()} due to frequent state changes"
        )
        return False
    return suppressed_until <= now_ts

def _is_protocol_notification_suppressed(dedupe_key: str) -> bool:
    return protocol_notify_suppressed_until.get(dedupe_key, 0) > datetime.now(timezone.utc).timestamp()

def load_topology_ports(device_id: str) -> set[str]:
    rows = _db_quick(
        '''
                    SELECT source_device_id, target_device_id, source_port_normalized, target_port_normalized
        FROM topology_links
        WHERE (source_device_id = ? OR target_device_id = ?)
          AND COALESCE(is_inferred, 0) = 0
        ''',
        (device_id, device_id),
        fetchall=True,
    ) or []
    ports: set[str] = set()
    for row in rows:
        source_port = str(row['source_port_normalized'] or '').strip().lower()
        target_port = str(row['target_port_normalized'] or '').strip().lower()
        if str(row['source_device_id'] or '') == device_id and source_port:
            ports.add(source_port)
        if str(row['target_device_id'] or '') == device_id and target_port:
            ports.add(target_port)
    return ports

def load_persisted_interface_statuses(device_id: str) -> dict[str, str]:
    rows = _db_quick(
        '''
        SELECT latest.interface_name, latest.status
        FROM interface_telemetry_raw AS latest
        JOIN (
            SELECT interface_name, MAX(ts) AS max_ts
            FROM interface_telemetry_raw
            WHERE device_id = ?
            GROUP BY interface_name
        ) AS snapshot
          ON latest.interface_name = snapshot.interface_name
         AND latest.ts = snapshot.max_ts
        WHERE latest.device_id = ?
        ''',
        (device_id, device_id),
        fetchall=True,
    ) or []
    return {
        str(row['interface_name'] or ''): str(row['status'] or '').lower()
        for row in rows
        if str(row['interface_name'] or '').strip()
    }

def persist_protocol_peer_state(metric_type: str, device_id: str, peers: dict[str, str]):
    _db_quick(
        "DELETE FROM protocol_peer_state WHERE metric_type = ? AND device_id = ?",
        (metric_type, device_id),
    )
    if not peers:
        return
    now_iso = _utc_now_iso()
    _db_many(
        '''
        INSERT INTO protocol_peer_state (metric_type, device_id, peer, object_name, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ''',
        [
            (metric_type, device_id, peer, object_name, now_iso)
            for peer, object_name in peers.items()
        ],
    )

def sync_lldp_neighbor_alerts():
    links = _db_quick(
        '''
        SELECT l.*, s.status AS source_status, t.status AS target_status
        FROM topology_links l
        JOIN devices s ON l.source_device_id = s.id
        JOIN devices t ON l.target_device_id = t.id
        ''',
        fetchall=True,
    ) or []
    active_keys: set[str] = set()

    for row in links:
        link = dict(row)
        dedupe_key = f"lldp_neighbor_lost:{link.get('link_key') or link.get('id')}"
        active_keys.add(dedupe_key)
        source_online = str(link.get('source_status') or '').lower() == 'online'
        target_online = str(link.get('target_status') or '').lower() == 'online'
        is_lost = str(link.get('status') or '').lower() == 'stale' and source_online and target_online
        interface_name = f"{link.get('source_port_normalized') or link.get('source_port') or ''}->{link.get('target_port_normalized') or link.get('target_port') or ''}"
        rule = resolve_alert_rule('lldp_neighbor_lost', device_row={'id': link.get('source_device_id'), 'hostname': link.get('source_hostname') or '', 'site': '', 'ip_address': ''}, ip_address='', interface_name=interface_name)
        set_alert_state(
            dedupe_key,
            is_lost,
            (rule or {}).get('severity', 'major'),
            'LLDP Neighbor Lost',
            (
                f"链路 {link.get('source_hostname') or link.get('source_device_id')}:{link.get('source_port')} -> {link.get('target_hostname') or link.get('target_device_id')}:{link.get('target_port')} 未在最新邻居发现中出现"
                if is_lost else
                f"链路 {link.get('source_hostname') or link.get('source_device_id')}:{link.get('source_port')} -> {link.get('target_hostname') or link.get('target_device_id')}:{link.get('target_port')} 已重新被邻居发现"
            ),
            str(link.get('source_device_id') or ''),
            interface_name,
            ip_address='',
            status='active' if is_lost else 'resolved',
            rule=rule,
        )

    for dedupe_key in list(open_alerts.keys()):
        if dedupe_key.startswith('lldp_neighbor_lost:') and dedupe_key not in active_keys:
            set_alert_state(dedupe_key, False, 'major', 'LLDP Neighbor Lost', 'LLDP 邻居关系已恢复', '', None, status='resolved')

def _normalize_protocol_text(value) -> str:
    return str(value or '').strip().lower()

def _record_value(record: dict, exact_keys: tuple[str, ...], fuzzy_tokens: tuple[str, ...] = ()) -> str:
    lowered = {str(key).lower(): value for key, value in (record or {}).items()}
    for key in exact_keys:
        if key in lowered and str(lowered[key]).strip():
            return str(lowered[key]).strip()
    if fuzzy_tokens:
        for key, value in lowered.items():
            if any(token in key for token in fuzzy_tokens) and str(value).strip():
                return str(value).strip()
    return ''

def _protocol_state_display(metric_type: str, record: dict) -> str:
    if metric_type == 'bgp_neighbor_down':
        raw_state = _record_value(record, ('state_pfxrcd', 'state', 'status', 'session_state'), ('state', 'status'))
        normalized = _normalize_protocol_text(raw_state)
        if normalized.isdigit():
            return f"Established/Prefix={raw_state}"
        return raw_state or 'unknown'
    if metric_type == 'ospf_neighbor_down':
        return _record_value(record, ('state', 'adj_state', 'adjacency_state', 'status'), ('state', 'status')) or 'unknown'
    return _record_value(record, ('state', 'status', 'session_state'), ('state', 'status')) or 'unknown'

def _bgp_peer_state(record: dict) -> tuple[str, bool | None]:
    peer = _record_value(record, ('neighbor', 'peer', 'peer_ip', 'neighbor_ip', 'remote_addr', 'remote_ip'), ('neighbor', 'peer', 'remote'))
    state = _record_value(record, ('state_pfxrcd', 'state', 'status', 'session_state'), ('state', 'status'))
    normalized_state = _normalize_protocol_text(state)
    if not peer or not normalized_state:
        return peer, None
    if normalized_state.isdigit() or 'established' in normalized_state or normalized_state == 'up':
        return peer, False
    down_tokens = ('idle', 'active', 'connect', 'down', 'opensent', 'openconfirm', 'admin')
    if any(token in normalized_state for token in down_tokens):
        return peer, True
    return peer, None

def _ospf_peer_state(record: dict) -> tuple[str, bool | None]:
    peer = _record_value(record, ('neighbor_id', 'neighbor', 'router_id', 'address', 'ip_address'), ('neighbor', 'router', 'address'))
    state = _record_value(record, ('state', 'adj_state', 'adjacency_state', 'status'), ('state', 'status'))
    normalized_state = _normalize_protocol_text(state)
    if not peer or not normalized_state:
        return peer, None
    if 'full' in normalized_state or '2way' in normalized_state:
        return peer, False
    down_tokens = ('down', 'init', 'exstart', 'exchange', 'attempt', 'loading')
    if any(token in normalized_state for token in down_tokens):
        return peer, True
    return peer, None

def _bfd_peer_state(record: dict) -> tuple[str, str, bool | None]:
    peer = _record_value(
        record,
        ('neighbor_addr', 'neighbor_address', 'peer', 'neighbor', 'peer_ip', 'neighbor_ip', 'address', 'dest_addr', 'remote_addr'),
        ('neighbor', 'peer', 'address', 'remote'),
    )
    interface_name = _record_value(record, ('interface', 'intf', 'local_interface'), ('interface', 'intf'))
    state = _record_value(record, ('state', 'status', 'session_state'), ('state', 'status'))
    normalized_state = _normalize_protocol_text(state)
    if not peer or not normalized_state:
        return peer, interface_name, None
    if normalized_state == 'up':
        return peer, interface_name, False
    down_tokens = ('down', 'admindown', 'admin-down', 'init', 'fail', 'failed')
    if any(token in normalized_state for token in down_tokens):
        return peer, interface_name, True
    return peer, interface_name, None

async def _collect_protocol_neighbor_alerts(device_row: dict, ip_address: str):
    username = str(device_row.get('username') or '').strip()
    decrypted_password = decrypt_credential(device_row.get('password')) or ''
    if not username or not decrypted_password:
        return

    device_info = dict(device_row)
    device_info['password'] = decrypted_password
    try:
        payload = await asyncio.to_thread(collect_operational_data, device_info, ['bgp', 'ospf', 'bfd'])
    except Exception as exc:
        logger.debug(f"[Protocol Monitor] {ip_address} collection failed: {exc}")
        return

    categories = {str(item.get('key') or ''): item for item in (payload.get('categories') or []) if isinstance(item, dict)}
    def _sync_protocol_category(metric_type: str, category_key: str, title: str):
        category = categories.get(category_key, {})
        if not category or not bool(category.get('success')):
            return

        previous_peers = protocol_peer_cache.get((metric_type, device_row['id']), {})
        current_peers: dict[str, str] = {}
        peer_events: list[dict] = []
        records = category.get('records') or []

        for record in records:
            if not isinstance(record, dict):
                continue

            if metric_type == 'bgp_neighbor_down':
                peer, is_down = _bgp_peer_state(record)
                object_name = peer
            elif metric_type == 'ospf_neighbor_down':
                peer, is_down = _ospf_peer_state(record)
                object_name = peer
            else:
                peer, interface_name, is_down = _bfd_peer_state(record)
                object_name = interface_name or peer

            if not peer:
                continue

            current_peers[peer] = object_name or peer
            if is_down is None:
                continue

            state_display = _protocol_state_display(metric_type, record)
            if metric_type == 'bgp_neighbor_down':
                active_message = f"BGP 邻居 {peer} 状态由 UP 变为 DOWN（当前状态: {state_display}）"
                resolved_message = f"BGP 邻居 {peer} 状态由 DOWN 恢复为 UP（当前状态: {state_display}）"
                missing_message = f"BGP 邻居 {peer} 上一轮为 UP，本轮未采集到，按 DOWN 处理"
            elif metric_type == 'ospf_neighbor_down':
                active_message = f"OSPF 邻居 {peer} 状态由 UP 变为 DOWN（当前状态: {state_display}）"
                resolved_message = f"OSPF 邻居 {peer} 状态由 DOWN 恢复为 UP（当前状态: {state_display}）"
                missing_message = f"OSPF 邻居 {peer} 上一轮为 UP，本轮未采集到，按 DOWN 处理"
            else:
                suffix = f" ({interface_name})" if interface_name else ''
                active_message = f"BFD 会话 {peer}{suffix} 状态由 UP 变为 DOWN（当前状态: {state_display}）"
                resolved_message = f"BFD 会话 {peer}{suffix} 状态由 DOWN 恢复为 UP（当前状态: {state_display}）"
                missing_message = f"BFD 会话 {peer}{suffix} 上一轮为 UP，本轮未采集到，按 DOWN 处理"

            peer_events.append({
                'dedupe_key': f"{metric_type}:{device_row['id']}:{peer}",
                'peer': peer,
                'object_name': current_peers[peer],
                'is_down': bool(is_down),
                'message': active_message if is_down else resolved_message,
            })

        for peer, object_name in previous_peers.items():
            if peer in current_peers:
                continue

            if metric_type == 'bgp_neighbor_down':
                missing_message = f"BGP 邻居 {peer} 上一轮为 UP，本轮未采集到，按 DOWN 处理"
            elif metric_type == 'ospf_neighbor_down':
                missing_message = f"OSPF 邻居 {peer} 上一轮为 UP，本轮未采集到，按 DOWN 处理"
            else:
                missing_suffix = f" ({object_name})" if object_name and object_name != peer else ''
                missing_message = f"BFD 会话 {peer}{missing_suffix} 上一轮为 UP，本轮未采集到，按 DOWN 处理"

            peer_events.append({
                'dedupe_key': f"{metric_type}:{device_row['id']}:{peer}",
                'peer': peer,
                'object_name': object_name,
                'is_down': True,
                'message': missing_message,
            })

        down_peers = [str(event['peer']) for event in peer_events if event['is_down']]
        aggregate_active = len(down_peers) >= protocol_aggregate_threshold
        for event in peer_events:
            rule = resolve_alert_rule(metric_type, device_row=device_row, ip_address=ip_address, interface_name=event['object_name'])
            if not rule:
                continue
            set_alert_state(
                event['dedupe_key'],
                event['is_down'],
                rule.get('severity', 'critical'),
                title,
                event['message'],
                device_row['id'],
                event['object_name'],
                ip_address=ip_address,
                status='active' if event['is_down'] else 'resolved',
                rule=rule,
                notify=not aggregate_active,
            )

        protocol_peer_cache[(metric_type, device_row['id'])] = current_peers
        persist_protocol_peer_state(metric_type, device_row['id'], current_peers)
        _sync_protocol_aggregate_alert(metric_type, title, device_row, ip_address, down_peers)
        flapping_peers = [peer for peer in down_peers if _is_protocol_notification_suppressed(f"{metric_type}:{device_row['id']}:{peer}")]
        _sync_protocol_flap_alert(metric_type, title, device_row, ip_address, flapping_peers)

    _sync_protocol_category('bgp_neighbor_down', 'bgp', 'BGP Neighbor Down')
    _sync_protocol_category('ospf_neighbor_down', 'ospf', 'OSPF Neighbor Down')
    _sync_protocol_category('bfd_session_down', 'bfd', 'BFD Session Down')

def _set_protocol_alerts_for_device_offline(device_row: dict, ip_address: str):
    metric_titles = {
        'bgp_neighbor_down': 'BGP Neighbor Down',
        'ospf_neighbor_down': 'OSPF Neighbor Down',
        'bfd_session_down': 'BFD Session Down',
    }
    for metric_type, title in metric_titles.items():
        peer_map = protocol_peer_cache.get((metric_type, device_row['id']), {})
        down_peers: list[str] = []
        if peer_map:
            logger.info(
                f"[Protocol Monitor] Device {ip_address} offline, marking {len(peer_map)} {metric_type} peer(s) as down"
            )
        aggregate_active = len(peer_map) >= protocol_aggregate_threshold
        for peer, object_name in peer_map.items():
            rule = resolve_alert_rule(metric_type, device_row=device_row, ip_address=ip_address, interface_name=object_name)
            if not rule:
                continue
            down_peers.append(peer)
            if metric_type == 'bgp_neighbor_down':
                message = f"设备离线，BGP 邻居 {peer} 上一轮为 UP，现按 DOWN 处理"
            elif metric_type == 'ospf_neighbor_down':
                message = f"设备离线，OSPF 邻居 {peer} 上一轮为 UP，现按 DOWN 处理"
            else:
                suffix = f" ({object_name})" if object_name and object_name != peer else ''
                message = f"设备离线，BFD 会话 {peer}{suffix} 上一轮为 UP，现按 DOWN 处理"
            set_alert_state(
                f"{metric_type}:{device_row['id']}:{peer}",
                True,
                rule.get('severity', 'critical'),
                title,
                message,
                device_row['id'],
                object_name,
                ip_address=ip_address,
                status='active',
                rule=rule,
                notify=not aggregate_active,
            )
        _sync_protocol_aggregate_alert(metric_type, title, device_row, ip_address, down_peers)
        _sync_protocol_flap_alert(metric_type, title, device_row, ip_address, [])

def maybe_notify_webhook(dedupe_key: str, severity: str, title: str, message: str,
                           created_at: str, ip_address: str = '', object_name: str = '',
                           status: str = 'active', last_occurrence: str = '',
                           duration_seconds=None, impact_window=None, alert_count=None,
                           reopened_after_maintenance: bool = False,
                           rule: dict | None = None):
    now_ts = datetime.now(timezone.utc)
    repeat_window_seconds = max(0, int((rule or {}).get('notification_repeat_window_seconds', 120) or 0))
    if status == 'active' and not bool((rule or {}).get('notify_on_active', True)):
        return
    if status == 'resolved' and not bool((rule or {}).get('notify_on_recovery', True)):
        webhook_last_sent.pop(dedupe_key, None)
        return
    if reopened_after_maintenance and not bool((rule or {}).get('notify_on_reopen_after_maintenance', True)):
        return
    # 恢复通知不受节流限制，且清除节流记录（为下次触发做准备）
    if status == 'resolved':
        webhook_last_sent.pop(dedupe_key, None)
    else:
        last_ts = webhook_last_sent.get(dedupe_key)
        if last_ts and repeat_window_seconds > 0 and (now_ts - last_ts).total_seconds() < repeat_window_seconds:
            return
        webhook_last_sent[dedupe_key] = now_ts

    alert_info = {
        'title':            title,
        'object_name':      object_name or dedupe_key,
        'ip_address':       ip_address,
        'status':           status,
        'severity':         severity,
        'message':          message,
        'first_occurrence': created_at,
        'last_occurrence':  last_occurrence or created_at,
    }
    if duration_seconds is not None:
        alert_info['duration_seconds'] = duration_seconds
    if impact_window is not None:
        alert_info['impact_window'] = impact_window
    if alert_count is not None:
        alert_info['alert_count'] = alert_count

    # 1. 全局 webhook（.env 配置，纯文字兼容）
    if (settings.ALERT_NOTIFY_WEBHOOK_URL or '').strip():
        plain = (
            f"[{severity.upper()}] {title}\n"
            f"对象: {object_name}  IP: {ip_address}\n"
            f"{message}\n"
            f"时间: {created_at}"
        )
        payload = {"msgtype": "text", "text": {"content": plain}}
        asyncio.create_task(asyncio.to_thread(_send_webhook_notification, payload))

    def _dispatch_user_channels():
        try:
            user_alert = {**alert_info, 'lang': 'zh'}
            notification_service.dispatch_to_all_users(user_alert)
        except Exception as exc:
            logger.warning(f"[Alert] Workspace channel dispatch failed: {exc}")

    asyncio.create_task(asyncio.to_thread(_dispatch_user_channels))

def set_alert_state(dedupe_key: str, is_active: bool, severity: str, title: str, message: str,
                     device_id: str, interface_name: str | None = None,
                     ip_address: str = '', status: str = '', rule: dict | None = None,
                     notify: bool = True):
    currently_open = open_alerts.get(dedupe_key)
    if is_active and not currently_open:
        maintenance_window = alert_maintenance_service.find_active_window_for_alert({
            'dedupe_key': dedupe_key,
            'severity': severity,
            'title': title,
            'message': message,
            'device_id': device_id,
            'interface_name': interface_name,
            'ip_address': ip_address,
        })
        workflow_status = 'suppressed' if maintenance_window else 'open'
        note = f"Suppressed by maintenance window: {maintenance_window['name']}" if maintenance_window else ''
        _, created_at = _create_alert_event(
            dedupe_key, severity, title, message, device_id, interface_name,
            workflow_status=workflow_status,
            note=note,
        )
        open_alerts[dedupe_key] = created_at  # store first-occurrence time
        if maintenance_window:
            return
        object_name = interface_name if interface_name else dedupe_key
        if notify and _protocol_transition_notify_allowed(dedupe_key):
            maybe_notify_webhook(
                dedupe_key, severity, title, message,
                created_at=created_at,
                ip_address=ip_address,
                object_name=object_name,
                status=status or 'active',
                last_occurrence=created_at,
                rule=rule,
            )
    elif (not is_active) and currently_open:
        alert_row = _db_quick(
            "SELECT workflow_status FROM alert_events WHERE dedupe_key = ? AND resolved_at IS NULL ORDER BY created_at DESC LIMIT 1",
            (dedupe_key,), fetch=True,
        )
        _resolve_alert_event(dedupe_key)
        open_alerts.pop(dedupe_key, None)
        if alert_row and str(alert_row['workflow_status'] or '').lower() == 'suppressed':
            return
        now_ts = _local_now_str()
        object_name = interface_name if interface_name else dedupe_key
        # 计算持续时长、影响时间窗、告警次数
        try:
            _dur_start = datetime.fromisoformat(currently_open)
            _dur_end   = datetime.now()
            _duration_seconds = max(0, int((_dur_end - _dur_start).total_seconds()))
        except Exception:
            _duration_seconds = None
        _impact_window = (
            f"{currently_open.split(' ')[-1]} → {now_ts.split(' ')[-1]}"
            if ' ' in currently_open and ' ' in now_ts else None
        )
        _count_row = _db_quick(
            "SELECT COUNT(*) AS cnt FROM alert_events WHERE dedupe_key = ?",
            (dedupe_key,), fetch=True,
        )
        _alert_count = _count_row['cnt'] if _count_row else None
        if notify and _protocol_transition_notify_allowed(dedupe_key):
            maybe_notify_webhook(
                dedupe_key, severity, title, message,
                created_at=currently_open,
                ip_address=ip_address,
                object_name=object_name,
                status='resolved',
                last_occurrence=now_ts,
                duration_seconds=_duration_seconds,
                impact_window=_impact_window,
                alert_count=_alert_count,
                rule=rule,
            )

def _sync_protocol_aggregate_alert(metric_type: str, title: str, device_row: dict, ip_address: str, down_peers: list[str]):
    dedupe_key = f"{metric_type}:summary:{device_row['id']}"
    dev_label = device_row.get('hostname') or ip_address or device_row['id']
    sample = ', '.join(down_peers[:protocol_aggregate_sample_size])
    if len(down_peers) > protocol_aggregate_sample_size:
        sample = f"{sample} 等 {len(down_peers)} 个对象"
    message = (
        f"{dev_label} 当前 {_protocol_metric_label(metric_type)}异常 {len(down_peers)} 个：{sample}"
        if down_peers else
        f"{dev_label} {_protocol_metric_label(metric_type)}聚合告警已恢复"
    )
    rule = resolve_alert_rule(metric_type, device_row=device_row, ip_address=ip_address, interface_name=dev_label)
    set_alert_state(
        dedupe_key,
        len(down_peers) >= protocol_aggregate_threshold,
        (rule or {}).get('severity', 'critical'),
        f"{title} Summary",
        message,
        device_row['id'],
        dev_label,
        ip_address=ip_address,
        status='active' if len(down_peers) >= protocol_aggregate_threshold else 'resolved',
        rule=rule,
    )

def _sync_protocol_flap_alert(metric_type: str, title: str, device_row: dict, ip_address: str, flapping_peers: list[str]):
    dedupe_key = f"{metric_type}:flap:{device_row['id']}"
    dev_label = device_row.get('hostname') or ip_address or device_row['id']
    sample = ', '.join(flapping_peers[:protocol_aggregate_sample_size])
    if len(flapping_peers) > protocol_aggregate_sample_size:
        sample = f"{sample} 等 {len(flapping_peers)} 个对象"
    message = (
        f"{dev_label} 存在 {_protocol_metric_label(metric_type)}抖动对象 {len(flapping_peers)} 个，通知已进入抑制窗口：{sample}"
        if flapping_peers else
        f"{dev_label} {_protocol_metric_label(metric_type)}抖动抑制已解除"
    )
    rule = resolve_alert_rule(metric_type, device_row=device_row, ip_address=ip_address, interface_name=dev_label)
    set_alert_state(
        dedupe_key,
        bool(flapping_peers),
        (rule or {}).get('severity', 'major'),
        f"{title} Flapping",
        message,
        device_row['id'],
        dev_label,
        ip_address=ip_address,
        status='active' if flapping_peers else 'resolved',
        rule=rule,
    )

def resolved_alert_severity(rule: dict | None, fallback: str) -> str:
    configured = str((rule or {}).get('severity') or '').strip().lower()
    if configured:
        return configured
    normalized_fallback = str(fallback or '').strip().lower()
    return normalized_fallback or 'major'


async def _probe_device_reachability(ip_address: str, management_port: int = 22) -> tuple[bool, str]:
    """Treat a device as reachable when either ICMP or its management TCP port responds."""
    try:
        delay = await asyncio.to_thread(ping, ip_address, timeout=2)
        if delay is not None:
            return True, 'icmp'
    except Exception:
        pass

    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip_address, int(management_port or 22)),
            timeout=2,
        )
        writer.close()
        await writer.wait_closed()
        return True, 'tcp'
    except Exception:
        return False, 'unreachable'


def _device_management_port(device: dict) -> int:
    """Resolve the status-probe port using the device connection method."""
    raw_port = device.get('management_port') or device.get('port')
    if raw_port in (None, ''):
        return 23 if str(device.get('connection_method') or '').lower() == 'telnet' else 22
    try:
        port = int(raw_port)
    except (TypeError, ValueError):
        return 22
    return port if 1 <= port <= 65535 else 22

async def process_device(device, cycle_tick: int):
    start_time = _time.perf_counter()
    success = False
    try:
        res = await _process_device_raw(device, cycle_tick)
        success = True
        return res
    finally:
        duration = _time.perf_counter() - start_time
        try:
            from core.metrics import metrics_registry
            metrics_registry.record_polling(duration, success)
        except Exception:
            pass

async def _process_device_raw(device, cycle_tick: int):
    async with _get_semaphore():
        device = _as_dict(device)
        ip = device['ip_address']
        dev_id = device['id']
        poll_profile = _device_poll_profile(device)
        collect_intf = _should_collect(cycle_tick, poll_profile['interface'])
        collect_info = _should_collect(cycle_tick, poll_profile['info'])
        collect_protocol = _should_collect(cycle_tick, poll_profile['protocol'])

        def mark_offline_and_clear_cache():
            # Keep UI consistent with real reachability: when a device is offline,
            # discard last SNMP snapshot so stale interface rows are not shown.
            _db_quick('''
                UPDATE devices
                SET status = ?, cpu_usage = ?, memory_usage = ?
                WHERE id = ?
            ''', ('offline', 0, 0, dev_id))
            prev_intf_octets.pop(dev_id, None)

        if not ip or ip == '0.0.0.0':
            mark_offline_and_clear_cache()
            return

        # 1. Ping Check
        dev_label = device['hostname'] or ip
        try:
            # ping() is blocking; run it off the event loop to keep API endpoints responsive.
            reachable, probe_method = await _probe_device_reachability(
                ip,
                _device_management_port(device),
            )
            new_status = 'online' if reachable else 'offline'

            if device['status'] != new_status:
                if new_status == 'offline':
                    _set_protocol_alerts_for_device_offline(device, ip)
                    mark_offline_and_clear_cache()
                    set_alert_state(
                        f"dev_offline:{dev_id}", True, 'critical', 'Device Offline',
                        f"{dev_label} ({ip}) 无法连接，Ping 超时",
                        dev_id, ip_address=ip, status='active',
                    )
                else:
                    _db_quick('UPDATE devices SET status = ? WHERE id = ?', (new_status, dev_id))
                    set_alert_state(
                        f"dev_offline:{dev_id}", False, 'info', 'Device Offline',
                        f"{dev_label} ({ip}) 已恢复连接",
                        dev_id, ip_address=ip, status='resolved',
                    )
                logger.info(
                    f"[Status Monitor] Device {ip} status changed to {new_status} via {probe_method}"
                )
        except Exception:
            new_status = 'offline'
            if device.get('status') != 'offline':
                _set_protocol_alerts_for_device_offline(device, ip)
                set_alert_state(
                    f"dev_offline:{dev_id}", True, 'critical', 'Device Offline',
                    f"{dev_label} ({ip}) 无法连接，Ping 超时",
                    dev_id, ip_address=ip, status='active',
                )
            mark_offline_and_clear_cache()

        # 2. SNMP Metrics Collection (only if online)
        if new_status != 'online':
            # Ensure stale telemetry is never shown for offline devices.
            mark_offline_and_clear_cache()
            return

        cpu_history = json.loads(device['cpu_history'] or '[]')
        mem_history = json.loads(device['memory_history'] or '[]')

        snmp_community = device['snmp_community'] or 'public'
        snmp_port = device['snmp_port'] or 161
        platform = device['platform'] or 'cisco_ios'
        snmp_available = False

        # Try real SNMP collection (no DB lock held during await)
        cpu_usage = None
        memory_usage = None
        temp = None
        fan = None
        psu = None
        try:
            metrics = await collect_device_metrics(ip, platform, snmp_community, snmp_port)
            cpu_usage = metrics.get('cpu_usage')
            memory_usage = metrics.get('memory_usage')
            temp = metrics.get('temp')
            fan = metrics.get('fan_status')
            psu = metrics.get('psu_status')
            snmp_available = any(value is not None for value in (cpu_usage, memory_usage, temp, fan, psu))
        except Exception as snmp_err:
            logger.debug(f"[SNMP] {ip} metrics failed: {snmp_err}")

        # Fallback: if standard metrics failed (e.g. Linux servers lacking specific OIDs),
        # verify true reachability via standard sysUpTime before marking unreachable.
        if not snmp_available:
            try:
                from services.snmp_service import _snmp_get, SYS_UPTIME
                test_val = await _snmp_get(ip, snmp_community, SYS_UPTIME, snmp_port, timeout=1.5)
                if test_val is not None:
                    snmp_available = True
            except Exception:
                pass

        # Only append to history if we got data
        if cpu_usage is not None:
            cpu_history.append(cpu_usage)
            cpu_history = cpu_history[-20:]
        if memory_usage is not None:
            mem_history.append(memory_usage)
            mem_history = mem_history[-20:]

        _db_quick('''
            UPDATE devices 
            SET cpu_usage = ?, memory_usage = ?, cpu_history = ?, memory_history = ?, temp = ?, fan_status = ?, psu_status = ?
            WHERE id = ?
        ''', (cpu_usage, memory_usage, json.dumps(cpu_history), json.dumps(mem_history), temp, fan, psu, dev_id))

        # CPU / 内存阈值告警
        if cpu_usage is not None:
            cpu_key = f"cpu_high:{dev_id}"
            cpu_rule = resolve_alert_rule('cpu', device_row=device, ip_address=ip)
            cpu_threshold = float(cpu_rule['threshold']) if cpu_rule and cpu_rule.get('threshold') is not None else None
            if cpu_rule and cpu_threshold is not None and float(cpu_usage) >= cpu_threshold:
                set_alert_state(
                    cpu_key, True, cpu_rule.get('severity', 'major'), 'CPU Usage High',
                    f"{dev_label} CPU 利用率达到 {cpu_usage:.1f}%，超过阈值 {cpu_threshold}%",
                    dev_id, ip_address=ip, status='active', rule=cpu_rule,
                )
            else:
                set_alert_state(
                    cpu_key, False, resolved_alert_severity(cpu_rule, 'major'), 'CPU Usage High',
                    f"{dev_label} CPU 利用率已恢复（当前 {cpu_usage:.1f}%）",
                    dev_id, ip_address=ip, status='resolved', rule=cpu_rule,
                )
        if memory_usage is not None:
            mem_key = f"mem_high:{dev_id}"
            memory_rule = resolve_alert_rule('memory', device_row=device, ip_address=ip)
            memory_threshold = float(memory_rule['threshold']) if memory_rule and memory_rule.get('threshold') is not None else None
            if memory_rule and memory_threshold is not None and float(memory_usage) >= memory_threshold:
                set_alert_state(
                    mem_key, True, memory_rule.get('severity', 'major'), 'Memory Usage High',
                    f"{dev_label} 内存利用率达到 {memory_usage:.1f}%，超过阈值 {memory_threshold}%",
                    dev_id, ip_address=ip, status='active', rule=memory_rule,
                )
            else:
                set_alert_state(
                    mem_key, False, resolved_alert_severity(memory_rule, 'major'), 'Memory Usage High',
                    f"{dev_label} 内存利用率已恢复（当前 {memory_usage:.1f}%）",
                    dev_id, ip_address=ip, status='resolved', rule=memory_rule,
                )

        if temp is not None:
            temp_key = f"temp_high:{dev_id}"
            temp_rule = resolve_alert_rule('temperature_high', device_row=device, ip_address=ip)
            temp_threshold = float(temp_rule['threshold']) if temp_rule and temp_rule.get('threshold') is not None else None
            temp_active = bool(temp_rule and temp_threshold is not None and float(temp) >= temp_threshold)
            set_alert_state(
                temp_key,
                temp_active,
                (temp_rule or {}).get('severity', 'major'),
                'Temperature High',
                (f"{dev_label} 设备温度达到 {temp}°C，超过阈值 {temp_threshold}°C" if temp_active else f"{dev_label} 设备温度已恢复（当前 {temp}°C）"),
                dev_id,
                ip_address=ip,
                status='active' if temp_active else 'resolved',
                rule=temp_rule,
            )

        if fan is not None:
            fan_key = f"fan_failure:{dev_id}"
            fan_rule = resolve_alert_rule('fan_failure', device_row=device, ip_address=ip)
            fan_failed = str(fan).strip().lower() == 'fail'
            set_alert_state(
                fan_key,
                fan_failed,
                (fan_rule or {}).get('severity', 'critical'),
                'Fan Failure',
                (f"{dev_label} 风扇状态异常，请尽快检查散热组件" if fan_failed else f"{dev_label} 风扇状态已恢复正常"),
                dev_id,
                ip_address=ip,
                status='active' if fan_failed else 'resolved',
                rule=fan_rule,
            )

        if psu is not None:
            psu_key = f"psu_failure:{dev_id}"
            psu_rule = resolve_alert_rule('power_supply_failure', device_row=device, ip_address=ip)
            psu_failed = str(psu).strip().lower() == 'fail'
            set_alert_state(
                psu_key,
                psu_failed,
                (psu_rule or {}).get('severity', 'critical'),
                'Power Supply Failure',
                (f"{dev_label} 电源状态异常，请检查供电与冗余模块" if psu_failed else f"{dev_label} 电源状态已恢复正常"),
                dev_id,
                ip_address=ip,
                status='active' if psu_failed else 'resolved',
                rule=psu_rule,
            )

        # 3. Device info collection (every ~10 minutes)
        if collect_info:
            try:
                dev_info = await collect_device_info(ip, snmp_community, snmp_port)
                if dev_info:
                    snmp_available = True
                updates = {}
                if dev_info.get('sys_name'):
                    updates['sys_name'] = dev_info['sys_name']
                if dev_info.get('sys_descr'):
                    descr = dev_info['sys_descr']
                    if not device['model']:
                        first_line = descr.split('\r\n')[0].split('\n')[0].strip()
                        if first_line:
                            updates['model'] = first_line[:80]
                    if not device['version']:
                        ver_match = _re.search(r'[Vv]ersion\s+([\w\.\(\)\-/]+)', descr)
                        if ver_match:
                            updates['version'] = ver_match.group(1)
                if dev_info.get('uptime'):
                    updates['uptime'] = dev_info['uptime']
                if dev_info.get('sys_location'):
                    updates['sys_location'] = dev_info['sys_location']
                if dev_info.get('sys_contact'):
                    updates['sys_contact'] = dev_info['sys_contact']
                if updates:
                    set_clause = ', '.join(f'{k} = ?' for k in updates)
                    _db_quick(f'UPDATE devices SET {set_clause} WHERE id = ?',
                              (*updates.values(), dev_id))
            except Exception as info_err:
                logger.debug(f"[SNMP] {ip} device info collection failed: {info_err}")

        if collect_protocol:
            await _collect_protocol_neighbor_alerts(device, ip)

        # 4. Interface data collection
        if collect_intf:
            try:
                now_ts = _time.monotonic()
                now_iso = _utc_now_iso()
                intf_data = await collect_interface_data(ip, snmp_community, snmp_port)
                if intf_data:
                    snmp_available = True
                    topology_ports = load_topology_ports(dev_id)
                    # Calculate real-time throughput and bandwidth utilization from previous snapshot.
                    prev = prev_intf_octets.get(dev_id, {})
                    persisted_statuses = load_persisted_interface_statuses(dev_id) if not prev else {}
                    cur_snapshot = {}
                    raw_rows = []
                    for iface in intf_data:
                        iname = iface['name']
                        effective_prev_status = str(prev.get(iname, {}).get('status', '') or persisted_statuses.get(iname, '')).lower()
                        cur_snapshot[iname] = {
                            'in_octets': iface['in_octets'],
                            'out_octets': iface['out_octets'],
                            'in_ucast_pkts': iface.get('in_ucast_pkts', 0),
                            'out_ucast_pkts': iface.get('out_ucast_pkts', 0),
                            'in_errors': iface.get('in_errors', 0),
                            'out_errors': iface.get('out_errors', 0),
                            'in_discards': iface.get('in_discards', 0),
                            'out_discards': iface.get('out_discards', 0),
                            'status': iface.get('status', 'unknown'),
                            'ts': now_ts,
                        }

                        # ── Flap detection: track UP↔DOWN transitions ──
                        flap_key = f"{dev_id}:{iname}"
                        curr_status = str(iface.get('status', '')).lower()
                        if effective_prev_status and effective_prev_status != curr_status and effective_prev_status in ('up', 'down') and curr_status in ('up', 'down'):
                            hist = intf_flap_history.setdefault(flap_key, [])
                            hist.append(now_ts)
                        # Prune old entries outside the window
                        hist = intf_flap_history.get(flap_key, [])
                        cutoff = now_ts - FLAP_WINDOW_SECS
                        hist[:] = [t for t in hist if t > cutoff]
                        iface['flapping'] = len(hist) >= FLAP_THRESHOLD
                        flap_alert_key = f"if_flap:{dev_id}:{iname}"
                        flap_rule = resolve_alert_rule('interface_flap', device_row=device, ip_address=ip, interface_name=iname)
                        set_alert_state(
                            flap_alert_key, iface['flapping'], (flap_rule or {}).get('severity', 'major'), 'Interface Flapping',
                            (
                                f"{iname} 接口震荡：10 分钟内状态翻转 {len(hist)} 次"
                                if iface['flapping'] else
                                f"{iname} 接口震荡已平息"
                            ),
                            dev_id, iname,
                            ip_address=ip,
                            status='active' if iface['flapping'] else 'resolved',
                            rule=flap_rule,
                        )

                        if iname in prev:
                            dt = now_ts - prev[iname]['ts']
                            if dt > 0:
                                # Counter overflow compensation (32-bit wrap-around)
                                raw_delta_in = iface['in_octets'] - prev[iname]['in_octets']
                                raw_delta_out = iface['out_octets'] - prev[iname]['out_octets']
                                delta_in = raw_delta_in if raw_delta_in >= 0 else raw_delta_in + COUNTER32_MAX
                                delta_out = raw_delta_out if raw_delta_out >= 0 else raw_delta_out + COUNTER32_MAX
                                # Sanity: if delta implies >100 Gbps, likely a reset - discard
                                max_reasonable = 100_000_000_000 * dt / 8  # 100Gbps in bytes
                                if delta_in > max_reasonable:
                                    delta_in = 0
                                if delta_out > max_reasonable:
                                    delta_out = 0
                                in_bps = (delta_in * 8) / dt
                                out_bps = (delta_out * 8) / dt
                                iface['in_bps'] = round(in_bps, 1)
                                iface['out_bps'] = round(out_bps, 1)

                                speed_bps = iface.get('speed_mbps', 0) * 1_000_000
                                if speed_bps > 0:
                                    bw_in = round((in_bps / speed_bps) * 100, 1)
                                    bw_out = round((out_bps / speed_bps) * 100, 1)
                                    iface['bw_in_pct'] = min(bw_in, 100.0)
                                    iface['bw_out_pct'] = min(bw_out, 100.0)

                                delta_error_events = max(0, iface.get('in_errors', 0) - prev[iname].get('in_errors', 0))
                                delta_error_events += max(0, iface.get('out_errors', 0) - prev[iname].get('out_errors', 0))
                                delta_error_events += max(0, iface.get('in_discards', 0) - prev[iname].get('in_discards', 0))
                                delta_error_events += max(0, iface.get('out_discards', 0) - prev[iname].get('out_discards', 0))
                                delta_packets = max(0, iface.get('in_ucast_pkts', 0) - prev[iname].get('in_ucast_pkts', 0))
                                delta_packets += max(0, iface.get('out_ucast_pkts', 0) - prev[iname].get('out_ucast_pkts', 0))
                                if delta_packets > 0:
                                    iface['error_rate_pct'] = round((delta_error_events / delta_packets) * 100, 3)

                        # Persist high-frequency telemetry for short-term tracing.
                        raw_rows.append((
                            now_iso,
                            dev_id,
                            iname,
                            iface.get('status'),
                            iface.get('speed_mbps', 0),
                            iface.get('in_bps'),
                            iface.get('out_bps'),
                            iface.get('bw_in_pct'),
                            iface.get('bw_out_pct'),
                            iface.get('in_ucast_pkts', 0),
                            iface.get('out_ucast_pkts', 0),
                            iface.get('in_errors', 0),
                            iface.get('out_errors', 0),
                            iface.get('in_discards', 0),
                            iface.get('out_discards', 0),
                        ))

                        # Basic alert rules: interface down / high utilization.
                        # Requirement: only trigger DOWN alert on state transition UP -> DOWN.
                        normalized_iname = str(iname or '').strip().lower()
                        is_topology_port = normalized_iname in topology_ports
                        down_metric = 'interconnect_down' if is_topology_port else 'interface_down'
                        down_title = 'Interconnect Down' if is_topology_port else 'Interface Down'
                        down_message = (
                            f"{iname} 互联口状态变更：UP → DOWN，请优先检查邻居关系、上联链路与对端接口"
                            if is_topology_port else
                            f"{iname} 状态变更：UP → DOWN，请检查端口连接和用线"
                        )
                        recover_message = (
                            f"{iname} 互联口状态恢复：DOWN → UP"
                            if is_topology_port else
                            f"{iname} 状态恢复：DOWN → UP"
                        )
                        down_rule = resolve_alert_rule(down_metric, device_row=device, ip_address=ip, interface_name=iname)
                        curr_status = str(iface.get('status', '')).lower()
                        if down_rule:
                            down_key = f"{'interconnect_down' if is_topology_port else 'if_down'}:{dev_id}:{iname}"
                            alternate_key = f"{'if_down' if is_topology_port else 'interconnect_down'}:{dev_id}:{iname}"
                            if effective_prev_status == 'up' and curr_status == 'down':
                                set_alert_state(
                                    alternate_key, False, resolved_alert_severity(None, 'warning'), 'Interface Down',
                                    f"{iname} 状态恢复：DOWN → UP",
                                    dev_id, iname,
                                    ip_address=ip, status='resolved',
                                )
                                set_alert_state(
                                    down_key, True, down_rule.get('severity', 'major' if is_topology_port else 'warning'), down_title,
                                    down_message,
                                    dev_id, iname,
                                    ip_address=ip, status='active', rule=down_rule,
                                )
                            elif effective_prev_status == 'down' and curr_status == 'up':
                                set_alert_state(
                                    down_key, False, resolved_alert_severity(down_rule, 'major' if is_topology_port else 'warning'), down_title,
                                    recover_message,
                                    dev_id, iname,
                                    ip_address=ip, status='resolved', rule=down_rule,
                                )
                        else:
                            set_alert_state(
                                f"if_down:{dev_id}:{iname}", False, resolved_alert_severity(None, 'warning'), 'Interface Down',
                                f"{iname} 状态恢复：DOWN → UP",
                                dev_id, iname,
                                ip_address=ip, status='resolved',
                            )

                        error_rate_rule = resolve_alert_rule('interface_error_rate_high', device_row=device, ip_address=ip, interface_name=iname)
                        error_rate_threshold = float(error_rate_rule['threshold']) if error_rate_rule and error_rate_rule.get('threshold') is not None else None
                        current_error_rate = float(iface.get('error_rate_pct') or 0)
                        error_rate_active = bool(error_rate_rule and error_rate_threshold is not None and current_error_rate >= error_rate_threshold)
                        set_alert_state(
                            f"if_error_rate:{dev_id}:{iname}",
                            error_rate_active,
                            (error_rate_rule or {}).get('severity', 'major'),
                            'Interface Error Rate High',
                            (
                                f"{iname} 接口错误率达到 {current_error_rate:.3f}%，超过阈值 {error_rate_threshold}%"
                                if error_rate_active else
                                f"{iname} 接口错误率已恢复正常（当前 {current_error_rate:.3f}%）"
                            ),
                            dev_id,
                            iname,
                            ip_address=ip,
                            status='active' if error_rate_active else 'resolved',
                            rule=error_rate_rule,
                        )

                        max_util = max(float(iface.get('bw_in_pct') or 0), float(iface.get('bw_out_pct') or 0))
                        util_rule = resolve_alert_rule('interface_util', device_row=device, ip_address=ip, interface_name=iname)
                        util_threshold = float(util_rule['threshold']) if util_rule and util_rule.get('threshold') is not None else None
                        util_active = bool(util_rule and util_threshold is not None and max_util >= util_threshold)
                        util_key = f"if_util:{dev_id}:{iname}"
                        if util_active:
                            set_alert_state(
                                util_key, True,
                                util_rule.get('severity', 'warning'),
                                'Interface Utilization High',
                                f"{iname} 带宽占用率达到 {max_util:.1f}%，超过阈值 {util_threshold}%",
                                dev_id, iname,
                                ip_address=ip, status='active', rule=util_rule,
                            )
                        else:
                            set_alert_state(
                                util_key, False,
                                resolved_alert_severity(util_rule, 'warning'),
                                'Interface Utilization High',
                                f"{iname} 带宽占用率已恢复正常（当前 {max_util:.1f}%）",
                                dev_id, iname,
                                ip_address=ip, status='resolved', rule=util_rule,
                            )

                    prev_intf_octets[dev_id] = cur_snapshot
                    _db_many('''
                        INSERT INTO interface_telemetry_raw (
                            ts, device_id, interface_name, status, speed_mbps,
                            in_bps, out_bps, bw_in_pct, bw_out_pct,
                            in_pkts, out_pkts,
                            in_errors, out_errors, in_discards, out_discards
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', raw_rows)

                    # Update interfaces table with discovered interfaces
                    conn = get_db_connection()
                    try:
                        for iface in intf_data:
                            iname = iface['name']
                            desc = iface.get('description', '')
                            status = iface.get('status', 'down')
                            speed_mbps = float(iface.get('speed_mbps') or 0.0)
                            speed_bps = speed_mbps * 1_000_000.0
                            
                            conn.execute('''
                                INSERT INTO interfaces (
                                    id, device_id, interface_name, description, admin_status, oper_status,
                                    mac_address, speed, bandwidth, duplex, interface_type, switchport_mode, ip_enabled
                                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                ON CONFLICT(device_id, interface_name) DO UPDATE SET
                                    description = excluded.description,
                                    admin_status = excluded.admin_status,
                                    oper_status = excluded.oper_status,
                                    speed = excluded.speed,
                                    bandwidth = excluded.bandwidth
                            ''', (f"intf-{uuid.uuid4().hex[:12]}", dev_id, iname, desc, status, status, '', speed_bps, speed_bps, 'auto', 'physical', 'access', 0))
                        conn.commit()
                    except Exception as err:
                        logger.warning(f"Failed to upsert interfaces to DB for {dev_id}: {err}")
                    finally:
                        conn.close()
            except Exception as intf_err:
                logger.debug(f"[SNMP] {ip} interface collection failed: {intf_err}")

        is_server_asset = (str(device.get('asset_type') or '').strip().lower() == 'server') or \
                          (str(device.get('platform') or '').strip().lower() in ('linux', 'ubuntu', 'debian', 'centos', 'rhel', 'server')) or \
                          ('server' in str(device.get('device_category') or '').lower())
        if is_server_asset:
            snmp_available = True  # Linux 服务器采用 SSH 巡检，免除传统 SNMP 可达性告警监控

        snmp_rule = resolve_alert_rule('snmp_unreachable', device_row=device, ip_address=ip)
        snmp_key = f"snmp_unreachable:{dev_id}"
        if snmp_available:
            snmp_failure_streak.pop(dev_id, None)
            set_alert_state(
                snmp_key,
                False,
                resolved_alert_severity(snmp_rule, 'major'),
                'SNMP Unreachable',
                f"{dev_label} 为 Linux 服务器资产，默认采用 SSH 巡检通道，已自动免除 SNMP 监控告警" if is_server_asset else f"{dev_label} SNMP 采集已恢复正常",
                dev_id,
                ip_address=ip,
                status='resolved',
                rule=snmp_rule,
            )
        else:
            snmp_failure_streak[dev_id] = snmp_failure_streak.get(dev_id, 0) + 1
            snmp_active = snmp_failure_streak[dev_id] >= 2
            set_alert_state(
                snmp_key,
                snmp_active,
                (snmp_rule or {}).get('severity', 'major'),
                'SNMP Unreachable',
                f"{dev_label} 设备在线，但连续 {snmp_failure_streak[dev_id]} 次 SNMP 采集失败",
                dev_id,
                ip_address=ip,
                status='active' if snmp_active else 'resolved',
                rule=snmp_rule,
            )


async def process_device_fast(device):
    # Fast reachability probe (ICMP with management-port fallback)
    device = _as_dict(device)
    ip = device['ip_address']
    dev_id = device['id']
    
    def mark_offline_and_clear_cache():
        _db_quick("""
            UPDATE devices
            SET status = ?, cpu_usage = ?, memory_usage = ?
            WHERE id = ?
        """, ('offline', 0, 0, dev_id))
        prev_intf_octets.pop(dev_id, None)

    if not ip or ip == '0.0.0.0':
        mark_offline_and_clear_cache()
        return

    dev_label = device['hostname'] or ip
    try:
        reachable, probe_method = await _probe_device_reachability(
            ip,
            _device_management_port(device),
        )
        new_status = 'online' if reachable else 'offline'

        if device['status'] != new_status:
            if new_status == 'offline':
                _set_protocol_alerts_for_device_offline(device, ip)
                mark_offline_and_clear_cache()
                set_alert_state(
                    f"dev_offline:{dev_id}", True, 'critical', 'Device Offline',
                    f"{dev_label} ({ip}) 无法连接，Ping 超时",
                    dev_id, ip_address=ip, status='active',
                )
            else:
                _db_quick('UPDATE devices SET status = ? WHERE id = ?', (new_status, dev_id))
                set_alert_state(
                    f"dev_offline:{dev_id}", False, 'info', 'Device Offline',
                    f"{dev_label} ({ip}) 已恢复连接",
                    dev_id, ip_address=ip, status='resolved',
                )
            logger.info(
                f"[Status Monitor] Device {ip} status changed to {new_status} via {probe_method}"
            )
    except Exception:
        new_status = 'offline'
        if device.get('status') != 'offline':
            _set_protocol_alerts_for_device_offline(device, ip)
            set_alert_state(
                f"dev_offline:{dev_id}", True, 'critical', 'Device Offline',
                f"{dev_label} ({ip}) 无法连接，Ping 超时",
                dev_id, ip_address=ip, status='active',
            )
        mark_offline_and_clear_cache()

async def process_device_slow(device):
    # SNMP Metrics ONLY (B-Loop)
    device = _as_dict(device)
    if str(device.get('status')).lower() != 'online':
        return
        
    # Execute the heavy collection (using cycle 0 to force collection for info/protocol/intf)
    await process_device(device, 0)
