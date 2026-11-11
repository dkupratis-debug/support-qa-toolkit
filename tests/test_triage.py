"""Log parsing, counts, spikes, repeats, and input errors."""

from __future__ import annotations

import json
from pathlib import Path

from paths import SAMPLES
from sqt.logs import normalize_message, parse_timestamp, triage_file


def test_api_log_counts_window_spike_and_repeat(run_sqt) -> None:
    code, out, err = run_sqt(["triage", str(SAMPLES / "logs" / "api-morning.log")])
    assert code == 0
    assert err == ""
    assert out.startswith("# Log triage: api-morning.log\n")
    assert "**Lines:** 12 total, 12 parsed, 0 unrecognized, 0 blank" in out
    assert "**Window:** 2026-03-14T09:00:01Z → 2026-03-14T10:16:12Z" in out
    assert "**Errors:** 8" in out
    assert "**Warnings:** 1" in out
    assert "| TimeoutError | 7 | 2026-03-14T09:02:14Z | 2026-03-14T10:16:12Z | yes |" in out
    assert "| ValidationError | 1 | 2026-03-14T09:11:02Z | 2026-03-14T09:11:02Z | no |" in out
    assert "billing upstream timed out" in out
    assert "**TimeoutError** at 2026-03-14T09:00:00Z: 5 errors in 5 minutes" in out
    assert "median bucket for this type is 1" in out
    assert "**TimeoutError** — 7 times, from 2026-03-14T09:02:14Z to 2026-03-14T10:16:12Z." in out
    assert "ValidationError" in out
    assert "Spike rule:" in out
    assert "Repeated rule:" in out
    # The warning is counted, and it is not an error row.
    assert "retrying billing call" not in out.split("## Errors by type")[1].split("## Spikes")[0]


def test_jsonl_sample_is_repeated_but_not_a_spike(run_sqt) -> None:
    path = SAMPLES / "logs" / "worker.jsonl"
    code, out, err = run_sqt(["triage", str(path), "--format", "json"])
    assert code == 0
    assert err == ""
    report = json.loads(out)
    assert report["file"] == "worker.jsonl"
    assert report["parsed_lines"] == 5
    assert report["error_count"] == 4
    assert report["warning_count"] == 0
    assert report["repeated"] == ["JobFailed"]
    group = report["errors_by_type"][0]
    assert group["count"] == 4
    assert group["first_seen"] == "2026-03-14T11:00:05Z"
    assert group["last_seen"] == "2026-03-14T11:30:00Z"
    # 3 events then 1. Median is 2, so 3 is not 3x the median.
    assert report["spikes"] == []
    assert "No bucket cleared the spike rule." in report["notes"]
    assert "3×" in out


def test_markdown_and_json_share_one_analysis(run_sqt, tmp_path: Path) -> None:
    log = tmp_path / "app.log"
    log.write_text(
        "\n".join(
            [
                '2026-03-14T09:00:00Z ERROR api error_type=TimeoutError message="one"',
                '2026-03-14T09:01:00Z ERROR api error_type=TimeoutError message="two"',
                '2026-03-14T09:02:00Z ERROR api error_type=TimeoutError message="three"',
                '2026-03-14T09:40:00Z ERROR api error_type=TimeoutError message="later"',
                '2026-03-14T10:20:00Z ERROR api error_type=TimeoutError message="last"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    code, markdown, err = run_sqt(["triage", str(log)])
    assert code == 0 and err == ""
    code, payload, err = run_sqt(["triage", str(log), "--format", "json"])
    assert code == 0 and err == ""
    report = json.loads(payload)
    assert report["error_count"] == 5
    assert report["spikes"][0]["bucket_start"] == "2026-03-14T09:00:00Z"
    assert report["spikes"][0]["count"] == 3
    assert "2026-03-14T09:00:00Z" in markdown
    assert "TimeoutError" in markdown


def test_single_bucket_is_repeated_but_not_a_spike(tmp_path: Path) -> None:
    lines = [
        f'2026-03-14T09:0{index}:00Z ERROR api error_type=BoomError message="n{index}"'
        for index in range(4)
    ]
    path = tmp_path / "burst.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = triage_file(path)
    assert report.error_count == 4
    assert report.groups[0].repeated is True
    assert report.spikes == []


def test_first_and_last_follow_time_not_file_order(tmp_path: Path) -> None:
    path = tmp_path / "shuffled.log"
    path.write_text(
        "\n".join(
            [
                '2026-03-14T10:00:00Z ERROR api error_type=BoomError message="late"',
                '2026-03-14T08:00:00Z ERROR api error_type=BoomError message="early"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    report = triage_file(path)
    assert report.groups[0].first_seen == "2026-03-14T08:00:00Z"
    assert report.groups[0].last_seen == "2026-03-14T10:00:00Z"
    assert report.window_start == "2026-03-14T08:00:00Z"
    assert report.window_end == "2026-03-14T10:00:00Z"


def test_python_logging_bracket_fatal_and_http_status(tmp_path: Path) -> None:
    path = tmp_path / "mixed.log"
    path.write_text(
        "\n".join(
            [
                "2026-03-14 09:05:12,018 ERROR paperlane.billing: TimeoutError: upstream timed out",
                "[2026-03-14T09:06:00Z] [WARN] queue lag",
                '[2026-03-14T09:07:00Z] FATAL worker message="gave up"',
                '2026-03-14T09:08:00Z ERROR api status=502 message="bad gateway"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    report = triage_file(path)
    kinds = {group.error_type: group for group in report.groups}
    assert set(kinds) == {"TimeoutError", "message:gave up", "HTTP_502"}
    assert report.warning_count == 1
    assert report.error_count == 3
    assert kinds["message:gave up"].example == "gave up"
    assert kinds["HTTP_502"].example == "bad gateway"
    assert kinds["TimeoutError"].example.startswith("paperlane.billing")


def test_message_fallback_collapses_ids() -> None:
    assert normalize_message("export job 441 failed") == normalize_message("export job 999 failed")
    assert normalize_message("no digits").startswith("message:")


def test_naive_timestamp_is_utc() -> None:
    parsed = parse_timestamp("2026-03-14 09:05:12,018")
    assert parsed is not None
    assert parsed.utcoffset() is not None
    assert parsed.utcoffset().total_seconds() == 0
    assert parsed.hour == 9


def test_info_only_log_is_a_successful_empty_triage(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "quiet.log"
    path.write_text('2026-03-14T09:00:00Z INFO api message="ok"\n', encoding="utf-8")
    code, out, err = run_sqt(["triage", str(path)])
    assert code == 0
    assert err == ""
    assert "**Errors:** 0" in out
    assert "No error-level lines." in out
    assert "No error-level lines in this log." in out
    assert "## Repeated issues" in out
    assert "None." in out


def test_unrecognized_lines_are_skipped(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "mixed.log"
    path.write_text(
        "\n".join(
            [
                "hello from a support note",
                '2026-03-14T09:00:00Z ERROR api error_type=BoomError message="x"',
                "",
                "still not a log",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    code, out, err = run_sqt(["triage", str(path)])
    assert code == 0
    assert err == ""
    assert "4 total, 1 parsed, 2 unrecognized, 1 blank" in out
    assert "Unrecognized lines were ignored: 1, 4." in out
    assert "**Errors:** 1" in out


def test_empty_log_is_an_error_without_a_traceback(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "empty.log"
    path.write_text("\n\n", encoding="utf-8")
    code, out, err = run_sqt(["triage", str(path)])
    assert code == 2
    assert out == ""
    assert "Traceback" not in err
    assert "log file is empty" in err


def test_unknown_prose_format(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text(
        "The customer said the button did nothing.\nThen they refreshed.\n",
        encoding="utf-8",
    )
    code, out, err = run_sqt(["triage", str(path)])
    assert code == 2
    assert out == ""
    assert "Traceback" not in err
    assert "no recognized log lines" in err
    assert "timestamp plus a level" in err


def test_invalid_json_lines(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text("{not json\n{still bad\n", encoding="utf-8")
    code, out, err = run_sqt(["triage", str(path)])
    assert code == 2
    assert out == ""
    assert "Traceback" not in err
    assert "look like JSON but are not valid" in err


def test_json_lines_missing_fields(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "thin.jsonl"
    path.write_text('{"message": "no time or level"}\n', encoding="utf-8")
    code, out, err = run_sqt(["triage", str(path)])
    assert code == 2
    assert "need a timestamp" in err
    assert "Traceback" not in err


def test_level_without_a_timestamp_is_not_a_log(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "level-only.log"
    path.write_text("ERROR something happened\nWARN something else\n", encoding="utf-8")
    code, _, err = run_sqt(["triage", str(path)])
    assert code == 2
    assert "no recognized log lines" in err
    assert "Traceback" not in err


def test_triage_writes_json_to_a_file(run_sqt, tmp_path: Path) -> None:
    dest = tmp_path / "out.json"
    code, out, err = run_sqt(
        ["triage", str(SAMPLES / "logs" / "worker.jsonl"), "--format", "json", "-o", str(dest)]
    )
    assert code == 0
    assert out == ""
    assert err == ""
    report = json.loads(dest.read_text(encoding="utf-8"))
    assert report["error_count"] == 4
