# Troubleshooting a stalled or failing command

The script reports its own state in `hello`, and `doctor` prints it. A stall is answered by reading
counters, not by re-reading code.

## 1. Is the code you edited the code Live is running?

`doctor` prints `script`. That value is `SCRIPT_VERSION` from the build Live loaded at startup.

- Version older than the repo → `uv run enableton setup --force`, then **restart Live**. Without
  `--force`, setup reports success having written 0 files, because an existing install counts as done.
- Editing `remote_script/` changes nothing on its own. Live loads the copy in the User Library.

## 2. Read the counters

| Counter | Means |
|---|---|
| `queued` | Requests waiting for the main thread, right now. |
| `display` | How many times Live called `update_display()`. This is Live's heartbeat. |
| `drains` | How many of those calls reached `Bridge.drain()`. |
| `ran` | How many queued tasks were actually dispatched to a handler. |
| `errors` | How many handlers raised. |
| `super_errors` | How many times the framework's own `super().update_display()` raised. |
| `busy` | How many requests hit the queue cap or the wait deadline. |

## 3. Patterns

| Reading | Cause | Next |
|---|---|---|
| `display` frozen, `script` current | Live is not ticking the surface. Check the Control Surface slot still holds `Enableton`, and that no modal dialog is open. `hello` answers on the socket thread, so `connected yes` proves nothing. | Fix the slot or dismiss the dialog; no code change. |
| `display` growing, `drains` frozen | `super().update_display()` is raising before our drain. | Read `last_super_error` in `doctor --json`. |
| `drains` growing, `ran` frozen, `queued` > 0 | Work is queued and the drain runs, but dispatch never fires. | Suspect `dispatch` / handler registration, not transport. |
| `ran` growing, no reply | The reply path is broken, not the work. | Check the socket thread's `sendall` and framing. |
| `errors` climbing | A handler raised — suspect the LOM object's shape, not the bridge. | Reproduce against real Live; fake-based tests won't show it. |

`LIVE_BUSY` is the bridge answering; `TIMEOUT` is the client giving up. The bridge replies at
`timeout_s * 0.9`, so a `TIMEOUT` means the bridge never answered inside the client's watchdog at all.
An earlier version waited `timeout_s + 0.5` and inverted that margin, turning every stall into an
unexplainable `TIMEOUT`.

## 4. Port

`9878` is the default. `AbletonMureka` lives in the same Remote Scripts folder and competes for it —
whichever script binds first wins, and the other only logs the failure. If `doctor` stops connecting
after a restart, find which script holds the port before suspecting the code.

## What this machine proved on 2026-11-09

- `callable(song)` on a real `Song` is **true**, so the property/method guard called it and every read
  returned `INTERNAL: 'Song' object is not callable'`. Fixed with `resolve_song`.
- The deadline inversion turned that into a bare `TIMEOUT` on the next session, which is how a
  handler error became indistinguishable from a dead main thread.
- With `0.1.1` installed and live: `script 0.1.1`, then `status` answered `LIVE_BUSY` in 6 s instead
  of silence — the structured error working — while `display` and `drains` stayed at 0, which is the
  "Live is not ticking the surface" row above.
