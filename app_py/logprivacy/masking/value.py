"""Helpers for masking concrete sensitive values consistently."""

from __future__ import annotations

from typing import cast

from logprivacy.exceptions import LogBlockedError
from logprivacy.masking.strategy import MaskingStrategy
from logprivacy.policy import CleanerPolicy

_EXACT_SCALAR_TYPES = frozenset({int, float, complex, bool})
_EXACT_BYTE_TYPES = frozenset({bytes, bytearray, memoryview})


def mask_concrete_value(
    value: object,
    *,
    category: str,
    rule_name: str,
    reason: str,
    masking: MaskingStrategy,
) -> str:
    """Mask a safe concrete value, falling back to a category placeholder.

    Arbitrary objects are deliberately not stringified. Their ``__str__`` or
    ``__repr__`` implementation may disclose data or perform unsafe work.
    """
    concrete = _safe_concrete_text(value)
    if not concrete:
        return masking.mask_category(category)
    return masking.mask_value(concrete, category)


def mask_sensitive_value(
    value: object,
    *,
    category: str,
    rule_name: str,
    reason: str,
    policy: CleanerPolicy,
) -> str:
    """Apply policy blocking and mask one sensitive value consistently."""
    if category in policy.block_categories:
        raise LogBlockedError(
            f"LogPrivacy blocked sensitive categories: {category}",
            categories=(category,),
        )

    return mask_concrete_value(
        value,
        category=category,
        rule_name=rule_name,
        reason=reason,
        masking=policy.masking,
    )


def _safe_concrete_text(value: object) -> str | None:
    """Return text only for exact, side-effect-free built-in value types."""
    value_type = type(value)

    if value_type is str:
        return cast(str, value)
    if value_type is bytes:
        return cast(bytes, value).decode("utf-8", errors="replace")
    if value_type is bytearray:
        return bytes(cast(bytearray, value)).decode("utf-8", errors="replace")
    if value_type is memoryview:
        return bytes(cast(memoryview, value)).decode("utf-8", errors="replace")
    if value_type in _EXACT_SCALAR_TYPES:
        return str(value)
    return None
