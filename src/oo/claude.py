"""Handing an environment to the Claude desktop app, which connects to it over SSH itself."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from urllib.parse import urlencode

from . import ssh

BUNDLE_ID = "com.anthropic.claudefordesktop"
NOT_INSTALLED_HINT = "Install it from [bold]https://claude.ai/download[/], then open it once."


class ClaudeError(Exception):
    def __init__(self, message: str, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


def link(env_id: str, checkout: str = "") -> str:
    """The link that starts a Claude Code session in the desktop app, over SSH to `env_id`.

    The app only takes folders starting with `/` or `~/`, so anything else is left off and
    Claude Code starts in the home folder.
    """
    params = {"ssh_host": ssh.host(env_id)}
    if checkout.startswith(("/", "~/")):
        params["ssh_folder"] = checkout
    return f"claude://code/new?{urlencode(params)}"


def check_installed() -> None:
    """Fail early if the Claude desktop app clearly isn't there.

    Only macOS can say for sure, so elsewhere this lets everything through, and `open_link`
    finds out instead.
    """
    osascript = shutil.which("osascript") if sys.platform == "darwin" else None
    if not osascript:
        return
    script = f'POSIX path of (path to application id "{BUNDLE_ID}")'
    done = subprocess.run([osascript, "-e", script], capture_output=True, text=True)
    if done.returncode:
        raise ClaudeError("The Claude desktop app isn't installed.", hint=NOT_INSTALLED_HINT)


def open_link(url: str) -> None:
    """Have the OS hand `url` to the Claude desktop app."""
    if sys.platform == "win32":
        try:
            os.startfile(url)
        except OSError as e:
            raise ClaudeError(
                "Couldn't open the Claude desktop app.", hint=NOT_INSTALLED_HINT
            ) from e
        return
    opener = shutil.which("open" if sys.platform == "darwin" else "xdg-open")
    if not opener:
        raise ClaudeError(
            "Couldn't find a way to open links.", hint=f"Open [bold]{url}[/] yourself."
        )
    done = subprocess.run([opener, url], capture_output=True, text=True)
    if done.returncode:
        raise ClaudeError("Couldn't open the Claude desktop app.", hint=NOT_INSTALLED_HINT)
