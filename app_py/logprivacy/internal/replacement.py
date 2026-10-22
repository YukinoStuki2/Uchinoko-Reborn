"""Backward-compatible helpers for applying redactions safely.

The canonical implementation now lives in ``logprivacy.internal.pipeline``.
These wrappers preserve the internal call-sites in ``Cleaner`` and structured
traversal helpers that have not yet been migrated to the new pipeline API.
"""

from __future__ import annotations

from logprivacy.internal.matches import _DetectedMatch
from logprivacy.internal.pipeline import FindingResolver
from logprivacy.masking.strategy import MaskingStrategy
from logprivacy.result import Finding
from logprivacy.rules.base import RedactionRule

_resolver = FindingResolver()


def select_non_overlapping(
    matches: tuple[_DetectedMatch, ...],
) -> tuple[_DetectedMatch, ...]:
    """Return non-overlapping matches using the canonical FindingResolver."""
    return _resolver.resolve(matches)


def apply_replacements(
    text: str,
    matches: tuple[_DetectedMatch, ...],
    *,
    rules: tuple[RedactionRule, ...],
    masking: MaskingStrategy,
) -> tuple[str, tuple[Finding, ...]]:
    """Apply matches to text right-to-left, return (cleaned_text, public_findings).

    The rule used for each replacement is looked up from ``rules`` by name.
    ``rules`` must have been validated for uniqueness before this call (the
    RuleSet enforces this; ad-hoc callers must ensure it themselves).
    """
    if not matches:
        return text, ()

    rules_by_name = {rule.name: rule for rule in rules}
    resolved: list[Finding] = []

    cleaned = text
    for match in reversed(matches):
        rule = rules_by_name[match.rule_name]
        replacement = rule.replacement_for(match, masking)
        cleaned = f"{cleaned[: match.start]}{replacement}{cleaned[match.end :]}"
        finding = Finding(
            rule_name=match.rule_name,
            category=match.category,
            start=match.start,
            end=match.end,
            replacement=replacement,
            reason=match.reason,
            metadata=dict(match.metadata),
        )
        resolved.append(finding)

    return cleaned, tuple(reversed(resolved))
