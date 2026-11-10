# Enableton — project conventions

Read `SPEC.md` first: it owns the design and wins any conflict. `MISSION.md` owns sequencing and the
verified state of this machine. `PROMPT.md` is the origin brief and is historical only.

## The rule that outranks the others

A milestone is not done because the suite is green. The tests import the Remote Script's modules
in-process and hand them a fake `Song` — an object model far better behaved than Live's (the fake
song is not callable, which is exactly why the `callable(song)` bug passed 84 tests). Green proves
internal consistency, not that anything works. **Done means one real-Live call returned real data**,
and that call is named in the milestone's acceptance.

## Changing the Remote Script — four steps, always

1. Bump `SCRIPT_VERSION` in `remote_script/Enableton/server.py`.
2. `uv run enableton setup --force`. Without `--force` setup reports success having written **0
   files**, because an existing install counts as done.
3. Restart Live. It scans Remote Scripts only at startup and holds the old build in RAM until then.
4. `uv run enableton doctor` must report the new version **and** a `build` digest matching this repo.
   A file on disk is not evidence of what Live is running: `doctor` compares the digest of what Live
   loaded with what the repo ships and prints `stale` when they differ, so a forgotten version bump
   can no longer hide an old build. A forced install is clean — files the build no longer ships and
   any `__pycache__` are removed.

Editing `remote_script/` alone changes nothing: Live loads the copy in the User Library, so step 2 is
the only thing that moves a change into Live's process. `AbletonMureka` sits in that same folder and
competes for port 9878 — if `doctor` stops connecting after a restart, check which script bound the
port before assuming the code broke. Every change to `server.py` lands with a test in `tests/`.

## Timeout triage

A stalled command is a counter question, not a code question: `doctor` prints `queued`, `display`,
`drains`, `ran`, `errors` and `super_errors` from the script itself. Read
[docs/troubleshooting.md](docs/troubleshooting.md) before changing any code — it maps each pattern to
its cause. The one rule that matters here: the bridge answers at `timeout_s * 0.9`, never later than
the client's watchdog.

## Live Object Model traps, learned the hard way

Rules only — the reasoning behind them lives in `SPEC.md` §3 and the module docstrings.

- `callable(song)` is **true** for LOM objects and then raises `'Song' object is not callable`. Use
  `isinstance(x, types.MethodType)` to tell a property from a method (`resolve_song`).
- `schedule_message` silently drops tasks appended from the socket thread. Marshal work through a
  queue drained in `update_display()`.
- `update_display` must call `super().update_display()` first, or components and scheduled work stop
  and every real command times out while ping still answers.
- All LOM access happens on Live's main thread, never on the socket thread.
- `ControlSurface` has **no** `log_message` on this build. Log through `_safe_log`, never directly: an
  exception from a diagnostic call in `__init__` kills the surface while its daemon socket survives,
  which looks exactly like a dead main thread (`connected yes`, `display 0`).

## Data safety

- The user's Sets live at `F:\ableton songs`. Backups sit in `/Backup/` subfolders and outnumber the
  working Sets roughly 2:1 (192 `.als` on 2026-11-09, 126 of them backups). Exclude `/Backup/` from
  every scan and fixture walk, and never hardcode a count — the library changes.
- Never write a user `.als` in place. Copy to staging, then move.
- No hardcoded machine paths in code. Config is *planned* at `%APPDATA%\Enableton`, but no config
  module exists yet (`src/enableton/state/` holds only `snapshot.py`) — don't cite it as if it does.
- The installed script is a copy in the User Library, not this repo. Nothing here runs until step 2
  above.

## Invariants that must not be broken

- An unavailable capability reports `unavailable` **with a reason**. Never fake it, never substitute
  different behaviour, never raise at call time.
- One socket, one in-flight request. A second call while one is pending returns `LIVE_BUSY`
  (`MAX_QUEUED = 8`).
- Tests never use port 9878. They bind port 0 and assert the bound port is not Live's, so the suite
  can run while Live is open.
- Nothing in `src/` or `remote_script/` references the Sets path. The M2 safety executor and a
  real scratch-Set write/restore exist (`0.2.1`), and the M2 acceptance gates passed on real
  `0.2.3`, including the restore response name and a forced mid-plan failure. Don't assume full
  save/restore works because `SPEC.md` describes it.
- M3 is complete and **Verified** on real `0.2.4` against `SCRATCH fortnight`: 25 findings dropped
  to 22 after the three `tracks_set_volume` steps, a controlled real count rise halted and rolled
  back, and 14 needs-listening findings never entered the plan or the apply. `ableton_escalate`
  produced a stored, expiring plan that a separate CLI process applied with `ableton_plan_apply`, and
  `modes --findings` reported the before/after per-mode counts. The working `fortnight` Set was not
  written. Do not call an autofix or plan apply before `doctor` reports the matching script and
  build.
- `enableton serve` is a stub until M5: it prints a message and exits 0.
- `doctor` and `status` need Live running with `Enableton` selected in a Control Surface slot
  (Preferences > Link, Tempo & MIDI). `hello` answers on the socket thread, so `connected yes` alone
  does not mean the main thread is alive — check `drains`.

## Evidence

- Tag every factual claim in a document **Verified** (someone ran it), **Assumed**, or **Unverified**.
  An untagged claim is how `SPEC.md` came to promise two tests that did not exist.
- Report checks that failed or could not run as limitations. Never describe a compile or a fake-based
  test as proof that behaviour works.

## Working on this repo

One writer at a time. Commit before handing the tree to another session: an uncommitted tree gives
the next writer no diff, no baseline, and no way to tell your edits from theirs. If a file appears
that you did not create, check `git status` and its mtime before assuming a second agent is running.

## Commands

```bash
uv run pytest -q                  # whole suite against the fake Song; never quote a fixed count
uv run enableton doctor           # connection, script version, queue counters
uv run enableton status           # first real read: the real-Live gate
uv run enableton setup --force    # install after any Remote Script change
```
