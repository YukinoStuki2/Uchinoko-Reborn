"""Credential key/value redaction rule."""

from __future__ import annotations

import re

from logprivacy.internal.matches import _DetectedMatch
from logprivacy.masking.strategy import MaskingStrategy
from logprivacy.masking.value import mask_concrete_value
from logprivacy.rules.base import RedactionRule

_AUTHORIZATION_PATTERN = re.compile(
    r"(?P<key>\b(?:authorization|proxy[-_]?authorization)\b)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<quote>['\"]?)"
    r"(?P<scheme>Bearer|Basic)"
    r"(?P<scheme_sep>\s+)"
    r"(?P<value>[^'\"\s,;&]+)"
    r"(?P=quote)",
    re.IGNORECASE,
)

_CREDENTIAL_PATTERN = re.compile(
    r"(?P<key>\b(?:password|passwd|pwd|secret|api_key|apikey|access_key|access_token|"
    r"refresh_token|token|client_secret|private_key|auth_token|authorization|cookie|set-cookie)\b)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<quote>['\"]?)"
    r"(?P<value>[^'\"\s,;&]+)"
    r"(?P=quote)",
    re.IGNORECASE,
)


def _ranges_overlap(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    """Return whether ``[start, end)`` overlaps any protected range."""
    return any(
        start < protected_end and protected_start < end for protected_start, protected_end in ranges
    )


class CredentialRule(RedactionRule):
    """Detect values assigned to credential-like keys."""

    name = "credential"
    category = "credential"

    def find(self, text: str) -> tuple[_DetectedMatch, ...]:
        """Return credential assignments as internal matches."""
        matches: list[_DetectedMatch] = []
        authorization_ranges: list[tuple[int, int]] = []

        for match in _AUTHORIZATION_PATTERN.finditer(text):
            scheme = match.group("scheme")
            category = "token" if scheme.casefold() == "bearer" else "credential"
            matches.append(
                _DetectedMatch(
                    rule_name=self.name,
                    category=category,
                    start=match.start(),
                    end=match.end(),
                    matched=match.group(0),
                    reason=f"authorization scheme {scheme!r} carries a sensitive credential",
                    metadata={
                        "kind": "authorization",
                        "key": match.group("key"),
                        "sep": match.group("sep"),
                        "quote": match.group("quote"),
                        "scheme": scheme,
                        "scheme_sep": match.group("scheme_sep"),
                        "value": match.group("value"),
                    },
                )
            )
            authorization_ranges.append((match.start(), match.end()))

        for match in _CREDENTIAL_PATTERN.finditer(text):
            if _ranges_overlap(match.start(), match.end(), authorization_ranges):
                continue

            matches.append(
                _DetectedMatch(
                    rule_name=self.name,
                    category=self.category,
                    start=match.start(),
                    end=match.end(),
                    matched=match.group(0),
                    reason=f"key {match.group('key')!r} is considered sensitive",
                    metadata={
                        "key": match.group("key"),
                        "sep": match.group("sep"),
                        "quote": match.group("quote"),
                        "value": match.group("value"),
                    },
                )
            )
        return tuple(matches)

    def replacement_for(self, match: _DetectedMatch, masking: MaskingStrategy) -> str:
        """Keep the credential key visible and redact only the concrete value."""
        key = match.metadata.get("key", "secret")
        sep = match.metadata.get("sep", "=")
        quote = match.metadata.get("quote", "")
        value = match.metadata.get("value", "")

        replacement = mask_concrete_value(
            value,
            category=match.category,
            rule_name=match.rule_name,
            reason=match.reason,
            masking=masking,
        )

        if match.metadata.get("kind") == "authorization":
            scheme = match.metadata.get("scheme", "")
            scheme_sep = match.metadata.get("scheme_sep", " ")
            return f"{key}{sep}{quote}{scheme}{scheme_sep}{replacement}{quote}"

        return f"{key}{sep}{quote}{replacement}{quote}"
