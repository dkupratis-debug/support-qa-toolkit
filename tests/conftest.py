"""Shared paths and a small CLI runner."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from sqt.cli import main


@pytest.fixture
def run_sqt(capsys: pytest.CaptureFixture[str]) -> Callable[[list[str]], tuple[int, str, str]]:
    def _run(argv: list[str]) -> tuple[int, str, str]:
        code = main(argv)
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run
