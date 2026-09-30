"""The thin layer that actually runs the `ona` CLI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import Any, NoReturn

from .envs import Env
from .projects import EnvClass, Project


class OnaError(Exception):
    def __init__(self, message: str, detail: str | None = None, hint: str | None = None):
        super().__init__(message)
        self.detail = detail
        self.hint = hint


def _binary() -> str:
    path = shutil.which("ona")
    if not path:
        raise OnaError(
            "Couldn't find the ona CLI.",
            hint="Install it and make sure [bold]ona[/] is on your PATH, then [bold]ona login[/].",
        )
    return path


def _error(what: str, stderr: str) -> OnaError:
    """Pull ona's `Error: …` lines out from under any usage text it prints."""
    lines = [line.strip() for line in stderr.splitlines()]
    errors = [line.removeprefix("Error:").strip() for line in lines if line.startswith("Error:")]
    detail = "; ".join(errors) or next((line for line in lines if line), "") or None
    hint = None
    auth_words = ("login", "unauthenticated", "unauthorized", "expired")
    if detail and any(w in detail.lower() for w in auth_words):
        hint = "You may need to log in again: [bold]ona login[/]"
    return OnaError(f"ona couldn't list {what}.", detail=detail, hint=hint)


def _list(what: str, *args: str, timeout: float | None = None) -> list[dict[str, Any]]:
    try:
        done = subprocess.run(
            [_binary(), *args, "--format", "json"], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        raise OnaError(f"ona took too long to list {what}.") from e
    if done.returncode != 0:
        raise _error(what, done.stderr)
    try:
        return json.loads(done.stdout or "[]") or []
    except json.JSONDecodeError as e:
        raise OnaError("ona sent back something that isn't JSON.", detail=str(e)) from e


def list_envs(timeout: float | None = None) -> list[Env]:
    items = _list("your environments", "environment", "list", timeout=timeout)
    return [Env.from_json(item) for item in items]


def list_projects() -> list[Project]:
    return [Project.from_json(item) for item in _list("projects", "project", "list")]


def list_classes() -> list[EnvClass]:
    items = _list("environment classes", "environment", "list-classes")
    return [EnvClass.from_json(item) for item in items if item.get("enabled", True)]


def run(*args: str) -> int:
    """Run an ona command attached to this terminal; returns its exit code."""
    return subprocess.call([_binary(), *args])


def replace_with(*args: str) -> NoReturn:
    """Become an ona command, so SSH gets the terminal all to itself."""
    binary = _binary()
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(binary, [binary, *args])
