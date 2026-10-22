"""Strict rules for sensitive environments."""

from __future__ import annotations

from logprivacy.rule_sets.default import default_rules
from logprivacy.rules import IPAddressRule, PhoneRule
from logprivacy.rules.base import RedactionRule


def strict_rules() -> tuple[RedactionRule, ...]:
    """Return a stricter rule set that also redacts IP addresses and phone numbers."""
    return (*default_rules(), IPAddressRule(), PhoneRule())
