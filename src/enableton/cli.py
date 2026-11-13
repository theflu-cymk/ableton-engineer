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
from typing import Any, Dict, Optional

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
