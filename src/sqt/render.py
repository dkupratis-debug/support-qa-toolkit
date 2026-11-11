"""Render bug reports and triage summaries as Markdown or JSON."""

from __future__ import annotations

import json

from sqt.logs import TriageReport
from sqt.severity import classify
from sqt.tickets import Ticket, open_questions

_ENV_FIELDS = (
    ("Product", "product"),
    ("Version", "version"),
    ("Environment", "environment"),
    ("OS", "os"),
    ("Browser", "browser"),
    ("Reported", "reported_at"),
    ("Role", "role"),
    ("Frequency", "frequency"),
)


def render_bug_report(ticket: Ticket) -> str:
    """Build the Markdown bug report for a parsed ticket."""

    severity = classify(ticket)
    questions = open_questions(ticket)
    title = ticket.subject or "Untitled report"
    lines = [
        f"# Bug: {title}",
        "",
        f"- **Source ticket:** {_or_missing(ticket.ticket_id)}",
        f"- **Severity:** {severity.level.capitalize()} (`{severity.rule}`)",
        f"- **Rationale:** {severity.rationale}",
        "",
        "## Summary",
        "",
        ticket.description or "No description was provided.",
        "",
        "## Environment",
        "",
        "| Field | Value |",
        "| --- | --- |",
    ]
    for label, attr in _ENV_FIELDS:
        lines.append(f"| {label} | {_cell(getattr(ticket, attr))} |")
    lines.extend(
        [
            "",
            "## Steps to reproduce",
            "",
        ]
    )
    if ticket.steps:
        lines.extend(f"{index}. {step}" for index, step in enumerate(ticket.steps, start=1))
    else:
        lines.append("No steps were written down.")
    lines.extend(
        [
            "",
            "## Expected",
            "",
            ticket.expected or "Not stated.",
            "",
            "## Actual",
            "",
            ticket.actual or "Not stated.",
            "",
            "## Open questions",
            "",
        ]
    )
    if questions:
        lines.extend(f"- {question}" for question in questions)
    else:
        lines.append("None.")
    if ticket.notes:
        lines.extend(["", "## Reporter notes", "", ticket.notes])
    lines.extend(
        [
            "",
            "## Heuristics",
            "",
            f"- Parsed as {ticket.source_format}.",
            "- Severity is the first matching rule in `sqt.severity`. "
            "Content rules outrank the priority written on the ticket.",
            "- Steps come only from a steps field or a steps section. "
            "They are not inferred from the description.",
            "",
        ]
    )
    return "\n".join(lines)


def render_triage_markdown(report: TriageReport) -> str:
    """Build the Markdown triage summary."""

    window = "n/a"
    if report.window_start and report.window_end:
        window = f"{report.window_start} → {report.window_end}"
    unrecognized = len(report.unrecognized_lines)
    lines = [
        f"# Log triage: {report.filename}",
        "",
        (
            f"- **Lines:** {report.total_lines} total, {report.parsed_lines} parsed, "
            f"{unrecognized} unrecognized, {report.blank_lines} blank"
        ),
        f"- **Window:** {window}",
        f"- **Errors:** {report.error_count}",
        f"- **Warnings:** {report.warning_count}",
        "",
        "## Errors by type",
        "",
    ]
    if report.groups:
        lines.extend(
            [
                "| Type | Count | First seen | Last seen | Repeated | Example |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for group in report.groups:
            repeated = "yes" if group.repeated else "no"
            cells = (
                _cell(group.error_type),
                str(group.count),
                _cell(group.first_seen),
                _cell(group.last_seen),
                repeated,
                _cell(group.example),
            )
            lines.append("| " + " | ".join(cells) + " |")
    else:
        lines.append("No error-level lines.")
    lines.extend(["", "## Spikes", ""])
    if report.spikes:
        for spike in report.spikes:
            median = _format_median(spike.median_bucket_count)
            lines.append(
                f"- **{spike.error_type}** at {spike.bucket_start}: "
                f"{spike.count} errors in {spike.bucket_minutes} minutes "
                f"(median bucket for this type is {median})."
            )
    else:
        lines.append("None.")
    lines.extend(["", "## Repeated issues", ""])
    if report.repeated:
        for group in report.repeated:
            lines.append(
                f"- **{group.error_type}** — {group.count} times, "
                f"from {group.first_seen} to {group.last_seen}."
            )
    else:
        lines.append("None.")
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {note}" for note in report.notes)
    lines.append("")
    return "\n".join(lines)


def render_triage_json(report: TriageReport) -> str:
    """Build the JSON triage summary."""

    return json.dumps(report.to_dict(), indent=2, ensure_ascii=False) + "\n"


def _or_missing(value: str | None) -> str:
    return value if value else "not provided"


def _cell(value: str | None) -> str:
    if not value:
        return "not provided"
    return value.replace("|", "\\|").replace("\n", " ")


def _format_median(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return str(value)
