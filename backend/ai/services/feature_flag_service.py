"""Deterministic Feature Flag and Rollout Service for Knowledge Engine V2.

This module implements MIG-011, MIG-012, and MIG-013:
- Role-based and user-whitelisted V2 enablement (MIG-011)
- Staged gradual rollout (Admin -> Pilot -> Site -> Percentage) (MIG-012)
- Zero-downtime hot-switching and emergency circuit-breaking without DB rollback (MIG-013)
"""

from __future__ import annotations

import hashlib
import threading
from typing import Any, Mapping, Sequence

from core.config import settings


class KnowledgeFeatureFlagService:
    """Thread-safe feature flag decision engine with runtime override support."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runtime_overrides: dict[str, Any] = {}

    def set_runtime_override(self, key: str, value: Any) -> None:
        with self._lock:
            self._runtime_overrides[key] = value

    def clear_runtime_overrides(self) -> None:
        with self._lock:
            self._runtime_overrides.clear()

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._runtime_overrides:
                return self._runtime_overrides[key]
        return getattr(settings, key, default)

    def evaluate_v2_access(
        self,
        user_context: Mapping[str, Any] | None = None,
        *,
        request_override: bool | None = None,
    ) -> tuple[bool, str, dict[str, Any]]:
        """Evaluate whether a request or user should use Knowledge Engine V2.

        Returns:
            (is_enabled, reason, metadata)
        """
        if request_override is not None:
            return (
                bool(request_override),
                "explicit_request_override",
                {"requested": request_override},
            )

        context = dict(user_context or {})
        tenant_id = str(context.get("tenant_id") or "tenant-default").strip()
        user_id = str(context.get("user_id") or context.get("username") or "").strip()
        roles = {
            str(r).strip().lower()
            for r in (context.get("roles") or [])
            if str(r).strip()
        }
        if "role" in context and context["role"]:
            roles.add(str(context["role"]).strip().lower())

        site_ids = {
            str(s).strip()
            for s in (context.get("site_ids") or [])
            if str(s).strip()
        }
        if "site_id" in context and context["site_id"]:
            site_ids.add(str(context["site_id"]).strip())

        global_enabled = bool(self.get_setting("KNOWLEDGE_V2_ENABLED", False))
        if not global_enabled:
            return (
                False,
                "global_disabled",
                {
                    "global_enabled": False,
                    "shadow_enabled": bool(self.get_setting("KNOWLEDGE_V2_SHADOW_READ", False)),
                },
            )

        # 1. Admin & Pilot Role Gate (MIG-011)
        pilot_roles = {
            str(r).strip().lower()
            for r in self.get_setting("KNOWLEDGE_V2_PILOT_ROLES", ["admin", "knowledge_admin"])
            if str(r).strip()
        }
        matched_roles = roles & pilot_roles
        if matched_roles:
            return (
                True,
                "pilot_role_match",
                {"matched_roles": sorted(matched_roles), "tier": "tier_1_role"},
            )

        # 2. Pilot User Whitelist Gate (MIG-012)
        pilot_users = {
            str(u).strip()
            for u in self.get_setting("KNOWLEDGE_V2_PILOT_USERS", [])
            if str(u).strip()
        }
        if user_id and user_id in pilot_users:
            return (
                True,
                "pilot_user_whitelist",
                {"user_id": user_id, "tier": "tier_2_pilot_user"},
            )

        # 3. Pilot Site Whitelist Gate (MIG-012)
        enabled_sites = {
            str(s).strip()
            for s in self.get_setting("KNOWLEDGE_V2_ENABLED_SITES", [])
            if str(s).strip()
        }
        matched_sites = site_ids & enabled_sites
        if matched_sites:
            return (
                True,
                "pilot_site_whitelist",
                {"matched_sites": sorted(matched_sites), "tier": "tier_3_site"},
            )

        # 4. Percentage-based Gradual Rollout (MIG-012)
        rollout_percent = int(self.get_setting("KNOWLEDGE_V2_ROLLOUT_PERCENT", 0))
        if rollout_percent >= 100:
            return (
                True,
                "full_rollout_100",
                {"rollout_percent": 100, "tier": "tier_4_full"},
            )
        if rollout_percent <= 0:
            return (
                False,
                "rollout_percent_zero",
                {"rollout_percent": 0, "tier": "tier_4_percentage"},
            )

        # Compute deterministic hash bucket based on tenant_id + user_id
        seed = f"{tenant_id}:{user_id or 'anon'}"
        bucket = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % 100
        is_hit = bucket < rollout_percent

        return (
            is_hit,
            "rollout_percentage_hit" if is_hit else "rollout_percentage_miss",
            {
                "rollout_percent": rollout_percent,
                "bucket": bucket,
                "tier": "tier_4_percentage",
            },
        )

    def is_v2_enabled(
        self,
        user_context: Mapping[str, Any] | None = None,
        *,
        request_override: bool | None = None,
    ) -> bool:
        enabled, _reason, _meta = self.evaluate_v2_access(
            user_context, request_override=request_override
        )
        return enabled


feature_flag_service = KnowledgeFeatureFlagService()
