"""Safe JSON serialization APIs."""

from __future__ import annotations

import json as _json
from typing import Any, TextIO

from logprivacy.adapters import AdapterRegistry
from logprivacy.policy import CleanerPolicy
from logprivacy.safe_data import to_safe_data


def safe_json_dumps(
    value: object,
    *,
    policy: CleanerPolicy | None = None,
    adapters: AdapterRegistry | None = None,
    **json_options: Any,
) -> str:
    """Serialize ``value`` as JSON after sanitizing it with ``to_safe_data()``."""
    if "default" in json_options:
        raise TypeError("safe_json_dumps does not support default=")

    json_options["allow_nan"] = False
    safe_value = to_safe_data(value, policy=policy, adapters=adapters)
    return _json.dumps(safe_value, **json_options)


def safe_json_dump(
    value: object,
    file: TextIO,
    *,
    policy: CleanerPolicy | None = None,
    adapters: AdapterRegistry | None = None,
    **json_options: Any,
) -> None:
    """Write sanitized JSON for ``value`` to a text file-like object."""
    file.write(
        safe_json_dumps(
            value,
            policy=policy,
            adapters=adapters,
            **json_options,
        )
    )
