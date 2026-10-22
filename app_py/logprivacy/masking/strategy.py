"""Masking strategy interfaces and built-in strategies."""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol

from logprivacy.masking.masks import keep_edges, mask_email, mask_token
from logprivacy.masking.placeholders import DEFAULT_PLACEHOLDERS

if TYPE_CHECKING:
    from logprivacy.result import Finding

_HASH_DOMAIN = b"logprivacy.hash.v1"
_HMAC_DOMAIN = b"logprivacy.hmac.v1"
_MIN_HASH_LENGTH = 12
_MAX_HASH_LENGTH = sha256().digest_size * 2
_MIN_HMAC_KEY_BYTES = 16


class MaskingStrategy(Protocol):
    """Protocol implemented by objects that know how to mask findings."""

    def mask(self, finding: Finding) -> str:
        """Return the replacement text for a Finding (legacy path).

        Called by the internal redaction pipeline when a Finding is available.
        New code should prefer ``mask_value``.
        """

    def mask_value(self, value: str, category: str) -> str:
        """Return the replacement text for a raw matched value and its category.

        This is the primary masking entry point used by the redaction pipeline.
        """

    def mask_category(self, category: str) -> str:
        """Return the replacement text for a category when no concrete value exists."""


@dataclass(frozen=True, slots=True)
class PlaceholderMaskingStrategy:
    """Replace sensitive values with readable placeholders such as [EMAIL]."""

    placeholders: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PLACEHOLDERS))
    fallback: str = "[REDACTED]"

    def mask(self, finding: Finding) -> str:
        """Return a placeholder for the finding category."""
        return self.mask_category(finding.category)

    def mask_value(self, value: str, category: str) -> str:
        """Return a placeholder for the category (value is ignored)."""
        return self.mask_category(category)

    def mask_category(self, category: str) -> str:
        """Return a placeholder for a category."""
        return self.placeholders.get(category, self.fallback)


@dataclass(frozen=True, slots=True)
class PartialMaskingStrategy:
    """Mask values while preserving enough shape for debugging."""

    fallback: str = "[REDACTED]"

    def mask(self, finding: Finding) -> str:
        """Return a partially masked value."""
        if not finding.matched:
            return self.mask_category(finding.category)
        return self.mask_value(finding.matched, finding.category)

    def mask_value(self, value: str, category: str) -> str:
        """Return a partially masked representation of value."""
        if category == "email":
            return mask_email(value)
        if category in {"token", "secret", "credential"}:
            return mask_token(value)
        if category == "url":
            return "[URL]"
        return keep_edges(value)

    def mask_category(self, category: str) -> str:
        """Return a safe category placeholder when no concrete value exists."""
        return DEFAULT_PLACEHOLDERS.get(category, self.fallback)


@dataclass(frozen=True, slots=True)
class HashMaskingStrategy:
    """Replace values with stable pseudonymous correlation tokens.

    Supplying ``key`` enables HMAC-SHA-256 and is the recommended production
    configuration. Without a key, the strategy remains deterministic for
    backward compatibility but must not be treated as protection against
    dictionary attacks. Hash masking is pseudonymization, not anonymization.

    ``salt`` is retained for backward compatibility with earlier releases. It
    is not secret and cannot be combined with ``key``. The default digest length
    is 16 hexadecimal characters (64 bits); shorter values are rejected.
    """

    placeholders: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PLACEHOLDERS))
    salt: str = field(default="", repr=False)
    length: int = 16
    key: str | bytes | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Validate security-sensitive options before the strategy is used."""
        if isinstance(self.length, bool) or not isinstance(self.length, int):
            raise TypeError("length must be an integer")
        if not _MIN_HASH_LENGTH <= self.length <= _MAX_HASH_LENGTH:
            raise ValueError(f"length must be between {_MIN_HASH_LENGTH} and {_MAX_HASH_LENGTH}")
        if not isinstance(self.salt, str):
            raise TypeError("salt must be a string")
        if self.key is not None and self.salt:
            raise ValueError("key and salt cannot be configured together")
        if self.key is not None:
            key_bytes = _coerce_key(self.key)
            if len(key_bytes) < _MIN_HMAC_KEY_BYTES:
                raise ValueError(
                    f"key must contain at least {_MIN_HMAC_KEY_BYTES} bytes after UTF-8 encoding"
                )

    def mask(self, finding: Finding) -> str:
        """Return a category-prefixed deterministic correlation token."""
        return self.mask_value(finding.matched, finding.category)

    def mask_value(self, value: str, category: str) -> str:
        """Return a category-prefixed deterministic correlation token."""
        payload = _build_hash_payload(category, value, salt=self.salt)
        if self.key is None:
            digest = sha256(payload).hexdigest()
        else:
            digest = hmac.new(_coerce_key(self.key), payload, sha256).hexdigest()

        label = self.placeholders.get(category, "[REDACTED]").strip("[]")
        return f"[{label}:{digest[: self.length]}]"

    def mask_category(self, category: str) -> str:
        """Return a placeholder when no concrete value exists."""
        return self.placeholders.get(category, "[REDACTED]")


def _coerce_key(key: str | bytes) -> bytes:
    """Return a byte key without accepting mutable or ambiguous key types."""
    if isinstance(key, str):
        return key.encode("utf-8")
    if isinstance(key, bytes):
        return key
    raise TypeError("key must be a string, bytes, or None")


def _build_hash_payload(category: str, value: str, *, salt: str) -> bytes:
    """Frame hash inputs to prevent concatenation ambiguity and cross-domain reuse."""
    return b"".join(
        (
            _frame(_HASH_DOMAIN),
            _frame(category.encode("utf-8")),
            _frame(salt.encode("utf-8")),
            _frame(value.encode("utf-8")),
        )
    )


def _frame(value: bytes) -> bytes:
    """Prefix one binary component with its fixed-width length."""
    return len(value).to_bytes(8, byteorder="big") + value


_HMAC_SAFE_CATEGORY_PATTERN = re.compile(r"[^A-Za-z0-9_]+")
_MIN_HMAC_DIGEST_SIZE = 8
_MAX_HMAC_DIGEST_SIZE = 64  # sha256 hex length


def _build_hmac_payload(category: str, value: str) -> bytes:
    """Frame HMAC inputs with domain separation and unambiguous boundaries."""
    return b"".join(
        (
            _frame(_HMAC_DOMAIN),
            _frame(category.encode("utf-8")),
            _frame(value.encode("utf-8")),
        )
    )


@dataclass(frozen=True, slots=True)
class HMACMaskingStrategy:
    """Deterministic pseudonymization using HMAC-SHA256.

    Produces correlation tokens in the form ``[CATEGORY:hmac:hexdigest]``.
    The same key + value + category always produces the same token; rotate
    the key to invalidate all tokens.

    This is pseudonymization, not anonymization. A party with the key can
    re-derive any token from the original value.

    Security:
    - ``key`` never appears in ``repr``, ``str``, exceptions, or serialization.
    - ``key`` must be bytes (no implicit string coercion).
    - ``key`` must contain at least 16 bytes; 32 random bytes are recommended.
    - category and value are length-framed under a dedicated HMAC domain.
    - ``digest_size`` is the number of hexadecimal characters in the output.
    """

    key: bytes = field(repr=False)
    digest_size: int = 12

    def __post_init__(self) -> None:
        if isinstance(self.key, bool) or not isinstance(self.key, bytes):
            raise TypeError("HMACMaskingStrategy key must be bytes")
        if not self.key:
            raise ValueError("HMACMaskingStrategy key must not be empty")
        if len(self.key) < _MIN_HMAC_KEY_BYTES:
            raise ValueError(
                f"HMACMaskingStrategy key must contain at least {_MIN_HMAC_KEY_BYTES} bytes"
            )
        if isinstance(self.digest_size, bool) or not isinstance(self.digest_size, int):
            raise TypeError("digest_size must be an integer")
        if not (_MIN_HMAC_DIGEST_SIZE <= self.digest_size <= _MAX_HMAC_DIGEST_SIZE):
            raise ValueError(
                f"digest_size must be between {_MIN_HMAC_DIGEST_SIZE} and {_MAX_HMAC_DIGEST_SIZE}"
            )

    def mask(self, finding: Finding) -> str:
        """Return a pseudonymous correlation token for the finding."""
        return self.mask_value(finding.matched, finding.category)

    def mask_value(self, value: str, category: str) -> str:
        """Return a pseudonymous correlation token for value and category."""
        payload = _build_hmac_payload(category, value)
        digest = hmac.new(self.key, payload, sha256).hexdigest()
        label = _HMAC_SAFE_CATEGORY_PATTERN.sub("_", category).upper() or "REDACTED"
        return f"[{label}:hmac:{digest[: self.digest_size]}]"

    def mask_category(self, category: str) -> str:
        """Return a safe placeholder when no concrete value is available."""
        label = _HMAC_SAFE_CATEGORY_PATTERN.sub("_", category).upper() or "REDACTED"
        return f"[{label}:hmac:?]"

    def __str__(self) -> str:
        return f"HMACMaskingStrategy(digest_size={self.digest_size})"
