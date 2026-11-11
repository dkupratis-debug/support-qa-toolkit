"""ticket2bug parsing, the report shape, and input errors."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from paths import SAMPLES
from sqt.errors import SqtError
from sqt.tickets import load_ticket, open_questions, parse_ticket


def test_text_sample_becomes_a_structured_report(run_sqt) -> None:
    code, out, err = run_sqt(["ticket2bug", str(SAMPLES / "tickets" / "export-hang.txt")])
    assert code == 0
    assert err == ""
    assert out.startswith("# Bug: Invoice CSV export spins and never downloads\n")
    assert "- **Source ticket:** SUP-1042" in out
    assert "- **Severity:** High (`core_action_blocked`)" in out
    assert "## Summary" in out
    assert "## Environment" in out
    assert "| Product | Paperlane |" in out
    assert "| Version | 2.4.1 |" in out
    assert "| Environment | production |" in out
    assert "| OS | macOS 14.6 |" in out
    assert "| Browser | Chrome 128 |" in out
    assert "## Steps to reproduce" in out
    assert "1. Signed in as a workspace admin" in out
    assert "4. Clicked Export CSV" in out
    assert "## Expected" in out
    assert "A CSV file downloads within a few seconds." in out
    assert "## Actual" in out
    assert "The spinner never stops." in out
    assert "Is there a request id so this can be matched to application logs?" in out
    assert "What are the exact steps" not in out


def test_json_sample_uses_the_status_500_rule(run_sqt) -> None:
    code, out, err = run_sqt(["ticket2bug", str(SAMPLES / "tickets" / "login-loop.json")])
    assert code == 0
    assert err == ""
    assert "# Bug: Sign-in returns to the login page" in out
    assert "- **Source ticket:** SUP-1108" in out
    assert "`http_500_or_crash`" in out
    assert "- **Severity:** High" in out
    assert "1. Open the Paperlane sign-in page" in out
    assert "3. Submit the form" in out
    assert "status 500" in out
    assert "Parsed as json." in out


def test_sparse_ticket_lists_what_is_missing(run_sqt) -> None:
    code, out, err = run_sqt(["ticket2bug", str(SAMPLES / "tickets" / "sparse.txt")])
    assert code == 0
    assert err == ""
    assert "`cosmetic`" in out
    assert "- **Severity:** Low" in out
    assert "No steps were written down." in out
    assert "Not stated." in out
    assert "Which product is this, and which version or build?" in out
    assert "What environment was this in" in out
    assert "What are the exact steps to reproduce" in out
    assert "What did the user expect to happen?" in out
    assert "What happened instead" in out
    assert "How often does this happen" in out
    assert "What account role or plan was the user on?" in out
    assert "When did this start?" in out
    assert "Is there a request id" in out


def test_signals_in_prose_answer_questions_without_labels() -> None:
    ticket = parse_ticket(
        "Subject: Notes fail to open\n\n"
        "Description:\n"
        "A member said this happens every time. It started 2026-04-02T08:00:00Z. "
        "request_id=req-77.\n\n"
        "Steps:\n"
        "1. Open a note\n"
    )
    questions = open_questions(ticket)
    assert not any("how often" in question.lower() for question in questions)
    assert not any("role" in question.lower() for question in questions)
    assert not any("when did this start" in question.lower() for question in questions)
    assert not any("request id" in question.lower() for question in questions)


def test_steps_are_not_invented_from_the_description() -> None:
    ticket = parse_ticket(
        "Subject: Export is odd\n\nDescription:\nI clicked export and then I waited.\n"
    )
    assert ticket.steps == []
    assert any("steps" in question.lower() for question in open_questions(ticket))


def test_unlabeled_prose_uses_the_first_line_as_the_subject() -> None:
    ticket = parse_ticket("The save icon is one pixel to the left.\n")
    assert ticket.subject == "The save icon is one pixel to the left."
    assert ticket.source_format == "text"
    assert classify_rule(ticket) == "cosmetic"


def test_empty_object_is_a_report_full_of_questions(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "empty-object.json"
    path.write_text("{}\n", encoding="utf-8")
    code, out, err = run_sqt(["ticket2bug", str(path)])
    assert code == 0
    assert err == ""
    assert "# Bug: Untitled report" in out
    assert "No description was provided." in out
    assert "`default`" in out
    assert "Which product is this" in out


def test_json_ticket_with_a_bom_is_a_report(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "bom.json"
    path.write_bytes(b'\xef\xbb\xbf{"id": "SUP-9", "subject": "BOM ticket"}\n')
    code, out, err = run_sqt(["ticket2bug", str(path)])
    assert code == 0
    assert err == ""
    assert "Traceback" not in err
    assert "# Bug: BOM ticket" in out
    assert "- **Source ticket:** SUP-9" in out


def test_bom_only_ticket_is_empty(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "only-bom.txt"
    path.write_bytes(b"\xef\xbb\xbf\n")
    code, out, err = run_sqt(["ticket2bug", str(path)])
    assert code == 2
    assert out == ""
    assert "ticket file is empty" in err
    assert "Traceback" not in err


def test_empty_ticket_is_an_error_without_a_traceback(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "blank.txt"
    path.write_text("  \n\n", encoding="utf-8")
    code, out, err = run_sqt(["ticket2bug", str(path)])
    assert code == 2
    assert out == ""
    assert "Traceback" not in err
    assert "ticket file is empty" in err


def test_malformed_json_is_an_error_without_a_traceback(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{nope\n", encoding="utf-8")
    code, out, err = run_sqt(["ticket2bug", str(path)])
    assert code == 2
    assert out == ""
    assert "Traceback" not in err
    assert "looks like JSON but is not valid" in err


def test_json_list_is_rejected(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "list.json"
    path.write_text("[]\n", encoding="utf-8")
    code, out, err = run_sqt(["ticket2bug", str(path)])
    assert code == 2
    assert out == ""
    assert "must be an object, got a list" in err
    assert "Traceback" not in err


def test_json_steps_must_be_strings(tmp_path: Path) -> None:
    path = tmp_path / "bad-steps.json"
    path.write_text(json.dumps({"subject": "X", "steps": ["ok", 2]}), encoding="utf-8")
    with pytest.raises(SqtError, match="item 2 must be a string"):
        load_ticket(path)


def test_missing_file_and_directory(run_sqt, tmp_path: Path) -> None:
    code, out, err = run_sqt(["ticket2bug", str(tmp_path / "missing.txt")])
    assert code == 2
    assert out == ""
    assert "file not found" in err
    assert "Traceback" not in err

    code, out, err = run_sqt(["ticket2bug", str(tmp_path)])
    assert code == 2
    assert "path is a directory" in err
    assert "Traceback" not in err


def test_invalid_utf8(run_sqt, tmp_path: Path) -> None:
    path = tmp_path / "binary.txt"
    path.write_bytes(b"\xff\xfe not text")
    code, out, err = run_sqt(["ticket2bug", str(path)])
    assert code == 2
    assert out == ""
    assert "not valid UTF-8" in err
    assert "Traceback" not in err


def test_output_file(run_sqt, tmp_path: Path) -> None:
    dest = tmp_path / "bug.md"
    code, out, err = run_sqt(
        ["ticket2bug", str(SAMPLES / "tickets" / "sparse.txt"), "-o", str(dest)]
    )
    assert code == 0
    assert out == ""
    assert err == ""
    written = dest.read_text(encoding="utf-8")
    assert written.startswith("# Bug: Save button is the wrong color")
    assert written.endswith("\n")


def test_output_directory_missing(run_sqt, tmp_path: Path) -> None:
    dest = tmp_path / "missing" / "bug.md"
    code, out, err = run_sqt(
        ["ticket2bug", str(SAMPLES / "tickets" / "sparse.txt"), "-o", str(dest)]
    )
    assert code == 2
    assert out == ""
    assert "could not write" in err
    assert "Traceback" not in err


def classify_rule(ticket) -> str:
    from sqt.severity import classify

    return classify(ticket).rule
