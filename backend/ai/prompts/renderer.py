"""
Prompt Template Renderer supporting variable substitution and string formatting
"""

from __future__ import annotations

from typing import Any, Dict
from jinja2 import Template


class PromptRenderer:
    """Renders prompt templates with variables."""

    @staticmethod
    def render(template_str: str, variables: Dict[str, Any]) -> str:
        if not template_str:
            return ""
        try:
            # First try Jinja2 template rendering
            tmpl = Template(template_str)
            return tmpl.render(**variables)
        except Exception:
            # Fallback to simple string replace
            result = template_str
            for key, val in variables.items():
                result = result.replace(f"{{{{{key}}}}}", str(val if val is not None else ""))
                result = result.replace(f"{{{key}}}", str(val if val is not None else ""))
            return result


prompt_renderer = PromptRenderer()
