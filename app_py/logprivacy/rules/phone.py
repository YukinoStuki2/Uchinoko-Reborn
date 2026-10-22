"""Phone number redaction rule."""

from __future__ import annotations

import re

from logprivacy.rules.base import RegexRedactionRule

_PHONE_PATTERN = (
    r"(?<!\d)"
    r"(?:\+?\d{1,3}[-.\s]?)?"
    r"(?:\(?\d{2,4}\)?[-.\s]?)"
    r"\d{3,4}[-.\s]?\d{4}"
    r"(?!\d)"
)


class PhoneRule(RegexRedactionRule):
    """Detect common phone-like values."""

    def __init__(self) -> None:
        super().__init__(
            name="phone",
            category="phone",
            pattern=re.compile(_PHONE_PATTERN),
            reason="text matched a phone-like pattern",
        )
