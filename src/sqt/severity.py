"""Map a ticket to a severity with an explicit rule name and rationale.

Rules run in the order below. The first match wins. Customer priority is a
signal of its own, and it never overrides a stronger content rule: a deleted
data report stays critical even if the form says "low", and a typo stays low
even if the form says "urgent".

1. ``data_loss`` — critical. Records, files, invoices, documents, or data
   described as deleted, wiped, erased, corrupted, disappeared, or gone.
2. ``security`` — critical. A named class of security failure (injection,
   takeover, exposed credentials, unauthorized access). The bare word
   "security" is not enough.
3. ``total_outage`` — critical. The service is down, or every user is blocked.
4. ``http_500_or_crash`` — high. A crash, a traceback, an uncaught exception,
   or an HTTP 500.
5. ``core_action_blocked`` — high. A core action (sign in, pay, checkout,
   export, download, upload, save, delete) and a failure word sit within
   160 characters of each other. They do not have to be in one sentence,
   and a failure word alone is not enough.
6. ``cosmetic`` — low. Typo, spelling, wording, alignment, or the wrong color.
7. ``stated_urgent`` — high. Priority is urgent, critical, highest, blocker,
   high, P0, or Sev-1, and nothing above matched. A stated "critical" stays
   high unless a critical content rule matched.
8. ``stated_low`` — low. Priority is low, minor, trivial, P3, P4, or Sev-3,
   and nothing above matched.
9. ``intermittent`` — medium. The text says the issue is intermittent, or
   that a workaround exists.
10. ``default`` — medium. No rule above matched, so the report stays in the
    queue instead of being dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqt.tickets import Ticket

_DATA_LOSS_RE = re.compile(
    r"\bdata loss\b"
    r"|\b(?:data|files|invoices|records|documents)\b.{0,48}\b"
    r"(?:deleted|wiped|erased|corrupted|disappeared|gone)\b"
    r"|\b(?:deleted|wiped|erased|corrupted)\b.{0,48}\b"
    r"(?:data|files|invoices|records|documents)\b",
    re.IGNORECASE | re.DOTALL,
)
_SECURITY_RE = re.compile(
    r"\b(?:xss|csrf|sql injection|account takeover|privilege escalation|"
    r"unauthorized access|security breach|credential leak)\b"
    r"|\b(?:password|token|api key)s?\b.{0,24}\b(?:exposed|leaked|logged)\b",
    re.IGNORECASE | re.DOTALL,
)
_OUTAGE_RE = re.compile(
    r"\b(?:site|app|application|service|production) (?:is )?down\b"
    r"|\bcomplete outage\b"
    r"|\ball (?:users|customers) (?:cannot|can't|are unable|unable)\b",
    re.IGNORECASE,
)
_CRASH_RE = re.compile(
    r"\b(?:crash(?:es|ed|ing)?|traceback|uncaught exception|internal server error)\b"
    r"|\b(?:status(?: code)?\s*500|http\s*500|500 error|error 500)\b",
    re.IGNORECASE,
)
_ACTION_RE = re.compile(
    r"\b(log(?:ging)? ?in|sign(?:ing)? in|sign-in|pay(?:ment|ing)?|checkout|"
    r"export(?:ing)?|download(?:ing)?|upload(?:ing)?|sav(?:e|ing)|delet(?:e|ing))\b",
    re.IGNORECASE,
)
_FAILURE_RE = re.compile(
    r"\b(cannot|can't|unable to|fails? to|failed to|hang(?:s|ing)?|hung|stuck|"
    r"spin(?:s|ner|ning)?|never (?:finishes|loads|downloads|stops)|"
    r"times? out|timed out|timeout|login loop|redirect loop)\b",
    re.IGNORECASE,
)
_COSMETIC_RE = re.compile(
    r"\b(typo|cosmetic|misaligned|alignment|wrong colou?r|pixel|wording|spelling)\b",
    re.IGNORECASE,
)
_INTERMITTENT_RE = re.compile(
    r"\b(workaround|sometimes|intermittent(?:ly)?|occasionally)\b",
    re.IGNORECASE,
)

_URGENT_PRIORITIES = {
    "urgent",
    "critical",
    "highest",
    "blocker",
    "p0",
    "sev-0",
    "sev0",
    "sev-1",
    "sev1",
    "high",
}
_LOW_PRIORITIES = {"low", "minor", "trivial", "p3", "p4", "sev-3", "sev3", "lowest"}

# How far apart a core action and a failure word may be and still count.
_ACTION_WINDOW = 160


@dataclass(frozen=True)
class Severity:
    level: str
    rule: str
    rationale: str


def classify(ticket: Ticket) -> Severity:
    """Return the first matching severity rule for ``ticket``."""

    text = ticket.corpus()
    priority = _normalize_priority(ticket.priority)

    match = _first(_DATA_LOSS_RE, text)
    if match:
        return Severity(
            "critical",
            "data_loss",
            f'Describes data being deleted, erased, corrupted, or gone ("{match}").',
        )

    match = _first(_SECURITY_RE, text)
    if match:
        return Severity(
            "critical",
            "security",
            f'Describes a security failure ("{match}").',
        )

    match = _first(_OUTAGE_RE, text)
    if match:
        return Severity(
            "critical",
            "total_outage",
            f'Describes a full outage ("{match}").',
        )

    match = _first(_CRASH_RE, text)
    if match:
        return Severity(
            "high",
            "http_500_or_crash",
            f'Mentions a crash or an HTTP 500 ("{match}").',
        )

    paired = _action_and_failure(text)
    if paired:
        action, failure = paired
        return Severity(
            "high",
            "core_action_blocked",
            f"A core action ({action}) is paired with a failure ({failure}).",
        )

    match = _first(_COSMETIC_RE, text)
    if match:
        rationale = f'Wording is cosmetic ("{match}").'
        if priority in _URGENT_PRIORITIES:
            rationale += (
                f' Stated priority "{priority}" was not raised, because the wording is cosmetic.'
            )
        return Severity("low", "cosmetic", rationale)

    if priority in _URGENT_PRIORITIES:
        named_critical = {
            "critical",
            "urgent",
            "highest",
            "blocker",
            "p0",
            "sev-0",
            "sev0",
            "sev-1",
            "sev1",
        }
        if priority in named_critical:
            rationale = (
                f'Priority is "{priority}". No outage, data-loss, or security signal, '
                "so this is high rather than critical."
            )
        else:
            rationale = f'Priority is "{priority}", and no stronger content rule matched.'
        return Severity("high", "stated_urgent", rationale)

    if priority in _LOW_PRIORITIES:
        return Severity(
            "low",
            "stated_low",
            f'Priority is "{priority}", and the text has no higher-severity signal.',
        )

    match = _first(_INTERMITTENT_RE, text)
    if match:
        return Severity(
            "medium",
            "intermittent",
            f'Described as intermittent or as having a workaround ("{match}"), '
            "with no stronger failure signal.",
        )

    return Severity(
        "medium",
        "default",
        "No data-loss, security, outage, crash, blocked-workflow, or cosmetic signal. "
        "Defaulting to medium so the report stays in the review queue.",
    )


def _normalize_priority(priority: str | None) -> str:
    if not priority:
        return ""
    return re.sub(r"\s+", " ", priority).strip().lower()


def _first(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    snippet = re.sub(r"\s+", " ", match.group(0)).strip()
    return snippet


def _action_and_failure(text: str) -> tuple[str, str] | None:
    """Return the action and failure words when they land in one window."""

    for action in _ACTION_RE.finditer(text):
        window = text[
            max(0, action.start() - _ACTION_WINDOW) : min(len(text), action.end() + _ACTION_WINDOW)
        ]
        failure = _FAILURE_RE.search(window)
        if failure:
            return action.group(0), failure.group(0)
    return None
