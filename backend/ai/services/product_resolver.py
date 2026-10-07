"""Conservative Product Registry/Alias resolver for knowledge retrieval."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from database.core import get_db_connection
from ai.services.knowledge_metadata import parse_markdown_document
from ai.services.document_entity_resolution import resolve_document_entities
from ai.services.product_alias_service import normalize_alias, trigram_similarity
from ai.services.query_normalizer import NormalizedQuery, normalize_query


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
    match_method: str = "none"
    match_score: float | None = None
    normalized_query: str | None = None

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
            "match_method": self.match_method,
            "match_score": self.match_score,
            "normalized_query": self.normalized_query,
        }


class ProductResolver:
    SERIES_ALIASES = {
        "ce68": "CloudEngine 6800",
        "ce6800": "CloudEngine 6800",
        "ce68xx": "CloudEngine 6800",
        "cloudengine6800": "CloudEngine 6800",
        "cloudengine 6800": "CloudEngine 6800",
    }

    _MODEL_ALIASES = {
        "ce6885": ("ce6885", "ce6885-48ys8cq", "ce6885 48ys8cq"),
        "c9300": ("c9300", "catalyst93", "catalyst 9300", "catalyst9300"),
        # Catalyst 3850 is a reviewed IOS-XE catalog family.  Keep the
        # hardware token and the common WS-C spelling together so a C3850
        # query does not fall through to a fuzzy C9300 candidate.
        "c3850": ("c3850", "catalyst 3850", "catalyst3850", "ws-c3850"),
        "rg-s6220": ("rg-s6220", "rg s6220", "rg-s6220-48xs4qxs", "rg-s6220-48xt4qxs"),
        "s5735-l-v2": ("s5735-l-v2", "s5735 l v2"),
        "s6520x": ("s6520x", "s6520 x"),
        # S6850 is an explicitly reviewed H3C data-center model.  Keep it in
        # the shadow resolver so product resolution remains deterministic even
        # before the runtime product-registry projection has been refreshed.
        "s6850": ("s6850",),
    }

    _REVIEWED_MODEL_METADATA = {
        "s6850": {
            "vendor": "H3C",
            "os_family": "Comware 7",
            "os_generation": "COMWARE-7",
            "cli_platform": "h3c_comware",
            "document_type": "product_registry",
        },
        "rg-s6220": {
            "vendor": "Ruijie",
            "os_family": "RGOS",
            "os_generation": "RGOS-10/11",
            "cli_platform": "ruijie_rgos",
            "document_type": "product_registry",
        },
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
    def _normalise_os_family(value: Any) -> str:
        return re.sub(r"[\s_-]+", "", str(value or "").strip().casefold())

    @classmethod
    def _os_family_compatible(cls, requested: Any, candidate: Any) -> bool:
        """Allow only reviewed base-family to concrete-family inheritance."""
        requested_token = cls._normalise_os_family(requested)
        candidate_token = cls._normalise_os_family(candidate)
        if not requested_token or not candidate_token:
            return False
        if requested_token == candidate_token:
            return True
        # A generic Comware/VRP token may bind to a reviewed numeric family,
        # but arbitrary families must still match exactly.
        if requested_token not in {"comware", "vrp"}:
            return False
        suffix = candidate_token[len(requested_token):] if candidate_token.startswith(requested_token) else ""
        return bool(suffix and suffix.isdigit())

    @classmethod
    def _reviewed_registry_os_family(cls, resolution: EntityResolution) -> Optional[str]:
        """Return one concrete OS family supplied by a unique registry row."""
        requested = resolution.metadata.get("os_family")
        registry_candidates = [
            item
            for item in resolution.candidates
            if str(item.get("document_type") or "").casefold() == "product_registry"
        ]
        families = {
            str(item.get("os_family") or "").strip()
            for item in registry_candidates
            if item.get("os_family")
        }
        if len(registry_candidates) != 1 or len(families) != 1:
            return None
        candidate = next(iter(families))
        return candidate if cls._os_family_compatible(requested, candidate) else None

    @staticmethod
    def _json(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        try:
            parsed = json.loads(str(value or "{}"))
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}

    @classmethod
    def _query_alias_candidates(cls, query: str, *, tenant_id: str) -> list[dict[str, Any]]:
        """Resolve reviewed aliases without choosing across a conflict.

        The physical DB-006 catalog remains release-gated.  This adapter uses
        the reviewed alias map as a deterministic shadow resolver and returns
        bounded candidates; it never authorizes a driver or a write action.
        """
        normalized = normalize_alias(query)
        candidates: list[dict[str, Any]] = []
        def series_for(model: str) -> str:
            if model.lower().startswith("ce6"):
                return "CloudEngine 6800"
            if model.lower().startswith("c9300"):
                return "Catalyst 9300"
            if model.lower().startswith("c3850"):
                return "Catalyst 3850"
            if model.lower().startswith("rg-s6220"):
                return "RG-S6220"
            return cls._canonical_series(model) or model
        for model, aliases in cls._MODEL_ALIASES.items():
            normalized_aliases = {normalize_alias(alias) for alias in aliases}
            if normalized in normalized_aliases:
                # Keep the reviewed SKU when the operator supplied the full
                # alias (for example ``CE6885-48YS8CQ``).  The short alias
                # ``CE6885`` intentionally retains the legacy canonical key
                # because it is a series/model prefix in older catalog rows.
                # Returning the full alias here lets SQL match the exact
                # hardware ``product_model`` without changing that legacy
                # resolver contract.
                base_alias = normalize_alias(model)
                candidate_model = model
                for alias in aliases:
                    alias_text = normalize_alias(alias)
                    if (
                        alias_text == normalized
                        and alias_text.startswith(f"{base_alias} ")
                        and re.search(r"\s+\d", alias_text)
                    ):
                        # Prefer the SKU spelling with its dash when both
                        # dashed and space-separated aliases normalize to the
                        # same identity.
                        candidate_model = str(alias).strip().lower()
                        if "-" in str(alias):
                            break
                candidates.append({
                    "tenant_id": tenant_id,
                    "product_model": candidate_model,
                    "product_series": series_for(model),
                    "alias": query,
                    "match_method": "exact" if normalized == normalize_alias(aliases[0]) else "canonical",
                    "match_score": 1.0,
                    **cls._REVIEWED_MODEL_METADATA.get(model, {}),
                })
                continue
            if any(alias.startswith(normalized) or normalized.startswith(alias) for alias in normalized_aliases if len(normalized) >= 2):
                candidates.append({
                    "tenant_id": tenant_id,
                    "product_model": model,
                    "product_series": series_for(model),
                    "alias": query,
                    "match_method": "prefix",
                    "match_score": 0.80,
                    **cls._REVIEWED_MODEL_METADATA.get(model, {}),
                })
                continue
            score = max((trigram_similarity(normalized, alias) for alias in normalized_aliases), default=0.0)
            if score >= 0.58:
                candidates.append({
                    "tenant_id": tenant_id,
                    "product_model": model,
                    "product_series": series_for(model),
                    "alias": query,
                    "match_method": "trigram",
                    "match_score": score,
                    **cls._REVIEWED_MODEL_METADATA.get(model, {}),
                })
        return sorted(candidates, key=lambda item: (-float(item["match_score"]), str(item["product_model"])))[:20]

    @classmethod
    def _metadata_from_normalized(cls, normalized: NormalizedQuery) -> dict[str, Any]:
        """Project the normalizer contract into RetrievalRequest metadata."""
        return {
            "vendor": normalized.vendor,
            "product_series": normalized.product,
            "product_model": normalized.model,
            "os_family": normalized.os_family,
            "os_generation": normalized.generation,
            "software_train": normalized.version if (normalized.version or "").upper().startswith("V") else None,
            "software_release": normalized.version if normalized.version and ("R" in normalized.version.upper() or "." in normalized.version) else None,
            "feature": normalized.topic,
            "feature_domain": (
                "routing" if normalized.topic in {"ospf", "bgp", "arp", "static_route", "loopback"}
                else "switching" if normalized.topic in {"vlan", "stp", "lldp", "access_port", "trunk", "lacp"}
                else "overlay" if normalized.topic in {"evpn", "vxlan"}
                else "security" if normalized.topic == "acl"
                else "management" if normalized.topic in {"ntp", "snmp", "ssh"}
                else "reliability" if normalized.topic in {"vrrp"}
                else None
            ),
            "document_category": normalized.document_category,
            "cli_platform": None,
        }

    def resolve_query(
        self,
        query: str,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        tenant_id: str = "tenant-default",
    ) -> EntityResolution:
        """Resolve an operator query with exact/canonical/prefix/trigram evidence."""
        normalized = normalize_query(query, tenant_id=tenant_id)
        projected = self._metadata_from_normalized(normalized)
        merged = {key: value for key, value in projected.items() if value not in (None, "")}
        merged.update({key: value for key, value in dict(metadata or {}).items() if value not in (None, "")})
        # A concrete model token is preferred.  A reviewed family alias such
        # as ``Catalyst 9300`` is also a canonical resolver identity (the
        # catalog maps it to the c9300 family); CloudEngine 6800 remains a
        # series-only scope unless a CE SKU is present.
        identity_query = normalized.model or (
            normalized.product if normalized.product != "CloudEngine 6800" else None
        )
        candidates = self._query_alias_candidates(identity_query or query, tenant_id=tenant_id) if identity_query else []
        # An exact/canonical identity must not become ambiguous merely because
        # a neighbouring product happens to clear the fuzzy trigram threshold
        # (for example Catalyst 3850 versus Catalyst 9300).  Preserve the full
        # candidate list for diagnostics, but use same-strength candidates for
        # the identity decision.
        identity_candidates = candidates
        if candidates and str(candidates[0].get("match_method") or "") in {"exact", "canonical"}:
            identity_candidates = [
                item for item in candidates
                if str(item.get("match_method") or "") in {"exact", "canonical"}
            ]
        identity_models = {str(item.get("product_model")) for item in identity_candidates}
        match_method = str(candidates[0].get("match_method") or "none") if candidates else "none"
        match_score = float(candidates[0].get("match_score")) if candidates else None
        ambiguous = len(identity_models) > 1 or match_method in {"prefix", "trigram"}
        if len(identity_models) == 1 and match_method in {"exact", "canonical"} and not next(iter(identity_models), "").lower().startswith("s"):
            winner = candidates[0]
            merged["product_series"] = winner.get("product_series")
            merged["product_model"] = winner.get("product_model")
        if len(identity_models) == 1 and not merged.get("cli_platform"):
            winner = candidates[0]
            if winner.get("cli_platform"):
                # A reviewed shadow row may provide the parser family while
                # the durable product-registry projection is being refreshed.
                # This is still advisory metadata and never authorizes a
                # driver or write operation.
                merged["cli_platform"] = winner["cli_platform"]
        if identity_models and next(iter(identity_models), "").lower().startswith("s") and match_method == "exact":
            # S-series identifiers are hierarchy scopes in the reviewed
            # catalog; an exact series alias is still candidate-only until a
            # concrete model row is selected.
            match_method = "prefix"
            ambiguous = True
        result = self.resolve(merged, tenant_id=tenant_id)
        result.candidates = candidates[:20] or result.candidates
        result.ambiguous = result.ambiguous or ambiguous
        result.match_method = match_method if candidates else result.evidence
        result.match_score = match_score
        result.normalized_query = normalized.normalized_text
        reviewed_os_family = self._reviewed_registry_os_family(result)
        if reviewed_os_family:
            # This enriches retrieval metadata from the exact product registry
            # row only; it does not authorize a driver or device operation.
            result.metadata["os_family"] = reviewed_os_family
        if candidates and match_method in {"prefix", "trigram"}:
            result.outcome = "candidates"
            result.retrieval_eligible = result.retrieval_eligible and len(identity_models) <= 1
            # A short/fuzzy model alias is still ambiguous even when every
            # current candidate happens to share one CLI platform.  Platform
            # agreement prevents cross-dialect mixing, but it does not prove
            # that a concrete hardware SKU was selected; S57 must not silently
            # become S5735 (or another future S57 variant).
        return result

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
        # A vendor-only query is not a product identity.  Do not turn every
        # model registered for that vendor into an ambiguous match; doing so
        # would manufacture a product-registry decision for an intentionally
        # unknown model such as ``Huawei unknown-9000``.
        if series or normalized.get("product_model"):
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
                        row_os_family = item.get("os_family") or raw_meta.get("os_family")
                        row_os_generation = item.get("os_generation") or raw_meta.get("os_generation")
                        document_type = str(raw_meta.get("document_type") or "").strip().casefold()
                        if not row_series:
                            try:
                                parsed = parse_markdown_document(item.get("normalized_content") or "")
                                row_meta = parsed.metadata
                                row_series = row_meta.get("product_series") or row_meta.get("technical_series")
                                row_platform = row_platform or row_meta.get("cli_platform")
                                row_train = row_train or row_meta.get("software_train")
                                row_os_family = row_os_family or row_meta.get("os_family")
                                row_os_generation = row_os_generation or row_meta.get("os_generation")
                                document_type = document_type or str(row_meta.get("document_type") or "").strip().casefold()
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
                            "os_family": row_os_family,
                            "os_generation": row_os_generation,
                            "document_type": "product_registry" if "product_registry" in str(item.get("name") or "").lower() else document_type,
                        }
                        candidates.append(candidate)
                        if row_platform:
                            platforms.add(str(row_platform))
            except Exception:
                # Resolver is advisory; retrieval still uses explicit fields
                # from the parser when the registry is temporarily unavailable.
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
