"""Collect current Cisco IOS HSRP/VRRP and H3C Comware VRRP without history writes."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from core.platform_utils import normalize_device_platform
from services import ip_locator_service, vault_service
from services.ipam_current_fhrp_observation_service import (
    begin_current_fhrp_collection,
    finish_current_fhrp_collection,
)
from services.ipam_fhrp_parser import parse_fhrp_output
from services.network_access_limiter import limited_connect_handler


logger = logging.getLogger(__name__)

_CISCO_PROTOCOL_COMMANDS = {
    "hsrp": "show standby brief",
    "vrrp": "show vrrp brief",
}
_H3C_PROTOCOL_COMMANDS = {
    "vrrp": ("display vrrp verbose", "display vrrp ipv6 verbose"),
}
_CISCO_IOS_PLATFORMS = frozenset({
    "cisco_ios", "cisco_iosxe", "cisco_xe", "ios", "iosxe",
})
_PLATFORM_PROTOCOL_COMMANDS = {
    **{platform: {protocol: (command,) for protocol, command in _CISCO_PROTOCOL_COMMANDS.items()}
       for platform in _CISCO_IOS_PLATFORMS},
    "h3c_comware": _H3C_PROTOCOL_COMMANDS,
}
_DEVICE_SELECT = """
    SELECT id, hostname, ip_address, status, vendor, platform,
           management_port, username, password,
           normal_username, normal_password, admin_username, admin_password,
           enable_password, credential_source, credential_id,
           admin_credential_id, vault_path, ssh_algorithm_profile, asset_id
      FROM devices
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_devices(device_ids: set[str] | None) -> list[dict[str, Any]]:
    conn = get_db_connection()
    try:
        sql = _DEVICE_SELECT
        params: tuple[str, ...] = ()
        if device_ids is not None:
            if not device_ids:
                return []
            placeholders = ", ".join("?" for _ in device_ids)
            sql += f" WHERE id IN ({placeholders})"
            params = tuple(sorted(device_ids))
        sql += " ORDER BY hostname, id"
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _reserve_generations(
    *, device_id: str, protocols: tuple[str, ...], attempted_at: str, run_id: str,
) -> dict[str, int]:
    conn = get_db_connection()
    try:
        generations = {
            protocol: begin_current_fhrp_collection(
                conn,
                device_id=device_id,
                protocol=protocol,
                attempted_at=attempted_at,
                run_id=run_id,
            )
            for protocol in protocols
        }
        # Persist the fences before any CLI command is sent.
        conn.commit()
        return generations
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _finish(
    *, device_id: str, protocol: str, generation: int, status: str,
    attempted_at: str, completed_at: str, run_id: str,
    observations: list[dict[str, Any]] | None = None, error_code: str = "",
) -> int:
    conn = get_db_connection()
    try:
        count = finish_current_fhrp_collection(
            conn,
            device_id=device_id,
            protocol=protocol,
            generation=generation,
            status=status,
            attempted_at=attempted_at,
            completed_at=completed_at,
            observations=observations,
            run_id=run_id,
            error_code=error_code,
        )
        conn.commit()
        return count
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _classify_collection_error(exc: Exception) -> tuple[str, str]:
    message = str(exc).casefold()
    kind = type(exc).__name__.casefold()
    details = f"{kind} {message}"
    if any(marker in f"{kind} {message}" for marker in (
        "nosuchcommand", "invalid input", "unknown command", "unsupported command",
        "not supported", "unrecognized command",
    )):
        return "unsupported", "cli_command_unsupported"
    if any(marker in details for marker in (
        "error reading ssh protocol banner", "ssh protocol banner", "connection reset by peer",
    )):
        return "failed", "ssh_banner_unavailable"
    if any(marker in details for marker in (
        "no matching key exchange", "no matching cipher", "no matching host key",
        "algorithm negotiation failed",
    )):
        return "failed", "ssh_algorithm_mismatch"
    if any(marker in message for marker in ("timeout", "incomplete", "truncated", "malformed")):
        return "partial", "cli_output_incomplete"
    return "failed", "cli_collection_failed"


def _supported_protocols(platform: str) -> tuple[str, ...]:
    # Ask the parser's allowlist. Unknown platform keys never reach a Cisco or
    # H3C command family through Netmiko's historical fallback.
    command_map = _PLATFORM_PROTOCOL_COMMANDS.get(platform, {})
    return tuple(
        protocol for protocol, commands in command_map.items()
        if commands and all(
            parse_fhrp_output(command, "", platform=platform)["status"] != "unsupported"
            for command in commands
        )
    )


def _prepare_ssh_device(
    device: dict[str, Any], ssh_credentials: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = dict(device)
    target["_ssh_username"] = str(ssh_credentials.get("username") or "")
    target["_ssh_password"] = str(ssh_credentials.get("password") or "")
    target["_ssh_enable"] = str(ssh_credentials.get("enable_password") or "")
    target["management_port"] = int(
        ssh_credentials.get("port") or target.get("management_port") or 22
    )
    return target, ip_locator_service._build_ssh_params(target)


def _collect_protocol_outputs(
    device: dict[str, Any], ssh_credentials: dict[str, Any], protocols: tuple[str, ...],
) -> dict[str, tuple[str | list[tuple[str, str]], str]]:
    """Return command/output or a sanitized error class for each protocol."""
    from netmiko import ConnectHandler

    raw_platform = str(device.get("platform") or "").strip().casefold().replace("-", "_").replace(" ", "_")
    platform = normalize_device_platform(str(device.get("vendor") or ""), raw_platform)
    command_map = _PLATFORM_PROTOCOL_COMMANDS.get(platform, {})
    if not command_map:
        return {protocol: ("", "platform_unsupported") for protocol in protocols}

    target, params = _prepare_ssh_device(device, ssh_credentials)
    output: dict[str, tuple[str | list[tuple[str, str]], str]] = {}
    with limited_connect_handler(target, ConnectHandler, **params) as client:
        if params.get("secret"):
            try:
                client.enable()
            except Exception:
                # Read-only show commands may remain available at the login level.
                pass
        for protocol in protocols:
            commands = command_map.get(protocol, ())
            command_outputs: list[tuple[str, str]] = []
            error_code = ""
            for command in commands:
                try:
                    text = client.send_command(
                        command,
                        cmd_verify=False,
                        strip_prompt=True,
                        strip_command=True,
                        read_timeout=30,
                    )
                    command_outputs.append((command, str(text or "")))
                except Exception as exc:  # noqa: BLE001
                    _status, error_code = _classify_collection_error(exc)
                    break
            if error_code:
                output[protocol] = ("", error_code)
            elif len(command_outputs) == 1:
                output[protocol] = (command_outputs[0][1], "")
            else:
                output[protocol] = (command_outputs, "")
    return output


def _collect_device(
    device: dict[str, Any], *, run_id: str,
) -> dict[str, Any]:
    device_id = str(device.get("id") or "").strip()
    raw_platform = str(device.get("platform") or "").strip().casefold().replace("-", "_").replace(" ", "_")
    platform = normalize_device_platform(
        str(device.get("vendor") or ""), raw_platform,
    )
    if platform not in _PLATFORM_PROTOCOL_COMMANDS:
        platform = ""
    protocols = _supported_protocols(platform)
    # A non-supported vendor/platform is never sent a Cisco command.
    if not protocols:
        protocols = tuple(_CISCO_PROTOCOL_COMMANDS)
        attempted_at = _utc_now()
        generations = _reserve_generations(
            device_id=device_id, protocols=protocols, attempted_at=attempted_at, run_id=run_id,
        )
        counts = {
            protocol: _finish(
                device_id=device_id, protocol=protocol, generation=generations[protocol],
                status="unsupported", attempted_at=attempted_at, completed_at=_utc_now(),
                run_id=run_id, error_code="platform_unsupported",
            )
            for protocol in protocols
        }
        return {
            "device_id": device_id,
            "status": "unsupported",
            "protocols_attempted": len(protocols),
            "observations": sum(counts.values()),
        }

    attempted_at = _utc_now()
    generations = _reserve_generations(
        device_id=device_id, protocols=protocols, attempted_at=attempted_at, run_id=run_id,
    )
    try:
        credentials = vault_service.resolve_collector_credentials(device).get("ssh") or {}
    except Exception as exc:  # noqa: BLE001
        credentials = {}
        credential_error = type(exc).__name__
    else:
        credential_error = ""

    if credential_error or not credentials.get("username") or not credentials.get("password"):
        error_code = "credential_resolution_failed" if credential_error else "ssh_not_configured"
        counts = {
            protocol: _finish(
                device_id=device_id, protocol=protocol, generation=generations[protocol],
                status="failed", attempted_at=attempted_at, completed_at=_utc_now(),
                run_id=run_id, error_code=error_code,
            )
            for protocol in protocols
        }
        return {
            "device_id": device_id,
            "status": "failed",
            "protocols_attempted": len(protocols),
            "observations": sum(counts.values()),
            "error_code": error_code,
        }

    try:
        outputs = _collect_protocol_outputs(device, credentials, protocols)
    except Exception as exc:  # noqa: BLE001
        status, error_code = _classify_collection_error(exc)
        logger.info(
            "Current FHRP collection failed for device %s (%s)",
            device_id,
            type(exc).__name__,
        )
        counts = {
            protocol: _finish(
                device_id=device_id, protocol=protocol, generation=generations[protocol],
                status=status, attempted_at=attempted_at, completed_at=_utc_now(),
                run_id=run_id, error_code=error_code,
            )
            for protocol in protocols
        }
        return {
            "device_id": device_id,
            "status": status,
            "protocols_attempted": len(protocols),
            "observations": sum(counts.values()),
            "error_code": error_code,
        }

    protocol_results: list[dict[str, Any]] = []
    command_map = _PLATFORM_PROTOCOL_COMMANDS[platform]
    for protocol in protocols:
        payload, error_code = outputs.get(protocol, ("", "cli_collection_failed"))
        if error_code:
            error_status = "unsupported" if error_code == "cli_command_unsupported" else (
                "partial" if error_code == "cli_output_incomplete" else (
                    "unsupported" if error_code == "platform_unsupported" else "failed"
                )
            )
            count = _finish(
                device_id=device_id, protocol=protocol, generation=generations[protocol],
                status=error_status, attempted_at=attempted_at, completed_at=_utc_now(),
                run_id=run_id, error_code=error_code,
            )
            protocol_results.append({"protocol": protocol, "status": error_status, "count": count})
            continue

        if isinstance(payload, str):
            command_outputs = [(command_map[protocol][0], payload)]
        else:
            command_outputs = list(payload)
        observations: list[dict[str, Any]] = []
        parser_status = "complete"
        parser_error_code = ""
        if len(command_outputs) != len(command_map[protocol]):
            parser_status = "partial"
            parser_error_code = "cli_output_incomplete"
        else:
            for command, text in command_outputs:
                parsed = parse_fhrp_output(command, text, platform=platform)
                if parsed["status"] != "complete":
                    parser_status = parsed["status"]
                    parser_error_code = (
                        "cli_command_unsupported"
                        if parser_status == "unsupported"
                        else "cli_output_incomplete"
                    )
                    break
                observations.extend(parsed["observations"])

        if parser_status == "complete":
            count = _finish(
                device_id=device_id, protocol=protocol, generation=generations[protocol],
                status="complete", attempted_at=attempted_at, completed_at=_utc_now(),
                run_id=run_id, observations=observations,
            )
            protocol_results.append({"protocol": protocol, "status": "complete", "count": count})
        else:
            status = "partial" if parser_status == "partial" else "unsupported"
            count = _finish(
                device_id=device_id, protocol=protocol, generation=generations[protocol],
                status=status, attempted_at=attempted_at, completed_at=_utc_now(),
                run_id=run_id, error_code=parser_error_code,
            )
            protocol_results.append({"protocol": protocol, "status": status, "count": count})

    failures = [item for item in protocol_results if item["status"] != "complete"]
    return {
        "device_id": device_id,
        "status": "partial" if failures else "complete",
        "protocol_results": protocol_results,
        "protocols_attempted": len(protocols),
        "observations": sum(int(item["count"] or 0) for item in protocol_results),
    }


def run_current_fhrp_collection(
    *, device_ids: set[str] | list[str] | tuple[str, ...] | None = None,
    collection_run_id: str = "",
) -> dict[str, Any]:
    """Refresh current FHRP snapshots for explicitly supported device platforms.

    No device facts are projected into discovery-history tables. Unsupported
    platforms are marked per protocol without attempting an incompatible CLI
    command family. H3C IPv4 and IPv6 VRRP must both parse completely before a
    single current VRRP snapshot is replaced.
    """
    normalized_ids = None if device_ids is None else {
        str(device_id).strip() for device_id in device_ids if str(device_id).strip()
    }
    devices = _load_devices(normalized_ids)
    run_id = str(collection_run_id or uuid.uuid4())
    results: list[dict[str, Any]] = []
    for device in devices:
        if str(device.get("status") or "").strip().casefold() != "online":
            results.append({"device_id": str(device.get("id") or ""), "status": "skipped", "error_code": "device_offline"})
            continue
        results.append(_collect_device(device, run_id=run_id))

    if not devices:
        coverage_status = "not_collected"
        status = "skipped"
    elif any(item.get("status") not in {"complete", "unsupported", "skipped"} for item in results):
        coverage_status = "partial"
        status = "partial"
    elif all(item.get("status") in {"unsupported", "skipped"} for item in results):
        coverage_status = "not_collected"
        status = "skipped"
    elif any(item.get("status") in {"unsupported", "skipped"} for item in results):
        coverage_status = "partial"
        status = "partial"
    else:
        coverage_status = "complete"
        status = "success"
    return {
        "collection_run_id": run_id,
        "status": status,
        "coverage_status": coverage_status,
        "devices_seen": len(devices),
        "devices_collected": sum(1 for item in results if item.get("status") == "complete"),
        "devices_skipped": sum(1 for item in results if item.get("status") == "skipped"),
        "device_results": results,
    }
