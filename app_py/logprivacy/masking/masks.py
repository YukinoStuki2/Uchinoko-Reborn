"""Convenience masking helpers."""

from __future__ import annotations


def keep_edges(value: str, *, left: int = 2, right: int = 2, fill: str = "*") -> str:
    """
    Mask the middle of a value while keeping its edges.

    Example:
        keep_edges("abcdef") -> "ab**ef"
    """
    if len(value) <= left + right:
        return fill * len(value)
    return f"{value[:left]}{fill * (len(value) - left - right)}{value[-right:]}"


def mask_email(value: str) -> str:
    """Partially mask an email while keeping the domain visible."""
    if "@" not in value:
        return keep_edges(value)
    local, domain = value.split("@", 1)
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def mask_token(value: str) -> str:
    """Partially mask a token-like value."""
    return keep_edges(value, left=4, right=4)
