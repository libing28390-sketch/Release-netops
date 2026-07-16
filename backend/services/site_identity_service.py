"""Canonical site identity helpers shared by monitoring and topology paths."""

from __future__ import annotations

from typing import Any


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
