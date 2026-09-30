"""`oo`: hop into your Ona environments by branch name."""

from __future__ import annotations

import difflib
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.prompt import IntPrompt

from . import __version__, github, ona, render
from .envs import PREFIX_VAR, Ambiguous, Env, NoMatch, branch_prefix, newest, pick, sort_envs
from .github import BranchStatus, GitHubError, NoGh
from .ona import OnaError
from .projects import CLASS_VAR, PROJECT_VAR, ChoiceError, pick_class, pick_project

out = Console(highlight=False)
err = Console(stderr=True, highlight=False)

app = typer.Typer(
    rich_markup_mode="rich",
    context_settings={"help_option_names": ["-h", "--help"]},
)

ACTIVE = ("running", "starting", "creating", "updating")
NO_ENVS_HINT = "Create one with [bold]ona environment create <repo-url>[/]."


def _fail(message: str, *, detail: str | None = None, hint: str | None = None) -> NoReturn:
    render.error(err, message, detail=detail, hint=hint)
    raise typer.Exit(1)


def _interactive() -> bool:
    """Whether there's someone at a terminal to answer questions."""
    return sys.stdin.isatty() and err.is_terminal


def _cancelled() -> NoReturn:
    err.print("\n[dim]Cancelled.[/]")
    raise typer.Exit(130)


def _load() -> list[Env]:
    try:
        with err.status(render.working("Asking Ona…"), spinner_style=render.ACCENT):
            return sort_envs(ona.list_envs())
    except OnaError as e:
        _fail(str(e), detail=e.detail, hint=e.hint)
    except KeyboardInterrupt:
        _cancelled()


def _github(envs: list[Env]) -> dict[str, BranchStatus] | None:
    """What GitHub says about each branch, or None if we can't ask."""
    try:
        with err.status(render.working("Asking GitHub…"), spinner_style=render.ACCENT):
            return github.lookup(envs)
    except NoGh:
        return None
    except GitHubError as e:
        render.warning(err, "Couldn't get pull requests from GitHub.", detail=str(e))
        return None
    except KeyboardInterrupt:
        _cancelled()


def _find(envs: list[Env], query: str, *, strict: bool = False) -> Env:
    prefix = branch_prefix()
    try:
        return pick(envs, query, prefix, strict=strict)
    except NoMatch:
        if not envs:
            _fail("You don't have any environments yet.", hint=NO_ENVS_HINT)
        close = difflib.get_close_matches(query, [e.short_branch(prefix) for e in envs], n=3)
        hint = "Run [bold]oo[/] to see your environments."
        if close:
            hint = "Did you mean " + " or ".join(f"[bold]{name}[/]" for name in close) + "?"
        _fail(f'No environment matches "{query}".', hint=hint)
    except Ambiguous as e:
        same_branch = len({c.branch for c in e.candidates}) == 1
        render.error(err, f'"{query}" matches {len(e.candidates)} environments:')
        err.print()
        err.print(
            render.env_table(e.candidates, prefix, width=err.width, ids=same_branch, details=False)
        )
        err.print()
        err.print("  Use its ID instead." if same_branch else "  Be more specific.")
        raise typer.Exit(1) from None


def _find_all(envs: list[Env], queries: list[str], *, strict: bool = False) -> list[Env]:
    found = [_find(envs, q, strict=strict) for q in queries]
    return list({env.id: env for env in found}.values())


def _choose(envs: list[Env], query: str | None, verb: str) -> Env:
    """The environment `query` names; without one, the obvious choice or else ask."""
    if query:
        return _find(envs, query)
    if not envs:
        _fail("You don't have any environments yet.", hint=NO_ENVS_HINT)
    running = [e for e in envs if e.running]
    if len(envs) == 1:
        return envs[0]
    if len(running) == 1:
        return running[0]
    if not _interactive():
        _fail(f"Which environment should I {verb}?", hint="Pass its branch name.")
    err.print()
    err.print(render.env_table(envs, branch_prefix(), width=err.width, numbered=True))
    err.print()
    try:
        choice = IntPrompt.ask(
            f"[{render.ACCENT}]Which one?[/] [dim](1-{len(envs)})[/]",
            console=err,
            choices=[str(i) for i in range(1, len(envs) + 1)],
            show_choices=False,
        )
    except (KeyboardInterrupt, EOFError):
        _cancelled()
    return envs[choice - 1]


def _run(*args: str) -> None:
    try:
        code = ona.run(*args)
    except KeyboardInterrupt:
        _cancelled()
    if code:
        raise typer.Exit(code)


def _complete_branch(incomplete: str) -> list[tuple[str, str]]:
    try:
        envs = sort_envs(ona.list_envs(timeout=5))
    except (OnaError, OSError):
        return []
    prefix = branch_prefix()
    names = [(e.short_branch(prefix), e.phase) for e in envs]
    return [(name, phase) for name, phase in names if name.startswith(incomplete)]


BRANCH_HELP = "Branch (your prefix is optional), environment name or ID."
Branch = Annotated[
    str, typer.Argument(help=BRANCH_HELP, autocompletion=_complete_branch, show_default=False)
]
MaybeBranch = Annotated[
    str | None,
    typer.Argument(help=BRANCH_HELP, autocompletion=_complete_branch, show_default=False),
]
Branches = Annotated[
    list[str],
    typer.Argument(help=BRANCH_HELP, autocompletion=_complete_branch, show_default=False),
]
MaybeBranches = Annotated[
    list[str] | None,
    typer.Argument(help=BRANCH_HELP, autocompletion=_complete_branch, show_default=False),
]
Wait = Annotated[bool, typer.Option("--wait", "-w", help="Wait for ona to finish.")]


def _version(value: bool) -> None:
    if value:
        out.print(f"oo {__version__}")
        raise typer.Exit()


EPILOG = (
    "[bold]Examples[/]\n\n"
    "  [cyan]oo[/]                             list your environments\n"
    "  [cyan]oo c login-fix[/]                  SSH into the one on adam/login-fix\n"
    "  [cyan]oo c[/]                           …the only running one, or pick from a list\n"
    "  [cyan]oo c login -- git status[/]        run a command instead of a shell\n"
    "  [cyan]oo open login -e cursor[/]         open it in Cursor\n"
    "  [cyan]oo new[/]                         create an environment and connect to it\n"
    "  [cyan]oo stop --all[/]                  stop everything that's running\n"
    "  [cyan]ona env logs $(oo id login)[/]    hand an ID to any other ona command\n\n"
    f"Set [bold]${PREFIX_VAR}[/] (e.g. [dim]adam/[/]) to leave your branch prefix off. "
    "Branches can be shortened to any unique part."
)


@app.callback(invoke_without_command=True, epilog=EPILOG)
def root(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option("--version", "-V", callback=_version, is_eager=True, help="Show version."),
    ] = None,
) -> None:
    """Hop into your [bold]Ona[/] environments by branch name.

    With no command, lists your environments.
    """
    if ctx.invoked_subcommand is None:
        ls()


@app.command("ls")
def ls() -> None:
    """List your environments, running ones first, with their pull requests."""
    envs = _load()
    if not envs:
        render.error(err, "You don't have any environments yet.", hint=NO_ENVS_HINT)
        return
    render.listing(out, envs, branch_prefix(), _github(envs))


@app.command("c")
def connect(
    branch: MaybeBranch = None,
    command: Annotated[
        list[str] | None,
        typer.Argument(
            help="A command to run instead of a shell, after [bold]--[/].", show_default=False
        ),
    ] = None,
) -> None:
    """SSH into an environment, starting it first if it's stopped."""
    env = _choose(_load(), branch, "connect to")
    starting = "" if env.running else f"{env.phase}, so starting it first"
    render.heading(err, "Connecting to", env, branch_prefix(), starting)
    ona.replace_with("environment", "ssh", env.id, *(["--", *command] if command else []))


@app.command("open")
def open_(
    branch: MaybeBranch = None,
    editor: Annotated[
        str | None,
        typer.Option(
            "--editor",
            "-e",
            envvar="OO_EDITOR",
            help="Editor alias like [bold]cursor[/] or [bold]vscode[/] "
            "(see [bold]ona environment list-editors[/]).",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Open an environment in your editor, starting it first if it's stopped."""
    env = _choose(_load(), branch, "open")
    render.heading(err, "Opening", env, branch_prefix(), f"in {editor}" if editor else "")
    ona.replace_with(
        "environment", "open", env.id, "--start", *(["--editor", editor] if editor else [])
    )


@app.command()
def new(
    project: Annotated[
        str | None,
        typer.Option(
            "--project",
            "-p",
            envvar=PROJECT_VAR,
            help="Project to create from, by ID or name. "
            "Defaults to the one your newest environment came from.",
            show_default=False,
        ),
    ] = None,
    env_class: Annotated[
        str | None,
        typer.Option(
            "--class",
            "-c",
            envvar=CLASS_VAR,
            help="Where to run it: a region like [bold]frankfurt[/], optionally with a machine "
            "like [bold]m7i[/], or a class ID. Defaults to what your newest environment runs on.",
            show_default=False,
        ),
    ] = None,
) -> None:
    """Create an environment and connect to it."""
    try:
        with (
            err.status(render.working("Asking Ona…"), spinner_style=render.ACCENT),
            ThreadPoolExecutor() as pool,
        ):
            envs_job = pool.submit(ona.list_envs)
            projects_job = pool.submit(ona.list_projects)
            classes_job = pool.submit(ona.list_classes)
            envs, projects, classes = envs_job.result(), projects_job.result(), classes_job.result()
    except OnaError as e:
        _fail(str(e), detail=e.detail, hint=e.hint)
    except KeyboardInterrupt:
        _cancelled()
    try:
        chosen = pick_project(projects, envs, project)
        where = pick_class(classes, chosen, envs, env_class)
    except ChoiceError as e:
        _fail(str(e), hint=e.hint)

    render.creating(err, chosen, where)
    before = {e.id for e in envs}
    _run("environment", "create", chosen.id, *(["--class-id", where.id] if where else []))
    created = newest([e for e in _load() if e.id not in before])
    if created is None:
        _fail("Ona created it, but I can't find it to connect.", hint="Run [bold]oo[/] to look.")
    render.heading(err, "Connecting to", created, branch_prefix())
    ona.replace_with("environment", "ssh", created.id)


@app.command()
def start(branches: Branches, wait: Wait = False) -> None:
    """Start environments without connecting, to warm them up."""
    prefix = branch_prefix()
    targets = []
    for env in _find_all(_load(), branches):
        if env.phase in ACTIVE:
            render.heading(err, "Skipping", env, prefix, f"already {env.phase}")
        else:
            render.heading(err, "Starting", env, prefix)
            targets.append(env)
    if not targets:
        return
    _run("environment", "start", *(e.id for e in targets), *([] if wait else ["--dont-wait"]))
    if not wait:
        err.print("[dim]  They'll finish starting in the background. `oo c` waits if it has to.[/]")


@app.command()
def stop(
    branches: MaybeBranches = None,
    everything: Annotated[
        bool, typer.Option("--all", "-a", help="Stop every running one.")
    ] = False,
    wait: Wait = False,
) -> None:
    """Stop environments. With no branch, stops the only running one."""
    prefix = branch_prefix()
    envs = _load()
    running = [e for e in envs if e.phase in ACTIVE]
    if branches:
        targets = []
        for env in _find_all(envs, branches):
            if env.phase in ACTIVE:
                targets.append(env)
            else:
                render.heading(err, "Skipping", env, prefix, f"already {env.phase}")
        if not targets:
            return
    elif everything or len(running) <= 1:
        targets = running
    else:
        _fail(
            f"{len(running)} environments are running.",
            hint="Name the ones to stop, or stop them all with [bold]oo stop --all[/].",
        )
    if not targets:
        render.success(err, "Nothing is running.")
        return
    for env in targets:
        render.heading(err, "Stopping", env, prefix)
    _run("environment", "stop", *(e.id for e in targets), *([] if wait else ["--dont-wait"]))


@app.command("rm")
def remove(branches: Branches, wait: Wait = False) -> None:
    """Delete environments. Ona finishes the job in the background."""
    prefix = branch_prefix()
    targets = _find_all(_load(), branches, strict=True)
    for env in targets:
        render.heading(err, "Deleting", env, prefix)
    _run("environment", "delete", *(e.id for e in targets), *([] if wait else ["--dont-wait"]))
    if wait:
        render.success(err, "Deleted.")
    else:
        err.print("[dim]  Ona will finish deleting in the background.[/]")


@app.command("id")
def id_(branch: Branch) -> None:
    """Print an environment's ID, to hand to other ona commands."""
    print(_find(_load(), branch).id)


# Longhand spellings, for muscle memory from ona and friends.
app.command("ssh", hidden=True)(connect)
app.command("list", hidden=True)(ls)
app.command("delete", hidden=True)(remove)


def main() -> None:
    app()
