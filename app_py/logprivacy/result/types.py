"""Result objects returned by LogPrivacy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar

from logprivacy.typing import JSONValue

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class SafeDataStats:
    """Aggregate counters from a single ``to_safe_data_with_result()`` call.

    Counters are local to one call and do not accumulate across calls.
    """

    masked: int = 0
    removed: int = 0
    truncated: int = 0
    unsupported: int = 0
    adapter_errors: int = 0
    field_rule_matches: int = 0
    path_rule_matches: int = 0
    not_allowed: int = 0
    pseudonymized: int = 0


@dataclass(frozen=True, slots=True)
class SafeDataResult:
    """Full result of a ``to_safe_data_with_result()`` call.

    ``cleaned`` is the sanitized JSON-compatible value.
    ``complete`` is ``False`` when any part of the input could not be fully
    inspected (max_depth, max_items, iteration_error, adapter_error, etc.).
    ``limitations`` contains stable non-sensitive identifiers for each limit hit.
    ``stats`` contains aggregate counters for the operation.

    The result does not retain any reference to the original value, source text,
    raw payload, or adapter.
    """

    cleaned: JSONValue
    complete: bool
    limitations: tuple[str, ...]
    stats: SafeDataStats


@dataclass(frozen=True, slots=True, repr=False)
class Finding:
    """
    A sensitive value detected in text, safe for public consumption.

    The original matched text is **not** retained by default — only the
    replacement, position, rule name, category, and reason are stored.

    If you need the matched value for a trusted internal context (e.g. debug
    tooling not written to logs), construct the Finding with
    ``retain_sensitive_match=True``, which stores it in the private
    ``_matched`` slot.  This option should never be enabled in production paths.

    Attributes exposed in repr, to_dict, and serialisation are safe: they
    contain no source-text fragments.
    """

    rule_name: str
    category: str
    start: int
    end: int
    replacement: str = ""
    reason: str = ""
    metadata: dict[str, str] = field(default_factory=dict, repr=False)
    location: str = ""
    # Private: populated only when retain_sensitive_match=True was requested.
    # Not included in repr, to_dict, or any public output.
    _matched: str = field(default="", repr=False, compare=False, hash=False)

    def __repr__(self) -> str:
        """Return a safe representation without matched text or derived sensitive values."""
        location = f", location={self.location!r}" if self.location else ""
        return (
            f"{type(self).__name__}("
            f"rule_name={self.rule_name!r}, "
            f"category={self.category!r}, "
            f"start={self.start}, "
            f"end={self.end}, "
            f"has_replacement={bool(self.replacement)!r}"
            f"{location})"
        )

    @property
    def matched(self) -> str:
        """Return the retained sensitive match text, or empty string if not retained.

        This property is provided for backward compatibility and for trusted
        tooling.  In the default pipeline, ``_matched`` is always empty — the
        sensitive text is discarded after redaction.  It is only non-empty when
        the pipeline was run with ``retain_sensitive_matches=True``.
        """
        return self._matched

    @property
    def length(self) -> int:
        """Return the number of characters covered by this finding."""
        return self.end - self.start

    def with_replacement(self, replacement: str) -> Finding:
        """Return this finding with a resolved replacement value."""
        return Finding(
            rule_name=self.rule_name,
            category=self.category,
            start=self.start,
            end=self.end,
            replacement=replacement,
            reason=self.reason,
            metadata=dict(self.metadata),
            location=self.location,
            _matched=self._matched,
        )

    def with_location(self, location: str) -> Finding:
        """Return this finding with a safe human-readable source location."""
        return Finding(
            rule_name=self.rule_name,
            category=self.category,
            start=self.start,
            end=self.end,
            replacement=self.replacement,
            reason=self.reason,
            metadata=dict(self.metadata),
            location=location,
            _matched=self._matched,
        )

    def to_dict(
        self,
        *,
        include_match: bool = False,
        include_metadata: bool = False,
    ) -> dict[str, Any]:
        """
        Return a JSON-friendly representation.

        Sensitive source text and rule metadata are excluded by default.
        ``include_match=True`` exposes the privately retained matched value
        only if it was stored (i.e. the pipeline was run with
        ``retain_sensitive_matches=True``).  Use only in a trusted context that
        is not written to logs, telemetry, or user-visible output.
        """
        data: dict[str, Any] = {
            "rule_name": self.rule_name,
            "category": self.category,
            "start": self.start,
            "end": self.end,
            "replacement": self.replacement,
            "reason": self.reason,
        }
        if self.location:
            data["location"] = self.location
        if include_match:
            data["matched"] = self._matched
        if include_metadata:
            data["metadata"] = dict(self.metadata)
        return data


@dataclass(frozen=True, slots=True, repr=False)
class RedactionResult(Generic[T]):
    """
    The result of a cleaning operation, pairing the cleaned value with finding metadata.

    ``original`` may contain sensitive values. The representation therefore
    contains only aggregate, non-sensitive state.
    Use ``summary()`` or ``explain()`` for safe diagnostic output.
    """

    original: T = field(repr=False)
    cleaned: T = field(repr=False)
    findings: tuple[Finding, ...] = field(default=(), repr=False)

    def __repr__(self) -> str:
        """Return a safe representation without original or cleaned payloads."""
        return (
            f"{type(self).__name__}("
            f"changed={self.changed!r}, "
            f"finding_count={self.finding_count}, "
            f"categories={self.categories!r})"
        )

    @property
    def changed(self) -> bool:
        """Return True when the cleaned value differs from the original."""
        return self.original != self.cleaned

    @property
    def finding_count(self) -> int:
        """Return how many findings were redacted."""
        return len(self.findings)

    @property
    def categories(self) -> tuple[str, ...]:
        """Return distinct finding categories in order of appearance."""
        seen: list[str] = []
        for finding in self.findings:
            if finding.category not in seen:
                seen.append(finding.category)
        return tuple(seen)

    def summary(self) -> dict[str, Any]:
        """Return a compact, safe summary without original sensitive values."""
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.category] = counts.get(finding.category, 0) + 1
        return {
            "changed": self.changed,
            "finding_count": self.finding_count,
            "categories": list(self.categories),
            "counts": counts,
        }

    def explain(self) -> str:
        """Return a human-readable explanation of what was redacted."""
        if not self.findings:
            return "LogPrivacy found no sensitive values."

        lines = [
            f"LogPrivacy found {self.finding_count} sensitive value(s).",
            "",
        ]
        for index, finding in enumerate(self.findings, start=1):
            reason = finding.reason or f"text matched the {finding.rule_name!r} rule"
            lines.extend(
                [
                    f"{index}. {finding.category}",
                    f"   Rule: {finding.rule_name}",
                    f"   Reason: {reason}",
                    f"   Action: replaced with {finding.replacement}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip()


@dataclass(frozen=True, slots=True)
class JSONLStats:
    """Aggregate counters from a JSONL processing operation."""

    lines_read: int = 0
    lines_written: int = 0
    invalid_lines: int = 0
    skipped_lines: int = 0
    placeholder_lines: int = 0


@dataclass(frozen=True, slots=True)
class JSONLResult:
    """Full result of a JSONL processing operation."""

    complete: bool
    limitations: tuple[str, ...]
    stats: JSONLStats


@dataclass(frozen=True, slots=True)
class JSONLRecord:
    """Per-line result from ``iter_safe_jsonl()``."""

    line_number: int
    result: SafeDataResult


@dataclass(frozen=True, slots=True)
class JSONLScanRecord:
    """Per-line scan result from ``scan_jsonl()``."""

    line_number: int
    findings: tuple[Finding, ...]
