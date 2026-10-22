"""Shared type aliases used by LogPrivacy."""

from __future__ import annotations

from typing import TypeAlias

JSONScalar: TypeAlias = str | int | float | bool | None
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
SensitiveCategory: TypeAlias = str
MaskingName: TypeAlias = str
