# M6/M7 implementation status

Offline-only progress ledger. **Fake/synthetic tests and file analysis are not Live verification.**
Branch `theflu-cymk-m6-audio-tools` was reconciled with the M4 accounting base
`bd023bfd2611ba6c043426f5d98fbaa7150b52b2` on 2026-11-11. The M4 owner confirmed the prior
candidate `a4d9681` and landed the accounting-only correction on top. The original M6/M7 base was
`5761472b6c77a9e4360a004daee832bca3102677`.

**Parked:** shared-file integration remains parked. Do not add M6/M7 catalogue, mode,
catalogue-test or Remote Script changes until M4 is accepted.

| Item/task | Status | Blocker and evidence | Unblock condition / owner | Shared files or decision dependencies | Next independent task |
|---|---|---|---|---|---|
| PCM WAV file metrics | offline-ready | Synthetic PCM 8/16/24/32-bit tests cover aggregate/per-channel peak, RMS, DC, and bounded `[start, end)` windows rounded to nearest frame; out-of-range or malformed windows fail explicitly. No actual Live capture/readback tested. | Add a verified real-capture artifact and scratch-Set readback gate; Live operator/integrator. | M6 tool registration will touch `src/enableton/tools.json`, now present from M4 base `bd023bf`; integration remains parked. | Consider further offline source metrics only where the SPEC provides a clear measurement contract. |
| Recipe pattern parser and v1 validator | offline-ready | Synthetic tests cover format, required fields, documented `hit`/`layer` modes, bar divisibility, duplicate lane/slot identifier rejection, and optional source metadata (kind, file, window, confidence); no MIDI scheduling, clip writing, or recipe tools. | Integrator wires recipe handlers/catalog after M4 shared files are available. | `tools.json`, modes/catalogue tests are now present from M4 base `bd023bf`; integration remains parked. | Continue pure recipe data validation; catalog/mode integration remains blocked. |
| Recipe JSON store | offline-ready | Temporary-directory tests cover list/show/save/override/delete; default application config path is intentionally not selected, and storage is not registered as a tool. | Configuration owner selects/implements the supported user data directory; integrator registers recipe tools. | Planned `%APPDATA%\\Enableton` location is not implemented in the base; registration uses the candidate `tools.json`; integration remains parked. | Recipe schema edge cases that do not choose global paths. |
| M6 meter polling, resample capture, routing verification, spectral/loudness analysis, master compare/device audition | Live-gated | No Live API probing or captured audio is available under this offline assignment; fake tests would not establish LOM semantics. | Approved scratch-Set probes with real Live readback, capture file verification, and explicit failed-arm exercise; Live operator. | Runtime catalogue plus Remote Script handler surfaces; the latter also contains concurrent M4 work. | Continue a separate offline, file-only analysis increment. |
| M7 generation audition/accept/discard and Browser-backed recipe build/learn | Live-gated | No Browser load, scratch-preview scene, audition, or real clip write has been exercised. | Approved scratch-Set probes with identity guards/readback and Browser-backed sample provenance; Live operator/integrator. | Catalogue/modes and Remote Script handler surfaces; do not collide with M4 changes. | Continue pure recipe data validation and offline sample-analysis utilities. |
| M6/M7 runtime catalogue registration and mission reconciliation | reconciled, parked | M4 accounting base `bd023bf` is merged into this branch; the M4 owner confirmed the base and landed the accounting correction. MISSION/SPEC retain both M4 and M6/M7 content. Full offline suite: **445 passed, 42 subtests**; no M6/M7 runtime tools are registered. M4 accounting branch `7de7e66` is superseded; M5 `c57edc7` remains separate. | M4 acceptance; then integrate M5 and decide M6/M7 runtime. Runtime handlers still require their scratch-Set gates. | `tools.json`, modes, catalogue tests and Remote Script are parked for M6/M7 registration. | Continue pure offline M6/M7 work only; no shared-file edits. |

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

No Live, setup, doctor, or Live tool was run for these slices. This ledger records offline work on
the reconciled branch only; it does not claim M6/M7 acceptance or Live verification.
