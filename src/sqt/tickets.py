"""Parse a support ticket from plain text or a JSON object.

Plain text uses labeled lines. A label is a known field name, a colon, and an
optional value. Section labels (description, steps, expected, actual, notes)
keep every following line until the next known label. Other labels take the
rest of their line, and extra lines stay with that label until the next one.

A file whose first non-space character is ``{`` or ``[`` is JSON. Invalid JSON
is an error, not a text ticket. There is no network access and no language model.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from sqt.errors import SqtError

_LABEL_RE = re.compile(r"^([A-Za-z][A-Za-z ]{0,40}):\s*(.*)$")

# One-line fields. The key is the normalized label ("user role" -> user role).
_SINGLE_FIELDS = {
    "ticket": "ticket_id",
    "ticket id": "ticket_id",
    "id": "ticket_id",
    "product": "product",
    "app": "product",
    "application": "product",
    "version": "version",
    "build": "version",
    "environment": "environment",
    "env": "environment",
    "browser": "browser",
    "os": "os",
    "operating system": "os",
    "platform": "os",
    "priority": "priority",
    "severity": "priority",
    "customer priority": "priority",
    "summary": "subject",
    "reported": "reported_at",
    "reported at": "reported_at",
    "date": "reported_at",
    "role": "role",
    "user role": "role",
    "plan": "role",
    "subject": "subject",
    "title": "subject",
    "frequency": "frequency",
    "how often": "frequency",
    "repro": "frequency",
}

_SECTION_FIELDS = {
    "description": "description",
    "details": "description",
    "body": "description",
    "steps": "steps",
    "steps to reproduce": "steps",
    "steps i tried": "steps",
    "repro steps": "steps",
    "expected": "expected",
    "expected behavior": "expected",
    "expected result": "expected",
    "actual": "actual",
    "actual behavior": "actual",
    "actual result": "actual",
    "notes": "notes",
}

_JSON_ALIASES = {
    "ticket_id": ("id", "ticket", "ticket_id", "key"),
    "product": ("product", "app", "application"),
    "version": ("version", "app_version", "build"),
    "environment": ("environment", "env"),
    "browser": ("browser", "client"),
    "os": ("os", "operating_system", "platform"),
    "priority": ("priority", "severity", "customer_priority"),
    "reported_at": ("reported_at", "reported", "created_at", "timestamp"),
    "role": ("role", "user_role", "account_role", "plan"),
    "subject": ("subject", "title", "summary"),
    "description": ("description", "body", "details"),
    "steps": ("steps", "steps_to_reproduce", "repro_steps"),
    "expected": ("expected", "expected_result", "expected_behavior"),
    "actual": ("actual", "actual_result", "actual_behavior"),
    "frequency": ("frequency", "repro", "how_often"),
    "notes": ("notes",),
}

_STEP_MARKER = re.compile(r"^(?:\d+[\.\)]\s+|[-*]\s+)(.*)$")
_REQUEST_ID_RE = re.compile(
    r"\b(?:request[_ ]id|trace[_ ]id|correlation[_ ]id|req-[A-Za-z0-9-]+)\b",
    re.IGNORECASE,
)
_WHEN_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
_FREQUENCY_RE = re.compile(
    r"\b(?:always|every time|each time|intermittent(?:ly)?|sometimes|occasionally|"
    r"once|one time|rarely|often|consistently)\b",
    re.IGNORECASE,
)
_ROLE_RE = re.compile(
    r"\b(?:workspace admin|billing admin|admin|owner|member|viewer|end user)\b",
    re.IGNORECASE,
)


@dataclass
class Ticket:
    """Fields a bug report can be built from. Missing values stay None or []."""

    source_format: str
    ticket_id: str | None = None
    product: str | None = None
    version: str | None = None
    environment: str | None = None
    browser: str | None = None
    os: str | None = None
    priority: str | None = None
    reported_at: str | None = None
    role: str | None = None
    subject: str | None = None
    description: str | None = None
    steps: list[str] = field(default_factory=list)
    expected: str | None = None
    actual: str | None = None
    frequency: str | None = None
    notes: str | None = None

    def corpus(self) -> str:
        """All free text, in a stable order, for keyword rules."""

        parts = [
            self.subject,
            self.description,
            self.expected,
            self.actual,
            self.notes,
            "\n".join(self.steps),
        ]
        return "\n".join(part for part in parts if part)


def load_ticket(path: Path) -> Ticket:
    """Read ``path`` and return a ticket, or raise ``SqtError``."""

    text = read_text(path)
    if not text.strip():
        raise SqtError("ticket file is empty")
    return parse_ticket(text)


def parse_ticket(text: str) -> Ticket:
    """Parse ticket text that has already been decoded."""

    stripped = text.lstrip("\ufeff").lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return parse_json_ticket(text)
    return parse_text_ticket(text)


def parse_json_ticket(text: str) -> Ticket:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SqtError(
            f"ticket looks like JSON but is not valid: {exc.msg} (line {exc.lineno})"
        ) from exc
    if isinstance(data, list):
        raise SqtError("ticket JSON must be an object, got a list")
    if not isinstance(data, dict):
        raise SqtError(f"ticket JSON must be an object, got {type(data).__name__}")
    if not data:
        return Ticket(source_format="json")

    values: dict[str, object] = {}
    for field_name, aliases in _JSON_ALIASES.items():
        for alias in aliases:
            if alias in data and data[alias] is not None:
                values[field_name] = data[alias]
                break

    steps_raw = values.pop("steps", None)
    ticket = Ticket(source_format="json")
    for name, raw in values.items():
        setattr(ticket, name, _json_string(name, raw))
    ticket.steps = _json_steps(steps_raw)
    if not ticket.subject:
        ticket.subject = _subject_from_description(ticket.description)
    return ticket


def parse_text_ticket(text: str) -> Ticket:
    buckets: dict[str, list[str]] = {}
    current: str | None = None
    preamble: list[str] = []

    for line in text.lstrip("\ufeff").splitlines():
        label = _match_label(line)
        if label is not None:
            field_name, value = label
            current = field_name
            buckets.setdefault(current, [])
            if value:
                buckets[current].append(value)
            continue
        if current is None:
            preamble.append(line)
        else:
            buckets[current].append(line)

    def take(name: str) -> str | None:
        if name not in buckets:
            return None
        joined = "\n".join(buckets[name]).strip()
        return joined or None

    description = take("description")
    if description is None:
        preamble_text = "\n".join(preamble).strip()
        description = preamble_text or None

    steps_text = take("steps")
    ticket = Ticket(
        source_format="text",
        ticket_id=take("ticket_id"),
        product=take("product"),
        version=take("version"),
        environment=take("environment"),
        browser=take("browser"),
        os=take("os"),
        priority=take("priority"),
        reported_at=take("reported_at"),
        role=take("role"),
        subject=take("subject"),
        description=description,
        steps=split_steps(steps_text) if steps_text else [],
        expected=take("expected"),
        actual=take("actual"),
        frequency=take("frequency"),
        notes=take("notes"),
    )
    if not ticket.subject:
        ticket.subject = _subject_from_description(ticket.description)
    return ticket


def split_steps(text: str) -> list[str]:
    """Turn a steps section into a list.

    Numbered lines and bullet lines win when any of them are present.
    Otherwise each non-empty line is one step. Steps are never invented
    from a description paragraph.
    """

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    marked: list[str] = []
    for line in lines:
        match = _STEP_MARKER.match(line)
        if match and match.group(1).strip():
            marked.append(match.group(1).strip())
    if marked:
        return marked
    return lines


def open_questions(ticket: Ticket) -> list[str]:
    """Questions a support engineer would send back before filing the bug.

    These are absence checks, not guesses. A field counts as present when it
    was labeled or when the free text already contains a clear signal
    (a timestamp, a role word, a frequency word, a request id).
    """

    text = ticket.corpus()
    questions: list[str] = []
    if not ticket.product:
        questions.append("Which product is this, and which version or build?")
    elif not ticket.version:
        questions.append("Which version or build was the user on?")
    if not any((ticket.environment, ticket.os, ticket.browser)):
        questions.append(
            "What environment was this in (production or staging, OS, and browser or client)?"
        )
    if not ticket.steps:
        questions.append("What are the exact steps to reproduce, starting from a known page?")
    if not ticket.expected:
        questions.append("What did the user expect to happen?")
    if not ticket.actual:
        questions.append(
            "What happened instead, including any error text on the page or in the console?"
        )
    if not ticket.frequency and not _FREQUENCY_RE.search(text):
        questions.append("How often does this happen: once, intermittent, or every time?")
    if not ticket.role and not _ROLE_RE.search(text):
        questions.append("What account role or plan was the user on?")
    if not ticket.reported_at and not _WHEN_RE.search(text):
        questions.append("When did this start?")
    if not _REQUEST_ID_RE.search(text):
        questions.append("Is there a request id so this can be matched to application logs?")
    return questions


def read_text(path: Path) -> str:
    """Read a UTF-8 text file or raise ``SqtError`` with a short reason."""

    if not path.exists():
        raise SqtError(f"file not found: {path}")
    if path.is_dir():
        raise SqtError(f"path is a directory: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise SqtError(f"file is not valid UTF-8: {path}") from exc
    except OSError as exc:
        reason = exc.strerror or "unable to read"
        raise SqtError(f"could not read {path}: {reason}") from exc


def _match_label(line: str) -> tuple[str, str] | None:
    match = _LABEL_RE.match(line.strip())
    if not match:
        return None
    label = re.sub(r"\s+", " ", match.group(1)).strip().lower()
    field_name = _SINGLE_FIELDS.get(label) or _SECTION_FIELDS.get(label)
    if field_name is None:
        return None
    return field_name, match.group(2).strip()


def _json_string(field_name: str, raw: object) -> str | None:
    if isinstance(raw, str):
        value = raw.strip()
        return value or None
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        return str(raw)
    raise SqtError(f"ticket field {field_name!r} must be a string")


def _json_steps(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return split_steps(raw)
    if isinstance(raw, list):
        steps: list[str] = []
        for index, item in enumerate(raw, start=1):
            if not isinstance(item, str):
                raise SqtError(f"ticket field 'steps' item {index} must be a string")
            item = item.strip()
            if item:
                steps.append(item)
        return steps
    raise SqtError("ticket field 'steps' must be a string or a list of strings")


def _subject_from_description(description: str | None) -> str | None:
    if not description:
        return None
    for line in description.splitlines():
        cleaned = line.strip()
        if cleaned:
            return _shorten(cleaned, 100)
    return None


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    clipped = text[: limit - 1].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped + "…"
