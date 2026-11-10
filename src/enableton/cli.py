"""The CLI. Exit codes are part of the contract: 0 clean, 1 findings, 2 connection failure."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional

from .manifest import load_manifest
from .modes import ModeError, load_modes
from .protocol.client import DEFAULT_PORT, LiveClient
from .protocol.codes import LiveError
from .reports import summary_from_snapshot
from .setup import InstallError, default_source, digest, install, instructions
from .tools import run_tool

EXIT_OK, EXIT_FINDINGS, EXIT_CONNECTION = 0, 1, 2


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

    sub = parser.add_subparsers(dest="command")

    setup = sub.add_parser("setup", help="install the Remote Script into Live")
    setup.add_argument("--dir", default=None, help="target folder (default: User Library)")
    setup.add_argument("--force", action="store_true", help="replace an existing install")
    setup.add_argument("--dry-run", action="store_true", help="show what would be written")

    sub.add_parser("doctor", help="environment, version and connection report")
    sub.add_parser("status", help="connection and Set summary")
    guide = sub.add_parser("guide", help="the command sheet for a mode")
    guide.add_argument("--mode", default=None)
    call = sub.add_parser("call", help="run one tool by name")
    call.add_argument("tool")
    call.add_argument("--args", default="{}", help="JSON object of arguments")

    sub.add_parser("modes", help="list modes and their tool counts")

    serve = sub.add_parser("serve", help="run the MCP server")
    serve.add_argument("--mode", default=None)

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
        _print({"default": modes.default, "cap": modes.max_tools, "modes": rows})
        return EXIT_OK

    if args.command == "guide":
        catalogue = load_manifest()
        modes = load_modes(catalogue)
        mode = modes.get(args.mode)
        rows = [{"tool": t, "summary": catalogue[t].summary,
                 "examples": catalogue[t].examples} for t in mode.tools]
        _print({"mode": mode.name, "tools": rows})
        return EXIT_OK

    if args.command == "status":
        client = LiveClient(host=args.host, port=args.port)
        try:
            client.connect(timeout=1.5)
            _print(summary_from_snapshot(client.call("snapshot.get", {}, timeout_ms=6000)))
            return EXIT_OK
        except LiveError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_CONNECTION
        finally:
            client.close()

    if args.command == "call":
        try:
            payload = json.loads(args.args or "{}")
        except ValueError as exc:
            print("--args must be JSON: %s" % exc, file=sys.stderr)
            return EXIT_CONNECTION
        if not isinstance(payload, dict):
            print("--args must be a JSON object", file=sys.stderr)
            return EXIT_CONNECTION

        client = LiveClient(host=args.host, port=args.port)
        try:
            client.connect(timeout=1.5)
            _print(run_tool(args.tool, payload, client))
            return EXIT_OK
        except LiveError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_CONNECTION
        finally:
            client.close()

    if args.command == "serve":
        print("enableton serve arrives in M5; the protocol and catalogue are ready.", file=sys.stderr)
        return EXIT_OK

    parser.print_help()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
