"""Reviewed vendor/model catalog used by product resolution and RAG scoping.

Templates describe CLI families, while this catalog records the concrete
switch models for which those families are applicable.  Keeping the model
identity in a small, reviewed registry prevents an S5130/S9825/Nexus query
from silently falling through to a different vendor's syntax.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

from ai.services.knowledge_service import _json_db_value, knowledge_service
from database import get_db_connection


MODEL_CATALOG: dict[str, tuple[dict[str, str], ...]] = {
    "Huawei": (
        {"model": "CloudEngine S5731-H24P4XC", "series": "S5731-H", "scope": "campus", "platform": "huawei_vrp_v200"},
        {"model": "CloudEngine S5731-H48T4XC-B", "series": "S5731-H", "scope": "campus", "platform": "huawei_vrp_v200"},
        {"model": "CloudEngine S5731-S48T4X", "series": "S5731-S", "scope": "campus", "platform": "huawei_vrp_v200"},
        {"model": "CloudEngine S5732-H48S6Q", "series": "S5732-H", "scope": "campus", "platform": "huawei_vrp_v200"},
        {"model": "CloudEngine S5735-L48P4X-A", "series": "S5735-L", "scope": "campus", "platform": "huawei_vrp_v600"},
        {"model": "CloudEngine S5735-S24P4XE-V2", "series": "S5735-S-V2", "scope": "campus", "platform": "huawei_vrp_v600"},
        {"model": "CloudEngine S5736-S48S4XC", "series": "S5736-S", "scope": "campus", "platform": "huawei_vrp_v200"},
        {"model": "CloudEngine S6730-S48X6Q", "series": "S6730-S", "scope": "campus", "platform": "huawei_vrp_v600"},
        {"model": "CloudEngine S6730-H48X6C", "series": "S6730-H", "scope": "campus", "platform": "huawei_vrp_v200"},
        {"model": "CloudEngine S6750-H36C", "series": "S6750-H", "scope": "campus", "platform": "huawei_vrp_v600"},
        {"model": "CE6885-48YS8CQ", "series": "CloudEngine 6800", "scope": "datacenter", "platform": "huawei_vrp_v300"},
        {"model": "CE8851-32CQ8DQ-K", "series": "CloudEngine 8800", "scope": "datacenter", "platform": "huawei_vrp_v300"},
        {"model": "CE9866-128DQ", "series": "CloudEngine 9800", "scope": "datacenter", "platform": "huawei_vrp_v300"},
        {"model": "XH16800-16", "series": "CloudEngine 16800", "scope": "datacenter", "platform": "huawei_vrp_v300"},
    ),
    "H3C": (
        {"model": "S5130S-28P-EI", "series": "S5130S", "scope": "campus", "platform": "h3c_comware"},
        {"model": "S5130S-52P-EI", "series": "S5130S", "scope": "campus", "platform": "h3c_comware"},
        {"model": "S5560X-30C-EI", "series": "S5560X", "scope": "campus", "platform": "h3c_comware"},
        {"model": "S5560X-54C-EI", "series": "S5560X", "scope": "campus", "platform": "h3c_comware"},
        {"model": "S6520X-26C-SI", "series": "S6520X", "scope": "campus", "platform": "h3c_comware"},
        {"model": "S6520X-54XC-UPWR-SI", "series": "S6520X", "scope": "campus", "platform": "h3c_comware"},
        {"model": "S7506E", "series": "S7500E", "scope": "campus", "platform": "h3c_comware"},
        {"model": "S6800-54QF", "series": "S6800", "scope": "datacenter", "platform": "h3c_comware"},
        {"model": "S6860-54HF", "series": "S6860", "scope": "datacenter", "platform": "h3c_comware"},
        # H3C's official S6850 support catalog is a distinct data-center
        # series; it must not be silently treated as S6800 or as a generic
        # Comware model when a query names S6850 explicitly.
        {"model": "S6850", "series": "S6850", "scope": "datacenter", "platform": "h3c_comware", "source_checked_at": "2026-09-04"},
        {"model": "S9825-64D", "series": "S9825", "scope": "datacenter", "platform": "h3c_comware"},
        {"model": "S9855", "series": "S9855", "scope": "datacenter", "platform": "h3c_comware"},
        {"model": "S10508X", "series": "S10500", "scope": "datacenter", "platform": "h3c_comware"},
    ),
    "Cisco": (
        {"model": "C9200L-24P-4G", "series": "Catalyst 9200", "scope": "campus", "platform": "cisco_iosxe"},
        {"model": "C9200-48P", "series": "Catalyst 9200", "scope": "campus", "platform": "cisco_iosxe"},
        # Cisco's official Catalyst 3850 data sheet lists the C3850 family
        # and its WS-C3850 hardware variants.  C3850 is the canonical
        # shorthand used by the query normalizer, while the series field
        # preserves the human-readable product family.
        {"model": "C3850", "series": "Catalyst 3850", "scope": "campus", "platform": "cisco_iosxe", "source_checked_at": "2026-09-04"},
        {"model": "C9300-24T", "series": "Catalyst 9300", "scope": "campus", "platform": "cisco_iosxe"},
        {"model": "C9300-48U", "series": "Catalyst 9300", "scope": "campus", "platform": "cisco_iosxe"},
        {"model": "C9350", "series": "C9350", "scope": "campus", "platform": "cisco_iosxe"},
        {"model": "Catalyst 9400", "series": "Catalyst 9400", "scope": "campus", "platform": "cisco_iosxe"},
        {"model": "C9550", "series": "C9550", "scope": "campus", "platform": "cisco_iosxe"},
        {"model": "Catalyst 9500", "series": "Catalyst 9500", "scope": "campus", "platform": "cisco_iosxe"},
        {"model": "C9610", "series": "C9610", "scope": "campus", "platform": "cisco_iosxe"},
        {"model": "Catalyst 9600", "series": "Catalyst 9600", "scope": "campus", "platform": "cisco_iosxe"},
        {"model": "N3K-C3172PQ-10GE", "series": "Nexus 3000", "scope": "datacenter", "platform": "cisco_nxos"},
        {"model": "N3K-C3232C", "series": "Nexus 3000", "scope": "datacenter", "platform": "cisco_nxos"},
        {"model": "N9K-C93180YC-FX", "series": "Nexus 9000", "scope": "datacenter", "platform": "cisco_nxos"},
        {"model": "N9K-C9364C", "series": "Nexus 9000", "scope": "datacenter", "platform": "cisco_nxos"},
        {"model": "Nexus 9000", "series": "Nexus 9000", "scope": "datacenter", "platform": "cisco_nxos"},
    ),
}


OFFICIAL_MODEL_REFERENCE = {
    # These are vendor-owned catalogs/documentation maps.  The entries above
    # are deliberately limited to names visible in these official sources;
    # we do not infer a SKU from a reseller or an unverified search result.
    "Huawei": "https://info.support.huawei.com/info-finder/encyclopedia/en/Switch.html",
    "H3C": "https://www.h3c.com/en/Products_and_Solutions/InterConnect/Switches/Products/",
    "Cisco": "https://www.cisco.com/c/en/us/products/switches/index.html",
}

OFFICIAL_MODEL_CHECKED_AT = "2026-08-23"

# The catalog is intentionally explicit about the evidence URL for every row.
# A series-level page is valid evidence when the vendor page lists the model
# in that series; exact hardware pages are used where the vendor publishes
# one.  No reseller, search-result, or inferred SKU URL is accepted here.
_OFFICIAL_MODEL_URL_OVERRIDES: dict[tuple[str, str], str] = {
    # Huawei exact product/support pages gathered from Huawei's official
    # Info-Finder and Enterprise support sites.
    ("Huawei", "CloudEngine S5735-S24P4XE-V2"): "https://info.support.huawei.com/info-finder/search-center/en/enterprise/Switches/cloudengine-s5735-s24p4xe-v2-pid-C00000015191/hardwarecenter",
    ("Huawei", "CE6885-48YS8CQ"): "https://support.huawei.com/enterprise/en/switches/ce6885-48ys8cq-pid-257795345?offeringId=252837181",
    ("Huawei", "CE8851-32CQ8DQ-K"): "https://support.huawei.com/enterprise/zh/doc/EDOC1100369508/afadd079",
    ("Huawei", "XH16800-16"): "https://support.huawei.com/enterprise/zh/switches/xh16800-16-pid-261324004",
    # H3C official product and hardware documentation pages.
    ("H3C", "S5130S-28P-EI"): "https://www.h3c.com/en/Support/Resource_Center/EN/Switches/Catalog/S5130S/S5130S-EI/Technical_Documents/Product_Literature/Hardware_Information___Specifications/H3C_S5130S-EI_IG/202306/1867335_294551_0.htm",
    ("H3C", "S5130S-52P-EI"): "https://www.h3c.com/en/Support/Resource_Center/EN/Switches/Catalog/S5130S/S5130S-EI/Technical_Documents/Product_Literature/Hardware_Information___Specifications/H3C_S5130S-EI_IG/202306/1867335_294551_0.htm",
    ("H3C", "S5560X-30C-EI"): "https://www.h3c.com/en/d_202502/2353307_294551_0.htm",
    ("H3C", "S5560X-54C-EI"): "https://www.h3c.com/en/d_202502/2353307_294551_0.htm",
    ("H3C", "S6520X-26C-SI"): "https://www.h3c.com/en/Products_and_Solutions/InterConnect/Switches/Products/Campus_Network/Aggregation/S6500/H3C_S6520X-SI/",
    ("H3C", "S6520X-54XC-UPWR-SI"): "https://www.h3c.com/en/Products_and_Solutions/InterConnect/Switches/Products/Campus_Network/Aggregation/S6500/H3C_S6520X-SI/",
    ("H3C", "S7506E"): "https://www.h3c.com/en/d_202502/2356236_294551_0.htm",
    ("H3C", "S6800-54QF"): "https://www.h3c.com/en/Support/Resource_Center/EN/Switches/Catalog/S6800/S6800/Technical_Documents/Product_Literature/Hardware_Information___Specifications/H3C_S6800_HIS/?CHID=1002659",
    ("H3C", "S6850"): "https://www.h3c.com/en/Support/Resource_Center/EN/Switches/Catalog/S6850/S6850/Default.htm?category=315791",
    ("H3C", "S6860-54HF"): "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Switches/00-Public/Product_Literature/Hardware_Information___Specifications/H3C_Data_Center_Fixed_Port_Swi-17390/202403/2059464_294551_0.htm",
    ("H3C", "S9825-64D"): "https://www.h3c.com/en/Support/Resource_Center/EN/Home/Public/00-Public/Technical_Documents/Product_Literature/Hardware_Information___Specifications/H3C_S9825_S9-14512/?CHID=1123124",
    ("H3C", "S9855"): "https://www.h3c.com/en/Products_and_Solutions/InterConnect/Switches/Products/Data_Center/Aggregation/S9800/H3C_S9855/",
    ("H3C", "S10508X"): "https://www.h3c.com/en/d_202305/1838346_294551_0.htm",
    # Cisco official model/series pages and public datasheets.
    ("Cisco", "C9200L-24P-4G"): "https://www.cisco.com/c/en/us/td/docs/switches/lan/catalyst9200/hardware/install/b-c9200-hig/product_overview.html",
    ("Cisco", "C9200-48P"): "https://www.cisco.com/c/en/us/products/collateral/switches/catalyst-9200-series-switches/nb-06-cat9200-ser-data-sheet-cte-en.html",
    ("Cisco", "C3850"): "https://www.cisco.com/c/en/us/products/collateral/switches/catalyst-3850-series-switches/data_sheet_c78-720918.html",
    ("Cisco", "C9300-24T"): "https://www.cisco.com/site/us/en/products/networking/switches/catalyst-9300-series-switches/index.html",
    ("Cisco", "C9300-48U"): "https://www.cisco.com/c/en/us/products/collateral/switches/catalyst-9300-series-switches/nb-06-cat9300-ser-data-sheet-cte-en.html",
    ("Cisco", "N3K-C3172PQ-10GE"): "https://www.cisco.com/c/en/us/products/collateral/switches/nexus-3000-series-switches/data_sheet_c78-729483.html",
    ("Cisco", "N3K-C3232C"): "https://www.cisco.com/c/en/us/products/switches/nexus-3000-series-switches/datasheet-listing.html",
    ("Cisco", "N9K-C93180YC-FX"): "https://www.cisco.com/c/en/us/support/switches/nexus-93180yc-fx-switch/model.html",
    ("Cisco", "N9K-C9364C"): "https://www.cisco.com/c/en/us/products/switches/nexus-9000-series-switches/datasheet-listing.html",
    ("Cisco", "Nexus 9000"): "https://www.cisco.com/c/en/us/support/switches/nexus-9000-series-switches/series.html",
}


def _official_model_url(vendor: str, item: dict[str, str]) -> str:
    return _OFFICIAL_MODEL_URL_OVERRIDES.get((vendor, item["model"]), OFFICIAL_MODEL_REFERENCE[vendor])


for _vendor, _rows in MODEL_CATALOG.items():
    for _row in _rows:
        _row.setdefault("official_url", _official_model_url(_vendor, _row))
        _row.setdefault("verification_level", "official_model_or_series_catalog")
        _row.setdefault("source_checked_at", OFFICIAL_MODEL_CHECKED_AT)


def vendor_models(vendor: str, *, scope: str | None = None) -> list[dict[str, str]]:
    rows = [dict(item) for item in MODEL_CATALOG.get(str(vendor), ())]
    if scope:
        rows = [item for item in rows if item.get("scope") == scope]
    return rows


def all_vendor_model_names(vendor: str) -> list[str]:
    return [item["model"] for item in vendor_models(vendor)]


def model_aliases(item: dict[str, str]) -> list[str]:
    """Return searchable spellings without inventing a different model.

    Huawei's official names often carry the ``CloudEngine`` product prefix,
    while operators type the hardware token (for example ``S5731-H``).  Both
    spellings refer to the same reviewed row; the bare token is an alias, not
    a new SKU.
    """

    model = str(item.get("model") or "").strip()
    values = [model]
    if model.lower().startswith("cloudengine "):
        values.append(model[len("CloudEngine "):])
    return list(dict.fromkeys(value for value in values if value))


def _safe_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _reviewed_os_family(vendor: str, platform: str) -> str:
    """Return the reviewed OS family used by the model catalog boundary."""
    if vendor == "Huawei":
        return "VRP"
    if vendor == "H3C":
        return "Comware 7"
    return "NX-OS" if platform == "cisco_nxos" else "IOS-XE"


def _existing_registry_ids(tenant_id: str) -> set[str]:
    ids: set[str] = set()
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT name, product_model, metadata_json FROM ai_document
            WHERE (tenant_id = ? OR tenant_id = 'tenant-default' OR tenant_id IS NULL)
            """,
            (tenant_id,),
        ).fetchall()
    for row in rows:
        name = str(row[0] if not hasattr(row, "keys") else row["name"] or "")
        scalar_model = str(row[1] if not hasattr(row, "keys") else row["product_model"] or "")
        raw = row[2] if not hasattr(row, "keys") else row["metadata_json"]
        if isinstance(raw, dict):
            metadata = raw
        else:
            try:
                metadata = json.loads(raw or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                metadata = {}
        identity = metadata.get("catalog_identity") if isinstance(metadata, dict) else None
        if identity:
            ids.add(str(identity))
        # Existing Huawei imports predate the dedicated ``product_registry``
        # source type and are stored as ``user_document`` with a hardware
        # metadata marker.  Treat those rows as the same official identity so
        # startup backfill is idempotent and does not duplicate the corpus.
        if isinstance(metadata, dict) and (
            str(metadata.get("document_type") or "").lower() in {"product_registry", "hardware_manual"}
            or "product_registry" in name.lower()
        ):
            vendor = str(metadata.get("vendor") or "").strip()
            models = metadata.get("product_models") or metadata.get("applicable_product_models") or []
            if not isinstance(models, (list, tuple)):
                models = [models]
            if scalar_model:
                models = list(models) + [scalar_model]
            for model in models:
                if vendor and str(model).strip():
                    ids.add(f"{vendor}:{str(model).strip()}")
    return ids


def _refresh_existing_registry_document(
    *,
    tenant_id: str,
    identity: str,
    name: str,
    vendor: str,
    platform: str,
    reference: str,
    metadata: dict[str, Any],
) -> bool:
    """Refresh provenance for a previously seeded model row in place.

    The first registry release used one vendor landing page for every model.
    Updating the existing row avoids duplicate documents while making the new
    per-model official evidence visible immediately in PostgreSQL.
    """
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, metadata_json FROM ai_document "
            "WHERE tenant_id = ? AND (name = ? OR CAST(metadata_json AS TEXT) LIKE ? ) "
            "ORDER BY id LIMIT 1",
            (tenant_id, name, f"%{identity}%"),
        ).fetchone()
        if not row:
            return False
        row_id = str(row[0] if not hasattr(row, "keys") else row["id"])
        raw = row[1] if not hasattr(row, "keys") else row["metadata_json"]
        try:
            existing_metadata = raw if isinstance(raw, dict) else json.loads(raw or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            existing_metadata = {}
        if not isinstance(existing_metadata, dict):
            existing_metadata = {}
        merged = dict(existing_metadata)
        merged.update(metadata)
        assignments = [
            "source = ?",
            "vendor = ?",
            "platform = ?",
            "knowledge_source_type = ?",
            "source_trust_level = ?",
            "metadata_json = ?",
        ]
        values: list[Any] = [
            reference,
            vendor,
            platform,
            "official_url",
            "official",
            _json_db_value(merged),
        ]
        # Older registry rows may have generic or stale semantic columns even
        # after their JSON metadata is refreshed.  Reconcile the indexed
        # columns as well so query resolution sees the same reviewed contract.
        for column in ("product_series", "product_model", "os_family", "os_generation", "cli_platform"):
            if column in metadata:
                assignments.append(f"{column} = ?")
                values.append(metadata[column])
        values.extend((row_id, tenant_id))
        conn.execute(
            f"UPDATE ai_document SET {', '.join(assignments)} "
            "WHERE id = ? AND tenant_id = ?",
            values,
        )
        return True


def ensure_official_product_registry_documents(
    *,
    tenant_id: str = "tenant-default",
    created_by: str = "system",
) -> dict[str, Any]:
    """Publish one searchable product-identity record for every reviewed model."""

    knowledge_base = knowledge_service.get_or_create_default_knowledge_base(
        tenant_id=tenant_id,
        created_by=created_by,
    )
    existing = _existing_registry_ids(tenant_id)
    published: list[dict[str, str]] = []
    for vendor, rows in MODEL_CATALOG.items():
        for item in rows:
            model = item["model"]
            identity = f"{vendor}:{model}"
            registry_name = f"{vendor}.{_safe_key(model)}.product_registry.model"
            if identity in existing:
                reference = str(item.get("official_url") or OFFICIAL_MODEL_REFERENCE[vendor])
                aliases = model_aliases(item)
                refreshed_metadata = {
                    "vendor": vendor,
                    "product_series": item["series"],
                    "product_model": model,
                    "applicable_product_models": aliases,
                    "applicable_product_series": [item["series"]],
                    "os_family": _reviewed_os_family(vendor, item["platform"]),
                    "cli_platform": item["platform"],
                    "scope": item["scope"],
                    "official_reference": reference,
                    "canonical_url": reference,
                    "source_checked_at": OFFICIAL_MODEL_CHECKED_AT,
                    "verification_level": item.get("verification_level") or "official_model_or_series_catalog",
                    "official_source_kind": "vendor_model_or_series_page",
                    "official_source_locator": model,
                    "catalog_identity": identity,
                }
                _refresh_existing_registry_document(
                    tenant_id=tenant_id,
                    identity=identity,
                    name=registry_name,
                    vendor=vendor,
                    platform=item["platform"],
                    reference=reference,
                    metadata=refreshed_metadata,
                )
                continue
            reference = str(item.get("official_url") or OFFICIAL_MODEL_REFERENCE[vendor])
            aliases = model_aliases(item)
            metadata = {
                "schema_version": "1.0",
                "document_id": f"product-registry-{_safe_key(vendor)}-{_safe_key(model)}",
                "title": f"{vendor} {model} product registry",
                "vendor": vendor,
                "product_type": "network_switch",
                "document_category": "hardware",
                "source_type": "product_registry",
                "official_only": True,
                "status": "active",
                "document_type": "product_registry",
                "product_family": "campus_switch" if item["scope"] == "campus" else "datacenter_switch",
                "product_series": item["series"],
                "product_model": model,
                "applicable_product_models": aliases,
                "applicable_product_series": [item["series"]],
                "os_family": _reviewed_os_family(vendor, item["platform"]),
                "cli_platform": item["platform"],
                "scope": item["scope"],
                "verification_level": item.get("verification_level") or "official_model_or_series_catalog",
                "rag_priority": 90,
                "source_trust_level": "official",
                "official_reference": reference,
                "canonical_url": reference,
                "catalog_identity": identity,
                "source_checked_at": OFFICIAL_MODEL_CHECKED_AT,
                "official_source_kind": "vendor_model_or_series_page",
                "official_source_locator": model,
                "model_aliases_are_not_skus": True,
            }
            content = (
                f"{vendor} {model}\n"
                f"系列：{item['series']}\n"
                f"网络范围：{'园区网' if item['scope'] == 'campus' else '数据中心'}\n"
                f"CLI 平台：{item['platform']}\n"
                f"官方产品目录：{reference}\n"
                f"核验日期：{OFFICIAL_MODEL_CHECKED_AT}（仅采用厂商官网列出的系列/型号）\n"
                f"官方来源类型：{metadata['official_source_kind']}；来源定位型号：{model}"
            )
            result = knowledge_service.add_document_and_chunk(
                knowledge_base_id=str(knowledge_base["id"]),
                name=registry_name,
                content=content,
                vendor=vendor,
                platform=item["platform"],
                # ``official_url`` keeps the row inside the existing official
                # knowledge scope.  The semantic ``document_type`` remains
                # product_registry so the resolver can identify it.
                knowledge_source_type="official_url",
                chunk_size=500,
                tenant_id=tenant_id,
                source_trust_level="official",
                metadata=metadata,
                source=reference,
            )
            published.append({"vendor": vendor, "model": model, "document_id": str(result.get("document_id") or "")})
            existing.add(identity)
    return {
        "tenant_id": tenant_id,
        "knowledge_base_id": str(knowledge_base["id"]),
        "published": published,
        "published_count": len(published),
        "model_counts": {vendor: len(rows) for vendor, rows in MODEL_CATALOG.items()},
    }


__all__ = [
    "MODEL_CATALOG",
    "OFFICIAL_MODEL_REFERENCE",
    "all_vendor_model_names",
    "ensure_official_product_registry_documents",
    "vendor_models",
    "model_aliases",
    "OFFICIAL_MODEL_CHECKED_AT",
]
