"""Update check against GitHub Releases, and in-place upgrade via the Inno Setup installer.

The check is one unauthenticated GET to the GitHub API. An update downloads
Capption-Setup-<ver>.exe to the temp folder and runs it silently; the installer reuses the
previous install folder, keeps models/settings, and relaunches Capption (/launch=1).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import __version__

log = logging.getLogger(__name__)

REPO = "tomwright0/capption"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
INSTALLER_RE = re.compile(r"^Capption-Setup-.*\.exe$", re.IGNORECASE)
_USER_AGENT = f"Capption/{__version__}"


class UpdateCancelled(Exception):
    pass


@dataclass(frozen=True)
class Release:
    version: tuple[int, ...]
    tag: str
    page_url: str
    installer_url: str | None
    installer_size: int


def parse_version(text: str) -> tuple[int, ...]:
    """"v1.2.3" / "1.2" -> (1, 2, 3) / (1, 2, 0). Pre-release suffixes are ignored."""
    m = re.match(r"^\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", text)
    if not m:
        raise ValueError(f"Not a version: {text!r}")
    return tuple(int(g or 0) for g in m.groups())


def parse_release(data: dict) -> Release:
    asset = next((a for a in data.get("assets", []) if INSTALLER_RE.match(a.get("name", ""))), None)
    return Release(
        version=parse_version(data["tag_name"]),
        tag=data["tag_name"],
        page_url=data.get("html_url") or RELEASES_PAGE,
        installer_url=asset["browser_download_url"] if asset else None,
        installer_size=int(asset.get("size", 0)) if asset else 0,
    )


def latest_release(timeout: float = 10.0) -> Release:
    url = os.environ.get("CAPPTION_UPDATE_URL", LATEST_URL)  # tests point this at a local server
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return parse_release(json.load(resp))


def newer_release(current: str = __version__) -> Release | None:
    """The latest release if it is newer than ``current``; None if up to date."""
    release = latest_release()
    return release if release.version > parse_version(current) else None


def can_self_update() -> bool:
    """Only an installer-made install can upgrade itself (portable zips just get a link)."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return False
    return (Path(sys.executable).parent / "unins000.exe").is_file()


def download_installer(
    release: Release,
    on_progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    if not release.installer_url:
        raise RuntimeError("This release has no installer")
    dest = Path(tempfile.gettempdir()) / f"Capption-Setup-{release.tag.lstrip('v')}.exe"
    partial = dest.with_suffix(".part")
    req = urllib.request.Request(release.installer_url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp, open(partial, "wb") as out:
        total = int(resp.headers.get("Content-Length") or release.installer_size or 0)
        done = 0
        while chunk := resp.read(1 << 20):
            if cancel is not None and cancel.is_set():
                out.close()
                partial.unlink(missing_ok=True)
                raise UpdateCancelled()
            out.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total)
    partial.replace(dest)
    return dest


def run_installer(path: Path) -> None:
    """Start the installer detached; the caller should quit right after so files aren't locked."""
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [str(path), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS", "/launch=1"],
        creationflags=flags,
        close_fds=True,
    )
    log.info("Started installer %s", path)
