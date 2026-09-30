"""What GitHub knows about each environment's branch, asked through the gh CLI."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from .envs import Env

REPO_URL = re.compile(r"(?:https://|ssh://git@|git@)github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?/?$")
SHA = re.compile(r"[0-9a-f]{40}")


class GitHubError(Exception):
    pass


class NoGh(GitHubError):
    pass


@dataclass(frozen=True, slots=True)
class PullRequest:
    number: int
    state: str  # draft, open, approved, changes requested, merged or closed
    url: str

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> PullRequest:
        state = (data.get("state") or "").lower()
        if state == "open":
            if data.get("isDraft"):
                state = "draft"
            elif data.get("reviewDecision") == "APPROVED":
                state = "approved"
            elif data.get("reviewDecision") == "CHANGES_REQUESTED":
                state = "changes requested"
        return cls(number=data.get("number", 0), state=state, url=data.get("url", ""))


@dataclass(frozen=True, slots=True)
class BranchStatus:
    pr: PullRequest | None = None
    pushed: bool | None = None  # is the environment's latest commit on GitHub? None if unknown


def _repo(url: str) -> tuple[str, str] | None:
    match = REPO_URL.match(url)
    return (match[1], match[2]) if match else None


def _ask(repo: tuple[str, str], envs: list[Env]) -> dict[str, BranchStatus]:
    """One GraphQL query per repository, covering every environment in it."""
    owner, name = repo
    params = ["$owner: String!", "$name: String!"]
    fields = []
    values = {"owner": owner, "name": name}
    for i, env in enumerate(envs):
        params.append(f"$b{i}: String!")
        values[f"b{i}"] = env.branch
        fields.append(
            f"p{i}: pullRequests(headRefName: $b{i}, first: 1, "
            "orderBy: {field: CREATED_AT, direction: DESC}) "
            "{ nodes { number state isDraft reviewDecision url } }"
        )
        if SHA.fullmatch(env.commit):
            params.append(f"$c{i}: GitObjectID!")
            values[f"c{i}"] = env.commit
            fields.append(f"c{i}: object(oid: $c{i}) {{ oid }}")
    query = (
        f"query({', '.join(params)}) "
        f"{{ repository(owner: $owner, name: $name) {{ {' '.join(fields)} }} }}"
    )
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in values.items():
        args += ["-f", f"{key}={value}"]
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=30)
        data = json.loads(done.stdout or "{}")
    except subprocess.TimeoutExpired as e:
        raise GitHubError("GitHub took too long to answer.") from e
    except json.JSONDecodeError:
        data = {}
    repository = (data.get("data") or {}).get("repository")
    if repository is None:
        errors = [e.get("message", "") for e in data.get("errors") or []]
        raise GitHubError(
            "; ".join(errors) or done.stderr.strip() or f"No answer for {owner}/{name}."
        )

    statuses = {}
    for i, env in enumerate(envs):
        nodes = (repository.get(f"p{i}") or {}).get("nodes") or []
        pushed = repository[f"c{i}"] is not None if f"c{i}" in repository else None
        statuses[env.id] = BranchStatus(
            pr=PullRequest.from_json(nodes[0]) if nodes else None, pushed=pushed
        )
    return statuses


def lookup(envs: list[Env]) -> dict[str, BranchStatus]:
    """Each environment's pull request and push status, keyed by environment ID."""
    if not shutil.which("gh"):
        raise NoGh("gh isn't installed.")
    by_repo: dict[tuple[str, str], list[Env]] = {}
    for env in envs:
        if env.branch and (repo := _repo(env.repo_url)):
            by_repo.setdefault(repo, []).append(env)
    statuses: dict[str, BranchStatus] = {}
    with ThreadPoolExecutor() as pool:
        for found in pool.map(_ask, by_repo, by_repo.values()):
            statuses.update(found)
    return statuses
