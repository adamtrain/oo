from __future__ import annotations

import pytest

from oo import ona
from oo.ona import OnaError, error_from

USAGE_THEN_ERROR = """Usage:
  ona environment list [flags]

Flags:
  -h, --help   help for list

Error: context nope does not exist

Possible resolutions:
  - use `ona config context list` to list available contexts
  - make sure the value provided with --context is correct
"""


def test_error_from_digs_out_the_error_and_resolutions():
    error = error_from("It broke.", USAGE_THEN_ERROR)
    assert str(error) == "It broke."
    assert error.detail == "context nope does not exist"
    assert error.hint == (
        "- use `ona config context list` to list available contexts\n"
        "  - make sure the value provided with --context is correct"
    )


def test_error_from_falls_back_to_the_last_thing_said():
    assert error_from("It broke.", "working…\npanic: oh no\n\n").detail == "panic: oh no"
    assert error_from("It broke.", "").detail is None


def test_error_from_suggests_logging_in():
    assert "ona login" in (error_from("x", "Error: unauthenticated").hint or "")


@pytest.fixture
def fake_ona(monkeypatch, tmp_path):
    """Point oo at a shell script standing in for ona."""

    def install(script: str) -> None:
        path = tmp_path / "ona"
        path.write_text(f"#!/bin/sh\n{script}\n")
        path.chmod(0o755)
        monkeypatch.setattr(ona, "_binary", lambda: str(path))

    return install


def test_quietly_keeps_ona_quiet(fake_ona, capfd):
    fake_ona('echo "Starting environment…"; echo "noise" >&2')
    assert ona.quietly("environment", "start", "x", failed="nope") >= 0
    assert capfd.readouterr() == ("", "")


def test_quietly_raises_what_ona_said(fake_ona):
    fake_ona(
        'echo "Deleting environment"; echo "Error: not_found: environment not found" >&2; exit 1'
    )
    with pytest.raises(OnaError, match="Ona couldn't delete it") as e:
        ona.quietly("environment", "delete", "x", failed="Ona couldn't delete it.")
    assert e.value.detail == "not_found: environment not found"
