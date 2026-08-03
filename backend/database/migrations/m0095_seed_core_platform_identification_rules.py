"""Seed reviewed identification rules for the built-in platform catalog.

The platform registry can only return ``MATCHED`` when a SYSTEM profile has at
least one enabled rule for the command emitted by its connection driver.  The
original catalog seeded domestic profiles only, leaving common profiles such
as ``cisco_ios`` without any rule and making live detection report
``NO_MATCH`` even when the device was already bound to that profile.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


VERSION = 95
NAME = "seed_core_platform_identification_rules"


# Keep these anchors vendor/product-specific.  Generic strings such as
# ``Software`` or ``Version`` create false matches across vendors.  Domestic
# rules repeat the reviewed patterns from m0088 so this migration also repairs
# their deterministic rule rows without touching tenant-owned rules.
RULES: dict[str, tuple[str, tuple[str, ...]]] = {
    "arista_eos": ("show version", ("Arista Networks EOS", "Arista vEOS", "Arista DCS-")),
    "cisco_ios": (
        "show version",
        (
            "Cisco IOS Software",
            "Cisco IOS XE Software",
            "Cisco Internetwork Operating System Software",
        ),
    ),
    "h3c_comware": (
        "display version",
        ("H3C Comware Software", "H3C Comware Platform Software"),
    ),
    "huawei_vrp": (
        "display version",
        ("Versatile Routing Platform Software", "HUAWEI NetEngine"),
    ),
    "juniper_junos": ("show version", ("JUNOS", "Junos:")),
    "dptech_fw_s211": ("show version", ("FW1000-TS-C", "Software Release S211")),
    "maipu_s3330_v9": ("show version", ("MyPower S3330", "Software Version 9.7.")),
    "ruijie_eg_rgos11": ("show version", ("EG3000UE", "EG_RGOS 11.")),
    "ruijie_s6k_rgos12": ("show version", ("S6231-48XS8CQ", "S6K-A_RGOS 12.")),
    "zte_5900_v6": ("show version", ("ZXR10 5960", "5900 V6.", "5960X_")),
    "zte_zsrv2_v3": ("show version", ("ZXR10 1800-2S", "ZSRV2 V3.")),
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def upgrade(cursor, use_pg: bool) -> None:
    now = _now()
    for platform_code, (command, patterns) in RULES.items():
        profile = cursor.execute(
            """SELECT id FROM platform_profiles
               WHERE tenant_id IS NULL AND source = 'SYSTEM' AND platform_code = ?""",
            (platform_code,),
        ).fetchone()
        if not profile:
            continue

        profile_id = profile[0]
        for rule_order, pattern in enumerate(patterns, start=1):
            rule_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"nexora:identification:{platform_code}:{pattern}",
                )
            )
            cursor.execute(
                """INSERT INTO platform_identification_rules
                   (id, platform_profile_id, command, match_type, pattern,
                    logic_group, rule_order, confidence, negate, enabled, created_at)
                   VALUES (?, ?, ?, 'contains', ?, 'ANY', ?, 0.95, 0, 1, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     platform_profile_id = excluded.platform_profile_id,
                     command = excluded.command,
                     match_type = excluded.match_type,
                     pattern = excluded.pattern,
                     logic_group = excluded.logic_group,
                     rule_order = excluded.rule_order,
                     confidence = excluded.confidence,
                     negate = excluded.negate,
                     enabled = excluded.enabled""",
                (rule_id, profile_id, command, pattern, rule_order, now),
            )
