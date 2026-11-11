"""Each severity rule, in the order the module documents."""

from __future__ import annotations

from sqt.severity import classify
from sqt.tickets import parse_ticket


def _level(text: str) -> tuple[str, str, str]:
    result = classify(parse_ticket(text))
    return result.level, result.rule, result.rationale


def test_data_loss_is_critical_even_when_priority_says_low() -> None:
    level, rule, rationale = _level(
        "Priority: low\nSubject: Records gone\n\nDescription:\nAll invoices disappeared."
    )
    assert (level, rule) == ("critical", "data_loss")
    assert "disappeared" in rationale


def test_deleted_records_phrased_the_other_way_is_still_data_loss() -> None:
    level, rule, _ = _level("Subject: Problem\n\nDescription:\nWe deleted customer records.")
    assert (level, rule) == ("critical", "data_loss")


def test_security_failure_is_critical() -> None:
    level, rule, rationale = _level(
        "Subject: Search box\n\nDescription:\nThe search box has a SQL injection."
    )
    assert (level, rule) == ("critical", "security")
    assert "SQL injection" in rationale


def test_bare_word_security_is_not_enough() -> None:
    level, rule, _ = _level(
        "Subject: Question\n\nDescription:\nWhere is the security setting for the avatar?"
    )
    assert rule != "security"
    assert level == "medium"


def test_total_outage_is_critical() -> None:
    level, rule, _ = _level(
        "Subject: Down\n\nDescription:\nProduction is down for every workspace."
    )
    assert (level, rule) == ("critical", "total_outage")


def test_http_500_is_high() -> None:
    level, rule, rationale = _level(
        "Subject: Save failed\n\nDescription:\nPOST /notes returned status 500."
    )
    assert (level, rule) == ("high", "http_500_or_crash")
    assert "500" in rationale


def test_core_action_within_the_window_is_high() -> None:
    level, rule, rationale = _level(
        "Subject: CSV export hangs\n\nDescription:\nClicked export and the page hangs."
    )
    assert (level, rule) == ("high", "core_action_blocked")
    assert "export" in rationale
    assert "hangs" in rationale


def test_core_action_and_failure_far_apart_do_not_pair() -> None:
    padding = "word " * 80
    level, rule, _ = _level(f"Subject: Export\n\nDescription:\n{padding}times out")
    assert (level, rule) == ("medium", "default")


def test_cosmetic_stays_low_when_the_form_says_urgent() -> None:
    level, rule, rationale = _level(
        "Priority: urgent\nSubject: Typo\n\nDescription:\nThe wording on the button is wrong."
    )
    assert (level, rule) == ("low", "cosmetic")
    assert "urgent" in rationale
    assert "cosmetic" in rationale


def test_stated_critical_without_a_content_rule_is_high_not_critical() -> None:
    level, rule, rationale = _level(
        "Priority: critical\nSubject: Something odd\n\n"
        "Description:\nThe inbox feels different today."
    )
    assert (level, rule) == ("high", "stated_urgent")
    assert "rather than critical" in rationale


def test_stated_low_is_low() -> None:
    level, rule, _ = _level(
        "Priority: low\nSubject: Slow search\n\nDescription:\nSearch feels slower."
    )
    assert (level, rule) == ("low", "stated_low")


def test_intermittent_without_a_stronger_signal_is_medium() -> None:
    level, rule, _ = _level(
        "Subject: Avatar\n\nDescription:\nSometimes the avatar fails to load. "
        "There is a workaround."
    )
    assert (level, rule) == ("medium", "intermittent")


def test_no_signal_defaults_to_medium() -> None:
    level, rule, rationale = _level(
        "Subject: Search\n\nDescription:\nSearching invoices feels slower than last week."
    )
    assert (level, rule) == ("medium", "default")
    assert "medium" in rationale
