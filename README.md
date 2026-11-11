# support-qa-toolkit

A small command-line tool that does two jobs from the support-to-QA workflow: turn a messy ticket into a structured bug report, and turn an application log into an error summary a tester can reproduce against.

Support tickets arrive as pasted text or a JSON blob, often missing the version, the steps, or what should have happened. Logs arrive as a wall of lines. `sqt` applies documented, rule-based heuristics and writes Markdown (or JSON for the log summary). It does not call a language model and it does not use the network, so the same file always produces the same report.

All sample data in this repository is fictional. Paperlane is a made-up invoicing web app. The tickets, request ids, and log lines were written for this project. They are not real customers, companies, or products.

## Demo

These are the commands and the output from a local run of this repo. Nothing below was typed in by hand.

A text ticket that already has steps, environment, and expected versus actual:

```bash
sqt ticket2bug samples/tickets/export-hang.txt
```

```text
# Bug: Invoice CSV export spins and never downloads

- **Source ticket:** SUP-1042
- **Severity:** High (`core_action_blocked`)
- **Rationale:** A core action (export) is paired with a failure (spins).

## Summary

Exporting last month's invoices from Billing never finishes. The button spinner stays up for more than two minutes, no file downloads, and the page shows no error. The browser console shows TypeError: Cannot read properties of undefined (reading 'rows').

## Environment

| Field | Value |
| --- | --- |
| Product | Paperlane |
| Version | 2.4.1 |
| Environment | production |
| OS | macOS 14.6 |
| Browser | Chrome 128 |
| Reported | 2026-03-14T09:12:00Z |
| Role | workspace admin |
| Frequency | every time |

## Steps to reproduce

1. Signed in as a workspace admin
2. Opened Billing, then Invoices
3. Set the date range to the previous calendar month
4. Clicked Export CSV

## Expected

A CSV file downloads within a few seconds.

## Actual

The spinner never stops. No file is saved. The console shows TypeError reading 'rows'.

## Open questions

- Is there a request id so this can be matched to application logs?

## Heuristics

- Parsed as text.
- Severity is the first matching rule in `sqt.severity`. Content rules outrank the priority written on the ticket.
- Steps come only from a steps field or a steps section. They are not inferred from the description.
```

The same morning, as an application log. Seven of the eight errors are `TimeoutError`, five of them inside one 5-minute bucket:

```bash
sqt triage samples/logs/api-morning.log
```

```text
# Log triage: api-morning.log

- **Lines:** 12 total, 12 parsed, 0 unrecognized, 0 blank
- **Window:** 2026-03-14T09:00:01Z → 2026-03-14T10:16:12Z
- **Errors:** 8
- **Warnings:** 1

## Errors by type

| Type | Count | First seen | Last seen | Repeated | Example |
| --- | --- | --- | --- | --- | --- |
| TimeoutError | 7 | 2026-03-14T09:02:14Z | 2026-03-14T10:16:12Z | yes | billing upstream timed out |
| ValidationError | 1 | 2026-03-14T09:11:02Z | 2026-03-14T09:11:02Z | no | invoice.rows missing |

## Spikes

- **TimeoutError** at 2026-03-14T09:00:00Z: 5 errors in 5 minutes (median bucket for this type is 1).

## Repeated issues

- **TimeoutError** — 7 times, from 2026-03-14T09:02:14Z to 2026-03-14T10:16:12Z.

## Notes

- Spike rule: per error type, a 5-minute UTC bucket with at least 3 events and a count at least 3× the median of that type's non-empty buckets. A type seen in only one bucket is not a spike.
- Repeated rule: the same error type on at least 3 lines.
```

A ticket that is only a cosmetic complaint. The report stays low and lists what is missing instead of inventing steps:

```bash
sqt ticket2bug samples/tickets/sparse.txt
```

```text
# Bug: Save button is the wrong color

- **Source ticket:** not provided
- **Severity:** Low (`cosmetic`)
- **Rationale:** Wording is cosmetic ("wrong color").

## Summary

The save button is the wrong color, and the wording says "Svae".

## Environment

| Field | Value |
| --- | --- |
| Product | not provided |
| Version | not provided |
| Environment | not provided |
| OS | not provided |
| Browser | not provided |
| Reported | not provided |
| Role | not provided |
| Frequency | not provided |

## Steps to reproduce

No steps were written down.

## Expected

Not stated.

## Actual

Not stated.

## Open questions

- Which product is this, and which version or build?
- What environment was this in (production or staging, OS, and browser or client)?
- What are the exact steps to reproduce, starting from a known page?
- What did the user expect to happen?
- What happened instead, including any error text on the page or in the console?
- How often does this happen: once, intermittent, or every time?
- What account role or plan was the user on?
- When did this start?
- Is there a request id so this can be matched to application logs?

## Heuristics

- Parsed as text.
- Severity is the first matching rule in `sqt.severity`. Content rules outrank the priority written on the ticket.
- Steps come only from a steps field or a steps section. They are not inferred from the description.
```

JSON Lines from a worker, printed as JSON. Four `JobFailed` lines is a repeated issue. It is not a spike: three of them share a bucket and the fourth is later, and three is not three times the median bucket.

```bash
sqt triage samples/logs/worker.jsonl --format json
```

```json
{
  "file": "worker.jsonl",
  "total_lines": 5,
  "parsed_lines": 5,
  "blank_lines": 0,
  "unrecognized_lines": [],
  "window": {
    "start": "2026-03-14T11:00:00Z",
    "end": "2026-03-14T11:30:00Z"
  },
  "error_count": 4,
  "warning_count": 0,
  "errors_by_type": [
    {
      "type": "JobFailed",
      "count": 4,
      "first_seen": "2026-03-14T11:00:05Z",
      "last_seen": "2026-03-14T11:30:00Z",
      "repeated": true,
      "example": "export job 441 failed"
    }
  ],
  "spikes": [],
  "repeated": [
    "JobFailed"
  ],
  "notes": [
    "Spike rule: per error type, a 5-minute UTC bucket with at least 3 events and a count at least 3× the median of that type's non-empty buckets. A type seen in only one bucket is not a spike.",
    "Repeated rule: the same error type on at least 3 lines.",
    "No bucket cleared the spike rule."
  ]
}
```

Bad input exits 2 and prints one line to stderr. These three were run the same way:

```bash
printf '{nope\n' > /tmp/not-a-ticket.json
sqt ticket2bug /tmp/not-a-ticket.json
```

```text
sqt: ticket looks like JSON but is not valid: Expecting property name enclosed in double quotes (line 1)
```

```bash
printf 'The button did nothing.\n' > /tmp/not-a-log.txt
sqt triage /tmp/not-a-log.txt
```

```text
sqt: no recognized log lines in 'not-a-log.txt'. Expected a timestamp plus a level (DEBUG, INFO, WARN, ERROR, CRITICAL) or JSON lines with a timestamp and a level.
```

```bash
printf '\n' > /tmp/empty.log
sqt triage /tmp/empty.log
```

```text
sqt: log file is empty
```

## Setup

Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

`pip install -e .` is enough to get the `sqt` command. The `[dev]` extra adds pytest and ruff. There are no runtime dependencies beyond the Python standard library.

## Usage

```text
sqt ticket2bug FILE [-o PATH]
sqt triage FILE [--format markdown|json] [-o PATH]
```

Omit `-o` to write to stdout. `--format` defaults to `markdown`. Exit status is 0 when a report is written and 2 when the file is missing, empty, not UTF-8, or not in a recognized shape. `python -m sqt` runs the same commands.

### Tickets

A file whose first non-space character is `{` or `[` is parsed as JSON. Anything else is plain text. Invalid JSON is an error, not a text ticket.

Text labels are a known name, a colon, and an optional value. `Description`, `Steps`, `Expected`, `Actual`, and `Notes` keep the following lines until the next known label. Other labels, such as `Ticket`, `Product`, `Version`, `Environment`, `Browser`, `OS`, `Priority`, `Reported`, `Role`, `Subject`, and `Frequency`, take the rest of their line. JSON accepts the same ideas under a few aliases (`id`, `title`, `steps_to_reproduce`, `expected_behavior`, and so on). The lists live in `src/sqt/tickets.py`.

Steps come only from a steps section or a JSON steps array. A numbered or bulleted list is split into steps. A description paragraph is not rewritten into steps. Missing product, version, environment, steps, expected result, actual result, frequency, role, time, or a request id becomes an open question.

Severity is the first matching rule in `src/sqt/severity.py`. The report names the rule and gives a one-line rationale.

| Order | Rule | Level | What matches |
| --- | --- | --- | --- |
| 1 | `data_loss` | critical | Records, files, or data described as deleted, wiped, corrupted, disappeared, or gone |
| 2 | `security` | critical | A named failure such as SQL injection, account takeover, or a leaked credential. The word "security" alone does not match |
| 3 | `total_outage` | critical | The service is down, or every user is blocked |
| 4 | `http_500_or_crash` | high | A crash, a traceback, or an HTTP 500 |
| 5 | `core_action_blocked` | high | A core action (sign in, pay, checkout, export, download, upload, save, delete) and a failure word within 160 characters |
| 6 | `cosmetic` | low | Typo, wording, alignment, or the wrong color. This stays low even if the form says urgent |
| 7 | `stated_urgent` | high | Priority is urgent, critical, high, blocker, P0, or Sev-1, and nothing above matched. A stated "critical" is reported as high |
| 8 | `stated_low` | low | Priority is low, minor, trivial, P3, or Sev-3, and nothing above matched |
| 9 | `intermittent` | medium | The text says intermittent, sometimes, or workaround |
| 10 | `default` | medium | Nothing above matched, so the report stays in the queue |

`samples/tickets/login-loop.json` is the JSON shape. On the run used for this README it was High under `http_500_or_crash`, because the actual result says `status 500`.

### Logs

`src/sqt/logs.py` accepts four line shapes:

```text
2026-03-14T09:02:14Z ERROR api error_type=TimeoutError message="billing upstream timed out"
2026-03-14 09:05:12,018 ERROR paperlane.billing: TimeoutError: upstream timed out
[2026-03-14T09:02:14Z] [ERROR] message
{"ts": "2026-03-14T11:00:05Z", "level": "ERROR", "error_type": "JobFailed", "message": "export job 441 failed"}
```

The level is the token after the timestamp, or the JSON `level` / `severity` / `lvl`. `ERROR`, `FATAL`, and `CRITICAL` are errors. `WARN` and `WARNING` are warnings. Other levels are context. Blank lines are ignored. A line that does not match is skipped and listed. If the file is non-empty and nothing matches, the command errors instead of printing an empty success.

Error type, first match wins: an `error_type` or `exception` field, then an exception class such as `TimeoutError`, then an HTTP 5xx status (`HTTP_502`), then the message with numbers and UUIDs replaced by `#`.

Timestamps without a zone are read as UTC. Spike buckets are 5 minutes, per error type. A spike needs at least 3 events in the bucket and a count at least 3× the median of that type's non-empty buckets. One bucket is not a spike, because there is no baseline. The same type on at least 3 lines anywhere in the file is a repeated issue, even when it is not a spike.

## Samples

| Path | What it is |
| --- | --- |
| `samples/tickets/export-hang.txt` | Text ticket, export hang, high |
| `samples/tickets/login-loop.json` | JSON ticket, sign-in returns status 500 |
| `samples/tickets/sparse.txt` | Cosmetic complaint with almost no fields |
| `samples/logs/api-morning.log` | Text log with a TimeoutError spike |
| `samples/logs/worker.jsonl` | JSON Lines log, repeated JobFailed, no spike |

## Tech stack

- Python 3.11+
- Standard library only at runtime (`argparse`, `json`, `re`, `datetime`, `statistics`, `pathlib`)
- pytest and ruff as development tools
- setuptools, with a `sqt` console script declared in `pyproject.toml`
- GitHub Actions (`.github/workflows/ci.yml`) on Ubuntu with Python 3.11

## Tests

```bash
ruff check .
pytest
```

The suite covers both commands, each severity rule, spike and repeat math, and the edge cases: an empty ticket, malformed JSON, a JSON value of the wrong type, an empty log, an unrecognized log, JSON lines that do not parse, a missing file, a directory, and a file that is not UTF-8. Those cases print an `sqt:` line and do not print a traceback.

CI runs `ruff check .` and `pytest` on every push and every pull request.

## Limitations / what I'd add next

The heuristics are keywords, labels, and time buckets. They are reproducible, and they are also blunt.

- A core action and a failure word only have to land within 160 characters. They do not have to be in the same sentence, so a long ticket can pair the wrong two words, or miss a pair that sits further apart.
- Steps are never inferred from a description. If the reporter writes the repro as a paragraph, the report leaves the steps blank and asks. That is deliberate, and it means a human still has to pull the steps out of prose.
- Severity is a queue hint. The rule name is there so a person can disagree with it. A stated "critical" does not become critical unless the text matches a critical rule.
- The log parser does not read syslog, multi-line stack traces, or a level that comes before the timestamp. Unmatched lines are skipped, or the whole file is rejected when none match.
- The fallback error type is a normalized message, and the match is case-sensitive. Two sentences about one bug can show up as two types.
- Spikes use one fixed 5-minute window and a 3× median. A steady high rate is "repeated" and not a spike. A slow burn across an hour will not show up as a spike. A type that appears in only one bucket never will, no matter how large that bucket is.
- Timestamps without a zone are treated as UTC.
- One ticket goes in and one report comes out. There is no dedupe across a queue, no reading of screenshots, and no filing into a tracker.

What I would add next, still without a model call: a way to pass a log path into `ticket2bug` and append the triage summary to the bug report, a configurable bucket size, and a CI check that the sample commands still match a saved copy of their output. Multi-line stack traces are worth supporting once there is a scrubbed fixture set for them. A drafted report should stay marked as needing a human pass before anyone pastes it into a tracker.

## License

MIT. Copyright (c) 2026 David Kupratis. See [LICENSE](LICENSE).
