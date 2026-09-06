"""Make SNMP template selection explicit per device.

Before this migration, a saved profile was resolved by vendor + model, so
applying one profile implicitly affected every device with the same identity.
The new nullable device reference preserves existing effective associations
but makes all future selection and removal explicit.
"""

from __future__ import annotations

import re


VERSION = 181
NAME = "explicit_snmp_template_bindings"


def _columns(cursor, table: str) -> set[str]:
    cursor.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?",
        (table,),
    )
    return {str(row[0]) for row in cursor.fetchall()}



def _value(row, key: str, index: int, default: str = "") -> str:
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        try:
            value = row[index]
        except (IndexError, TypeError):
            value = default
    return default if value is None else str(value)


def _clean(value: object) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


_PLATFORM_VENDOR_NAMES = {
    "cisco": "cisco",
    "huawei": "huawei",
    "h3c": "h3c",
    "comware": "h3c",
    "arista": "arista",
    "juniper": "juniper",
    "junos": "juniper",
    "fortinet": "fortinet",
    "fortios": "fortinet",
    "ruijie": "ruijie",
    "zte": "zte",
    "raisecom": "raisecom",
    "瑞斯康达": "raisecom",
    "maipu": "maipu",
}


def _vendor_key(vendor: object, platform: object = "") -> str:
    value = _clean(vendor)
    if not value:
        platform_value = _clean(platform).replace("-", "_")
        for token, canonical in _PLATFORM_VENDOR_NAMES.items():
            if token in platform_value:
                return canonical
        return platform_value
    if value in {"瑞斯康达", "瑞斯康达通信", "raisecom"}:
        return "raisecom"
    return value


def _model_key(model: object) -> str:
    return _clean(model)


def _quote_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Unsafe database identifier: {value}")
    return '"' + value.replace('"', '""') + '"'


def _ensure_profile_columns(cursor) -> None:
    existing = _columns(cursor, "snmp_metric_profiles")
    definitions = {
        "template_name": "TEXT NOT NULL DEFAULT ''",
        "source": "TEXT NOT NULL DEFAULT 'legacy'",
        "official_preset_id": "TEXT NOT NULL DEFAULT ''",
    }
    for name, definition in definitions.items():
        if name in existing:
            continue
        cursor.execute(
            f"ALTER TABLE snmp_metric_profiles ADD COLUMN IF NOT EXISTS {name} {definition}"
        )


def _drop_postgres_vendor_model_unique(cursor) -> None:
    cursor.execute(
        """
        SELECT tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_schema = tc.constraint_schema
         AND ccu.constraint_name = tc.constraint_name
        WHERE tc.table_schema = current_schema()
          AND tc.table_name = 'snmp_metric_profiles'
          AND tc.constraint_type = 'UNIQUE'
        GROUP BY tc.constraint_name
        HAVING COUNT(*) = 2
           AND COUNT(CASE WHEN ccu.column_name IN ('vendor_key', 'model_key') THEN 1 END) = 2
        """
    )
    for row in cursor.fetchall():
        constraint_name = _value(row, "constraint_name", 0)
        if constraint_name:
            cursor.execute(
                f"ALTER TABLE snmp_metric_profiles DROP CONSTRAINT IF EXISTS "
                f"{_quote_identifier(constraint_name)}"
            )


def _backfill_device_bindings(cursor) -> None:
    profiles = cursor.execute(
        "SELECT id, vendor_key, model_key FROM snmp_metric_profiles"
    ).fetchall()
    devices = cursor.execute(
        "SELECT id, vendor, platform, model, snmp_metric_profile_id "
        "FROM devices WHERE COALESCE(TRIM(model), '') <> ''"
    ).fetchall()
    for profile in profiles:
        profile_id = _value(profile, "id", 0)
        profile_vendor = _value(profile, "vendor_key", 1).casefold()
        profile_model = _value(profile, "model_key", 2).casefold()
        if not profile_id or not profile_model:
            continue
        for device in devices:
            if _value(device, "snmp_metric_profile_id", 4).strip():
                continue
            if _vendor_key(_value(device, "vendor", 1), _value(device, "platform", 2)) != profile_vendor:
                continue
            if _model_key(_value(device, "model", 3)) != profile_model:
                continue
            cursor.execute(
                "UPDATE devices SET snmp_metric_profile_id = ? "
                "WHERE id = ? AND COALESCE(TRIM(snmp_metric_profile_id), '') = ''",
                (profile_id, _value(device, "id", 0)),
            )


def upgrade(cursor, use_pg: bool) -> None:
    _ensure_profile_columns(cursor)
    cursor.execute(
        "ALTER TABLE devices ADD COLUMN IF NOT EXISTS snmp_metric_profile_id TEXT DEFAULT ''"
    )
    _drop_postgres_vendor_model_unique(cursor)

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_devices_snmp_metric_profile_id "
        "ON devices(snmp_metric_profile_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_snmp_metric_profiles_source "
        "ON snmp_metric_profiles(source, official_preset_id)"
    )
    cursor.execute(
        "UPDATE snmp_metric_profiles SET template_name = model_name "
        "WHERE COALESCE(TRIM(template_name), '') = ''"
    )
    _backfill_device_bindings(cursor)


def downgrade(cursor, use_pg: bool) -> None:  # noqa: ARG001
    # Keep explicit bindings and template metadata during downgrade. Removing
    # them could silently stop monitoring or reintroduce global model binding.
    return None
