"""Conservative Product Registry/Alias resolver for knowledge retrieval."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from database.core import get_db_connection
from ai.services.knowledge_metadata import parse_markdown_document
from ai.services.document_entity_resolution import resolve_document_entities


@dataclass
class EntityResolution:
    metadata: Dict[str, Any]
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    platform_candidates: List[str] = field(default_factory=list)
    ambiguous: bool = False
    evidence: str = "none"
    outcome: str = "legacy"
    retrieval_eligible: bool = True
    driver_selection_allowed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata,
            "candidates": self.candidates,
            "candidate_count": len(self.candidates),
            "platform_candidates": self.platform_candidates,
            "ambiguous": self.ambiguous,
            "evidence": self.evidence,
            "outcome": self.outcome,
            "retrieval_eligible": self.retrieval_eligible,
            "driver_selection_allowed": self.driver_selection_allowed,
        }


class ProductResolver:
    SERIES_ALIASES = {
        "ce68": "CloudEngine 6800",
        "ce6800": "CloudEngine 6800",
        "ce68xx": "CloudEngine 6800",
        "cloudengine6800": "CloudEngine 6800",
        "cloudengine 6800": "CloudEngine 6800",
    }

    @classmethod
    def _canonical_series(cls, value: Any) -> Optional[str]:
        if not value:
            return None
        raw = str(value).strip()
        return cls.SERIES_ALIASES.get(raw.lower().replace("-", ""), cls.SERIES_ALIASES.get(raw.lower(), raw))

    @staticmethod
    def _series_matches(requested: Optional[str], candidate: Optional[str]) -> bool:
        """Match exact series names and short S57-style family prefixes."""
        if not requested:
            return True
        requested_text = str(requested).strip().lower()
        candidate_text = str(candidate or "").strip().lower()
        if requested_text == candidate_text:
            return True
        # A bare S-number is an operator search prefix, not a complete model.
        # It may therefore match S5731/S5735/S5755 variants in the registry.
        return bool(re.fullmatch(r"s\d{2,4}", requested_text) and candidate_text.startswith(requested_text))

    @staticmethod
    def _json(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(str(value or "{}"))
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    def resolve(self, metadata: Dict[str, Any], *, tenant_id: str = "tenant-default") -> EntityResolution:
        v2_resolution = resolve_document_entities(metadata, tenant_id=tenant_id)
        if v2_resolution.catalog_ready:
            return EntityResolution(
                metadata=dict(v2_resolution.retrieval_filters or v2_resolution.metadata),
                candidates=[dict(item) for item in v2_resolution.candidates],
                platform_candidates=v2_resolution.platform_candidates,
                ambiguous=v2_resolution.ambiguous or v2_resolution.outcome.value in {"unknown", "conflict"},
                evidence=f"v2:{v2_resolution.outcome.value}",
                outcome=v2_resolution.outcome.value,
                retrieval_eligible=v2_resolution.retrieval_eligible,
                driver_selection_allowed=v2_resolution.driver_selection_allowed,
            )
        normalized = dict(metadata or {})
        series = self._canonical_series(normalized.get("product_series") or normalized.get("product_model"))
        if series:
            normalized["product_series"] = series

        candidates: list[dict[str, Any]] = []
        platforms: set[str] = set()
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM ai_document "
                    "WHERE status = 'active' "
                    "AND (tenant_id = ? OR tenant_id = 'tenant-default' OR tenant_id IS NULL) "
                    "ORDER BY id",
                    (tenant_id or "tenant-default",),
                )
                descriptions = [str(item[0]) for item in (cursor.description or [])]
                for row in cursor.fetchall():
                    item = dict(zip(descriptions, row))
                    raw_meta = self._json(item.get("metadata_json"))
                    is_registry = "product_registry" in str(item.get("name") or "").lower() or str(raw_meta.get("document_type") or "").lower() in {"hardware_manual", "product_registry"}
                    if not is_registry:
                        continue
                    row_series = item.get("product_series") or raw_meta.get("product_series") or raw_meta.get("technical_series")
                    row_models = raw_meta.get("product_models") or raw_meta.get("applicable_product_models") or []
                    row_model = item.get("product_model") or (row_models[0] if isinstance(row_models, list) and len(row_models) == 1 else None)
                    row_platform = item.get("cli_platform") or raw_meta.get("cli_platform")
                    row_train = item.get("software_train") or raw_meta.get("software_train")
                    if not row_series:
                        try:
                            parsed = parse_markdown_document(item.get("normalized_content") or "")
                            row_meta = parsed.metadata
                            row_series = row_meta.get("product_series") or row_meta.get("technical_series")
                            row_platform = row_platform or row_meta.get("cli_platform")
                            row_train = row_train or row_meta.get("software_train")
                        except Exception:
                            pass
                    canonical_row_series = self._canonical_series(row_series)
                    if series and not self._series_matches(series, canonical_row_series):
                        continue
                    if normalized.get("vendor") and str(item.get("vendor") or raw_meta.get("vendor") or "").lower() != str(normalized["vendor"]).lower():
                        continue
                    if normalized.get("software_train") and str(row_train or "").upper() != str(normalized["software_train"]).upper():
                        continue
                    candidate = {
                        "document_id": item.get("id"),
                        "document_name": item.get("name"),
                        "product_series": canonical_row_series or row_series,
                        "product_model": row_model,
                        "software_train": row_train,
                        "cli_platform": row_platform,
                    }
                    candidates.append(candidate)
                    if row_platform:
                        platforms.add(str(row_platform))
        except Exception:
            # Resolver is advisory; retrieval still uses explicit fields from
            # the parser when the registry is temporarily unavailable.
            candidates = []

        explicit_platform = bool(normalized.get("cli_platform"))
        has_product_identity = bool(series or normalized.get("product_model"))
        requires_clarification = False
        if len(platforms) == 1 and not explicit_platform and has_product_identity:
            # A product registry identity plus its software boundary is valid
            # evidence.  A software train by itself is not a device identity:
            # V200/V300/V600 describe software lines, not hardware models.
            normalized["cli_platform"] = next(iter(platforms))
            evidence = "product_registry"
        elif len(platforms) == 1 and not explicit_platform:
            evidence = "product_registry_insufficient_identity"
            requires_clarification = True
        elif len(platforms) > 1 and not explicit_platform:
            evidence = "product_registry_ambiguous"
            requires_clarification = True
        elif candidates:
            evidence = "product_registry"
        else:
            evidence = "alias_only" if series else "none"
        return EntityResolution(
            metadata=normalized,
            # Keep debug/context payloads bounded while retaining all platform
            # candidates used for ambiguity detection above.
            candidates=candidates[:50],
            platform_candidates=sorted(platforms),
            ambiguous=requires_clarification,
            evidence=evidence,
            outcome="legacy",
            retrieval_eligible=True,
            driver_selection_allowed=False,
        )


product_resolver = ProductResolver()
