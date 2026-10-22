"""Validation helpers."""

from __future__ import annotations

from logprivacy.exceptions import RuleValidationError


def ensure_non_empty(name: str, value: str) -> None:
    """Raise when a string value is empty."""
    if not value:
        raise RuleValidationError(f"{name} must not be empty")
