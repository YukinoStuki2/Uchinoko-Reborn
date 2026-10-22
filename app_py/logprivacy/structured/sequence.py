"""Sequence cleaning support."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from logprivacy.internal.traversal import (
    LIMIT_ITERATION_ERROR,
    RECURSIVE_PLACEHOLDER,
    TRUNCATED_PLACEHOLDER,
    UNAVAILABLE_PLACEHOLDER,
    TraversalState,
)

if TYPE_CHECKING:
    from logprivacy.cleaner import Cleaner


def clean_sequence(
    sequence: Sequence[Any],
    cleaner: Cleaner,
    depth: int,
    state: TraversalState,
) -> Any:
    """Return a bounded cleaned sequence with explicit fail-closed markers."""
    sequence_id = id(sequence)
    if sequence_id in state.active:
        return (RECURSIVE_PLACEHOLDER,) if isinstance(sequence, tuple) else [RECURSIVE_PLACEHOLDER]

    state.active.add(sequence_id)
    cleaned: list[Any] = []
    try:
        try:
            iterator = iter(sequence)
        except Exception:
            state.mark_limit(LIMIT_ITERATION_ERROR)
            cleaned.append(UNAVAILABLE_PLACEHOLDER)
            return tuple(cleaned) if isinstance(sequence, tuple) else cleaned

        while True:
            try:
                item = next(iterator)
            except StopIteration:
                break
            except Exception:
                state.mark_limit(LIMIT_ITERATION_ERROR)
                cleaned.append(UNAVAILABLE_PLACEHOLDER)
                break

            if not state.consume_item():
                cleaned.append(TRUNCATED_PLACEHOLDER)
                break

            cleaned.append(
                cleaner._clean_value(
                    item,
                    depth=depth + 1,
                    state=state,
                )
            )

        return tuple(cleaned) if isinstance(sequence, tuple) else cleaned
    finally:
        state.active.discard(sequence_id)
