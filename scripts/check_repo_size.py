"""Fail when a tracked file is large enough to bloat a clone."""

from __future__ import annotations

import pathlib
import subprocess
import sys

LIMIT_BYTES = 5 * 1024 * 1024


def tracked_files() -> list[pathlib.Path]:
    result = subprocess.run(["git", "ls-files", "-z"], capture_output=True, check=True)
    entries = result.stdout.split(b"\0")
    return [pathlib.Path(entry.decode("utf-8")) for entry in entries if entry]


def main() -> int:
    oversized = [
        f"{path} ({path.stat().st_size / 1048576:.1f} MB)"
        for path in tracked_files()
        if path.is_file() and path.stat().st_size > LIMIT_BYTES
    ]
    if not oversized:
        print("No tracked file over 5 MB.")
        return 0
    print("Tracked files over 5 MB - move them to scratch space or `git rm --cached` them:")
    for row in oversized:
        print(f"  {row}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
