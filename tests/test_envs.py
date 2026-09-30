from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import raw_env

from oo.envs import Ambiguous, Env, NoMatch, branch_prefix, matches, pick, sort_envs


def env(*args, **kwargs) -> Env:
    return Env.from_json(raw_env(*args, **kwargs))


ENVS = [
    env("11111111-aaaa", "sam/feat-10", "running", active="2026-09-30T10:00:00Z"),
    env("22222222-bbbb", "sam/feat-10-2", "stopped", active="2026-09-29T10:00:00Z"),
    env("33333333-cccc", "sam/docs", "stopped", active="2026-09-28T10:00:00Z", name="Docs"),
    env("44444444-dddd", "kim/review-me", "stopped"),
    env("55555555-eeee", "main", "stopped"),
]


def test_parses_what_we_need():
    e = env(
        "abc", "sam/x", "running", changed=["a.py", "b.py"], active="2026-09-30T18:07:04.123456789Z"
    )
    assert (e.branch, e.phase, e.repo, e.changed_count) == ("sam/x", "running", "widgets", 2)
    assert e.changes == ("a.py", "b.py")
    assert e.last_active == datetime(2026, 9, 30, 18, 7, 4, 123456, tzinfo=UTC)


def test_falls_back_to_the_spec_before_cloning():
    e = Env.from_json(
        {
            "id": "abc",
            "spec": {
                "content": {
                    "initializer": {
                        "specs": [
                            {"git": {"cloneTarget": "sam/new", "remoteUri": "https://x/y.git"}}
                        ]
                    }
                }
            },
            "status": {"phase": "ENVIRONMENT_PHASE_CREATING"},
        }
    )
    assert (e.branch, e.repo, e.phase, e.last_active) == ("sam/new", "y", "creating", None)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("", ""), ("sam", "sam/"), ("sam/", "sam/"), (" sam ", "sam/"), ("sam-", "sam-")],
)
def test_branch_prefix_gets_a_separator(monkeypatch, value, expected):
    monkeypatch.setenv("OO_BRANCH_PREFIX", value)
    assert branch_prefix() == expected


def test_short_branch_strips_only_your_prefix():
    assert ENVS[0].short_branch("sam/") == "feat-10"
    assert ENVS[3].short_branch("sam/") == "kim/review-me"
    assert ENVS[0].short_branch("") == "sam/feat-10"


def ids(envs: list[Env]) -> list[str]:
    return [e.id[:2] for e in envs]


@pytest.mark.parametrize(
    ("query", "prefix", "expected"),
    [
        ("feat-10", "sam/", ["11"]),  # exact with prefix beats substring feat-10-2
        ("feat-10", "", ["11"]),  # branch tail, no prefix needed
        ("sam/feat-10-2", "sam/", ["22"]),  # full branch name
        ("review-me", "sam/", ["44"]),  # someone else's prefix
        ("feat", "sam/", ["11", "22"]),  # substring
        ("DOCS", "", ["33"]),  # case-insensitive, name or branch
        ("Docs", "", ["33"]),  # exact name
        ("4444", "", ["44"]),  # ID prefix
        ("-eeee", "", ["55"]),  # ID suffix
        ("11111111-aaaa", "", ["11"]),  # full ID
        ("nope", "", []),
        ("  ", "", []),
    ],
)
def test_matches(query, prefix, expected):
    assert ids(matches(ENVS, query, prefix)) == expected


def test_pick_complains_about_different_branches():
    with pytest.raises(Ambiguous) as e:
        pick(ENVS, "feat", "sam/")
    assert ids(e.value.candidates) == ["11", "22"]


def test_pick_complains_when_nothing_matches():
    with pytest.raises(NoMatch):
        pick(ENVS, "nope", "sam/")


def test_pick_wont_guess_between_environments_on_one_branch():
    twins = [
        env("0000-aaaaaa", "sam/twin", "stopped", active="2026-09-30T11:00:00Z"),
        env("0000-bbbbbb", "sam/twin", "running", active="2026-09-30T09:00:00Z"),
    ]
    with pytest.raises(Ambiguous) as e:
        pick(twins, "twin", "sam/")
    assert [c.short_id for c in e.value.candidates] == ["bbbbbb", "aaaaaa"]  # running first
    assert pick(twins, "aaaaaa", "sam/").id == "0000-aaaaaa"


def test_sort_puts_running_first_then_recent():
    shuffled = [ENVS[2], ENVS[1], ENVS[0], env("66", "starting-one", "starting")]
    assert ids(sort_envs(shuffled)) == ["11", "66", "22", "33"]
