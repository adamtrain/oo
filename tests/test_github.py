from __future__ import annotations

import json
import subprocess

import pytest
from conftest import raw_env

from oo import github
from oo.envs import Env
from oo.github import GitHubError, PullRequest


@pytest.mark.parametrize(
    ("node", "state"),
    [
        ({"state": "OPEN", "isDraft": True}, "draft"),
        ({"state": "OPEN", "reviewDecision": "REVIEW_REQUIRED"}, "open"),
        ({"state": "OPEN", "reviewDecision": "APPROVED"}, "approved"),
        ({"state": "OPEN", "reviewDecision": "CHANGES_REQUESTED"}, "changes requested"),
        ({"state": "MERGED", "reviewDecision": "APPROVED"}, "merged"),
        ({"state": "CLOSED"}, "closed"),
    ],
)
def test_pull_request_state(node, state):
    assert PullRequest.from_json({"number": 1, **node}).state == state


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/acme/widgets.git", ("acme", "widgets")),
        ("https://github.com/acme/widgets", ("acme", "widgets")),
        ("git@github.com:acme/widgets.git", ("acme", "widgets")),
        ("https://gitlab.com/acme/widgets.git", None),
    ],
)
def test_repo_from_clone_url(url, expected):
    assert github._repo(url) == expected


class FakeGh:
    """Records each call and answers with whatever `answer` holds."""

    def __init__(self):
        self.calls: list[list[str]] = []
        self.answer: dict = {}

    def run(self, args, **kwargs):
        self.calls.append(args)
        return subprocess.CompletedProcess(args, 0, json.dumps(self.answer), "")


@pytest.fixture
def gh(monkeypatch):
    fake = FakeGh()
    monkeypatch.setattr(github.shutil, "which", lambda name: "/usr/bin/gh")
    monkeypatch.setattr(github.subprocess, "run", fake.run)
    return fake


def test_one_query_per_repo_with_prs_and_push_status(gh):
    envs = [
        Env.from_json(raw_env("e0", "sam/a", commit="a" * 40)),
        Env.from_json(raw_env("e1", "sam/b", commit="b" * 40)),
        Env.from_json(raw_env("e2", "sam/c", commit="not-a-sha")),
    ]
    gh.answer = {
        "data": {
            "repository": {
                "p0": {"nodes": [{"number": 7, "state": "MERGED", "url": "u"}]},
                "c0": {"oid": "a" * 40},
                "p1": {"nodes": []},
                "c1": None,
                "p2": {"nodes": []},
            }
        }
    }
    statuses = github.lookup(envs)
    assert len(gh.calls) == 1
    assert "-f" in gh.calls[0] and "b1=sam/b" in gh.calls[0]
    assert statuses["e0"].pr == PullRequest(number=7, state="merged", url="u")
    assert statuses["e0"].pushed is True
    assert (statuses["e1"].pr, statuses["e1"].pushed) == (None, False)
    assert statuses["e2"].pushed is None


def test_graphql_errors_become_github_errors(gh):
    gh.answer = {"data": {"repository": None}, "errors": [{"message": "Could not resolve"}]}
    with pytest.raises(GitHubError, match="Could not resolve"):
        github.lookup([Env.from_json(raw_env("e0", "sam/a"))])


def test_no_gh_means_no_lookup(monkeypatch):
    monkeypatch.setattr(github.shutil, "which", lambda name: None)
    with pytest.raises(github.NoGh):
        github.lookup([])
