"""Parse an application log and summarize errors.

Recognized lines, and only these:

* ``2026-03-14T09:02:14Z ERROR api error_type=TimeoutError message="..."``
* ``2026-03-14 09:05:12,018 ERROR paperlane.billing: TimeoutError: ...``
* ``[2026-03-14T09:02:14Z] [ERROR] message``
* A JSON object on one line with a timestamp field (``ts``, ``timestamp``,
  ``time``, or ``datetime``) and a level field (``level``, ``severity``, or
  ``lvl``).

The level is the token after the timestamp (or the JSON level). ``WARNING``
and ``WARN`` are warnings. ``ERROR``, ``FATAL``, and ``CRITICAL`` are errors.
Other levels are counted as parsed context and left out of the error table.

Error type, first match wins:

1. An ``error_type`` / ``exception`` field.
2. An exception class in the message, such as ``TimeoutError``.
3. An HTTP 5xx status, reported as ``HTTP_503``.
4. The message itself, with numbers and UUIDs replaced by ``#`` and a
   ``message:`` prefix. Two wordings of the same bug can still split.

Timestamps without a zone are treated as UTC. Spike buckets are 5 minutes
in UTC, computed per error type. A spike is a bucket with at least 3 events
of that type and a count at least 3 times the median of that type's
non-empty buckets. A type seen in only one bucket is not a spike, because
there is no baseline. A repeated issue is the same type on at least 3 lines
anywhere in the file.

Blank lines are ignored. A non-empty file that yields no recognized lines is
an error. A line that does not match is skipped and reported, not fatal.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from sqt.errors import SqtError
from sqt.tickets import read_text

SPIKE_BUCKET_MINUTES = 5
SPIKE_MIN_COUNT = 3
SPIKE_MEDIAN_FACTOR = 3
REPEATED_MIN_COUNT = 3

_TS = r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?"
_LEVEL = r"CRITICAL|FATAL|ERROR|WARNING|WARN|INFO|DEBUG|TRACE"
_PLAIN_RE = re.compile(rf"^(?P<ts>{_TS})\s+(?P<level>{_LEVEL})\b\s*(?P<rest>.*)$", re.IGNORECASE)
_BRACKET_RE = re.compile(
    rf"^\[(?P<ts>{_TS})\]\s+\[?(?P<level>{_LEVEL})\]?\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_ERROR_TYPE_RE = re.compile(
    r"\berror[_ ]?type=(\"[^\"]+\"|'[^']+'|[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)
_EXCEPTION_RE = re.compile(r"\b([A-Z][A-Za-z0-9_]*(?:Error|Exception|Fault))\b")
_HTTP_5XX_RE = re.compile(r"\b(?:status(?:_code)?|http)\s*[=:]?\s*(5\d\d)\b", re.IGNORECASE)
_MESSAGE_RE = re.compile(r'\bmessage="([^"]*)"|\bmessage=(\S+)', re.IGNORECASE)
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_NUMBER_RE = re.compile(r"\d+")

_TS_KEYS = ("ts", "timestamp", "time", "datetime")
_LEVEL_KEYS = ("level", "severity", "lvl")
_TYPE_KEYS = ("error_type", "errorType", "exception")
_MESSAGE_KEYS = ("message", "msg", "error")

_LEVEL_MAP = {
    "trace": "DEBUG",
    "debug": "DEBUG",
    "info": "INFO",
    "warn": "WARN",
    "warning": "WARN",
    "error": "ERROR",
    "fatal": "CRITICAL",
    "critical": "CRITICAL",
    "err": "ERROR",
}


@dataclass
class LogEvent:
    line_no: int
    timestamp_raw: str
    timestamp: datetime | None
    level: str
    message: str
    error_type: str | None
    raw: str


@dataclass
class ParseResult:
    filename: str
    events: list[LogEvent]
    total_lines: int
    blank_lines: int
    unrecognized: list[int] = field(default_factory=list)


@dataclass
class ErrorGroup:
    error_type: str
    count: int
    first_seen: str | None
    last_seen: str | None
    repeated: bool
    example: str


@dataclass
class Spike:
    error_type: str
    bucket_start: str
    count: int
    median_bucket_count: float
    bucket_minutes: int = SPIKE_BUCKET_MINUTES


@dataclass
class TriageReport:
    filename: str
    total_lines: int
    parsed_lines: int
    blank_lines: int
    unrecognized_lines: list[int]
    window_start: str | None
    window_end: str | None
    error_count: int
    warning_count: int
    groups: list[ErrorGroup]
    spikes: list[Spike]
    notes: list[str]

    @property
    def repeated(self) -> list[ErrorGroup]:
        return [group for group in self.groups if group.repeated]

    def to_dict(self) -> dict[str, object]:
        return {
            "file": self.filename,
            "total_lines": self.total_lines,
            "parsed_lines": self.parsed_lines,
            "blank_lines": self.blank_lines,
            "unrecognized_lines": self.unrecognized_lines,
            "window": {"start": self.window_start, "end": self.window_end},
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "errors_by_type": [
                {
                    "type": group.error_type,
                    "count": group.count,
                    "first_seen": group.first_seen,
                    "last_seen": group.last_seen,
                    "repeated": group.repeated,
                    "example": group.example,
                }
                for group in self.groups
            ],
            "spikes": [
                {
                    "type": spike.error_type,
                    "bucket_start": spike.bucket_start,
                    "bucket_minutes": spike.bucket_minutes,
                    "count": spike.count,
                    "median_bucket_count": spike.median_bucket_count,
                }
                for spike in self.spikes
            ],
            "repeated": [group.error_type for group in self.repeated],
            "notes": self.notes,
        }


def triage_file(path: Path) -> TriageReport:
    """Parse and summarize the log at ``path``."""

    text = read_text(path)
    if not text.strip():
        raise SqtError("log file is empty")
    parsed = parse_log(text, filename=path.name)
    if not parsed.events:
        raise SqtError(_unrecognized_message(path.name, text))
    return summarize(parsed)


def parse_log(text: str, filename: str = "<log>") -> ParseResult:
    events: list[LogEvent] = []
    unrecognized: list[int] = []
    total = 0
    blank = 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        total += 1
        if not line.strip():
            blank += 1
            continue
        event = parse_line(line_no, line)
        if event is None:
            unrecognized.append(line_no)
        else:
            events.append(event)
    return ParseResult(
        filename=filename,
        events=events,
        total_lines=total,
        blank_lines=blank,
        unrecognized=unrecognized,
    )


def parse_line(line_no: int, line: str) -> LogEvent | None:
    stripped = line.strip()
    if stripped.startswith("{"):
        return _parse_json_line(line_no, stripped, line)
    match = _PLAIN_RE.match(stripped) or _BRACKET_RE.match(stripped)
    if not match:
        return None
    level = _normalize_level(match.group("level"))
    if level is None:
        return None
    raw_ts = match.group("ts")
    rest = match.group("rest").strip()
    message = _message_from_rest(rest) or rest
    error_type = _error_type_from_text(rest) if level in {"ERROR", "CRITICAL"} else None
    if level in {"ERROR", "CRITICAL"} and not error_type:
        error_type = normalize_message(message)
    return LogEvent(
        line_no=line_no,
        timestamp_raw=raw_ts,
        timestamp=parse_timestamp(raw_ts),
        level=level,
        message=message,
        error_type=error_type,
        raw=line,
    )


def summarize(parsed: ParseResult) -> TriageReport:
    errors = [event for event in parsed.events if event.level in {"ERROR", "CRITICAL"}]
    warnings = [event for event in parsed.events if event.level == "WARN"]
    groups = _group_errors(errors)
    spikes = _find_spikes(errors)
    # Window follows parsed time, not file order, so a shuffled log still reports
    # the real first and last instant.
    ordered = sorted(
        (event for event in parsed.events if event.timestamp is not None),
        key=lambda event: event.timestamp or datetime.min.replace(tzinfo=UTC),
    )
    notes = _notes(parsed, errors, spikes)
    return TriageReport(
        filename=parsed.filename,
        total_lines=parsed.total_lines,
        parsed_lines=len(parsed.events),
        blank_lines=parsed.blank_lines,
        unrecognized_lines=list(parsed.unrecognized),
        window_start=ordered[0].timestamp_raw if ordered else None,
        window_end=ordered[-1].timestamp_raw if ordered else None,
        error_count=len(errors),
        warning_count=len(warnings),
        groups=groups,
        spikes=spikes,
        notes=notes,
    )


def parse_timestamp(value: str) -> datetime | None:
    """Parse a log timestamp. Naive values are read as UTC. ``None`` if it fails."""

    text = value.strip().replace("Z", "+00:00")
    text = re.sub(r",(?=\d)", ".", text, count=1)
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_message(message: str) -> str:
    """Build a stable fallback error type from a free-text message."""

    text = message.strip().strip('"').strip("'").lower()
    text = _UUID_RE.sub("#", text)
    text = _NUMBER_RE.sub("#", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = text[:60].rstrip()
    if not text:
        return "unknown"
    return f"message:{text}"


def _group_errors(errors: list[LogEvent]) -> list[ErrorGroup]:
    grouped: dict[str, list[LogEvent]] = defaultdict(list)
    for event in errors:
        grouped[event.error_type or "unknown"].append(event)
    groups: list[ErrorGroup] = []
    for error_type, events in grouped.items():
        ordered = sorted(events, key=_event_sort_key)
        groups.append(
            ErrorGroup(
                error_type=error_type,
                count=len(events),
                first_seen=ordered[0].timestamp_raw,
                last_seen=ordered[-1].timestamp_raw,
                repeated=len(events) >= REPEATED_MIN_COUNT,
                example=_short_example(ordered[0].message),
            )
        )
    groups.sort(key=lambda group: (-group.count, group.error_type))
    return groups


def _find_spikes(errors: list[LogEvent]) -> list[Spike]:
    by_type: dict[str, list[LogEvent]] = defaultdict(list)
    for event in errors:
        if event.timestamp is None:
            continue
        by_type[event.error_type or "unknown"].append(event)

    spikes: list[Spike] = []
    for error_type, events in by_type.items():
        buckets: dict[datetime, int] = defaultdict(int)
        for event in events:
            assert event.timestamp is not None
            buckets[_floor_bucket(event.timestamp)] += 1
        if len(buckets) < 2:
            continue
        counts = list(buckets.values())
        median = float(statistics.median(counts))
        threshold = SPIKE_MEDIAN_FACTOR * median
        for bucket_start, count in buckets.items():
            if count >= SPIKE_MIN_COUNT and count >= threshold:
                spikes.append(
                    Spike(
                        error_type=error_type,
                        bucket_start=_format_utc(bucket_start),
                        count=count,
                        median_bucket_count=median,
                    )
                )
    spikes.sort(key=lambda spike: (spike.bucket_start, spike.error_type))
    return spikes


def _notes(parsed: ParseResult, errors: list[LogEvent], spikes: list[Spike]) -> list[str]:
    notes = [
        (
            f"Spike rule: per error type, a {SPIKE_BUCKET_MINUTES}-minute UTC bucket "
            f"with at least {SPIKE_MIN_COUNT} events and a count at least "
            f"{SPIKE_MEDIAN_FACTOR}× the median of that type's non-empty buckets. "
            "A type seen in only one bucket is not a spike."
        ),
        f"Repeated rule: the same error type on at least {REPEATED_MIN_COUNT} lines.",
    ]
    if not errors:
        notes.append("No error-level lines in this log.")
    elif not spikes:
        notes.append("No bucket cleared the spike rule.")
    if parsed.unrecognized:
        shown = ", ".join(str(number) for number in parsed.unrecognized[:5])
        extra = len(parsed.unrecognized) - 5
        if extra > 0:
            shown = f"{shown} (and {extra} more)"
        notes.append(f"Unrecognized lines were ignored: {shown}.")
    untimed = sum(1 for event in errors if event.timestamp is None)
    if untimed:
        notes.append(
            f"{untimed} error line(s) had no parseable timestamp "
            "and were left out of spike buckets."
        )
    return notes


def _parse_json_line(line_no: int, stripped: str, raw: str) -> LogEvent | None:
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    raw_ts = _first_present(data, _TS_KEYS)
    raw_level = _first_present(data, _LEVEL_KEYS)
    if not isinstance(raw_ts, str) or not isinstance(raw_level, str):
        return None
    level = _normalize_level(raw_level)
    if level is None:
        return None
    message = _first_present(data, _MESSAGE_KEYS)
    message_text = message.strip() if isinstance(message, str) else ""
    error_type = None
    if level in {"ERROR", "CRITICAL"}:
        explicit = _first_present(data, _TYPE_KEYS)
        if isinstance(explicit, str) and explicit.strip():
            error_type = explicit.strip().strip('"').strip("'")
        else:
            error_type = _error_type_from_text(message_text) or normalize_message(message_text)
    return LogEvent(
        line_no=line_no,
        timestamp_raw=raw_ts.strip(),
        timestamp=parse_timestamp(raw_ts),
        level=level,
        message=message_text or stripped,
        error_type=error_type,
        raw=raw,
    )


def _unrecognized_message(filename: str, text: str) -> str:
    nonempty = [line.strip() for line in text.splitlines() if line.strip()]
    if nonempty and all(line.startswith("{") for line in nonempty):
        invalid = False
        for line in nonempty:
            try:
                json.loads(line)
            except json.JSONDecodeError:
                invalid = True
                break
        if invalid:
            return (
                f"no recognized log lines in {filename!r}. "
                "The lines look like JSON but are not valid."
            )
        return (
            f"no recognized log lines in {filename!r}. "
            "JSON lines need a timestamp (ts, timestamp, time, or datetime) and a level."
        )
    return (
        f"no recognized log lines in {filename!r}. "
        "Expected a timestamp plus a level (DEBUG, INFO, WARN, ERROR, CRITICAL) "
        "or JSON lines with a timestamp and a level."
    )


def _message_from_rest(rest: str) -> str:
    match = _MESSAGE_RE.search(rest)
    if not match:
        return ""
    return (match.group(1) if match.group(1) is not None else match.group(2)).strip()


def _error_type_from_text(text: str) -> str | None:
    explicit = _ERROR_TYPE_RE.search(text)
    if explicit:
        return explicit.group(1).strip().strip('"').strip("'")
    exception = _EXCEPTION_RE.search(text)
    if exception:
        return exception.group(1)
    http = _HTTP_5XX_RE.search(text)
    if http:
        return f"HTTP_{http.group(1)}"
    return None


def _normalize_level(level: str) -> str | None:
    return _LEVEL_MAP.get(level.strip().lower())


def _first_present(data: dict[str, object], keys: tuple[str, ...]) -> object | None:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def _event_sort_key(event: LogEvent) -> tuple[int, datetime | str]:
    if event.timestamp is not None:
        return (0, event.timestamp)
    return (1, event.timestamp_raw)


def _floor_bucket(moment: datetime) -> datetime:
    moment = moment.astimezone(UTC).replace(second=0, microsecond=0)
    minute = moment.minute - (moment.minute % SPIKE_BUCKET_MINUTES)
    return moment.replace(minute=minute)


def _format_utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _short_example(message: str, limit: int = 120) -> str:
    text = re.sub(r"\s+", " ", message).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
