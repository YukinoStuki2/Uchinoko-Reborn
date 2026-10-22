"""Public path-based field rules for structured sanitization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

from logprivacy.field_rules.rules import normalize_field_name

PathAction: TypeAlias = Literal["mask", "remove", "truncate", "block", "pseudonymize"]
PathMatchMode: TypeAlias = Literal["exact", "glob"]

_VALID_PATH_ACTIONS: frozenset[str] = frozenset(
    {"mask", "remove", "truncate", "block", "pseudonymize"}
)
_VALID_PATH_MODES: frozenset[str] = frozenset({"exact", "glob"})

# Internal type: path elements from traversal
# (dict keys/dataclass names are str, list indices are int)
_TraversalPath: TypeAlias = tuple[str | int, ...]


@dataclass(frozen=True, slots=True)
class PathRule:
    """Rule that applies a privacy action based on the full field path.

    Paths are dot-separated segments: ``"account.balance"`` or ``"orders.*.order_id"``.
    The ``*`` wildcard matches exactly one segment of any value (only in glob mode).

    Field name segments are normalized the same way as ``FieldRule``:
    camelCase is split, separators are unified, case is folded.
    List/sequence indices are matched as their string representation (``"0"``, ``"1"``).

    Example::

        PathRule.exact("account.balance", action="remove")
        PathRule.glob("orders.*.order_id", action="pseudonymize", category="order_id")
    """

    path: str
    action: PathAction = "mask"
    mode: PathMatchMode = "exact"
    max_chars: int | None = None
    category: str = ""
    _segments: tuple[str, ...] = field(default=(), init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.action not in _VALID_PATH_ACTIONS:
            raise ValueError(
                f"path rule action must be one of: {', '.join(sorted(_VALID_PATH_ACTIONS))}"
            )
        if self.mode not in _VALID_PATH_MODES:
            raise ValueError("path rule mode must be one of: exact, glob")
        if self.action == "truncate":
            if isinstance(self.max_chars, bool) or not isinstance(self.max_chars, int):
                raise ValueError("truncate path rules require max_chars as an integer")
            if self.max_chars < 0:
                raise ValueError("max_chars must be >= 0")
        elif self.max_chars is not None:
            raise ValueError("max_chars is only supported for truncate path rules")

        segments = _parse_rule_path(self.path, mode=self.mode)
        object.__setattr__(self, "_segments", segments)

    @classmethod
    def exact(
        cls,
        path: str,
        *,
        action: PathAction = "mask",
        max_chars: int | None = None,
        category: str = "",
    ) -> PathRule:
        """Create a rule that matches an exact field path."""
        return cls(path=path, action=action, mode="exact", max_chars=max_chars, category=category)

    @classmethod
    def glob(
        cls,
        path: str,
        *,
        action: PathAction = "mask",
        max_chars: int | None = None,
        category: str = "",
    ) -> PathRule:
        """Create a rule that matches a field path with ``*`` wildcards."""
        return cls(path=path, action=action, mode="glob", max_chars=max_chars, category=category)

    def matches_traversal_path(self, path: _TraversalPath) -> bool:
        """Return whether this rule matches the given traversal path.

        Traversal paths contain strings (from dict keys, dataclass field names,
        exception fields) and integers (from list/tuple/set indices).
        Integers are converted to strings for comparison.
        """
        segments = self._segments
        if len(segments) != len(path):
            return False
        for rule_seg, path_seg in zip(segments, path, strict=False):
            if rule_seg == "*":
                continue
            path_str = (
                str(path_seg) if isinstance(path_seg, int) else normalize_field_name(path_seg)
            )
            if rule_seg != path_str:
                return False
        return True


def _parse_rule_path(path_str: str, *, mode: str) -> tuple[str, ...]:
    """Parse and validate a rule path string into normalized segments."""
    if not path_str:
        raise ValueError("path rule path must not be empty")
    if path_str.startswith("."):
        raise ValueError("path rule path must not start with '.'")
    if path_str.endswith("."):
        raise ValueError("path rule path must not end with '.'")
    if ".." in path_str:
        raise ValueError("path rule path must not contain '..'")

    segments: list[str] = []
    for seg in path_str.split("."):
        if not seg:
            raise ValueError(f"empty segment in path rule path {path_str!r}")
        if seg == "**":
            raise ValueError("'**' is not supported in path rules; use '*' for a single segment")
        if "*" in seg and seg != "*":
            raise ValueError(
                f"partial wildcard {seg!r} is not supported; use '*' for a full segment"
            )
        if seg == "*":
            if mode == "exact":
                raise ValueError("wildcards are not allowed in exact path rules; use glob mode")
            segments.append("*")
        else:
            norm = normalize_field_name(seg)
            if not norm:
                raise ValueError(f"path segment {seg!r} normalizes to empty string")
            segments.append(norm)

    return tuple(segments)
