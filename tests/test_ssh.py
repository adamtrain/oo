from __future__ import annotations

import subprocess

import pytest

from oo import ssh
from oo.ssh import Spot, SshError


@pytest.mark.parametrize(
    ("arg", "spot"),
    [
        ("notes.md", Spot("notes.md")),
        ("login:", Spot("", remote=True, branch="login")),
        ("adam/login-fix:src/a.py", Spot("src/a.py", remote=True, branch="adam/login-fix")),
        (":out.csv", Spot("out.csv", remote=True)),
        ("login:a:b", Spot("a:b", remote=True, branch="login")),
        ("./odd:name", Spot("./odd:name")),
        ("/tmp/odd:name", Spot("/tmp/odd:name")),
        ("~/odd:name", Spot("~/odd:name")),
    ],
)
def test_parse_tells_local_from_remote(arg, spot):
    assert Spot.parse(arg) == spot


@pytest.mark.parametrize(
    ("path", "resolved"),
    [
        ("", "/workspaces/web"),
        ("src/a.py", "/workspaces/web/src/a.py"),
        ("/tmp/x", "/tmp/x"),
        ("~/x", "~/x"),
    ],
)
def test_relative_paths_start_in_the_repo(path, resolved):
    assert Spot(path, remote=True).resolved("/workspaces/web") == resolved


def test_relative_paths_start_at_home_when_the_repo_is_unknown():
    assert Spot("src/a.py", remote=True).resolved("") == "src/a.py"


@pytest.fixture
def ssh_runs(monkeypatch):
    """Fake ssh: a record of each command it was given, along with what came down its stdin."""
    runs: list[tuple[list[str], bytes]] = []
    answer = subprocess.CompletedProcess([], 0, b"", b"")

    def run(args, stdin, **kwargs):
        runs.append((args, stdin.read()))
        return answer

    monkeypatch.setattr(ssh, "binary", lambda name: name)
    monkeypatch.setattr(subprocess, "run", run)
    return runs, answer


def test_put_in_home_makes_the_folder_and_keeps_the_file_private(ssh_runs, tmp_path):
    runs, _ = ssh_runs
    source = tmp_path / "hosts.yml"
    source.write_text("github.com:\n")
    ssh.put_in_home("1234", source, ".config/gh/hosts.yml")
    [(args, sent)] = runs
    assert args[:4] == ["ssh", "-o", "BatchMode=yes", "1234.ona.environment"]
    assert args[4] == (
        'mkdir -p "$HOME"/.config/gh && umask 077 && cat > "$HOME"/.config/gh/hosts.yml'
        ' && chmod 600 "$HOME"/.config/gh/hosts.yml'
    )
    assert sent == b"github.com:\n"


def test_put_in_home_quotes_awkward_paths(ssh_runs, tmp_path):
    runs, _ = ssh_runs
    source = tmp_path / "notes"
    source.write_text("")
    ssh.put_in_home("1234", source, "my notes/to do")
    assert """cat > "$HOME"/'my notes/to do'""" in runs[0][0][4]


def test_put_in_home_says_what_ssh_said_when_it_fails(ssh_runs, tmp_path):
    _, answer = ssh_runs
    answer.returncode, answer.stderr = 255, b"Permission denied (publickey).\n"
    source = tmp_path / "hosts.yml"
    source.write_text("")
    with pytest.raises(SshError) as raised:
        ssh.put_in_home("1234", source, ".config/gh/hosts.yml")
    assert raised.value.hint == "Permission denied (publickey)."


def test_put_in_home_says_when_it_cant_read_the_file(ssh_runs, tmp_path):
    with pytest.raises(SshError, match="Couldn't read"):
        ssh.put_in_home("1234", tmp_path / "missing.yml", ".config/gh/hosts.yml")
