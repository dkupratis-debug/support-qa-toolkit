# support-qa-toolkit

[![CI](https://github.com/dkupratis-debug/support-qa-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/dkupratis-debug/support-qa-toolkit/actions/workflows/ci.yml)

`sqt` turns a pasted support ticket into a structured bug report, and an application log into an error summary a tester can reproduce, using local rules so the same file always produces the same result.

## Example

The samples are fictional. Paperlane is a made-up invoicing app, and the tickets, request ids, and log lines were written for this project.

This is the stdout of `sqt ticket2bug samples/tickets/export-hang.txt` after `python -m pip install -e .`:

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

`sqt triage samples/logs/api-morning.log` prints a Markdown summary of that file: 12 lines, 8 errors, 1 warning, a repeated `TimeoutError`, and one 5-minute spike. Add `--format json` for the same analysis as JSON. `python -m sqt` runs either command.

## Features

- `sqt ticket2bug FILE [-o PATH]` reads a plain-text ticket or a JSON object and writes a Markdown bug report. A file whose first non-space character is `{` or `[` is JSON. Invalid JSON exits 2.
- `sqt triage FILE [--format markdown|json] [-o PATH]` reads a text log or JSON Lines and writes Markdown (the default) or JSON. It counts errors and warnings, groups errors by type, and flags spikes and repeats.
- Omit `-o` to write to stdout. Exit status is 0 when a report is written. It is 2 when the path is missing, a directory, empty, not UTF-8, or not a recognized shape. Those cases print one `sqt:` line on stderr.
- Severity is the first matching rule in `src/sqt/severity.py`. The report names the rule and gives a one-line rationale. Content rules outrank the priority written on the ticket.
- Steps come only from a steps field or a steps section. A description paragraph stays a description. Missing product, version, environment, steps, expected result, actual result, frequency, role, time, or a request id becomes an open question. Free text can already answer frequency, role, time, or request id, so a labeled field is not the only way those questions clear.
- Text labels and JSON field aliases live in `src/sqt/tickets.py`.
- The package does not use the network. Runtime dependencies are the Python standard library.

### Severity

`sqt ticket2bug --help` points here. First match wins.

| Order | Rule | Level | What matches |
| --- | --- | --- | --- |
| 1 | `data_loss` | critical | "data loss", or records, files, invoices, documents, or data described as deleted, wiped, erased, corrupted, disappeared, or gone |
| 2 | `security` | critical | XSS, CSRF, SQL injection, account takeover, privilege escalation, unauthorized access, a security breach, or a credential leak. A password, token, or API key described as exposed, leaked, or logged also matches. The word "security" alone does not |
| 3 | `total_outage` | critical | The site, app, service, or production is down, the text says "complete outage", or all users or customers cannot or are unable |
| 4 | `http_500_or_crash` | high | A crash, a traceback, an uncaught exception, an internal server error, or an HTTP 500 |
| 5 | `core_action_blocked` | high | A core action (sign in, pay, checkout, export, download, upload, save, delete) and a failure word within 160 characters |
| 6 | `cosmetic` | low | Typo, spelling, wording, alignment, "pixel", or the wrong color (or colour). This stays low even when the ticket says urgent |
| 7 | `stated_urgent` | high | Priority is urgent, critical, highest, blocker, high, P0, Sev-0, Sev0, Sev-1, or Sev1, and nothing above matched. A stated "critical" is reported as high |
| 8 | `stated_low` | low | Priority is low, minor, trivial, lowest, P3, P4, Sev-3, or Sev3, and nothing above matched |
| 9 | `intermittent` | medium | The text says intermittent, sometimes, occasionally, or workaround, and nothing above matched |
| 10 | `default` | medium | Nothing above matched, so the report stays in the queue |

### Logs

`src/sqt/logs.py` accepts these line shapes:

```text
2026-03-14T09:02:14Z ERROR api error_type=TimeoutError message="billing upstream timed out"
2026-03-14 09:05:12,018 ERROR paperlane.billing: TimeoutError: upstream timed out
[2026-03-14T09:02:14Z] [ERROR] message
{"ts": "2026-03-14T11:00:05Z", "level": "ERROR", "error_type": "JobFailed", "message": "export job 441 failed"}
```

The level is the token after the timestamp, or the JSON `level`, `severity`, or `lvl`. `ERROR`, `FATAL`, and `CRITICAL` are errors. `WARN` and `WARNING` are warnings. Other levels are counted as parsed context. Blank lines are ignored. A line that does not match is skipped and listed. If the file is non-empty and nothing matches, the command exits 2.

Error type, first match wins: an `error_type` or `exception` field, then an exception class such as `TimeoutError`, then an HTTP 5xx status (`HTTP_502`), then the message with numbers and UUIDs replaced by `#`.

Timestamps without a zone are read as UTC. Spike buckets are 5 minutes, per error type. A spike needs at least 3 events in the bucket and a count at least 3× the median of that type's non-empty buckets. A type seen in only one bucket is not a spike. The same type on at least 3 lines anywhere in the file is a repeated issue.

The parser does not read syslog or join multi-line stack traces. A core action and a failure word only have to land within 160 characters, so a long ticket can pair the wrong two words. One ticket or one log goes in, and one report comes out.

## Setup

Python 3.11 or newer. On Debian and Ubuntu, `python3 -m venv` needs the `python3-venv` package. If the command says ensurepip is unavailable, install the package named in that message. With Python 3.12 on Ubuntu 24.04, that package is `python3.12-venv`.

From the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

`python -m pip install -e .` is enough to get the `sqt` command. The `[dev]` extra adds pytest and ruff. There are no runtime dependencies beyond the Python standard library.

## Tests

With the dev extra installed, from the repository root:

```bash
ruff check .
pytest
```

The suite covers both commands, each severity rule, spike and repeat math, and bad input: an empty ticket, malformed JSON, a JSON value of the wrong type, an empty log, an unrecognized log, JSON lines that do not parse, a missing file, a directory, and a file that is not UTF-8.

## Tech stack

- Python 3.11+ (`requires-python` in `pyproject.toml`). CI uses 3.11. The setup commands and the example above were run with Python 3.12.3
- Standard library only at runtime (`argparse`, `json`, `re`, `datetime`, `statistics`, `pathlib`)
- pytest and ruff as the `dev` extra
- setuptools, with the `sqt` console script pointed at `sqt.cli:main`
- GitHub Actions in `.github/workflows/ci.yml`: on every push and pull request, Ubuntu, Python 3.11, `ruff check .`, then `pytest -q`

## Project layout

```text
.github/workflows/ci.yml          GitHub Actions workflow named CI
LICENSE                           MIT
pyproject.toml                    package metadata and the sqt script
README.md
samples/logs/api-morning.log      text log, TimeoutError spike
samples/logs/worker.jsonl         JSON Lines, repeated JobFailed, no spike
samples/tickets/export-hang.txt   text ticket used in the example above
samples/tickets/login-loop.json   JSON ticket, High under http_500_or_crash
samples/tickets/sparse.txt        cosmetic complaint, Low, mostly open questions
src/sqt/__init__.py               package version
src/sqt/__main__.py               python -m sqt
src/sqt/cli.py                    commands, output files, exit codes
src/sqt/errors.py                 sqt: errors
src/sqt/logs.py                   log parsing, spikes, repeats
src/sqt/render.py                 Markdown and JSON
src/sqt/severity.py               ordered severity rules
src/sqt/tickets.py                text and JSON ticket parsing
tests/                            pytest modules for the CLI, severity, both commands, and sample data
```

`samples/tickets/login-loop.json` came out High under `http_500_or_crash` because the actual result says `status 500`. `samples/tickets/sparse.txt` came out Low under `cosmetic`. `samples/logs/worker.jsonl` with `--format json` lists `JobFailed` as repeated and leaves `spikes` empty.

## License

MIT. Copyright (c) 2026 David Kupratis. See [LICENSE](LICENSE).
