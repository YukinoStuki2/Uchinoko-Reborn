"""Main cleaning engine."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from logprivacy.audit import AuditReport
from logprivacy.exceptions import LogBlockedError
from logprivacy.internal.audit_location import append_mapping_key, append_sequence_index
from logprivacy.internal.matches import _DetectedMatch
from logprivacy.internal.pipeline import FindingResolver, TextRedactor, TextScanner
from logprivacy.internal.traversal import (
    LIMIT_ITERATION_ERROR,
    LIMIT_MAX_DEPTH,
    LIMIT_REPRESENTATION_ERROR,
    MAX_DEPTH_PLACEHOLDER,
    UNAVAILABLE_PLACEHOLDER,
    TraversalState,
    safe_mapping_key_text,
)
from logprivacy.masking.strategy import PlaceholderMaskingStrategy
from logprivacy.policy import CleanerPolicy
from logprivacy.result import Finding, RedactionResult
from logprivacy.rules.set import RuleSet
from logprivacy.structured.mapping import clean_mapping
from logprivacy.structured.sequence import clean_sequence

_EXACT_BYTE_TYPES = frozenset({bytes, bytearray, memoryview})
_EXACT_SCALAR_TYPES = frozenset({int, float, complex, bool})


@dataclass(frozen=True, slots=True)
class Cleaner:
    """Clean sensitive data from strings and structured values.

    Pipeline components (scanner, resolver, redactor) are built once per
    instance in ``__post_init__`` so repeated calls to ``clean_text()`` and
    related methods do not reconstruct them.
    """

    policy: CleanerPolicy = field(default_factory=CleanerPolicy.default)
    _scanner: TextScanner = field(init=False, repr=False)
    _resolver: FindingResolver = field(init=False, repr=False)
    _redactor: TextRedactor = field(init=False, repr=False)
    _placeholder_redactor: TextRedactor = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Build the text pipeline once and validate the rule set eagerly."""
        rule_set = RuleSet(self.policy.rules)
        object.__setattr__(self, "_scanner", TextScanner(rule_set))
        object.__setattr__(self, "_resolver", FindingResolver())
        object.__setattr__(self, "_redactor", TextRedactor(rule_set, self.policy.masking))
        object.__setattr__(
            self,
            "_placeholder_redactor",
            TextRedactor(rule_set, PlaceholderMaskingStrategy()),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def clean(self, value: Any) -> Any:
        """Return a fail-closed cleaned copy of a scalar or structured value."""
        state = TraversalState(remaining_items=self.policy.max_items)
        return self._clean_value(value, depth=0, state=state)

    def clean_text(self, text: str) -> str:
        """Return a cleaned string."""
        return self.clean_with_result(text).cleaned

    def clean_with_result(self, text: str) -> RedactionResult[str]:
        """Return cleaned text and a ``RedactionResult`` with finding details."""
        raw_matches = self._scanner.scan(text)
        resolved = self._resolver.resolve(raw_matches)
        self._raise_if_blocked_matches(resolved)
        cleaned, findings = self._redactor.redact(text, resolved)
        return RedactionResult(original=text, cleaned=cleaned, findings=findings)

    def audit(self, value: Any) -> AuditReport:
        """Audit a value and fail closed when traversal cannot inspect everything.

        ``report.safe`` is true only when the complete value was inspected within
        ``max_depth``, ``max_items``, and ``max_findings`` and no sensitive value
        was found.
        """
        state = TraversalState(
            remaining_items=self.policy.max_items,
            remaining_findings=self.policy.max_findings,
        )
        findings = self._collect_audit_findings(value, depth=0, state=state)
        return AuditReport(
            findings,
            complete=state.complete,
            limitations=tuple(state.limitations),
        )

    def _collect_audit_findings(
        self,
        value: Any,
        *,
        depth: int,
        state: TraversalState,
        path: str = "$",
    ) -> tuple[Finding, ...]:
        """Recursively collect findings while respecting global traversal budgets."""
        if depth > self.policy.max_depth:
            state.mark_limit(LIMIT_MAX_DEPTH)
            return ()

        value_type = type(value)
        if isinstance(value, str):
            return self._bounded_findings(value, state, path=path)

        if value_type in _EXACT_BYTE_TYPES:
            text = bytes(value).decode("utf-8", errors="replace")
            return self._bounded_findings(text, state, path=path)

        if isinstance(value, Mapping):
            return self._audit_mapping(value, depth=depth, state=state, path=path)

        if value_type is range:
            return ()

        if isinstance(value, Sequence):
            return self._audit_sequence(value, depth=depth, state=state, path=path)

        if value is None or value_type in _EXACT_SCALAR_TYPES:
            return ()

        try:
            text = str(value)
        except Exception:
            state.mark_limit(LIMIT_REPRESENTATION_ERROR)
            return ()
        return self._bounded_findings(text, state, path=path)

    def _audit_mapping(
        self,
        value: Mapping[Any, Any],
        *,
        depth: int,
        state: TraversalState,
        path: str = "$",
    ) -> tuple[Finding, ...]:
        """Audit a mapping without looping forever or trusting arbitrary keys."""
        value_id = id(value)
        if value_id in state.active:
            return ()

        state.active.add(value_id)
        findings: list[Finding] = []
        try:
            try:
                iterator = iter(value.items())
            except Exception:
                state.mark_limit(LIMIT_ITERATION_ERROR)
                return ()

            while True:
                try:
                    key, item = next(iterator)
                except StopIteration:
                    break
                except Exception:
                    state.mark_limit(LIMIT_ITERATION_ERROR)
                    break

                if not state.consume_item():
                    break

                key_text, trusted = safe_mapping_key_text(key)
                safe_key = self._sanitize_location_text(key_text)
                child_path = append_mapping_key(path, safe_key)

                if self.policy.is_sensitive_key(key):
                    matched = self._sensitive_value_marker(item)
                    if matched:
                        finding = Finding(
                            rule_name="sensitive_key",
                            category="credential",
                            start=0,
                            end=len(matched),
                            reason="value is associated with a policy-sensitive key",
                            location=child_path,
                        )
                        findings.extend(state.take_findings((finding,)))
                else:
                    findings.extend(
                        self._collect_audit_findings(
                            item,
                            depth=depth + 1,
                            state=state,
                            path=child_path,
                        )
                    )
            return tuple(findings)
        finally:
            state.active.discard(value_id)

    def _audit_sequence(
        self,
        value: Sequence[Any],
        *,
        depth: int,
        state: TraversalState,
        path: str = "$",
    ) -> tuple[Finding, ...]:
        """Audit a sequence with cycle, iteration, and item-budget protection."""
        value_id = id(value)
        if value_id in state.active:
            return ()

        state.active.add(value_id)
        findings: list[Finding] = []
        index = 0
        try:
            try:
                iterator = iter(value)
            except Exception:
                state.mark_limit(LIMIT_ITERATION_ERROR)
                return ()

            while True:
                try:
                    item = next(iterator)
                except StopIteration:
                    break
                except Exception:
                    state.mark_limit(LIMIT_ITERATION_ERROR)
                    break

                current_index = index
                index += 1

                if not state.consume_item():
                    break
                findings.extend(
                    self._collect_audit_findings(
                        item,
                        depth=depth + 1,
                        state=state,
                        path=append_sequence_index(path, current_index),
                    )
                )
            return tuple(findings)
        finally:
            state.active.discard(value_id)

    def _sanitize_location_text(self, text: str) -> str:
        """Redact a safe label without applying block-mode side effects."""
        raw_matches = self._scanner.scan(text)
        resolved = self._resolver.resolve(raw_matches)
        if not resolved:
            return text
        cleaned, _ = self._placeholder_redactor.redact(text, resolved)
        return cleaned

    def _bounded_findings(
        self, text: str, state: TraversalState, *, path: str = ""
    ) -> tuple[Finding, ...]:
        raw_matches = self._scanner.scan(text)
        resolved = self._resolver.resolve(raw_matches)
        _, findings = self._redactor.redact(text, resolved)
        if path:
            findings = tuple(f.with_location(path) for f in findings)
        return state.take_findings(findings)

    @staticmethod
    def _sensitive_value_marker(value: Any) -> str:
        """Return concrete safe-to-convert values or a non-sensitive type marker."""
        value_type = type(value)
        if value is None:
            return ""
        if value_type is str:
            return cast(str, value)
        if value_type in _EXACT_BYTE_TYPES:
            return bytes(value).decode("utf-8", errors="replace")
        if value_type in _EXACT_SCALAR_TYPES:
            return repr(value)
        return f"<{value_type.__name__}>"

    def explain(self, text: str) -> str:
        """Return a human-readable explanation of what would be redacted and why."""
        return self.clean_with_result(text).explain()

    def _find(self, text: str) -> tuple[_DetectedMatch, ...]:
        """Return all matches detected by active rules (internal use)."""
        return self._scanner.scan(text)

    def _raise_if_blocked(self, findings: tuple[Finding, ...]) -> None:
        """Raise when policy block categories are present in public findings."""
        blocked = tuple(
            dict.fromkeys(
                finding.category
                for finding in findings
                if finding.category in self.policy.block_categories
            )
        )
        if blocked:
            joined = ", ".join(blocked)
            raise LogBlockedError(
                f"LogPrivacy blocked sensitive categories: {joined}", categories=blocked
            )

    def _raise_if_blocked_matches(self, matches: tuple[_DetectedMatch, ...]) -> None:
        """Raise when policy block categories are present in resolved matches."""
        blocked = tuple(
            dict.fromkeys(
                match.category
                for match in matches
                if match.category in self.policy.block_categories
            )
        )
        if blocked:
            joined = ", ".join(blocked)
            raise LogBlockedError(
                f"LogPrivacy blocked sensitive categories: {joined}", categories=blocked
            )

    def _clean_value(
        self,
        value: Any,
        *,
        depth: int,
        state: TraversalState,
    ) -> Any:
        """Recursively clean a value without returning uninspected source branches."""
        if depth > self.policy.max_depth:
            state.mark_limit(LIMIT_MAX_DEPTH)
            return MAX_DEPTH_PLACEHOLDER

        value_type = type(value)
        if isinstance(value, str):
            return self.clean_text(value)

        if value_type in _EXACT_BYTE_TYPES:
            decoded = bytes(value).decode("utf-8", errors="surrogateescape")
            cleaned = self.clean_text(decoded).encode("utf-8", errors="surrogateescape")
            if value_type is bytes:
                return cleaned
            if value_type is bytearray:
                return bytearray(cleaned)
            return memoryview(cleaned)

        if isinstance(value, Mapping):
            return clean_mapping(value, self, depth, state)

        if value_type is range:
            return value

        if isinstance(value, Sequence) and value_type not in _EXACT_BYTE_TYPES:
            return clean_sequence(value, self, depth, state)

        if self.policy.clean_unknown_objects and value is not None:
            try:
                return self.clean_text(str(value))
            except Exception:
                state.mark_limit(LIMIT_REPRESENTATION_ERROR)
                return UNAVAILABLE_PLACEHOLDER

        return value
