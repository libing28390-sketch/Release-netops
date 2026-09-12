"""
AI Model Router for mapping scenes (chat, command_explain, config_diff, etc.) to target Models & Fallbacks
"""

from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple
from database.core import get_db_connection
from ai.gateway.exceptions import AIModelNotFoundException
from ai.security.sanitizer import sanitize_log_text

logger = logging.getLogger(__name__)

# Default hardcoded scene route defaults if DB is empty
DEFAULT_SCENE_ROUTES = {
    "chat": "deepseek-v4-flash",
    "command_explain": "deepseek-v4-flash",
    "config_explain": "deepseek-v4-flash",
    "config_diff": "deepseek-v4-flash",
    "alarm_analysis": "deepseek-v4-flash",
    "natural_query": "deepseek-v4-flash",
    "troubleshooting": "deepseek-v4-flash",
    "agent": "deepseek-v4-flash",
}


class ModelRouter:
    """Model Router resolving scene -> (primary_model, fallback_model)."""

    def resolve_route(self, scene: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Query DB for active route for `scene`.
        Returns (model_id, fallback_model_id).
        """
        try:
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT model_id, fallback_model_id FROM ai_model_route WHERE scene = ? AND enabled = 1 ORDER BY priority DESC, updated_at DESC LIMIT 1",
                    (scene,)
                )
                row = cursor.fetchone()
                if row:
                    return row[0], row[1]
                
                # Check default model in ai_model table
                cursor.execute(
                    "SELECT id FROM ai_model WHERE is_default = 1 AND enabled = 1 ORDER BY priority DESC LIMIT 1"
                )
                def_row = cursor.fetchone()
                if def_row:
                    return def_row[0], None
                
                # Check any enabled model in ai_model table
                cursor.execute(
                    "SELECT id FROM ai_model WHERE enabled = 1 ORDER BY priority DESC LIMIT 1"
                )
                any_row = cursor.fetchone()
                if any_row:
                    return any_row[0], None

        except Exception as exc:
            # Exception text may contain provider URLs or connection details;
            # keep the operational log bounded to a stable type name.
            logger.warning(
                "Error resolving model route for scene '%s': %s",
                sanitize_log_text(scene, limit=64),
                type(exc).__name__,
            )
        
        return None, None

    def resolve_route_with_reason(self, scene: str) -> tuple[Optional[str], Optional[str], str]:
        """Resolve a route while preserving the precedence explanation."""
        try:
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT model_id, fallback_model_id FROM ai_model_route WHERE scene = ? AND enabled = 1 ORDER BY priority DESC, updated_at DESC LIMIT 1",
                    (scene,),
                ).fetchone()
                if row:
                    return row[0], row[1], "scene_route"
                row = conn.execute("SELECT id FROM ai_model WHERE is_default = 1 AND enabled = 1 ORDER BY priority DESC LIMIT 1").fetchone()
                if row:
                    return row[0], None, "system_default"
                row = conn.execute("SELECT id FROM ai_model WHERE enabled = 1 ORDER BY priority DESC LIMIT 1").fetchone()
                if row:
                    return row[0], None, "system_default"
        except Exception as exc:
            logger.warning("Error resolving model route with reason for scene '%s': %s", scene, type(exc).__name__)
        return None, None, "system_default"


model_router = ModelRouter()
