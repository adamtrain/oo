"""What `oo new` creates from: an Ona project, on an environment class (a machine in a region)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .envs import Env, newest

PROJECT_VAR = "OO_PROJECT"
CLASS_VAR = "OO_CLASS"


@dataclass(frozen=True, slots=True)
class EnvClass:
    id: str
    name: str  # the machine, e.g. m7i.xlarge
    runner: str  # where it runs, e.g. Frankfurt

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> EnvClass:
        return cls(id=data.get("id", ""), name=data.get("name", ""), runner=data.get("runner", ""))

    def __str__(self) -> str:
        return f"{self.name} in {self.runner}" if self.runner else self.name or self.id


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    class_ids: tuple[str, ...] = ()  # the classes it offers, in the order the UI shows them

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Project:
        offered = sorted(data.get("environmentClasses") or [], key=lambda c: c.get("order") or 0)
        return cls(
            id=data.get("id", ""),
            name=(data.get("metadata") or {}).get("name") or "",
            class_ids=tuple(
                c["environmentClassId"] for c in offered if c.get("environmentClassId")
            ),
        )


class ChoiceError(Exception):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


def pick_project(projects: list[Project], envs: list[Env], wanted: str | None) -> Project:
    """The project named by ID or name, or else the one your latest environment came from."""
    if wanted:
        q = wanted.strip().lower()
        for project in projects:
            if q in (project.id.lower(), project.name.lower()):
                return project
        raise ChoiceError(
            f'No project matches "{wanted}".',
            hint="See them with [bold]ona project list[/].",
        )
    latest = newest([e for e in envs if e.project_id])
    if latest is None:
        raise ChoiceError(
            "Which project should I create the environment from?",
            hint=f"Set [bold]${PROJECT_VAR}[/] to a project from [bold]ona project list[/].",
        )
    known = {p.id: p for p in projects}
    return known.get(latest.project_id, Project(id=latest.project_id, name=""))


def pick_class(
    classes: list[EnvClass], project: Project, envs: list[Env], wanted: str | None
) -> EnvClass | None:
    """The class to create on.

    `wanted` can be an ID, or words that pick one out, like `frankfurt` or `tokyo m7i`, preferring
    the classes the project offers. Without it, reuse whatever your latest environment from
    this project ran on, or else the project's first choice. None leaves it to Ona.
    """
    by_id = {c.id: c for c in classes}
    offered = [by_id[i] for i in project.class_ids if i in by_id]
    if wanted:
        if wanted.strip() in by_id:
            return by_id[wanted.strip()]
        words = wanted.lower().replace("/", " ").split()
        for pool in (offered, classes):
            hits = [c for c in pool if all(w in f"{c.runner} {c.name}".lower() for w in words)]
            if len(hits) == 1:
                return hits[0]
            if hits:
                options = ", ".join(str(c) for c in hits)
                raise ChoiceError(f'"{wanted}" could mean {options}.', hint="Be more specific.")
        choices = ", ".join(str(c) for c in offered or classes)
        raise ChoiceError(
            f'No environment class matches "{wanted}".', hint=f"Try one of: {choices}"
        )
    latest = newest([e for e in envs if e.project_id == project.id and e.class_id in by_id])
    if latest is not None and (not offered or by_id[latest.class_id] in offered):
        return by_id[latest.class_id]
    return offered[0] if offered else None
