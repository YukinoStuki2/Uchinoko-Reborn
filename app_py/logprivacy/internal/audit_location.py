"""Safe location formatting for audit findings."""

from __future__ import annotations

import json
import re
from typing import cast
from unicodedata import category as unicode_category

_ROOT_LOCATION = "$"
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MAX_COMPONENT_CHARS = 160
_EXACT_SCALAR_TYPES = frozenset({int, float, complex, bool, type(None)})


def root_location() -> str:
    """Return the canonical root marker used by structured audits."""
    return _ROOT_LOCATION


def safe_mapping_key_text(key: object) -> str:
    """Return a bounded key label without trusting arbitrary object representations."""
    key_type = type(key)
    if key_type is str:
        text = cast(str, key)
    elif key_type in _EXACT_SCALAR_TYPES:
        text = repr(key)
    elif key_type is bytes:
        text = cast(bytes, key).decode("utf-8", errors="replace")
    elif key_type is bytearray:
        text = bytes(cast(bytearray, key)).decode("utf-8", errors="replace")
    elif key_type is memoryview:
        text = bytes(cast(memoryview, key)).decode("utf-8", errors="replace")
    else:
        text = f"<{key_type.__name__}>"
    return _bound_component(_escape_controls(text))


def append_mapping_key(parent: str, key_text: str) -> str:
    """Append a sanitized mapping key using a JSONPath-like representation."""
    bounded = _bound_component(_escape_controls(key_text))
    if _IDENTIFIER_PATTERN.fullmatch(bounded):
        return f"{parent}.{bounded}"
    encoded = json.dumps(bounded, ensure_ascii=True)
    return f"{parent}[{encoded}]"


def append_sequence_index(parent: str, index: int) -> str:
    """Append a zero-based sequence index to an audit location."""
    return f"{parent}[{index}]"


def format_file_location(source_name: str, *, line: int, column: int) -> str:
    """Return a safe one-based file location without exposing an absolute path."""
    if line < 1:
        raise ValueError("line must be at least 1")
    if column < 1:
        raise ValueError("column must be at least 1")
    safe_source = _bound_component(_escape_controls(source_name)) or "<file>"
    return f"{safe_source}:{line}:{column}"


def _escape_controls(value: str) -> str:
    """Render control and formatting characters as inert Unicode escapes."""
    escaped: list[str] = []
    for char in value:
        if unicode_category(char) in {"Cc", "Cf", "Cs"}:
            codepoint = ord(char)
            if codepoint <= 0xFF:
                escaped.append(f"\\x{codepoint:02x}")
            elif codepoint <= 0xFFFF:
                escaped.append(f"\\u{codepoint:04x}")
            else:
                escaped.append(f"\\U{codepoint:08x}")
        else:
            escaped.append(char)
    return "".join(escaped)


def _bound_component(value: str) -> str:
    """Limit one location component so reports remain safe to render."""
    if len(value) <= _MAX_COMPONENT_CHARS:
        return value
    return f"{value[: _MAX_COMPONENT_CHARS - 3]}..."
