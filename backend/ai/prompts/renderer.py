"""
Prompt Template Renderer supporting variable substitution and string formatting
"""

from __future__ import annotations

import re
from typing import Any, Dict
from jinja2.sandbox import SandboxedEnvironment

_SANDBOX_ENV = SandboxedEnvironment(autoescape=False)
_DOUBLE_BRACE_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")


class PromptRenderer:
    """Renders prompt templates with variables."""

    @staticmethod
    def render(template_str: str, variables: Dict[str, Any]) -> str:
        if not template_str:
            return ""
        try:
            # First try Jinja2 template rendering
            tmpl = _SANDBOX_ENV.from_string(template_str)
            return tmpl.render(**variables)
        except Exception:
            # Single-pass regex fallback prevents second-order template injection
            # when an earlier variable value contains placeholder-like braces.
            def _replace(match: re.Match[str]) -> str:
                key = match.group(1)
                if key not in variables:
                    return match.group(0)
                val = variables[key]
                return str(val if val is not None else "")

            return _DOUBLE_BRACE_RE.sub(_replace, template_str)


prompt_renderer = PromptRenderer()
