"""Helpers for scanning and cleaning log files."""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path
from typing import cast

from logprivacy.audit import AuditReport
from logprivacy.cleaner import Cleaner
from logprivacy.internal.audit_location import format_file_location
from logprivacy.internal.traversal import LIMIT_MAX_FINDINGS
from logprivacy.policy import CleanerPolicy
from logprivacy.result import Finding

_TEMP_PREFIX = ".logprivacy-"
_TEMP_SUFFIX = ".tmp"
_FCHMOD = cast(Callable[[int, int], None] | None, getattr(os, "fchmod", None))


def scan_file(
    path: str | Path,
    *,
    policy: CleanerPolicy | None = None,
    encoding: str = "utf-8",
) -> AuditReport:
    """Return an audit report for a text file."""
    cleaner = Cleaner(policy=policy or CleanerPolicy.default())
    findings: list[Finding] = []
    limitations: list[str] = []
    file_path = Path(path)
    safe_name = cleaner._sanitize_location_text(file_path.name)
    line_number = 0
    with file_path.open("r", encoding=encoding, errors="replace") as stream:
        for line in stream:
            line_number += 1
            report = cleaner.audit(line)
            for limitation in report.limitations:
                if limitation not in limitations:
                    limitations.append(limitation)

            remaining = cleaner.policy.max_findings - len(findings)
            if remaining <= 0:
                if LIMIT_MAX_FINDINGS not in limitations:
                    limitations.append(LIMIT_MAX_FINDINGS)
                break

            line_findings = report.findings[:remaining]
            findings.extend(
                f.with_location(
                    format_file_location(
                        safe_name,
                        line=line_number,
                        column=f.start + 1,
                    )
                )
                for f in line_findings
            )
            if len(report.findings) > remaining or len(findings) >= cleaner.policy.max_findings:
                if LIMIT_MAX_FINDINGS not in limitations:
                    limitations.append(LIMIT_MAX_FINDINGS)
                break

    return AuditReport(
        tuple(findings),
        complete=not limitations,
        limitations=tuple(limitations),
    )


def clean_file(
    path: str | Path,
    *,
    output: str | Path,
    policy: CleanerPolicy | None = None,
    encoding: str = "utf-8",
) -> Path:
    """
    Clean a text file and atomically replace the destination.

    The cleaned data is written to a private temporary file in the destination
    directory, flushed to disk, and moved into place with ``os.replace()`` only
    after the complete operation succeeds. Existing destination data therefore
    remains intact if reading, cleaning, encoding, or writing fails.

    Passing the same path as both ``path`` and ``output`` performs safe in-place
    cleaning. Symlink destinations are followed, while ambiguous hard-link
    aliases to the input are rejected.
    """
    cleaner = Cleaner(policy=policy or CleanerPolicy.default())
    input_path = _resolve_input_path(path)
    requested_output = Path(output)
    target_path = _resolve_output_path(requested_output)

    _validate_paths(input_path, target_path)
    target_mode = _target_mode(input_path, target_path)
    temporary_descriptor, temporary_path = _create_temporary_file(target_path)

    try:
        _write_cleaned_file(
            input_path,
            temporary_path,
            temporary_descriptor=temporary_descriptor,
            target_mode=target_mode,
            cleaner=cleaner,
            encoding=encoding,
        )
        os.replace(temporary_path, target_path)
        _fsync_directory(target_path.parent)
    except BaseException:
        _remove_temporary_file(temporary_path)
        raise

    return requested_output


def _resolve_input_path(path: str | Path) -> Path:
    """Resolve and validate the source path before any destination is opened."""
    input_path = Path(path).expanduser().resolve(strict=True)
    if not input_path.is_file():
        if input_path.is_dir():
            raise IsADirectoryError(input_path)
        raise ValueError(f"input path is not a regular file: {input_path}")
    return input_path


def _resolve_output_path(path: Path) -> Path:
    """Resolve the destination while preserving normal symlink-following behavior."""
    return path.expanduser().resolve(strict=False)


def _validate_paths(input_path: Path, target_path: Path) -> None:
    """Reject invalid and ambiguous destinations before creating a temp file."""
    parent = target_path.parent
    if not parent.exists():
        raise FileNotFoundError(parent)
    if not parent.is_dir():
        raise NotADirectoryError(parent)

    if target_path.exists():
        if target_path.is_dir():
            raise IsADirectoryError(target_path)
        if not target_path.is_file():
            raise ValueError(f"output path is not a regular file: {target_path}")

        try:
            same_file = os.path.samefile(input_path, target_path)
        except OSError:
            same_file = False

        if same_file and input_path != target_path:
            raise ValueError(
                "input and output refer to the same file through different hard-link paths; "
                "use the input path itself for in-place cleaning"
            )


def _target_mode(input_path: Path, target_path: Path) -> int:
    """Return permissions to apply to the atomically replaced destination."""
    source = target_path if target_path.exists() else input_path
    return stat.S_IMODE(source.stat().st_mode)


def _create_temporary_file(target_path: Path) -> tuple[int, Path]:
    """Create a private temporary file beside the final destination."""
    file_descriptor, name = tempfile.mkstemp(
        prefix=f"{_TEMP_PREFIX}{target_path.name}-",
        suffix=_TEMP_SUFFIX,
        dir=target_path.parent,
    )
    return file_descriptor, Path(name)


def _write_cleaned_file(
    input_path: Path,
    temporary_path: Path,
    *,
    temporary_descriptor: int,
    target_mode: int,
    cleaner: Cleaner,
    encoding: str,
) -> None:
    """Stream cleaned text into a temporary file and make its contents durable."""
    try:
        target = os.fdopen(
            temporary_descriptor,
            "w",
            encoding=encoding,
            errors="strict",
            newline="",
        )
    except BaseException:
        os.close(temporary_descriptor)
        raise

    with (
        target,
        input_path.open(
            "r",
            encoding=encoding,
            errors="replace",
            newline="",
        ) as source,
    ):
        for line in source:
            target.write(cleaner.clean_text(line))

        if _FCHMOD is not None:
            _FCHMOD(target.fileno(), target_mode)

        target.flush()
        os.fsync(target.fileno())

    if _FCHMOD is None:
        os.chmod(temporary_path, target_mode)


def _remove_temporary_file(path: Path) -> None:
    """Remove an unfinished temporary file without hiding the original failure."""
    with suppress(OSError):
        path.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    """Best-effort directory sync so the replacement survives a sudden restart."""
    if os.name == "nt":
        return

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        file_descriptor = os.open(path, flags)
    except OSError:
        return

    try:
        with suppress(OSError):
            os.fsync(file_descriptor)
    finally:
        os.close(file_descriptor)
