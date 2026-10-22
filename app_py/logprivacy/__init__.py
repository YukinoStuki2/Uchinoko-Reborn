"""
LogPrivacy public API.

Simple by default, powerful by composition, safe by guidance.
"""

from __future__ import annotations

from logprivacy.adapters import AdapterRegistry
from logprivacy.api import (
    assert_clean,
    audit,
    clean,
    clean_file,
    clean_text,
    clean_url,
    clean_with_result,
    explain,
    get_safe_logger,
    safe_print,
    scan_file,
)
from logprivacy.audit import AuditReport
from logprivacy.cleaner import Cleaner
from logprivacy.exceptions import (
    JSONLProcessingError,
    LogBlockedError,
    LogPrivacyAssertionError,
    LogPrivacyError,
    PolicyConfigurationError,
    PseudonymizationConfigurationError,
    RuleValidationError,
)
from logprivacy.field_rules import FieldAction, FieldRule
from logprivacy.integrations.logging_filter import LogPrivacyFilter
from logprivacy.integrations.logging_formatter import LogPrivacyFormatter
from logprivacy.json import safe_json_dump, safe_json_dumps
from logprivacy.jsonl import clean_jsonl, iter_safe_jsonl, safe_jsonl_write, scan_jsonl
from logprivacy.masking.strategy import (
    HashMaskingStrategy,
    HMACMaskingStrategy,
    PartialMaskingStrategy,
    PlaceholderMaskingStrategy,
)
from logprivacy.path_rules import PathAction, PathRule
from logprivacy.policy import CleanerPolicy
from logprivacy.result import (
    Finding,
    JSONLRecord,
    JSONLResult,
    JSONLScanRecord,
    JSONLStats,
    RedactionResult,
    SafeDataResult,
    SafeDataStats,
)
from logprivacy.rules.custom import CustomRegexRule
from logprivacy.rules.email import EmailRule
from logprivacy.rules.secret import SecretRule
from logprivacy.rules.token import TokenRule
from logprivacy.rules.url import UrlRule
from logprivacy.safe_data import to_safe_data, to_safe_data_with_result
from logprivacy.typing import JSONScalar, JSONValue

__all__ = [
    "AdapterRegistry",
    "AuditReport",
    "Cleaner",
    "CleanerPolicy",
    "CustomRegexRule",
    "EmailRule",
    "FieldAction",
    "FieldRule",
    "Finding",
    "HMACMaskingStrategy",
    "HashMaskingStrategy",
    "JSONLProcessingError",
    "JSONLRecord",
    "JSONLResult",
    "JSONLScanRecord",
    "JSONLStats",
    "JSONScalar",
    "JSONValue",
    "LogBlockedError",
    "LogPrivacyAssertionError",
    "LogPrivacyError",
    "LogPrivacyFilter",
    "LogPrivacyFormatter",
    "PartialMaskingStrategy",
    "PathAction",
    "PathRule",
    "PlaceholderMaskingStrategy",
    "PolicyConfigurationError",
    "PseudonymizationConfigurationError",
    "RedactionResult",
    "RuleValidationError",
    "SafeDataResult",
    "SafeDataStats",
    "SecretRule",
    "TokenRule",
    "UrlRule",
    "assert_clean",
    "audit",
    "clean",
    "clean_file",
    "clean_jsonl",
    "clean_text",
    "clean_url",
    "clean_with_result",
    "explain",
    "get_safe_logger",
    "iter_safe_jsonl",
    "safe_jsonl_write",
    "safe_print",
    "safe_json_dump",
    "safe_json_dumps",
    "scan_file",
    "scan_jsonl",
    "to_safe_data",
    "to_safe_data_with_result",
]

__version__ = "0.6.0"
