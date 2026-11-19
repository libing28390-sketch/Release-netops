"""Persist static, reusable topology device icons and their assignments."""

from __future__ import annotations

import hashlib
import hmac
import io
import logging
import math
import re
import uuid
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from database import get_db_connection
from services.storage_service import StorageError, build_storage_service, effective_storage_provider


DEVICE_TYPES = frozenset({
    "switch",
    "firewall",
    "router",
    "load_balancer",
    "waf",
    "vpn_gateway",
    "server",
    "wireless_ap",
    "wireless_controller",
    "wireless",
    "generic",
})
MAX_ICON_SIZE_BYTES = 4 * 1024 * 1024
MAX_SVG_ELEMENTS = 10_000
MAX_SVG_DEPTH = 32
MAX_SVG_ATTRIBUTE_VALUE_LENGTH = 100_000
MAX_RASTER_EDGE = 4_096
MAX_RASTER_PIXELS = 16_777_216
MAX_PNG_DECODED_BYTES = 80 * 1024 * 1024

logger = logging.getLogger(__name__)

_SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_SVG_ELEMENTS = frozenset({
    "svg", "g", "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "defs", "linearGradient", "radialGradient", "stop", "clipPath", "mask", "title", "desc",
})
_SVG_ATTRIBUTES = frozenset({
    "xmlns", "width", "height", "viewBox", "preserveAspectRatio", "version",
    "fill", "fill-rule", "fill-opacity", "stroke", "stroke-width", "stroke-linecap",
    "stroke-linejoin", "stroke-miterlimit", "stroke-dasharray", "stroke-dashoffset",
    "stroke-opacity", "opacity", "transform", "d", "x", "y", "x1", "y1", "x2", "y2",
    "cx", "cy", "r", "rx", "ry", "points", "id", "offset", "stop-color", "stop-opacity",
    "gradientUnits", "gradientTransform", "spreadMethod", "clipPathUnits", "maskUnits",
    "maskContentUnits",
})
_SAFE_LOCAL_URL = re.compile(r"url\(\s*(['\"]?)#([A-Za-z_][\w.:-]*)\1\s*\)", re.IGNORECASE)
_SVG_LENGTH = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(?:px)?\s*$", re.IGNORECASE)


class TopologyIconError(ValueError):
    def __init__(self, detail: str, status_code: int = 422):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class ValidatedTopologyIcon:
    device_type: str
    name: str
    filename_extension: str
    content_type: str
    content: bytes
    sha256: str


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _validate_device_type(device_type: str) -> str:
    normalized = str(device_type or "").strip().lower()
    if normalized not in DEVICE_TYPES:
        raise TopologyIconError("device_type is not supported")
    return normalized


def _svg_dimension(root: ET.Element, view_box_index: int, attribute: str) -> float | None:
    view_box = root.attrib.get("viewBox")
    if view_box:
        values = re.split(r"[\s,]+", view_box.strip())
        if len(values) != 4:
            raise TopologyIconError("SVG viewBox must contain four numbers")
        try:
            dimensions = [float(value) for value in values]
        except ValueError as exc:
            raise TopologyIconError("SVG viewBox must contain finite numbers") from exc
        if not all(math.isfinite(value) for value in dimensions) or dimensions[2] <= 0 or dimensions[3] <= 0:
            raise TopologyIconError("SVG viewBox dimensions must be positive")
        return dimensions[view_box_index]

    raw = root.attrib.get(attribute)
    if raw is None:
        return None
    match = _SVG_LENGTH.fullmatch(raw)
    if not match:
        raise TopologyIconError("SVG dimensions must use numeric pixel values or a viewBox")
    return float(match.group(1))


def _validate_svg(content: bytes) -> None:
    try:
        svg_text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise TopologyIconError("SVG must use UTF-8 encoding") from exc
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", svg_text, re.IGNORECASE):
        raise TopologyIconError("SVG DTD and entity declarations are not supported")
    if re.search(r"<\?(?!xml(?:\s|\?))", svg_text, re.IGNORECASE):
        raise TopologyIconError("SVG processing instructions are not supported")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise TopologyIconError("SVG XML could not be parsed") from exc
    if root.tag != f"{{{_SVG_NAMESPACE}}}svg" and root.tag != "svg":
        raise TopologyIconError("SVG document must have an svg root element")

    width = _svg_dimension(root, 2, "width")
    height = _svg_dimension(root, 3, "height")
    if width is None or height is None:
        raise TopologyIconError("SVG requires a viewBox or explicit width and height")
    if width <= 0 or height <= 0 or width > 16_384 or height > 16_384:
        raise TopologyIconError("SVG dimensions must be between 1 and 16384")

    identifiers: set[str] = set()
    references: list[str] = []
    stack: list[tuple[ET.Element, int]] = [(root, 1)]
    element_count = 0
    while stack:
        element, depth = stack.pop()
        element_count += 1
        if element_count > MAX_SVG_ELEMENTS or depth > MAX_SVG_DEPTH:
            raise TopologyIconError("SVG contains too many or deeply nested elements")

        if element.tag.startswith("{"):
            namespace, local_name = element.tag[1:].split("}", 1)
            if namespace != _SVG_NAMESPACE:
                raise TopologyIconError("SVG may only contain SVG namespace elements")
        else:
            local_name = element.tag
        if local_name not in _SVG_ELEMENTS:
            raise TopologyIconError(f"SVG element '{local_name}' is not supported")

        for raw_name, value in element.attrib.items():
            local_attribute = raw_name.rsplit("}", 1)[-1]
            if local_attribute.lower().startswith("on") or local_attribute.lower() in {"href", "src", "style"}:
                raise TopologyIconError("SVG scripts, styles, and external references are not supported")
            if local_attribute not in _SVG_ATTRIBUTES:
                raise TopologyIconError(f"SVG attribute '{local_attribute}' is not supported")
            if len(value) > MAX_SVG_ATTRIBUTE_VALUE_LENGTH:
                raise TopologyIconError("SVG attribute value is too long")
            if local_attribute == "id":
                identifiers.add(value)
            for match in _SAFE_LOCAL_URL.finditer(value):
                references.append(match.group(2))
            safe_value = _SAFE_LOCAL_URL.sub("", value)
            if "url(" in safe_value.lower():
                raise TopologyIconError("SVG references must point to an element in the same file")
        stack.extend((child, depth + 1) for child in reversed(list(element)))

    if any(reference not in identifiers for reference in references):
        raise TopologyIconError("SVG references must point to an existing element")


def validate_topology_icon_upload(
    *, device_type: str, name: str, filename: str, content_type: str | None, content: bytes,
) -> ValidatedTopologyIcon:
    normalized_type = _validate_device_type(device_type)
    normalized_name = str(name or "").strip()
    if not normalized_name or len(normalized_name) > 80 or any(ord(char) < 32 for char in normalized_name):
        raise TopologyIconError("Icon name must contain 1 to 80 printable characters")
    if not content:
        raise TopologyIconError("Icon file is empty")
    if len(content) > MAX_ICON_SIZE_BYTES:
        raise TopologyIconError("Icon file must be 4 MiB or smaller")

    filename_extension = str(filename or "").rsplit(".", 1)[-1].lower() if "." in str(filename or "") else ""
    supplied_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if filename_extension == "svg":
        if supplied_type not in {"", "application/octet-stream", "image/svg+xml"}:
            raise TopologyIconError("SVG file content type does not match its extension")
        _validate_svg(content)
        resolved_type = "image/svg+xml"
    elif filename_extension == "png":
        if supplied_type not in {"", "application/octet-stream", "image/png"}:
            raise TopologyIconError("PNG file content type does not match its extension")
        if len(content) < 45 or content[:8] != b"\x89PNG\r\n\x1a\n":
            raise TopologyIconError("File does not have a valid PNG signature and IHDR")
        offset = 8
        width = height = 0
        saw_header = saw_image_data = saw_end = False
        saw_palette = False
        idat_chunks: list[bytes] = []
        color_type = bit_depth = interlace = 0
        idat_sequence_ended = False
        while offset + 12 <= len(content):
            chunk_length = int.from_bytes(content[offset:offset + 4], "big")
            chunk_type = content[offset + 4:offset + 8]
            data_start = offset + 8
            data_end = data_start + chunk_length
            crc_end = data_end + 4
            if crc_end > len(content):
                raise TopologyIconError("PNG contains a truncated chunk")
            chunk_data = content[data_start:data_end]
            expected_crc = int.from_bytes(content[data_end:crc_end], "big")
            actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
            if expected_crc != actual_crc:
                raise TopologyIconError("PNG chunk checksum is invalid")
            if not saw_header:
                if chunk_type != b"IHDR" or chunk_length != 13:
                    raise TopologyIconError("PNG must begin with a valid IHDR chunk")
                width = int.from_bytes(chunk_data[0:4], "big")
                height = int.from_bytes(chunk_data[4:8], "big")
                bit_depth = chunk_data[8]
                color_type = chunk_data[9]
                valid_depths = {
                    0: {1, 2, 4, 8, 16},
                    2: {8, 16},
                    3: {1, 2, 4, 8},
                    4: {8, 16},
                    6: {8, 16},
                }
                if bit_depth not in valid_depths.get(color_type, set()):
                    raise TopologyIconError("PNG color type or bit depth is invalid")
                interlace = chunk_data[12]
                if chunk_data[10] != 0 or chunk_data[11] != 0 or interlace not in {0, 1}:
                    raise TopologyIconError("PNG compression, filter, or interlace mode is invalid")
                saw_header = True
            elif chunk_type == b"IHDR":
                raise TopologyIconError("PNG may only contain one IHDR chunk")

            if chunk_type == b"IDAT":
                if idat_sequence_ended:
                    raise TopologyIconError("PNG IDAT chunks must be consecutive")
                if color_type == 3 and not saw_palette:
                    raise TopologyIconError("Indexed PNG files require a palette before image data")
                saw_image_data = True
                idat_chunks.append(chunk_data)
            elif saw_image_data and chunk_type != b"IEND":
                idat_sequence_ended = True
            if chunk_type == b"PLTE":
                if saw_image_data or saw_palette:
                    raise TopologyIconError("PNG palette must occur once before image data")
                saw_palette = True
            if chunk_type not in {b"IHDR", b"PLTE", b"IDAT", b"IEND"} and chunk_type[0] & 0x20 == 0:
                raise TopologyIconError("PNG contains an unsupported critical chunk")
            if chunk_type == b"IEND":
                if chunk_length != 0 or not saw_image_data or crc_end != len(content):
                    raise TopologyIconError("PNG IEND must follow image data and end the file")
                saw_end = True
                break
            offset = crc_end

        if not saw_header or not saw_image_data or not saw_end or width == 0 or height == 0:
            raise TopologyIconError("PNG is incomplete or has invalid dimensions")
        if width > MAX_RASTER_EDGE or height > MAX_RASTER_EDGE or width * height > MAX_RASTER_PIXELS:
            raise TopologyIconError("PNG dimensions must be at most 4096 pixels per edge and 16 megapixels")
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color_type]
        passes = (
            ((0, 0, 1, 1),)
            if interlace == 0
            else ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
        )
        decoded_size = 0
        scanline_sizes: list[int] = []
        for x_start, y_start, x_step, y_step in passes:
            pass_width = max(0, (width - x_start + x_step - 1) // x_step)
            pass_height = max(0, (height - y_start + y_step - 1) // y_step)
            if not pass_width or not pass_height:
                continue
            scanline_size = (pass_width * channels * bit_depth + 7) // 8
            scanline_sizes.extend([scanline_size] * pass_height)
            decoded_size += (scanline_size + 1) * pass_height
        if decoded_size > MAX_PNG_DECODED_BYTES:
            raise TopologyIconError("Decoded PNG content exceeds the 80 MiB processing limit")
        inflater = zlib.decompressobj()
        try:
            decoded = inflater.decompress(b"".join(idat_chunks), MAX_PNG_DECODED_BYTES + 1)
        except zlib.error as exc:
            raise TopologyIconError("PNG image data could not be decoded") from exc
        if len(decoded) != decoded_size or not inflater.eof or inflater.unconsumed_tail or inflater.unused_data:
            raise TopologyIconError("PNG image data is incomplete or has invalid dimensions")
        offset = 0
        for scanline_size in scanline_sizes:
            if decoded[offset] > 4:
                raise TopologyIconError("PNG scanline filter is invalid")
            offset += scanline_size + 1
        resolved_type = "image/png"
    else:
        raise TopologyIconError("Only SVG and PNG icon files are supported")

    return ValidatedTopologyIcon(
        device_type=normalized_type,
        name=normalized_name,
        filename_extension=filename_extension,
        content_type=resolved_type,
        content=content,
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _storage_service_for_provider(provider):
    if provider.source == "database":
        return build_storage_service(storage_config_id=provider.id)
    return build_storage_service(backend_name=provider.backend, bucket=provider.bucket or None)


def _icon_public_fields(row) -> dict[str, Any]:
    return {
        "id": str(row[0]),
        "device_type": str(row[1]),
        "name": str(row[2]),
        "content_type": str(row[3]),
        "content_url": f"/api/topology/icons/{row[0]}/content",
        "object_size": int(row[4]),
        "created_at": str(row[5]),
    }


def list_topology_icons() -> dict[str, Any]:
    conn = get_db_connection()
    try:
        icon_rows = conn.execute(
            """
            SELECT id, device_type, name, content_type, object_size, created_at
            FROM topology_device_icons
            ORDER BY device_type, created_at, name, id
            """
        ).fetchall()
        default_rows = conn.execute(
            "SELECT device_type, icon_id FROM topology_device_icon_defaults ORDER BY device_type"
        ).fetchall()
        override_rows = conn.execute(
            "SELECT device_id, device_type, icon_id FROM topology_device_icon_overrides ORDER BY device_id"
        ).fetchall()
        return {
            "icons": [_icon_public_fields(row) for row in icon_rows],
            "type_defaults": {str(row[0]): str(row[1]) for row in default_rows},
            "device_overrides": {
                str(row[0]): {"device_type": str(row[1]), "icon_id": str(row[2])}
                for row in override_rows
            },
        }
    finally:
        conn.close()


def create_topology_icon(
    *, device_type: str, name: str, filename: str, content_type: str | None,
    content: bytes, actor_id: str,
) -> dict[str, Any]:
    validated = validate_topology_icon_upload(
        device_type=device_type,
        name=name,
        filename=filename,
        content_type=content_type,
        content=content,
    )
    try:
        provider = effective_storage_provider()
        storage = _storage_service_for_provider(provider)
    except StorageError as exc:
        logger.warning("Could not initialize topology icon storage: %s", type(exc.__cause__ or exc).__name__)
        raise TopologyIconError("Topology icon storage is unavailable", 503) from exc

    icon_id = str(uuid.uuid4())
    object_key = f"topology/device-icons/{icon_id}/original.{validated.filename_extension}"
    try:
        stored = storage.put_stream(object_key, io.BytesIO(validated.content), validated.content_type)
    except (StorageError, OSError) as exc:
        cause = exc.__cause__ or exc
        logger.warning("Could not write topology icon to %s storage: %s", provider.backend, type(cause).__name__)
        if provider.backend == "s3" and isinstance(cause, ModuleNotFoundError):
            raise TopologyIconError("S3 topology icon storage requires boto3 on the server", 503) from exc
        if provider.backend == "s3" and type(cause).__name__ in {"EndpointConnectionError", "ConnectTimeoutError"}:
            raise TopologyIconError("Could not connect to S3 topology icon storage. Check the endpoint in Storage Settings.", 503) from exc
        raise TopologyIconError("Topology icon file could not be written to storage", 503) from exc

    created_at = _utc_now_iso()
    try:
        conn = get_db_connection()
        try:
            conn.execute(
                """
                INSERT INTO topology_device_icons (
                    id, device_type, name, content_type, storage_backend, storage_config_id,
                    storage_bucket, object_key, object_size, object_sha256, created_by, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    icon_id,
                    validated.device_type,
                    validated.name,
                    validated.content_type,
                    provider.backend,
                    provider.id,
                    provider.bucket if provider.backend == "s3" else "",
                    stored.object_key,
                    stored.size,
                    stored.sha256 or validated.sha256,
                    str(actor_id or ""),
                    created_at,
                ),
            )
            conn.commit()
            return {
                "id": icon_id,
                "device_type": validated.device_type,
                "name": validated.name,
                "content_type": validated.content_type,
                "content_url": f"/api/topology/icons/{icon_id}/content",
                "object_size": stored.size,
                "created_at": created_at,
            }
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as exc:
        logger.error("Could not save topology icon metadata: %s", type(exc).__name__)
        try:
            storage.delete(stored.object_key)
        except Exception as cleanup_exc:
            logger.error("Could not remove uploaded topology icon after database write failed: %s", type(cleanup_exc).__name__)
        raise TopologyIconError("Topology icon metadata could not be saved", 503) from exc


def get_topology_icon_content(icon_id: str) -> tuple[bytes, str]:
    conn = get_db_connection()
    try:
        try:
            row = conn.execute(
                """
                SELECT content_type, storage_backend, storage_config_id, storage_bucket,
                       object_key, object_size, object_sha256
                FROM topology_device_icons WHERE id = ?
                """,
                (str(icon_id),),
            ).fetchone()
        except Exception as exc:
            raise TopologyIconError("Topology icon metadata is unavailable", 503) from exc
    finally:
        conn.close()
    if not row:
        raise TopologyIconError("Topology icon was not found", 404)

    content_type, storage_backend, storage_config_id, bucket, object_key, expected_size, expected_sha256 = (
        str(row[0]), str(row[1]), str(row[2] or ""), str(row[3] or ""), str(row[4]), int(row[5]), str(row[6])
    )
    try:
        storage = (
            build_storage_service(storage_config_id=storage_config_id)
            if storage_config_id
            else build_storage_service(backend_name=storage_backend, bucket=bucket or None)
        )
        stream = storage.get_stream(object_key)
        try:
            content = stream.read(MAX_ICON_SIZE_BYTES + 1)
        finally:
            stream.close()
    except StorageError as exc:
        raise TopologyIconError("Topology icon content is unavailable", 503) from exc
    except Exception as exc:
        raise TopologyIconError("Topology icon content is unavailable", 503) from exc
    if len(content) != expected_size or len(content) > MAX_ICON_SIZE_BYTES:
        raise TopologyIconError("Topology icon content failed integrity checks", 503)
    if not hmac.compare_digest(hashlib.sha256(content).hexdigest(), expected_sha256):
        raise TopologyIconError("Topology icon content failed integrity checks", 503)
    return content, content_type


def set_topology_icon_default(*, device_type: str, icon_id: str | None, actor_id: str) -> None:
    normalized_type = _validate_device_type(device_type)
    conn = get_db_connection()
    try:
        if icon_id is None:
            conn.execute("DELETE FROM topology_device_icon_defaults WHERE device_type = ?", (normalized_type,))
            conn.commit()
            return
        _require_icon_type(conn, icon_id, normalized_type)
        conn.execute(
            """
            INSERT INTO topology_device_icon_defaults (device_type, icon_id, updated_by, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT (device_type) DO UPDATE SET
                icon_id = excluded.icon_id,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (normalized_type, str(icon_id), str(actor_id or ""), _utc_now_iso()),
        )
        conn.commit()
    except TopologyIconError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise TopologyIconError("Could not update the device type icon", 503) from exc
    finally:
        conn.close()


def set_topology_device_icon(
    *, device_id: str, device_type: str, icon_id: str | None, actor_id: str,
) -> None:
    normalized_type = _validate_device_type(device_type)
    conn = get_db_connection()
    try:
        device = conn.execute("SELECT id FROM devices WHERE id = ?", (str(device_id),)).fetchone()
        if not device:
            raise TopologyIconError("Device was not found", 404)
        if icon_id is None:
            conn.execute("DELETE FROM topology_device_icon_overrides WHERE device_id = ?", (str(device_id),))
            conn.commit()
            return
        _require_icon_type(conn, icon_id, normalized_type)
        conn.execute(
            """
            INSERT INTO topology_device_icon_overrides (
                device_id, device_type, icon_id, updated_by, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (device_id) DO UPDATE SET
                device_type = excluded.device_type,
                icon_id = excluded.icon_id,
                updated_by = excluded.updated_by,
                updated_at = excluded.updated_at
            """,
            (str(device_id), normalized_type, str(icon_id), str(actor_id or ""), _utc_now_iso()),
        )
        conn.commit()
    except TopologyIconError:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise TopologyIconError("Could not update the device icon", 503) from exc
    finally:
        conn.close()


def _require_icon_type(conn, icon_id: str, device_type: str) -> None:
    row = conn.execute(
        "SELECT device_type FROM topology_device_icons WHERE id = ?", (str(icon_id),)
    ).fetchone()
    if not row:
        raise TopologyIconError("Topology icon was not found", 404)
    if str(row[0]) != device_type:
        raise TopologyIconError("Icon device_type does not match the requested assignment", 422)


__all__ = [
    "DEVICE_TYPES",
    "MAX_ICON_SIZE_BYTES",
    "TopologyIconError",
    "create_topology_icon",
    "get_topology_icon_content",
    "list_topology_icons",
    "set_topology_device_icon",
    "set_topology_icon_default",
    "validate_topology_icon_upload",
]
