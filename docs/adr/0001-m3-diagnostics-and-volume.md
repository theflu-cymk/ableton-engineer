# ADR 0001 — M3 diagnostics and `tracks_set_volume`

- **Status:** Accepted
- **Date:** 2026-11-10
- **Affects:** `src/enableton/diagnostics.py`, `src/enableton/tools.json`,
  `src/enableton/modes.json`, `remote_script/Enableton/server.py`,
  `remote_script/Enableton/handlers/tracks.py`

## Context

M3 needs a finding model, phase-ordered plans and an autofix path that can be held to the M2 write
safety rules. A plan is only useful if at least one finding has a real repair. The existing
`tracks_gain_stage` cannot repair an above-unity fader without a measured peak; the scratch Set has
no peaks in its snapshot, so it skips every track.

The SPEC's change-control rule requires an ADR for any change to `server.py`, which carries the
script version despite the new command living in a handler module.

## Decision

1. Add `tracks_set_volume({tracks, volume, dry_run, restore})` as a single-parameter write. Volume
   is Live's raw 0..1 fader position, so `0.85` is `0.0 dB`. It is dry-run by default, returns one
   tool-owned undo token per touched track, and replays those exact values through `restore`.
2. Treat an above-unity fader as a `gain` phase, `auto`-mode finding with a `tracks_set_volume` fix
   to unity. When Live's display string is absent, a raw position above `0.85` is still proof of an
   above-unity trim; the finding records that the exact dB is unknown.
3. Keep unimplemented hygiene fixes in the finding model. `inspect_plan` returns them as
   `unavailable` with the missing tool name rather than dropping them or pretending they are fixed.
4. Run autofix one phase at a time through `PlanExecutor`, re-read after each phase, and roll back
   every earlier phase if a later phase fails or the total finding count rises. Each phase remains
   a normal transaction with its own scratch copy and dry-run trace check.
5. Keep all `inspect_*` tools local. They read the snapshot cache; only `inspect_autofix` applies
   writes, through the existing executor.

`SCRIPT_VERSION` becomes `0.2.4`. The wire protocol, framing and error-code set do not change.

## Consequences

- The manifest gains `tracks.set_volume`, so `remote_commands()` and the drift test change.
- Live must be restarted after `setup --force`; adding the handler to the repo does not change the
  process Live already loaded. Until that restart, an autofix apply will fail at the first volume
  step, and `doctor` will report `stale`.
- `inspect_plan` can report a finding with no executable fix. That is deliberate: the gap is
  visible and named, not hidden.
- Autofix is all-or-nothing across its selected phases. A count rise triggers rollback, so the
  report may show `counts_after_change` higher than the final `counts_after`.
