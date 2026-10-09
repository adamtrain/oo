"""Plain ssh and scp, for copying files, which ona doesn't do itself."""

from __future__ import annotations

import os
import posixpath
import shutil
import subprocess
import sys
from dataclasses import dataclass
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


def _binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SshError(f"Couldn't find {name}.", hint=f"Make sure [bold]{name}[/] is on your PATH.")
    return path


def configured(env_id: str) -> bool:
    """Whether ssh knows how to reach the environment, from `ona environment ssh-config`."""
    name = host(env_id)
    done = subprocess.run([_binary("ssh"), "-G", name], capture_output=True, text=True)
    if done.returncode:
        return False
    settings = dict(line.partition(" ")[::2] for line in done.stdout.splitlines())
    # Unconfigured, ssh would just try to look the made-up name up in DNS.
    return (
        settings.get("hostname") != name
        or settings.get("proxycommand", "none") != "none"
        or settings.get("proxyjump", "none") != "none"
    )


def replace_with_scp(*args: str) -> NoReturn:
    """Become scp, so it can show its progress and ask for anything it needs."""
    binary = _binary("scp")
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(binary, [binary, *args])
