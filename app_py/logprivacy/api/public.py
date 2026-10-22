"""Small public functions for the most common LogPrivacy use cases."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, TextIO

from logprivacy.audit import AuditReport
from logprivacy.cleaner import Cleaner
from logprivacy.exceptions import LogPrivacyAssertionError
from logprivacy.files import clean_file as _clean_file
from logprivacy.files import scan_file as _scan_file
from logprivacy.integrations.logging_filter import LogPrivacyFilter, install_handler_filters
from logprivacy.internal.rendering import (
    DEFAULT_MAX_RENDER_CHARS,
    DEFAULT_MAX_RENDER_ITEMS,
    safe_render_values,
    sanitize_output_text,
)
from logprivacy.policy import CleanerPolicy
from logprivacy.result import RedactionResult
from logprivacy.url import clean_url as _clean_url

_DEFAULT_CLEANER = Cleaner()


def clean(value: Any, *, policy: CleanerPolicy | None = None) -> Any:
    """
    Return a cleaned copy of a string or structured value.

    Accepts strings, dicts, lists, and tuples. Nested structures are traversed
    recursively. This is the most common entry point.

    Example::

        clean("email=john@example.com password=123")
        # "email=[EMAIL] password=[SECRET]"

        clean({"password": "123", "status": "ok"})
        # {"password": "[SECRET]", "status": "ok"}
    """
    cleaner = _DEFAULT_CLEANER if policy is None else Cleaner(policy=policy)
    return cleaner.clean(value)


def clean_text(text: str, *, policy: CleanerPolicy | None = None) -> str:
    """
    Return a cleaned string.

    Like ``clean()`` but always returns a string. Use this when you know the
    input is a string and want a typed return value.
    """
    cleaner = _DEFAULT_CLEANER if policy is None else Cleaner(policy=policy)
    return cleaner.clean_text(text)


def clean_with_result(
    text: str,
    *,
    policy: CleanerPolicy | None = None,
) -> RedactionResult[str]:
    """
    Return a ``RedactionResult`` containing the cleaned text and detected findings.

    Use this when you need to know what was redacted, not just the cleaned output.

    Example::

        result = clean_with_result("john@example.com")
        result.cleaned        # "[EMAIL]"
        result.finding_count  # 1
        result.categories     # ("email",)
    """
    cleaner = _DEFAULT_CLEANER if policy is None else Cleaner(policy=policy)
    return cleaner.clean_with_result(text)


def audit(value: Any, *, policy: CleanerPolicy | None = None) -> AuditReport:
    """
    Return an ``AuditReport`` describing sensitive data found in a value.

    Does not modify the input. Works on strings, dicts, lists, and tuples.
    Use this to check whether a value is safe to log before actually logging it.

    Example::

        report = audit({"password": "123"})
        report.safe        # False
        report.risk_level  # "high"
        report.categories  # ("credential",)
    """
    cleaner = _DEFAULT_CLEANER if policy is None else Cleaner(policy=policy)
    return cleaner.audit(value)


def explain(text: str, *, policy: CleanerPolicy | None = None) -> str:
    """
    Return a human-readable explanation of what ``clean()`` would redact.

    Useful for debugging policies and understanding why something is redacted.
    """
    cleaner = _DEFAULT_CLEANER if policy is None else Cleaner(policy=policy)
    return cleaner.explain(text)


def assert_clean(value: Any, *, policy: CleanerPolicy | None = None) -> None:
    """
    Raise ``LogPrivacyAssertionError`` if sensitive data is found in a value.

    Intended for tests and CI pipelines. Works on strings, dicts, lists, and
    tuples. Passes silently when the value is safe.

    Example::

        def test_response_payload_is_safe():
            assert_clean(response.json())
    """
    report = audit(value, policy=policy)
    if not report.safe:
        categories = ", ".join(report.categories)
        raise LogPrivacyAssertionError(
            f"Sensitive data found: {categories}",
            categories=report.categories,
        )


def safe_print(
    *values: Any,
    sep: str | None = " ",
    end: str | None = "\n",
    file: TextIO | None = None,
    flush: bool = False,
    policy: CleanerPolicy | None = None,
    max_items: int = DEFAULT_MAX_RENDER_ITEMS,
    max_chars: int = DEFAULT_MAX_RENDER_CHARS,
) -> None:
    """
    Print sanitized diagnostic values with bounded resource usage.

    ``safe_print`` mirrors the common ``print()`` arguments while deliberately
    using safe representations for arbitrary objects and containers. Control
    characters are escaped, recursive or hostile containers fail closed, and
    rendering is capped by ``max_items`` and ``max_chars``.

    Example::

        safe_print("token=abc123456789", {"password": "123456"})
        # token=[SECRET] {'password': '[SECRET]'}
    """
    cleaner = _DEFAULT_CLEANER if policy is None else Cleaner(policy=policy)
    raw_separator = " " if sep is None else sep
    raw_end = "\n" if end is None else end

    if not isinstance(raw_separator, str):
        raise TypeError(f"sep must be None or a string, not {type(raw_separator).__name__}")
    if not isinstance(raw_end, str):
        raise TypeError(f"end must be None or a string, not {type(raw_end).__name__}")

    safe_separator = sanitize_output_text(
        cleaner.clean_text(raw_separator),
        max_chars=max_chars,
    )
    safe_end = sanitize_output_text(
        cleaner.clean_text(raw_end),
        allow_newline=True,
        allow_tab=True,
        max_chars=max_chars,
    )
    rendered = safe_render_values(
        values,
        cleaner,
        separator=safe_separator,
        max_items=max_items,
        max_chars=max_chars,
    )
    print(rendered, end=safe_end, file=file, flush=flush)


def get_safe_logger(
    name: str | None = None,
    *,
    policy: CleanerPolicy | None = None,
    level: int | None = None,
    drop_blocked: bool | None = None,
) -> logging.Logger:
    """
    Return a stdlib logger protected by ``LogPrivacyFilter``.

    The logger's own records are cleaned directly. Filters scoped to its
    namespace are also installed on every currently configured handler in the
    propagation chain, protecting child loggers such as ``app.http`` while
    leaving unrelated logger namespaces unchanged.

    Call this function after configuring logging handlers. Calling it again is
    safe and refreshes handler protection. A second call without an explicit
    ``policy`` reuses the existing cleaner; an explicit policy replaces it.
    ``drop_blocked=False`` makes production block mode raise ``LogBlockedError``
    instead of silently dropping the record.

    Example::

        logger = get_safe_logger(__name__)
        logger.warning("User john@example.com used password=123456")
        # emits: User [EMAIL] used password=[SECRET]
    """
    logger = logging.getLogger(name)
    if level is not None:
        logger.setLevel(level)

    existing = next(
        (
            candidate
            for candidate in logger.filters
            if isinstance(candidate, LogPrivacyFilter) and candidate.logger_prefix is None
        ),
        None,
    )

    if existing is None:
        cleaner = Cleaner(policy=policy or CleanerPolicy.default())
        effective_drop_blocked = True if drop_blocked is None else drop_blocked
        existing = LogPrivacyFilter(
            cleaner=cleaner,
            drop_blocked=effective_drop_blocked,
        )
        logger.addFilter(existing)
    else:
        if policy is not None:
            existing.cleaner = Cleaner(policy=policy)
        if drop_blocked is not None:
            existing.drop_blocked = drop_blocked

        cleaner = existing.cleaner
        effective_drop_blocked = existing.drop_blocked

    install_handler_filters(
        logger,
        cleaner=cleaner,
        drop_blocked=effective_drop_blocked,
    )
    return logger


def clean_url(url: str, *, policy: CleanerPolicy | None = None, redact_full: bool = False) -> str:
    """Clean a URL while preserving safe context."""
    return _clean_url(url, policy=policy, redact_full=redact_full)


def scan_file(
    path: str | Path, *, policy: CleanerPolicy | None = None, encoding: str = "utf-8"
) -> AuditReport:
    """Scan a text file and return an audit report."""
    return _scan_file(path, policy=policy, encoding=encoding)


def clean_file(
    path: str | Path,
    *,
    output: str | Path,
    policy: CleanerPolicy | None = None,
    encoding: str = "utf-8",
) -> Path:
    """Clean a text file and write the cleaned output."""
    return _clean_file(path, output=output, policy=policy, encoding=encoding)
