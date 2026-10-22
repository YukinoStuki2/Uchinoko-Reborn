"""Audit reports for sensitive data detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from logprivacy.result import Finding

_HIGH_RISK = {"credential", "token", "secret", "credit_card"}


@dataclass(frozen=True, slots=True, repr=False)
class AuditReport:
    """Describe sensitive findings and whether the audit inspected everything.

    ``complete`` is ``False`` when traversal stopped because of configured
    resource limits or an unsafe container/object failure. An incomplete report
    is never considered safe, even when no sensitive value was found in the
    inspected prefix.
    """

    findings: tuple[Finding, ...] = field(repr=False)
    complete: bool = True
    limitations: tuple[str, ...] = ()

    def __repr__(self) -> str:
        """Return a safe representation without nested finding contents."""
        return (
            f"{type(self).__name__}("
            f"safe={self.safe!r}, "
            f"complete={self.complete!r}, "
            f"risk_level={self.risk_level!r}, "
            f"finding_count={self.finding_count}, "
            f"categories={self.categories!r}, "
            f"limitations={self.limitations!r})"
        )

    @property
    def safe(self) -> bool:
        """Return ``True`` only when the complete input was inspected and clean."""
        return self.complete and not self.findings

    @property
    def truncated(self) -> bool:
        """Return whether resource limits or traversal errors made the audit incomplete."""
        return not self.complete

    @property
    def finding_count(self) -> int:
        """Return the number of retained sensitive findings."""
        return len(self.findings)

    @property
    def categories(self) -> tuple[str, ...]:
        """Return distinct finding categories in order of first appearance."""
        seen: list[str] = []
        for finding in self.findings:
            if finding.category not in seen:
                seen.append(finding.category)
        return tuple(seen)

    @property
    def locations(self) -> tuple[str, ...]:
        """Return distinct finding locations in order of first appearance."""
        seen: list[str] = []
        for finding in self.findings:
            if finding.location and finding.location not in seen:
                seen.append(finding.location)
        return tuple(seen)

    def details(self) -> list[dict[str, Any]]:
        """Return safe structured details for each finding, without matched values."""
        result = []
        for finding in self.findings:
            d: dict[str, Any] = {
                "rule_name": finding.rule_name,
                "category": finding.category,
                "start": finding.start,
                "end": finding.end,
                "reason": finding.reason,
            }
            if finding.location:
                d["location"] = finding.location
            result.append(d)
        return result

    @property
    def risk_level(self) -> str:
        """Return ``none``, ``low``, ``medium``, ``high``, or ``unknown``."""
        if any(finding.category in _HIGH_RISK for finding in self.findings):
            return "high"
        if not self.complete:
            return "unknown"
        if not self.findings:
            return "none"
        if len(self.findings) >= 3:
            return "medium"
        return "low"

    def summary(self) -> dict[str, Any]:
        """Return a safe structured summary without source values."""
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.category] = counts.get(finding.category, 0) + 1
        return {
            "safe": self.safe,
            "complete": self.complete,
            "truncated": self.truncated,
            "risk_level": self.risk_level,
            "finding_count": self.finding_count,
            "categories": list(self.categories),
            "locations": list(self.locations),
            "counts": counts,
            "limitations": list(self.limitations),
        }

    def describe(self) -> str:
        """Return a human-readable report that clearly identifies incomplete audits."""
        if self.safe:
            return "LogPrivacy audit: safe. No sensitive values were found."

        lines = [
            "LogPrivacy audit",
            "",
            f"Complete: {'yes' if self.complete else 'no'}",
            f"Risk level: {self.risk_level}",
            f"Findings: {self.finding_count}",
            f"Categories: {', '.join(self.categories) if self.categories else 'none'}",
        ]
        if self.limitations:
            lines.append(f"Limitations: {', '.join(self.limitations)}")
        for finding in self.findings:
            if finding.location:
                lines.append(f"{finding.category} at {finding.location}")
            else:
                lines.append(f"{finding.category}")
        if not self.complete:
            lines.extend(
                (
                    "",
                    "The input was not fully inspected and must not be treated as safe.",
                )
            )
        return "\n".join(lines)
