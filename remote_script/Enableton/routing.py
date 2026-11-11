"""Routing labels, identifiers and option indexes.

Live 12.2.5's Python LOM does not expose a usable ``identifier`` for routing types or channels:
the labels can duplicate (two output types named ``Main``) and a channel can be nameless. The
option's position in Live's own vector is then the only exact selector, so the writer accepts an
index and the undo token carries the index as well as the human label.

Identity is not enough to find the current index: Live wraps LOM objects afresh on every access.
A routing type exposes ``category`` and ``attached_object``; a channel exposes ``layout``. Those
fields, plus the label and identifier, form a signature that can be matched against the vector.
If even the signature is ambiguous, the index is left unknown rather than guessed.
"""

from __future__ import annotations

from .errors import ScriptError


def attr(obj, name, default=None):
    try:
        return getattr(obj, name)
    except Exception:
        return default


def identifier(obj):
    if obj is None:
        return None
    value = attr(obj, "identifier", None)
    if isinstance(value, str):
        return value or None
    if value is not None and not isinstance(value, (dict, list)):
        return str(value)
    return None


def label(obj):
    if obj is None:
        return None
    for name in ("display_name", "name"):
        text = attr(obj, name, None)
        if isinstance(text, str) and text:
            return text
    return identifier(obj)


def ref(obj):
    return {"name": label(obj), "identifier": identifier(obj)}


def _plain(value):
    """Turn an enum-ish LOM value into a stable, JSON-safe scalar."""
    if value is None:
        return None
    name = attr(value, "name", None)
    if isinstance(name, str) and name:
        return name
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def _attached(obj):
    target = attr(obj, "attached_object", None)
    if target is None:
        return None
    pointer = attr(target, "_live_ptr", None)
    if pointer is not None:
        try:
            return int(pointer)
        except (TypeError, ValueError):
            return str(pointer)
    name = attr(target, "name", None)
    return name if isinstance(name, str) and name else None


def signature(obj):
    """The observable fields that distinguish two routing options with the same name."""
    if obj is None:
        return None
    return (
        label(obj),
        identifier(obj),
        _plain(attr(obj, "category", None)),
        _plain(attr(obj, "layout", None)),
        _attached(obj),
    )


def index_of(options, current):
    """Return the exact position of ``current`` in ``options``, or None when ambiguous."""
    if current is None:
        return None
    options = list(options)
    wanted = signature(current)
    matches = [index for index, option in enumerate(options) if signature(option) == wanted]
    if len(matches) == 1:
        return matches[0]

    # A missing signature field can still leave identity or equality to distinguish the entry.
    fallback = []
    for index, option in enumerate(options):
        try:
            if option is current or option == current:
                fallback.append(index)
        except Exception:
            continue
    if len(fallback) == 1:
        return fallback[0]
    return None


def choice(obj, index):
    """A teaching label for an option, always carrying its selectable position."""
    text = "%s [%d]" % (label(obj) or "?", index)
    identifier_text = identifier(obj)
    if identifier_text:
        text += " (%s)" % identifier_text
    return text


def pick(options, wanted, kind, index=None):
    """Resolve one option by exact index or by identifier/label."""
    options = list(options)
    if index is not None:
        if isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(options):
            raise ScriptError(
                "BAD_ARGS",
                "%s index must be an integer from 0 to %d" % (kind, len(options) - 1),
            )
        return options[index]

    if wanted is None:
        raise ScriptError("BAD_ARGS", "%s needs a name or an index" % (kind,))
    wanted = str(wanted)

    by_identifier = [option for option in options if identifier(option) == wanted]
    if len(by_identifier) == 1:
        return by_identifier[0]
    if len(by_identifier) > 1:
        raise ScriptError(
            "AMBIGUOUS_REF",
            "%d %s options share the identifier %r; use an index: %s"
            % (
                len(by_identifier),
                kind,
                wanted,
                ", ".join(choice(option, i) for i, option in enumerate(options)),
            ),
        )

    matches = [option for option in options if label(option) == wanted]
    if not matches:
        matches = [
            option for option in options
            if str(label(option) or "").casefold() == wanted.casefold()
            or str(identifier(option) or "").casefold() == wanted.casefold()
        ]
    if not matches:
        raise ScriptError(
            "NOT_FOUND",
            "no %s named %r; available: %s"
            % (
                kind,
                wanted,
                ", ".join(choice(option, i) for i, option in enumerate(options)),
            ),
        )
    if len(matches) > 1:
        raise ScriptError(
            "AMBIGUOUS_REF",
            "%d %s options are named %r; use an index: %s"
            % (
                len(matches),
                kind,
                wanted,
                ", ".join(choice(option, i) for i, option in enumerate(options)),
            ),
        )
    return matches[0]
