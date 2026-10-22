"""Exceptions raised by LogPrivacy."""

from __future__ import annotations


class LogPrivacyError(Exception):
    """Base exception for LogPrivacy errors."""


class RuleValidationError(LogPrivacyError):
    """Raised when a redaction rule is invalid."""


class LogBlockedError(LogPrivacyError):
    """Raised when block mode prevents a sensitive value from being logged."""

    def __init__(self, message: str, *, categories: tuple[str, ...]) -> None:
        super().__init__(message)
        self.categories = categories


class LogPrivacyAssertionError(AssertionError):
    """Raised by assert_clean() when sensitive data is found."""

    def __init__(self, message: str, *, categories: tuple[str, ...]) -> None:
        super().__init__(message)
        self.categories = categories


class PolicyConfigurationError(LogPrivacyError):
    """Raised when a policy is misconfigured (e.g., invalid declarative policy schema)."""


class JSONLProcessingError(LogPrivacyError):
    """Raised by JSONL streaming when on_error='raise' and a line cannot be processed.

    Never contains the raw line content.
    """

    def __init__(self, message: str, *, line_number: int, reason: str) -> None:
        super().__init__(message)
        self.line_number = line_number
        self.reason = reason


class PseudonymizationConfigurationError(LogPrivacyError):
    """Raised when pseudonymize action is used but no pseudonymizer is configured."""
