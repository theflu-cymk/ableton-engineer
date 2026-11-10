"""Undo the last applied transaction by replaying the tools' own restore tokens.

Live's undo stack is linear and cannot unwind a plan, so Enableton keeps its own record: the tool
name, its script command and the undo token it returned. Each token is replayed through the same
tool's ``restore`` argument, in reverse order. The record is consumed whether or not every restore
succeeds, because replaying half an undo a second time is not safe; failures are reported instead.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..manifest import Tool
from ..protocol.codes import LiveError
from .transactions import TransactionStore, TransactionStoreError


def _only(args: Dict[str, Any], allowed: tuple) -> None:
    unknown = sorted(set(args) - set(allowed))
    if unknown:
        raise LiveError("BAD_ARGS", "unknown argument(s): %s" % ", ".join(unknown))


def undo_transaction(
    adapter: Any,
    cache: Any,
    args: Optional[Dict[str, Any]] = None,
    catalogue: Optional[Dict[str, Tool]] = None,
    store: Optional[TransactionStore] = None,
) -> Dict[str, Any]:
    """Restore the last transaction, with one honest result per replayed tool."""
    args = dict(args or {})
    _only(args, ("scope",))
    scope = args.get("scope", "last")
    if scope != "last":
        raise LiveError(
            "BAD_ARGS", "scope must be 'last'; this build keeps only the last transaction"
        )

    store = store or TransactionStore()
    try:
        record = store.get()
    except TransactionStoreError as exc:
        raise LiveError("PRECONDITION_FAILED", str(exc)) from exc

    data = cache.get()
    current_set = (data.get("song") or {}).get("file_path")
    recorded_set = record.get("set_path")
    if recorded_set and current_set and recorded_set != current_set:
        raise LiveError(
            "PRECONDITION_FAILED",
            "the last transaction was applied to %s; this Set is %s, so it was not undone"
            % (recorded_set, current_set),
        )

    if catalogue is None:
        from ..manifest import load_manifest

        catalogue = load_manifest()

    steps: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    restored = 0
    for entry in reversed(record["entries"]):
        name = entry["tool"]
        tool = catalogue.get(name)
        if tool is None or not tool.cmd:
            failures.append({"tool": name, "error": "no script command for this tool"})
            continue
        try:
            result = adapter.call(
                tool.cmd,
                {"restore": list(entry["undo"]), "dry_run": False},
                timeout_ms=tool.timeout_ms,
            )
        except Exception as exc:  # noqa: BLE001 - the restore failure is the answer
            failures.append({
                "tool": name,
                "error": {
                    "code": getattr(exc, "code", None),
                    "message": str(exc),
                },
            })
            continue
        steps.append({"tool": name, "result": result})
        if isinstance(result, dict):
            missing = result.get("missing")
            if isinstance(missing, list) and missing:
                failures.append({"tool": name, "error": {"message": "some entries were missing"}})
                continue
            count = result.get("restored")
            if isinstance(count, int):
                restored += count

    try:
        store.clear()
    except TransactionStoreError as exc:
        failures.append({"tool": "transaction", "error": {"message": str(exc)}})

    cache.invalidate()
    return {
        "scope": "last",
        "set_path": recorded_set,
        "ok": not failures,
        "restored": restored,
        "steps": steps,
        "failures": failures,
    }


__all__ = ["undo_transaction"]
