"""URL sanitization helpers."""

from __future__ import annotations

from unicodedata import category as unicode_category
from urllib.parse import parse_qsl, quote_plus, urlsplit, urlunsplit

from logprivacy.cleaner import Cleaner
from logprivacy.masking.value import mask_sensitive_value
from logprivacy.policy import CleanerPolicy

# URL-specific secret names that are not always appropriate as global mapping
# keys.  ``CleanerPolicy.is_sensitive_key()`` remains the primary source of
# truth, while this set covers OAuth, signed URL, and session parameters.
_URL_ONLY_SENSITIVE_KEYS = frozenset(
    {
        "auth",
        "auth_token",
        "authorization_code",
        "code",
        "id_token",
        "key",
        "session",
        "session_id",
        "sig",
        "signature",
    }
)


def _normalize_key(key: str) -> str:
    """Return a canonical representation used for sensitive-key checks."""
    return key.strip().casefold().replace("-", "_")


def _is_sensitive_parameter(key: str, policy: CleanerPolicy) -> bool:
    """Return whether a URL parameter must be fully redacted."""
    normalized = _normalize_key(key)
    return policy.is_sensitive_key(key) or normalized in _URL_ONLY_SENSITIVE_KEYS


def _category_for_parameter(key: str) -> str:
    """Return the masking category used for a sensitive URL parameter."""
    return "email" if _normalize_key(key) == "email" else "secret"


def _mask_value(cleaner: Cleaner, value: str, *, category: str, reason: str) -> str:
    """Mask one concrete URL component using the configured strategy."""
    return mask_sensitive_value(
        value,
        category=category,
        rule_name="url",
        reason=reason,
        policy=cleaner.policy,
    )


def _escape_control_characters(value: str) -> str:
    """Percent-encode control characters so output cannot forge log lines."""
    escaped: list[str] = []
    for char in value:
        if unicode_category(char) == "Cc":
            escaped.extend(f"%{byte:02X}" for byte in char.encode("utf-8"))
        else:
            escaped.append(char)
    return "".join(escaped)


def _encode_parameter_value(value: str) -> str:
    """Encode parameter data while keeping redaction placeholders readable."""
    return quote_plus(value, safe="[],:/@-._~")


def _clean_parameter_string(value: str, cleaner: Cleaner) -> str:
    """Clean a query-string-like component while preserving parameter order."""
    cleaned_parts: list[str] = []
    for key, parameter_value in parse_qsl(value, keep_blank_values=True):
        normalized_key = _normalize_key(key)
        cleaned_key = quote_plus(_escape_control_characters(cleaner.clean_text(key)))

        if _is_sensitive_parameter(key, cleaner.policy):
            category = _category_for_parameter(key)
            cleaned_value = _mask_value(
                cleaner,
                parameter_value,
                category=category,
                reason=f"URL parameter {normalized_key!r} is considered sensitive",
            )
        else:
            cleaned_value = cleaner.clean_text(parameter_value)

        cleaned_parts.append(f"{cleaned_key}={_encode_parameter_value(cleaned_value)}")

    return "&".join(cleaned_parts)


def _clean_netloc(netloc: str, cleaner: Cleaner) -> str:
    """Remove user information and clean the remaining host/port component."""
    userinfo, separator, host_port = netloc.rpartition("@")
    if not separator:
        return _escape_control_characters(cleaner.clean_text(netloc))

    masked_userinfo = _mask_value(
        cleaner,
        userinfo,
        category="credential",
        reason="URL user information may contain a username and password",
    )
    cleaned_host_port = _escape_control_characters(cleaner.clean_text(host_port))
    return f"{masked_userinfo}@{cleaned_host_port}"


def _clean_fragment(fragment: str, cleaner: Cleaner) -> str:
    """Clean a URL fragment, including OAuth-style parameter fragments."""
    if not fragment:
        return ""
    if "=" in fragment or "&" in fragment:
        return _clean_parameter_string(fragment, cleaner)
    return _escape_control_characters(cleaner.clean_text(fragment))


def clean_url(url: str, *, policy: CleanerPolicy | None = None, redact_full: bool = False) -> str:
    """
    Clean sensitive data from all log-relevant URL components.

    The scheme and safe host context are preserved. User information, sensitive
    query or fragment parameters, and values detected by the active policy are
    redacted. Parameter values are safely re-encoded while placeholders such as
    ``[SECRET]`` and ``[EMAIL]`` remain readable.

    The result is intended for logging and display, not exact URL round-tripping.

    Example::

        clean_url("https://api.example.com/users?page=1&token=abc&email=j@x.com")
        # "https://api.example.com/users?page=1&token=[SECRET]&email=[EMAIL]"
    """
    cleaner = Cleaner(policy=policy or CleanerPolicy.default())
    if redact_full:
        return cleaner.policy.masking.mask_category("url")

    try:
        parts = urlsplit(url)
    except ValueError:
        return cleaner.clean_text(url)

    if not parts.scheme or not parts.netloc:
        return cleaner.clean_text(url)

    cleaned_netloc = _clean_netloc(parts.netloc, cleaner)
    cleaned_path = _escape_control_characters(cleaner.clean_text(parts.path))
    cleaned_query = _clean_parameter_string(parts.query, cleaner) if parts.query else ""
    cleaned_fragment = _clean_fragment(parts.fragment, cleaner)

    return urlunsplit((parts.scheme, cleaned_netloc, cleaned_path, cleaned_query, cleaned_fragment))
