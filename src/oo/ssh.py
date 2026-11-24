"""Plain ssh and scp, for copying files, which ona doesn't do itself."""

from __future__ import annotations

import os
import posixpath
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn


class SshError(Exception):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


def host(env_id: str) -> str:
    """The name `ona environment ssh-config` teaches ssh for an environment."""
    return f"{env_id}.ona.environment"


@dataclass(frozen=True, slots=True)
class Spot:
    """One path in an `oo cp`: on your machine, or in the environment `branch` names."""

    path: str
    remote: bool = False
    branch: str = ""

    @classmethod
    def parse(cls, arg: str) -> Spot:
        """`branch:path` or `:path` means an environment; anything else is a local path.

        Branches can't contain colons, so the first one ends the branch. Paths starting with
        `/`, `.` or `~` are always local, so `./odd:name` is a way to say a local file.
        """
        branch, colon, path = arg.partition(":")
        if not colon or arg.startswith(("/", ".", "~")):
            return cls(arg)
        return cls(path, remote=True, branch=branch)

    def resolved(self, checkout: str) -> str:
        """The remote path, with relative ones starting in the repo checkout, not home."""
        if not checkout or self.path.startswith(("/", "~")):
            return self.path
        return posixpath.join(checkout, self.path) if self.path else checkout


def binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SshError(f"Couldn't find {name}.", hint=f"Make sure [bold]{name}[/] is on your PATH.")
    return path


def configured(env_id: str) -> bool:
    """Whether ssh knows how to reach the environment, from `ona environment ssh-config`."""
    name = host(env_id)
    done = subprocess.run([binary("ssh"), "-G", name], capture_output=True, text=True)
    if done.returncode:
        return False
    settings = dict(line.partition(" ")[::2] for line in done.stdout.splitlines())
    # Unconfigured, ssh would just try to look the made-up name up in DNS.
    return (
        settings.get("hostname") != name
        or settings.get("proxycommand", "none") != "none"
        or settings.get("proxyjump", "none") != "none"
    )


def put_in_home(env_id: str, source: Path, dest: str, timeout: float = 60) -> None:
    """Write the local file `source` to `dest` in the environment's home folder, private to you.

    It goes down ssh's stdin rather than through scp, so that one connection can make the folder,
    write the file and keep it from other users.
    """
    folder = '"$HOME"/' + shlex.quote(posixpath.dirname(dest))
    target = '"$HOME"/' + shlex.quote(dest)
    command = f"mkdir -p {folder} && umask 077 && cat > {target} && chmod 600 {target}"
    try:
        with source.open("rb") as stdin:
            done = subprocess.run(
                [binary("ssh"), "-o", "BatchMode=yes", host(env_id), command],
                stdin=stdin,
                capture_output=True,
                timeout=timeout,
            )
    except OSError as e:
        raise SshError(f"Couldn't read {source}.", hint=e.strerror) from e
    except subprocess.TimeoutExpired as e:
        raise SshError("The environment took too long to answer over SSH.") from e
    if done.returncode:
        raise SshError(
            "Couldn't write to the environment over SSH.",
            hint=done.stderr.decode(errors="replace").strip() or None,
        )


def feed(env_id: str, command: str, data: bytes, *, failed: str, timeout: float = 60) -> None:
    """Run `command` in the environment's shell, with `data` on its stdin.

    For secrets, which this keeps out of every command line on this machine. Raises SshError
    saying `failed`, with what the command printed to stderr, if it doesn't exit cleanly.
    """
    try:
        done = subprocess.run(
            [binary("ssh"), "-o", "BatchMode=yes", host(env_id), command],
            input=data,
            capture_output=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise SshError("The environment took too long to answer over SSH.") from None
    if done.returncode:
        raise SshError(failed, hint=done.stderr.decode(errors="replace").strip() or None)


def replace_with_scp(*args: str) -> NoReturn:
    """Become scp, so it can show its progress and ask for anything it needs."""
    scp = binary("scp")
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(scp, [scp, *args])
