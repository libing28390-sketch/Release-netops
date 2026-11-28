"""
odf_service.py — ODF 光纤配线架 CMDB 服务层

Provides authoritative CMDB CRUD and fiber cross-connect lifecycle management for:
  - ``odf_frames``: Optical Distribution Frame cabinets (site/floor/room/row/vendor/model/capacity)
  - ``odf_trays``:  Modular splice/patch subracks (e.g. 12 trays × 48 cores = 576F)
  - ``odf_ports``:  Sparse-stored active/reserved/faulty LC/SC/MPO fiber terminations
                    linking A-end (network device + interface) <-> ODF tray/port <-> Z-end
                    (peer device, peer ODF, or carrier circuit).

Uses sparse storage in ``odf_ports`` (only non-idle or annotated ports are persisted)
and projects full tray matrices on read so even 100+ ODF frames (50,000+ cores) stay fast.
"""

from __future__ import annotations

import logging
import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from services import rack_service

logger = logging.getLogger(__name__)
_ODF_SCHEMA_LOCK = threading.Lock()
_ODF_SCHEMA_READY = False

VALID_CONNECTOR_TYPES = frozenset({'LC/UPC', 'LC/APC', 'SC/UPC', 'SC/APC', 'MPO-12', 'MPO-24', 'FC/UPC'})
VALID_FIBER_MODES = frozenset({'OS2', 'OM4', 'OM3', 'mixed'})
VALID_FRAME_STATUSES = frozenset({'active', 'planned', 'maintenance', 'retired'})
VALID_PORT_STATUSES = frozenset({'idle', 'occupied', 'reserved', 'fault'})
VALID_Z_ENDPOINT_TYPES = frozenset({'device', 'odf', 'carrier', 'other'})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, 'keys'):
        return {k: row[k] for k in row.keys()}
    return dict(row)


def ensure_odf_tables(conn, *, force: bool = False) -> None:
    """Idempotently ensure ODF CMDB tables and indexes exist on PostgreSQL."""
    global _ODF_SCHEMA_READY
    if _ODF_SCHEMA_READY and not force:
        return
    with _ODF_SCHEMA_LOCK:
        if _ODF_SCHEMA_READY and not force:
            return
        _ensure_odf_tables_locked(conn)
        _ODF_SCHEMA_READY = True


def _ensure_odf_tables_locked(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS odf_frames (
            id VARCHAR(50) PRIMARY KEY,
            site_id VARCHAR(50) NOT NULL,
            frame_code VARCHAR(64) NOT NULL UNIQUE,
            name VARCHAR(120) NOT NULL,
            vendor VARCHAR(80) DEFAULT '',
            model VARCHAR(120) DEFAULT '',
            floor VARCHAR(100) DEFAULT '',
            room VARCHAR(100) DEFAULT '',
            row VARCHAR(50) DEFAULT '',
            rack_id VARCHAR(50) DEFAULT '',
            tray_count INTEGER NOT NULL DEFAULT 12,
            ports_per_tray INTEGER NOT NULL DEFAULT 48,
            total_cores INTEGER NOT NULL DEFAULT 576,
            connector_type VARCHAR(24) NOT NULL DEFAULT 'LC/UPC',
            fiber_mode VARCHAR(24) NOT NULL DEFAULT 'OS2',
            status VARCHAR(24) NOT NULL DEFAULT 'active',
            remarks TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            FOREIGN KEY (site_id) REFERENCES sites (id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS odf_trays (
            id VARCHAR(50) PRIMARY KEY,
            frame_id VARCHAR(50) NOT NULL,
            tray_no INTEGER NOT NULL,
            tray_code VARCHAR(32) NOT NULL,
            label VARCHAR(160) DEFAULT '',
            port_count INTEGER NOT NULL DEFAULT 48,
            fiber_mode VARCHAR(24) NOT NULL DEFAULT 'OS2',
            connector_type VARCHAR(24) NOT NULL DEFAULT 'LC/UPC',
            status VARCHAR(24) NOT NULL DEFAULT 'active',
            remarks TEXT DEFAULT '',
            created_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT '',
            FOREIGN KEY (frame_id) REFERENCES odf_frames (id) ON DELETE CASCADE,
            UNIQUE (frame_id, tray_no)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS odf_ports (
            id VARCHAR(50) PRIMARY KEY,
            frame_id VARCHAR(50) NOT NULL,
            tray_id VARCHAR(50) NOT NULL,
            tray_no INTEGER NOT NULL,
            port_no INTEGER NOT NULL,
            port_code VARCHAR(48) NOT NULL,
            status VARCHAR(24) NOT NULL DEFAULT 'occupied',
            fiber_type VARCHAR(24) NOT NULL DEFAULT 'OS2',
            connector_type VARCHAR(24) NOT NULL DEFAULT 'LC/UPC',
            a_device_id VARCHAR(64) DEFAULT '',
            a_device_name VARCHAR(160) DEFAULT '',
            a_interface_name VARCHAR(120) DEFAULT '',
            a_rack_name VARCHAR(120) DEFAULT '',
            z_endpoint_type VARCHAR(24) NOT NULL DEFAULT 'device',
            z_device_id VARCHAR(64) DEFAULT '',
            z_device_name VARCHAR(160) DEFAULT '',
            z_interface_name VARCHAR(120) DEFAULT '',
            z_odf_frame_id VARCHAR(50) DEFAULT '',
            z_odf_port_code VARCHAR(48) DEFAULT '',
            z_peer_label VARCHAR(200) DEFAULT '',
            cable_tag VARCHAR(120) DEFAULT '',
            circuit_id VARCHAR(120) DEFAULT '',
            attenuation_db REAL,
            remarks TEXT DEFAULT '',
            updated_by VARCHAR(80) DEFAULT '',
            updated_at TEXT DEFAULT '',
            FOREIGN KEY (frame_id) REFERENCES odf_frames (id) ON DELETE CASCADE,
            FOREIGN KEY (tray_id) REFERENCES odf_trays (id) ON DELETE CASCADE,
            UNIQUE (tray_id, port_no)
        )
        """
    )

    conn.execute("CREATE INDEX IF NOT EXISTS idx_odf_frames_site_id ON odf_frames(site_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_odf_trays_frame_no ON odf_trays(frame_id, tray_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_odf_ports_frame_tray_port ON odf_ports(frame_id, tray_no, port_no)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_odf_ports_a_device ON odf_ports(a_device_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_odf_ports_z_device ON odf_ports(z_device_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_odf_ports_status ON odf_ports(frame_id, status)")
    conn.commit()


def _format_tray_code(tray_no: int) -> str:
    return f"A{tray_no:02d}"


def _format_port_code(tray_code: str, port_no: int) -> str:
    return f"{tray_code}-{port_no:02d}"


def _build_scope_filters(
    *,
    site_id: str = '',
    keyword: str = '',
    tenant_id: str | None = None,
    allowed_site_ids: tuple[str, ...] | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if site_id:
        clauses.append("f.site_id = ?")
        params.append(site_id)
    if tenant_id is not None:
        clauses.append("COALESCE(s.tenant_id, 'tenant-default') = ?")
        params.append(tenant_id)
    if allowed_site_ids is not None:
        if not allowed_site_ids:
            clauses.append("1 = 0")
        else:
            ph = ','.join('?' for _ in allowed_site_ids)
            clauses.append(f"f.site_id IN ({ph})")
            params.extend(allowed_site_ids)
    if keyword.strip():
        pat = f"%{keyword.strip().lower()}%"
        clauses.append(
            "("
            "LOWER(COALESCE(f.name, '')) LIKE ? OR "
            "LOWER(COALESCE(f.frame_code, '')) LIKE ? OR "
            "LOWER(COALESCE(f.vendor, '')) LIKE ? OR "
            "LOWER(COALESCE(f.model, '')) LIKE ? OR "
            "LOWER(COALESCE(f.room, '')) LIKE ? OR "
            "LOWER(COALESCE(s.site_code, '')) LIKE ? OR "
            "LOWER(COALESCE(s.site_name, '')) LIKE ?"
            ")"
        )
        params.extend([pat] * 7)
    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ''
    return where_sql, params


def list_odf_frames(
    conn,
    *,
    site_id: str = '',
    keyword: str = '',
    tenant_id: str | None = None,
    allowed_site_ids: tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    where_sql, params = _build_scope_filters(
        site_id=site_id,
        keyword=keyword,
        tenant_id=tenant_id,
        allowed_site_ids=allowed_site_ids,
    )
    rows = conn.execute(
        f"""
        SELECT f.*, s.site_code, s.site_name, s.tenant_id AS site_tenant_id
        FROM odf_frames f
        LEFT JOIN sites s ON s.id = f.site_id
        {where_sql}
        ORDER BY COALESCE(s.site_code, ''), COALESCE(f.room, ''), COALESCE(f.row, ''), f.name
        """,
        tuple(params),
    ).fetchall()
    frames = [_row_to_dict(r) for r in rows]
    if not frames:
        return []

    frame_ids = [str(f['id']) for f in frames]
    ph = ','.join('?' for _ in frame_ids)

    # Aggregate real core usage per frame in a single query
    port_counts: dict[str, dict[str, int]] = {
        fid: {'occupied': 0, 'reserved': 0, 'fault': 0} for fid in frame_ids
    }
    agg_rows = conn.execute(
        f"""
        SELECT frame_id, status, COUNT(*) AS cnt
        FROM odf_ports
        WHERE frame_id IN ({ph})
        GROUP BY frame_id, status
        """,
        tuple(frame_ids),
    ).fetchall()
    for raw in agg_rows:
        item = _row_to_dict(raw)
        fid = str(item.get('frame_id') or '')
        st = str(item.get('status') or '').lower()
        if fid in port_counts and st in port_counts[fid]:
            port_counts[fid][st] += int(item.get('cnt') or 0)

    # Per-tray summary counts for 3D visual binding (occupied per tray!)
    tray_rows = conn.execute(
        f"""
        SELECT t.id, t.frame_id, t.tray_no, t.tray_code, t.label, t.port_count, t.fiber_mode, t.connector_type,
               COALESCE(SUM(CASE WHEN p.status = 'occupied' THEN 1 ELSE 0 END), 0) AS occupied_count,
               COALESCE(SUM(CASE WHEN p.status = 'reserved' THEN 1 ELSE 0 END), 0) AS reserved_count,
               COALESCE(SUM(CASE WHEN p.status = 'fault' THEN 1 ELSE 0 END), 0) AS fault_count
        FROM odf_trays t
        LEFT JOIN odf_ports p ON p.tray_id = t.id
        WHERE t.frame_id IN ({ph})
        GROUP BY t.id, t.frame_id, t.tray_no, t.tray_code, t.label, t.port_count, t.fiber_mode, t.connector_type
        ORDER BY t.frame_id, t.tray_no
        """,
        tuple(frame_ids),
    ).fetchall()
    trays_by_frame: dict[str, list[dict[str, Any]]] = {fid: [] for fid in frame_ids}
    for raw in tray_rows:
        t = _row_to_dict(raw)
        fid = str(t.get('frame_id') or '')
        if fid in trays_by_frame:
            trays_by_frame[fid].append({
                'id': t['id'],
                'tray_no': int(t['tray_no']),
                'tray_code': t['tray_code'],
                'label': t.get('label') or '',
                'port_count': int(t.get('port_count') or 48),
                'fiber_mode': t.get('fiber_mode') or 'OS2',
                'connector_type': t.get('connector_type') or 'LC/UPC',
                'occupied_count': int(t.get('occupied_count') or 0),
                'reserved_count': int(t.get('reserved_count') or 0),
                'fault_count': int(t.get('fault_count') or 0),
            })

    enriched: list[dict[str, Any]] = []
    for f in frames:
        fid = str(f['id'])
        total_cores = max(1, int(f.get('total_cores') or (int(f.get('tray_count') or 12) * int(f.get('ports_per_tray') or 48))))
        counts = port_counts[fid]
        occupied = counts['occupied']
        reserved = counts['reserved']
        fault = counts['fault']
        idle = max(0, total_cores - occupied - reserved - fault)
        enriched.append({
            **f,
            'site_label': f.get('site_name') or f.get('site_code') or f.get('site_id') or '',
            'total_cores': total_cores,
            'occupied_cores': occupied,
            'reserved_cores': reserved,
            'fault_cores': fault,
            'idle_cores': idle,
            'utilization_pct': round((occupied / total_cores) * 100, 1),
            'trays': trays_by_frame.get(fid, []),
        })
    return enriched


def get_odf_stats(
    conn,
    *,
    tenant_id: str | None = None,
    allowed_site_ids: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    frames = list_odf_frames(
        conn,
        tenant_id=tenant_id,
        allowed_site_ids=allowed_site_ids,
    )
    total_cores = sum(int(f['total_cores']) for f in frames)
    occupied = sum(int(f['occupied_cores']) for f in frames)
    reserved = sum(int(f['reserved_cores']) for f in frames)
    fault = sum(int(f['fault_cores']) for f in frames)
    idle = max(0, total_cores - occupied - reserved - fault)
    return {
        'total_frames': len(frames),
        'total_trays': sum(int(f.get('tray_count') or 0) for f in frames),
        'total_cores': total_cores,
        'occupied_cores': occupied,
        'reserved_cores': reserved,
        'fault_cores': fault,
        'idle_cores': idle,
        'utilization_pct': round((occupied / total_cores) * 100, 1) if total_cores > 0 else 0.0,
    }


def get_odf_frame(conn, frame_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT f.*, s.site_code, s.site_name, s.tenant_id AS site_tenant_id
        FROM odf_frames f
        LEFT JOIN sites s ON s.id = f.site_id
        WHERE f.id = ?
        """,
        (frame_id,),
    ).fetchone()
    if not row:
        raise ValueError(f"ODF frame not found: {frame_id}")
    data = _row_to_dict(row)
    data['site_label'] = data.get('site_name') or data.get('site_code') or data.get('site_id') or ''
    return data


def create_odf_frame(
    conn,
    *,
    name: str,
    site_id: str = '',
    frame_code: str = '',
    vendor: str = 'Huawei',
    model: str = 'GPX147-576F',
    floor: str = '',
    room: str = '',
    row: str = '',
    rack_id: str = '',
    tray_count: int = 12,
    ports_per_tray: int = 48,
    connector_type: str = 'LC/UPC',
    fiber_mode: str = 'OS2',
    status: str = 'active',
    remarks: str = '',
) -> dict[str, Any]:
    cleaned_name = str(name or '').strip()
    if not cleaned_name:
        raise ValueError("ODF name is required")
    tray_count = max(1, min(24, int(tray_count or 12)))
    ports_per_tray = max(12, min(96, int(ports_per_tray or 48)))
    connector_type = str(connector_type or 'LC/UPC').strip()
    if connector_type not in VALID_CONNECTOR_TYPES:
        raise ValueError(f"connector_type must be one of {sorted(VALID_CONNECTOR_TYPES)}")
    fiber_mode = str(fiber_mode or 'OS2').strip()
    if fiber_mode not in VALID_FIBER_MODES:
        raise ValueError(f"fiber_mode must be one of {sorted(VALID_FIBER_MODES)}")
    status = str(status or 'active').strip().lower()
    if status not in VALID_FRAME_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_FRAME_STATUSES)}")

    resolved_site_id, _site_code, _site_name = rack_service._resolve_site(conn, site_id, '')
    frame_id = str(uuid.uuid4())
    code = str(frame_code or '').strip() or f"ODF_{uuid.uuid4().hex[:8].upper()}"
    dup = conn.execute("SELECT id FROM odf_frames WHERE frame_code = ? LIMIT 1", (code,)).fetchone()
    if dup:
        raise ValueError(f"ODF frame_code already exists: {code}")

    total_cores = tray_count * ports_per_tray
    now = _utc_now()
    conn.execute(
        """
        INSERT INTO odf_frames (
            id, site_id, frame_code, name, vendor, model, floor, room, row, rack_id,
            tray_count, ports_per_tray, total_cores, connector_type, fiber_mode, status,
            remarks, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            frame_id, resolved_site_id, code, cleaned_name,
            str(vendor or '').strip(), str(model or '').strip(),
            str(floor or '').strip(), str(room or '').strip(), str(row or '').strip(),
            str(rack_id or '').strip(),
            tray_count, ports_per_tray, total_cores, connector_type, fiber_mode, status,
            str(remarks or '').strip(), now, now,
        ),
    )

    # Auto-provision modular splice/patch trays
    for tray_no in range(1, tray_count + 1):
        tray_mode = (
            ('OM4' if tray_no > max(1, int(tray_count * 2 / 3)) else 'OS2')
            if fiber_mode == 'mixed'
            else fiber_mode
        )
        tray_code = _format_tray_code(tray_no)
        conn.execute(
            """
            INSERT INTO odf_trays (
                id, frame_id, tray_no, tray_code, label, port_count,
                fiber_mode, connector_type, status, remarks, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', '', ?, ?)
            """,
            (
                str(uuid.uuid4()), frame_id, tray_no, tray_code,
                f"第 {tray_no:02d} 熔配盘", ports_per_tray,
                tray_mode, connector_type, now, now,
            ),
        )
    conn.commit()
    return get_odf_frame_detail(conn, frame_id)


def update_odf_frame(conn, frame_id: str, **fields) -> dict[str, Any]:
    existing = get_odf_frame(conn, frame_id)
    updates: list[str] = []
    params: list[Any] = []

    if 'site_id' in fields and fields['site_id']:
        resolved_site_id, _, _ = rack_service._resolve_site(conn, str(fields['site_id']), '')
        fields['site_id'] = resolved_site_id

    for key in ('name', 'frame_code', 'site_id', 'vendor', 'model', 'floor', 'room', 'row', 'rack_id', 'connector_type', 'fiber_mode', 'status', 'remarks'):
        if key in fields and fields[key] is not None:
            val = str(fields[key]).strip()
            if key == 'connector_type' and val not in VALID_CONNECTOR_TYPES:
                raise ValueError(f"Invalid connector_type: {val}")
            if key == 'fiber_mode' and val not in VALID_FIBER_MODES:
                raise ValueError(f"Invalid fiber_mode: {val}")
            if key == 'status' and val not in VALID_FRAME_STATUSES:
                raise ValueError(f"Invalid status: {val}")
            if key == 'frame_code' and val != existing.get('frame_code'):
                dup = conn.execute("SELECT id FROM odf_frames WHERE frame_code = ? AND id <> ? LIMIT 1", (val, frame_id)).fetchone()
                if dup:
                    raise ValueError(f"ODF frame_code already exists: {val}")
            updates.append(f"{key} = ?")
            params.append(val)

    if updates:
        updates.append("updated_at = ?")
        params.append(_utc_now())
        params.append(frame_id)
        conn.execute(f"UPDATE odf_frames SET {', '.join(updates)} WHERE id = ?", tuple(params))
        conn.commit()
    return get_odf_frame_detail(conn, frame_id)


def delete_odf_frame(conn, frame_id: str, *, force: bool = False) -> None:
    get_odf_frame(conn, frame_id)
    if not force:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM odf_ports WHERE frame_id = ? AND status IN ('occupied', 'reserved')",
            (frame_id,),
        ).fetchone()
        cnt = int(_row_to_dict(row).get('cnt') or 0)
        if cnt > 0:
            raise ValueError(f"无法删除：该 ODF 配线架仍有 {cnt} 芯在用/预留跳纤，请先释放端子或强制删除。")
    conn.execute("DELETE FROM odf_ports WHERE frame_id = ?", (frame_id,))
    conn.execute("DELETE FROM odf_trays WHERE frame_id = ?", (frame_id,))
    conn.execute("DELETE FROM odf_frames WHERE id = ?", (frame_id,))
    conn.commit()


def update_odf_tray(conn, tray_id: str, **fields) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM odf_trays WHERE id = ?", (tray_id,)).fetchone()
    if not row:
        raise ValueError(f"ODF tray not found: {tray_id}")
    tray = _row_to_dict(row)
    updates: list[str] = []
    params: list[Any] = []
    for key in ('label', 'fiber_mode', 'connector_type', 'status', 'remarks'):
        if key in fields and fields[key] is not None:
            val = str(fields[key]).strip()
            if key == 'fiber_mode' and val not in {'OS2', 'OM4', 'OM3'}:
                raise ValueError(f"Invalid tray fiber_mode: {val}")
            if key == 'connector_type' and val not in VALID_CONNECTOR_TYPES:
                raise ValueError(f"Invalid connector_type: {val}")
            updates.append(f"{key} = ?")
            params.append(val)
    if updates:
        updates.append("updated_at = ?")
        params.append(_utc_now())
        params.append(tray_id)
        conn.execute(f"UPDATE odf_trays SET {', '.join(updates)} WHERE id = ?", tuple(params))
        conn.commit()
    updated = _row_to_dict(conn.execute("SELECT * FROM odf_trays WHERE id = ?", (tray_id,)).fetchone())
    return updated


def get_odf_frame_detail(conn, frame_id: str) -> dict[str, Any]:
    frame = get_odf_frame(conn, frame_id)
    tray_rows = conn.execute(
        "SELECT * FROM odf_trays WHERE frame_id = ? ORDER BY tray_no ASC",
        (frame_id,),
    ).fetchall()
    trays = [_row_to_dict(r) for r in tray_rows]

    port_rows = conn.execute(
        "SELECT * FROM odf_ports WHERE frame_id = ? ORDER BY tray_no ASC, port_no ASC",
        (frame_id,),
    ).fetchall()
    ports_by_key: dict[tuple[int, int], dict[str, Any]] = {}
    active_links: list[dict[str, Any]] = []
    for raw in port_rows:
        p = _row_to_dict(raw)
        ports_by_key[(int(p['tray_no']), int(p['port_no']))] = p
        if str(p.get('status') or 'idle') != 'idle':
            active_links.append(p)

    occupied_total = 0
    reserved_total = 0
    fault_total = 0
    total_cores = 0
    detailed_trays: list[dict[str, Any]] = []

    for t in trays:
        tno = int(t['tray_no'])
        tcode = str(t.get('tray_code') or _format_tray_code(tno))
        pcount = int(t.get('port_count') or 48)
        total_cores += pcount
        t_occ = 0
        t_res = 0
        t_flt = 0
        ports_list: list[dict[str, Any]] = []
        for pno in range(1, pcount + 1):
            stored = ports_by_key.get((tno, pno))
            if stored:
                st = str(stored.get('status') or 'idle').lower()
                if st == 'occupied':
                    t_occ += 1
                elif st == 'reserved':
                    t_res += 1
                elif st == 'fault':
                    t_flt += 1
                ports_list.append(stored)
            else:
                ports_list.append({
                    'id': '',
                    'frame_id': frame_id,
                    'tray_id': t['id'],
                    'tray_no': tno,
                    'port_no': pno,
                    'port_code': _format_port_code(tcode, pno),
                    'status': 'idle',
                    'fiber_type': t.get('fiber_mode') or 'OS2',
                    'connector_type': t.get('connector_type') or 'LC/UPC',
                    'a_device_id': '',
                    'a_device_name': '',
                    'a_interface_name': '',
                    'a_rack_name': '',
                    'z_endpoint_type': 'device',
                    'z_device_id': '',
                    'z_device_name': '',
                    'z_interface_name': '',
                    'z_odf_frame_id': '',
                    'z_odf_port_code': '',
                    'z_peer_label': '',
                    'cable_tag': '',
                    'circuit_id': '',
                    'attenuation_db': None,
                    'remarks': '',
                    'updated_by': '',
                    'updated_at': '',
                })
        occupied_total += t_occ
        reserved_total += t_res
        fault_total += t_flt
        detailed_trays.append({
            **t,
            'occupied_count': t_occ,
            'reserved_count': t_res,
            'fault_count': t_flt,
            'idle_count': max(0, pcount - t_occ - t_res - t_flt),
            'ports': ports_list,
        })

    if total_cores <= 0:
        total_cores = max(1, int(frame.get('total_cores') or 576))

    return {
        **frame,
        'total_cores': total_cores,
        'occupied_cores': occupied_total,
        'reserved_cores': reserved_total,
        'fault_cores': fault_total,
        'idle_cores': max(0, total_cores - occupied_total - reserved_total - fault_total),
        'utilization_pct': round((occupied_total / total_cores) * 100, 1),
        'trays': detailed_trays,
        'active_links': active_links,
    }


def upsert_odf_port(
    conn,
    *,
    frame_id: str,
    tray_no: int,
    port_no: int,
    status: str = 'occupied',
    fiber_type: str = '',
    connector_type: str = '',
    a_device_id: str = '',
    a_device_name: str = '',
    a_interface_name: str = '',
    a_rack_name: str = '',
    z_endpoint_type: str = 'device',
    z_device_id: str = '',
    z_device_name: str = '',
    z_interface_name: str = '',
    z_odf_frame_id: str = '',
    z_odf_port_code: str = '',
    z_peer_label: str = '',
    cable_tag: str = '',
    circuit_id: str = '',
    attenuation_db: float | None = None,
    remarks: str = '',
    pair_next: bool = False,
    updated_by: str = '',
) -> list[dict[str, Any]]:
    """Bind, update, or release a single ODF port (or TX/RX duplex pair when pair_next=True)."""
    get_odf_frame(conn, frame_id)
    tray_row = conn.execute(
        "SELECT * FROM odf_trays WHERE frame_id = ? AND tray_no = ?",
        (frame_id, int(tray_no)),
    ).fetchone()
    if not tray_row:
        raise ValueError(f"Tray {tray_no} not found in ODF frame {frame_id}")
    tray = _row_to_dict(tray_row)
    max_ports = int(tray.get('port_count') or 48)
    port_no = int(port_no)
    if port_no < 1 or port_no > max_ports:
        raise ValueError(f"port_no must be between 1 and {max_ports}")

    status = str(status or 'occupied').strip().lower()
    if status not in VALID_PORT_STATUSES:
        raise ValueError(f"status must be one of {sorted(VALID_PORT_STATUSES)}")
    z_endpoint_type = str(z_endpoint_type or 'device').strip().lower()
    if z_endpoint_type not in VALID_Z_ENDPOINT_TYPES:
        raise ValueError(f"z_endpoint_type must be one of {sorted(VALID_Z_ENDPOINT_TYPES)}")

    target_ports = [port_no]
    if pair_next and port_no + 1 <= max_ports:
        target_ports.append(port_no + 1)

    now = _utc_now()
    eff_fiber = str(fiber_type or tray.get('fiber_mode') or 'OS2').strip()
    eff_conn = str(connector_type or tray.get('connector_type') or 'LC/UPC').strip()
    tcode = str(tray.get('tray_code') or _format_tray_code(int(tray_no)))
    saved: list[dict[str, Any]] = []

    for idx, pno in enumerate(target_ports):
        pcode = _format_port_code(tcode, pno)
        if status == 'idle' and not any([a_device_name, z_device_name, z_peer_label, cable_tag, circuit_id, remarks]):
            conn.execute("DELETE FROM odf_ports WHERE tray_id = ? AND port_no = ?", (tray['id'], pno))
            saved.append({'tray_no': int(tray_no), 'port_no': pno, 'port_code': pcode, 'status': 'idle'})
            continue

        existing = conn.execute(
            "SELECT id FROM odf_ports WHERE tray_id = ? AND port_no = ?",
            (tray['id'], pno),
        ).fetchone()
        role_suffix = ''
        if len(target_ports) == 2 and remarks:
            role_suffix = f" ({'TX' if idx == 0 else 'RX'})" if '(TX)' not in remarks and '(RX)' not in remarks else ''

        if existing:
            pid = _row_to_dict(existing)['id']
            conn.execute(
                """
                UPDATE odf_ports SET
                    status = ?, fiber_type = ?, connector_type = ?,
                    a_device_id = ?, a_device_name = ?, a_interface_name = ?, a_rack_name = ?,
                    z_endpoint_type = ?, z_device_id = ?, z_device_name = ?, z_interface_name = ?,
                    z_odf_frame_id = ?, z_odf_port_code = ?, z_peer_label = ?,
                    cable_tag = ?, circuit_id = ?, attenuation_db = ?, remarks = ?,
                    updated_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    status, eff_fiber, eff_conn,
                    str(a_device_id or '').strip(), str(a_device_name or '').strip(),
                    str(a_interface_name or '').strip(), str(a_rack_name or '').strip(),
                    z_endpoint_type, str(z_device_id or '').strip(), str(z_device_name or '').strip(),
                    str(z_interface_name or '').strip(), str(z_odf_frame_id or '').strip(),
                    str(z_odf_port_code or '').strip(), str(z_peer_label or '').strip(),
                    str(cable_tag or '').strip(), str(circuit_id or '').strip(),
                    attenuation_db, f"{str(remarks or '').strip()}{role_suffix}",
                    str(updated_by or '').strip(), now, pid,
                ),
            )
        else:
            pid = str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO odf_ports (
                    id, frame_id, tray_id, tray_no, port_no, port_code, status,
                    fiber_type, connector_type,
                    a_device_id, a_device_name, a_interface_name, a_rack_name,
                    z_endpoint_type, z_device_id, z_device_name, z_interface_name,
                    z_odf_frame_id, z_odf_port_code, z_peer_label,
                    cable_tag, circuit_id, attenuation_db, remarks, updated_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    pid, frame_id, tray['id'], int(tray_no), pno, pcode, status,
                    eff_fiber, eff_conn,
                    str(a_device_id or '').strip(), str(a_device_name or '').strip(),
                    str(a_interface_name or '').strip(), str(a_rack_name or '').strip(),
                    z_endpoint_type, str(z_device_id or '').strip(), str(z_device_name or '').strip(),
                    str(z_interface_name or '').strip(), str(z_odf_frame_id or '').strip(),
                    str(z_odf_port_code or '').strip(), str(z_peer_label or '').strip(),
                    str(cable_tag or '').strip(), str(circuit_id or '').strip(),
                    attenuation_db, f"{str(remarks or '').strip()}{role_suffix}",
                    str(updated_by or '').strip(), now,
                ),
            )
        saved.append(_row_to_dict(conn.execute("SELECT * FROM odf_ports WHERE id = ?", (pid,)).fetchone()))

    conn.commit()
    return saved


def trace_odf_links(
    conn,
    *,
    query: str,
    tenant_id: str | None = None,
    allowed_site_ids: tuple[str, ...] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    q = str(query or '').strip().lower()
    if not q:
        return []
    pat = f"%{q}%"
    clauses = [
        "("
        "LOWER(COALESCE(p.port_code, '')) LIKE ? OR "
        "LOWER(COALESCE(p.a_device_name, '')) LIKE ? OR "
        "LOWER(COALESCE(p.a_interface_name, '')) LIKE ? OR "
        "LOWER(COALESCE(p.z_device_name, '')) LIKE ? OR "
        "LOWER(COALESCE(p.z_interface_name, '')) LIKE ? OR "
        "LOWER(COALESCE(p.z_peer_label, '')) LIKE ? OR "
        "LOWER(COALESCE(p.cable_tag, '')) LIKE ? OR "
        "LOWER(COALESCE(p.circuit_id, '')) LIKE ? OR "
        "LOWER(COALESCE(f.name, '')) LIKE ?"
        ")"
    ]
    params: list[Any] = [pat] * 9
    if tenant_id is not None:
        clauses.append("COALESCE(s.tenant_id, 'tenant-default') = ?")
        params.append(tenant_id)
    if allowed_site_ids is not None:
        if not allowed_site_ids:
            return []
        ph = ','.join('?' for _ in allowed_site_ids)
        clauses.append(f"f.site_id IN ({ph})")
        params.extend(allowed_site_ids)
    params.append(max(1, min(200, int(limit or 100))))

    rows = conn.execute(
        f"""
        SELECT p.*, f.name AS frame_name, f.frame_code, f.room, f.row,
               s.site_code, s.site_name
        FROM odf_ports p
        JOIN odf_frames f ON f.id = p.frame_id
        LEFT JOIN sites s ON s.id = f.site_id
        WHERE {' AND '.join(clauses)}
        ORDER BY f.name, p.tray_no, p.port_no
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


_IFACE_VIRTUAL_PREFIXES = (
    'vlan', 'loopback', 'inloop', 'null', 'bridge-agg', 'route-agg',
    'eth-trunk', 'port-channel', 'po', 'tunnel', 'm-eth', 'm-gigabit',
    'm-ge', 'management', 'mgmt', 'meth', 'console', 'aux', 'register',
    'sslvpn', 'dialer', 'virtual', 'bvi', 'nve', 'lo', 'veth', 'docker', 'br-',
)


def _natural_sort_key(text: str) -> list[Any]:
    return [int(tok) if tok.isdigit() else tok.lower() for tok in re.split(r'(\d+)', str(text or ''))]


def lookup_bindable_devices(
    conn,
    *,
    keyword: str = '',
    tenant_id: str | None = None,
    allowed_site_ids: tuple[str, ...] | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    """Lightweight CMDB network device + rack lookup for A-end / Z-end ODF port binding."""
    clauses: list[str] = []
    params: list[Any] = []
    if tenant_id is not None:
        clauses.append("COALESCE(d.tenant_id, 'tenant-default') = ?")
        params.append(tenant_id)
    if allowed_site_ids is not None:
        if not allowed_site_ids:
            return []
        ph = ','.join('?' for _ in allowed_site_ids)
        clauses.append(f"COALESCE(NULLIF(pa.site_id, ''), NULLIF(d.site_id, '')) IN ({ph})")
        params.extend(allowed_site_ids)
    if keyword.strip():
        pat = f"%{keyword.strip().lower()}%"
        clauses.append(
            "("
            "LOWER(COALESCE(d.hostname, '')) LIKE ? OR "
            "LOWER(COALESCE(d.ip_address, '')) LIKE ? OR "
            "LOWER(COALESCE(d.vendor, '')) LIKE ? OR "
            "LOWER(COALESCE(d.model, '')) LIKE ? OR "
            "LOWER(COALESCE(r.name, r2.name, '')) LIKE ? OR "
            "LOWER(COALESCE(pa.asset_tag, '')) LIKE ?"
            ")"
        )
        params.extend([pat] * 6)
    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ''
    effective_limit = max(1, min(200, int(limit or 80)))
    params.append(effective_limit * 2)
    rows = conn.execute(
        f"""
        SELECT d.id, d.hostname, d.ip_address, d.vendor, d.model, d.role,
               COALESCE(NULLIF(r.name, ''), NULLIF(r2.name, ''), '') AS rack_name
        FROM devices d
        LEFT JOIN physical_assets pa ON pa.id = d.asset_id
        LEFT JOIN rack_devices rd ON rd.asset_id = d.asset_id AND rd.asset_id IS NOT NULL AND rd.asset_id <> ''
        LEFT JOIN racks r ON r.id = rd.rack_id
        LEFT JOIN racks r2 ON r2.id = d.rack_id
        {where_sql}
        ORDER BY d.hostname
        LIMIT ?
        """,
        tuple(params),
    ).fetchall()
    seen_ids: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for raw in rows:
        item = _row_to_dict(raw)
        dev_id = str(item.get('id') or '')
        if not dev_id or dev_id in seen_ids:
            continue
        seen_ids.add(dev_id)
        deduped.append(item)
        if len(deduped) >= effective_limit:
            break
    return deduped


def lookup_device_interfaces(conn, device_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT interface_name, oper_status, speed, description
        FROM interfaces
        WHERE device_id = ?
        ORDER BY interface_name
        """,
        (device_id,),
    ).fetchall()
    items = []
    for raw in rows:
        item = _row_to_dict(raw)
        name = str(item.get('interface_name') or '').strip()
        low = name.lower()
        if not name or '.' in low or any(low.startswith(p) for p in _IFACE_VIRTUAL_PREFIXES):
            continue
        items.append(item)
    items.sort(key=lambda it: _natural_sort_key(it.get('interface_name') or ''))
    return items
