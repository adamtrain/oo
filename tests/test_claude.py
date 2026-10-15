from __future__ import annotations

import subprocess
from urllib.parse import parse_qs, urlsplit

import pytest

from oo import claude


def test_link_starts_in_the_repo():
    url = urlsplit(claude.link("abc-123", "/workspaces/web"))
    assert (url.scheme, url.netloc, url.path) == ("claude", "code", "/new")
    assert parse_qs(url.query) == {
        "ssh_host": ["abc-123.ona.environment"],
        "ssh_folder": ["/workspaces/web"],
    }


@pytest.mark.parametrize("checkout", ["", "workspaces/web"])
def test_link_leaves_off_folders_the_app_wont_take(checkout):
    assert claude.link("abc-123", checkout) == "claude://code/new?ssh_host=abc-123.ona.environment"


def _fake_platform(monkeypatch, platform, returncode=0):
    monkeypatch.setattr(claude.sys, "platform", platform)
    monkeypatch.setattr(claude.shutil, "which", lambda name: f"/usr/bin/{name}")
    ran = []

    def run(args, **kwargs):
        ran.append(args)
        return subprocess.CompletedProcess(args, returncode, "", "")

    monkeypatch.setattr(claude.subprocess, "run", run)
    return ran


def test_check_installed_asks_macos_for_the_app(monkeypatch):
    ran = _fake_platform(monkeypatch, "darwin")
    claude.check_installed()
    assert ran[0][0] == "/usr/bin/osascript"
    assert claude.BUNDLE_ID in ran[0][-1]


def test_check_installed_fails_when_macos_cant_find_the_app(monkeypatch):
    _fake_platform(monkeypatch, "darwin", returncode=1)
    with pytest.raises(claude.ClaudeError, match="isn't installed"):
        claude.check_installed()


def test_check_installed_lets_other_platforms_through(monkeypatch):
    ran = _fake_platform(monkeypatch, "linux", returncode=1)
    claude.check_installed()
    assert ran == []


def test_open_link_fails_nicely_when_nothing_opens_it(monkeypatch):
    _fake_platform(monkeypatch, "linux", returncode=3)
    with pytest.raises(claude.ClaudeError, match="Couldn't open"):
        claude.open_link("claude://code/new")


def test_open_link_fails_nicely_on_windows_without_the_app(monkeypatch):
    monkeypatch.setattr(claude.sys, "platform", "win32")

    def startfile(url):
        raise OSError("No application is associated with the specified file")

    monkeypatch.setattr(claude.os, "startfile", startfile, raising=False)
    with pytest.raises(claude.ClaudeError, match="Couldn't open"):
        claude.open_link("claude://code/new")
