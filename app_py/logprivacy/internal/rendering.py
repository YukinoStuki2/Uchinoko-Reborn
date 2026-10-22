"""Safe, bounded rendering helpers for terminal and diagnostic output."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence, Set
from dataclasses import dataclass, field
from typing import Any, cast
from unicodedata import category as unicode_category

from logprivacy.cleaner import Cleaner
from logprivacy.exceptions import LogBlockedError
from logprivacy.masking.value import mask_sensitive_value

DEFAULT_MAX_RENDER_ITEMS = 100
DEFAULT_MAX_RENDER_CHARS = 16_384

_MAX_DEPTH_PLACEHOLDER = "[MAX_DEPTH]"
_TRUNCATED_PLACEHOLDER = "..."
_UNRENDERABLE_TEMPLATE = "<unrenderable {type_name}>"
_UNPRINTABLE_TEMPLATE = "<unprintable {type_name}>"
_EXACT_PRIMITIVE_TYPES = frozenset({int, float, complex, bool, type(None)})
_EXACT_BYTE_TYPES = frozenset({bytes, bytearray, memoryview})


def safe_render(
    value: Any,
    cleaner: Cleaner,
    *,
    max_items: int = DEFAULT_MAX_RENDER_ITEMS,
    max_chars: int = DEFAULT_MAX_RENDER_CHARS,
) -> str:
    """Return a recursively sanitized and size-bounded representation of ``value``."""
    renderer = _SafeRenderer(
        cleaner=cleaner,
        max_items=_validate_positive_limit("max_items", max_items),
        max_chars=_validate_positive_limit("max_chars", max_chars),
    )
    return renderer.render(value, nested=False, depth=0, budget=renderer.max_chars)


def safe_render_values(
    values: Sequence[Any],
    cleaner: Cleaner,
    *,
    separator: str,
    max_items: int = DEFAULT_MAX_RENDER_ITEMS,
    max_chars: int = DEFAULT_MAX_RENDER_CHARS,
) -> str:
    """Render top-level values with one shared item and character budget."""
    renderer = _SafeRenderer(
        cleaner=cleaner,
        max_items=_validate_positive_limit("max_items", max_items),
        max_chars=_validate_positive_limit("max_chars", max_chars),
    )
    return renderer.render_values(values, separator=separator)


def sanitize_output_text(
    value: str,
    *,
    allow_newline: bool = False,
    allow_tab: bool = False,
    max_chars: int = DEFAULT_MAX_RENDER_CHARS,
) -> str:
    """Escape terminal-control characters and bound the resulting text length."""
    limit = _validate_positive_limit("max_chars", max_chars)
    escaped = _escape_control_characters(
        value,
        allow_newline=allow_newline,
        allow_tab=allow_tab,
    )
    return _fit_text(escaped, limit)


@dataclass(slots=True)
class _SafeRenderer:
    cleaner: Cleaner
    max_items: int
    max_chars: int
    active: set[int] = field(default_factory=set)

    def render(self, value: Any, *, nested: bool, depth: int, budget: int) -> str:
        """Render one value without trusting arbitrary ``repr()`` implementations."""
        budget = max(0, min(budget, self.max_chars))
        if budget == 0:
            return ""

        max_depth = int(getattr(self.cleaner.policy, "max_depth", 20))
        if depth > max_depth:
            return self._render_text(_MAX_DEPTH_PLACEHOLDER, nested=nested, budget=budget)

        value_type = type(value)

        if value_type is str:
            return self._render_text(
                self.cleaner.clean_text(value),
                nested=nested,
                budget=budget,
            )

        if value_type in _EXACT_BYTE_TYPES:
            decoded = bytes(value).decode("utf-8", errors="replace")
            return self._render_text(
                self.cleaner.clean_text(decoded),
                nested=nested,
                budget=budget,
            )

        if value_type is range:
            return _fit_text(repr(value), budget)

        if value_type in _EXACT_PRIMITIVE_TYPES:
            return _fit_text(repr(value), budget)

        if isinstance(value, Mapping):
            return self._render_mapping(value, nested=nested, depth=depth, budget=budget)

        if isinstance(value, tuple):
            return self._render_tuple(value, nested=nested, depth=depth, budget=budget)

        if isinstance(value, list):
            return self._render_list(value, nested=nested, depth=depth, budget=budget)

        if isinstance(value, Set):
            return self._render_set(value, nested=nested, depth=depth, budget=budget)

        if isinstance(value, Sequence):
            return self._render_sequence(value, nested=nested, depth=depth, budget=budget)

        rendered = _stringify_unknown(value)
        return self._render_text(
            self.cleaner.clean_text(rendered),
            nested=nested,
            budget=budget,
        )

    def render_values(self, values: Sequence[Any], *, separator: str) -> str:
        """Render positional print values under one global character budget."""
        selected = list(values[: self.max_items])
        truncated = len(values) > self.max_items
        parts: list[str] = []
        used = 0

        for value in selected:
            separator_cost = len(separator) if parts else 0
            available = self.max_chars - used - separator_cost
            if available <= 0:
                truncated = True
                break

            part = self.render(value, nested=False, depth=0, budget=available)
            if parts:
                used += len(separator)
            parts.append(part)
            used += len(part)

            if used >= self.max_chars:
                truncated = True
                break

        if truncated:
            self._append_marker(parts, separator=separator, budget=self.max_chars)

        return _fit_text(separator.join(parts), self.max_chars)

    def _render_text(self, value: str, *, nested: bool, budget: int) -> str:
        escaped = _escape_control_characters(value)
        rendered = repr(escaped) if nested else escaped
        return _fit_text(rendered, budget)

    def _render_mapping(
        self,
        value: Mapping[Any, Any],
        *,
        nested: bool,
        depth: int,
        budget: int,
    ) -> str:
        cycle = self._enter(value, cycle_placeholder="{...}")
        if cycle is not None:
            return _fit_text(cycle, budget)

        try:
            try:
                items, truncated = _take_limited(value.items(), self.max_items)
            except Exception:
                return self._render_failure(value, nested=nested, budget=budget)

            pair_factories: list[tuple[str, Any, bool]] = []
            for key, item in items:
                key_text, rendered_key = self._prepare_mapping_key(key, budget=budget)
                sensitive = self._is_sensitive_key_text(key_text)
                pair_factories.append((rendered_key, item, sensitive))

            parts: list[str] = []
            used = 2  # opening and closing braces

            for rendered_key, item, sensitive in pair_factories:
                separator_cost = 2 if parts else 0
                available = budget - used - separator_cost
                if available <= 0:
                    truncated = True
                    break

                key_budget = max(1, min(len(rendered_key), max(16, available // 3)))
                safe_key = _fit_text(rendered_key, key_budget)
                value_budget = max(0, available - len(safe_key) - 2)

                if sensitive:
                    replacement = mask_sensitive_value(
                        item,
                        category="credential",
                        rule_name="safe_render",
                        reason="value belongs to a sensitive mapping key",
                        policy=self.cleaner.policy,
                    )
                    rendered_item = _fit_text(repr(replacement), value_budget)
                else:
                    rendered_item = self.render(
                        item,
                        nested=True,
                        depth=depth + 1,
                        budget=value_budget,
                    )

                pair = f"{safe_key}: {rendered_item}"
                if parts:
                    used += 2
                parts.append(pair)
                used += len(pair)

                if used >= budget:
                    truncated = True
                    break

            if truncated:
                self._append_marker(parts, separator=", ", budget=max(0, budget - 2))

            return _fit_text("{" + ", ".join(parts) + "}", budget)
        except LogBlockedError:
            raise
        except Exception:
            return self._render_failure(value, nested=nested, budget=budget)
        finally:
            self.active.discard(id(value))

    def _render_tuple(
        self,
        value: tuple[Any, ...],
        *,
        nested: bool,
        depth: int,
        budget: int,
    ) -> str:
        return self._render_iterable_container(
            value,
            opening="(",
            closing=")",
            cycle_placeholder="(...)",
            nested=nested,
            depth=depth,
            budget=budget,
            single_item_suffix=",",
        )

    def _render_list(
        self,
        value: list[Any],
        *,
        nested: bool,
        depth: int,
        budget: int,
    ) -> str:
        return self._render_iterable_container(
            value,
            opening="[",
            closing="]",
            cycle_placeholder="[...]",
            nested=nested,
            depth=depth,
            budget=budget,
        )

    def _render_set(
        self,
        value: Set[Any],
        *,
        nested: bool,
        depth: int,
        budget: int,
    ) -> str:
        if isinstance(value, frozenset):
            opening, closing, empty = "frozenset({", "})", "frozenset()"
        else:
            opening, closing, empty = "{", "}", "set()"

        return self._render_iterable_container(
            value,
            opening=opening,
            closing=closing,
            cycle_placeholder="{...}",
            nested=nested,
            depth=depth,
            budget=budget,
            empty_representation=empty,
        )

    def _render_sequence(
        self,
        value: Sequence[Any],
        *,
        nested: bool,
        depth: int,
        budget: int,
    ) -> str:
        return self._render_iterable_container(
            value,
            opening="[",
            closing="]",
            cycle_placeholder="[...]",
            nested=nested,
            depth=depth,
            budget=budget,
        )

    def _render_iterable_container(
        self,
        value: Iterable[Any],
        *,
        opening: str,
        closing: str,
        cycle_placeholder: str,
        nested: bool,
        depth: int,
        budget: int,
        single_item_suffix: str = "",
        empty_representation: str | None = None,
    ) -> str:
        cycle = self._enter(value, cycle_placeholder=cycle_placeholder)
        if cycle is not None:
            return _fit_text(cycle, budget)

        try:
            try:
                items, truncated = _take_limited(value, self.max_items)
            except Exception:
                return self._render_failure(value, nested=nested, budget=budget)

            if not items and not truncated and empty_representation is not None:
                return _fit_text(empty_representation, budget)

            parts: list[str] = []
            used = len(opening) + len(closing)

            for item in items:
                separator_cost = 2 if parts else 0
                available = budget - used - separator_cost
                if available <= 0:
                    truncated = True
                    break

                rendered = self.render(
                    item,
                    nested=True,
                    depth=depth + 1,
                    budget=available,
                )
                if parts:
                    used += 2
                parts.append(rendered)
                used += len(rendered)

                if used >= budget:
                    truncated = True
                    break

            if truncated:
                self._append_marker(
                    parts,
                    separator=", ",
                    budget=max(0, budget - len(opening) - len(closing)),
                )

            suffix = single_item_suffix if len(parts) == 1 and not truncated else ""
            return _fit_text(opening + ", ".join(parts) + suffix + closing, budget)
        except LogBlockedError:
            raise
        except Exception:
            return self._render_failure(value, nested=nested, budget=budget)
        finally:
            self.active.discard(id(value))

    def _prepare_mapping_key(self, key: object, *, budget: int) -> tuple[str, str]:
        """Stringify a mapping key once and reuse it for rendering and classification."""
        key_type = type(key)
        if key_type is str:
            # ``type(key) is str`` is intentionally stricter than isinstance(),
            # but static type checkers do not narrow through the cached type.
            key_text = cast(str, key)
            rendered = self._render_text(
                self.cleaner.clean_text(key_text),
                nested=True,
                budget=budget,
            )
            return key_text, rendered

        if key_type in _EXACT_PRIMITIVE_TYPES:
            key_text = str(key)
            return key_text, _fit_text(repr(key), budget)

        if key_type is bytes:
            key_text = cast(bytes, key).decode("utf-8", errors="replace")
        elif key_type is bytearray:
            key_text = bytes(cast(bytearray, key)).decode("utf-8", errors="replace")
        elif key_type is memoryview:
            key_text = bytes(cast(memoryview, key)).decode("utf-8", errors="replace")
        else:
            key_text = _stringify_unknown(key)

        rendered = self._render_text(
            self.cleaner.clean_text(key_text),
            nested=True,
            budget=budget,
        )
        return key_text, rendered

    def _is_sensitive_key_text(self, key_text: str) -> bool:
        """Classify a stable string value without invoking a user key again."""
        try:
            return self.cleaner.policy.is_sensitive_key(key_text)
        except Exception:
            return False

    def _render_failure(self, value: object, *, nested: bool, budget: int) -> str:
        placeholder = _UNRENDERABLE_TEMPLATE.format(type_name=type(value).__name__)
        return self._render_text(placeholder, nested=nested, budget=budget)

    def _enter(self, value: object, *, cycle_placeholder: str) -> str | None:
        value_id = id(value)
        if value_id in self.active:
            return cycle_placeholder
        self.active.add(value_id)
        return None

    @staticmethod
    def _append_marker(parts: list[str], *, separator: str, budget: int) -> None:
        """Append a truncation marker only when it fits the available budget."""
        current = len(separator.join(parts))
        marker_cost = len(_TRUNCATED_PLACEHOLDER) + (len(separator) if parts else 0)
        if current + marker_cost <= budget:
            parts.append(_TRUNCATED_PLACEHOLDER)
        elif parts:
            remaining = max(0, budget - current)
            if remaining:
                parts[-1] = _fit_text(parts[-1], max(1, len(parts[-1]) - marker_cost + remaining))


def _take_limited(values: Iterable[Any], limit: int) -> tuple[list[Any], bool]:
    """Consume at most ``limit + 1`` items to detect truncation safely."""
    iterator = iter(values)
    selected: list[Any] = []
    for _ in range(limit + 1):
        try:
            selected.append(next(iterator))
        except StopIteration:
            return selected, False
    return selected[:limit], True


def _stringify_unknown(value: Any) -> str:
    """Convert an object to text without propagating conversion failures or their messages."""
    try:
        return str(value)
    except Exception:
        return _UNPRINTABLE_TEMPLATE.format(type_name=type(value).__name__)


def _escape_control_characters(
    value: str,
    *,
    allow_newline: bool = False,
    allow_tab: bool = False,
) -> str:
    """Expose control and formatting characters as inert escape sequences."""
    escaped: list[str] = []
    for char in value:
        if char == "\n" and allow_newline:
            escaped.append(char)
            continue
        if char == "\t" and allow_tab:
            escaped.append(char)
            continue

        if unicode_category(char) in {"Cc", "Cf", "Cs"}:
            codepoint = ord(char)
            if codepoint <= 0xFF:
                escaped.append(f"\\x{codepoint:02x}")
            elif codepoint <= 0xFFFF:
                escaped.append(f"\\u{codepoint:04x}")
            else:
                escaped.append(f"\\U{codepoint:08x}")
        else:
            escaped.append(char)
    return "".join(escaped)


def _fit_text(value: str, limit: int) -> str:
    """Bound text while keeping truncation visible."""
    if limit <= 0:
        return ""
    if len(value) <= limit:
        return value
    if limit <= len(_TRUNCATED_PLACEHOLDER):
        return _TRUNCATED_PLACEHOLDER[:limit]
    return value[: limit - len(_TRUNCATED_PLACEHOLDER)] + _TRUNCATED_PLACEHOLDER


def _validate_positive_limit(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value
