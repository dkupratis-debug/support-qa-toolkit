"""Invocation, the console script, and the offline boundary."""

from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import entry_points

import pytest

from paths import ROOT
from sqt.cli import main


def test_help_lists_both_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "ticket2bug" in output
    assert "triage" in output


def test_missing_command_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


def test_module_help_runs_without_install() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    result = subprocess.run(
        [sys.executable, "-m", "sqt", "--help"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        cwd=ROOT,
    )
    assert result.returncode == 0
    assert "ticket2bug" in result.stdout
    assert "triage" in result.stdout


def test_console_script_points_at_cli() -> None:
    matches = [item for item in entry_points(group="console_scripts") if item.name == "sqt"]
    assert matches, "sqt console script is not installed (pip install -e .)"
    assert matches[0].value == "sqt.cli:main"


def test_package_does_not_import_a_network_client() -> None:
    banned = ("urllib", "requests", "httpx", "socket", "openai", "http.client")
    offenders: list[str] = []
    for path in (ROOT / "src").rglob("*.py"):
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            if any(name in stripped for name in banned):
                offenders.append(f"{path.relative_to(ROOT)}:{line_no}: {stripped}")
    assert offenders == []


def test_license_names_the_author() -> None:
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "Copyright (c) 2026 David Kupratis" in text
    assert "MIT License" in text


def test_pyproject_entry_point() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'sqt = "sqt.cli:main"' in text
    assert 'requires-python = ">=3.11"' in text


def test_ci_runs_ruff_and_pytest_on_push_and_pull_request() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "push:" in text
    assert "pull_request:" in text
    assert "ruff check" in text
    assert "pytest" in text
