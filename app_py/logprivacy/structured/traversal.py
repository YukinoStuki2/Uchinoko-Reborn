"""Shared traversal helpers for structured data."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def should_descend(value: Any) -> bool:
    """Return True when a value should be traversed as structured data."""
    if isinstance(value, str | bytes | bytearray):
        return False
    return isinstance(value, Mapping | Sequence)
