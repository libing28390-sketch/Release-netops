"""Canonical site identity helpers shared by monitoring and topology paths."""

from __future__ import annotations

from typing import Any


def resolve_canonical_site_id(conn: Any, value: str | None) -> str:
    """Resolve a site ID, code, or name to the canonical ``sites.id`` value.

    Asset imports historically accepted a free-text site field, so callers may
    still send a site name or code.  Persisting that label in a ``site_id``
    column breaks joins once the CMDB reads the canonical site table.
    """
    requested = str(value or '').strip()
    if not requested:
        return ''

    row = conn.execute(
        "SELECT id FROM sites WHERE id = ? LIMIT 1",
        (requested,),
    ).fetchone()
    if not row:
        row = conn.execute(
            """SELECT id FROM sites
               WHERE LOWER(TRIM(site_code)) = LOWER(TRIM(?))
                  OR LOWER(TRIM(site_name)) = LOWER(TRIM(?))
               ORDER BY CASE
                   WHEN LOWER(TRIM(site_code)) = LOWER(TRIM(?)) THEN 0
                   ELSE 1
               END, id
               LIMIT 1""",
            (requested, requested, requested),
        ).fetchone()
    if not row:
        raise ValueError(f'Unknown CMDB site: {requested}')
    return str(row['id']).strip()


def canonical_site_id(record: Any) -> str:
    if record is None:
        return ''
    if hasattr(record, 'get'):
        return str(record.get('site_id') or '').strip()
    return ''


def canonical_site_name(record: Any) -> str:
    if record is None:
        return 'Unassigned'
    if hasattr(record, 'get'):
        return str(
            record.get('site_name')
            or record.get('site_code')
            or record.get('site')
            or record.get('site_id')
            or 'Unassigned'
        ).strip()
    return 'Unassigned'


def site_scope_key(record: Any) -> str:
    return canonical_site_id(record) or 'unassigned'
