"""The producer-facing local panel.

The panel is deliberately a thin surface over the same bridge and tool catalogue the CLI and MCP
server use. It does not speak the socket protocol itself and it does not have a second write path:
a preview is a dry run, and an apply replays the exact preview arguments through ``run_tool``.
Preview tokens live only in this process, are single-use and expire, so the browser cannot apply a
change it was not shown.

Only ``http.server`` and ``json`` are used. The default bind is ``127.0.0.1``; there is no
telemetry, CDN asset or remote font.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import unquote, urlsplit

from .manifest import load_manifest
from .plans import PlanStore, PlanStoreError, TransactionStore, TransactionStoreError
from .protocol.client import DEFAULT_PORT, LiveClient
from .protocol.codes import LiveError
from .recipe_store import RecipeStore, RecipeStoreError
from .recipe_tools import default_store, show_recipe
from .setup import default_source, digest
from .state.snapshot import SnapshotCache
from .tools import run_tool

PANEL_HOST = "127.0.0.1"
DEFAULT_PANEL_PORT = 9879
PREVIEW_TTL_S = 600.0
MAX_BODY = 1_000_000
ASSET_ROOT = Path(__file__).with_name("panel_assets")

_LOGGER = logging.getLogger("enableton.panel")

_TRANSPORT_CODES = frozenset({"DISCONNECTED", "TIMEOUT"})
_CONFLICT_CODES = frozenset({"LIVE_BUSY", "PRECONDITION_FAILED", "ALREADY_APPLIED"})
_TAKE_RE = re.compile(r"^(?P<base>.+?)\s+take\s+(?P<take>\d+)$", re.IGNORECASE)


class PanelError(Exception):
    """An error the panel can render as its JSON envelope."""

    def __init__(self, code: str, message: str, status: int = 400,
                 detail: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.detail = detail or {}


@dataclass
class Preview:
    token: str
    tool: str
    args: Dict[str, Any]
    result: Dict[str, Any]
    created: float
    expires: float


@dataclass
class Cue:
    """A compiled recipe plan the producer has seen and may run once."""

    token: str
    recipe_id: str
    plan_id: str
    digest: str
    created: float
    expires: float


class PanelBridge:
    """Own the panel's one Live client, reconnecting once when the socket disappears.

    ``LiveClient`` is itself the transport layer; this wrapper only supplies the lazy connect and
    the retry that a long-lived HTTP process needs. A failed poll therefore replaces the dead
    socket and retries rather than leaving the UI stuck on a stale failure.
    """

    features = frozenset()

    def __init__(self, host: str = PANEL_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self._client: Optional[LiveClient] = None
        self._lock = threading.RLock()

    def _connect(self) -> LiveClient:
        if self._client is None or not self._client.connected:
            if self._client is not None:
                self._client.close()
            self._client = LiveClient(host=self.host, port=self.port)
            self._client.connect(timeout=1.5)
        return self._client

    def call(self, cmd: str, args: Optional[Dict[str, Any]] = None,
             timeout_ms: Optional[int] = None) -> Dict[str, Any]:
        with self._lock:
            # Deliberately no automatic retry. A lost reply may mean Live executed the command,
            # especially for a write; reconnecting is left to the next panel poll or click.
            return self._connect().call(cmd, args or {}, timeout_ms=timeout_ms)

    def describe(self) -> Dict[str, Any]:
        return {"backend": "live", "host": self.host, "port": self.port}

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.close()


def _default_status(host: str, port: int) -> Dict[str, Any]:
    # Imported lazily so the CLI can import the panel without a module cycle.
    from .cli import doctor

    return doctor(host, port)


def _expected_digest() -> Optional[str]:
    """Read the shipped build once; a 2 s status poll must not rehash the script each time."""
    try:
        return digest(default_source())
    except Exception:  # noqa: BLE001 - an installed wheel need not ship the source tree
        return None


def _as_error(exc: BaseException, default_status: int = 400) -> PanelError:
    if isinstance(exc, PanelError):
        return exc
    if isinstance(exc, LiveError):
        status = 503 if exc.code in _TRANSPORT_CODES else (
            409 if exc.code in _CONFLICT_CODES else default_status
        )
        return PanelError(exc.code, exc.message, status, exc.detail)
    if isinstance(exc, OSError):
        return PanelError(
            "DISCONNECTED",
            "Live is not reachable on this computer: %s" % exc,
            503,
        )
    return PanelError("INTERNAL", str(exc) or type(exc).__name__, 500)


def _device_names(row: Dict[str, Any]) -> list:
    names = []
    for device in row.get("devices") or []:
        name = device.get("name") if isinstance(device, dict) else None
        if name:
            names.append(str(name))
    return names


def _plan_digest(plan: Dict[str, Any]) -> str:
    payload = {
        "plan_id": plan.get("plan_id"),
        "steps": plan.get("steps") or [],
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _hints() -> list:
    return [
        "Open Ableton Live and open a Set.",
        "In Preferences > Link, Tempo & MIDI, choose Enableton as a Control Surface.",
        "Run `enableton doctor` in the same terminal for the full connection report.",
    ]


class PanelService:
    """The panel's request-independent application layer."""

    def __init__(
        self,
        adapter: Any = None,
        status_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        catalogue: Optional[Dict[str, Any]] = None,
        cache: Optional[SnapshotCache] = None,
        host: str = PANEL_HOST,
        bridge_port: int = DEFAULT_PORT,
        preview_ttl: float = PREVIEW_TTL_S,
        backup_root: Optional[str] = None,
        recipe_store: Optional[RecipeStore] = None,
        plan_root: Optional[str] = None,
        transaction_root: Optional[str] = None,
    ):
        self.host = host
        self.bridge_port = bridge_port
        self.adapter = adapter if adapter is not None else PanelBridge(host, bridge_port)
        self.catalogue = catalogue or load_manifest()
        self.cache = cache or SnapshotCache(self.adapter)
        self._status_provider = status_provider or (
            lambda: _default_status(self.host, self.bridge_port)
        )
        self._preview_ttl = preview_ttl
        self._backup_root = backup_root
        self._recipe_store = recipe_store
        self._plan_root = plan_root
        self._transaction_root = transaction_root
        self._expected_build = _expected_digest()
        self._previews: Dict[str, Preview] = {}
        self._cues: Dict[str, Cue] = {}
        self._lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        with self._lock:
            self._previews.clear()
            self._cues.clear()
        close = getattr(self.adapter, "close", None)
        if callable(close):
            close()

    # -- reads -------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        try:
            with self._lock:
                report = dict(self._status_provider())
        except OSError as exc:
            raise _as_error(exc)
        except Exception as exc:  # noqa: BLE001 - the report is the answer
            raise _as_error(exc)

        expected = self._expected_build
        report["expected_build"] = expected
        if report.get("build") and expected:
            report["stale"] = report["build"] != expected
        else:
            report["stale"] = None
        report["panel"] = {
            "host": self.host,
            "bridge_port": self.bridge_port,
            "loopback": True,
        }

        if not report.get("connected"):
            reason = report.get("error") or "the bridge did not answer"
            raise PanelError(
                report.get("code") or "DISCONNECTED",
                "Live is not connected. %s" % reason,
                503,
                {"status": report, "hints": _hints()},
            )
        return report

    def session(self) -> Dict[str, Any]:
        try:
            with self._lock:
                return run_tool(
                    "session_brief",
                    {"include_tracks": True},
                    adapter=self.adapter,
                    catalogue=self.catalogue,
                    cache=self.cache,
                )
        except Exception as exc:  # noqa: BLE001 - translated to the error envelope
            raise _as_error(exc)

    def tracks(self) -> Dict[str, Any]:
        data = self._snapshot()
        rows = list(data.get("tracks") or [])
        main_count = sum(1 for row in rows if row.get("kind") != "return")
        tracks = []
        for row in rows:
            kind = str(row.get("kind") or "track")
            index = row.get("index")
            if kind == "return":
                restore_kind = "return"
                restore_index = int(index) - main_count if isinstance(index, int) else None
            else:
                restore_kind = "track"
                restore_index = index
            tracks.append({
                "index": index,
                "name": row.get("name") or "",
                "kind": kind,
                "group": row.get("group"),
                "volume": row.get("volume"),
                "volume_str": row.get("volume_str"),
                "pan": row.get("pan"),
                "mute": bool(row.get("mute")),
                "solo": bool(row.get("solo")),
                "arm": bool(row.get("arm")),
                "device_count": int(row.get("device_count") or 0),
                "devices": _device_names(row),
                "restore_kind": restore_kind,
                "restore_index": restore_index,
            })
        counts = dict(data.get("counts") or {})
        counts["main_tracks"] = main_count
        counts["returns"] = sum(1 for row in rows if row.get("kind") == "return")
        return {
            "song": data.get("song") or {},
            "tracks": tracks,
            "counts": counts,
            "master_track": data.get("master_track") or {},
            "captured": data.get("captured") or {},
        }

    def takes(self) -> Dict[str, Any]:
        data = self._snapshot()
        groups: Dict[str, Dict[str, Any]] = {}
        for row in data.get("tracks") or []:
            name = str(row.get("name") or "")
            match = _TAKE_RE.match(name)
            if not match:
                continue
            base = match.group("base").strip()
            group = groups.setdefault(base, {"source": base, "takes": []})
            volume = row.get("volume")
            try:
                active = volume is not None and float(volume) > 0.001
            except (TypeError, ValueError):
                active = False
            group["takes"].append({
                "index": row.get("index"),
                "name": name,
                "take": int(match.group("take")),
                "volume": volume,
                "mute": bool(row.get("mute")),
                "solo": bool(row.get("solo")),
                "active": active and not bool(row.get("mute")),
            })
        ordered = []
        for base in sorted(groups):
            group = groups[base]
            group["takes"].sort(key=lambda item: item["take"])
            group["count"] = len(group["takes"])
            ordered.append(group)
        return {
            "groups": ordered,
            "count": len(ordered),
            "read_only": False,
            "controls": {"select": True, "discard_preview": True, "discard_apply": False},
        }

    # -- recipes -----------------------------------------------------------
    def _store(self) -> RecipeStore:
        return self._recipe_store or default_store()

    def _plan_store(self) -> PlanStore:
        return PlanStore(root=self._plan_root)

    def _transactions(self) -> TransactionStore:
        return TransactionStore(root=self._transaction_root)

    def recipes(self) -> Dict[str, Any]:
        """Read the recipe catalog without requiring Live."""
        try:
            with self._lock:
                rows = self._store().catalog()
        except RecipeStoreError as exc:
            raise PanelError("BAD_ARGS", str(exc), 400)
        return {"recipes": rows, "count": len(rows)}

    def recipe(self, recipe_id: Any) -> Dict[str, Any]:
        if not isinstance(recipe_id, str) or not recipe_id:
            raise PanelError("BAD_ARGS", "recipe id must be a non-empty string", 400)
        try:
            with self._lock:
                rows = self._store().catalog()
        except RecipeStoreError as exc:
            raise PanelError("BAD_ARGS", str(exc), 400)
        summary = next((row for row in rows if row.get("id") == recipe_id), None)
        if summary is None:
            raise PanelError("NOT_FOUND", "No recipe with id %r." % recipe_id, 404)
        if summary.get("status") == "invalid":
            raise PanelError(
                "BAD_ARGS",
                summary.get("error") or "This recipe file is not valid.",
                400,
                {"recipe": summary},
            )
        try:
            with self._lock:
                shown = show_recipe({"id": recipe_id}, store=self._store())
        except Exception as exc:  # noqa: BLE001 - translated to the panel envelope
            raise _as_error(exc)
        return {"summary": summary, **shown}

    def recipe_targets(self) -> Dict[str, Any]:
        """MIDI clips that a rhythm recipe can render into."""
        data = self._snapshot()
        tracks = []
        for row in data.get("tracks") or []:
            if not isinstance(row, dict) or row.get("kind") != "midi":
                continue
            clips = []
            for clip in row.get("arrangement") or []:
                if not isinstance(clip, dict):
                    continue
                name = clip.get("name")
                if not isinstance(name, str) or not name:
                    continue
                clips.append({
                    "name": name,
                    "location": "arrangement",
                    "start": clip.get("start"),
                    "length": clip.get("length"),
                })
            session = row.get("session") or {}
            for clip in session.get("clips") or []:
                if not isinstance(clip, dict):
                    continue
                name = clip.get("name")
                if not isinstance(name, str) or not name:
                    continue
                clips.append({
                    "name": name,
                    "location": "session",
                    "slot": clip.get("slot"),
                })
            if clips:
                tracks.append({
                    "index": row.get("index"),
                    "name": row.get("name") or "",
                    "clips": clips,
                })
        return {"tracks": tracks, "count": len(tracks)}

    def cue_recipe(self, payload: Any) -> Dict[str, Any]:
        """Compile a recipe into a stored plan and offer one exact Run token."""
        if not isinstance(payload, dict):
            raise PanelError("BAD_ARGS", "expected a JSON object", 400)
        recipe_id = payload.get("id")
        if not isinstance(recipe_id, str) or not recipe_id:
            raise PanelError("BAD_ARGS", "id must be a non-empty recipe id", 400)
        target = payload.get("target")
        if target is not None and not isinstance(target, dict):
            raise PanelError("BAD_ARGS", "target must be an object", 400)
        bindings = payload.get("track_bindings") or {}
        if not isinstance(bindings, dict):
            raise PanelError("BAD_ARGS", "track_bindings must be an object", 400)
        for key, value in bindings.items():
            if not isinstance(key, str) or not key or not isinstance(value, str) or not value:
                raise PanelError(
                    "BAD_ARGS", "track_bindings must map non-empty names to non-empty names", 400,
                )
        confirmed = payload.get("manual_confirmed", False)
        if not isinstance(confirmed, bool):
            raise PanelError("BAD_ARGS", "manual_confirmed must be a boolean", 400)

        args: Dict[str, Any] = {"id": recipe_id}
        if target is not None:
            args["target"] = target
        if confirmed:
            args["manual_confirmed"] = True
        if bindings:
            args["track_bindings"] = bindings
        try:
            with self._lock:
                result = run_tool(
                    "recipe_apply",
                    args,
                    adapter=self.adapter,
                    catalogue=self.catalogue,
                    cache=self.cache,
                    plan_root=self._plan_root,
                    recipe_store=self._store(),
                )
        except Exception as exc:  # noqa: BLE001
            raise _as_error(exc)
        if not isinstance(result, dict):
            raise PanelError("INTERNAL", "The recipe compiler returned no result.", 500)

        status = result.get("status")
        base = {
            "recipe_id": recipe_id,
            "recipe_name": result.get("recipe_name") or recipe_id,
            "status": status,
            "plan_id": result.get("plan_id"),
            "token": None,
            "reason": result.get("reason"),
            "manual": result.get("manual") or [],
            "expected": result.get("expected") or {},
            "render": result.get("render"),
            "warnings": result.get("warnings") or [],
        }
        if status != "plan_ready":
            base["can_confirm"] = status == "manual_required"
            return base

        plan_id = result.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id:
            raise PanelError("INTERNAL", "The recipe compiler produced no plan id.", 500)
        try:
            plan = self._plan_store().get(plan_id)
        except PlanStoreError as exc:
            raise PanelError("PRECONDITION_FAILED", str(exc), 409)
        digest = _plan_digest(plan)
        token = secrets.token_urlsafe(24)
        now = time.monotonic()
        cue = Cue(
            token=token,
            recipe_id=recipe_id,
            plan_id=plan_id,
            digest=digest,
            created=now,
            expires=now + self._preview_ttl,
        )
        with self._lock:
            for old_token, old in list(self._cues.items()):
                if old.expires < now:
                    self._cues.pop(old_token, None)
            self._cues[token] = cue
        return {
            **base,
            "status": "ready",
            "plan_id": plan_id,
            "token": token,
            "expires_in_s": int(self._preview_ttl),
            "intent": plan.get("intent"),
            "steps": plan.get("steps") or [],
        }

    def run_cue(self, token: Any) -> Dict[str, Any]:
        """Run exactly the plan the producer was shown, once."""
        if not isinstance(token, str) or not token:
            raise PanelError("BAD_ARGS", "token must be a non-empty string", 400)
        with self._lock:
            cue = self._cues.pop(token, None)
        if cue is None:
            raise PanelError(
                "PREVIEW_NOT_FOUND",
                "That cue has already been run, discarded or expired. Stage the recipe again.",
                409,
            )
        if time.monotonic() > cue.expires:
            raise PanelError(
                "PREVIEW_EXPIRED",
                "That cue expired. Stage the recipe again before running it.",
                409,
            )
        try:
            plan = self._plan_store().get(cue.plan_id)
        except PlanStoreError as exc:
            raise PanelError("PRECONDITION_FAILED", str(exc), 409)
        if _plan_digest(plan) != cue.digest:
            raise PanelError(
                "PRECONDITION_FAILED",
                "The stored plan changed after it was shown; nothing was run. Stage it again.",
                409,
            )
        try:
            with self._lock:
                result = run_tool(
                    "ableton_plan_apply",
                    {"plan_id": cue.plan_id},
                    adapter=self.adapter,
                    catalogue=self.catalogue,
                    cache=self.cache,
                    backup_root=self._backup_root,
                    plan_root=self._plan_root,
                    transaction_root=self._transaction_root,
                )
        except Exception as exc:  # noqa: BLE001
            raise _as_error(exc)
        if not isinstance(result, dict):
            raise PanelError("INTERNAL", "The plan executor returned no result.", 500)
        if not result.get("applied"):
            error = result.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else None
            raise PanelError(
                "APPLY_FAILED",
                message or "Live refused the plan. Nothing was left half-applied.",
                409,
                {"result": result},
            )
        undo_available = False
        try:
            self._transactions().get()
            undo_available = True
        except TransactionStoreError:
            pass
        return {
            "applied": True,
            "plan_id": cue.plan_id,
            "recipe_id": cue.recipe_id,
            "result": result,
            "undo_available": undo_available,
        }

    def discard_cue(self, token: Any) -> Dict[str, Any]:
        """Delete a staged plan without touching Live."""
        if not isinstance(token, str) or not token:
            raise PanelError("BAD_ARGS", "token must be a non-empty string", 400)
        with self._lock:
            cue = self._cues.pop(token, None)
        if cue is None:
            raise PanelError(
                "PREVIEW_NOT_FOUND",
                "That cue is already gone.",
                409,
            )
        try:
            result = run_tool(
                "ableton_plan_discard",
                {"plan_id": cue.plan_id},
                adapter=self.adapter,
                catalogue=self.catalogue,
                cache=self.cache,
                plan_root=self._plan_root,
            )
        except Exception as exc:  # noqa: BLE001
            raise _as_error(exc)
        return {
            "discarded": bool(result.get("discarded")),
            "plan_id": cue.plan_id,
        }

    def undo(self) -> Dict[str, Any]:
        """Restore the last applied transaction; the panel only offers this after a Run."""
        try:
            with self._lock:
                return run_tool(
                    "ableton_undo",
                    {"scope": "last"},
                    adapter=self.adapter,
                    catalogue=self.catalogue,
                    cache=self.cache,
                    transaction_root=self._transaction_root,
                )
        except Exception as exc:  # noqa: BLE001
            raise _as_error(exc)

    # -- preview / apply ---------------------------------------------------
    def plan(self, tool_name: Any, args: Any) -> Dict[str, Any]:
        if not isinstance(tool_name, str) or not tool_name:
            raise PanelError("BAD_ARGS", "tool must be a non-empty string", 400)
        if not isinstance(args, dict):
            raise PanelError("BAD_ARGS", "args must be a JSON object", 400)
        tool = self.catalogue.get(tool_name)
        if tool is None:
            raise PanelError(
                "UNKNOWN_COMMAND",
                "Enableton has no tool %r. Run `enableton tools` to list the catalogue."
                % (tool_name,),
                400,
            )

        if not tool.writes:
            try:
                with self._lock:
                    result = run_tool(
                        tool_name, dict(args), adapter=self.adapter,
                        catalogue=self.catalogue, cache=self.cache,
                    )
            except Exception as exc:  # noqa: BLE001
                raise _as_error(exc)
            return {
                "tool": tool_name,
                "writes": False,
                "reversible": True,
                "can_apply": False,
                "token": None,
                "preview": result,
                "note": "This tool only reads the Set; there is nothing to apply.",
            }

        properties = tool.input.get("properties") or {}
        if "dry_run" not in properties:
            raise PanelError(
                "UNSUPPORTED",
                "This write has no dry-run mode, so the panel cannot show a safe preview of it.",
                400,
                {"tool": tool_name},
            )

        preview_args = dict(args)
        preview_args["dry_run"] = True
        try:
            with self._lock:
                preview = run_tool(
                    tool_name, preview_args, adapter=self.adapter,
                    catalogue=self.catalogue, cache=self.cache,
                    backup_root=self._backup_root,
                )
        except Exception as exc:  # noqa: BLE001
            raise _as_error(exc)
        if not isinstance(preview, dict) or preview.get("dry_run") is not True:
            raise PanelError(
                "PRECONDITION_FAILED",
                "The tool did not return a dry-run result; nothing can be applied from it.",
                409,
                {"tool": tool_name},
            )

        can_apply = bool(tool.reversible)
        token = None
        now = time.monotonic()
        if can_apply:
            token = secrets.token_urlsafe(24)
            apply_args = {key: value for key, value in args.items() if key != "dry_run"}
            with self._lock:
                for old_token, old in list(self._previews.items()):
                    if old.expires < now:
                        self._previews.pop(old_token, None)
                self._previews[token] = Preview(
                    token=token,
                    tool=tool_name,
                    args=apply_args,
                    result=preview,
                    created=now,
                    expires=now + self._preview_ttl,
                )
        note = (
            None if can_apply else
            "This tool cannot be undone, so the panel will not offer Apply. "
            "Use the CLI or MCP surface with the tool's own confirmation."
        )
        return {
            "tool": tool_name,
            "writes": True,
            "reversible": bool(tool.reversible),
            "can_apply": can_apply,
            "token": token,
            "preview": preview,
            "expires_in_s": int(self._preview_ttl) if token else None,
            "note": note,
        }

    def apply(self, token: Any) -> Dict[str, Any]:
        if not isinstance(token, str) or not token:
            raise PanelError("BAD_ARGS", "token must be a non-empty string", 400)
        with self._lock:
            preview = self._previews.pop(token, None)
        if preview is None:
            raise PanelError(
                "PREVIEW_NOT_FOUND",
                "That preview has already been applied, cancelled or expired. Preview the change again.",
                409,
            )
        if time.monotonic() > preview.expires:
            raise PanelError(
                "PREVIEW_EXPIRED",
                "That preview expired. Preview the change again before applying it.",
                409,
            )
        args = dict(preview.args)
        args["dry_run"] = False
        try:
            with self._lock:
                result = run_tool(
                    preview.tool, args, adapter=self.adapter,
                    catalogue=self.catalogue, cache=self.cache,
                    backup_root=self._backup_root,
                )
        except Exception as exc:  # noqa: BLE001
            raise _as_error(exc)
        undo = result.get("undo") if isinstance(result, dict) else None
        return {
            "tool": preview.tool,
            "applied": True,
            "result": result,
            "undo": undo,
            "scratch_copy": result.get("scratch_copy") if isinstance(result, dict) else None,
        }

    # -- internals ---------------------------------------------------------
    def _snapshot(self) -> Dict[str, Any]:
        try:
            with self._lock:
                data = self.cache.get()
        except Exception as exc:  # noqa: BLE001
            raise _as_error(exc)
        if not isinstance(data, dict):
            raise PanelError("INTERNAL", "Live returned a malformed snapshot.", 500)
        return data


class PanelHTTPServer(ThreadingHTTPServer):
    """A loopback HTTP server bound to one PanelService."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple, service: PanelService):
        self.service = service
        super().__init__(address, PanelRequestHandler)


class PanelRequestHandler(BaseHTTPRequestHandler):
    server_version = "EnabletonPanel/0.1"
    protocol_version = "HTTP/1.0"

    @property
    def service(self) -> PanelService:
        return self.server.service  # type: ignore[attr-defined]

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        try:
            if path == "/api/status":
                self._send_json(200, {"ok": True, "status": self.service.status()})
            elif path == "/api/session":
                self._send_json(200, {"ok": True, "session": self.service.session()})
            elif path == "/api/tracks":
                self._send_json(200, {"ok": True, **self.service.tracks()})
            elif path == "/api/takes":
                self._send_json(200, {"ok": True, **self.service.takes()})
            elif path == "/api/recipes":
                self._send_json(200, {"ok": True, **self.service.recipes()})
            elif path.startswith("/api/recipes/"):
                recipe_id = unquote(path[len("/api/recipes/"):])
                self._send_json(200, {"ok": True, **self.service.recipe(recipe_id)})
            elif path == "/api/recipe-targets":
                self._send_json(200, {"ok": True, **self.service.recipe_targets()})
            elif path == "/":
                self._send_asset("index.html", "text/html; charset=utf-8")
            elif path == "/panel.css":
                self._send_asset("panel.css", "text/css; charset=utf-8")
            elif path == "/panel.js":
                self._send_asset("panel.js", "application/javascript; charset=utf-8")
            else:
                raise PanelError("NOT_FOUND", "No panel route at %s." % path, 404)
        except Exception as exc:  # noqa: BLE001 - every failure gets the envelope
            self._send_error(exc)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        try:
            if path == "/api/plan":
                body = self._read_json()
                result = self.service.plan(body.get("tool"), body.get("args", {}))
                self._send_json(200, {"ok": True, **result})
            elif path == "/api/apply":
                body = self._read_json()
                result = self.service.apply(body.get("token"))
                self._send_json(200, {"ok": True, **result})
            elif path == "/api/cue":
                body = self._read_json()
                result = self.service.cue_recipe(body)
                self._send_json(200, {"ok": True, **result})
            elif path == "/api/cue/run":
                body = self._read_json()
                result = self.service.run_cue(body.get("token"))
                self._send_json(200, {"ok": True, **result})
            elif path == "/api/cue/discard":
                body = self._read_json()
                result = self.service.discard_cue(body.get("token"))
                self._send_json(200, {"ok": True, **result})
            elif path == "/api/undo":
                self._read_json()
                result = self.service.undo()
                self._send_json(200, {"ok": True, **result})
            else:
                raise PanelError("NOT_FOUND", "No panel route at %s." % path, 404)
        except Exception as exc:  # noqa: BLE001 - every failure gets the envelope
            self._send_error(exc)

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_HEAD(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        self._send_error(PanelError(
            "METHOD_NOT_ALLOWED", "%s is not allowed; use GET or POST." % self.command, 405,
        ))

    def _read_json(self) -> Dict[str, Any]:
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise PanelError("BAD_REQUEST", "A JSON request body is required.", 400)
        try:
            length = int(raw_length)
        except ValueError:
            raise PanelError("BAD_REQUEST", "Content-Length must be a number.", 400)
        if length < 0 or length > MAX_BODY:
            raise PanelError("REQUEST_TOO_LARGE", "The request body is too large.", 413)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError) as exc:
            raise PanelError("BAD_REQUEST", "The request body is not valid JSON: %s" % exc, 400)
        if not isinstance(body, dict):
            raise PanelError("BAD_REQUEST", "The request body must be a JSON object.", 400)
        return body

    def _send_asset(self, name: str, content_type: str) -> None:
        path = ASSET_ROOT / name
        if not path.is_file():
            raise PanelError("NOT_FOUND", "The panel asset %s is missing from this install." % name, 500)
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, exc: BaseException) -> None:
        error = _as_error(exc)
        payload = {
            "ok": False,
            "error": {
                "code": error.code,
                "message": error.message,
                "status": error.status,
            },
        }
        if error.detail:
            payload["error"]["detail"] = error.detail
        _LOGGER.warning(
            "panel error %s %s: %s: %s",
            getattr(self, "command", "?"), getattr(self, "path", "?"),
            error.code, error.message,
        )
        try:
            self._send_json(error.status, payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt: str, *args: Any) -> None:
        _LOGGER.info("panel %s - %s", self.address_string(), fmt % args)


def run_panel(
    host: str = PANEL_HOST,
    port: int = DEFAULT_PANEL_PORT,
    no_browser: bool = False,
    service: Optional[PanelService] = None,
) -> int:
    """Run the panel until interrupted; return a CLI exit code."""

    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("the panel only binds loopback (127.0.0.1)")
    bind_host = PANEL_HOST
    if not isinstance(port, int) or port < 0 or port > 65535:
        raise ValueError("port must be an integer from 0 to 65535")
    if port == DEFAULT_PORT:
        raise ValueError(
            "port %d is reserved for the Live bridge; use the panel default 9879 or another port"
            % DEFAULT_PORT
        )

    service = service or PanelService(host=bind_host)
    if not _LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)
    _LOGGER.propagate = False

    server = None
    try:
        server = PanelHTTPServer((bind_host, port), service)
        actual = server.server_address[1]
        url = "http://127.0.0.1:%d/" % actual
        print("Enableton panel: %s" % url, flush=True)
        print("Bridge: 127.0.0.1:%d. Press Ctrl+C to stop." % DEFAULT_PORT, flush=True)
        if not no_browser:
            webbrowser.open(url)
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            print("\nPanel stopped.", flush=True)
        return 0
    except OSError as exc:
        print(
            "Could not start the panel on 127.0.0.1:%d: %s" % (port, exc),
            file=sys.stderr,
        )
        return 2
    finally:
        if server is not None:
            server.server_close()
        service.close()
