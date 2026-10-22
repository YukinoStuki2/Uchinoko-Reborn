"""URL redaction rule."""

from __future__ import annotations

import re

from logprivacy.rules.base import RegexRedactionRule

_URL_PATTERN = r"https?://[^\s'\"<>]+"


class UrlRule(RegexRedactionRule):
    """Detect HTTP and HTTPS URLs."""

    def __init__(self) -> None:
        super().__init__(
            name="url",
            category="url",
            pattern=re.compile(_URL_PATTERN, re.IGNORECASE),
            reason="text matched an HTTP or HTTPS URL",
        )
