"""Your Buildkite CLI token: asked for through bk here, and handed to bk in an environment."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import ssh


class BuildkiteError(Exception):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


@dataclass(frozen=True, slots=True)
class Login:
    """The access token bk is signed in with, and the organization it's for."""

    token: str = field(repr=False)  # kept out of anything that prints a Login
    org: str
    expires: datetime | None = None  # None if Buildkite didn't say

    def expiry(self, now: datetime | None = None) -> str:
        """e.g. `expires in 7h`, or nothing if Buildkite didn't say when."""
        if self.expires is None:
            return ""
        minutes = int((self.expires - (now or datetime.now(UTC))).total_seconds() // 60)
        if minutes < 0:
            return "already expired"
        if minutes < 60:
            return f"expires in {max(minutes, 1)}m"
        hours = minutes // 60
        return f"expires in {hours}h" if hours < 48 else f"expires in {hours // 24}d"


def _when(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        when = datetime.fromisoformat(value)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=UTC)


def login(timeout: float = 60) -> Login:
    """The token bk is signed in with on this machine, renewed by bk first if it had expired.

    bk keeps it in your system's keychain, so there's no file to read: `bk auth token --json`
    hands it over, along with its organization and when it expires. Only what bk prints to
    stderr ever goes into an error, since its stdout is the token.
    """
    bk = shutil.which("bk")
    if not bk:
        raise BuildkiteError(
            "bk isn't installed.",
            hint="Install the Buildkite CLI, then run [bold]bk auth login[/].",
        )
    try:
        done = subprocess.run(
            [bk, "auth", "token", "--json"], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise BuildkiteError("bk took too long to answer.") from None
    if done.returncode:
        said = done.stderr.strip().splitlines()
        raise BuildkiteError("bk has no token to give.", hint=said[-1] if said else None)
    try:
        data = json.loads(done.stdout)
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        data = {}
    token, org = data.get("access_token"), data.get("organization_slug")
    if not (isinstance(token, str) and token.strip() and isinstance(org, str) and org.strip()):
        raise BuildkiteError(
            "bk didn't say which token and organization it's signed in with.",
            hint="Check [bold]bk auth status[/], and that bk is up to date.",
        )
    return Login(token=token.strip(), org=org.strip(), expires=_when(data.get("expires_at")))


def sign_in_command(org: str) -> str:
    """The shell that signs bk in for `org` in an environment, with the token from its stdin.

    bk only takes a token as an argument, so it's on bk's own command line there for the moment
    bk runs, but never on ssh's here. bk exits happily when it has nowhere to keep a token, so
    asking for the token back is what tells us it stuck.
    """
    o = shlex.quote(org)
    script = (
        'command -v bk >/dev/null || { echo "bk isn\'t installed there." >&2; exit 127; }; '
        "IFS= read -r token || exit 1; "
        f'bk auth login --org {o} --token "$token" >/dev/null || exit 1; '
        f"bk auth token --org {o} >/dev/null 2>&1 || "
        '{ echo "bk there had nowhere to keep the token." >&2; exit 1; }'
    )
    # Whatever your shell is in the environment, sh reads this the same way.
    return f"sh -c {shlex.quote(script)}"


def sign_in(env_id: str, login: Login) -> None:
    """Sign bk in on the environment as it is here. Raises ssh.SshError if that doesn't work.

    Only the access token goes. The refresh token that renews it stays here: Buildkite replaces
    it on each use, so sharing it would sign out whichever machine renewed second.
    """
    try:
        ssh.feed(
            env_id,
            sign_in_command(login.org),
            login.token.encode() + b"\n",
            failed="bk wouldn't sign in there.",
        )
    except ssh.SshError as e:
        # bk has no reason to repeat the token back, but it mustn't reach your terminal if it does.
        hint = (e.hint or "").replace(login.token, "<token>") or None
        raise ssh.SshError(str(e), hint=hint) from None
