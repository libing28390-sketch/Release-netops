"""
AI Model Router: scene (chat, command_explain, config_diff, ...) -> model + fallback.

Review item L1: the unused ``resolve_route`` / ``resolve_route_with_reason``
helpers and the hard-coded ``DEFAULT_SCENE_ROUTES`` table (which pointed at a
DeepSeek model code regardless of what was configured) were removed.  Routing
comes only from ``ai_model_route`` and the configured default model.
"""

from __future__ import annotations

import logging
from typing import Optional

from database.core import get_db_connection
from ai.security.sanitizer import sanitize_log_text

logger = logging.getLogger(__name__)


_LIGHTWEIGHT_SCENES = frozenset({"natural_query", "model_health_probe"})


class ModelRouter:
    """Model Router resolving scene -> (primary_model, fallback_model)."""

    def resolve_route_policy(self, scene: str) -> tuple[Optional[str], Optional[str], str, Optional[str]]:
        """Resolve a route with precedence reason and optional scene data classification.

        Returns ``(model_id, fallback_model_id, reason, data_classification)``;
        reason is ``scene_route``, ``cost_optimized_default``, or ``system_default``.
        """
        try:
            with get_db_connection() as conn:
                # ai_model_route.data_classification exists since m0139.
                row = conn.execute(
                    "SELECT model_id, fallback_model_id, data_classification FROM ai_model_route WHERE scene = ? AND enabled = 1 ORDER BY priority DESC, updated_at DESC LIMIT 1",
                    (scene,),
                ).fetchone()
                if row:
                    return row[0], row[1], "scene_route", (str(row[2]) if row[2] else None)
                # For lightweight background scenes (intent classification,
                # health probes), prefer local/cheapest/flash enabled models
                # when no explicit scene route is configured.
                if str(scene or "").strip().lower() in _LIGHTWEIGHT_SCENES:
                    try:
                        cheap_row = conn.execute(
                            """
                            SELECT m.id
                            FROM ai_model m
                            JOIN ai_provider p ON p.id = m.provider_id
                            WHERE m.enabled = 1 AND p.enabled = 1
                              AND LOWER(COALESCE(m.model_type, 'chat')) IN ('chat', 'reasoning')
                            ORDER BY
                              CASE WHEN LOWER(COALESCE(p.provider_type, '')) IN ('ollama', 'local', 'vllm') THEN 0 ELSE 1 END ASC,
                              CASE WHEN LOWER(COALESCE(m.model_code, '')) LIKE '%flash%'
                                     OR LOWER(COALESCE(m.model_code, '')) LIKE '%mini%'
                                     OR LOWER(COALESCE(m.model_code, '')) LIKE '%lite%'
                                     OR LOWER(COALESCE(m.model_code, '')) LIKE '%small%' THEN 0 ELSE 1 END ASC,
                              (COALESCE(m.cost_input_per_1k, 0) + COALESCE(m.cost_output_per_1k, 0)) ASC,
                              m.priority DESC
                            LIMIT 1
                            """
                        ).fetchone()
                        if cheap_row:
                            return cheap_row[0], None, "cost_optimized_default", None
                    except Exception:
                        pass
                row = conn.execute("SELECT id FROM ai_model WHERE is_default = 1 AND enabled = 1 ORDER BY priority DESC LIMIT 1").fetchone()
                if row:
                    return row[0], None, "system_default", None
                row = conn.execute("SELECT id FROM ai_model WHERE enabled = 1 ORDER BY priority DESC LIMIT 1").fetchone()
                if row:
                    return row[0], None, "system_default", None
        except Exception as exc:
            # Exception text may contain connection details; log a stable type name.
            logger.warning(
                "Error resolving model route for scene '%s': %s code=AI_ROUTE_LOOKUP_FAILED",
                sanitize_log_text(scene, limit=64),
                type(exc).__name__,
            )
        return None, None, "system_default", None


model_router = ModelRouter()
