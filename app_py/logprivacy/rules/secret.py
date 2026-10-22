"""Common secret redaction rule."""

from __future__ import annotations

import re

from logprivacy.rules.base import RegexRedactionRule

_SECRET_PATTERN = (
    r"\b(?:"
    r"sk_live_[A-Za-z0-9_-]{8,}|"
    r"sk_test_[A-Za-z0-9_-]{8,}|"
    r"sk-[A-Za-z0-9_-]{16,}|"
    r"ghp_[A-Za-z0-9_]{20,}|"
    r"gho_[A-Za-z0-9_]{20,}|"
    r"ghu_[A-Za-z0-9_]{20,}|"
    r"ghs_[A-Za-z0-9_]{20,}|"
    r"ghr_[A-Za-z0-9_]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"ASIA[0-9A-Z]{16}"
    r")\b"
)


class SecretRule(RegexRedactionRule):
    """Detect common API-key and secret formats."""

    def __init__(self) -> None:
        super().__init__(
            name="secret",
            category="secret",
            pattern=re.compile(_SECRET_PATTERN),
            reason="text matched a known secret/token pattern",
        )
