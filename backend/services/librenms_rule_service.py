"""Import LibreNMS OS detection and hardware definitions without running PHP.

The importer reads YAML with safe_load and emits two versioned, JSON-safe
contracts: identity predicates and structured hardware definitions.  Legacy
OID candidates remain available for existing discovery callers.
"""

from __future__ import annotations

import json
import logging
import math
import re
import subprocess
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from services.librenms_user_functions import supports_librenms_user_func
from services.snmp_vendor_registry import (
    ASSET_NETWORK_VENDORS,
    infer_librenms_vendor,
    normalize_asset_vendor,
)

try:
    import yaml
except ImportError:  # pragma: no cover - deployment dependency
    yaml = None

if yaml is not None:
    class _LibreNMSRuleLoader(yaml.SafeLoader):
        """Safe YAML loader that treats a plain equals sign as a string."""

    _LibreNMSRuleLoader.yaml_implicit_resolvers = {
        initial: [
            resolver for resolver in resolvers
            if resolver[0] != "tag:yaml.org,2002:value"
        ]
        for initial, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
else:  # pragma: no cover - deployment dependency
    _LibreNMSRuleLoader = None

logger = logging.getLogger(__name__)

RULE_CONTRACT_VERSION = "nexora.librenms.rules.v1"
IDENTITY_CONTRACT = "nexora.librenms.identity-match.v1"
HARDWARE_CONTRACT = "nexora.librenms.hardware-definition.v1"
LIBRENMS_BUNDLE_DIR = Path(__file__).resolve().parents[1] / "vendor" / "librenms"

_COMPATIBILITY_RANK = {
    "supported": 0, "partial": 1, "requires_adapter": 2, "unsupported": 3,
}
_IDENTITY_FIELDS = {
    "sysobjectid": ("sys_object_id", "oid_prefix"),
    "sysdescr": ("sys_descr", "contains"),
    "sysname": ("sys_name", "contains"),
    "syscontact": ("sys_contact", "contains"),
    "syslocation": ("sys_location", "contains"),
    "sysobjectid_regex": ("sys_object_id", "regex"),
    "sysdescr_regex": ("sys_descr", "regex"),
    "sysname_regex": ("sys_name", "regex"),
    "syscontact_regex": ("sys_contact", "regex"),
    "syslocation_regex": ("sys_location", "regex"),
}
_IDENTITY_SNMP_FIELDS = {
    "snmpget": "snmp_get",
    "snmpwalk": "snmp_walk",
}
_IDENTITY_SNMP_OPERATORS = {
    "=", "!=", "==", "!==", ">=", "<=", ">", "<", "contains",
    "not_contains", "starts", "not_starts", "ends", "not_ends",
    "regex", "not_regex", "in_array", "not_in_array", "exists",
}
_LIMIT_FIELDS = {
    "high_limit", "low_limit", "warn_limit", "low_warn_limit", "high_warn_limit",
    "low_limit_warn", "high_limit_warn", "low_limit_alarm", "high_limit_alarm",
    "low_warn", "high_warn", "threshold", "threshold_oid", "warn_threshold",
    "high_threshold", "low_threshold", "minor_threshold", "major_threshold",
    "critical_threshold",
}
_SUPPORTED_SKIP_OPERATORS = {
    "=", "==", "eq", "equals", "!=", "!==", "<", "<=", ">", ">=",
    "starts", "ends", "contains", "regex", "in_array", "not_starts",
    "not_ends", "not_contains", "not_regex", "not_in_array", "exists",
}
_AUTO_SYNC_LOCK = threading.Lock()
_AUTO_SYNC_DONE = False
_AUTO_SYNC_KEY: tuple[str, str, str] | None = None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def source_root() -> Path:
    import os

    configured = str(os.environ.get("LIBRENMS_REPO_PATH") or "").strip()
    if configured:
        return Path(configured).resolve()
    return LIBRENMS_BUNDLE_DIR.resolve()


def source_commit(root: Path) -> str:
    manifest_path = root / "source-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        commit = str(manifest.get("upstream_commit") or "").strip()
        if commit:
            return commit[:64]
    except (OSError, ValueError, AttributeError):
        pass
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True,
        ).stdout.strip()[:64]
    except Exception:
        return ""


def _json_safe(value: Any) -> Any:
    """Convert safe-loaded YAML values to data accepted by json.dumps."""
    if isinstance(value, Mapping):
        return {str(key): _json_safe(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(child) for child in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _repair_known_upstream_yaml_issues(text: str) -> tuple[str, list[str]]:
    """Repair only two structurally unambiguous formatting mistakes in upstream YAML."""
    repaired = text
    notes: list[str] = []

    # NXOS has a version key followed by two equally indented quoted OIDs
    # without YAML sequence markers. Preserve both items as a list.
    lines = repaired.splitlines(keepends=True)
    index = 0
    changed_list = False
    while index < len(lines):
        key_match = re.match(r"^(?P<parent>[ \t]*)(?P<key>[A-Za-z_][A-Za-z0-9_-]*):[ \t]*(?:\r?\n)?$", lines[index])
        if not key_match:
            index += 1
            continue
        parent_indent = len(key_match.group("parent").expandtabs(8))
        cursor = index + 1
        candidates: list[int] = []
        child_indent: int | None = None
        while cursor < len(lines):
            raw_line = lines[cursor]
            if not raw_line.strip():
                break
            indent_text = raw_line[:len(raw_line) - len(raw_line.lstrip(" \t"))]
            indent = len(indent_text.expandtabs(8))
            if indent <= parent_indent:
                break
            content = raw_line[len(indent_text):].strip()
            if child_indent is None:
                child_indent = indent
            if indent != child_indent or not re.fullmatch(r"(?:'[^'\r\n]*'|\"[^\"\r\n]*\")[ \t]*(?:\r?\n)?", raw_line[len(indent_text):]):
                candidates = []
                break
            candidates.append(cursor)
            cursor += 1
        if len(candidates) >= 2:
            for candidate in candidates:
                line = lines[candidate]
                indentation = line[:len(line) - len(line.lstrip(" \t"))]
                body = line[len(indentation):]
                lines[candidate] = f"{indentation}- {body}"
            changed_list = True
            index = candidates[-1] + 1
        else:
            index += 1
    if changed_list:
        repaired = "".join(lines)
        notes.append("recovered_quoted_scalar_sequence")

    # Scalance has an empty flow-map entry (`, ,`) before a later key. Repair
    # only commas inside an inline mapping; comments and quoted scalar text are
    # left byte-for-byte intact.
    flow_lines: list[str] = []
    count = 0
    for line in repaired.splitlines(keepends=True):
        code_end = len(line)
        quote = ""
        escaped = False
        for position, char in enumerate(line):
            if escaped:
                escaped = False
                continue
            if quote == '"' and char == "\\":
                escaped = True
                continue
            if quote:
                if char == quote:
                    quote = ""
                continue
            if char in {"'", '"'}:
                quote = char
            elif char == "#":
                code_end = position
                break
        code = line[:code_end]
        comment = line[code_end:]
        output: list[str] = []
        quote = ""
        escaped = False
        brace_depth = 0
        index = 0
        line_count = 0
        while index < len(code):
            char = code[index]
            if escaped:
                escaped = False
                output.append(char)
                index += 1
                continue
            if quote == '"' and char == "\\":
                escaped = True
                output.append(char)
                index += 1
                continue
            if quote:
                if char == quote:
                    quote = ""
                output.append(char)
                index += 1
                continue
            if char in {"'", '"'}:
                quote = char
                output.append(char)
                index += 1
                continue
            if char == "{":
                brace_depth += 1
            elif char == "}":
                brace_depth = max(0, brace_depth - 1)
            if char == "," and brace_depth > 0:
                cursor = index + 1
                while cursor < len(code) and code[cursor] in " \t":
                    cursor += 1
                if cursor < len(code) and code[cursor] == ",":
                    output.append(",")
                    index = cursor + 1
                    line_count += 1
                    continue
            output.append(char)
            index += 1
        flow_lines.append("".join(output) + comment)
        count += line_count
    if count:
        repaired = "".join(flow_lines)
        notes.append("recovered_empty_flow_mapping_slot")
    return repaired, notes


def _load_yaml_result(path: Path) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if not path.exists():
        return {}, []
    if yaml is None:
        return {}, [{
            "code": "yaml_dependency_missing",
            "path": str(path),
            "message": "PyYAML is unavailable; this LibreNMS rule file was not parsed.",
        }]
    content = path.read_text(encoding="utf-8", errors="replace")

    def parse_yaml(source: str) -> Any:
        return yaml.load(source, Loader=_LibreNMSRuleLoader)

    try:
        value = parse_yaml(content)
        if value is None:
            return {}, []
        if not isinstance(value, Mapping):
            return {}, [{
                "code": "yaml_root_not_mapping",
                "path": str(path),
                "message": "LibreNMS definition root must be a mapping.",
            }]
        return dict(value), []
    except Exception as initial_error:
        repaired, repairs = _repair_known_upstream_yaml_issues(content)
        if repairs:
            try:
                value = parse_yaml(repaired)
                if value is None:
                    value = {}
                if isinstance(value, Mapping):
                    return dict(value), [{
                        "code": "yaml_recovered_upstream_format",
                        "path": str(path),
                        "message": "LibreNMS YAML contains a known formatting error; parsed a conservative in-memory repair: " + ", ".join(repairs) + ".",
                    }]
            except Exception as recovery_error:
                logger.debug("LibreNMS YAML recovery failed for %s: %s", path, recovery_error)
        logger.debug("LibreNMS YAML parse failed for %s: %s", path, initial_error)
        return {}, [{
            "code": "yaml_parse_error",
            "path": str(path),
            "message": f"LibreNMS YAML could not be parsed: {type(initial_error).__name__}.",
        }]


def _load_yaml(path: Path) -> dict[str, Any]:
    """Backward-compatible internal helper returning only parsed YAML."""
    return _load_yaml_result(path)[0]


def _numeric_oid(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\{\{[^}]+\}\}", "", text).strip().strip(".")
    match = re.search(r"(?:^|[^0-9])(1(?:\.[0-9]+)+)(?:$|[^0-9])", text)
    return "." + match.group(1) if match else ""


def _category(context: str, definition: Mapping[str, Any] | None = None) -> str:
    fields = definition or {}
    token = " ".join(
        [context, *(str(fields.get(key) or "") for key in ("state_name", "descr", "oid", "value"))]
    ).casefold()
    if any(item in token for item in ("cpu", "processor", "cpurate", "cpuload")):
        return "cpu"
    if any(item in token for item in ("memory", "mempool", "memusage", "buffer")):
        return "memory"
    if "temp" in token:
        return "temperature"
    if "fan" in token:
        return "fan"
    if any(item in token for item in ("power", "psu", "supply")):
        return "power_supply"
    if any(item in token for item in ("accesspoint", "onlineap", "wireless")):
        return "wireless_ap_online_count"
    if any(item in token for item in ("client", "station", "assocuser")):
        return "wireless_client_online_count"
    return "other"


def _collect_candidates(value: Any, *, path: str = "") -> list[dict[str, Any]]:
    """Produce the legacy numeric OID view, without executing or interpreting code."""
    output: list[dict[str, Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if str(key).casefold() in {"num_oid", "num_oids", "numeric_oid"}:
                values = child if isinstance(child, list) else [child]
                for raw in values:
                    oid = _numeric_oid(raw)
                    if oid:
                        output.append({
                            "category": _category(child_path),
                            "oid": oid,
                            "context": child_path,
                        })
            output.extend(_collect_candidates(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            output.extend(_collect_candidates(child, path=f"{path}[{index}]"))
    return output


def _diagnostic(code: str, path: str, message: str, *, feature: str = "") -> dict[str, str]:
    result = {"code": code, "path": path, "message": message}
    if feature:
        result["feature"] = feature
    return result


def _compatibility(level: str, diagnostics: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "level": level,
        "diagnostics": diagnostics,
    }


def _worst_compatibility(*levels: str) -> str:
    return max(levels or ("supported",), key=lambda level: _COMPATIBILITY_RANK.get(level, 3))


def _as_values(value: Any, *, field: str, path: str) -> tuple[list[Any], str | None]:
    if isinstance(value, Mapping):
        if "prefix" in value and field == "sysObjectID":
            value = value.get("prefix")
        elif "any" in value:
            value = value.get("any")
        elif "values" in value:
            value = value.get("values")
        elif "value" in value:
            value = value.get("value")
        else:
            return [], f"Dictionary value for {field} must use prefix, any, values, or value."
    values = value if isinstance(value, (list, tuple)) else [value]
    if not values or all(item is None or str(item).strip() == "" for item in values):
        return [], f"Condition {field} has no usable values."
    return list(values), None


def _regex_parts(value: Any) -> tuple[str, int, str | None]:
    """Translate the safe subset of PHP/PCRE delimiters and modifiers to Python re."""
    raw = str(value or "").strip()
    pattern = raw
    flags = 0
    if raw.startswith("/"):
        closing = -1
        for index in range(len(raw) - 1, 0, -1):
            if raw[index] != "/":
                continue
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and raw[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                closing = index
                break
        if closing < 0:
            return raw, flags, "Delimited PCRE is missing its closing slash."
        modifiers = raw[closing + 1:]
        if any(char not in "imsxu" for char in modifiers):
            return raw, flags, f"Unsupported PCRE modifier(s): {modifiers}."
        pattern = raw[1:closing]
        if "i" in modifiers:
            flags |= re.IGNORECASE
        if "m" in modifiers:
            flags |= re.MULTILINE
        if "s" in modifiers:
            flags |= re.DOTALL
        if "x" in modifiers:
            flags |= re.VERBOSE
    # PCRE's named-group spelling is accepted by LibreNMS rules but differs in Python.
    pattern = re.sub(r"\(\?<([A-Za-z_][A-Za-z0-9_]*)>", r"(?P<\1>", pattern)
    try:
        re.compile(pattern, flags)
    except re.error as exc:
        return pattern, flags, f"Regex syntax is unsupported by the safe Python matcher: {exc}."
    return pattern, flags, None


def _identity_oid_token_supported(value: Any) -> bool:
    token = str(value or "").strip()
    if re.fullmatch(r"\.?\d+(?:\.\d+)*", token):
        return True
    return re.fullmatch(
        r"[A-Za-z][A-Za-z0-9_-]*::[A-Za-z][A-Za-z0-9_-]*(?:\.(?:\d+|\"[^\"\\]*\"|'[^'\\]*'))*",
        token,
    ) is not None


def _compile_identity(detection: Mapping[str, Any], *, source_path: str = "") -> dict[str, Any]:
    default_mib_dir = detection.get("mib_dir")
    raw_discovery = detection.get("discovery")
    if raw_discovery is None:
        legacy_fields = {
            key: detection[key]
            for key in (
                "sysObjectID", "sysDescr", "sysName", "sysContact", "sysLocation",
                "sysObjectID_regex", "sysDescr_regex", "sysName_regex",
            )
            if key in detection
        }
        raw_discovery = [legacy_fields] if legacy_fields else []
    if isinstance(raw_discovery, Mapping):
        raw_clauses = [raw_discovery]
    elif isinstance(raw_discovery, (list, tuple)):
        raw_clauses = list(raw_discovery)
    elif raw_discovery in (None, ""):
        raw_clauses = []
    else:
        raw_clauses = [raw_discovery]

    diagnostics: list[dict[str, str]] = []
    clauses: list[dict[str, Any]] = []
    for clause_index, raw_clause in enumerate(raw_clauses):
        clause_path = f"{source_path}.discovery[{clause_index}]".strip(".")
        predicates: list[dict[str, Any]] = []
        clause_supported = True
        if not isinstance(raw_clause, Mapping):
            diagnostics.append(_diagnostic(
                "unsupported_identity_clause",
                clause_path,
                "Each discovery alternative must be a mapping; this alternative will never match.",
                feature=type(raw_clause).__name__,
            ))
            clauses.append({"all": [], "supported": False})
            continue

        for raw_key, raw_value in raw_clause.items():
            key = str(raw_key)
            negated = key.casefold().endswith("_except")
            field_key = key[:-7] if negated else key
            snmp_field = _IDENTITY_SNMP_FIELDS.get(field_key.casefold())
            predicate_path = f"{clause_path}.{key}"
            if snmp_field:
                if not isinstance(raw_value, Mapping):
                    diagnostics.append(_diagnostic(
                        "unsupported_identity_snmp_clause",
                        predicate_path,
                        "SNMP identity conditions must provide an OID and expected value; this alternative will never match.",
                        feature=field_key,
                    ))
                    clause_supported = False
                    continue
                oid_token = str(raw_value.get("oid") or "").strip()
                if not _identity_oid_token_supported(oid_token) or "value" not in raw_value:
                    diagnostics.append(_diagnostic(
                        "unsupported_identity_snmp_clause",
                        predicate_path,
                        "SNMP identity conditions need a numeric or qualified MIB OID and a value; this alternative will never match.",
                        feature=field_key,
                    ))
                    clause_supported = False
                    continue
                operator = str(raw_value.get("op") or "contains").strip().casefold()
                if operator not in _IDENTITY_SNMP_OPERATORS:
                    diagnostics.append(_diagnostic(
                        "unsupported_identity_snmp_operator",
                        predicate_path + ".op",
                        f"LibreNMS SNMP identity operator {operator!r} is not implemented; this alternative will never match.",
                        feature=operator,
                    ))
                    clause_supported = False
                    continue
                expected = raw_value.get("value")
                expected_values = expected if isinstance(expected, (list, tuple)) else [expected]
                if not expected_values:
                    diagnostics.append(_diagnostic(
                        "unsupported_identity_snmp_value",
                        predicate_path + ".value",
                        "SNMP identity conditions need at least one expected value; this alternative will never match.",
                        feature=field_key,
                    ))
                    clause_supported = False
                    continue
                predicates.append({
                    "field": snmp_field,
                    "source_field": key,
                    "op": operator,
                    "values": _json_safe(list(expected_values)),
                    "oid": oid_token,
                    "mib_dir": _json_safe(raw_value.get("mib_dir", default_mib_dir)),
                    "options": _json_safe(raw_value.get("options")),
                    "negated": negated,
                })
                continue
            spec = _IDENTITY_FIELDS.get(field_key.casefold())
            if not spec:
                diagnostics.append(_diagnostic(
                    "unsupported_identity_feature",
                    predicate_path,
                    f"LibreNMS identity field {key!r} is not implemented; this alternative will never match.",
                    feature=key,
                ))
                clause_supported = False
                continue
            identity_field, operator = spec
            values, error = _as_values(raw_value, field=field_key, path=predicate_path)
            if error:
                diagnostics.append(_diagnostic(
                    "unsupported_identity_value",
                    predicate_path,
                    error + " This alternative will never match.",
                    feature=field_key,
                ))
                clause_supported = False
                continue

            normalized: list[str] = []
            field_values_supported = True
            for raw in values:
                value = str(raw).strip()
                if operator == "oid_prefix":
                    oid_text = value.strip(".")
                    if not oid_text or not all(part.isdigit() for part in oid_text.split(".")):
                        diagnostics.append(_diagnostic(
                            "unsupported_sysobjectid_prefix",
                            predicate_path,
                            f"sysObjectID prefix {value!r} is not a numeric OID prefix.",
                            feature=field_key,
                        ))
                        field_values_supported = False
                    else:
                        normalized.append(oid_text)
                elif operator == "regex":
                    pattern, _flags, regex_error = _regex_parts(value)
                    if regex_error:
                        diagnostics.append(_diagnostic(
                            "unsupported_identity_regex",
                            predicate_path,
                            regex_error + " This alternative will never match.",
                            feature=field_key,
                        ))
                        field_values_supported = False
                    else:
                        normalized.append(value)
                else:
                    normalized.append(value)
            if not field_values_supported:
                clause_supported = False
                continue
            predicates.append({
                "field": identity_field,
                "source_field": field_key,
                "op": operator,
                "values": normalized,
                "negated": negated,
            })
        clauses.append({"all": predicates, "supported": clause_supported})

    if not clauses:
        diagnostics.append(_diagnostic(
            "no_identity_discovery_conditions",
            f"{source_path}.discovery".strip("."),
            "No supported OS identity conditions were defined.",
        ))
        level = "partial"
    elif all(not clause["supported"] for clause in clauses):
        level = "unsupported"
    elif any(not clause["supported"] for clause in clauses):
        level = "partial"
    else:
        level = "supported"
    return {
        "contract": IDENTITY_CONTRACT,
        "clauses": clauses,
        "compatibility": level,
        "diagnostics": diagnostics,
    }


def _sensor_component_class(sensor_class: str, definition: Mapping[str, Any]) -> tuple[str, str]:
    token = " ".join(
        str(definition.get(key) or "")
        for key in ("state_name", "descr", "oid", "value", "index")
    ).casefold()
    if sensor_class == "state":
        if "fan" in token:
            return "fan_state", "state"
        if any(word in token for word in ("power", "supply", "psu")):
            return "power_supply_state", "state"
        return "component_state", "state"
    if sensor_class in {"temp", "temperature"}:
        return "temperature", "temperature"
    if sensor_class in {"fan", "fanspeed", "fan_speed"}:
        return "fan", "fan_speed"
    if sensor_class in {"power", "power_supply"}:
        return "power_measurement", "power"
    if sensor_class in {"voltage", "current"}:
        return sensor_class, sensor_class
    return sensor_class or "sensor", sensor_class or "measurement"


def _definition_diagnostics(
    entry: Mapping[str, Any],
    path: str,
    *,
    module: str = "",
) -> list[tuple[str, dict[str, str]]]:
    findings: list[tuple[str, dict[str, str]]] = []
    if entry.get("user_func") and not supports_librenms_user_func(entry.get("user_func")):
        findings.append(("requires_adapter", _diagnostic(
            "librenms_user_function_requires_adapter",
            path + ".user_func",
            "LibreNMS user_func is preserved as metadata, but no reviewed native adapter is available.",
            feature=str(entry.get("user_func")),
        )))
    for field in ("skip_value_lt", "skip_value_gt"):
        if field not in entry or entry.get(field) is None:
            continue
        limits = entry[field] if isinstance(entry[field], list) else [entry[field]]
        for index, limit in enumerate(limits):
            try:
                float(limit)
            except (TypeError, ValueError):
                findings.append(("requires_adapter", _diagnostic(
                    "invalid_skip_value_threshold",
                    f"{path}.{field}[{index}]",
                    "LibreNMS skip thresholds must be numeric for the native probe.",
                    feature=field,
                )))
    skip_values = entry.get("skip_values")
    if skip_values is not None:
        skip_conditions = skip_values if isinstance(skip_values, list) else [skip_values]
        for index, condition in enumerate(skip_conditions):
            if not isinstance(condition, Mapping):
                if isinstance(condition, (str, int, float, bool)):
                    # LibreNMS scalar entries mean "skip if the polled value
                    # equals this value"; the native probe implements that.
                    continue
                findings.append(("requires_adapter", _diagnostic(
                    "unsupported_skip_value_shape",
                    f"{path}.skip_values[{index}]",
                    "Skip condition is preserved, but its shape is not supported by the native probe.",
                )))
                continue
            operator = str(condition.get("op") or "!=").strip().casefold()
            if operator and operator not in _SUPPORTED_SKIP_OPERATORS:
                findings.append(("requires_adapter", _diagnostic(
                    "unsupported_skip_value_operator",
                    f"{path}.skip_values[{index}].op",
                    f"Skip operator {operator!r} is preserved but requires a native adapter.",
                    feature=operator,
                )))
            if operator in {"regex", "not_regex"}:
                pattern, _flags, regex_error = _regex_parts(condition.get("value"))
                if regex_error:
                    findings.append(("requires_adapter", _diagnostic(
                        "unsupported_skip_regex_pattern",
                        f"{path}.skip_values[{index}].value",
                        regex_error,
                        feature=pattern[:120],
                    )))
            if condition.get("device"):
                device_field = str(condition.get("device") or "").strip().casefold()
                if device_field in {"hardware", "version"}:
                    findings.append(("partial", _diagnostic(
                        "skip_device_field_requires_identity",
                        f"{path}.skip_values[{index}].device",
                        "This LibreNMS condition is evaluated from the discovered device model/version; if that identity value is missing, the sample remains unsupported.",
                        feature=device_field,
                    )))
                else:
                    findings.append(("requires_adapter", _diagnostic(
                        "skip_device_field_requires_adapter",
                        f"{path}.skip_values[{index}].device",
                        "This LibreNMS device field is preserved, but the native probe only resolves hardware and version from device identity.",
                        feature=device_field,
                    )))
            if operator in {"in_array", "not_in_array"}:
                alternatives = condition.get("values") if isinstance(condition.get("values"), list) else condition.get("value") if isinstance(condition.get("value"), list) else []
                if not alternatives:
                    findings.append(("requires_adapter", _diagnostic(
                        "unsupported_skip_value_shape",
                        f"{path}.skip_values[{index}]",
                        "Array skip operators require a non-empty values or list-valued value field.",
                        feature=operator,
                    )))
    if module == "mempools":
        relations = {key for key in ("used", "total", "free", "percent_used") if entry.get(key) not in (None, "")}
        if not relations:
            findings.append(("partial", _diagnostic(
                "mempool_relations_missing",
                path,
                "Mempool definition has no used, total, free, or percent_used relation.",
            )))
        elif len(relations) < 2 and relations != {"percent_used"}:
            findings.append(("partial", _diagnostic(
                "mempool_relations_incomplete",
                path,
                "Mempool byte quantities require at least two LibreNMS relations; percent_used alone is allowed.",
            )))
    elif not entry.get("num_oid"):
        findings.append(("partial", _diagnostic(
            "definition_without_num_oid",
            path,
            "Definition is retained, but a numeric polling OID is not supplied by this YAML entry.",
            feature="num_oid",
        )))
    elif not _numeric_oid(entry.get("num_oid")):
        findings.append(("requires_adapter", _diagnostic(
            "symbolic_num_oid_requires_resolution",
            path + ".num_oid",
            "num_oid is preserved but cannot be reduced to a numeric OID without MIB/template resolution.",
            feature="num_oid",
        )))
    return findings


def _memory_relation(value: Any) -> dict[str, Any] | None:
    """Tag LibreNMS mempool relation values as constants or OID references."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return {"kind": "unsupported", "value": value}
    if isinstance(value, (int, float)):
        number = float(value)
        if math.isfinite(number):
            return {"kind": "constant", "value": number}
        return {"kind": "unsupported", "value": str(value)}

    token = str(value).strip()
    if not token:
        return None
    # LibreNMS numeric OIDs are normally dot-prefixed or have multiple arcs;
    # a scalar such as "268435456" is a constant byte quantity.
    if token.startswith(".") or re.fullmatch(r"\d+(?:\.\d+){2,}", token):
        return {"kind": "oid", "value": token}
    try:
        number = float(token)
    except (TypeError, ValueError):
        return {"kind": "oid", "value": token}
    if math.isfinite(number):
        return {"kind": "constant", "value": number}
    return {"kind": "unsupported", "value": token}


def _hardware_entry(
    module: str,
    source_class: str,
    definition: Mapping[str, Any],
    path: str,
) -> dict[str, Any]:
    raw = _json_safe(dict(definition))
    if module == "processors":
        component_class, measurement_type = "processor", "cpu_usage"
    elif module == "mempools":
        component_class, measurement_type = "memory_pool", "memory_pool"
    else:
        component_class, measurement_type = _sensor_component_class(source_class, definition)

    entry: dict[str, Any] = {
        "source_module": module,
        "source_class": source_class,
        "component_class": component_class,
        "measurement_type": measurement_type,
        "table_oid": raw.get("oid"),
        "value_oid": raw.get("value"),
        "num_oid": raw.get("num_oid"),
        "numeric_oid_prefix": _numeric_oid(raw.get("num_oid")),
        "index": raw.get("index"),
        "descr": raw.get("descr"),
        "group": raw.get("group"),
        "entPhysicalIndex": raw.get("entPhysicalIndex"),
        "entPhysicalIndex_measured": raw.get("entPhysicalIndex_measured"),
        "unit": raw.get("unit"),
        "units": raw.get("units"),
        "scale": raw.get("scale"),
        "divisor": raw.get("divisor"),
        "multiplier": raw.get("multiplier"),
        "offset": raw.get("offset"),
        "precision": raw.get("precision"),
        "user_func": raw.get("user_func"),
        "skip_values": _expanded_skip_values(raw),
        "state_name": raw.get("state_name"),
        "states": raw.get("states"),
        "limits": {key: raw[key] for key in raw if key.casefold() in _LIMIT_FIELDS or "limit" in key.casefold()},
        "raw": raw,
    }
    if module == "mempools":
        entry["memory"] = {
            "used_oid": raw.get("used"),
            "free_oid": raw.get("free"),
            "total_oid": raw.get("total"),
            "percent_used_oid": raw.get("percent_used"),
            "relations": {
                name: relation
                for name in ("used", "free", "total", "percent_used")
                if (relation := _memory_relation(raw.get(name))) is not None
            },
            "precision": raw.get("precision"),
            "allocation_unit": raw.get("units"),
            "pool_class": raw.get("mib"),
        }
    if isinstance(raw.get("states"), list):
        entry["state_mapping"] = [
            {
                "raw_value": state.get("value"),
                "description": state.get("descr"),
                "generic_state": state.get("generic"),
            }
            for state in raw["states"]
            if isinstance(state, Mapping)
        ]
    return entry


def _values_for_merge(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else [value]


def _merge_group_options(options: Any, definition: Mapping[str, Any]) -> dict[str, Any]:
    """Apply LibreNMS class options, including its index-based array_replace semantics."""
    group = dict(options) if isinstance(options, Mapping) else {}
    merged = {**group, **dict(definition)}
    for key in ("skip_values", "skip_value_lt", "skip_value_gt"):
        if key not in group or key not in definition:
            continue
        values = _values_for_merge(group[key])
        # LibreNMS casts a null entry value to an empty array before
        # array_replace, leaving inherited class-level conditions in place.
        entry_values = [] if definition[key] is None else _values_for_merge(definition[key])
        for index, value in enumerate(entry_values):
            if index < len(values):
                values[index] = value
            else:
                values.append(value)
        merged[key] = values
    return merged


def _expanded_skip_values(definition: Mapping[str, Any]) -> list[Any] | None:
    """Normalize LibreNMS skip_values and scalar low/high filters for the probe."""
    values: list[Any] = []
    skip_values = definition.get("skip_values")
    if skip_values is not None:
        values.extend(_values_for_merge(skip_values))
    for field, operator in (("skip_value_lt", "<"), ("skip_value_gt", ">")):
        raw_thresholds = definition.get(field)
        if raw_thresholds is None:
            continue
        for threshold in _values_for_merge(raw_thresholds):
            values.append({"op": operator, "value": threshold})
    return values or None


def _parse_hardware_definitions(discovery: Mapping[str, Any], *, source_path: str) -> dict[str, Any]:
    modules = discovery.get("modules")
    diagnostics: list[dict[str, str]] = []
    entries: dict[str, list[dict[str, Any]]] = {
        "processors": [], "mempools": [], "sensors": [],
    }
    compatibility_levels: list[str] = []

    if modules is not None and not isinstance(modules, Mapping):
        diagnostics.append(_diagnostic(
            "unsupported_modules_shape",
            source_path + ".modules",
            "LibreNMS modules must be a mapping; hardware definitions were not inferred.",
        ))
        return {
            "contract": HARDWARE_CONTRACT,
            **entries,
            "compatibility": _compatibility("unsupported", diagnostics),
        }

    modules = modules if isinstance(modules, Mapping) else {}
    module_paths: list[tuple[str, str, Any, Mapping[str, Any]]] = []
    for module in ("processors", "mempools"):
        section = modules.get(module)
        if section is None:
            continue
        if not isinstance(section, Mapping):
            diagnostics.append(_diagnostic(
                "unsupported_hardware_module_shape",
                f"{source_path}.modules.{module}",
                f"{module}.data must be a list; the source structure was preserved as a rule diagnostic.",
            ))
            compatibility_levels.append("unsupported")
            continue
        data = section.get("data")
        if data is None:
            diagnostics.append(_diagnostic(
                "hardware_module_data_missing",
                f"{source_path}.modules.{module}",
                f"{module} has no data list.",
            ))
            compatibility_levels.append("partial")
            continue
        module_paths.append((module, module, data, section.get("options") if isinstance(section.get("options"), Mapping) else {}))

    sensors = modules.get("sensors")
    if sensors is not None and not isinstance(sensors, Mapping):
        diagnostics.append(_diagnostic(
            "unsupported_sensor_module_shape",
            f"{source_path}.modules.sensors",
            "sensors must map sensor classes to definitions.",
        ))
        compatibility_levels.append("unsupported")
    elif isinstance(sensors, Mapping):
        for sensor_class, section in sensors.items():
            normalized_class = str(sensor_class)
            if normalized_class.casefold() == "additional_oids":
                continue
            if not isinstance(section, Mapping):
                diagnostics.append(_diagnostic(
                    "unsupported_sensor_class_shape",
                    f"{source_path}.modules.sensors.{normalized_class}",
                    "Sensor class definition must be a mapping containing data.",
                ))
                compatibility_levels.append("unsupported")
                continue
            if "data" not in section:
                # Non-polling sensor metadata such as options is not a definition.
                continue
            module_paths.append((
                "sensors", normalized_class, section.get("data"),
                section.get("options") if isinstance(section.get("options"), Mapping) else {},
            ))

    for module, source_class, data, group_options in module_paths:
        path = f"{source_path}.modules.{module}"
        if module == "sensors":
            path += f".{source_class}"
        path += ".data"
        if not isinstance(data, list):
            diagnostics.append(_diagnostic(
                "unsupported_hardware_data_shape",
                path,
                "Definition data must be a list; no entries were guessed from this structure.",
            ))
            compatibility_levels.append("unsupported")
            continue
        for index, definition in enumerate(data):
            definition_path = f"{path}[{index}]"
            if not isinstance(definition, Mapping):
                diagnostics.append(_diagnostic(
                    "unsupported_hardware_entry_shape",
                    definition_path,
                    "Hardware definition entry must be a mapping.",
                ))
                compatibility_levels.append("partial")
                continue
            effective_definition = _merge_group_options(group_options, definition)
            entry = _hardware_entry(module, source_class, effective_definition, definition_path)
            entries[module].append(entry)
            for level, item in _definition_diagnostics(effective_definition, definition_path, module=module):
                diagnostics.append(item)
                compatibility_levels.append(level)

    if not any(entries.values()):
        diagnostics.append(_diagnostic(
            "no_structured_hardware_definitions",
            source_path + ".modules",
            "No processors, mempools, or sensor data definitions were found in LibreNMS YAML.",
        ))
        compatibility_levels.append("partial")
    level = _worst_compatibility(*compatibility_levels) if compatibility_levels else "supported"
    return {
        "contract": HARDWARE_CONTRACT,
        **entries,
        "compatibility": _compatibility(level, diagnostics),
    }


def _rule_compatibility(identity: Mapping[str, Any], hardware: Mapping[str, Any]) -> dict[str, Any]:
    identity_level = str(identity.get("compatibility") or "partial")
    hardware_level = str((hardware.get("compatibility") or {}).get("level") or "partial")
    diagnostics = [
        *identity.get("diagnostics", []),
        *((hardware.get("compatibility") or {}).get("diagnostics", [])),
    ]
    return {
        "version": RULE_CONTRACT_VERSION,
        "level": _worst_compatibility(identity_level, hardware_level),
        "identity_level": identity_level,
        "hardware_level": hardware_level,
        "diagnostics": diagnostics,
    }


def parse_rules(root: Path | None = None) -> list[dict[str, Any]]:
    """Parse OS YAML files and return versioned definitions plus legacy candidates.

    The identity contract treats top-level discovery list items as OR alternatives,
    keys inside a clause as AND predicates, and values inside a field list as OR.
    Unsupported predicates remain in diagnostics and make their whole clause
    non-matching, so parsing never broadens an upstream identity rule.
    """
    root = (root or source_root()).resolve()
    detection_dir = root / "resources" / "definitions" / "os_detection"
    discovery_dir = root / "resources" / "definitions" / "os_discovery"
    if not detection_dir.exists():
        return []
    commit = source_commit(root)
    rules: list[dict[str, Any]] = []
    for detection_path in sorted(detection_dir.glob("*.yaml")):
        os_key = detection_path.stem.casefold()
        detection, detection_diagnostics = _load_yaml_result(detection_path)
        discovery_path = discovery_dir / detection_path.name
        discovery, discovery_diagnostics = _load_yaml_result(discovery_path)
        source_path = str(detection_path.relative_to(root)).replace("\\", "/")
        discovery_source_path = str(discovery_path.relative_to(root)).replace("\\", "/")
        identity = _compile_identity(detection, source_path=source_path)
        hardware = _parse_hardware_definitions(discovery, source_path=discovery_source_path)
        load_diagnostics = [*detection_diagnostics, *discovery_diagnostics]
        if load_diagnostics:
            identity["diagnostics"].extend(detection_diagnostics)
            hardware["compatibility"]["diagnostics"].extend(discovery_diagnostics)
            detection_errors = [
                item for item in detection_diagnostics
                if item.get("code") != "yaml_recovered_upstream_format"
            ]
            discovery_errors = [
                item for item in discovery_diagnostics
                if item.get("code") != "yaml_recovered_upstream_format"
            ]
            if detection_errors and identity["compatibility"] == "supported":
                identity["compatibility"] = "partial"
            if discovery_errors and hardware["compatibility"]["level"] == "supported":
                hardware["compatibility"]["level"] = "partial"
        candidates = _collect_candidates(discovery)
        compatibility = _rule_compatibility(identity, hardware)
        raw_identity = {
            "discovery": _json_safe(detection.get("discovery") or []),
            "sysDescr": _json_safe(detection.get("sysDescr") or []),
            "sysDescr_regex": _json_safe(detection.get("sysDescr_regex") or []),
        }
        rules.append({
            "id": f"librenms-{os_key}-{commit[:12] or 'local'}",
            "os_key": os_key,
            "vendor": normalize_asset_vendor(infer_librenms_vendor(os_key, detection)),
            "platform": str(detection.get("os") or os_key),
            "display_name": str(detection.get("text") or os_key),
            "detection": raw_identity,
            "identity_match": identity,
            "hardware_definitions": hardware,
            "rule_contract_version": RULE_CONTRACT_VERSION,
            "compatibility": compatibility,
            "oid_candidates": candidates,
            "source_path": source_path,
            "discovery_source_path": discovery_source_path,
            "source_commit": commit,
            "rule_status": "active" if candidates or detection else "identity_only",
            "generated_at": _now(),
        })
    return rules


def sync_rules(conn: Any, root: Path | None = None) -> dict[str, Any]:
    rules = parse_rules(root)
    if not rules:
        return {
            "imported": 0, "candidates": 0, "source_commit": "",
            "diagnostics": 0, "compatibility": {},
        }
    compatibility_counts: dict[str, int] = {}
    for rule in rules:
        compatibility_counts[rule["compatibility"]["level"]] = (
            compatibility_counts.get(rule["compatibility"]["level"], 0) + 1
        )
        persisted_detection = {
            **rule["detection"],
            "identity_match": rule["identity_match"],
            "hardware_definitions": rule["hardware_definitions"],
            "rule_contract_version": rule["rule_contract_version"],
            "compatibility": rule["compatibility"],
            "raw_discovery": rule["detection"].get("discovery", []),
        }
        conn.execute(
            """
            INSERT INTO snmp_librenms_rules
              (id, os_key, vendor, platform, display_name, detection_json,
               oid_candidates_json, source_path, source_commit, rule_status,
               generated_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
              vendor = excluded.vendor, platform = excluded.platform,
              display_name = excluded.display_name, detection_json = excluded.detection_json,
              oid_candidates_json = excluded.oid_candidates_json, source_path = excluded.source_path,
              source_commit = excluded.source_commit, rule_status = excluded.rule_status,
              updated_at = excluded.updated_at
            """,
            (
                rule["id"], rule["os_key"], rule["vendor"], rule["platform"], rule["display_name"],
                json.dumps(persisted_detection, ensure_ascii=False, sort_keys=True),
                json.dumps(rule["oid_candidates"], ensure_ascii=False, sort_keys=True),
                rule["source_path"], rule["source_commit"], rule["rule_status"],
                rule["generated_at"], _now(),
            ),
        )
    current_commit = str(rules[0].get("source_commit") or "")
    if current_commit:
        conn.execute(
            """
            UPDATE snmp_librenms_rules
               SET rule_status = 'inactive', updated_at = ?
             WHERE id LIKE 'librenms-%'
               AND source_commit <> ?
               AND rule_status IN ('active', 'identity_only')
            """,
            (_now(), current_commit),
        )
    conn.commit()
    return {
        "imported": len(rules),
        "candidates": sum(len(rule["oid_candidates"]) for rule in rules),
        "source_commit": str(rules[0]["source_commit"]),
        "diagnostics": sum(len(rule["compatibility"]["diagnostics"]) for rule in rules),
        "compatibility": compatibility_counts,
    }


def sync_rules_from_repository(root: Path | None = None) -> dict[str, Any]:
    from database import get_db_connection

    conn = get_db_connection()
    try:
        return sync_rules(conn, root)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _legacy_identity_definition(detection: Mapping[str, Any]) -> dict[str, Any]:
    raw = detection.get("raw_discovery")
    if raw is None:
        raw = detection.get("discovery")
    if raw is None:
        raw = detection.get("sysObjectID")
    legacy: dict[str, Any] = {"discovery": raw or []}
    for key in ("sysDescr", "sysDescr_regex", "sysName", "sysName_regex"):
        if key in detection:
            legacy[key] = detection[key]
    return _compile_identity(legacy)


def _oid_prefix_matches(observed: Any, prefix: str) -> bool:
    actual = str(observed or "").strip().strip(".")
    expected = str(prefix or "").strip().strip(".")
    if not actual or not expected:
        return False
    actual_parts = actual.split(".")
    expected_parts = expected.split(".")
    if not all(part.isdigit() for part in actual_parts + expected_parts):
        return False
    return len(actual_parts) >= len(expected_parts) and actual_parts[:len(expected_parts)] == expected_parts


def _resolve_identity_oid(
    conn: Any,
    token: Any,
    *,
    mib_dir: Any = "",
    cache: dict[tuple[str, str], str] | None = None,
) -> str:
    raw = str(token or "").strip()
    preferred_dir = str(mib_dir or "").strip().replace("\\", "/").casefold()
    # Keep the token's exact spelling: quoted ASCII indexes are case-sensitive
    # even though the MIB directory preference is not.
    cache_key = (raw, preferred_dir)
    if cache is not None and cache_key in cache:
        return cache[cache_key]
    numeric = _numeric_oid(raw)
    if numeric:
        resolved_numeric = numeric.lstrip(".")
        if cache is not None:
            cache[cache_key] = resolved_numeric
        return resolved_numeric
    match = re.fullmatch(
        r"(?P<module>[A-Za-z][A-Za-z0-9_-]*)::(?P<symbol>[A-Za-z][A-Za-z0-9_-]*)(?P<suffix>(?:\.(?:\d+|\"[^\"\\]*\"|'[^'\\]*'))*)",
        raw,
    )
    if not match:
        if cache is not None:
            cache[cache_key] = ""
        return ""
    module = match.group("module").casefold()
    symbol = match.group("symbol")
    savepoint = "snmp_identity_oid_resolution"
    conn.execute(f"SAVEPOINT {savepoint}")
    try:
        rows = conn.execute(
            """
            SELECT n.oid, m.relative_path
              FROM snmp_mib_nodes n
              JOIN snmp_mibs m ON m.id = n.mib_id
             WHERE m.is_active = 1
               AND LOWER(m.name) = ?
               AND LOWER(n.node_name) = LOWER(?)
               AND TRIM(COALESCE(n.oid, '')) <> ''
             ORDER BY CASE WHEN ? <> '' AND LOWER(COALESCE(m.relative_path, '')) LIKE '%' || ? || '%' THEN 0 ELSE 1 END,
                      m.updated_at DESC
             LIMIT 8
            """,
            (module, symbol, preferred_dir, preferred_dir),
        ).fetchall()
    except Exception:
        try:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            # Let the enclosing optional identity lookup recover its savepoint.
            raise
        if cache is not None:
            cache[cache_key] = ""
        return ""
    else:
        conn.execute(f"RELEASE SAVEPOINT {savepoint}")
    if not rows:
        if cache is not None:
            cache[cache_key] = ""
        return ""
    base = _numeric_oid(rows[0][0]).lstrip(".")
    if not base:
        if cache is not None:
            cache[cache_key] = ""
        return ""

    suffix = match.group("suffix")
    indexes: list[int] = []
    cursor = 0
    while cursor < len(suffix):
        if suffix[cursor] != ".":
            if cache is not None:
                cache[cache_key] = ""
            return ""
        cursor += 1
        if cursor >= len(suffix):
            if cache is not None:
                cache[cache_key] = ""
            return ""
        if suffix[cursor] in {"'", '"'}:
            quote = suffix[cursor]
            end = cursor + 1
            chars: list[str] = []
            while end < len(suffix) and suffix[end] != quote:
                if suffix[end] == "\\" and end + 1 < len(suffix):
                    end += 1
                chars.append(suffix[end])
                end += 1
            if end >= len(suffix):
                if cache is not None:
                    cache[cache_key] = ""
                return ""
            try:
                encoded = "".join(chars).encode("ascii")
            except UnicodeEncodeError:
                if cache is not None:
                    cache[cache_key] = ""
                return ""
            indexes.extend((len(encoded), *encoded))
            cursor = end + 1
        else:
            end = cursor
            while end < len(suffix) and suffix[end].isdigit():
                end += 1
            if end == cursor:
                if cache is not None:
                    cache[cache_key] = ""
                return ""
            indexes.append(int(suffix[cursor:end]))
            cursor = end
    resolved = ".".join((base, *(str(index) for index in indexes)))
    if cache is not None:
        cache[cache_key] = resolved
    return resolved


def _runtime_identity_definition(
    conn: Any,
    definition: Mapping[str, Any],
    *,
    identity: Mapping[str, Any] | None = None,
    rule_vendor: Any = "",
    minimum_score: int = 0,
    require_pure_snmp_vendor: bool = False,
    cache: dict[tuple[str, str], str] | None = None,
) -> dict[str, Any]:
    resolved = dict(definition)
    clauses = definition.get("clauses") if isinstance(definition.get("clauses"), list) else []
    runtime_clauses: list[Any] = []
    known_vendor = normalize_asset_vendor((identity or {}).get("vendor")) if identity else ""
    normalized_rule_vendor = normalize_asset_vendor(rule_vendor)
    for clause in clauses:
        if not isinstance(clause, Mapping):
            runtime_clauses.append(clause)
            continue
        runtime_clause = dict(clause)
        predicates = clause.get("all") if isinstance(clause.get("all"), list) else []
        eligible_for_snmp = identity is None and clause.get("supported") is not False
        if identity is not None:
            eligible_for_snmp = bool(predicates) and clause.get("supported") is not False
            has_system_predicate = False
            for predicate in predicates:
                if not isinstance(predicate, Mapping):
                    eligible_for_snmp = False
                    break
                field = str(predicate.get("field") or "")
                if field in {"snmp_get", "snmp_walk"}:
                    continue
                has_system_predicate = True
                matched, _evidence, _score = _predicate_matches(predicate, identity)
                if not matched:
                    eligible_for_snmp = False
                    break
            if (
                eligible_for_snmp
                and not has_system_predicate
                and require_pure_snmp_vendor
                and not (known_vendor and normalized_rule_vendor == known_vendor)
            ):
                eligible_for_snmp = False
            if minimum_score > 1200:
                eligible_for_snmp = False

        runtime_predicates: list[Any] = []
        for predicate in predicates:
            if not isinstance(predicate, Mapping):
                runtime_predicates.append(predicate)
                continue
            if predicate.get("field") not in {"snmp_get", "snmp_walk"} or not eligible_for_snmp:
                # Preserve every original predicate when a clause is not
                # eligible. Keeping the clause prevents platform fallback from
                # treating a rule with unmet identity conditions as unconditional.
                runtime_predicates.append(dict(predicate))
                continue
            runtime_predicates.append({
                **dict(predicate),
                "resolved_oid": _resolve_identity_oid(
                    conn,
                    predicate.get("oid"),
                    mib_dir=predicate.get("mib_dir"),
                    cache=cache,
                ),
            })
        runtime_clause["all"] = runtime_predicates
        runtime_clauses.append(runtime_clause)
    resolved["clauses"] = runtime_clauses
    return resolved


def _identity_is_numeric(value: Any) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    if isinstance(value, (int, float)):
        return True
    return re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", str(value).strip()) is not None


def _identity_number_cast(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(int(value))
    raw = str(value).strip()
    try:
        return float(raw)
    except (TypeError, ValueError):
        prefix = re.match(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", raw)
        return float(prefix.group(0)) if prefix else 0.0


def _identity_truthy(value: Any) -> bool:
    if value is None or value is False or value == 0 or value == 0.0 or value == "" or value == "0":
        return False
    return True


def _identity_loose_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return _identity_truthy(left) == _identity_truthy(right)
    if left is None or right is None:
        if left is None and right is None:
            return True
        other = right if left is None else left
        return other is False or other == 0 or other == 0.0 or other == ""
    if _identity_is_numeric(left) and _identity_is_numeric(right):
        return _identity_number_cast(left) == _identity_number_cast(right)
    return str(left) == str(right)


def _compare_librenms_values(actual: Any, expected: Any, operator: str) -> bool:
    op = str(operator or "=").strip().casefold()
    expected_values = expected if isinstance(expected, (list, tuple)) else [expected]
    if op in {"contains", "starts", "ends", "not_contains", "not_starts", "not_ends"}:
        actual_text = "" if actual is None else str(actual)
        needles = [str(value) for value in expected_values if value is not None]
        if not needles:
            return False
        positive = op.removeprefix("not_")
        if positive == "contains":
            matched = any(needle in actual_text for needle in needles)
        elif positive == "starts":
            matched = any(actual_text.startswith(needle) for needle in needles)
        else:
            matched = any(actual_text.endswith(needle) for needle in needles)
        return not matched if op.startswith("not_") else matched
    if op in {"regex", "not_regex"}:
        if actual is None:
            return False
        matched = False
        for pattern_value in expected_values:
            pattern, flags, error = _regex_parts(pattern_value)
            if not error:
                try:
                    matched = re.search(pattern, str(actual), flags) is not None
                except re.error:
                    matched = False
            if matched:
                break
        return not matched if op == "not_regex" else matched
    if op in {"in_array", "not_in_array"}:
        if not isinstance(expected, (list, tuple)) or not expected:
            return False
        matched = any(_identity_loose_equal(actual, value) for value in expected)
        return not matched if op == "not_in_array" else matched
    if op == "exists":
        expected_value = expected_values[0] if len(expected_values) == 1 else expected
        expected_exists = expected_value is True or expected_value == 1 or str(expected_value).casefold() in {"true", "1"}
        return (actual is not None) == expected_exists
    if op not in {"=", "!=", "==", "!==", ">=", "<=", ">", "<"}:
        return False

    right = expected
    left = actual
    if _identity_is_numeric(left) or _identity_is_numeric(right):
        left = _identity_number_cast(left)
        if not isinstance(right, (list, tuple)):
            right = _identity_number_cast(right)
    if op == "=":
        return _identity_loose_equal(left, right)
    if op == "!=":
        return not _identity_loose_equal(left, right)
    if op == "==":
        return type(left) is type(right) and left == right
    if op == "!==":
        return not (type(left) is type(right) and left == right)
    try:
        return {">=": left >= right, "<=": left <= right, ">": left > right, "<": left < right}[op]
    except (TypeError, ValueError):
        return False


def _identity_value(identity: Mapping[str, Any], field: str) -> Any:
    aliases = {
        "sys_object_id": ("sys_object_id", "sysObjectID", "sysobjectid"),
        "sys_descr": ("sys_descr", "sysDescr", "sysdescr"),
        "sys_name": ("sys_name", "sysName", "sysname"),
        "sys_contact": ("sys_contact", "sysContact", "syscontact"),
        "sys_location": ("sys_location", "sysLocation", "syslocation"),
    }
    if field in {"snmp_get", "snmp_walk"}:
        return identity.get(field, {})
    return next((identity[key] for key in aliases.get(field, (field,)) if key in identity), "")


def _predicate_matches(
    predicate: Mapping[str, Any],
    identity: Mapping[str, Any],
) -> tuple[bool, dict[str, Any] | None, int]:
    field = str(predicate.get("field") or "")
    operator = str(predicate.get("op") or "")
    observed = _identity_value(identity, field)
    values = predicate.get("values") if isinstance(predicate.get("values"), list) else []
    found_value: Any = None
    matched = False
    score = 0
    if field in {"snmp_get", "snmp_walk"}:
        oid = str(predicate.get("resolved_oid") or "")
        if not oid or not isinstance(observed, Mapping) or oid not in observed:
            return False, None, 0
        actual_values = observed.get(oid)
        if field == "snmp_get":
            candidates = [actual_values]
        elif isinstance(actual_values, (list, tuple)):
            candidates = list(actual_values)
        else:
            candidates = []
        # An empty/failed walk provides no positive device identity evidence.
        if not candidates:
            return False, None, 0
        for actual in candidates:
            expected: Any = values
            if operator not in {
                "contains", "starts", "ends", "not_contains", "not_starts", "not_ends",
                "regex", "not_regex", "in_array", "not_in_array",
            } and len(values) == 1:
                expected = values[0]
            if _compare_librenms_values(actual, expected, operator):
                matched = True
                found_value = values
                break
        if bool(predicate.get("negated")):
            matched = not matched
        if matched:
            score = 1200
            evidence = {
                "field": predicate.get("source_field") or field,
                "operator": operator,
                "oid": oid,
                "value": found_value,
                "negated": bool(predicate.get("negated")),
            }
            return True, evidence, score
        return False, None, 0
    for expected in values:
        if operator == "oid_prefix":
            candidate_match = _oid_prefix_matches(observed, str(expected))
            candidate_score = 1000 + len(str(expected).split("."))
        elif operator == "contains":
            candidate_match = bool(str(expected)) and str(expected).casefold() in str(observed or "").casefold()
            candidate_score = 600
        elif operator == "regex":
            pattern, flags, error = _regex_parts(expected)
            if error:
                candidate_match = False
            else:
                try:
                    candidate_match = re.search(pattern, str(observed or ""), flags) is not None
                except re.error:
                    candidate_match = False
            candidate_score = 800 if field == "sys_object_id" else 700
        else:
            candidate_match = False
            candidate_score = 0
        if candidate_match:
            matched = True
            found_value = expected
            score = max(score, candidate_score)
            break
    if bool(predicate.get("negated")):
        matched = not matched
        if matched:
            found_value = values[0] if values else None
            score = max(score, 500)
    evidence = None
    if matched:
        evidence = {
            "field": predicate.get("source_field") or field,
            "operator": operator,
            "value": found_value,
            "negated": bool(predicate.get("negated")),
        }
    return matched, evidence, score


def match_identity(identity_match: Mapping[str, Any], identity: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a compiled identity contract without dropping unsupported conditions.

    Returns matched_by evidence and rule diagnostics for callers that need to show
    why a rule was or was not eligible.
    """
    definition = dict(identity_match)
    if definition.get("contract") != IDENTITY_CONTRACT:
        definition = _legacy_identity_definition(definition)
    clauses = definition.get("clauses") if isinstance(definition.get("clauses"), list) else []
    diagnostics = list(definition.get("diagnostics") or [])
    best: tuple[int, int, list[dict[str, Any]]] | None = None
    for clause_index, clause in enumerate(clauses):
        if not isinstance(clause, Mapping) or clause.get("supported") is False:
            continue
        predicates = clause.get("all") if isinstance(clause.get("all"), list) else []
        evidence: list[dict[str, Any]] = []
        scores: list[int] = []
        clause_matched = True
        for predicate in predicates:
            if not isinstance(predicate, Mapping):
                clause_matched = False
                break
            predicate_matched, item, score = _predicate_matches(predicate, identity)
            if not predicate_matched:
                clause_matched = False
                break
            if item:
                evidence.append(item)
            scores.append(score)
        if clause_matched and predicates:
            clause_score = max(scores or [0])
            if best is None or clause_score > best[0]:
                best = (clause_score, clause_index, evidence)
    return {
        "contract": IDENTITY_CONTRACT,
        "matched": best is not None,
        "matched_by": best[2] if best else [],
        "score": best[0] if best else 0,
        "matched_clause": best[1] if best else None,
        "compatibility": str(definition.get("compatibility") or "partial"),
        "diagnostics": diagnostics,
    }


def identity_snmp_probe_plan(
    conn: Any,
    identity: Mapping[str, Any],
    *,
    minimum_score: int = 0,
) -> list[dict[str, str]]:
    """Return bounded GET/WALK OIDs for clauses still plausible from sys data.

    A clause is probed only after all of its system identity predicates match.
    Pure SNMP clauses additionally require a known catalog vendor so a device
    without identity evidence cannot trigger a broad sweep of OS probes.
    """
    try:
        rows = conn.execute(
            "SELECT vendor, detection_json FROM snmp_librenms_rules "
            "WHERE rule_status IN ('active','identity_only') ORDER BY vendor, os_key"
        ).fetchall()
    except Exception:
        return []
    known_vendor = normalize_asset_vendor(identity.get("vendor"))
    conflict = str(identity.get("status") or "").casefold() == "conflict"
    needed: set[tuple[str, str]] = set()
    mib_cache: dict[tuple[str, str], str] = {}
    for row in rows:
        item = dict(row)
        rule_vendor = normalize_asset_vendor(item.get("vendor"))
        if known_vendor and not conflict and rule_vendor and rule_vendor != known_vendor:
            continue
        try:
            detection = json.loads(item.get("detection_json") or "{}")
        except (TypeError, ValueError):
            continue
        if not isinstance(detection, Mapping):
            continue
        definition = detection.get("identity_match")
        if not isinstance(definition, Mapping):
            definition = _legacy_identity_definition(detection)
        runtime_definition = _runtime_identity_definition(
            conn,
            definition,
            identity=identity,
            rule_vendor=rule_vendor,
            minimum_score=minimum_score,
            require_pure_snmp_vendor=True,
            cache=mib_cache,
        )
        clauses = runtime_definition.get("clauses") if isinstance(runtime_definition.get("clauses"), list) else []
        for clause in clauses:
            if not isinstance(clause, Mapping) or clause.get("supported") is False:
                continue
            predicates = clause.get("all") if isinstance(clause.get("all"), list) else []
            required: list[tuple[str, str]] = []
            system_scores: list[int] = []
            possible = bool(predicates)
            has_system_predicate = False
            for predicate in predicates:
                if not isinstance(predicate, Mapping):
                    possible = False
                    break
                field = str(predicate.get("field") or "")
                if field in {"snmp_get", "snmp_walk"}:
                    oid = str(predicate.get("resolved_oid") or "")
                    if not oid:
                        possible = False
                        break
                    required.append((field, oid))
                    continue
                has_system_predicate = True
                predicate_matched, _evidence, score = _predicate_matches(predicate, identity)
                if not predicate_matched:
                    possible = False
                    break
                system_scores.append(score)
            if not possible or not required:
                continue
            if not has_system_predicate and not (known_vendor and rule_vendor == known_vendor):
                continue
            # SNMP identity clauses rank above any individual sysDescr/OID
            # predicate (their runtime score is 1200). Keep probes bounded when
            # an already stronger match cannot be displaced.
            if minimum_score > 1200:
                continue
            needed.update(required)
    return [
        {"field": field, "oid": oid}
        for field, oid in sorted(needed)
    ]


def resolve_rule(conn: Any, identity: Mapping[str, Any]) -> dict[str, Any] | None:
    """Pick the best persisted LibreNMS rule and return its match evidence."""
    vendor = str(identity.get("vendor") or "").casefold()
    platform = str(identity.get("platform") or "").casefold()
    rows = conn.execute(
        "SELECT * FROM snmp_librenms_rules WHERE rule_status IN ('active','identity_only') ORDER BY vendor, os_key"
    ).fetchall()
    matches: list[tuple[int, dict[str, Any]]] = []
    mib_cache: dict[tuple[str, str], str] = {}
    for row in rows:
        item = dict(row)
        if vendor and item.get("vendor") and str(item["vendor"]).casefold() != vendor:
            continue
        try:
            detection = json.loads(item.get("detection_json") or "{}")
            candidates = json.loads(item.get("oid_candidates_json") or "[]")
        except (TypeError, ValueError):
            detection, candidates = {}, []
        if not isinstance(detection, Mapping):
            detection = {}
        if not isinstance(candidates, list):
            candidates = []
        identity_definition = detection.get("identity_match")
        if not isinstance(identity_definition, Mapping):
            identity_definition = _legacy_identity_definition(detection)
        identity_definition = _runtime_identity_definition(
            conn,
            identity_definition,
            identity=identity,
            rule_vendor=item.get("vendor"),
            cache=mib_cache,
        )
        match = match_identity(identity_definition, identity)
        # Keep the old explicit platform fallback only for records that have no
        # identity predicates at all; it must not bypass an upstream condition.
        clauses = identity_definition.get("clauses") if isinstance(identity_definition, Mapping) else []
        if not match["matched"] and not clauses and platform:
            rule_platform = str(item.get("platform") or "").casefold()
            if rule_platform and (rule_platform == platform or rule_platform in platform):
                match.update({
                    "matched": True,
                    "matched_by": [{
                        "field": "platform",
                        "operator": "declared_platform",
                        "value": item.get("platform"),
                        "negated": False,
                    }],
                    "score": 100,
                })
        if not match["matched"]:
            continue

        hardware = detection.get("hardware_definitions")
        if not isinstance(hardware, Mapping):
            hardware = {
                "contract": HARDWARE_CONTRACT,
                "processors": [],
                "mempools": [],
                "sensors": [],
                "compatibility": _compatibility("partial", [
                    _diagnostic(
                        "legacy_rule_without_structured_hardware",
                        str(item.get("source_path") or ""),
                        "This persisted rule predates structured hardware definitions; re-import is required.",
                    ),
                ]),
            }
        compatibility = detection.get("compatibility")
        if not isinstance(compatibility, Mapping):
            compatibility = {
                "version": str(detection.get("rule_contract_version") or "legacy"),
                "level": "partial",
                "identity_level": str(match.get("compatibility") or "partial"),
                "hardware_level": str((hardware.get("compatibility") or {}).get("level") or "partial"),
                "diagnostics": [*match.get("diagnostics", []), *((hardware.get("compatibility") or {}).get("diagnostics", []))],
            }
        item["detection"] = dict(detection)
        item["identity_match"] = {**dict(identity_definition), **match}
        item["hardware_definitions"] = dict(hardware)
        item["rule_contract_version"] = str(
            detection.get("rule_contract_version") or "legacy"
        )
        item["compatibility"] = dict(compatibility)
        item["oid_candidates"] = candidates
        matches.append((int(match["score"]), item))

    if not matches:
        return None
    matches.sort(key=lambda pair: (-pair[0], str(pair[1].get("os_key") or "")))
    best_score, best_item = matches[0]
    best_item["identity_match"]["conflicts"] = [
        {
            "rule_id": other.get("id"),
            "os_key": other.get("os_key"),
            "vendor": other.get("vendor"),
            "score": score,
        }
        for score, other in matches[1:]
        if score == best_score and other.get("id") != best_item.get("id")
    ]
    return best_item


def ensure_rules_available() -> dict[str, Any]:
    """Index the project-bundled LibreNMS source once, without network access."""
    global _AUTO_SYNC_DONE, _AUTO_SYNC_KEY
    from services.librenms_mib_service import PARSER_VERSION, import_mibs_from_directory

    root = source_root()
    current_source_commit = source_commit(root)
    sync_key = (current_source_commit, PARSER_VERSION, RULE_CONTRACT_VERSION)

    if _AUTO_SYNC_DONE and _AUTO_SYNC_KEY == sync_key:
        return {"status": "cached"}
    with _AUTO_SYNC_LOCK:
        root = source_root()
        current_source_commit = source_commit(root)
        sync_key = (current_source_commit, PARSER_VERSION, RULE_CONTRACT_VERSION)
        if _AUTO_SYNC_DONE and _AUTO_SYNC_KEY == sync_key:
            return {"status": "cached"}
        detection_dir = root / "resources" / "definitions" / "os_detection"
        discovery_dir = root / "resources" / "definitions" / "os_discovery"
        mibs_dir = root / "mibs"
        if not detection_dir.is_dir() or not discovery_dir.is_dir() or not mibs_dir.is_dir():
            _AUTO_SYNC_DONE = False
            _AUTO_SYNC_KEY = None
            logger.error("Project-local LibreNMS source bundle is incomplete at %s", root)
            return {"status": "local_bundle_missing", "source_root": str(root)}
        result = sync_rules_from_repository(root)
        mib_result: dict[str, Any] = {}
        try:
            # Private symbolic OIDs in LibreNMS sensor definitions (notably
            # skip conditions and descriptions) must resolve from the same
            # pinned local snapshot before the first hardware collection.
            mib_result = import_mibs_from_directory(
                mibs_dir=mibs_dir,
                target_vendors=[*ASSET_NETWORK_VENDORS, "Standard"],
                retire_missing_files=False,
                retire_out_of_scope=False,
                rules_source_commit=str(result.get("source_commit") or current_source_commit),
                rules_contract_version=RULE_CONTRACT_VERSION,
            )
        except Exception as exc:
            logger.warning("Bundled LibreNMS MIB indexing unavailable: %s", type(exc).__name__)
            _AUTO_SYNC_DONE = False
            _AUTO_SYNC_KEY = None
            return {"status": "synced_local", **result, "mib_import": mib_result, "retryable": True}
        if not mib_result.get("success"):
            _AUTO_SYNC_DONE = False
            _AUTO_SYNC_KEY = None
            return {"status": "synced_local", **result, "mib_import": mib_result, "retryable": True}
        _AUTO_SYNC_DONE = True
        _AUTO_SYNC_KEY = sync_key
        return {"status": "synced_local", **result, "mib_import": mib_result}
