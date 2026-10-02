from __future__ import annotations

import json

import database
from services import librenms_rule_service as rules
from services import snmp_hardware_probe_service as hardware


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return list(self._rows)


class _RuleConnection:
    """Small DB-shaped spy used to count MIB lookups without SQLite."""

    def __init__(self, rows):
        self.rule_rows = rows
        self.mib_queries = 0

    def execute(self, statement, params=()):
        normalized = " ".join(str(statement).split()).casefold()
        if normalized.startswith(("savepoint ", "release savepoint ", "rollback to savepoint ")):
            return _Rows([])
        if "from snmp_librenms_rules" in normalized:
            return _Rows(self.rule_rows)
        if "from snmp_mib_nodes" in normalized:
            self.mib_queries += 1
            return _Rows([("1.3.6.1.4.1.55555.1.1", "example.mib")])
        raise AssertionError(f"unexpected SQL in spy: {statement}")


def _identity_definition(*predicates):
    return {
        "contract": rules.IDENTITY_CONTRACT,
        "clauses": [{"supported": True, "all": list(predicates)}],
    }


def _snmp_predicate():
    return {
        "field": "snmp_get",
        "op": "=",
        "oid": "EXAMPLE-MIB::deviceIdentity",
        "values": ["ready"],
    }


def _rule(definition, *, vendor="huawei", platform="huawei_vrp"):
    return {
        "id": "rule-1",
        "os_key": "rule-1",
        "vendor": vendor,
        "platform": platform,
        "detection_json": json.dumps({"identity_match": definition}),
        "oid_candidates_json": "[]",
        "rule_status": "active",
    }


def _insert_mib(conn, *, mib_id: str, is_active: int):
    conn.execute(
        """
        INSERT INTO snmp_mibs
            (id, name, vendor, filename, created_at, updated_at, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (mib_id, "EXAMPLE-MIB", "standard", "example.mib", "2026-01-01", "2026-01-01", is_active),
    )
    conn.execute(
        """
        INSERT INTO snmp_mib_nodes
            (id, mib_id, node_name, oid, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (f"{mib_id}-node", mib_id, "deviceIdentity", "1.3.6.1.4.1.55555.1.1", "2026-01-01"),
    )
    conn.commit()


def test_active_integer_mib_row_resolves_and_disabled_row_is_ignored(isolated_db):
    conn = database.get_db_connection()
    try:
        _insert_mib(conn, mib_id="mib-active", is_active=1)
        assert rules._resolve_identity_oid(conn, "EXAMPLE-MIB::deviceIdentity") == "1.3.6.1.4.1.55555.1.1"
        assert hardware._resolve_mib_symbol(
            conn,
            "EXAMPLE-MIB::deviceIdentity",
            vendor="standard",
        ) == "1.3.6.1.4.1.55555.1.1"

        conn.execute("UPDATE snmp_mibs SET is_active = 0 WHERE id = ?", ("mib-active",))
        conn.commit()
        # A new call must observe the current database state; no global MIB cache
        # is allowed to retain the previously active row.
        assert rules._resolve_identity_oid(conn, "EXAMPLE-MIB::deviceIdentity") == ""
        assert hardware._resolve_mib_symbol(
            conn,
            "EXAMPLE-MIB::deviceIdentity",
            vendor="standard",
        ) == ""
    finally:
        conn.close()


def test_probe_plan_skips_unmatched_system_and_unknown_vendor_without_mib_queries():
    definition = _identity_definition(
        {"field": "sys_descr", "op": "contains", "values": ["Huawei"]},
        _snmp_predicate(),
    )
    unmatched = _RuleConnection([_rule(definition)])
    assert rules.identity_snmp_probe_plan(unmatched, {"sys_descr": "unrelated", "vendor": "huawei"}) == []
    assert unmatched.mib_queries == 0

    pure_snmp = _RuleConnection([_rule(_identity_definition(_snmp_predicate()), vendor="huawei")])
    assert rules.identity_snmp_probe_plan(pure_snmp, {"vendor": ""}) == []
    assert pure_snmp.mib_queries == 0


def test_probe_plan_resolves_matching_clause_once_per_token():
    definition = _identity_definition(
        {"field": "sys_descr", "op": "contains", "values": ["Huawei"]},
        _snmp_predicate(),
    )
    conn = _RuleConnection([_rule(definition)])
    identity = {"sys_descr": "Huawei VRP", "vendor": "huawei"}
    assert rules.identity_snmp_probe_plan(conn, identity) == [
        {"field": "snmp_get", "oid": "1.3.6.1.4.1.55555.1.1"},
    ]
    assert conn.mib_queries == 1


def test_identity_cache_preserves_case_sensitive_quoted_indexes():
    conn = _RuleConnection([])
    cache = {}
    upper = rules._resolve_identity_oid(conn, 'EXAMPLE-MIB::deviceIdentity."A"', cache=cache)
    lower = rules._resolve_identity_oid(conn, 'EXAMPLE-MIB::deviceIdentity."a"', cache=cache)
    assert upper.endswith(".1.65")
    assert lower.endswith(".1.97")
    assert conn.mib_queries == 2


def test_hardware_mib_cache_deduplicates_same_token_within_call():
    conn = _RuleConnection([])
    cache = {}
    token = "EXAMPLE-MIB::deviceIdentity"
    assert hardware._resolve_mib_symbol(conn, token, vendor="huawei", cache=cache)
    assert hardware._resolve_mib_symbol(conn, token, vendor="huawei", cache=cache)
    assert conn.mib_queries == 1


def test_resolve_rule_does_not_platform_fallback_past_unmatched_snmp_clause():
    definition = _identity_definition(_snmp_predicate())
    conn = _RuleConnection([_rule(definition)])
    assert rules.resolve_rule(conn, {"vendor": "huawei", "platform": "huawei_vrp"}) is None
    assert conn.mib_queries == 1


def test_resolve_rule_keeps_pure_snmp_resolution_when_vendor_is_empty():
    definition = _identity_definition(_snmp_predicate())
    conn = _RuleConnection([_rule(definition)])
    resolved = rules.resolve_rule(
        conn,
        {
            "vendor": "",
            "platform": "huawei_vrp",
            "snmp_get": {"1.3.6.1.4.1.55555.1.1": "ready"},
        },
    )
    assert resolved is not None
    assert resolved["os_key"] == "rule-1"
    assert conn.mib_queries == 1


def test_unsupported_identity_clause_is_preserved_without_mib_lookup():
    definition = {
        "contract": rules.IDENTITY_CONTRACT,
        "clauses": [{"supported": False, "all": [_snmp_predicate()]}],
    }
    conn = _RuleConnection([_rule(definition)])
    assert rules.identity_snmp_probe_plan(conn, {"vendor": "huawei"}) == []
    assert conn.mib_queries == 0
