"""Production-grade internet outbound health probes.

The service deliberately keeps the probing policy out of the API layer. It
supports target-level results, grouped status, hysteresis, SSRF protection and
independent egress-IP checks while remaining usable in offline unit tests.
"""

from __future__ import annotations

import concurrent.futures
import http.client
import ipaddress
import json
import logging
import os
import re
import socket
import ssl
import struct
import time
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from core.config import settings
from database import get_db_connection

logger = logging.getLogger(__name__)

STATUS_HEALTHY = "healthy"
STATUS_DEGRADED = "degraded"
STATUS_UNAVAILABLE = "unavailable"
STATUS_UNKNOWN = "unknown"

PROBE_TYPES = {"TCP_CONNECT", "HTTP_GET", "HTTPS_GET", "DNS_RESOLVE", "ICMP_PING"}
GROUPS = {"domestic", "international", "dns", "web", "business"}
ERROR_TYPES = {
    "DNS_FAILED",
    "CONNECT_TIMEOUT",
    "CONNECTION_REFUSED",
    "NETWORK_UNREACHABLE",
    "TLS_FAILED",
    "HTTP_STATUS_ERROR",
    "SSRF_BLOCKED",
    "UNKNOWN",
}
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9._:-]{1,253}$")
_MAX_BODY_BYTES = 64 * 1024
# Storage keeps 30 days, but one API/chart query is intentionally limited to
# seven days to keep response size and rendering latency predictable.
OUTBOUND_MAX_HISTORY_HOURS = 7 * 24
OUTBOUND_MAX_HISTORY_POINTS = 1500


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _bounded_history_hours(history_hours: int) -> int:
    return max(1, min(int(history_hours or 24), OUTBOUND_MAX_HISTORY_HOURS))


def _downsample_history(items: list[dict], max_points: int = OUTBOUND_MAX_HISTORY_POINTS) -> list[dict]:
    """Keep chart payloads bounded while preserving the first and last sample."""
    if len(items) <= max_points:
        return items
    if max_points < 2:
        return items[-1:]
    step = (len(items) - 1) / (max_points - 1)
    indexes = [round(index * step) for index in range(max_points)]
    return [items[index] for index in indexes]


def _allow_private_targets() -> bool:
    return os.environ.get("OUTBOUND_PROBE_ALLOW_PRIVATE_NETWORKS", "false").lower() in {"1", "true", "yes"}


def _allowed_private_networks() -> list[ipaddress._BaseNetwork]:
    raw = os.environ.get("OUTBOUND_PROBE_ALLOWED_CIDRS", "")
    networks = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid OUTBOUND_PROBE_ALLOWED_CIDRS entry")
    return networks


def _is_allowed_ip(address: str) -> bool:
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return False
    if parsed.is_loopback or parsed.is_link_local or parsed.is_multicast or parsed.is_unspecified or parsed.is_reserved:
        return False
    if parsed.is_private:
        if not _allow_private_targets():
            return False
        return any(parsed in network for network in _allowed_private_networks())
    return True


def _validate_host_syntax(host: str) -> str:
    value = (host or "").strip().rstrip(".")
    if not value or len(value) > 253 or not _HOSTNAME_RE.fullmatch(value):
        raise ValueError("Invalid target host")
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if value.lower() in {"localhost", "localhost.localdomain"}:
            raise ValueError("Target host is not allowed")
    return value


def _resolve_and_validate(host: str, port: int) -> list[str]:
    """Resolve all addresses and reject private/link-local destinations.

    Validation is repeated immediately before connecting to reduce DNS
    rebinding risk. The resulting addresses are used for the connection so a
    second resolver lookup cannot silently change the destination.
    """
    host = _validate_host_syntax(host)
    try:
        literal = ipaddress.ip_address(host)
        addresses = [str(literal)]
    except ValueError:
        try:
            infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            addresses = list(dict.fromkeys(str(item[4][0]) for item in infos if item[4]))
        except socket.gaierror as exc:
            raise OSError("DNS_FAILED") from exc
    if not addresses:
        raise OSError("DNS_FAILED")
    blocked = [address for address in addresses if not _is_allowed_ip(address)]
    if blocked:
        raise PermissionError("SSRF_BLOCKED")
    return addresses


def normalize_target_payload(payload: dict, *, target_id: str | None = None) -> dict:
    """Validate and normalize a target without performing network I/O."""
    name = str(payload.get("target_name") or payload.get("name") or "").strip()
    host = str(payload.get("host") or "").strip()
    probe_type = str(payload.get("probe_type") or "TCP_CONNECT").strip().upper()
    group_name = str(payload.get("group_name") or payload.get("group") or "business").strip().lower()
    url = str(payload.get("url") or "").strip()
    if not name or len(name) > 100:
        raise ValueError("Target name must be 1-100 characters")
    if probe_type not in PROBE_TYPES:
        raise ValueError(f"Unsupported probe type: {probe_type}")
    if group_name not in GROUPS:
        raise ValueError(f"Unsupported target group: {group_name}")
    if probe_type in {"HTTP_GET", "HTTPS_GET"}:
        if not url:
            scheme = "https" if probe_type == "HTTPS_GET" else "http"
            url = f"{scheme}://{host}"
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("HTTP probes require a valid http(s) URL")
        if probe_type == "HTTPS_GET" and parsed.scheme.lower() != "https":
            raise ValueError("HTTPS_GET requires an https URL")
        if probe_type == "HTTP_GET" and parsed.scheme.lower() != "http":
            raise ValueError("HTTP_GET requires an http URL")
        host = parsed.hostname
        if parsed.port:
            port = parsed.port
        else:
            port = 443 if parsed.scheme.lower() == "https" else 80
    else:
        _validate_host_syntax(host)
        try:
            port = int(payload.get("port", 53 if probe_type == "DNS_RESOLVE" else 443))
        except (TypeError, ValueError) as exc:
            raise ValueError("Port must be an integer") from exc
    try:
        configured_ip = ipaddress.ip_address(host)
        if not _is_allowed_ip(str(configured_ip)):
            raise ValueError("Target address is not allowed")
    except ValueError as exc:
        # Preserve the explicit policy error for IP literals while allowing
        # ordinary DNS names to be validated again immediately before connect.
        if str(exc) == "Target address is not allowed":
            raise
    if probe_type == "ICMP_PING":
        port = int(payload.get("port") or 0)
        if not 0 <= port <= 65535:
            raise ValueError("Port must be between 0 and 65535")
    elif not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    try:
        timeout_ms = int(payload.get("timeout_ms", 2000))
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout_ms must be an integer") from exc
    if not 100 <= timeout_ms <= 10000:
        raise ValueError("timeout_ms must be between 100 and 10000")
    expected_status = payload.get("expected_status_code", 200)
    try:
        expected_status = int(expected_status) if expected_status is not None else 200
    except (TypeError, ValueError) as exc:
        raise ValueError("expected_status_code must be an integer") from exc
    if not 100 <= expected_status <= 599:
        raise ValueError("expected_status_code must be between 100 and 599")
    keyword = str(payload.get("expected_keyword") or "")[:128]
    return {
        "id": target_id or payload.get("id") or str(uuid.uuid4()),
        "target_name": name,
        "host": host,
        "port": port,
        "probe_type": probe_type,
        "group_name": group_name,
        "url": url,
        "expected_status_code": expected_status,
        "expected_keyword": keyword,
        "timeout_ms": timeout_ms,
        "enabled": 1 if bool(payload.get("enabled", payload.get("is_active", 1))) else 0,
        "updated_at": utc_now_iso(),
    }


def _classify_error(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, PermissionError) and str(exc) == "SSRF_BLOCKED":
        return "SSRF_BLOCKED", "Target address is not allowed"
    if isinstance(exc, OSError) and str(exc) == "DNS_FAILED":
        return "DNS_FAILED", "Target name could not be resolved"
    if isinstance(exc, socket.timeout) or isinstance(exc, TimeoutError):
        return "CONNECT_TIMEOUT", "Connection timed out"
    if isinstance(exc, ConnectionRefusedError):
        return "CONNECTION_REFUSED", "Connection refused"
    if isinstance(exc, OSError):
        message = str(exc).lower()
        if any(token in message for token in ("network is unreachable", "no route", "host is down")):
            return "NETWORK_UNREACHABLE", "Network is unreachable"
    if isinstance(exc, ssl.SSLError):
        return "TLS_FAILED", "TLS handshake failed"
    return "UNKNOWN", "Probe failed"


def _base_result(target: dict) -> dict:
    return {
        "target_id": target["id"],
        "target_name": target["target_name"],
        "group": target.get("group_name") or "business",
        "probe_type": target.get("probe_type") or "TCP_CONNECT",
        "success": False,
        "latency_ms": None,
        "error_type": None,
        "error_message": None,
        "resolved_ip": None,
        "http_status": None,
        "dns_answers": [],
    }


def _probe_icmp(target: dict) -> dict:
    import subprocess
    import platform
    result = _base_result(target)
    started = time.perf_counter()
    host = target["host"]
    timeout_ms = int(target.get("timeout_ms", 2000))
    try:
        # Check SSRF/Allowed destination first (resolve IP)
        addresses = _resolve_and_validate(host, 80)
        ip_addr = addresses[0]
        
        system = platform.system().lower()
        if system == "windows":
            cmd = ["ping", "-n", "1", "-w", str(timeout_ms), ip_addr]
        else:
            timeout_sec = max(1, int(timeout_ms / 1000))
            cmd = ["ping", "-c", "1", "-W", str(timeout_sec), ip_addr]
            
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout_ms / 1000 + 1)
        if proc.returncode == 0:
            result.update(success=True, latency_ms=round((time.perf_counter() - started) * 1000, 2), resolved_ip=ip_addr)
        else:
            result["error_type"] = "PING_FAILED"
            result["error_message"] = proc.stderr.strip() or proc.stdout.strip() or f"Ping failed with exit code {proc.returncode}"
    except BaseException as exc:
        result["error_type"], result["error_message"] = _classify_error(exc)
    return result


def _probe_tcp(target: dict) -> dict:
    result = _base_result(target)
    started = time.perf_counter()
    try:
        addresses = _resolve_and_validate(target["host"], int(target["port"]))
        last_error: BaseException | None = None
        for address in addresses:
            try:
                with socket.create_connection((address, int(target["port"])), timeout=int(target["timeout_ms"]) / 1000):
                    result.update(success=True, latency_ms=round((time.perf_counter() - started) * 1000, 2), resolved_ip=address)
                    return result
            except BaseException as exc:  # one address may fail while another works
                last_error = exc
        raise last_error or OSError("Connection failed")
    except BaseException as exc:
        result["error_type"], result["error_message"] = _classify_error(exc)
        return result


def _probe_dns(target: dict) -> dict:
    result = _base_result(target)
    started = time.perf_counter()
    try:
        host = _validate_host_syntax(target["host"])
        
        is_ip = False
        try:
            ipaddress.ip_address(host)
            is_ip = True
        except ValueError:
            pass
            
        if is_ip:
            if not _is_allowed_ip(host):
                raise PermissionError("SSRF_BLOCKED")
            timeout = float(target.get("timeout_ms") or 2000) / 1000.0
            
            # Send UDP DNS query for www.baidu.com
            domain = "www.baidu.com"
            header = struct.pack("!HHHHHH", 0x1a2b, 0x0100, 1, 0, 0, 0)
            qname = b""
            for part in domain.split("."):
                if not part:
                    continue
                part_bytes = part.encode("utf-8")
                qname += struct.pack("B", len(part_bytes)) + part_bytes
            qname += b"\x00"
            question = qname + struct.pack("!HH", 1, 1)
            packet = header + question
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            try:
                sock.sendto(packet, (host, int(target.get("port") or 53)))
                data, _ = sock.recvfrom(512)
                if len(data) >= 12:
                    tx_id, flags = struct.unpack("!HH", data[:4])
                    if tx_id == 0x1a2b:
                        latency = round((time.perf_counter() - started) * 1000, 2)
                        result.update(success=True, latency_ms=latency, resolved_ip=host)
                        return result
                raise ValueError("Invalid DNS response")
            finally:
                sock.close()
        else:
            answers = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
            ips = list(dict.fromkeys(str(item[4][0]) for item in answers if item[4]))
            allowed = [ip for ip in ips if _is_allowed_ip(ip)]
            if not allowed:
                raise PermissionError("SSRF_BLOCKED")
            result.update(success=True, latency_ms=round((time.perf_counter() - started) * 1000, 2), resolved_ip=allowed[0], dns_answers=allowed[:8])
    except BaseException as exc:
        result["error_type"], result["error_message"] = _classify_error(exc)
    return result


def _http_request(target: dict) -> dict:
    result = _base_result(target)
    started = time.perf_counter()
    parsed = urlsplit(target.get("url") or "")
    try:
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Invalid HTTP URL")
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addresses = _resolve_and_validate(host, port)
        address = addresses[0]
        raw_sock = socket.create_connection((address, port), timeout=int(target["timeout_ms"]) / 1000)
        connection = None
        try:
            if parsed.scheme == "https":
                context = ssl.create_default_context()
                raw_sock = context.wrap_socket(raw_sock, server_hostname=host)
            connection = http.client.HTTPConnection(host, port, timeout=int(target["timeout_ms"]) / 1000)
            connection.sock = raw_sock
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.putrequest("GET", path, skip_host=True, skip_accept_encoding=True)
            connection.putheader("Host", host)
            connection.putheader("User-Agent", "Nexora-NetOps-OutboundProbe/1.0")
            connection.putheader("Accept", "text/plain,text/html;q=0.8,*/*;q=0.1")
            connection.endheaders()
            response = connection.getresponse()
            body = response.read(_MAX_BODY_BYTES).decode("utf-8", errors="replace")
            result["http_status"] = int(response.status)
            expected = int(target.get("expected_status_code") or 200)
            keyword = str(target.get("expected_keyword") or "")
            if response.status != expected:
                result["error_type"] = "HTTP_STATUS_ERROR"
                result["error_message"] = f"Expected HTTP {expected}, received {response.status}"
            elif keyword and keyword not in body:
                result["error_type"] = "HTTP_STATUS_ERROR"
                result["error_message"] = "Expected response keyword was not found"
            else:
                result.update(success=True, latency_ms=round((time.perf_counter() - started) * 1000, 2), resolved_ip=address)
        finally:
            try:
                if connection is not None:
                    connection.close()
            except Exception:
                try:
                    raw_sock.close()
                except Exception:
                    pass
    except BaseException as exc:
        result["error_type"], result["error_message"] = _classify_error(exc)
    return result


def _probe_target(target: dict) -> dict:
    probe_type = str(target.get("probe_type") or "TCP_CONNECT").upper()
    if probe_type == "DNS_RESOLVE":
        return _probe_dns(target)
    if probe_type in {"HTTP_GET", "HTTPS_GET"}:
        return _http_request(target)
    if probe_type == "ICMP_PING":
        return _probe_icmp(target)
    return _probe_tcp(target)


def _raw_status(success_count: int, total_targets: int) -> str:
    if total_targets <= 0:
        return STATUS_UNKNOWN
    if success_count == total_targets:
        return STATUS_HEALTHY
    if success_count == 0:
        return STATUS_UNAVAILABLE
    return STATUS_DEGRADED


def _status_with_hysteresis(previous: dict | None, raw_status: str) -> tuple[str, int, int]:
    if not previous:
        if raw_status == STATUS_HEALTHY:
            return STATUS_HEALTHY, 0, 1
        if raw_status == STATUS_UNKNOWN:
            return STATUS_UNKNOWN, 0, 0
        return STATUS_UNKNOWN, 1, 0
    current = str(previous.get("status") or STATUS_UNKNOWN)
    failures = int(previous.get("consecutive_failure_count") or 0)
    recoveries = int(previous.get("consecutive_recovery_count") or 0)
    if raw_status == STATUS_UNKNOWN:
        return STATUS_UNKNOWN, 0, 0
    if raw_status == STATUS_HEALTHY:
        recoveries += 1
        failures = 0
        if current in {STATUS_UNAVAILABLE, STATUS_DEGRADED, STATUS_UNKNOWN} and recoveries < 2:
            return current, failures, recoveries
        return STATUS_HEALTHY, failures, recoveries
    failures += 1
    recoveries = 0
    if current in {STATUS_HEALTHY, STATUS_DEGRADED, STATUS_UNKNOWN} and failures < 3:
        return current, failures, recoveries
    return raw_status, failures, recoveries


def _group_statuses(results: list[dict]) -> dict[str, dict]:
    grouped: dict[str, list[dict]] = {}
    for item in results:
        grouped.setdefault(item["group"], []).append(item)
    output = {}
    for group, items in grouped.items():
        success_count = sum(1 for item in items if item["success"])
        raw = _raw_status(success_count, len(items))
        output[group] = {
            "status": raw,
            "success_count": success_count,
            "total_count": len(items),
            "availability_percent": round(success_count / len(items) * 100, 2) if items else 0,
        }
    return output


def _latest_node(conn) -> dict:
    row = conn.execute(
        "SELECT * FROM outbound_probe_nodes WHERE node_name = ? AND enabled IS TRUE LIMIT 1",
        ("platform-server",),
    ).fetchone()
    if row:
        return dict(row)
    raise RuntimeError("No enabled outbound probe node is configured")


def _latest_run(conn, node_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM outbound_probe_runs WHERE node_id = ? ORDER BY finished_at DESC LIMIT 1",
        (node_id,),
    ).fetchone()
    return dict(row) if row else None


def list_outbound_targets() -> list[dict]:
    conn = get_db_connection()
    try:
        # Check if default ICMP ping targets exist, if not, add them automatically
        cursor = conn.cursor()
        cursor.execute("SELECT target_name FROM outbound_probe_targets WHERE probe_type = 'ICMP_PING'")
        existing_pings = {str(row[0]) for row in cursor.fetchall()}
        
        now = datetime.now(timezone.utc).isoformat()
        default_pings = [
            ("default-aliyun-ping", "Aliyun Ping", "223.5.5.5", 0, "ICMP_PING", "domestic", "", 200),
            ("default-tencent-ping", "Tencent Ping", "119.29.29.29", 0, "ICMP_PING", "domestic", "", 200),
            ("default-google-ping", "Google DNS Ping", "8.8.8.8", 0, "ICMP_PING", "international", "", 200),
        ]
        seeded_any = False
        for target_id, name, host, port, probe_type, group_name, url, expected_status in default_pings:
            if name not in existing_pings:
                cursor.execute(
                    """
                    INSERT INTO outbound_probe_targets (
                        id, target_name, host, port, probe_type, enabled, created_at, group_name,
                        url, expected_status_code, expected_keyword, timeout_ms, is_active, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (id) DO NOTHING
                    """,
                    (target_id, name, host, port, probe_type, True, now, group_name, url, expected_status, "", 2500, True, now),
                )
                seeded_any = True
        if seeded_any:
            conn.commit()

        rows = conn.execute(
            "SELECT id, target_name, host, port, probe_type, group_name, url, expected_status_code, "
            "expected_keyword, timeout_ms, enabled, is_active, created_at, updated_at "
            "FROM outbound_probe_targets ORDER BY group_name, target_name"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def upsert_outbound_target(payload: dict, *, target_id: str | None = None) -> dict:
    target = normalize_target_payload(payload, target_id=target_id)
    conn = get_db_connection()
    try:
        existing = conn.execute("SELECT * FROM outbound_probe_targets WHERE id = ?", (target["id"],)).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE outbound_probe_targets
                SET target_name = ?, host = ?, port = ?, probe_type = ?, group_name = ?, url = ?,
                    expected_status_code = ?, expected_keyword = ?, timeout_ms = ?, enabled = ?,
                    is_active = ?, updated_at = ?
                WHERE id = ?
                """,
                (target["target_name"], target["host"], target["port"], target["probe_type"], target["group_name"],
                 target["url"], target["expected_status_code"], target["expected_keyword"], target["timeout_ms"],
                 target["enabled"], target["enabled"], target["updated_at"], target["id"]),
            )
        else:
            conn.execute(
                """
                INSERT INTO outbound_probe_targets
                    (id, target_name, host, port, probe_type, is_active, created_at, group_name, url,
                     expected_status_code, expected_keyword, timeout_ms, enabled, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (target["id"], target["target_name"], target["host"], target["port"], target["probe_type"],
                 target["enabled"], target["updated_at"], target["group_name"], target["url"],
                 target["expected_status_code"], target["expected_keyword"], target["timeout_ms"],
                 target["enabled"], target["updated_at"]),
            )
        conn.commit()
        row = conn.execute("SELECT * FROM outbound_probe_targets WHERE id = ?", (target["id"],)).fetchone()
        return dict(row)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_outbound_target(target_id: str) -> bool:
    conn = get_db_connection()
    try:
        row = conn.execute("SELECT id FROM outbound_probe_targets WHERE id = ?", (target_id,)).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM outbound_probe_targets WHERE id = ?", (target_id,))
        conn.commit()
        return True
    finally:
        conn.close()


_CONFIG_ERRORS: list[str] = []
_CONFIG_VALID = True
_EXPECTED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
_EXPECTED_IPS: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
_LAST_EXPECTED_RAW = None

def validate_expected_egress_ip_config() -> None:
    global _CONFIG_VALID, _CONFIG_ERRORS, _EXPECTED_NETWORKS, _EXPECTED_IPS
    expected_raw = os.environ.get("OUTBOUND_PROBE_EXPECTED_EGRESS_IP", "").strip()
    if not expected_raw:
        _CONFIG_VALID = True
        _CONFIG_ERRORS = []
        _EXPECTED_NETWORKS = []
        _EXPECTED_IPS = []
        return
    
    errors = []
    networks = []
    ips = []
    
    parts = [item.strip() for item in expected_raw.split(",") if item.strip()]
    seen = set()
    unique_parts = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            unique_parts.append(p)
            
    for part in unique_parts:
        try:
            if "/" in part:
                net = ipaddress.ip_network(part, strict=False)
                networks.append(net)
            else:
                addr = ipaddress.ip_address(part)
                ips.append(addr)
        except ValueError as exc:
            errors.append(f"Invalid entry '{part}': {exc}")
            
    if errors:
        _CONFIG_VALID = False
        _CONFIG_ERRORS = errors
        _EXPECTED_NETWORKS = []
        _EXPECTED_IPS = []
        for err in errors:
            logger.error("[配置错误] OUTBOUND_PROBE_EXPECTED_EGRESS_IP: %s", err)
    else:
        _CONFIG_VALID = True
        _CONFIG_ERRORS = []
        _EXPECTED_NETWORKS = networks
        _EXPECTED_IPS = ips


validate_expected_egress_ip_config()


def _check_ip_matches_expected(detected_ip: str) -> bool:
    global _LAST_EXPECTED_RAW
    expected_raw = os.environ.get("OUTBOUND_PROBE_EXPECTED_EGRESS_IP", "").strip()
    if expected_raw != _LAST_EXPECTED_RAW:
        _LAST_EXPECTED_RAW = expected_raw
        validate_expected_egress_ip_config()
        
    if not _CONFIG_VALID:
        logger.warning("[警告] 由于配置格式错误，跳过期望出口 IP 校验。")
        return True
    
    if not expected_raw:
        return True
        
    if not detected_ip:
        return False
        
    try:
        detected_addr = ipaddress.ip_address(detected_ip)
    except ValueError:
        return False
        
    for net in _EXPECTED_NETWORKS:
        if detected_addr.version == net.version:
            if detected_addr in net:
                return True
    for ip in _EXPECTED_IPS:
        if detected_addr.version == ip.version:
            if detected_addr == ip:
                return True
                
    return False


def _egress_sources() -> list[str]:
    raw = os.environ.get("OUTBOUND_PROBE_EGRESS_SOURCES", "https://api.ipify.org,https://ifconfig.me/ip")
    return [item.strip() for item in raw.split(",") if item.strip()][:3]


def detect_egress_ip() -> dict:
    static_ip = os.environ.get("OUTBOUND_PROBE_STATIC_EGRESS_IP", "").strip()
    if static_ip:
        return {
            "confirmed_ip": static_ip,
            "source_a_ip": static_ip,
            "source_b_ip": static_ip,
            "consistent": True,
            "error_message": "",
            "public_ip_source": "static_override",
            "public_ip_verified": False,
            "confidence": "high",
            "providers_succeeded": 0,
            "providers_total": 0,
        }

    values: list[str] = []
    errors: list[str] = []
    sources = _egress_sources()
    providers_total = len(sources)
    for url in sources:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Nexora-NetOps-OutboundProbe/1.0"})
            with urllib.request.urlopen(request, timeout=2.0) as response:
                candidate = response.read(128).decode("utf-8", errors="ignore").strip()
            parsed = ipaddress.ip_address(candidate)
            if not parsed.is_global:
                raise ValueError("non-global egress address")
            values.append(str(parsed))
        except Exception as exc:
            errors.append(type(exc).__name__)
            
    source_a = values[0] if values else ""
    source_b = values[1] if len(values) > 1 else ""
    consistent = bool(source_a and source_b and source_a == source_b)
    confirmed_ip = source_a if consistent else ""
    
    providers_succeeded = len(values)
    
    if providers_succeeded > 0:
        public_ip_source = "detected"
        public_ip_verified = True
        if providers_succeeded >= 2 and consistent:
            confidence = "high"
        else:
            confidence = "medium"
    else:
        public_ip_source = "unknown"
        public_ip_verified = False
        confidence = "low"
        
    return {
        "confirmed_ip": confirmed_ip,
        "source_a_ip": source_a,
        "source_b_ip": source_b,
        "consistent": consistent,
        "error_message": "; ".join(errors[:2]),
        "public_ip_source": public_ip_source,
        "public_ip_verified": public_ip_verified,
        "confidence": confidence,
        "providers_succeeded": providers_succeeded,
        "providers_total": providers_total,
    }


def _record_egress_event(conn, node_id: str, detected: dict, observed_at: str) -> dict:
    previous_row = conn.execute(
        "SELECT confirmed_ip FROM outbound_egress_ip_events WHERE node_id = ? AND consistent IS TRUE "
        "ORDER BY observed_at DESC LIMIT 1",
        (node_id,),
    ).fetchone()
    previous_ip = str(previous_row[0] or "") if previous_row else ""
    confirmed_ip = str(detected.get("confirmed_ip") or "")

    static_ip = os.environ.get("OUTBOUND_PROBE_STATIC_EGRESS_IP", "").strip()
    expected_ip_raw = os.environ.get("OUTBOUND_PROBE_EXPECTED_EGRESS_IP", "").strip()
    
    if static_ip:
        # In static override mode, we skip expected IP drift check
        changed = False
    elif expected_ip_raw and confirmed_ip:
        # Look up the last 2 events to execute the continuous confirmation state machine
        rows = conn.execute(
            "SELECT confirmed_ip FROM outbound_egress_ip_events WHERE node_id = ? "
            "ORDER BY observed_at DESC LIMIT 2",
            (node_id,),
        ).fetchall()
        prev_1 = str(rows[0][0] or "") if len(rows) > 0 else ""
        prev_2 = str(rows[1][0] or "") if len(rows) > 1 else ""
        
        curr_match = _check_ip_matches_expected(confirmed_ip)
        if not prev_1:
            changed = False
        else:
            prev_1_match = _check_ip_matches_expected(prev_1)
            prev_2_match = _check_ip_matches_expected(prev_2) if prev_2 else True
            
            if not curr_match:
                if not prev_1_match:
                    # 连续两次不匹配：确认漂移
                    changed = True
                else:
                    # 第一次不匹配：暂不确认，维持健康状态
                    changed = False
            else:
                if prev_1_match:
                    # 连续两次匹配：确认恢复/健康
                    changed = False
                else:
                    # 第一次匹配：暂不确认恢复，如果先前已经是已确认的漂移状态则保持，否则健康
                    if not prev_1_match and prev_2 and not prev_2_match:
                        changed = True
                    else:
                        changed = False
    else:
        changed = bool(confirmed_ip and previous_ip and confirmed_ip != previous_ip)

    conn.execute(
        """
        INSERT INTO outbound_egress_ip_events
            (id, node_id, observed_at, previous_ip, confirmed_ip, source_a_ip, source_b_ip, consistent, error_message, public_ip_source, public_ip_verified)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (str(uuid.uuid4()), node_id, observed_at, previous_ip, confirmed_ip, detected.get("source_a_ip", ""),
         detected.get("source_b_ip", ""), bool(detected.get("consistent")), detected.get("error_message", ""),
         detected.get("public_ip_source", "unknown"), bool(detected.get("public_ip_verified"))),
    )
    return {
        "public_ip": confirmed_ip or previous_ip,
        "public_ip_changed": changed,
        "public_ip_source": detected.get("public_ip_source", "unknown"),
        "public_ip_verified": bool(detected.get("public_ip_verified")),
    }


def record_outbound_egress_snapshot() -> None:
    conn = get_db_connection()
    try:
        node = _latest_node(conn)
        observed_at = utc_now_iso()
        detected = detect_egress_ip()
        ip_info = _record_egress_event(conn, node["id"], detected, observed_at)
        conn.execute("UPDATE outbound_probe_nodes SET last_seen_at = ?, updated_at = ? WHERE id = ?", (observed_at, observed_at, node["id"]))
        latest = _latest_run(conn, node["id"])
        if latest:
            conn.execute(
                """
                UPDATE outbound_probe_runs 
                SET public_ip = ?, public_ip_changed = ?, public_ip_source = ?, public_ip_verified = ? 
                WHERE id = ?
                """,
                (ip_info["public_ip"], bool(ip_info["public_ip_changed"]), 
                 ip_info.get("public_ip_source", "unknown"), bool(ip_info.get("public_ip_verified")), 
                 latest["id"]),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Outbound egress IP snapshot failed")
    finally:
        conn.close()


def run_outbound_probe_once(*, include_egress_ip: bool = False) -> dict:
    started_at = utc_now_iso()
    conn = get_db_connection()
    try:
        node = _latest_node(conn)
        rows = conn.execute(
            "SELECT * FROM outbound_probe_targets WHERE enabled IS TRUE OR is_active IS TRUE ORDER BY group_name, target_name"
        ).fetchall()
        targets = [dict(row) for row in rows]
        previous = _latest_run(conn, node["id"])
        egress_info = {
            "public_ip": "",
            "public_ip_changed": False,
            "public_ip_source": "unknown",
            "public_ip_verified": False,
        }
        if include_egress_ip:
            egress_info = _record_egress_event(conn, node["id"], detect_egress_ip(), started_at)
        else:
            ip_row = conn.execute(
                "SELECT confirmed_ip, public_ip_source, public_ip_verified "
                "FROM outbound_egress_ip_events WHERE node_id = ? "
                "ORDER BY observed_at DESC LIMIT 1",
                (node["id"],),
            ).fetchone()
            if ip_row and ip_row[0]:
                egress_info["public_ip"] = str(ip_row[0])
                egress_info["public_ip_source"] = str(ip_row[1] or "unknown")
                egress_info["public_ip_verified"] = bool(ip_row[2])
            else:
                # Cold start fallback: if no cached IP exists, perform detection immediately
                detected = detect_egress_ip()
                egress_info = _record_egress_event(conn, node["id"], detected, started_at)
                
            static_ip = os.environ.get("OUTBOUND_PROBE_STATIC_EGRESS_IP", "").strip()
            expected_ip_raw = os.environ.get("OUTBOUND_PROBE_EXPECTED_EGRESS_IP", "").strip()
            if static_ip:
                egress_info["public_ip_changed"] = False
            elif expected_ip_raw and egress_info["public_ip"]:
                if previous:
                    egress_info["public_ip_changed"] = bool(previous.get("public_ip_changed"))
                else:
                    egress_info["public_ip_changed"] = not _check_ip_matches_expected(egress_info["public_ip"])
            else:
                if previous:
                    egress_info["public_ip_changed"] = bool(previous.get("public_ip_changed"))
    finally:
        conn.close()

    results: list[dict] = []
    if targets:
        workers = min(10, max(1, len(targets)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="outbound-probe") as executor:
            future_map = {executor.submit(_probe_target, target): target for target in targets}
            for future in concurrent.futures.as_completed(future_map):
                target = future_map[future]
                try:
                    result = future.result()
                except BaseException as exc:
                    result = _base_result(target)
                    result["error_type"], result["error_message"] = _classify_error(exc)
                results.append(result)
    results.sort(key=lambda item: (item["group"], item["target_name"]))
    success_count = sum(1 for result in results if result["success"])
    total_targets = len(results)
    raw_status = _raw_status(success_count, total_targets)
    status, failure_count, recovery_count = _status_with_hysteresis(previous, raw_status)
    
    # Check if the mismatch affects overall health
    mismatch_affects_health = os.environ.get("OUTBOUND_PROBE_EGRESS_IP_MISMATCH_AFFECT_HEALTH", "true").lower() == "true"
    
    # If the public IP is mismatched with the expected IP block, degrade status and set custom warning reason
    if egress_info.get("public_ip_changed"):
        expected_raw = os.environ.get("OUTBOUND_PROBE_EXPECTED_EGRESS_IP", "").strip()
        if expected_raw:
            reason = f"警告：当前公网出口 IP ({egress_info['public_ip']}) 与期望静态 IP ({expected_raw}) 不匹配，可能发生出口切换！"
        else:
            reason = f"提示：公网出口 IP 发生变更 (当前为 {egress_info['public_ip']})"
            
        if mismatch_affects_health and raw_status == STATUS_HEALTHY:
            raw_status = STATUS_DEGRADED
            status = STATUS_DEGRADED
    else:
        reason = f"{success_count} / {total_targets} 个目标可用" if total_targets else "没有已启用的探测目标"

    finished_at = utc_now_iso()
    latencies = [float(result["latency_ms"]) for result in results if result["success"] and result["latency_ms"] is not None]
    availability = round(success_count / total_targets * 100, 2) if total_targets else 0
    group_statuses = _group_statuses(results)
    run_id = str(uuid.uuid4())

    conn = get_db_connection()
    try:
        node = _latest_node(conn)
        conn.execute(
            """
            INSERT INTO outbound_probe_runs (
                id, node_id, started_at, finished_at, status, raw_status, status_reason,
                success_count, total_targets, availability_percent, average_latency_ms,
                public_ip, public_ip_changed, consecutive_failure_count, consecutive_recovery_count,
                group_status_json, created_at, public_ip_source, public_ip_verified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, node["id"], started_at, finished_at, status, raw_status, reason, success_count, total_targets,
             availability, round(sum(latencies) / len(latencies), 2) if latencies else None, egress_info["public_ip"],
             bool(egress_info["public_ip_changed"]), failure_count, recovery_count,
             json.dumps(group_statuses, ensure_ascii=True), finished_at,
             egress_info.get("public_ip_source", "unknown"), bool(egress_info.get("public_ip_verified"))),
        )
        for result in results:
            conn.execute(
                """
                INSERT INTO outbound_probe_results (
                    id, run_id, target_id, target_name, group_name, probe_type, sampled_at,
                    success, latency_ms, error_type, error_message, resolved_ip, http_status, dns_answers_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), run_id, result["target_id"], result["target_name"], result["group"], result["probe_type"],
                 finished_at, bool(result["success"]), result["latency_ms"], result["error_type"],
                 result["error_message"], result["resolved_ip"], result["http_status"], json.dumps(result["dns_answers"][:8])),
            )
        # Preserve the existing aggregate table for older consumers.
        conn.execute(
            """
            INSERT INTO outbound_probe_samples
                (id, timestamp, success_count, total_targets, success_rate, egress_ip, avg_latency_ms,
                 node_id, status, status_reason, public_ip_changed, consecutive_failure_count, consecutive_recovery_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, finished_at, success_count, total_targets, availability / 100, egress_info["public_ip"],
             round(sum(latencies) / len(latencies), 2) if latencies else 0, node["id"], status, reason,
             bool(egress_info["public_ip_changed"]), failure_count, recovery_count),
        )
        retention_days = max(1, int(getattr(settings, "OUTBOUND_PROBE_RETENTION_DAYS", 30) or 30))
        retention_hours = retention_days * 24
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=retention_hours)).isoformat()
        conn.execute("DELETE FROM outbound_probe_results WHERE sampled_at < ?", (cutoff,))
        conn.execute("DELETE FROM outbound_probe_runs WHERE finished_at < ?", (cutoff,))
        conn.execute("DELETE FROM outbound_probe_samples WHERE timestamp < ?", (cutoff,))
        conn.execute("UPDATE outbound_probe_nodes SET last_seen_at = ?, updated_at = ? WHERE id = ?", (finished_at, finished_at, node["id"]))
        conn.commit()
    except Exception:
        conn.rollback()
        logger.exception("Failed to persist outbound probe run")
        raise
    finally:
        conn.close()

    return {
        "run_id": run_id,
        "node_id": node["id"],
        "node_name": node["node_name"],
        "status": status,
        "raw_status": raw_status,
        "status_reason": reason,
        "success_count": success_count,
        "total_count": total_targets,
        "availability_percent": availability,
        "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "public_ip": egress_info["public_ip"],
        "public_ip_changed": bool(egress_info["public_ip_changed"]),
        "consecutive_failure_count": failure_count,
        "consecutive_recovery_count": recovery_count,
        "checked_at": finished_at,
        "groups": group_statuses,
        "targets": results,
    }


def record_outbound_probe_snapshot() -> None:
    """Backward-compatible scheduler entry point for older deployments."""
    run_outbound_probe_once(include_egress_ip=False)


def get_outbound_status(*, history_hours: int = 24) -> dict:
    conn = get_db_connection()
    try:
        node = _latest_node(conn)
        current = _latest_run(conn, node["id"])
        requested_history_hours = _bounded_history_hours(history_hours)
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=requested_history_hours)).isoformat()
        runs = conn.execute(
            "SELECT * FROM outbound_probe_runs WHERE node_id = ? AND finished_at >= ? ORDER BY finished_at ASC",
            (node["id"], cutoff),
        ).fetchall()
        current_payload = None
        if current:
            try:
                groups = json.loads(current.get("group_status_json") or "{}")
            except (TypeError, ValueError):
                groups = {}
            recent_cutoff = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
            recent_stats = conn.execute(
                """
                SELECT target_id, 
                       COUNT(*) as total_count,
                       SUM(CASE WHEN success IS TRUE THEN 1 ELSE 0 END) as success_count
                FROM outbound_probe_results
                WHERE sampled_at >= ?
                GROUP BY target_id
                """,
                (recent_cutoff,)
            ).fetchall()
            recent_avail_map = {}
            for row in recent_stats:
                total_cnt = int(row["total_count"])
                success_cnt = int(row["success_count"])
                avail = round(success_cnt / total_cnt * 100, 2) if total_cnt > 0 else 100.0
                recent_avail_map[row["target_id"]] = avail

            result_rows = conn.execute(
                "SELECT * FROM outbound_probe_results WHERE run_id = ? ORDER BY group_name, target_name",
                (current["id"],),
            ).fetchall()
            targets = []
            for row in result_rows:
                item = dict(row)
                try:
                    item["dns_answers"] = json.loads(item.pop("dns_answers_json", "[]") or "[]")
                except (TypeError, ValueError):
                    item["dns_answers"] = []
                item["group"] = item.pop("group_name", "business")
                item["success"] = bool(item.get("success"))
                tid = item.get("target_id")
                item["recent_availability"] = recent_avail_map.get(tid, 100.0)
                targets.append(item)
            # connectivity_status calculation:
            if current["status"] == STATUS_DEGRADED and bool(current.get("public_ip_changed")):
                if int(current["success_count"]) == int(current["total_targets"]) and int(current["total_targets"]) > 0:
                    connectivity_status = STATUS_HEALTHY
                else:
                    connectivity_status = STATUS_DEGRADED
            else:
                connectivity_status = current["status"]

            # Load the latest event to fetch detailed egress IP source / verified / confidence
            latest_event_row = conn.execute(
                "SELECT * FROM outbound_egress_ip_events WHERE node_id = ? "
                "ORDER BY observed_at DESC LIMIT 1",
                (node["id"],),
            ).fetchone()
            latest_event = dict(latest_event_row) if latest_event_row else {}
            
            source_a = latest_event.get("source_a_ip") or ""
            source_b = latest_event.get("source_b_ip") or ""
            consistent = bool(latest_event.get("consistent"))
            
            providers_succeeded = sum(1 for ip in (source_a, source_b) if ip)
            if latest_event.get("public_ip_source") == "static_override":
                confidence = "high"
            elif providers_succeeded >= 2 and consistent:
                confidence = "high"
            elif providers_succeeded >= 1:
                confidence = "medium"
            else:
                confidence = "low"
                
            expected_raw = os.environ.get("OUTBOUND_PROBE_EXPECTED_EGRESS_IP", "").strip()
            expected_list = [item.strip() for item in expected_raw.split(",") if item.strip()]
            
            match_ok = True
            mismatch_status = "none"
            if expected_raw and current.get("public_ip"):
                match_ok = _check_ip_matches_expected(current["public_ip"])
                mismatch_status = "match" if match_ok else "mismatch"
                
            egress_payload = {
                "address": current.get("public_ip") or "",
                "source": latest_event.get("public_ip_source") or "unknown",
                "verified": bool(latest_event.get("public_ip_verified")),
                "confidence": confidence,
                "expected": expected_list,
                "match": match_ok,
                "status": mismatch_status,
                "providers_succeeded": providers_succeeded,
                "providers_total": 2,
            }
            
            status_reasons = []
            if current.get("public_ip_changed"):
                severity = os.environ.get("OUTBOUND_PROBE_EGRESS_IP_MISMATCH_SEVERITY", "warning").lower()
                if severity not in ("info", "warning", "critical"):
                    severity = "warning"
                if expected_raw:
                    msg = f"互联网访问正常，但当前公网出口 IP ({current.get('public_ip')}) 与期望静态 IP 不匹配，可能发生出口切换！"
                else:
                    msg = f"公网出口 IP 发生变更 (当前为 {current.get('public_ip')})"
                status_reasons.append({
                    "type": "egress_ip_mismatch",
                    "severity": severity,
                    "message": msg
                })
            
            if not _CONFIG_VALID and _CONFIG_ERRORS:
                status_reasons.append({
                    "type": "configuration_error",
                    "severity": "critical",
                    "message": f"配置错误：OUTBOUND_PROBE_EXPECTED_EGRESS_IP 格式非法 — {_CONFIG_ERRORS[0]}"
                })
                
            # Calculate P95 and Max latency dynamically
            latencies = [float(item["latency_ms"]) for item in targets if item["success"] and item.get("latency_ms") is not None]
            p95_latency = _percentile(latencies, 0.95) if latencies else None
            max_latency = max(latencies) if latencies else None

            # Calculate overall status duration
            status_duration_seconds = 0
            current_status = current["status"]
            if current_status:
                diff_row = conn.execute(
                    "SELECT finished_at FROM outbound_probe_runs WHERE node_id = ? AND status != ? "
                    "ORDER BY finished_at DESC LIMIT 1",
                    (node["id"], current_status),
                ).fetchone()
                if diff_row and diff_row[0]:
                    transition_time = datetime.fromisoformat(diff_row[0].replace('Z', '+00:00'))
                else:
                    earliest_row = conn.execute(
                        "SELECT started_at FROM outbound_probe_runs WHERE node_id = ? "
                        "ORDER BY finished_at ASC LIMIT 1",
                        (node["id"],),
                    ).fetchone()
                    if earliest_row and earliest_row[0]:
                        transition_time = datetime.fromisoformat(earliest_row[0].replace('Z', '+00:00'))
                    else:
                        transition_time = None
                
                if transition_time:
                    now = datetime.now(timezone.utc)
                    status_duration_seconds = max(0, int((now - transition_time).total_seconds()))

            # Scheduler next check time and watchdog
            next_check_at = None
            try:
                from core.scheduler_manager import scheduler
                job = scheduler.get_job('outbound_probe_sampler')
                if job and job.next_run_time:
                    next_check_at = job.next_run_time.isoformat()
            except Exception:
                pass

            scheduler_is_running = True
            scheduler_interrupted_minutes = 0
            if current.get("finished_at"):
                last_checked = datetime.fromisoformat(current["finished_at"].replace('Z', '+00:00'))
                now = datetime.now(timezone.utc)
                diff_minutes = (now - last_checked).total_seconds() / 60
                if diff_minutes > 3.0:
                    scheduler_is_running = False
                    scheduler_interrupted_minutes = int(diff_minutes)

            current_payload = {
                "run_id": current["id"],
                "node_id": node["id"],
                "node_name": node["node_name"],
                "status": current["status"],
                "raw_status": current["raw_status"],
                "status_reason": current["status_reason"],
                "success_count": int(current["success_count"]),
                "total_count": int(current["total_targets"]),
                "availability_percent": float(current["availability_percent"]),
                "average_latency_ms": current["average_latency_ms"],
                "p95_latency_ms": p95_latency,
                "max_latency_ms": max_latency,
                "status_duration_seconds": status_duration_seconds,
                "next_check_at": next_check_at,
                "scheduler_is_running": scheduler_is_running,
                "scheduler_interrupted_minutes": scheduler_interrupted_minutes,
                "public_ip": current.get("public_ip") or "",
                "public_ip_changed": bool(current.get("public_ip_changed")),
                "consecutive_failure_count": int(current["consecutive_failure_count"]),
                "consecutive_recovery_count": int(current["consecutive_recovery_count"]),
                "checked_at": current["finished_at"],
                "groups": groups,
                "targets": targets,
                "connectivity_status": connectivity_status,
                "overall_status": current["status"],
                "egress_ip": egress_payload,
                "status_reasons": status_reasons,
            }
        history = []
        for row in runs:
            item = dict(row)
            try:
                item["groups"] = json.loads(item.pop("group_status_json", "{}") or "{}")
            except (TypeError, ValueError):
                item["groups"] = {}
            item["availability_percent"] = float(item.get("availability_percent") or 0)
            history.append(item)
        return {
            "current": current_payload,
            "history": _downsample_history(history),
            "history_hours": requested_history_hours,
            "history_total_points": len(history),
            "targets": list_outbound_targets(),
        }
    finally:
        conn.close()


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * weight, 2)


def get_outbound_target_history(*, target_id: str, history_hours: int = 24, start_time: str | None = None, end_time: str | None = None) -> dict | None:
    """Return per-target samples and latency/availability summary."""
    conn = get_db_connection()
    try:
        target_row = conn.execute(
            """
            SELECT id, target_name, host, port, probe_type, group_name, url, expected_status_code,
                   expected_keyword, timeout_ms, enabled, is_active, created_at, updated_at
            FROM outbound_probe_targets
            WHERE id = ?
            """,
            (target_id,),
        ).fetchone()
        if not target_row:
            return None

        if start_time and end_time:
            rows = conn.execute(
                """
                SELECT result.id, result.run_id, result.target_id, result.target_name, result.group_name,
                       result.probe_type, result.sampled_at, result.success, result.latency_ms,
                       result.error_type, result.error_message, result.resolved_ip, result.http_status,
                       result.dns_answers_json, run.status AS run_status, run.public_ip
                FROM outbound_probe_results AS result
                JOIN outbound_probe_runs AS run ON run.id = result.run_id
                WHERE result.target_id = ? AND result.sampled_at >= ? AND result.sampled_at <= ?
                ORDER BY result.sampled_at ASC
                """,
                (target_id, start_time, end_time),
            ).fetchall()
            try:
                start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                requested_history_hours = int((end_dt - start_dt).total_seconds() / 3600)
            except Exception:
                requested_history_hours = 24
        else:
            requested_history_hours = _bounded_history_hours(history_hours)
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=requested_history_hours)).isoformat()
            rows = conn.execute(
                """
                SELECT result.id, result.run_id, result.target_id, result.target_name, result.group_name,
                       result.probe_type, result.sampled_at, result.success, result.latency_ms,
                       result.error_type, result.error_message, result.resolved_ip, result.http_status,
                       result.dns_answers_json, run.status AS run_status, run.public_ip
                FROM outbound_probe_results AS result
                JOIN outbound_probe_runs AS run ON run.id = result.run_id
                WHERE result.target_id = ? AND result.sampled_at >= ?
                ORDER BY result.sampled_at ASC
                """,
                (target_id, cutoff),
            ).fetchall()

        samples: list[dict] = []
        latencies: list[float] = []
        success_count = 0
        for row in rows:
            item = dict(row)
            item["success"] = bool(item.get("success"))
            if item["success"]:
                success_count += 1
            if item.get("latency_ms") is not None:
                item["latency_ms"] = float(item["latency_ms"])
                if item["success"]:
                    latencies.append(item["latency_ms"])
            try:
                item["dns_answers"] = json.loads(item.pop("dns_answers_json", "[]") or "[]")
            except (TypeError, ValueError):
                item["dns_answers"] = []
            item["group"] = item.pop("group_name", "business")
            samples.append(item)

        total = len(samples)
        return {
            "target": dict(target_row),
            "history_hours": requested_history_hours,
            "history_total_points": len(samples),
            "summary": {
                "sample_count": total,
                "success_count": success_count,
                "failure_count": total - success_count,
                "availability_percent": round(success_count / total * 100, 2) if total else 0,
                "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
                "p50_latency_ms": _percentile(latencies, 0.50),
                "p95_latency_ms": _percentile(latencies, 0.95),
                "max_latency_ms": round(max(latencies), 2) if latencies else None,
            },
            "latest": samples[-1] if samples else None,
            "history": _downsample_history(samples),
        }
    finally:
        conn.close()
