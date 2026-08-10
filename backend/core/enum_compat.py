"""Compatibility helpers for enum features used by the Python 3.10 runtime."""

from __future__ import annotations

from enum import Enum

try:  # Python 3.11+
    from enum import StrEnum as StrEnum
except ImportError:  # Python 3.10, which remains the production Docker runtime.
    class StrEnum(str, Enum):
        """Backport the relevant Python 3.11 ``enum.StrEnum`` behaviour."""

        def __str__(self) -> str:
            return str(self.value)
