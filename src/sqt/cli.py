"""Command line for ticket2bug and triage.

Exit status is 0 on a written report and 2 on a bad invocation or a bad file.
Known input problems are printed as ``sqt: ...`` on stderr. They do not
produce a traceback.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqt.errors import SqtError
from sqt.logs import triage_file
from sqt.render import render_bug_report, render_triage_json, render_triage_markdown
from sqt.tickets import load_ticket

_BUG_EPILOG = """\
severity rules run in order: data loss, security, total outage, HTTP 500 or
crash, blocked core action, cosmetic wording, stated urgent priority, stated
low priority, intermittent, then a medium default. The report names the rule
that fired. See the README for the full list.
"""

_TRIAGE_EPILOG = """\
a spike is a 5-minute bucket of one error type with at least 3 events and a
count at least 3x that type's median non-empty bucket. The same type on at
least 3 lines, anywhere in the file, is a repeated issue.
"""


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns a process exit code."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "ticket2bug":
            text = render_bug_report(load_ticket(Path(args.file)))
        else:
            report = triage_file(Path(args.file))
            if args.format == "json":
                text = render_triage_json(report)
            else:
                text = render_triage_markdown(report)
        _emit(text, args.output)
    except SqtError as exc:
        print(f"sqt: {exc}", file=sys.stderr)
        return exc.exit_code
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sqt",
        description="Turn support tickets and app logs into bug reports and triage summaries.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ticket = subparsers.add_parser(
        "ticket2bug",
        help="Write a Markdown bug report from a plain-text or JSON ticket",
        description="Read a support ticket and write a structured Markdown bug report.",
        epilog=_BUG_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ticket.add_argument("file", help="Path to a plain-text or JSON ticket")
    ticket.add_argument(
        "-o",
        "--output",
        help="Write the report to this path instead of stdout",
    )

    triage = subparsers.add_parser(
        "triage",
        help="Summarize error counts, spikes, and repeats in an application log",
        description="Scan an application log and summarize errors by type.",
        epilog=_TRIAGE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    triage.add_argument("file", help="Path to a text log or JSON-lines log")
    triage.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
        help="Output format (default: markdown)",
    )
    triage.add_argument(
        "-o",
        "--output",
        help="Write the summary to this path instead of stdout",
    )
    return parser


def _emit(text: str, output: str | None) -> None:
    if not text.endswith("\n"):
        text += "\n"
    if output is None:
        sys.stdout.write(text)
        return
    path = Path(output)
    try:
        path.write_text(text, encoding="utf-8")
    except OSError as exc:
        reason = exc.strerror or "unable to write"
        raise SqtError(f"could not write {path}: {reason}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
