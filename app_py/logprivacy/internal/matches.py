"""Internal match type used during detection and redaction.

_DetectedMatch carries the sensitive original value.  It is used only during
the scan → resolve → redact pipeline and is never returned to callers as part
of the public API.  After redaction the pipeline emits Finding objects, which
do not retain the original matched text by default.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class _DetectedMatch:
    """One sensitive span found in text by a single rule.

    This object intentionally does *not* implement __repr__ in a way that
    exposes the matched value.  It is an internal implementation detail and
    must never appear in public results or exception messages.
    """

    rule_name: str
    category: str
    start: int
    end: int
    matched: str = field(repr=False)
    reason: str = ""
    metadata: dict[str, str] = field(default_factory=dict, repr=False)

    def __repr__(self) -> str:
        return (
            f"_DetectedMatch("
            f"rule_name={self.rule_name!r}, "
            f"category={self.category!r}, "
            f"start={self.start}, "
            f"end={self.end})"
        )

    @property
    def length(self) -> int:
        return self.end - self.start
