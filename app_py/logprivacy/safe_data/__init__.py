"""JSON-safe structured sanitization public API."""

from __future__ import annotations

from logprivacy.safe_data.normalization import (
    NON_FINITE_NUMBER_PLACEHOLDER,
    REMOVED_PLACEHOLDER,
    to_safe_data,
    to_safe_data_with_result,
)

__all__ = [
    "NON_FINITE_NUMBER_PLACEHOLDER",
    "REMOVED_PLACEHOLDER",
    "to_safe_data",
    "to_safe_data_with_result",
]
