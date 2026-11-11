"""Sample data stays generic. These checks are a tripwire, not a legal review."""

from __future__ import annotations

import re
from pathlib import Path

from paths import ROOT

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_DOC_PREFIXES = ("192.0.2.", "198.51.100.", "203.0.113.")
# Terms are split so this file does not itself contain the banned phrases.
_BANNED = (
    re.compile("sound" + "traxx", re.IGNORECASE),
    re.compile("model " + "train", re.IGNORECASE),
    re.compile(r"\b" + "dc" + r"c\b", re.IGNORECASE),
)

_SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
}


def _tracked_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        files.append(path)
    return files


def test_samples_and_source_have_no_real_identifiers() -> None:
    problems: list[str] = []
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(ROOT)
        for pattern in _BANNED:
            if pattern.search(text):
                problems.append(f"{relative} matched {pattern.pattern}")
        if _EMAIL.search(text):
            problems.append(f"{relative} contains an email address")
        for ip in _IP.findall(text):
            if not ip.startswith(_DOC_PREFIXES):
                problems.append(f"{relative} contains non-documentation IP {ip}")
    assert problems == []
