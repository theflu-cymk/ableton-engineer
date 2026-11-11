"""Install the Remote Script where Live will find it.

Idempotent by construction: running it twice leaves one installed copy, because setup is something
people run again after every update. Replacing an existing install needs ``force``, and a forced
install is *clean*: anything the new build no longer ships — a renamed module, a stale
``__pycache__`` — is removed, so an old file cannot outlive an upgrade. A dry run reports the same
changes without touching disk.
"""

from __future__ import annotations

import glob
import hashlib
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

SCRIPT_PACKAGE = "Enableton"

_VERSION_RE = re.compile(r'^SCRIPT_VERSION\s*=\s*"([^"]+)"', re.MULTILINE)


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


def script_version(source: Optional[Path] = None) -> Optional[str]:
    """The version the shipped Remote Script declares.

    This is the version that matters: ``pyproject.toml`` sits at 0.1.0 and has never tracked the
    script, so reading it would put two different numbers on one screen. Returns None rather than
    raising, because a missing script is the installer's problem, not the menu's.
    """
    try:
        root = Path(source) if source else default_source()
        text = (root / "server.py").read_text(encoding="utf-8")
    except (InstallError, OSError):
        return None
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


@dataclass
class InstallResult:
    target: Path
    files: List[str] = field(default_factory=list)
    dry_run: bool = False
    created: bool = False
    already_present: bool = False
    removed: List[str] = field(default_factory=list)

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


def digest(source: Optional[Path] = None) -> str:
    """Content hash of a script package, matching the Remote Script's ``build_digest``.

    Two implementations exist because they run in different interpreters — the server cannot reach
    Live's Python, and the script cannot import ``enableton``. ``tests/test_build_digest.py`` asserts
    they agree, so ``doctor`` can compare what Live loaded with what this repo ships.
    """
    root = Path(source) if source else default_source()
    entries = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        relative = str(path.relative_to(root)).replace(os.sep, "/")
        entries.append("%s:%s" % (relative, hashlib.sha256(path.read_bytes()).hexdigest()))
    return hashlib.sha256("\n".join(sorted(entries)).encode("utf-8")).hexdigest()[:12]


def _prune(target: Path, source: Path, dry_run: bool) -> List[str]:
    """Remove what this build no longer ships.

    Copying over the top was fine only while the file set never shrank: the first renamed or deleted
    module would have stayed behind in the User Library, and Live could still have imported it.
    """
    keep = set()
    for path in _script_files(source):
        keep.add(str(path.relative_to(source)).replace(os.sep, "/"))

    removed = []
    for path in sorted(target.rglob("*.py")):
        relative = str(path.relative_to(target)).replace(os.sep, "/")
        if relative in keep:
            continue
        removed.append(relative)
        if not dry_run:
            path.unlink()
    for stale in sorted(target.rglob("*.pyc")):
        removed.append(str(stale.relative_to(target)).replace(os.sep, "/"))
        if not dry_run:
            stale.unlink()
    for cache in sorted(target.rglob("__pycache__")):
        if not dry_run:
            shutil.rmtree(str(cache), ignore_errors=True)
    return removed


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

    removed = _prune(target, source, dry_run) if exists else []

    return InstallResult(target=target, files=written, dry_run=dry_run, created=created,
                         removed=removed)


def instructions() -> List[str]:
    return [
        "In Live: Preferences > Link, Tempo & MIDI",
        "Set an empty Control Surface slot to 'Enableton'",
        "The log should show Enableton listening on its port",
        "Run `enableton doctor` to confirm",
    ]
