"""Custom user-defined redaction rules."""

from __future__ import annotations

import re

from logprivacy.rules.base import RegexRedactionRule


class CustomRegexRule(RegexRedactionRule):
    """Create a redaction rule from a custom regular expression."""

    def __init__(
        self,
        *,
        name: str,
        category: str,
        pattern: str,
        flags: int = 0,
        reason: str = "text matched a custom redaction rule",
    ) -> None:
        super().__init__(
            name=name,
            category=category,
            pattern=re.compile(pattern, flags),
            reason=reason,
        )
