# M6/M7 implementation status

Offline-only progress ledger. **Fake/synthetic tests and file analysis are not Live verification.**
Branch `theflu-cymk-m6-audio-tools` was reconciled with the M4 accounting base
`bd023bfd2611ba6c043426f5d98fbaa7150b52b2` on 2026-11-11. The M4 owner confirmed the prior
candidate `a4d9681` and landed the accounting-only correction on top. The original M6/M7 base was
`5761472b6c77a9e4360a004daee832bca3102677`.

**Parked, with one directed exception:** shared-file integration remains parked until M4 is
accepted. On 2026-11-11 the user directed this branch to push the Live-gated blocker, so
`mix_meter_poll`, `mix_headroom` and `mix_resample_capture` are registered end-to-end, and
`mix_headroom` now consumes the meter window. Those are the only M6/M7 runtime changes on this
branch.

| Item/task | Status | Blocker and evidence | Unblock condition / owner | Shared files or decision dependencies | Next independent task |
|---|---|---|---|---|---|
| PCM WAV file metrics | offline-ready | Synthetic PCM 8/16/24/32-bit tests cover aggregate/per-channel peak, RMS, DC, and bounded `[start, end)` windows rounded to nearest frame; out-of-range or malformed windows fail explicitly. No actual Live capture/readback tested. | Add a verified real-capture artifact and scratch-Set readback gate; Live operator/integrator. | M6 tool registration will touch `src/enableton/tools.json`, now present from M4 base `bd023bf`; integration remains parked. | Consider further offline source metrics only where the SPEC provides a clear measurement contract. |
| Recipe pattern parser and v1 validator | offline-ready | Synthetic tests cover format, required fields, documented `hit`/`layer` modes, bar divisibility, duplicate lane/slot identifier rejection, and optional source metadata (kind, file, window, confidence); no MIDI scheduling, clip writing, or recipe tools. | Integrator wires recipe handlers/catalog after M4 shared files are available. | `tools.json`, modes/catalogue tests are now present from M4 base `bd023bf`; integration remains parked. | Continue pure recipe data validation; catalog/mode integration remains blocked. |
| Recipe JSON store | offline-ready | Temporary-directory tests cover list/show/save/override/delete; default application config path is intentionally not selected, and storage is not registered as a tool. | Configuration owner selects/implements the supported user data directory; integrator registers recipe tools. | Planned `%APPDATA%\\Enableton` location is not implemented in the base; registration uses the candidate `tools.json`; integration remains parked. | Recipe schema edge cases that do not choose global paths. |
| M6 meter polling, resample capture, routing verification, spectral/loudness analysis, master compare/device audition | Live-gated | No Live API probing or captured audio is available under this offline assignment; fake tests would not establish LOM semantics. | Approved scratch-Set probes with real Live readback, capture file verification, and explicit failed-arm exercise; Live operator. | Runtime catalogue plus Remote Script handler surfaces; the latter also contains concurrent M4 work. | Continue a separate offline, file-only analysis increment. |
| `mix_meter_poll` runtime slice | **Verified** (read-only) on real `0.4.14` | Handler samples `output_meter_level` plus instantaneous `output_meter_left/right` across display ticks through `Deferred`; each row reports its latest level, highest observed peak, sample count, and `unavailable` with the reason when a meter cannot be read. 12 new fake tests cover peak-across-ticks, zero-vs-unavailable, selection, ambiguity and arguments. `SCRIPT_VERSION` is `0.4.14`; `setup --force` installed 19 files and removed 19 stale `.pyc` files; repo build is `2d3a0a801a4d`. On `SCRATCH fortnight` a stopped poll returned 35 rows (32 tracks, 2 returns, master `Main`), all `available`, and a playback poll returned master peak `0.897554` (0.94 dB headroom) with 7 samples in 625 ms. | Done; `mix_headroom` now consumes this meter window. | `tools.json`, `modes.json`, `tests/test_manifest.py` and the Remote Script, changed at the user's explicit direction while M4 acceptance is pending. | None for this tool. |
| `mix_headroom` measured peaks | **Verified** on real `0.4.14` | The report now runs one `mix.meter_poll` window and joins meter rows to snapshot faders by index; `measure: false` keeps the fader-only answer. On `SCRATCH fortnight` while stopped: `measured: false`, 34 peaks at 0.0, not-playing reason. During playback from bar 9 (`ms: 600`): 7 samples over 625 ms, master peak `0.901003` -> `-0.91 dB` / 0.91 dB headroom, loudest `REVocals` `0.968695`. Transport stopped and playhead restored to 372.0. Offline suite **462 passed, 42 subtests**. | Done. | Client-side only; no Remote Script change or restart. | None. |
| `mix_resample_capture` runtime slice | Implemented and installed; **Unverified on Live** | Handler records the master through a `Resampling` input into an empty Session slot across display ticks. Dry-run by default; an apply refuses playback, an occupied slot and a MIDI track, verifies the routing readback before arming, stops after `ms`, restores routing and arm, deletes the temporary clip and keeps the WAV. `run_tool` attaches `audio_analysis.analyze_wave` metrics. 9 fake tests cover success, stubborn-arm refusal, restore, occupied slots and analysis; full suite **471 passed, 42 subtests**. `setup --force` installed 20 files and removed 19 stale `.pyc` files; repo build `4be9df47b888`. `doctor` still reports `0.4.14` / `2d3a0a801a4d` / `stale` because Live has not restarted. | Restart Live; confirm `doctor` shows `0.4.15` / `4be9df47b888`; dry-run on `SCRATCH fortnight`, then one short audible capture on `Unused` (index 26) with an analysis readback. | Audible; the first real capture needs the user's go-ahead. No `Samples/Recorded` file has been created yet. | `tools.json`, `modes.json`, `tests/test_manifest.py`, fake and Remote Script registration. | None until the Live gate passes. |
| Resample-capture preflight probe | probe Verified; capture Unverified | Read-only probe on `SCRATCH fortnight` (`0.4.14`, build `2d3a0a801a4d`): `tracks_set_routing` dry-runs resolved `Resampling` at input index 0 on `REVocals` (index 0) and `Unused` (index 26), both currently `Ext. In`, with nothing written. `Unused` is an audio track with no clips and no devices; `Samples/Recorded` exists and holds 34 WAVs. `Song.record_mode`, the post-arm routing readback and the recorded clip's `file_path` are untested. | Build `master_loudness_capture` with a dry-run preflight and an apply that verifies the arm took before recording; run one short capture on `Unused` only after explicit approval. | Audible and creates a clip; the first recording needs the user's go-ahead. | Capture engine and tool registration. |
| M7 generation audition/accept/discard and Browser-backed recipe build/learn | Live-gated | No Browser load, scratch-preview scene, audition, or real clip write has been exercised. | Approved scratch-Set probes with identity guards/readback and Browser-backed sample provenance; Live operator/integrator. | Catalogue/modes and Remote Script handler surfaces; do not collide with M4 changes. | Continue pure recipe data validation and offline sample-analysis utilities. |
| M6/M7 runtime catalogue registration and mission reconciliation | reconciled, parked | M4 accounting base `bd023bf` is merged into this branch; the M4 owner confirmed the base and landed the accounting correction. MISSION/SPEC retain both M4 and M6/M7 content. Full offline suite: **471 passed, 42 subtests**; `mix_meter_poll` is registered and verified, `mix_headroom` consumes it, and `mix_resample_capture` is registered and installed but still Live-gated. M4 accounting branch `7de7e66` is superseded; M5 `c57edc7` remains separate. | M4 acceptance; then integrate M5 and decide M6/M7 runtime. Runtime handlers still require their scratch-Set gates. | `tools.json`, modes, catalogue tests and Remote Script are parked for M6/M7 registration. | Continue pure offline M6/M7 work only; no shared-file edits. |

### 2026-11-11: reconciliation with confirmed M4 base (parked)

Merged local `main` `a4d9681f3d07482f7e232c7c76f5133cbf508f63` into this branch without overwriting
M4. The full offline suite is **441 passed, 27 subtests**; `compileall` and diff checks passed. The
offline M6/M7 foundations are present, but runtime registration and every Live gate remain pending.

### 2026-11-11: duplicate recipe identifiers

`validate_recipe` now rejects two lanes that reference the same slot ID and two slot definitions that
use the same slot ID. Focused synthetic tests: **37 passed, 20 subtests**; `compileall` and
`git diff --check` passed. No Live, catalogue, mode, or Remote Script change was made for this slice.

### 2026-11-11: optional recipe source metadata

`validate_recipe` now validates the optional `source` object shown in the recipe schema: `kind` and
`file` are non-empty strings, `window_s` is an ordered non-negative `[start, end]` pair when present,
and `confidence` is a finite number in `0..1` when present. The focused foundation suite is
**41 passed, 35 subtests**; the full offline suite is **445 passed, 42 subtests**; `compileall` and
`git diff --check` passed. This is synthetic schema validation only; no Live, catalogue, mode, or
Remote Script change was made.

### 2026-11-11: `mix_meter_poll` runtime slice (Verified on real `0.4.14`)

Registered `mix_meter_poll` end-to-end at the user's explicit direction to push the Live-gated
blocker. The handler samples `output_meter_level` and the instantaneous left/right meters on later
display ticks, so the main thread never blocks; `peak` is the highest instantaneous reading
observed, `level` is the latest peak-hold value, and an unreadable meter is `unavailable` with its
reason rather than a zero that would look like silence. The poll covers regular tracks, return
tracks and the master by default, resolves names across all three and refuses an ambiguous name.

`SCRIPT_VERSION` is `0.4.14`. Full offline suite: **457 passed, 42 subtests**; `compileall` and
`git diff --check` passed. `setup --force` installed 19 files and removed 19 stale `.pyc` files.
**Verified on real `0.4.14`.** `doctor` reported script `0.4.14`, build `2d3a0a801a4d`, no `stale`,
`errors 0`, `super_errors 0`. A stopped poll (`ms: 200`) returned 35 rows (32 tracks, 2 returns,
master `Main`), all `available`, 3 samples over 219 ms, with honest zeros and the not-playing note.
During a two-second playback probe from bar 9, a poll (`ms: 600`) returned 7 samples over 625 ms,
`playing: true`, master peak `0.897554` (0.94 dB headroom), loudest track `REVocals` `0.966257`, and
9 rows carrying signal. The transport was stopped and the playhead restored to 372.0. The held
`level` can exceed the observed `peak` because of Live's one-second hold; the report exposes both
rather than hiding the difference. No M4 acceptance is implied, and `main` was not touched.

### 2026-11-11: resample-capture probe (read-only, Verified)

The next M6 tier is resample capture (`SPEC.md` §11). Preconditions were probed read-only on
`SCRATCH fortnight` on `0.4.14` / build `2d3a0a801a4d`:

- `tracks.set_routing` dry-runs resolved `Resampling` at input index 0 on `REVocals` (index 0) and
  `Unused` (index 26); both currently read `Ext. In`. Nothing was written.
- `Unused` is an audio track with no clips and no devices, so it can host a capture without
  creating a track.
- `F:\ableton songs\Fortnight\fortnight Project\Samples\Recorded` exists and holds 34 WAVs.

Not probed: `Song.record_mode`, the routing readback after an applied arm (the silent-no-op trap),
the recorded clip's `file_path`, and cleanup. No capture has been run, no audio was recorded, and
`master_loudness_capture` is not registered. The first recording is audible and needs explicit
approval.

### 2026-11-11: `mix_resample_capture` runtime slice (implemented, Live gate pending)

Registered the resample-capture tier end-to-end. The new handler lives in
`remote_script/Enableton/handlers/capture.py`; it runs a four-phase `Deferred` state machine
(record -> stop -> finalize -> restore) so the main thread never blocks. It resolves the scratch
audio track by name or index, requires an empty Session slot, refuses while the Set is playing,
and sets `input_routing_type = Resampling` only after confirming the option exists. The readback
is checked before arming: a build that silently ignores the setter fails with
`PRECONDITION_FAILED` instead of recording silence. It then arms, fires the slot, waits `ms`,
stops, waits for the clip and its `file_path`, restores the previous routing from the current
option vector and the previous arm state, deletes the temporary clip and keeps the WAV. Every
failure path attempts the same restore before raising.

`run_tool` special-cases the tool because an M2 preflight/apply trace cannot describe a recording
that happens once; it calls the handler directly and attaches `analyze_wave` (sample peak, RMS,
DC offset) to the result. `tools.json` declares it audible, writes, reversible, dry-run by
default, with a 20 s timeout; `modes.json` adds it to `mix` (23 tools). `SCRIPT_VERSION` is
`0.4.15`. Full offline suite: **471 passed, 42 subtests**; `compileall` and `git diff --check`
passed. `setup --force` installed 20 files and removed 19 stale `.pyc` files; repo build is
`4be9df47b888`. `doctor` still reports `0.4.14` / `2d3a0a801a4d` / `stale`, so no real capture
has run and no `Samples/Recorded` WAV was created by this slice.
