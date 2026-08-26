"""Relax generic action contracts to match verified multi-vendor output."""

from __future__ import annotations

import json
from pathlib import Path

from database.migrations.m0171_h3c_operational_action_bindings import _checksum, _now

VERSION = 175
NAME = "reconcile_registry_field_contracts"


ACTION_CODES = {
    "get_version",
    "get_interface_brief",
    "get_logbuffer",
    "get_vlan_table",
    "get_temperature",
}

TEMPLATE_FILENAMES = {
    "h3c_comware_v5_display_cpu_usage.textfsm",
    "h3c_comware_v7_display_bfd_session.textfsm",
    "h3c_comware_v7_display_interface_brief.textfsm",
    "h3c_comware_v7_display_interface_brief_description.textfsm",
}


def _json(value) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False, sort_keys=True)


def _refresh_system_template_contents(cursor, now: str) -> None:
    root = Path(__file__).resolve().parents[3] / "data" / "textfsm_templates"
    for filename in sorted(TEMPLATE_FILENAMES):
        path = root / filename
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        template_rows = cursor.execute(
            "SELECT id FROM parser_templates WHERE source = 'SYSTEM' AND source_filename = ?",
            (filename,),
        ).fetchall()
        for template_row in template_rows:
            version_row = cursor.execute(
                "SELECT id FROM parser_template_versions WHERE template_id = ? ORDER BY version_number DESC LIMIT 1",
                (template_row[0],),
            ).fetchone()
            if not version_row:
                continue
            cursor.execute(
                """UPDATE parser_template_versions
                   SET content = ?, checksum = ?, status = 'PUBLISHED', updated_at = ?
                   WHERE id = ?""",
                (content, _checksum(content), now, version_row[0]),
            )


def upgrade(cursor, use_pg: bool) -> None:
    del use_pg
    try:
        cursor.execute("SELECT 1 FROM action_definitions LIMIT 1")
    except Exception:
        return

    from services.platform_registry_service import iter_action_definitions

    definitions = {
        str(item.get("action_code")): item
        for item in iter_action_definitions()
        if str(item.get("action_code")) in ACTION_CODES
    }
    now = _now()
    _refresh_system_template_contents(cursor, now)
    for action_code, definition in definitions.items():
        cursor.execute(
            """UPDATE action_definitions
               SET required_fields_json = ?, optional_fields_json = ?,
                   field_types_json = ?
               WHERE action_code = ?""",
            (
                _json(definition.get("fields") or []),
                _json(definition.get("optional_fields") or []),
                json.dumps(definition.get("field_types") or {}, ensure_ascii=False, sort_keys=True),
                action_code,
            ),
        )


def downgrade(cursor, use_pg: bool) -> None:
    del cursor, use_pg
    return None
