"""JSON-safe structured sanitization."""

from __future__ import annotations

import json as _json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date as Date
from datetime import datetime as DateTime
from datetime import time as Time
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from logprivacy.adapters import AdapterRegistry
from logprivacy.adapters.registry import _AdapterResolution
from logprivacy.cleaner import Cleaner
from logprivacy.exceptions import LogBlockedError
from logprivacy.exceptions.errors import PseudonymizationConfigurationError
from logprivacy.field_rules import FieldRule
from logprivacy.internal.traversal import (
    ERROR_MAPPING_KEY,
    LIMIT_ADAPTER_ERROR,
    LIMIT_ITERATION_ERROR,
    LIMIT_MAX_DEPTH,
    LIMIT_RECURSIVE,
    LIMIT_REPRESENTATION_ERROR,
    LIMIT_UNSUPPORTED_TYPE,
    LIMIT_UNTRUSTED_MAPPING_KEY,
    MAX_DEPTH_PLACEHOLDER,
    RECURSIVE_PLACEHOLDER,
    TRUNCATED_MAPPING_KEY,
    TRUNCATED_PLACEHOLDER,
    UNAVAILABLE_PLACEHOLDER,
    TraversalState,
    safe_mapping_key_text,
)
from logprivacy.masking.value import mask_sensitive_value
from logprivacy.path_rules.allowlist import _AllowlistMatcher, _AllowlistPathMatch
from logprivacy.path_rules.rules import PathRule, _TraversalPath
from logprivacy.policy import CleanerPolicy
from logprivacy.result import SafeDataResult, SafeDataStats
from logprivacy.typing import JSONValue

NON_FINITE_NUMBER_PLACEHOLDER = "[NON_FINITE_NUMBER]"
REMOVED_PLACEHOLDER = "[REMOVED]"
TRUNCATED_FIELD_PLACEHOLDER = "[TRUNCATED]"

_EXACT_BYTE_TYPES = frozenset({bytes, bytearray, memoryview})
_SAFE_TYPE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")


class _OmitSentinel:
    __slots__ = ()


_OMIT = _OmitSentinel()


def to_safe_data(
    value: object,
    *,
    policy: CleanerPolicy | None = None,
    adapters: AdapterRegistry | None = None,
) -> JSONValue:
    """Return a sanitized value made only of JSON-compatible Python types.

    Unknown objects fail closed as ``"[UNSUPPORTED:TypeName]"``. Converter
    results from ``adapters`` are processed again by the same sanitization
    pipeline and are never trusted as already safe.

    For richer output including completeness, limitations, and stats, use
    ``to_safe_data_with_result()``.
    """
    return to_safe_data_with_result(value, policy=policy, adapters=adapters).cleaned


def to_safe_data_with_result(
    value: object,
    *,
    policy: CleanerPolicy | None = None,
    adapters: AdapterRegistry | None = None,
) -> SafeDataResult:
    """Return sanitized data together with completeness, limitations, and stats."""
    effective_policy = CleanerPolicy.default() if policy is None else policy
    effective_adapters = AdapterRegistry.default() if adapters is None else adapters.copy()
    normalizer = _SafeDataNormalizer(effective_policy, effective_adapters)
    return normalizer.normalize_with_result(value)


@dataclass(slots=True)
class _NormalizationCounters:
    """Mutable counters local to one normalization call."""

    masked: int = 0
    removed: int = 0
    truncated: int = 0
    unsupported: int = 0
    adapter_errors: int = 0
    field_rule_matches: int = 0
    path_rule_matches: int = 0
    not_allowed: int = 0
    pseudonymized: int = 0

    def to_stats(self) -> SafeDataStats:
        return SafeDataStats(
            masked=self.masked,
            removed=self.removed,
            truncated=self.truncated,
            unsupported=self.unsupported,
            adapter_errors=self.adapter_errors,
            field_rule_matches=self.field_rule_matches,
            path_rule_matches=self.path_rule_matches,
            not_allowed=self.not_allowed,
            pseudonymized=self.pseudonymized,
        )


@dataclass(slots=True)
class _SafeDataNormalizer:
    policy: CleanerPolicy
    adapters: AdapterRegistry
    _cleaner: Cleaner = field(init=False, repr=False)
    _allowlist: _AllowlistMatcher = field(init=False, repr=False)
    _allowlist_active: bool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._cleaner = Cleaner(policy=self.policy)
        self._allowlist = _AllowlistMatcher(
            self.policy.allowlist if self.policy.allowlist is not None else ()
        )
        self._allowlist_active = self.policy.allowlist is not None

    def normalize_with_result(self, value: object) -> SafeDataResult:
        state = TraversalState(remaining_items=self.policy.max_items)
        counters = _NormalizationCounters()
        cleaned = self._normalize(value, depth=0, state=state, counters=counters)
        return SafeDataResult(
            cleaned=cleaned,
            complete=state.complete,
            limitations=tuple(state.limitations),
            stats=counters.to_stats(),
        )

    def _normalize(
        self,
        value: object,
        *,
        depth: int,
        state: TraversalState,
        counters: _NormalizationCounters,
        path: _TraversalPath = (),
    ) -> JSONValue:
        if depth > self.policy.max_depth:
            state.mark_limit(LIMIT_MAX_DEPTH)
            return MAX_DEPTH_PLACEHOLDER

        value_type = type(value)

        # Exact primitive types are reserved and never intercepted by adapters.
        if value is None or value_type is bool:
            return cast(JSONValue, value)
        if value_type is int:
            return cast(JSONValue, value)
        if value_type is float:
            float_value = cast(float, value)
            return float_value if math.isfinite(float_value) else NON_FINITE_NUMBER_PLACEHOLDER
        if value_type is str:
            return self._clean_text(cast(str, value), counters=counters)
        if value_type in _EXACT_BYTE_TYPES:
            return self._clean_text(
                bytes(cast(Any, value)).decode("utf-8", errors="replace"), counters=counters
            )

        # Resolve custom adapters before structural isinstance checks so custom
        # subclasses can override their native structural fallback.
        resolution: _AdapterResolution = self.adapters._resolve_result(value)
        if resolution.resolution_failed:
            state.mark_limit(LIMIT_ADAPTER_ERROR)
            counters.adapter_errors += 1
        elif resolution.converter is not None:
            return self._normalize_with_adapter(
                value,
                resolution,
                depth=depth,
                state=state,
                counters=counters,
                path=path,
            )

        if isinstance(value, str):
            return self._clean_text(value, counters=counters)
        if isinstance(value, Mapping):
            return self._normalize_mapping(
                value,
                depth=depth,
                state=state,
                counters=counters,
                parent_path=path,
            )
        if isinstance(value, (list, tuple)):
            return self._normalize_sequence(
                value,
                depth=depth,
                state=state,
                counters=counters,
                parent_path=path,
            )
        if isinstance(value, (set, frozenset)):
            return self._normalize_set(
                value,
                depth=depth,
                state=state,
                counters=counters,
                parent_path=path,
            )
        if is_dataclass(value) and not isinstance(value, type):
            return self._normalize_dataclass(
                value,
                depth=depth,
                state=state,
                counters=counters,
                parent_path=path,
            )
        if isinstance(value, Enum):
            return self._normalize(
                value.value,
                depth=depth + 1,
                state=state,
                counters=counters,
                path=path,
            )
        if isinstance(value, Decimal):
            return (
                self._clean_text(str(value), counters=counters)
                if value.is_finite()
                else NON_FINITE_NUMBER_PLACEHOLDER
            )
        if isinstance(value, DateTime):
            return self._clean_text(value.isoformat(), counters=counters)
        if isinstance(value, Date):
            return self._clean_text(value.isoformat(), counters=counters)
        if isinstance(value, Time):
            return self._clean_text(value.isoformat(), counters=counters)
        if isinstance(value, UUID):
            return self._clean_text(str(value), counters=counters)
        if isinstance(value, Path):
            return self._clean_text(value.as_posix(), counters=counters)
        if isinstance(value, BaseException):
            return self._normalize_exception(
                value,
                depth=depth,
                state=state,
                counters=counters,
                parent_path=path,
            )

        state.mark_limit(LIMIT_UNSUPPORTED_TYPE)
        counters.unsupported += 1
        return f"[UNSUPPORTED:{_safe_type_name(value)}]"

    def _normalize_with_adapter(
        self,
        value: object,
        resolution: _AdapterResolution,
        *,
        depth: int,
        state: TraversalState,
        counters: _NormalizationCounters,
        path: _TraversalPath = (),
    ) -> JSONValue:
        converter = resolution.converter
        assert converter is not None

        value_id = id(value)
        if value_id in state.active:
            state.mark_limit(LIMIT_RECURSIVE)
            return RECURSIVE_PLACEHOLDER

        state.active.add(value_id)
        try:
            try:
                converted_value = converter(value)
            except Exception:
                state.mark_limit(LIMIT_ADAPTER_ERROR)
                counters.adapter_errors += 1
                counters.unsupported += 1
                return f"[UNSUPPORTED:{_safe_type_name(value)}]"

            if converted_value is value:
                state.mark_limit(LIMIT_ADAPTER_ERROR)
                counters.adapter_errors += 1
                counters.unsupported += 1
                return f"[UNSUPPORTED:{_safe_type_name(value)}]"

            return self._normalize(
                converted_value,
                depth=depth + 1,
                state=state,
                counters=counters,
                path=path,
            )
        finally:
            state.active.discard(value_id)

    def _normalize_mapping(
        self,
        mapping: Mapping[Any, Any],
        *,
        depth: int,
        state: TraversalState,
        counters: _NormalizationCounters,
        parent_path: _TraversalPath = (),
    ) -> dict[str, JSONValue]:
        mapping_id = id(mapping)
        if mapping_id in state.active:
            state.mark_limit(LIMIT_RECURSIVE)
            return {ERROR_MAPPING_KEY: RECURSIVE_PLACEHOLDER}

        state.active.add(mapping_id)
        cleaned: dict[str, JSONValue] = {}
        try:
            try:
                iterator = iter(mapping.items())
            except Exception:
                state.mark_limit(LIMIT_ITERATION_ERROR)
                return {ERROR_MAPPING_KEY: UNAVAILABLE_PLACEHOLDER}

            while True:
                try:
                    key, item = next(iterator)
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
                output_key = _unique_json_key(
                    self._clean_text(key_text, counters=counters), cleaned
                )

                if not trusted_key:
                    # The value is fail-closed masked without traversing the branch.
                    # Report that limitation so ``complete`` never claims the whole
                    # input was inspected.
                    state.mark_limit(LIMIT_UNTRUSTED_MAPPING_KEY)
                    cleaned[output_key] = self._mask_field_value(item, counters=counters)
                    continue

                child_path: _TraversalPath = (*parent_path, key_text)
                result = self._process_named_field(
                    key_text,
                    item,
                    depth=depth + 1,
                    state=state,
                    counters=counters,
                    path=child_path,
                    sensitive_key=self.policy.is_sensitive_key(key),
                )
                if not isinstance(result, _OmitSentinel):
                    cleaned[output_key] = result
            return cleaned
        finally:
            state.active.discard(mapping_id)

    def _normalize_dataclass(
        self,
        value: object,
        *,
        depth: int,
        state: TraversalState,
        counters: _NormalizationCounters,
        parent_path: _TraversalPath = (),
    ) -> dict[str, JSONValue]:
        value_id = id(value)
        if value_id in state.active:
            state.mark_limit(LIMIT_RECURSIVE)
            return {ERROR_MAPPING_KEY: RECURSIVE_PLACEHOLDER}

        state.active.add(value_id)
        cleaned: dict[str, JSONValue] = {}
        try:
            for field_info in fields(cast(Any, value)):
                if not state.consume_item():
                    cleaned[TRUNCATED_MAPPING_KEY] = TRUNCATED_PLACEHOLDER
                    break

                key_text = field_info.name
                output_key = _unique_json_key(
                    self._clean_text(key_text, counters=counters), cleaned
                )
                try:
                    field_value = getattr(value, key_text)
                except Exception:
                    state.mark_limit(LIMIT_REPRESENTATION_ERROR)
                    cleaned[output_key] = UNAVAILABLE_PLACEHOLDER
                    continue

                child_path: _TraversalPath = (*parent_path, key_text)
                result = self._process_named_field(
                    key_text,
                    field_value,
                    depth=depth + 1,
                    state=state,
                    counters=counters,
                    path=child_path,
                    sensitive_key=self.policy.is_sensitive_key(key_text),
                )
                if not isinstance(result, _OmitSentinel):
                    cleaned[output_key] = result
            return cleaned
        finally:
            state.active.discard(value_id)

    def _normalize_sequence(
        self,
        sequence: Sequence[Any],
        *,
        depth: int,
        state: TraversalState,
        counters: _NormalizationCounters,
        parent_path: _TraversalPath = (),
    ) -> list[JSONValue]:
        sequence_id = id(sequence)
        if sequence_id in state.active:
            state.mark_limit(LIMIT_RECURSIVE)
            return [RECURSIVE_PLACEHOLDER]

        state.active.add(sequence_id)
        cleaned: list[JSONValue] = []
        try:
            try:
                iterator = iter(sequence)
            except Exception:
                state.mark_limit(LIMIT_ITERATION_ERROR)
                return [UNAVAILABLE_PLACEHOLDER]

            source_index = 0
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

                child_path: _TraversalPath = (*parent_path, source_index)
                source_index += 1
                result = self._process_child(
                    item,
                    depth=depth + 1,
                    state=state,
                    counters=counters,
                    path=child_path,
                )
                if not isinstance(result, _OmitSentinel):
                    cleaned.append(result)
            return cleaned
        finally:
            state.active.discard(sequence_id)

    def _normalize_set(
        self,
        values: set[Any] | frozenset[Any],
        *,
        depth: int,
        state: TraversalState,
        counters: _NormalizationCounters,
        parent_path: _TraversalPath = (),
    ) -> list[JSONValue]:
        value_id = id(values)
        if value_id in state.active:
            state.mark_limit(LIMIT_RECURSIVE)
            return [RECURSIVE_PLACEHOLDER]

        state.active.add(value_id)
        cleaned: list[JSONValue] = []
        try:
            try:
                iterator = iter(values)
            except Exception:
                state.mark_limit(LIMIT_ITERATION_ERROR)
                return [UNAVAILABLE_PLACEHOLDER]

            source_index = 0
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

                child_path: _TraversalPath = (*parent_path, source_index)
                source_index += 1
                result = self._process_child(
                    item,
                    depth=depth + 1,
                    state=state,
                    counters=counters,
                    path=child_path,
                )
                if not isinstance(result, _OmitSentinel):
                    cleaned.append(result)
            return sorted(cleaned, key=_json_sort_key)
        finally:
            state.active.discard(value_id)

    def _normalize_exception(
        self,
        value: BaseException,
        *,
        depth: int,
        state: TraversalState,
        counters: _NormalizationCounters,
        parent_path: _TraversalPath = (),
    ) -> dict[str, JSONValue]:
        value_id = id(value)
        if value_id in state.active:
            state.mark_limit(LIMIT_RECURSIVE)
            return {"type": _safe_type_name(value), "message": RECURSIVE_PLACEHOLDER}

        state.active.add(value_id)
        try:
            type_name = _safe_type_name(value)
            try:
                message: object = str(value)
            except Exception:
                state.mark_limit(LIMIT_REPRESENTATION_ERROR)
                message = UNAVAILABLE_PLACEHOLDER

            result: dict[str, JSONValue] = {}

            type_result = self._process_named_field(
                "type",
                type_name,
                depth=depth + 1,
                state=state,
                counters=counters,
                path=(*parent_path, "type"),
                sensitive_key=self.policy.is_sensitive_key("type"),
            )
            if not isinstance(type_result, _OmitSentinel):
                result["type"] = type_result

            message_result = self._process_named_field(
                "message",
                message,
                depth=depth + 1,
                state=state,
                counters=counters,
                path=(*parent_path, "message"),
                sensitive_key=self.policy.is_sensitive_key("message"),
            )
            if not isinstance(message_result, _OmitSentinel):
                result["message"] = message_result

            return result
        finally:
            state.active.discard(value_id)

    def _process_named_field(
        self,
        field_name: str,
        field_value: object,
        *,
        depth: int,
        state: TraversalState,
        counters: _NormalizationCounters,
        path: _TraversalPath,
        sensitive_key: bool = False,
    ) -> JSONValue | _OmitSentinel:
        """Apply path and field policies to one named child."""
        return self._process_child(
            field_value,
            depth=depth,
            state=state,
            counters=counters,
            path=path,
            field_name=field_name,
            sensitive_key=sensitive_key,
        )

    def _process_child(
        self,
        value: object,
        *,
        depth: int,
        state: TraversalState,
        counters: _NormalizationCounters,
        path: _TraversalPath,
        field_name: str | None = None,
        sensitive_key: bool = False,
    ) -> JSONValue | _OmitSentinel:
        """Apply structured policies to any child, including sequence elements.

        Source indices are part of ``path`` before any item is omitted. This
        keeps exact rules such as ``items.1`` stable even when ``items.0`` is
        removed by the allowlist.
        """
        path_rules = self._matching_path_rules(path)
        field_rules = self._matching_field_rules(field_name) if field_name is not None else ()

        # ``block`` is a security boundary, not an ordinary first-match action.
        # A later block rule must not be bypassed by an earlier mask/remove rule,
        # nor by an allowlist that would otherwise omit the field.
        blocking_path_rule = next((rule for rule in path_rules if rule.action == "block"), None)
        if blocking_path_rule is not None:
            counters.path_rule_matches += 1
            return self._apply_action(
                blocking_path_rule.action,
                value,
                depth=depth,
                state=state,
                counters=counters,
                path=path,
                max_chars=blocking_path_rule.max_chars,
                category=blocking_path_rule.category,
            )

        blocking_field_rule = next((rule for rule in field_rules if rule.action == "block"), None)
        if blocking_field_rule is not None:
            counters.field_rule_matches += 1
            return self._apply_action(
                blocking_field_rule.action,
                value,
                depth=depth,
                state=state,
                counters=counters,
                path=path,
                max_chars=blocking_field_rule.max_chars,
                category=blocking_field_rule.category,
            )

        # The allowlist is an output boundary. After blocking rules have had a
        # chance to stop the operation, a path that is not allowed must not be
        # reintroduced by a mask, truncate, remove, or pseudonymize rule.
        allowlist_match: _AllowlistPathMatch = "exact"
        if self._allowlist_active:
            allowlist_match = self._allowlist.match_path(path)
            if allowlist_match == "none":
                counters.not_allowed += 1
                return _OMIT
            if allowlist_match == "prefix" and _is_definitely_scalar(value):
                counters.not_allowed += 1
                return _OMIT

        path_rule = next((rule for rule in path_rules if rule.action != "block"), None)
        if path_rule is not None:
            counters.path_rule_matches += 1
            processed = self._apply_action(
                path_rule.action,
                value,
                depth=depth,
                state=state,
                counters=counters,
                path=path,
                max_chars=path_rule.max_chars,
                category=path_rule.category,
            )
            return self._omit_non_container_prefix_result(
                processed,
                allowlist_match=allowlist_match,
                counters=counters,
            )

        if field_name is not None:
            field_rule = next((rule for rule in field_rules if rule.action != "block"), None)
            if field_rule is not None:
                counters.field_rule_matches += 1
                processed = self._apply_action(
                    field_rule.action,
                    value,
                    depth=depth,
                    state=state,
                    counters=counters,
                    path=path,
                    max_chars=field_rule.max_chars,
                    category=field_rule.category,
                )
                return self._omit_non_container_prefix_result(
                    processed,
                    allowlist_match=allowlist_match,
                    counters=counters,
                )

            if sensitive_key:
                processed = self._mask_field_value(value, counters=counters)
                return self._omit_non_container_prefix_result(
                    processed,
                    allowlist_match=allowlist_match,
                    counters=counters,
                )

        processed = self._normalize(
            value,
            depth=depth,
            state=state,
            counters=counters,
            path=path,
        )
        return self._omit_non_container_prefix_result(
            processed,
            allowlist_match=allowlist_match,
            counters=counters,
        )

    @staticmethod
    def _omit_non_container_prefix_result(
        processed: JSONValue,
        *,
        allowlist_match: _AllowlistPathMatch,
        counters: _NormalizationCounters,
    ) -> JSONValue | _OmitSentinel:
        """Drop scalar output that only matched a parent-prefix allowlist path."""
        if allowlist_match == "prefix" and not isinstance(processed, (dict, list)):
            counters.not_allowed += 1
            return _OMIT
        return processed

    def _matching_path_rules(self, path: _TraversalPath) -> tuple[PathRule, ...]:
        """Return all matching path rules in declaration order."""
        return tuple(
            rule
            for rule in self.policy.path_rules
            if isinstance(rule, PathRule) and rule.matches_traversal_path(path)
        )

    def _matching_field_rules(self, field_name: str) -> tuple[FieldRule, ...]:
        """Return all matching field rules in declaration order."""
        return tuple(rule for rule in self.policy.field_rules if rule.matches(field_name))

    def _matching_path_rule(self, path: _TraversalPath) -> PathRule | None:
        """Return the first matching path rule for compatibility with internal callers."""
        return next(iter(self._matching_path_rules(path)), None)

    def _matching_field_rule(self, field_name: str) -> FieldRule | None:
        """Return the first matching field rule for compatibility with internal callers."""
        return next(iter(self._matching_field_rules(field_name)), None)

    def _apply_action(
        self,
        action: str,
        value: object,
        *,
        depth: int,
        state: TraversalState,
        counters: _NormalizationCounters,
        path: _TraversalPath,
        max_chars: int | None,
        category: str,
    ) -> JSONValue:
        del depth, state, path  # Reserved for action implementations that need traversal context.

        if action == "mask":
            return self._mask_field_value(value, counters=counters)
        if action == "remove":
            counters.removed += 1
            return REMOVED_PLACEHOLDER
        if action == "truncate":
            text = _truncatable_text(value)
            if text is None or max_chars is None:
                counters.truncated += 1
                return TRUNCATED_FIELD_PLACEHOLDER
            cleaned = self._clean_text(text, counters=counters)
            if len(cleaned) <= max_chars:
                return cleaned
            counters.truncated += 1
            return cleaned[:max_chars] + TRUNCATED_FIELD_PLACEHOLDER
        if action == "block":
            raise LogBlockedError(
                "LogPrivacy blocked a field by policy",
                categories=("field",),
            )
        if action == "pseudonymize":
            pseudonymizer = self.policy.pseudonymizer
            if pseudonymizer is None:
                raise PseudonymizationConfigurationError(
                    "pseudonymize action requires a pseudonymizer configured via "
                    "policy.with_pseudonymizer(HMACMaskingStrategy(key=...))"
                )
            text = _pseudonymizable_text(value)
            if text is None:
                return self._mask_field_value(value, counters=counters)
            effective_category = category or "credential"
            counters.pseudonymized += 1
            return pseudonymizer.mask_value(text, effective_category)

        return self._mask_field_value(value, counters=counters)

    def _mask_field_value(self, value: object, *, counters: _NormalizationCounters) -> str:
        counters.masked += 1
        return mask_sensitive_value(
            value,
            category="credential",
            rule_name="field_rule",
            reason="value belongs to a sensitive structured field",
            policy=self.policy,
        )

    def _clean_text(self, value: str, *, counters: _NormalizationCounters) -> str:
        result = self._cleaner.clean_with_result(value)
        counters.masked += len(result.findings)
        return result.cleaned


def _is_definitely_scalar(value: object) -> bool:
    """Return whether ``value`` cannot contain an allowlisted descendant.

    Exact primitive types and built-in scalar value objects are safe to classify
    immediately. Unknown custom objects are not classified as scalar here
    because a registered adapter may convert them into a mapping or sequence;
    their normalized result is checked after adapter processing instead.
    """
    value_type = type(value)
    if value is None or value_type in {bool, int, float, str, bytes, bytearray, memoryview}:
        return True
    return isinstance(value, (Enum, Decimal, DateTime, Date, Time, UUID, Path))


def _truncatable_text(value: object) -> str | None:
    value_type = type(value)
    if value_type is str:
        return cast(str, value)
    if value_type in _EXACT_BYTE_TYPES:
        return bytes(cast(Any, value)).decode("utf-8", errors="replace")
    return None


def _pseudonymizable_text(value: object) -> str | None:
    value_type = type(value)
    if value_type is str:
        return cast(str, value)
    if value_type in _EXACT_BYTE_TYPES:
        return bytes(cast(Any, value)).decode("utf-8", errors="replace")
    if value_type in (int, float):
        return str(value)
    return None


def _unique_json_key(candidate: str, existing: dict[str, JSONValue]) -> str:
    if candidate not in existing:
        return candidate

    suffix = 2
    while True:
        unique = f"{candidate}#{suffix}"
        if unique not in existing:
            return unique
        suffix += 1


def _json_sort_key(value: JSONValue) -> str:
    return _json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
    )


def _safe_type_name(value: object) -> str:
    name = type(value).__name__ or "object"
    safe = _SAFE_TYPE_NAME_PATTERN.sub("_", name)[:80]
    return safe or "object"
