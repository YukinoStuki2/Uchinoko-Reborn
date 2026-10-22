"""Python logging formatter that redacts the final formatted message."""

from __future__ import annotations

import copy
import logging
from dataclasses import dataclass, field

from logprivacy.cleaner import Cleaner
from logprivacy.integrations.logging_filter import LogPrivacyFilter


@dataclass(slots=True)
class LogPrivacyFormatter(logging.Formatter):
    """Formatter that cleans the final formatted output."""

    cleaner: Cleaner = field(default_factory=Cleaner)

    def __post_init__(self) -> None:
        logging.Formatter.__init__(self)

    def format(self, record: logging.LogRecord) -> str:
        """Format a sanitized copy while preserving multiline diagnostic fields."""
        safe_record = copy.copy(record)
        LogPrivacyFilter(cleaner=self.cleaner, drop_blocked=False).filter(safe_record)
        return logging.Formatter.format(self, safe_record)
