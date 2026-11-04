from __future__ import annotations

import json
import subprocess
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from oo import claude


def test_link_can_name_another_host():
    url = urlsplit(claude.link("abc-123", "/workspaces/web", host="abc-123.claude.oo"))
    assert parse_qs(url.query)["ssh_host"] == ["abc-123.claude.oo"]


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


class Box:
    """Stands in for ssh and ssh-keygen: a box with a user, and whether its own sshd is up."""

    def __init__(self, user="gitpod", listening=True):
        self.user = user
        self.listening = listening
        self.ran = []

    def run(self, args, **kwargs):
        self.ran.append(args)
        if args[0].endswith("ssh-keygen"):
            key = Path(args[args.index("-f") + 1])
            key.write_text("private\n")
            key.with_name(key.name + ".pub").write_text("ssh-ed25519 AAAAtest oo\n")
            return subprocess.CompletedProcess(args, 0, "", "")
        if "id -un" in args[-1]:
            state = "open" if self.listening else "closed"
            return subprocess.CompletedProcess(args, 0, f"{self.user}\n{state}\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")


@pytest.fixture
def home(monkeypatch, tmp_path):
    """A fresh home folder with ssh set up to include oo's config, and a fake box."""
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "config").write_text("Include oo/config\n")
    monkeypatch.setattr(claude.shutil, "which", lambda name: f"/usr/bin/{name}")
    box = Box()
    monkeypatch.setattr(claude.subprocess, "run", box.run)
    return tmp_path, box


def test_set_up_host_writes_a_host_entry_and_authorizes_the_key(home):
    folder, box = home
    assert claude.set_up_host("abc-123", {"abc-123"}) == "abc-123.claude.oo"
    assert (folder / ".ssh" / "oo_claude").exists()
    config = (folder / ".ssh" / "oo" / "config").read_text()
    assert config.splitlines() == [
        "Host abc-123.claude.oo",
        "  HostName localhost",
        "  Port 2222",
        "  User gitpod",
        "  IdentityFile ~/.ssh/oo_claude",
        "  IdentitiesOnly yes",
        "  HostKeyAlias abc-123.claude.oo",
        "  ProxyJump abc-123.ona.environment",
        "  StrictHostKeyChecking accept-new",
        f"  # last used {date.today().isoformat()}",
    ]
    assert "StrictHostKeyChecking no" not in config
    assert "UserKnownHostsFile" not in config
    keygen = next(args for args in box.ran if args[0].endswith("ssh-keygen"))
    assert keygen[keygen.index("-t") + 1] == "ed25519"
    authorize = box.ran[-1]
    assert authorize[:4] == ["/usr/bin/ssh", "-o", "BatchMode=yes", "abc-123.ona.environment"]
    assert "AAAAtest" in authorize[-1]
    assert "chmod 600 ~/.ssh/authorized_keys" in authorize[-1]


def test_set_up_host_keeps_the_key_it_already_made(home):
    folder, box = home
    (folder / ".ssh" / "oo_claude").write_text("old\n")
    (folder / ".ssh" / "oo_claude.pub").write_text("ssh-ed25519 AAAAtest oo\n")
    claude.set_up_host("abc-123", {"abc-123"})
    assert not any(args[0].endswith("ssh-keygen") for args in box.ran)


def test_set_up_host_adds_the_include_above_the_host_blocks(home):
    folder, _ = home
    (folder / ".ssh" / "config").write_text("Host *\n  ServerAliveInterval 60\n")
    claude.set_up_host("abc-123", {"abc-123"})
    config = (folder / ".ssh" / "config").read_text()
    assert config.startswith("Include oo/config\n\nHost *\n")
    assert (
        folder / ".ssh" / "config.oo-backup"
    ).read_text() == "Host *\n  ServerAliveInterval 60\n"


def test_set_up_host_backs_up_the_ssh_config_only_once(home):
    folder, _ = home
    (folder / ".ssh" / "config").write_text("Host *\n")
    claude.set_up_host("abc-123", {"abc-123"})
    (folder / ".ssh" / "config").write_text("Host gone\n")
    claude.set_up_host("abc-123", {"abc-123"})
    assert (folder / ".ssh" / "config.oo-backup").read_text() == "Host *\n"


def test_set_up_host_creates_the_ssh_config_when_there_isnt_one(home):
    folder, _ = home
    (folder / ".ssh" / "config").unlink()
    claude.set_up_host("abc-123", {"abc-123"})
    assert (folder / ".ssh" / "config").read_text().startswith("Include oo/config\n\n")
    assert not (folder / ".ssh" / "config.oo-backup").exists()


def test_set_up_host_says_why_when_the_boxs_sshd_isnt_running(home):
    folder, box = home
    box.listening = False
    with pytest.raises(claude.ClaudeError, match="Nothing is listening on port 2222"):
        claude.set_up_host("abc-123", {"abc-123"})
    assert not (folder / ".ssh" / "oo" / "config").exists()


def test_set_up_host_forgets_environments_that_are_gone(home):
    folder, _ = home
    today = date.today().isoformat()
    (folder / ".ssh" / "oo").mkdir()
    (folder / ".ssh" / "oo" / "config").write_text(
        f"Host gone-1.claude.oo\n  Port 2222\n  # last used {today}\n\n"
        f"Host kept-2.claude.oo\n  Port 2222\n  # last used {today}\n"
    )
    claude.set_up_host("abc-123", {"abc-123", "kept-2"})
    hosts = (folder / ".ssh" / "oo" / "config").read_text().splitlines()
    assert [line for line in hosts if line.startswith("Host ")] == [
        "Host kept-2.claude.oo",
        "Host abc-123.claude.oo",
    ]


def test_set_up_host_forgets_hosts_unused_for_thirty_days(home):
    folder, _ = home
    (folder / ".ssh" / "oo").mkdir()
    old = (date.today() - timedelta(days=31)).isoformat()
    recent = (date.today() - timedelta(days=29)).isoformat()
    (folder / ".ssh" / "oo" / "config").write_text(
        f"Host old-1.claude.oo\n  Port 2222\n  # last used {old}\n\n"
        f"Host recent-2.claude.oo\n  Port 2222\n  # last used {recent}\n"
    )
    claude.set_up_host("abc-123", {"abc-123", "old-1", "recent-2"})
    hosts = (folder / ".ssh" / "oo" / "config").read_text().splitlines()
    assert [line for line in hosts if line.startswith("Host ")] == [
        "Host recent-2.claude.oo",
        "Host abc-123.claude.oo",
    ]


def test_set_up_host_refuses_a_user_name_that_could_break_the_config(home, monkeypatch):
    monkeypatch.setattr(claude.subprocess, "run", Box(user="ev;il").run)
    with pytest.raises(claude.ClaudeError, match="looks odd"):
        claude.set_up_host("abc-123", {"abc-123"})


def test_set_up_host_treats_an_include_after_a_host_block_as_missing(home):
    folder, _ = home
    (folder / ".ssh" / "config").write_text("Host *\nInclude oo/config\n")
    claude.set_up_host("abc-123", {"abc-123"})
    assert (folder / ".ssh" / "config").read_text().startswith("Include oo/config\n\nHost *\n")


def _connection(env_id: str, name: str) -> dict[str, str]:
    return {"id": f"conn-{env_id}", "name": name, "sshHost": f"{env_id}.ona.environment"}


def _write_configs(path, configs, trusted, **extra):
    path.write_text(json.dumps({"configs": configs, "trustedHosts": trusted, **extra}))


def test_forget_drops_only_stale_ona_connections(ssh_configs):
    elsewhere = {"id": "conn-box", "name": "My box", "sshHost": "devbox.example.com"}
    configs = [_connection("dead", "Old work"), _connection("live", "Login work"), elsewhere]
    trusted = ["dead.ona.environment", "live.ona.environment", "devbox.example.com"]
    _write_configs(ssh_configs, configs, trusted, future="kept")

    assert claude.forget(lambda env_id: env_id == "dead") == ["Old work"]

    data = json.loads(ssh_configs.read_text())
    assert data["configs"] == configs[1:]
    assert data["trustedHosts"] == trusted[1:]
    assert data["future"] == "kept"


def test_forget_knows_oos_own_hosts_as_well_as_onas(ssh_configs):
    via_oo = {"id": "c", "name": "Old work", "sshHost": "dead.claude.oo"}
    _write_configs(ssh_configs, [via_oo, _connection("live", "Login work")], ["dead.claude.oo"])
    assert claude.forget(lambda env_id: env_id == "dead") == ["Old work"]
    data = json.loads(ssh_configs.read_text())
    assert [c["sshHost"] for c in data["configs"]] == ["live.ona.environment"]
    assert data["trustedHosts"] == []


def test_forget_tidies_trusted_hosts_left_without_a_connection(ssh_configs):
    _write_configs(ssh_configs, [], ["dead.ona.environment"])
    assert claude.forget(lambda env_id: True) == []
    assert json.loads(ssh_configs.read_text())["trustedHosts"] == []


def test_forget_leaves_the_file_alone_when_nothing_is_stale(ssh_configs):
    _write_configs(ssh_configs, [_connection("live", "Login work")], ["live.ona.environment"])
    before = ssh_configs.read_text()
    assert claude.forget(lambda env_id: False) == []
    assert ssh_configs.read_text() == before


def test_forget_names_unnamed_connections_by_host(ssh_configs):
    _write_configs(ssh_configs, [{"id": "c", "sshHost": "dead.ona.environment"}], [])
    assert claude.forget(lambda env_id: True) == ["dead.ona.environment"]


def test_forget_does_nothing_without_the_app(ssh_configs):
    assert claude.forget(lambda env_id: True) == []
    assert not ssh_configs.exists()


def test_forget_says_when_it_cant_read_the_file(ssh_configs):
    ssh_configs.write_text("{not json")
    with pytest.raises(claude.ClaudeError, match="Couldn't read"):
        claude.forget(lambda env_id: True)


@pytest.mark.parametrize(
    ("platform", "ending"),
    [
        ("darwin", "Library/Application Support/Claude/ssh_configs.json"),
        ("linux", ".config/Claude/ssh_configs.json"),
    ],
)
def test_ssh_configs_path_follows_the_platform(monkeypatch, platform, ending):
    monkeypatch.undo()  # the real function, not conftest's stand-in
    monkeypatch.setattr(claude.sys, "platform", platform)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    assert claude.ssh_configs_path().as_posix().endswith(ending)
