"""Internal allowlist matching for structured traversal."""

from __future__ import annotations

from typing import Literal, TypeAlias

from logprivacy.field_rules.rules import normalize_field_name

_TraversalPath: TypeAlias = tuple[str | int, ...]
_AllowlistPathMatch: TypeAlias = Literal["none", "prefix", "exact"]


class _AllowlistMatcher:
    """Pre-compiled allowlist for fast field-path checking.

    Allowlist paths are dot-separated patterns that may use ``*`` as a
    single-segment wildcard: ``"orders.*.status"``.

    ``match_path()`` distinguishes three states:

    - ``"exact"``: the current path is explicitly allowed;
    - ``"prefix"``: the current path is a parent of allowed descendants;
    - ``"none"``: the current path is not covered by the allowlist.

    Distinguishing exact matches from parent prefixes is important for safe
    traversal. A scalar value at a prefix-only path cannot contain the allowed
    descendant and must not be emitted merely because its path is a prefix.
    """

    __slots__ = ("_patterns",)

    def __init__(self, patterns: tuple[str, ...]) -> None:
        self._patterns: tuple[tuple[str, ...], ...] = tuple(
            _parse_allowlist_path(pattern) for pattern in patterns
        )

    def match_path(self, path: _TraversalPath) -> _AllowlistPathMatch:
        """Return whether ``path`` is exact, a parent prefix, or not covered."""
        if not self._patterns:
            return "none"

        normalized_path = _normalize_traversal_path(path)
        has_prefix_match = False

        for pattern in self._patterns:
            match = _match_normalized_path(normalized_path, pattern)
            if match == "exact":
                return "exact"
            if match == "prefix":
                has_prefix_match = True

        return "prefix" if has_prefix_match else "none"

    def is_path_allowed(self, path: _TraversalPath) -> bool:
        """Return whether ``path`` is explicitly allowed or leads to allowed content.

        This compatibility helper preserves the previous boolean API. Traversal
        code that needs to decide whether a scalar may be emitted should use
        ``match_path()`` so it can distinguish an exact match from a parent
        prefix.
        """
        return self.match_path(path) != "none"


def _normalize_traversal_path(path: _TraversalPath) -> tuple[str, ...]:
    normalized_segments: list[str] = []
    for segment in path:
        if isinstance(segment, int):
            normalized_segments.append(str(segment))
        else:
            normalized_segments.append(normalize_field_name(segment))
    return tuple(normalized_segments)


def _match_normalized_path(
    normalized_path: tuple[str, ...],
    pattern: tuple[str, ...],
) -> _AllowlistPathMatch:
    """Match an already-normalized traversal path against one pattern."""
    path_length = len(normalized_path)
    pattern_length = len(pattern)

    if path_length > pattern_length:
        return "none"

    for pattern_segment, path_segment in zip(pattern[:path_length], normalized_path, strict=False):
        if pattern_segment != "*" and pattern_segment != path_segment:
            return "none"

    if path_length == pattern_length:
        return "exact"
    return "prefix"


def _path_matches_or_prefixes_pattern(
    norm_path: tuple[str, ...],
    pattern: tuple[str, ...],
) -> bool:
    """Compatibility wrapper for the previous private helper."""
    return _match_normalized_path(norm_path, pattern) != "none"


def _parse_allowlist_path(path_str: str) -> tuple[str, ...]:
    """Parse an allowlist path into normalized segments."""
    if not path_str:
        raise ValueError("allowlist path must not be empty")
    if path_str.startswith(".") or path_str.endswith("."):
        raise ValueError(f"allowlist path {path_str!r} must not start or end with '.'")
    if ".." in path_str:
        raise ValueError(f"allowlist path {path_str!r} must not contain '..'")

    segments: list[str] = []
    for segment in path_str.split("."):
        if not segment:
            raise ValueError(f"empty segment in allowlist path {path_str!r}")
        if segment == "**":
            raise ValueError("'**' is not supported in allowlist paths; use '*'")
        if "*" in segment and segment != "*":
            raise ValueError(f"partial wildcard {segment!r} in allowlist path {path_str!r}")
        if segment == "*":
            segments.append("*")
            continue

        normalized_segment = normalize_field_name(segment)
        if not normalized_segment:
            raise ValueError(f"allowlist segment {segment!r} normalizes to empty string")
        segments.append(normalized_segment)

    return tuple(segments)
