"""Command-line interface for LogPrivacy."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from logprivacy.api import clean_file, clean_text, scan_file
from logprivacy.policy import CleanerPolicy


def _policy(name: str) -> CleanerPolicy:
    if name == "default":
        return CleanerPolicy.default()
    if name == "strict":
        return CleanerPolicy.strict()
    if name == "web":
        return CleanerPolicy.web()
    if name == "production":
        return CleanerPolicy.production()
    raise ValueError(f"Unknown policy: {name}")


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="logprivacy", description="Clean sensitive data from logs."
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    text_parser = subcommands.add_parser("text", help="Clean a text value.")
    text_parser.add_argument("value")
    text_parser.add_argument(
        "--policy", choices=["default", "strict", "web", "production"], default="default"
    )

    scan_parser = subcommands.add_parser("scan", help="Scan a log file and report risk.")
    scan_parser.add_argument("path", type=Path)
    scan_parser.add_argument(
        "--policy", choices=["default", "strict", "web", "production"], default="default"
    )

    clean_parser = subcommands.add_parser("clean", help="Clean a log file.")
    clean_parser.add_argument("path", type=Path)
    clean_parser.add_argument("--output", type=Path, required=True)
    clean_parser.add_argument(
        "--policy", choices=["default", "strict", "web", "production"], default="default"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the LogPrivacy CLI."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "text":
        print(clean_text(args.value, policy=_policy(args.policy)))
        return 0

    if args.command == "scan":
        report = scan_file(args.path, policy=_policy(args.policy))
        print(report.describe())
        return 1 if not report.safe else 0

    if args.command == "clean":
        output = clean_file(args.path, output=args.output, policy=_policy(args.policy))
        print(f"Wrote cleaned file: {output}")
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
