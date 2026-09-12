"""Canonical site identity helpers shared by monitoring and topology paths."""

from __future__ import annotations

import re
from typing import Any


_INTERNAL_SITE_ID_RE = re.compile(r'^site-[a-z0-9]+$', re.IGNORECASE)
_RESERVED_SYSTEM_SITE_VALUES = {'site-default', 'default_site'}


def is_reserved_system_site(value: Any) -> bool:
    """Return whether a site value is the legacy system fallback site."""
    return str(value or '').strip().lower() in _RESERVED_SYSTEM_SITE_VALUES


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
    canonical_id = str(row['id']).strip()
    if is_reserved_system_site(canonical_id):
        raise ValueError('System default site cannot be assigned to a business asset')
    return canonical_id


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
        for key in ('site_name', 'site_code', 'site'):
            value = str(record.get(key) or '').strip()
            if value and not _INTERNAL_SITE_ID_RE.fullmatch(value):
                return value
    return 'Unassigned'


def site_scope_key(record: Any) -> str:
    return canonical_site_id(record) or 'unassigned'
