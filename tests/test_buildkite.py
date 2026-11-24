from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime, timedelta

import pytest

from oo import buildkite, ssh
from oo.buildkite import BuildkiteError, Login

NOW = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)


@pytest.fixture
def bk(monkeypatch):
    """Fake bk: a record of what it was asked, and an answer to change as each test needs."""
    asked: list[list[str]] = []
    answer = subprocess.CompletedProcess(
        [],
        0,
        json.dumps(
            {
                "access_token": "bkua_secret",
                "expires_at": "2026-11-24T20:00:00.123456789Z",
                "organization_slug": "acme",
            }
        ),
        "",
    )

    def run(args, **kwargs):
        asked.append(args)
        return answer

    monkeypatch.setattr(shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(subprocess, "run", run)
    return asked, answer


def test_login_asks_bk_for_its_token_org_and_expiry(bk):
    asked, _ = bk
    login = buildkite.login()
    assert asked == [["/bin/bk", "auth", "token", "--json"]]
    assert (login.token, login.org) == ("bkua_secret", "acme")
    assert login.expires == datetime(2026, 11, 24, 20, 0, 0, 123456, tzinfo=UTC)


def test_login_takes_a_token_that_never_expires(bk):
    _, answer = bk
    answer.stdout = json.dumps(
        {"access_token": "bkua_secret", "expires_at": None, "organization_slug": "acme"}
    )
    login = buildkite.login()
    assert login.expires is None
    assert login.expiry() == ""


def test_login_never_shows_its_token():
    assert "bkua_secret" not in repr(Login("bkua_secret", "acme"))


def test_login_needs_bk(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(BuildkiteError, match="bk isn't installed"):
        buildkite.login()


def test_login_says_what_bk_said_when_youre_signed_out(bk):
    _, answer = bk
    answer.returncode = 1
    answer.stdout = ""
    answer.stderr = "Error: no token found; run `bk auth login` to authenticate\n"
    with pytest.raises(BuildkiteError) as raised:
        buildkite.login()
    assert raised.value.hint == "Error: no token found; run `bk auth login` to authenticate"


@pytest.mark.parametrize(
    "printed",
    ["", "not json", "[]", '{"access_token": "bkua_secret"}', '{"organization_slug": "acme"}'],
)
def test_login_wont_guess_from_an_answer_it_cant_read(bk, printed):
    _, answer = bk
    answer.stdout = printed
    with pytest.raises(BuildkiteError) as raised:
        buildkite.login()
    assert "bkua_secret" not in f"{raised.value} {raised.value.hint}"


def test_login_gives_up_on_a_bk_that_hangs(bk, monkeypatch):
    def run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 60, output="bkua_secret")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(BuildkiteError, match="too long") as raised:
        buildkite.login()
    assert raised.value.__cause__ is None


@pytest.mark.parametrize(
    ("left", "says"),
    [
        (timedelta(seconds=-1), "already expired"),
        (timedelta(seconds=20), "expires in 1m"),
        (timedelta(minutes=59), "expires in 59m"),
        (timedelta(hours=8), "expires in 8h"),
        (timedelta(hours=47), "expires in 47h"),
        (timedelta(days=30), "expires in 30d"),
    ],
)
def test_expiry_says_how_long_is_left(left, says):
    assert Login("bkua_secret", "acme", NOW + left).expiry(NOW) == says


def test_sign_in_command_reads_the_token_from_stdin_and_checks_it_stuck():
    command = buildkite.sign_in_command("acme")
    assert command.startswith("sh -c '")
    assert 'bk auth login --org acme --token "$token" >/dev/null' in command
    assert "IFS= read -r token" in command
    assert "bk auth token --org acme >/dev/null" in command


def test_sign_in_command_quotes_what_the_shell_would_read(tmp_path):
    command = buildkite.sign_in_command("a; rm -rf ~")
    assert "--org a; rm" not in command
    # Run for real where sh is the only program to find: the quoting holds, and it stops at
    # the first line for want of bk.
    (tmp_path / "sh").symlink_to("/bin/sh")
    done = subprocess.run(
        ["/bin/sh", "-c", command],
        env={"PATH": str(tmp_path)},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
    )
    assert (done.returncode, done.stderr.strip()) == (127, "bk isn't installed there.")


@pytest.fixture
def fed(monkeypatch):
    """Fake ssh.feed: a record of what would have gone to each environment."""
    sent: list[tuple[str, str, bytes]] = []
    monkeypatch.setattr(
        ssh, "feed", lambda env_id, command, data, failed: sent.append((env_id, command, data))
    )
    return sent


def test_sign_in_sends_the_token_down_stdin_and_never_in_the_command(fed):
    buildkite.sign_in("1234", Login("bkua_secret", "acme"))
    [(env_id, command, data)] = fed
    assert env_id == "1234"
    assert command == buildkite.sign_in_command("acme")
    assert "bkua_secret" not in command
    assert data == b"bkua_secret\n"


def test_sign_in_keeps_the_token_out_of_what_went_wrong(monkeypatch):
    def feed(env_id, command, data, failed):
        raise ssh.SshError(failed, hint="unexpected argument bkua_secret")

    monkeypatch.setattr(ssh, "feed", feed)
    with pytest.raises(ssh.SshError) as raised:
        buildkite.sign_in("1234", Login("bkua_secret", "acme"))
    assert str(raised.value) == "bk wouldn't sign in there."
    assert raised.value.hint == "unexpected argument <token>"
