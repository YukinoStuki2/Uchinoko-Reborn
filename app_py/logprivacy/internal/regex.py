"""Regex helpers used internally."""

from __future__ import annotations

import re
from re import Pattern


def compile_case_insensitive(pattern: str) -> Pattern[str]:
    """Compile a regex pattern with IGNORECASE."""
    return re.compile(pattern, re.IGNORECASE)
