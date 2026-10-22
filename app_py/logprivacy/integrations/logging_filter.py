"""Python logging filter that redacts sensitive data before emission."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Iterator
from dataclasses import dataclass, field

from logprivacy.cleaner import Cleaner
from logprivacy.exceptions import LogBlockedError
from logprivacy.internal.logging_values import LoggingValueSanitizer
from logprivacy.internal.rendering import (
    DEFAULT_MAX_RENDER_CHARS,
    safe_render,
    sanitize_output_text,
)
from logprivacy.masking.value import mask_sensitive_value


def _build_standard_record_attributes() -> frozenset[str]:
    """Return the stdlib attributes that are not user supplied through ``extra``."""
    sample = logging.LogRecord(
        name="logprivacy",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="",
        args=(),
        exc_info=None,
    )
    return frozenset((*sample.__dict__, "message", "asctime"))


_STANDARD_RECORD_ATTRIBUTES = _build_standard_record_attributes()


def _sanitize_value(value: object, cleaner: Cleaner) -> object:
    """Return one bounded logging-safe value using the hardened sanitizer."""
    return LoggingValueSanitizer(cleaner).sanitize(value)


def _sanitize_message(record: logging.LogRecord, sanitizer: LoggingValueSanitizer) -> None:
    """Render and clean a message without exposing failing or truncated arguments."""
    original_message = record.msg
    if type(original_message) is str:
        record.msg = original_message
    else:
        try:
            message_template = str(original_message)
        except Exception:
            message_template = f"<unprintable {type(original_message).__name__}>"
        record.msg = sanitize_output_text(
            message_template,
            allow_newline=True,
            allow_tab=True,
            max_chars=DEFAULT_MAX_RENDER_CHARS,
        )

    try:
        record.args = sanitizer.sanitize_args(record.args)
        rendered = record.getMessage()
    except LogBlockedError:
        raise
    except Exception:
        rendered = safe_render(
            original_message,
            sanitizer.cleaner,
            max_items=sanitizer.cleaner.policy.max_items,
            max_chars=DEFAULT_MAX_RENDER_CHARS,
        )

    cleaned = sanitizer.cleaner.clean_text(rendered)
    record.msg = sanitize_output_text(
        cleaned,
        max_chars=DEFAULT_MAX_RENDER_CHARS,
    )
    # Formatters must never interpolate the original values a second time.
    record.args = ()


def _sanitize_exception(record: logging.LogRecord, cleaner: Cleaner) -> None:
    """Render, clean, and cache exception text before any formatter sees it."""
    if record.exc_info:
        try:
            rendered = "".join(traceback.format_exception(*record.exc_info)).rstrip()
        except Exception:
            rendered = "[UNAVAILABLE]"
        finally:
            # Prevent a formatter from rebuilding the traceback from the original
            # exception object after a safe value has been produced.
            record.exc_info = None

        cleaned = cleaner.clean_text(rendered)
        record.exc_text = sanitize_output_text(
            cleaned,
            allow_newline=True,
            allow_tab=True,
            max_chars=DEFAULT_MAX_RENDER_CHARS,
        )
    elif record.exc_text:
        rendered = safe_render(
            record.exc_text,
            cleaner,
            max_items=cleaner.policy.max_items,
            max_chars=DEFAULT_MAX_RENDER_CHARS,
        )
        cleaned = cleaner.clean_text(rendered)
        record.exc_text = sanitize_output_text(
            cleaned,
            allow_newline=True,
            allow_tab=True,
            max_chars=DEFAULT_MAX_RENDER_CHARS,
        )


def _sanitize_extra_attributes(record: logging.LogRecord, sanitizer: LoggingValueSanitizer) -> None:
    """Clean user-provided ``extra`` fields in place."""
    for key in tuple(record.__dict__):
        if key in _STANDARD_RECORD_ATTRIBUTES:
            continue

        if sanitizer.cleaner.policy.is_sensitive_key(key):
            record.__dict__[key] = mask_sensitive_value(
                record.__dict__[key],
                category="credential",
                rule_name="logging_extra",
                reason="value belongs to a sensitive LogRecord attribute",
                policy=sanitizer.cleaner.policy,
            )
        else:
            record.__dict__[key] = sanitizer.sanitize(record.__dict__[key])


def _matches_logger_namespace(record_name: str, logger_prefix: str | None) -> bool:
    """Return whether a record belongs to a configured logger namespace."""
    if logger_prefix is None:
        return True
    return record_name == logger_prefix or record_name.startswith(f"{logger_prefix}.")


@dataclass(slots=True)
class LogPrivacyFilter(logging.Filter):
    """
    Clean every sensitive component of a ``LogRecord`` before formatting.

    Besides the rendered message, the filter sanitizes format arguments,
    exception tracebacks, stack information, and custom ``extra`` attributes.
    ``logger_prefix`` is used internally by ``get_safe_logger()`` when attaching
    a scoped filter to shared handlers so child loggers are protected without
    modifying unrelated namespaces.
    """

    cleaner: Cleaner = field(default_factory=Cleaner)
    drop_blocked: bool = True
    logger_prefix: str | None = None

    def filter(self, record: logging.LogRecord) -> bool:
        """Clean the complete record and allow it to be emitted."""
        if not _matches_logger_namespace(record.name, self.logger_prefix):
            return True

        try:
            sanitizer = LoggingValueSanitizer(self.cleaner)
            _sanitize_message(record, sanitizer)
            _sanitize_exception(record, self.cleaner)

            if record.stack_info:
                rendered_stack = safe_render(
                    record.stack_info,
                    self.cleaner,
                    max_items=self.cleaner.policy.max_items,
                    max_chars=DEFAULT_MAX_RENDER_CHARS,
                )
                cleaned_stack = self.cleaner.clean_text(rendered_stack)
                record.stack_info = sanitize_output_text(
                    cleaned_stack,
                    allow_newline=True,
                    allow_tab=True,
                    max_chars=DEFAULT_MAX_RENDER_CHARS,
                )

            _sanitize_extra_attributes(record, sanitizer)
        except LogBlockedError:
            if self.drop_blocked:
                return False
            raise

        return True


def _iter_effective_handlers(logger: logging.Logger) -> Iterator[logging.Handler]:
    """Yield each handler that can receive records from ``logger`` exactly once."""
    seen: set[int] = set()
    current: logging.Logger | None = logger

    while current is not None:
        for handler in current.handlers:
            handler_id = id(handler)
            if handler_id not in seen:
                seen.add(handler_id)
                yield handler

        if not current.propagate:
            break
        current = current.parent


def install_handler_filters(
    logger: logging.Logger,
    *,
    cleaner: Cleaner,
    drop_blocked: bool,
) -> None:
    """Protect configured handlers for ``logger`` and all of its child loggers."""
    root_logger = logging.getLogger()
    logger_prefix = None if logger is root_logger else logger.name

    for handler in _iter_effective_handlers(logger):
        existing = next(
            (
                candidate
                for candidate in handler.filters
                if isinstance(candidate, LogPrivacyFilter)
                and candidate.logger_prefix == logger_prefix
            ),
            None,
        )
        if existing is None:
            handler.addFilter(
                LogPrivacyFilter(
                    cleaner=cleaner,
                    drop_blocked=drop_blocked,
                    logger_prefix=logger_prefix,
                )
            )
        else:
            existing.cleaner = cleaner
            existing.drop_blocked = drop_blocked
