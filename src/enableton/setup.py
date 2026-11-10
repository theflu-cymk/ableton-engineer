"""Install the Remote Script where Live will find it.

Idempotent by construction: running it twice leaves one installed copy, because setup is
something people run again after every update. It never deletes anything — replacing an existing
install needs ``force``, and a dry run is available so the user can see what would change.
"""

from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

SCRIPT_PACKAGE = "Enableton"


class InstallError(Exception):
    pass


USER_LIBRARY_ENV = "ENABLETON_USER_LIBRARY"


def find_user_library() -> Path:
    r"""Locate Live's User Library.

    ``Documents\Ableton`` is only the default. A redirected Documents folder (OneDrive is
    common) moves it, and installing into the wrong place fails *silently*: the files are
    written and Live never looks there. So: explicit override, then the standard paths,
    then a shallow search of OneDrive.
    """
    override = os.environ.get(USER_LIBRARY_ENV)
    if override:
        return Path(override)

    home = Path(os.environ.get("USERPROFILE") or Path.home())
    candidates = [
        home / "Documents" / "Ableton" / "User Library",
        home / "Music" / "Ableton" / "User Library",
    ]
    candidates += [Path(p) for p in sorted(glob.glob(
        str(home / "OneDrive" / "**" / "Ableton" / "User Library"), recursive=True))]
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[0]


def default_target() -> Path:
    """Where the Remote Script goes. The User Library survives Live updates."""
    return find_user_library() / "Remote Scripts" / SCRIPT_PACKAGE


def default_source() -> Path:
    """The script shipped in this repository."""
    override = os.environ.get("ENABLETON_SCRIPT_SRC")
    if override:
        return Path(override)
    candidate = Path(__file__).resolve().parents[2] / "remote_script" / SCRIPT_PACKAGE
    if not candidate.is_dir():
        raise InstallError(
            "can't find the Remote Script to install (looked in %s). "
            "Set ENABLETON_SCRIPT_SRC to the folder that contains %s."
            % (candidate, SCRIPT_PACKAGE)
        )
    return candidate


@dataclass
class InstallResult:
    target: Path
    files: List[str] = field(default_factory=list)
    dry_run: bool = False
    created: bool = False
    already_present: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.files)


def _script_files(source: Path) -> List[Path]:
    files = []
    for path in sorted(source.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        files.append(path)
    if not files:
        raise InstallError("no .py files found in %s" % source)
    return files


def install(
    target: Optional[Path] = None,
    source: Optional[Path] = None,
    force: bool = False,
    dry_run: bool = False,
) -> InstallResult:
    target = Path(target) if target else default_target()
    source = Path(source) if source else default_source()

    if not source.is_dir():
        raise InstallError("source %s is not a directory" % source)

    files = _script_files(source)
    exists = target.exists()
    if exists and not force:
        return InstallResult(target=target, dry_run=dry_run, already_present=True)

    # A dry run must not create anything, not even the folder.
    created = not exists
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)

    written = []
    for path in files:
        relative = path.relative_to(source)
        if not dry_run:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(path), str(destination))
        written.append(str(relative).replace(os.sep, "/"))

    return InstallResult(target=target, files=written, dry_run=dry_run, created=created)


def instructions() -> List[str]:
    return [
        "In Live: Preferences > Link, Tempo & MIDI",
        "Set an empty Control Surface slot to 'Enableton'",
        "The log should show Enableton listening on its port",
        "Run `enableton doctor` to confirm",
    ]
