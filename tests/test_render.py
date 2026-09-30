from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from conftest import raw_env
from rich.console import Console

from oo.envs import Env
from oo.render import ago, env_table

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("delta", "expected"),
    [
        (timedelta(seconds=5), "just now"),
        (timedelta(minutes=3), "3m ago"),
        (timedelta(hours=5), "5h ago"),
        (timedelta(days=13), "13d ago"),
        (timedelta(days=400), "Aug 26, 2025"),
    ],
)
def test_ago(delta, expected):
    assert ago(NOW - delta, now=NOW) == expected


def render(envs: list[Env], **kwargs) -> str:
    console = Console(width=120, record=True, color_system=None)
    console.print(env_table(envs, "sam/", **kwargs))
    return console.export_text()


def test_repo_column_only_when_it_tells_you_something():
    one = [Env.from_json(raw_env("a", "sam/x")), Env.from_json(raw_env("b", "sam/y"))]
    assert "Repo" not in render(one)
    two = [*one, Env.from_json(raw_env("c", "sam/z", repo="https://github.com/acme/gadgets"))]
    assert "gadgets" in render(two)


def test_numbers_on_request():
    text = render([Env.from_json(raw_env("abc-123", "sam/x"))], numbered=True)
    assert text.splitlines()[1].lstrip().startswith("1")
    assert "Created" not in text


def test_twins_get_told_apart_by_id_and_creation():
    twins = [
        Env.from_json(raw_env("0000-aaaaaa", "sam/x", created="2026-09-28T10:00:00Z")),
        Env.from_json(raw_env("0000-bbbbbb", "sam/x", created="2026-09-29T10:00:00Z")),
    ]
    text = render(twins)
    assert "Created" in text
    assert "aaaaaa" in text and "0000-" not in text
    assert "Sep 28" in text and "Sep 29" in text
