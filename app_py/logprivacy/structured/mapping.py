"""Mapping cleaning support."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from logprivacy.internal.traversal import (
    ERROR_MAPPING_KEY,
    LIMIT_ITERATION_ERROR,
    RECURSIVE_PLACEHOLDER,
    TRUNCATED_MAPPING_KEY,
    TRUNCATED_PLACEHOLDER,
    UNAVAILABLE_PLACEHOLDER,
    TraversalState,
    safe_mapping_key_text,
)
from logprivacy.masking.value import mask_sensitive_value

if TYPE_CHECKING:
    from logprivacy.cleaner import Cleaner


def clean_mapping(
    mapping: Mapping[Any, Any],
    cleaner: Cleaner,
    depth: int,
    state: TraversalState,
) -> dict[Any, Any]:
    """Return a bounded cleaned dictionary copy that fails closed."""
    mapping_id = id(mapping)
    if mapping_id in state.active:
        return {ERROR_MAPPING_KEY: RECURSIVE_PLACEHOLDER}

    state.active.add(mapping_id)
    cleaned: dict[Any, Any] = {}
    try:
        try:
            iterator = iter(mapping.items())
        except Exception:
            state.mark_limit(LIMIT_ITERATION_ERROR)
            return {ERROR_MAPPING_KEY: UNAVAILABLE_PLACEHOLDER}

        while True:
            try:
                key, value = next(iterator)
            except StopIteration:
                break
            except Exception:
                state.mark_limit(LIMIT_ITERATION_ERROR)
                cleaned[ERROR_MAPPING_KEY] = UNAVAILABLE_PLACEHOLDER
                break

            if not state.consume_item():
                cleaned[TRUNCATED_MAPPING_KEY] = TRUNCATED_PLACEHOLDER
                break

            key_text, trusted_key = safe_mapping_key_text(key)
            if trusted_key:
                preferred_key: Any = (
                    cleaner.clean_text(key_text) if cleaner.policy.clean_mapping_keys else key
                )
            else:
                preferred_key = cleaner._sanitize_location_text(key_text)
            output_key = _unique_output_key(preferred_key, cleaned)

            if not trusted_key or cleaner.policy.is_sensitive_key(key_text):
                cleaned[output_key] = mask_sensitive_value(
                    value,
                    category="credential",
                    rule_name="sensitive_key",
                    reason="value belongs to a sensitive or untrusted mapping key",
                    policy=cleaner.policy,
                )
            else:
                cleaned[output_key] = cleaner._clean_value(
                    value,
                    depth=depth + 1,
                    state=state,
                )
        return cleaned
    finally:
        state.active.discard(mapping_id)


def _unique_output_key(candidate: Any, cleaned: dict[Any, Any]) -> Any:
    """Return a collision-free output key without invoking arbitrary user code."""
    if candidate not in cleaned:
        return candidate
    if not isinstance(candidate, str):
        return candidate

    suffix = 2
    while True:
        unique = f"{candidate}#{suffix}"
        if unique not in cleaned:
            return unique
        suffix += 1
