"""Immutable, validated ordered container for redaction rules."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

from logprivacy.exceptions import RuleValidationError

if TYPE_CHECKING:
    from logprivacy.rules.base import RedactionRule


class RuleSet:
    """An ordered, immutable, validated set of redaction rules.

    Duplicate rule names and invalid rules are rejected at construction time
    so that downstream code can rely on uniqueness guarantees without
    rechecking on every clean operation.
    """

    _rules: tuple[RedactionRule, ...]
    _index: dict[str, RedactionRule]
    __slots__ = ("_rules", "_index")

    def __init__(self, rules: tuple[RedactionRule, ...]) -> None:
        _validate_rules(rules)
        object.__setattr__(self, "_rules", rules)
        object.__setattr__(self, "_index", {rule.name: rule for rule in rules})

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError(f"{type(self).__name__!r} is immutable")

    # ------------------------------------------------------------------
    # Sequence-like interface
    # ------------------------------------------------------------------

    def __iter__(self) -> Iterator[RedactionRule]:
        return iter(self._rules)

    def __len__(self) -> int:
        return len(self._rules)

    def __contains__(self, rule: object) -> bool:
        return rule in self._rules

    def __repr__(self) -> str:
        names = [rule.name for rule in self._rules]
        return f"RuleSet({names!r})"

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get(self, name: str) -> RedactionRule | None:
        """Return the rule with this name, or None if not present."""
        return self._index.get(name)

    def __getitem__(self, name: str) -> RedactionRule:
        """Return the rule with this name; raise KeyError if absent."""
        try:
            return self._index[name]
        except KeyError:
            raise KeyError(f"No rule named {name!r} in this RuleSet") from None

    # ------------------------------------------------------------------
    # Composition (returns new RuleSet; does not mutate)
    # ------------------------------------------------------------------

    def append(self, *rules: RedactionRule) -> RuleSet:
        """Return a new RuleSet with additional rules appended."""
        return RuleSet((*self._rules, *rules))

    def as_tuple(self) -> tuple[RedactionRule, ...]:
        """Return a read-only tuple view of the rules in order."""
        return self._rules


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_rules(rules: tuple[RedactionRule, ...]) -> None:
    """Raise RuleValidationError for any structural problem in the rule list."""
    seen_names: set[str] = set()

    for index, rule in enumerate(rules):
        _validate_rule_contract(rule, index)

        name = rule.name
        category = rule.category

        if not isinstance(name, str) or not name.strip():
            raise RuleValidationError(f"Rule at index {index} has an empty or non-string name")
        if not isinstance(category, str) or not category.strip():
            raise RuleValidationError(
                f"Rule {name!r} at index {index} has an empty or non-string category"
            )
        if name in seen_names:
            raise RuleValidationError(f"Duplicate rule name {name!r} at index {index}")
        seen_names.add(name)


def _validate_rule_contract(rule: object, index: int) -> None:
    """Raise RuleValidationError when an object does not satisfy the rule contract."""
    if not hasattr(rule, "name"):
        raise RuleValidationError(
            f"Object at index {index} ({type(rule).__name__!r}) is missing 'name'"
        )
    if not hasattr(rule, "category"):
        raise RuleValidationError(
            f"Object at index {index} ({type(rule).__name__!r}) is missing 'category'"
        )
    if not hasattr(rule, "find") or not callable(getattr(rule, "find", None)):
        raise RuleValidationError(
            f"Object at index {index} ({type(rule).__name__!r}) is missing callable 'find'"
        )
    has_replacement = hasattr(rule, "replacement_for") and callable(
        getattr(rule, "replacement_for", None)
    )
    if not has_replacement:
        raise RuleValidationError(
            f"Object at index {index} ({type(rule).__name__!r})"
            " is missing callable 'replacement_for'"
        )
