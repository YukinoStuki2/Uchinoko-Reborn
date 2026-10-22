"""Base classes for redaction rules."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from re import Pattern

from logprivacy.internal.matches import _DetectedMatch
from logprivacy.masking.strategy import MaskingStrategy


class RedactionRule:
    """Base class for objects that find sensitive values in text."""

    name: str
    category: str

    def find(self, text: str) -> tuple[_DetectedMatch, ...]:
        """Return all matches detected in text as internal DetectedMatch objects."""
        raise NotImplementedError

    def replacement_for(self, match: _DetectedMatch, masking: MaskingStrategy) -> str:
        """Return replacement text for a detected match."""
        return masking.mask_value(match.matched, match.category)


@dataclass(frozen=True, slots=True)
class RegexRedactionRule(RedactionRule):
    """Redaction rule backed by a compiled regular expression."""

    name: str
    category: str
    pattern: Pattern[str] = field(repr=False)
    reason: str = ""

    @classmethod
    def from_pattern(
        cls,
        *,
        name: str,
        category: str,
        pattern: str,
        flags: int = 0,
        reason: str = "",
    ) -> RegexRedactionRule:
        """Create a regex rule from a pattern string."""
        return cls(name=name, category=category, pattern=re.compile(pattern, flags), reason=reason)

    def find(self, text: str) -> tuple[_DetectedMatch, ...]:
        """Return regex matches as internal DetectedMatch objects."""
        return tuple(
            _DetectedMatch(
                rule_name=self.name,
                category=self.category,
                start=match.start(),
                end=match.end(),
                matched=match.group(0),
                reason=self.reason,
            )
            for match in self.pattern.finditer(text)
        )

    def replacement_for(self, match: _DetectedMatch, masking: MaskingStrategy) -> str:
        """Return replacement via the masking strategy."""
        return masking.mask_value(match.matched, match.category)
