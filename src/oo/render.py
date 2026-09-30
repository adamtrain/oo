"""Everything oo prints for people to read."""

from __future__ import annotations

from datetime import UTC, datetime

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .envs import Env
from .github import BranchStatus
from .projects import EnvClass, Project

ACCENT = "#7c83f7"
ERROR = "#f2506e"
FAINT = "grey42"
GREEN = "#1fbf8f"
AMBER = "#eb9a12"
PURPLE = "#a871f7"

PR_LOOKS = {
    "draft": FAINT,
    "open": GREEN,
    "approved": f"bold {GREEN}",
    "changes requested": AMBER,
    "merged": PURPLE,
    "closed": ERROR,
}
PR_LABELS = {"changes requested": "changes req."}  # keeps the table inside 80 columns

PHASE_LOOKS = {
    "running": ("●", GREEN),
    "starting": ("◐", AMBER),
    "creating": ("◐", AMBER),
    "updating": ("◐", AMBER),
    "stopping": ("◑", AMBER),
    "stopped": ("○", FAINT),
    "deleting": ("✕", ERROR),
    "deleted": ("✕", FAINT),
}


def ago(when: datetime | None, now: datetime | None = None) -> str:
    if when is None:
        return "?"
    seconds = ((now or datetime.now(UTC)) - when).total_seconds()
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)}m ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h ago"
    if seconds < 60 * 86400:
        return f"{int(seconds // 86400)}d ago"
    return when.strftime("%b %-d, %Y")


def created(when: datetime | None) -> str:
    """Date and time in your timezone, precise enough to tell same-day environments apart."""
    return when.astimezone().strftime("%b %-d %H:%M") if when else "?"


def branch(env: Env, prefix: str) -> Text:
    """The branch with your prefix dimmed, so the part you'd type stands out."""
    if not env.branch:
        return Text(env.short_branch(prefix), style="bold")
    short = env.short_branch(prefix)
    if short == env.branch:
        return Text(short, style="bold")
    return Text.assemble((prefix, FAINT), (short, "bold"))


def phase(env: Env) -> Text:
    dot, color = PHASE_LOOKS.get(env.phase, ("?", FAINT))
    return Text.assemble((f"{dot} ", color), (env.phase, "" if env.running else color))


def pull_request(status: BranchStatus | None) -> Text:
    if status is None or status.pr is None:
        return Text()
    pr = status.pr
    number_style = f"link {pr.url}" if pr.url else ""
    return Text.assemble(
        (f"#{pr.number}", number_style),
        " ",
        (PR_LABELS.get(pr.state, pr.state), PR_LOOKS.get(pr.state, FAINT)),
    )


def changes(env: Env, status: BranchStatus | None) -> Text:
    parts = [f"{env.changed_count} uncommitted"] if env.changed_count else []
    if status and status.pushed is False:
        parts.append("unpushed")
    return Text(", ".join(parts), style=AMBER)


def env_table(
    envs: list[Env],
    prefix: str,
    *,
    width: int | None = None,
    numbered: bool = False,
    github: dict[str, BranchStatus] | None = None,
) -> Table:
    """One row per environment, fitted to `width` by cutting the branch short if need be.

    When branches repeat, rows also show the end of their ID and when they were created, to
    tell them apart. Pass what GitHub said about each branch as `github` to get a PR column.
    """
    show_repo = len({e.repo for e in envs}) > 1
    twins = len({e.branch for e in envs}) < len(envs)
    table = Table(box=None, pad_edge=False, padding=(0, 1), header_style=FAINT)
    if numbered:
        table.add_column("#", justify="right", style=FAINT, no_wrap=True)
    table.add_column("Branch", no_wrap=True, overflow="ellipsis")
    if twins:
        table.add_column("ID", no_wrap=True)
    if show_repo:
        table.add_column("Repo", no_wrap=True)
    table.add_column("Status", no_wrap=True)
    if twins:
        table.add_column("Created", no_wrap=True)
    table.add_column("Active", no_wrap=True, style=FAINT)
    if github is not None:
        table.add_column("PR", no_wrap=True)
    table.add_column("Changes", no_wrap=True)

    rows: list[list[Text]] = []
    for i, env in enumerate(envs, 1):
        status = github.get(env.id) if github else None
        cells = [Text(str(i))] if numbered else []
        cells.append(branch(env, prefix))
        if twins:
            cells.append(Text(env.short_id, style=ACCENT))
        if show_repo:
            cells.append(Text(env.repo))
        cells.append(phase(env))
        if twins:
            cells.append(Text(created(env.created)))
        cells.append(Text(ago(env.last_active)))
        if github is not None:
            cells.append(pull_request(status))
        cells.append(changes(env, status))
        rows.append(cells)
        table.add_row(*cells)

    if width is not None:
        # Every other column gets what it needs, plus a gap of 2 between columns.
        branch_index = 1 if numbered else 0
        others = sum(
            max(len(str(column.header)), *(row[i].cell_len for row in rows))
            for i, column in enumerate(table.columns)
            if i != branch_index
        )
        table.columns[branch_index].max_width = max(10, width - others - 2 * (len(rows[0]) - 1))
    return table


def listing(
    console: Console, envs: list[Env], prefix: str, github: dict[str, BranchStatus] | None
) -> None:
    console.print()
    console.print(env_table(envs, prefix, width=console.width, github=github))
    console.print()


def heading(console: Console, verb: str, env: Env, prefix: str, note: str = "") -> None:
    """e.g. `→ Connecting to adam/login-fix · running`"""
    line = Text.assemble(("→ ", ACCENT), (f"{verb} ", ACCENT), branch(env, prefix))
    line.append(f" · {note or env.phase}", style=FAINT)
    console.print(line)


def question(console: Console, message: str) -> None:
    console.print(Text.assemble(("? ", f"bold {ACCENT}"), (message, "bold")))


def warning(console: Console, message: str, detail: str | None = None) -> None:
    console.print(Text.assemble(("! ", f"bold {AMBER}"), message))
    if detail:
        console.print(Text(f"  {detail}", style=FAINT))


def working(message: str) -> Text:
    return Text(message, style=ACCENT)


def success(console: Console, message: str) -> None:
    console.print(Text.assemble(("✓ ", f"bold {GREEN}"), message))


def error(console: Console, message: str, *, detail: str | None = None, hint: str | None = None):
    console.print(Text.assemble(("✗ ", f"bold {ERROR}"), (message, "bold")))
    if detail:
        console.print(Text(f"  {detail}", style=FAINT))
    if hint:
        console.print(Text.from_markup(f"  {hint}"))


def creating(console: Console, project: Project, env_class: EnvClass | None) -> None:
    """e.g. `→ Creating an environment from Web app · m7i.xlarge in Frankfurt`"""
    line = Text.assemble(
        ("→ Creating an environment from ", ACCENT), (project.name or project.id, "bold")
    )
    line.append(f" · {env_class}" if env_class else " · on Ona's default class", style=FAINT)
    console.print(line)
