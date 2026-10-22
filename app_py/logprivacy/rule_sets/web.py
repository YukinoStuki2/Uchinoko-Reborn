"""Rules focused on web applications and HTTP logs."""

from __future__ import annotations

from logprivacy.rules import CredentialRule, SecretRule, TokenRule, UrlRule
from logprivacy.rules.base import RedactionRule


def web_rules() -> tuple[RedactionRule, ...]:
    """Return web-focused rules for URLs, tokens, credentials, and secrets."""
    return (
        UrlRule(),
        CredentialRule(),
        TokenRule(),
        SecretRule(),
    )
