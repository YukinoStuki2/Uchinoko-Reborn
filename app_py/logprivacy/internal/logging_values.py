"""Bounded, fail-closed sanitization for values stored in ``LogRecord`` objects."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from logprivacy.cleaner import Cleaner
from logprivacy.internal.rendering import (
    DEFAULT_MAX_RENDER_CHARS,
    safe_render,
    sanitize_output_text,
)
from logprivacy.internal.traversal import (
    ERROR_MAPPING_KEY,
    MAX_DEPTH_PLACEHOLDER,
    RECURSIVE_PLACEHOLDER,
    TRUNCATED_MAPPING_KEY,
    TRUNCATED_PLACEHOLDER,
    UNAVAILABLE_PLACEHOLDER,
    TraversalState,
    safe_mapping_key_text,
)
from logprivacy.masking.value import mask_sensitive_value

_EXACT_BYTE_TYPES = frozenset({bytes, bytearray, memoryview})
_EXACT_SCALAR_TYPES = frozenset({int, float, complex, bool, type(None)})
_MIN_CONTAINER_BUDGET = 8


@dataclass(slots=True)
class LoggingValueSanitizer:
    """Create logging-safe copies under shared item, depth, and text budgets."""

    cleaner: Cleaner
    max_chars: int = DEFAULT_MAX_RENDER_CHARS
    state: TraversalState = field(init=False)
    remaining_chars: int = field(init=False)

    def __post_init__(self) -> None:
        if isinstance(self.max_chars, bool) or not isinstance(self.max_chars, int):
            raise TypeError("max_chars must be an integer")
        if self.max_chars <= 0:
            raise ValueError("max_chars must be greater than zero")

        self.state = TraversalState(remaining_items=self.cleaner.policy.max_items)
        self.remaining_chars = self.max_chars

    def sanitize_args(self, value: Any) -> Any:
        """Sanitize format arguments while preserving named interpolation keys."""
        preserve_keys = isinstance(value, Mapping)
        return self.sanitize(value, depth=0, preserve_mapping_keys=preserve_keys)

    def sanitize(
        self,
        value: Any,
        *,
        depth: int = 0,
        preserve_mapping_keys: bool = False,
    ) -> Any:
        """Return a bounded value containing only formatter-safe components."""
        if depth > self.cleaner.policy.max_depth:
            return self._marker(MAX_DEPTH_PLACEHOLDER)

        value_type = type(value)
        if value_type is str:
            return self._clean_text(cast(str, value))

        if value_type in _EXACT_BYTE_TYPES:
            decoded = bytes(value).decode("utf-8", errors="replace")
            return self._clean_text(decoded)

        if value_type is range:
            self._charge(len(repr(value)))
            return value

        if value_type in _EXACT_SCALAR_TYPES:
            self._charge(len(repr(value)))
            return value

        if isinstance(value, Mapping):
            return self._sanitize_mapping(
                value,
                depth=depth,
                preserve_mapping_keys=preserve_mapping_keys,
            )

        if isinstance(value, Sequence):
            return self._sanitize_sequence(value, depth=depth)

        rendered = safe_render(
            value,
            self.cleaner,
            max_items=max(1, min(self.cleaner.policy.max_items, self.state.remaining_items or 1)),
            max_chars=max(1, self.remaining_chars),
        )
        return self._consume_rendered(rendered)

    def _sanitize_mapping(
        self,
        value: Mapping[Any, Any],
        *,
        depth: int,
        preserve_mapping_keys: bool,
    ) -> dict[Any, Any]:
        value_id = id(value)
        if value_id in self.state.active:
            return {ERROR_MAPPING_KEY: self._marker(RECURSIVE_PLACEHOLDER)}

        self.state.active.add(value_id)
        cleaned: dict[Any, Any] = {}
        try:
            try:
                iterator = iter(value.items())
            except Exception:
                return {ERROR_MAPPING_KEY: self._marker(UNAVAILABLE_PLACEHOLDER)}

            while True:
                if self.remaining_chars < _MIN_CONTAINER_BUDGET:
                    cleaned[self._unique_key(TRUNCATED_MAPPING_KEY, cleaned)] = self._marker(
                        TRUNCATED_PLACEHOLDER
                    )
                    break

                try:
                    key, item = next(iterator)
                except StopIteration:
                    break
                except Exception:
                    cleaned[self._unique_key(ERROR_MAPPING_KEY, cleaned)] = self._marker(
                        UNAVAILABLE_PLACEHOLDER
                    )
                    break

                if not self.state.consume_item():
                    cleaned[self._unique_key(TRUNCATED_MAPPING_KEY, cleaned)] = self._marker(
                        TRUNCATED_PLACEHOLDER
                    )
                    break

                key_text, trusted_key = safe_mapping_key_text(key)
                if preserve_mapping_keys and trusted_key:
                    preferred_key: Any = key
                else:
                    preferred_key = self.cleaner._sanitize_location_text(key_text)
                output_key = self._unique_key(preferred_key, cleaned)
                self._charge(self._safe_key_cost(output_key) + 4)

                if not trusted_key or self.cleaner.policy.is_sensitive_key(key_text):
                    cleaned[output_key] = mask_sensitive_value(
                        item,
                        category="credential",
                        rule_name="logging_extra",
                        reason="value belongs to a sensitive or untrusted logging mapping key",
                        policy=self.cleaner.policy,
                    )
                    self._charge(len(cast(str, cleaned[output_key])))
                else:
                    cleaned[output_key] = self.sanitize(item, depth=depth + 1)

            return cleaned
        finally:
            self.state.active.discard(value_id)

    def _sanitize_sequence(self, value: Sequence[Any], *, depth: int) -> Any:
        value_id = id(value)
        if value_id in self.state.active:
            marker = self._marker(RECURSIVE_PLACEHOLDER)
            return (marker,) if isinstance(value, tuple) else [marker]

        self.state.active.add(value_id)
        cleaned: list[Any] = []
        try:
            try:
                iterator = iter(value)
            except Exception:
                cleaned.append(self._marker(UNAVAILABLE_PLACEHOLDER))
                return tuple(cleaned) if isinstance(value, tuple) else cleaned

            while True:
                if self.remaining_chars < _MIN_CONTAINER_BUDGET:
                    cleaned.append(self._marker(TRUNCATED_PLACEHOLDER))
                    break

                try:
                    item = next(iterator)
                except StopIteration:
                    break
                except Exception:
                    cleaned.append(self._marker(UNAVAILABLE_PLACEHOLDER))
                    break

                if not self.state.consume_item():
                    cleaned.append(self._marker(TRUNCATED_PLACEHOLDER))
                    break

                self._charge(2)
                cleaned.append(self.sanitize(item, depth=depth + 1))

            return tuple(cleaned) if isinstance(value, tuple) else cleaned
        finally:
            self.state.active.discard(value_id)

    def _clean_text(self, value: str) -> str:
        cleaned = self.cleaner.clean_text(value)
        return self._consume_rendered(
            sanitize_output_text(
                cleaned,
                max_chars=max(1, self.remaining_chars),
            )
        )

    def _consume_rendered(self, value: str) -> str:
        if self.remaining_chars <= 0:
            return TRUNCATED_PLACEHOLDER
        bounded = sanitize_output_text(value, max_chars=max(1, self.remaining_chars))
        self._charge(len(bounded))
        return bounded

    def _marker(self, value: str) -> str:
        if self.remaining_chars <= 0:
            return TRUNCATED_PLACEHOLDER
        bounded = value[: self.remaining_chars]
        self._charge(len(bounded))
        return bounded

    def _charge(self, amount: int) -> None:
        self.remaining_chars = max(0, self.remaining_chars - max(0, amount))

    @staticmethod
    def _safe_key_cost(key: Any) -> int:
        key_type = type(key)
        if key_type is str:
            return len(cast(str, key))
        if key_type in _EXACT_SCALAR_TYPES:
            return len(repr(key))
        if key_type in _EXACT_BYTE_TYPES:
            return len(bytes(key))
        return len(type(key).__name__) + 2

    @staticmethod
    def _unique_key(candidate: Any, cleaned: dict[Any, Any]) -> Any:
        if candidate not in cleaned:
            return candidate
        if type(candidate) is not str:
            return candidate

        suffix = 2
        while True:
            unique = f"{candidate}#{suffix}"
            if unique not in cleaned:
                return unique
            suffix += 1
