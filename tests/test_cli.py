from __future__ import annotations

import pytest
from conftest import raw_env
from typer.testing import CliRunner

from oo import cli, github, ona
from oo.envs import Env
from oo.github import BranchStatus, GitHubError, PullRequest
from oo.projects import EnvClass, Project

RAW = [
    raw_env("11111111-aaaa", "sam/feat-10", "running", created="2026-09-20T00:00:00Z"),
    raw_env("22222222-bbbb", "sam/feat-10-2", changed=["src/a.py"]),
    raw_env("33333333-cccc", "sam/docs"),
]
FRANKFURT = EnvClass(id="c-fr", name="m7i.xlarge", runner="Frankfurt")
TOKYO = EnvClass(id="c-tk", name="m7i.xlarge", runner="Tokyo")
WIDGETS = Project(id="p-1", name="Widgets", class_ids=("c-tk", "c-fr"))


class Called(Exception):
    """Stands in for exec, which would replace the test process."""


@pytest.fixture
def envs() -> list[Env]:
    return [Env.from_json(r) for r in RAW]


@pytest.fixture
def calls(monkeypatch, envs):
    """Fake ona and GitHub: canned answers, and a record of what we asked ona to do."""
    record: list[tuple[str, ...]] = []

    def replace_with(*args):
        record.append(args)
        raise Called

    def run(*args):
        record.append(args)
        if args[:2] == ("environment", "create"):
            envs.append(Env.from_json(raw_env("99999999-new", "main", "running")))
        return 0

    monkeypatch.setattr(ona, "list_envs", lambda timeout=None: list(envs))
    monkeypatch.setattr(ona, "list_projects", lambda: [WIDGETS])
    monkeypatch.setattr(ona, "list_classes", lambda: [TOKYO, FRANKFURT])
    monkeypatch.setattr(ona, "replace_with", replace_with)
    monkeypatch.setattr(ona, "run", run)
    monkeypatch.setattr(github, "lookup", lambda envs: {})
    monkeypatch.setenv("OO_BRANCH_PREFIX", "sam")
    return record


def oo(*args: str, input: str | None = None):
    return CliRunner().invoke(cli.app, list(args), input=input)


def test_lists_by_default(calls):
    result = oo()
    assert result.exit_code == 0
    assert "feat-10-2" in result.output
    assert "1 uncommitted" in result.output
    assert calls == []


def test_lists_pull_requests_and_unpushed_work(calls, monkeypatch):
    pr = PullRequest(number=42, state="merged", url="https://github.com/acme/widgets/pull/42")
    statuses = {
        "11111111-aaaa": BranchStatus(pr=pr, pushed=True),
        "22222222-bbbb": BranchStatus(pr=None, pushed=False),
    }
    monkeypatch.setattr(github, "lookup", lambda envs: statuses)
    result = oo()
    assert "#42 merged" in result.output
    assert "1 uncommitted, unpushed" in result.output


def test_lists_anyway_when_github_fails(calls, monkeypatch):
    def broken(envs):
        raise GitHubError("Bad credentials")

    monkeypatch.setattr(github, "lookup", broken)
    result = oo()
    assert result.exit_code == 0
    assert "Bad credentials" in result.output
    assert "feat-10-2" in result.output


def test_connects_by_short_branch(calls):
    result = oo("c", "feat-10")
    assert isinstance(result.exception, Called)
    assert calls == [("environment", "ssh", "11111111-aaaa")]


def test_passes_a_remote_command_through(calls):
    oo("c", "docs", "--", "git", "status", "-sb")
    assert calls == [("environment", "ssh", "33333333-cccc", "--", "git", "status", "-sb")]


def test_connect_with_no_branch_picks_the_only_running_one(calls):
    oo("c")
    assert calls == [("environment", "ssh", "11111111-aaaa")]


def test_picks_from_a_list_when_its_not_obvious(calls, monkeypatch, envs):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    envs.pop(0)  # nothing running now
    result = oo("c", input="9\n2\n")
    assert "Which one?" in result.output
    assert calls == [("environment", "ssh", "33333333-cccc")]


def test_ambiguous_branch_is_an_error(calls):
    result = oo("c", "feat")
    assert result.exit_code == 1
    assert "matches 2 environments" in result.output
    assert calls == []


def test_open_uses_the_editor_from_the_environment(calls, monkeypatch):
    monkeypatch.setenv("OO_EDITOR", "cursor")
    oo("open", "docs")
    assert calls == [("environment", "open", "33333333-cccc", "--start", "--editor", "cursor")]


def test_id_prints_just_the_id(calls):
    result = oo("id", "docs")
    assert result.stdout == "33333333-cccc\n"


def test_start_skips_running_ones(calls):
    oo("start", "feat-10", "docs")
    assert calls == [("environment", "start", "33333333-cccc", "--dont-wait")]


def test_stop_with_no_branch_stops_the_only_running_one(calls):
    oo("stop")
    assert calls == [("environment", "stop", "11111111-aaaa", "--dont-wait")]


def test_stop_skips_stopped_ones(calls):
    result = oo("stop", "docs")
    assert "already stopped" in result.output
    assert calls == []


def test_stop_with_several_running_asks_for_names(calls, envs):
    envs[:] = [Env.from_json(raw_env(f"{i}{i}", f"sam/b{i}", "running")) for i in range(2)]
    assert oo("stop").exit_code == 1
    oo("stop", "--all")
    assert calls == [("environment", "stop", "00", "11", "--dont-wait")]


def test_rm_deletes_without_asking(calls):
    result = oo("rm", "feat-10-2", "docs")
    assert result.exit_code == 0
    assert calls == [("environment", "delete", "22222222-bbbb", "33333333-cccc", "--dont-wait")]


TWINS = [
    raw_env("01a0-0000-aaaaaa", "sam/twin", "running", created="2026-09-28T10:00:00Z"),
    raw_env("01a0-0000-bbbbbb", "sam/twin", created="2026-09-29T10:00:00Z"),
]


def test_twins_without_a_terminal_are_an_error_listing_them(calls, envs):
    envs[:] = [Env.from_json(r) for r in TWINS]
    result = oo("rm", "twin")
    assert result.exit_code == 1
    assert "Pass one of the IDs above instead" in result.output
    assert "Created" in result.output
    assert "aaaaaa" in result.output and "bbbbbb" in result.output
    assert calls == []


@pytest.mark.parametrize("command", ["c", "rm", "stop"])
def test_twins_get_asked_about(calls, monkeypatch, envs, command):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    envs[:] = [Env.from_json(r) for r in TWINS]
    result = oo(command, "twin", input="1\n")
    assert '"twin" matches 2 environments' in result.output
    assert "Which one?" in result.output
    assert calls[0][2] == "01a0-0000-aaaaaa"


def test_the_end_of_an_id_is_enough(calls, envs):
    envs[:] = [Env.from_json(r) for r in TWINS]
    oo("c", "bbbbbb")
    assert calls == [("environment", "ssh", "01a0-0000-bbbbbb")]


def test_vague_names_get_asked_about_too(calls, monkeypatch):
    monkeypatch.setattr(cli, "_interactive", lambda: True)
    oo("c", "feat", input="2\n")
    assert calls == [("environment", "ssh", "22222222-bbbb")]


def test_new_reuses_your_latest_project_and_class_then_connects(calls):
    result = oo("new")
    assert "from Widgets" in result.output
    assert "m7i.xlarge in Frankfurt" in result.output
    assert calls == [
        ("environment", "create", "p-1", "--class-id", "c-fr"),
        ("environment", "ssh", "99999999-new"),
    ]


def test_new_takes_project_and_class_from_the_environment(calls, monkeypatch):
    monkeypatch.setenv("OO_PROJECT", "widgets")
    monkeypatch.setenv("OO_CLASS", "tokyo")
    oo("new")
    assert calls[0] == ("environment", "create", "p-1", "--class-id", "c-tk")


def test_new_complains_about_unknown_classes(calls):
    result = oo("new", "--class", "mars")
    assert result.exit_code == 1
    assert "m7i.xlarge in Tokyo, m7i.xlarge in Frankfurt" in result.output
    assert calls == []
