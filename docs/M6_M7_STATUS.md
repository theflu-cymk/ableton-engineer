# M6/M7 implementation status

Offline-only progress ledger. **Fake/synthetic tests and file analysis are not Live verification.**
Branch `theflu-cymk-m6-audio-tools` is based on `5761472b6c77a9e4360a004daee832bca3102677`.
Latest observed authoritative `main`: `ce3132f4c85c1be0e14222d480c8dfed49e60d8c`.

| Item/task | Status | Blocker and evidence | Unblock condition / owner | Shared files or decision dependencies | Next independent task |
|---|---|---|---|---|---|
| PCM WAV file metrics | offline-ready | Synthetic PCM 8/16/24/32-bit tests cover aggregate/per-channel peak, RMS, DC, and bounded `[start, end)` windows rounded to nearest frame; out-of-range or malformed windows fail explicitly. No actual Live capture/readback tested. | Add a verified real-capture artifact and scratch-Set readback gate; Live operator/integrator. | M6 tool registration will touch `src/enableton/tools.json`, currently changed by M4 on main. | Consider further offline source metrics only where the SPEC provides a clear measurement contract. |
| Recipe pattern parser and v1 validator | offline-ready | Synthetic tests cover format, required fields, documented `hit`/`layer` modes, bar divisibility, and duplicate lane/slot identifier rejection; no MIDI scheduling, clip writing, or recipe tools. | Integrator wires recipe handlers/catalog after M4 shared files are available. | `tools.json`, modes/catalogue tests are M4-active on main; do not edit or merge here. | Continue pure recipe data validation; catalog/mode integration remains blocked. |
| Recipe JSON store | offline-ready | Temporary-directory tests cover list/show/save/override/delete; default application config path is intentionally not selected, and storage is not registered as a tool. | Configuration owner selects/implements the supported user data directory; integrator registers recipe tools. | Planned `%APPDATA%\\Enableton` location is not implemented in the base; registration uses M4-active `tools.json`. | Recipe schema edge cases that do not choose global paths. |
| M6 meter polling, resample capture, routing verification, spectral/loudness analysis, master compare/device audition | Live-gated | No Live API probing or captured audio is available under this offline assignment; fake tests would not establish LOM semantics. | Approved scratch-Set probes with real Live readback, capture file verification, and explicit failed-arm exercise; Live operator. | Runtime catalogue plus Remote Script handler surfaces; the latter also contains concurrent M4 work. | Continue a separate offline, file-only analysis increment. |
| M7 generation audition/accept/discard and Browser-backed recipe build/learn | Live-gated | No Browser load, scratch-preview scene, audition, or real clip write has been exercised. | Approved scratch-Set probes with identity guards/readback and Browser-backed sample provenance; Live operator/integrator. | Catalogue/modes and Remote Script handler surfaces; do not collide with M4 changes. | Continue pure recipe data validation and offline sample-analysis utilities. |
| M6/M7 runtime catalogue registration and mission reconciliation | integration-blocked | Current branch base is `5761472`; main is `ce3132f`. Since base, main changes `MISSION.md`, `src/enableton/tools.json`, `tests/test_catalogue_expansion.py`, `remote_script/Enableton/server.py`, and `remote_script/Enableton/handlers/tracks.py`. | Coordinate an integration pass after M4 settles; preserve its current edits and refresh the base rather than overwrite them. | All listed files; especially MISSION/catalogue and Remote Script handler registration. | Stay on non-overlapping offline code and tests. |

### 2026-11-11: duplicate recipe identifiers

`validate_recipe` now rejects two lanes that reference the same slot ID and two slot definitions that
use the same slot ID. Focused synthetic tests: **37 passed, 20 subtests**; `compileall` and
`git diff --check` passed. No Live, catalogue, mode, or Remote Script change was made for this slice.

No Live, setup, doctor, or Live tool was run for these slices. This ledger records work on the isolated
branch only; it does not claim M6/M7 acceptance or integration.
