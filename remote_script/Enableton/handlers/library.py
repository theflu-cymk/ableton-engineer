"""Read-only browser access.

The browser tree is the only way to see what the user owns without loading any of it. Reads walk
Live's main thread, so both commands are paged and bounded: a category holding thousands of samples
must not stall the Set for a listing nobody asked for.

A category that cannot be read reports its reason. ``available: false`` with a reason is the honest
answer; an empty list would claim the user's library is empty.
"""

from __future__ import annotations

from ..dispatch import check_args, command
from ..errors import ScriptError

CATEGORIES = (
    "sounds", "drums", "instruments", "audio_effects", "midi_effects",
    "samples", "audio_clips", "plugins", "packs", "user_library",
    "max_for_live", "current_project",
)

MAX_LIMIT = 500


def _attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def _browser(song):
    browser = _attr(song, "browser", None)
    if browser is not None:
        return browser
    try:
        import Live

        app = Live.Application.get_application()
        browser = _attr(app, "browser", None)
    except Exception as exc:  # noqa: BLE001 - the reason is the answer
        raise ScriptError(
            "UNSUPPORTED", "this Live build has no readable browser: %s" % (exc,)
        )
    if browser is None:
        raise ScriptError("UNSUPPORTED", "this Live build has no readable browser")
    return browser


def _item_row(item):
    return {
        "name": str(_attr(item, "name", "") or ""),
        "is_folder": bool(_attr(item, "is_folder", False)),
        "is_loadable": bool(_attr(item, "is_loadable", False)),
        "uri": str(_attr(item, "uri", "") or ""),
    }


def _children(item):
    kids = _attr(item, "children", None)
    if kids is None:
        raise ScriptError(
            "UNSUPPORTED",
            "browser item %r has no readable children" % (str(_attr(item, "name", "") or ""),),
        )
    return list(kids)


@command("library.folders")
def folders(args, song):
    check_args(args, allowed=())
    browser = _browser(song)
    items, missing = [], []
    for name in CATEGORIES:
        try:
            item = getattr(browser, name)
        except Exception as exc:  # noqa: BLE001 - the reason is the answer
            missing.append({"name": name, "reason": str(exc)})
            continue
        if item is None:
            missing.append({"name": name, "reason": "this Live build does not expose it"})
            continue
        row = _item_row(item)
        row["category"] = name
        try:
            row["child_count"] = len(_children(item))
        except ScriptError as exc:
            row["child_count"] = None
            row["reason"] = str(exc)
        items.append(row)
    return {"available": True, "categories": items, "missing": missing}


@command("library.browse")
def browse(args, song):
    check_args(args, allowed=("path", "offset", "limit"))
    path = args.get("path")
    if not isinstance(path, str) or not path.strip("/ "):
        raise ScriptError(
            "BAD_ARGS", "path must be a non-empty string such as 'user_library/Drums'"
        )
    offset = args.get("offset", 0)
    limit = args.get("limit", 100)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ScriptError("BAD_ARGS", "offset must be a non-negative integer")
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > MAX_LIMIT:
        raise ScriptError("BAD_ARGS", "limit must be an integer from 1 to %d" % MAX_LIMIT)

    browser = _browser(song)
    steps = [step for step in path.replace("\\", "/").split("/") if step]
    if not steps:
        raise ScriptError("BAD_ARGS", "path must name at least one browser folder")

    current = None
    walked = []
    for step in steps:
        if current is None:
            matches = []
            for name in CATEGORIES:
                try:
                    item = getattr(browser, name)
                except Exception:
                    continue
                if item is None:
                    continue
                if name == step or str(_attr(item, "name", "") or "") == step:
                    matches.append(item)
            if not matches:
                raise ScriptError("NOT_FOUND", "no browser category named %r" % (step,))
            current = matches[0]
        else:
            matches = [
                child for child in _children(current)
                if str(_attr(child, "name", "") or "") == step
            ]
            if not matches:
                raise ScriptError(
                    "NOT_FOUND", "no browser item named %r under %r"
                    % (step, str(_attr(current, "name", "") or "")),
                )
            if len(matches) > 1:
                raise ScriptError(
                    "AMBIGUOUS_REF", "%d browser items are named %r" % (len(matches), step)
                )
            current = matches[0]
        walked.append(str(_attr(current, "name", "") or step))

    children = _children(current)
    page = children[offset:offset + limit]
    rows = []
    for child in page:
        try:
            rows.append(_item_row(child))
        except Exception as exc:  # noqa: BLE001 - one bad item must not hide the rest
            rows.append({
                "name": "", "is_folder": False, "is_loadable": False, "uri": "",
                "reason": str(exc),
            })
    next_offset = offset + len(page)
    return {
        "path": "/".join(walked),
        "name": str(_attr(current, "name", "") or ""),
        "children": rows,
        "total": len(children),
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset if next_offset < len(children) else None,
    }
