"""The CLI. Exit codes are part of the contract.

0 clean, 1 findings or a request the script refused, 2 connection failure. A tool error is not a
connection failure: only a dead socket or a timeout earns the connection code, so a caller can
tell "nothing to do" from "nothing is listening".
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from typing import Any, Dict, Optional, Sequence

from . import diagnostics
from .manifest import load_manifest
from .modes import ModeError, guide as build_guide, load_modes
from .protocol.client import DEFAULT_PORT, LiveClient
from .protocol.codes import LiveError
from .reports import summary_from_snapshot
from .setup import InstallError, default_source, digest, install, instructions
from .tools import run_tool

EXIT_OK, EXIT_FINDINGS, EXIT_CONNECTION = 0, 1, 2

#: LiveError codes that mean the socket is gone. Everything else is a refused request.
TRANSPORT_ERRORS = frozenset({"DISCONNECTED", "TIMEOUT"})


def doctor(host: str = "127.0.0.1", port: int = DEFAULT_PORT) -> Dict[str, Any]:
    """Everything needed to answer 'why doesn't it work' in one call."""
    report: Dict[str, Any] = {"port": port, "host": host, "connected": False}
    client = LiveClient(host=host, port=port)
    try:
        client.connect(timeout=1.5)
        info = client.handshake()
        report.update(
            {
                "connected": True,
                "protocol": info.get("protocol"),
                "script": info.get("script"),
                "live": info.get("live"),
                "features": info.get("features", []),
                # A timeout has two causes and they look alike from here: Live never ticked the
                # surface (drains frozen), or the work ran and the reply was lost (ran grows).
                "queued": info.get("queued"),
                "stats": info.get("stats") or {},
                "build": info.get("build"),
            }
        )
    except LiveError as exc:
        report["error"] = exc.message
        report["code"] = exc.code
    except OSError as exc:
        report["error"] = str(exc)
        report["code"] = "DISCONNECTED"
    finally:
        client.close()
    return report


def _assignments(values: Sequence[str], flag: str) -> Dict[str, str]:
    """Parse repeated ``NAME=VALUE`` flags without inventing a shorthand."""
    out: Dict[str, str] = {}
    for value in values:
        name, sep, raw = value.partition("=")
        if not sep or not name.strip() or not raw.strip():
            raise ValueError("--%s must look like NAME=VALUE" % flag)
        out[name.strip()] = raw.strip()
    return out


def _print(obj: Any) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(prog="enableton", description="Ableton Live, for your LLM.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--json", action="store_true", help="machine-readable output")

    # Repeated on every subcommand so `enableton call x --port 9879` parses the same way as
    # `enableton --port 9879 call x`. SUPPRESS keeps a flag given before the command from being
    # reset by the subparser's own default.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--host", default=argparse.SUPPRESS)
    common.add_argument("--port", type=int, default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)

    sub = parser.add_subparsers(dest="command")

    setup = sub.add_parser("setup", help="install the Remote Script into Live", parents=[common])
    setup.add_argument("--dir", default=None, help="target folder (default: User Library)")
    setup.add_argument("--force", action="store_true", help="replace an existing install")
    setup.add_argument("--dry-run", action="store_true", help="show what would be written")

    sub.add_parser("doctor", help="environment, version and connection report", parents=[common])
    sub.add_parser("status", help="connection and Set summary", parents=[common])
    guide = sub.add_parser("guide", help="the command sheet for a mode", parents=[common])
    guide.add_argument("--mode", default=None)
    call = sub.add_parser("call", help="run one tool by name", parents=[common])
    call.add_argument("tool")
    call.add_argument("--args", default="{}", help="JSON object of arguments")

    tools_parser = sub.add_parser(
        "tools", help="list the tool catalogue", parents=[common]
    )
    tools_parser.add_argument("--domain", default=None, help="only this domain, e.g. mix")
    tools_parser.add_argument(
        "--writes", action="store_true", help="only tools that change Live"
    )

    describe = sub.add_parser(
        "describe", help="one tool's arguments, schema and examples", parents=[common]
    )
    describe.add_argument("tool")

    inspect_parser = sub.add_parser("inspect", help="run a diagnostic tier", parents=[common])
    inspect_parser.add_argument("--tier", choices=("fast", "standard", "deep"), default="standard")
    inspect_parser.add_argument("--limit", type=int, default=50)

    plan_parser = sub.add_parser(
        "plan", help="compile and store a plan without applying it", parents=[common]
    )
    plan_parser.add_argument("--intent", default="fix all safe findings")
    plan_parser.add_argument("--phase", action="append", choices=diagnostics.PHASES)

    run_parser = sub.add_parser("run", help="apply a stored plan id", parents=[common])
    run_parser.add_argument("plan_id")

    recipes_parser = sub.add_parser(
        "recipes", help="list shipped and user recipes", parents=[common]
    )
    recipes_parser.add_argument(
        "--kind", choices=("style", "rhythm", "workflow", "combination"), default=None,
        help="only this recipe kind",
    )
    recipes_parser.add_argument(
        "--tag", default=None, help="only recipes carrying this tag, e.g. riddim"
    )
    recipes_parser.add_argument(
        "--search", default=None, help="match this text in a recipe id or name"
    )
    recipes_parser.add_argument(
        "--runnable", action="store_true",
        help="only recipes this build can compile into a plan",
    )
    recipe_parser = sub.add_parser(
        "recipe", help="compile one recipe into a stored plan", parents=[common]
    )
    recipe_parser.add_argument("recipe_id")
    recipe_parser.add_argument(
        "--show", action="store_true",
        help="print the recipe definition and its manual checkpoints; does not compile or need Live",
    )
    recipe_parser.add_argument(
        "--target-track", default=None, help="existing MIDI track a rhythm renders into"
    )
    recipe_parser.add_argument(
        "--target-clip", default=None, help="existing MIDI clip a rhythm renders into"
    )
    recipe_parser.add_argument(
        "--location", choices=("arrangement", "session"), default=None,
        help="which clip a duplicate name means",
    )
    recipe_parser.add_argument(
        "--slot", type=int, default=None, help="Session slot of the target clip"
    )
    recipe_parser.add_argument(
        "--pitch", action="append", default=[], metavar="SLOT=PITCH",
        help="MIDI pitch for a rhythm slot that declares none; repeatable",
    )
    recipe_parser.add_argument(
        "--binding", action="append", default=[], metavar="ROLE=TRACK",
        help="point a recipe step's track name at the track in this Set; repeatable",
    )
    recipe_parser.add_argument(
        "--manual-confirmed", action="store_true",
        help="the recipe's before_apply checkpoints were completed",
    )
    recipe_parser.add_argument(
        "--apply", action="store_true", help="apply the compiled plan in the same call"
    )

    modes_parser = sub.add_parser(
        "modes", help="list modes, tool counts and finding counts", parents=[common]
    )
    modes_parser.add_argument(
        "--findings", action="store_true",
        help="read Live and add per-mode finding counts; no connection leaves them unavailable",
    )

    serve = sub.add_parser("serve", help="run the MCP server", parents=[common])
    serve.add_argument("--mode", default=None)

    sub.add_parser(
        "menu", help="interactive menu (what a bare `enableton` opens)", parents=[common]
    )

    # The panel's --port is its own HTTP port, not the bridge port. It deliberately does not
    # inherit ``common``: the bridge port stays at 9878 and the panel defaults to 9879 so the two
    # can never collide by accident.
    panel = sub.add_parser("panel", help="open the local producer panel")
    panel.add_argument("--host", default=argparse.SUPPRESS)
    panel.add_argument("--port", type=int, default=9879, help="panel HTTP port (default 9879)")
    panel.add_argument(
        "--no-browser", action="store_true",
        help="print the URL instead of opening a browser",
    )

    args = parser.parse_args(argv)

    if args.command == "setup":
        try:
            result = install(args.dir, force=args.force, dry_run=args.dry_run)
        except InstallError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_CONNECTION

        if result.already_present and not args.dry_run:
            print("Already installed at %s" % result.target)
            print("Use --force to reinstall after an update.")
        else:
            verb = "Would install" if result.dry_run else "Installed"
            print("%s %d file(s) into %s" % (verb, len(result.files), result.target))
            if result.removed:
                print("%s %d stale file(s): %s"
                      % ("Would remove" if result.dry_run else "Removed",
                         len(result.removed), ", ".join(result.removed)))
        print("")
        for line in instructions():
            print("  %s" % line)
        return EXIT_OK

    if args.command == "doctor":
        report = doctor(args.host, args.port)
        if args.json:
            _print(report)
        else:
            print("enableton doctor")
            print("  port      %d" % report["port"])
            print("  connected %s" % ("yes" if report["connected"] else "no"))
            if report["connected"]:
                print("  live      %s" % report.get("live"))
                print("  script    %s" % report.get("script"))
                print("  features  %s" % ", ".join(report.get("features") or []) or "-")
                stats = report.get("stats") or {}
                if report.get("queued") is not None or stats:
                    print("  queued    %s" % report.get("queued"))
                    print("  drains    %s   ran %s   errors %s"
                          % (stats.get("drains"), stats.get("ran"), stats.get("errors")))
                    print("  display   %s   super_errors %s"
                          % (stats.get("display"), stats.get("super_errors")))
                    if stats.get("last_super_error"):
                        print("  super_err %s" % stats["last_super_error"])
                if report.get("build"):
                    print("  build     %s" % report["build"])
                    try:
                        expected = digest(default_source())
                    except Exception:
                        expected = None
                    if expected and expected != report["build"]:
                        print("  stale     Live loaded %s; this repo is %s"
                              % (report["build"], expected))
                        print("            run `enableton setup --force`, then restart Live.")
            else:
                print("  error     %s" % report.get("error"))
                print("  fix       select 'Enableton' as a Control Surface in Live's")
                print("            Preferences > Link, Tempo & MIDI, then retry.")
        return EXIT_OK if report["connected"] else EXIT_CONNECTION

    if args.command == "modes":
        catalogue = load_manifest()
        modes = load_modes(catalogue)
        rows = [{"mode": m, "tools": len(modes.modes[m].tools),
                 "summary": modes.modes[m].summary} for m in modes.names()]
        payload = {"default": modes.default, "cap": modes.max_tools, "modes": rows}
        if args.findings:
            client = LiveClient(host=args.host, port=args.port)
            try:
                client.connect(timeout=1.5)
                snapshot = client.call("snapshot.get", {}, timeout_ms=6000)
                findings = diagnostics.detect(snapshot, "standard")
                payload["findings"] = diagnostics.counts(findings)
                payload["live"] = {"connected": True}
                for row in rows:
                    selected = [finding for finding in findings if finding.mode == row["mode"]]
                    row["findings"] = diagnostics.counts(selected)
            except (LiveError, OSError) as exc:
                message = exc.message if isinstance(exc, LiveError) else str(exc)
                payload["live"] = {"connected": False, "error": message}
            finally:
                client.close()
        _print(payload)
        return EXIT_OK

    if args.command == "guide":
        _print(build_guide(load_manifest(), args.mode))
        return EXIT_OK

    if args.command == "inspect":
        client = LiveClient(host=args.host, port=args.port)
        try:
            client.connect(timeout=1.5)
            result = run_tool("inspect_run", {"tier": args.tier, "limit": args.limit}, client)
            _print(result)
            return EXIT_FINDINGS if result["counts"]["total"] else EXIT_OK
        except (LiveError, OSError) as exc:
            message = exc.message if isinstance(exc, LiveError) else str(exc)
            print(message, file=sys.stderr)
            return EXIT_CONNECTION
        finally:
            client.close()

    if args.command == "plan":
        context = {"phases": args.phase} if args.phase else {}
        client = LiveClient(host=args.host, port=args.port)
        try:
            client.connect(timeout=1.5)
            result = run_tool(
                "ableton_escalate", {"intent": args.intent, "context": context}, client
            )
            _print(result)
            return EXIT_OK if result.get("plan_id") else EXIT_FINDINGS
        except (LiveError, OSError) as exc:
            message = exc.message if isinstance(exc, LiveError) else str(exc)
            print(message, file=sys.stderr)
            return EXIT_CONNECTION
        finally:
            client.close()

    if args.command == "run":
        client = LiveClient(host=args.host, port=args.port)
        try:
            client.connect(timeout=1.5)
            result = run_tool("ableton_plan_apply", {"plan_id": args.plan_id}, client)
            _print(result)
            return EXIT_OK if result.get("applied") else EXIT_FINDINGS
        except (LiveError, OSError) as exc:
            message = exc.message if isinstance(exc, LiveError) else str(exc)
            print(message, file=sys.stderr)
            return EXIT_CONNECTION
        finally:
            client.close()

    if args.command == "recipes":
        query: Dict[str, Any] = {}
        for key in ("kind", "tag", "search"):
            value = getattr(args, key)
            if value is not None:
                query[key] = value
        if args.runnable:
            query["runnable"] = True
        try:
            _print(run_tool("recipe_list", query))
            return EXIT_OK
        except LiveError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_FINDINGS

    if args.command == "recipe":
        # Reading a recipe is a local file read: only applying, or naming a target that has to be
        # resolved in the Set, needs the Live socket.
        if args.show:
            conflicts = sorted(
                flag for flag, given in (
                    ("--target-track", bool(args.target_track)),
                    ("--target-clip", bool(args.target_clip)),
                    ("--location", bool(args.location)),
                    ("--slot", args.slot is not None),
                    ("--pitch", bool(args.pitch)),
                    ("--binding", bool(args.binding)),
                    ("--manual-confirmed", args.manual_confirmed),
                    ("--apply", args.apply),
                ) if given
            )
            if conflicts:
                print(
                    "--show reads one recipe and cannot be combined with %s"
                    % ", ".join(conflicts),
                    file=sys.stderr,
                )
                return EXIT_FINDINGS
            try:
                _print(run_tool("recipe_show", {"id": args.recipe_id}))
                return EXIT_OK
            except LiveError as exc:
                print(str(exc), file=sys.stderr)
                return EXIT_FINDINGS

        payload: Dict[str, Any] = {"id": args.recipe_id}
        if not args.target_clip and (args.location or args.slot is not None):
            print(
                "--location and --slot need --target-clip: they describe an existing clip",
                file=sys.stderr,
            )
            return EXIT_FINDINGS
        if args.target_track or args.target_clip:
            target: Dict[str, Any] = {}
            if args.target_track:
                target["track"] = args.target_track
            if args.target_clip:
                target["clip"] = args.target_clip
            if args.location:
                target["location"] = args.location
            if args.slot is not None:
                target["slot"] = args.slot
            payload["target"] = target
        try:
            bindings = _assignments(args.binding, "binding")
            if bindings:
                payload["track_bindings"] = bindings
            if args.pitch:
                try:
                    pitches = {
                        name: int(value)
                        for name, value in _assignments(args.pitch, "pitch").items()
                    }
                except ValueError:
                    raise ValueError("--pitch values must be whole MIDI notes (0-127)")
                bad = sorted(name for name, value in pitches.items() if not 0 <= value <= 127)
                if bad:
                    raise ValueError(
                        "--pitch values must be whole MIDI notes (0-127): %s" % ", ".join(bad)
                    )
                payload["pitch_map"] = pitches
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_FINDINGS
        if args.manual_confirmed:
            payload["manual_confirmed"] = True

        if (
            not args.apply
            and not args.target_track
            and not args.target_clip
            and not args.pitch
            and not args.binding
        ):
            try:
                plan = run_tool("recipe_apply", payload)
            except LiveError as exc:
                print(str(exc), file=sys.stderr)
                return EXIT_FINDINGS
            _print(plan)
            return EXIT_OK if plan.get("plan_id") else EXIT_FINDINGS

        client = LiveClient(host=args.host, port=args.port)
        try:
            client.connect(timeout=1.5)
            plan = run_tool("recipe_apply", payload, client)
            if not args.apply or not plan.get("plan_id"):
                _print(plan)
                return EXIT_OK if plan.get("plan_id") else EXIT_FINDINGS
            applied = run_tool("ableton_plan_apply", {"plan_id": plan["plan_id"]}, client)
            _print({"recipe": plan, "apply": applied})
            return EXIT_OK if applied.get("applied") else EXIT_FINDINGS
        except LiveError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_CONNECTION if exc.code in TRANSPORT_ERRORS else EXIT_FINDINGS
        except OSError as exc:
            print("cannot reach Live on %s:%d: %s" % (args.host, args.port, exc), file=sys.stderr)
            return EXIT_CONNECTION
        finally:
            client.close()

    if args.command == "status":
        client = LiveClient(host=args.host, port=args.port)
        try:
            client.connect(timeout=1.5)
            _print(summary_from_snapshot(client.call("snapshot.get", {}, timeout_ms=6000)))
            return EXIT_OK
        except LiveError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_CONNECTION if exc.code in TRANSPORT_ERRORS else EXIT_FINDINGS
        except OSError as exc:
            print("cannot reach Live on %s:%d: %s" % (args.host, args.port, exc), file=sys.stderr)
            return EXIT_CONNECTION
        finally:
            client.close()

    if args.command == "tools":
        catalogue = load_manifest()
        rows = [
            {
                "name": tool.name,
                "domain": tool.domain,
                "writes": tool.writes,
                "timeout_ms": tool.timeout_ms,
                "summary": tool.summary,
            }
            for tool in catalogue.values()
            if (args.domain is None or tool.domain == args.domain)
            and (not args.writes or tool.writes)
        ]
        _print({"count": len(rows), "domain": args.domain, "tools": rows})
        return EXIT_OK

    if args.command == "describe":
        catalogue = load_manifest()
        tool = catalogue.get(args.tool)
        if tool is None:
            near = difflib.get_close_matches(args.tool, list(catalogue), n=3)
            hint = "; did you mean %s?" % ", ".join(near) if near else ""
            print("no tool named %r%s" % (args.tool, hint), file=sys.stderr)
            print("run `enableton tools` for the full catalogue", file=sys.stderr)
            return EXIT_FINDINGS
        _print(
            {
                "name": tool.name,
                "domain": tool.domain,
                "cmd": tool.cmd,
                "summary": tool.summary,
                "description": tool.description,
                "writes": tool.writes,
                "reversible": tool.reversible,
                "timeout_ms": tool.timeout_ms,
                "min_live": tool.min_live,
                "needs": list(tool.needs),
                "examples": list(tool.examples),
                "input": tool.input,
            }
        )
        return EXIT_OK

    if args.command == "call":
        try:
            payload = json.loads(args.args or "{}")
        except ValueError as exc:
            print("--args must be JSON: %s" % exc, file=sys.stderr)
            return EXIT_FINDINGS
        if not isinstance(payload, dict):
            print("--args must be a JSON object", file=sys.stderr)
            return EXIT_FINDINGS

        catalogue = load_manifest()
        if args.tool not in catalogue:
            near = difflib.get_close_matches(args.tool, list(catalogue), n=3)
            hint = "; did you mean %s?" % ", ".join(near) if near else ""
            print("no tool named %r%s" % (args.tool, hint), file=sys.stderr)
            print("run `enableton tools` for the full catalogue", file=sys.stderr)
            return EXIT_FINDINGS

        client = LiveClient(host=args.host, port=args.port)
        try:
            client.connect(timeout=1.5)
            _print(run_tool(args.tool, payload, client))
            return EXIT_OK
        except LiveError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_CONNECTION if exc.code in TRANSPORT_ERRORS else EXIT_FINDINGS
        except OSError as exc:
            print("cannot reach Live on %s:%d: %s" % (args.host, args.port, exc), file=sys.stderr)
            return EXIT_CONNECTION
        finally:
            client.close()

    if args.command == "serve":
        if args.mode == "list":
            catalogue = load_manifest()
            modes = load_modes(catalogue)
            _print(
                {
                    "default": modes.default,
                    "cap": modes.max_tools,
                    "modes": [
                        {
                            "mode": name,
                            "tools": len(modes.get(name).tools),
                            "summary": modes.get(name).summary,
                        }
                        for name in modes.names()
                    ],
                }
            )
            return EXIT_OK
        try:
            from .mcp.transport import run_stdio

            run_stdio(mode=args.mode, host=args.host, port=args.port)
        except ModeError as exc:
            parser.error(str(exc))
        return EXIT_OK

    if args.command == "panel":
        from .panel import run_panel

        try:
            return run_panel(
                host=args.host, port=args.port, no_browser=args.no_browser,
            )
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_FINDINGS

    if args.command == "menu" or args.command is None:
        return _menu(parser)

    parser.print_help()
    return EXIT_OK


def _menu(parser: argparse.ArgumentParser) -> int:
    """Open the interactive menu, or show usage when there is no terminal to draw in."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("enableton: the menu needs an interactive terminal; showing usage instead.\n")
        parser.print_help()
        return EXIT_OK
    from .tui import run as run_menu

    return run_menu(main)


if __name__ == "__main__":
    raise SystemExit(main())
