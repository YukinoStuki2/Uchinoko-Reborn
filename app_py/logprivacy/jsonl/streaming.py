"""Safe JSONL streaming for structured data."""

from __future__ import annotations

import contextlib
import json as _json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import IO, Literal, TextIO, cast

from logprivacy.adapters import AdapterRegistry
from logprivacy.cleaner import Cleaner
from logprivacy.exceptions.errors import JSONLProcessingError
from logprivacy.policy import CleanerPolicy
from logprivacy.result import (
    JSONLRecord,
    JSONLResult,
    JSONLScanRecord,
    JSONLStats,
    SafeDataResult,
    SafeDataStats,
)
from logprivacy.safe_data import to_safe_data_with_result

_OnError = Literal["raise", "skip", "placeholder"]
_SourceType = Path | str | TextIO
_OutputPath = Path | str
_SourceStream = IO[str] | IO[bytes]
_SourceLine = tuple[int, str | None, str | None]

_LIMIT_INVALID_JSON = "invalid_json"
_LIMIT_INVALID_UTF8 = "invalid_utf8"


def safe_jsonl_write(
    value: object,
    stream: TextIO,
    *,
    policy: CleanerPolicy | None = None,
    adapters: AdapterRegistry | None = None,
) -> SafeDataResult:
    """Sanitize ``value`` and write it as one JSON Lines record to ``stream``.

    Appends a newline after the JSON payload. Does not accept ``default=`` or
    ``allow_nan=True`` options. Returns the ``SafeDataResult`` from sanitization.
    """
    result = to_safe_data_with_result(value, policy=policy, adapters=adapters)
    line = _json.dumps(result.cleaned, allow_nan=False, separators=(",", ":"))
    stream.write(line)
    stream.write("\n")
    return result


def iter_safe_jsonl(
    source: _SourceType,
    *,
    policy: CleanerPolicy | None = None,
    adapters: AdapterRegistry | None = None,
    on_error: _OnError = "raise",
) -> Iterator[JSONLRecord]:
    """Yield sanitized records from a JSON Lines source line by line.

    The source is read one line at a time; the full file is never loaded into
    memory. Each yielded ``JSONLRecord`` contains the 1-based line number and
    a ``SafeDataResult`` for the sanitized object.

    Invalid JSON and invalid UTF-8 lines are handled according to ``on_error``:
    - ``"raise"`` — raise ``JSONLProcessingError`` without including line content;
    - ``"skip"`` — omit the invalid line;
    - ``"placeholder"`` — yield a safe placeholder record.

    File paths are opened in binary mode and decoded one line at a time so one
    invalid line does not prevent later valid lines from being processed.
    """
    _validate_on_error(on_error)

    for line_number, raw_line, source_error in _iter_source_lines(source):
        if source_error is not None:
            if on_error == "raise":
                raise _line_processing_error(line_number, source_error)
            if on_error == "skip":
                continue
            yield JSONLRecord(
                line_number=line_number,
                result=_placeholder_result(line_number, source_error),
            )
            continue

        assert raw_line is not None
        stripped = raw_line.strip()
        if not stripped:
            continue

        try:
            parsed = _json.loads(stripped)
        except _json.JSONDecodeError as exc:
            if on_error == "raise":
                raise _line_processing_error(
                    line_number,
                    _LIMIT_INVALID_JSON,
                ) from exc
            if on_error == "skip":
                continue
            yield JSONLRecord(
                line_number=line_number,
                result=_placeholder_result(line_number, _LIMIT_INVALID_JSON),
            )
            continue

        result = to_safe_data_with_result(parsed, policy=policy, adapters=adapters)
        yield JSONLRecord(line_number=line_number, result=result)


def clean_jsonl(
    source: _SourceType,
    *,
    output: _OutputPath,
    policy: CleanerPolicy | None = None,
    adapters: AdapterRegistry | None = None,
    on_error: _OnError = "raise",
) -> JSONLResult:
    """Sanitize a JSON Lines file and write the cleaned output atomically.

    Each line is read, sanitized, and written to a temporary file. When all
    lines are processed, the temp file is atomically renamed to ``output``.
    If processing fails, the temp file is removed and the original is untouched.

    When ``source`` and ``output`` resolve to the same file, in-place cleaning
    is performed safely via an intermediate temp file in the same directory.

    Skipped or placeholder lines are intentional recovery behaviors, but they
    mean the source was not fully processed as valid JSON and UTF-8. The result
    has ``complete=False`` and includes the relevant limitation.
    """
    _validate_on_error(on_error)
    output_path = _require_path(output, "output")
    output_dir = output_path.parent

    lines_read = 0
    lines_written = 0
    invalid_lines = 0
    skipped_lines = 0
    placeholder_lines = 0
    all_complete = True
    all_limitations: list[str] = []

    fd, tmp_path_str = tempfile.mkstemp(dir=output_dir, suffix=".jsonl.tmp")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as tmp_stream:
            for line_number, raw_line, source_error in _iter_source_lines(source):
                if source_error is not None:
                    lines_read += 1
                    invalid_lines += 1

                    if on_error == "raise":
                        raise _line_processing_error(line_number, source_error)

                    all_complete = False
                    _append_unique(all_limitations, source_error)

                    if on_error == "skip":
                        skipped_lines += 1
                        continue

                    _write_placeholder(tmp_stream, line_number, source_error)
                    placeholder_lines += 1
                    lines_written += 1
                    continue

                assert raw_line is not None
                stripped = raw_line.strip()
                if not stripped:
                    continue

                lines_read += 1
                try:
                    parsed = _json.loads(stripped)
                except _json.JSONDecodeError as exc:
                    invalid_lines += 1
                    if on_error == "raise":
                        raise _line_processing_error(
                            line_number,
                            _LIMIT_INVALID_JSON,
                        ) from exc

                    all_complete = False
                    _append_unique(all_limitations, _LIMIT_INVALID_JSON)

                    if on_error == "skip":
                        skipped_lines += 1
                        continue

                    _write_placeholder(
                        tmp_stream,
                        line_number,
                        _LIMIT_INVALID_JSON,
                    )
                    placeholder_lines += 1
                    lines_written += 1
                    continue

                result = to_safe_data_with_result(
                    parsed,
                    policy=policy,
                    adapters=adapters,
                )
                tmp_stream.write(_json.dumps(result.cleaned, allow_nan=False))
                tmp_stream.write("\n")
                lines_written += 1
                if not result.complete:
                    all_complete = False
                for limitation in result.limitations:
                    _append_unique(all_limitations, limitation)

        try:
            existing_mode = output_path.stat().st_mode
            os.chmod(tmp_path, existing_mode)
        except OSError:
            pass

        os.replace(tmp_path_str, str(output_path))
    except Exception:
        with contextlib.suppress(OSError):
            tmp_path.unlink(missing_ok=True)
        raise

    return JSONLResult(
        complete=all_complete,
        limitations=tuple(all_limitations),
        stats=JSONLStats(
            lines_read=lines_read,
            lines_written=lines_written,
            invalid_lines=invalid_lines,
            skipped_lines=skipped_lines,
            placeholder_lines=placeholder_lines,
        ),
    )


def scan_jsonl(
    source: _SourceType,
    *,
    policy: CleanerPolicy | None = None,
    adapters: AdapterRegistry | None = None,
    on_error: _OnError = "raise",
) -> Iterator[JSONLScanRecord]:
    """Yield scan findings from a JSON Lines source, line by line.

    Each non-empty line is parsed as JSON, then audited for sensitive values.
    Yields ``JSONLScanRecord`` for lines that contain findings.
    Lines with no findings are not yielded.

    ``"raise"`` raises ``JSONLProcessingError`` for invalid JSON or UTF-8.
    Because scan records only represent findings, ``"skip"`` and
    ``"placeholder"`` both omit invalid lines instead of yielding a synthetic
    finding. The original line content is never stored or included in errors.
    """
    _validate_on_error(on_error)
    effective_policy = CleanerPolicy.default() if policy is None else policy
    cleaner = Cleaner(policy=effective_policy)

    for line_number, raw_line, source_error in _iter_source_lines(source):
        if source_error is not None:
            if on_error == "raise":
                raise _line_processing_error(line_number, source_error)
            continue

        assert raw_line is not None
        stripped = raw_line.strip()
        if not stripped:
            continue

        try:
            parsed = _json.loads(stripped)
        except _json.JSONDecodeError as exc:
            if on_error == "raise":
                raise _line_processing_error(
                    line_number,
                    _LIMIT_INVALID_JSON,
                ) from exc
            continue

        report = cleaner.audit(parsed)
        if report.findings:
            yield JSONLScanRecord(line_number=line_number, findings=report.findings)


def _validate_on_error(on_error: str) -> None:
    if on_error not in ("raise", "skip", "placeholder"):
        raise ValueError(f"on_error must be 'raise', 'skip', or 'placeholder'; got {on_error!r}")


def _require_path(source: _OutputPath, name: str) -> Path:
    if isinstance(source, (str, Path)):
        return Path(source)
    raise TypeError(f"{name} must be a file path (str or Path) for atomic write")


def _iter_source_lines(source: _SourceType) -> Iterator[_SourceLine]:
    """Yield decoded source lines without loading the entire source.

    Paths are read as bytes so decoding errors are isolated to one physical
    line. Existing text streams are never closed by this function.
    """
    if isinstance(source, (str, Path)):
        with open(Path(source), "rb") as stream:
            yield from _iter_lines(stream)
        return

    yield from _iter_lines(source)


def _iter_lines(stream: _SourceStream) -> Iterator[_SourceLine]:
    """Yield line number, decoded text, and an optional safe error reason."""
    iterator = iter(stream)
    line_number = 0

    while True:
        try:
            raw_line = next(iterator)
        except StopIteration:
            return
        except UnicodeDecodeError:
            # A caller-provided text stream may fail inside its decoder. Its
            # state is not guaranteed to be recoverable, so report one error
            # record and stop without exposing decoder input.
            yield line_number + 1, None, _LIMIT_INVALID_UTF8
            return

        line_number += 1

        if isinstance(raw_line, bytes):
            try:
                decoded = raw_line.decode("utf-8")
            except UnicodeDecodeError:
                yield line_number, None, _LIMIT_INVALID_UTF8
                continue
        else:
            # ``stream`` is a union of text and binary streams. Mypy cannot
            # always narrow the result of ``next(iterator)`` to ``str`` here,
            # even though the bytes branch was handled above.
            decoded = cast(str, raw_line)

        yield line_number, decoded, None


def _line_processing_error(line_number: int, reason: str) -> JSONLProcessingError:
    """Build a safe public exception for one invalid source line."""
    description = "invalid UTF-8" if reason == _LIMIT_INVALID_UTF8 else "invalid JSON"
    return JSONLProcessingError(
        f"{description} at line {line_number}",
        line_number=line_number,
        reason=reason,
    )


def _placeholder_result(line_number: int, reason: str) -> SafeDataResult:
    """Return a safe placeholder result without retaining source content."""
    return SafeDataResult(
        cleaned={"_logprivacy_error": reason, "_line": line_number},
        complete=False,
        limitations=(reason,),
        stats=SafeDataStats(),
    )


def _write_placeholder(stream: TextIO, line_number: int, reason: str) -> None:
    """Write one safe error placeholder as JSONL."""
    placeholder = {
        "_logprivacy_error": reason,
        "_line": line_number,
    }
    stream.write(_json.dumps(placeholder, allow_nan=False))
    stream.write("\n")


def _append_unique(values: list[str], value: str) -> None:
    """Append ``value`` once while preserving first-seen order."""
    if value not in values:
        values.append(value)
