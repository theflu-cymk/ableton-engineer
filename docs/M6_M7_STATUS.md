# M6/M7 implementation status

Offline-only progress ledger. **Fake/synthetic tests and file analysis are not Live verification.**
Branch `theflu-cymk-m6-audio-tools` integrates candidate local `main`
`a4d9681f3d07482f7e232c7c76f5133cbf508f63` as of 2026-11-11; that base is **unconfirmed** until
the M4 owner verifies it is still the intended integration point. Its original base was
`5761472b6c77a9e4360a004daee832bca3102677`.

**Parked:** MISSION/SPEC record the merge for history, but this ledger does not treat `a4d9681` as
approved integration. Do not add M6/M7 catalogue, mode, catalogue-test or Remote Script changes
until the M4 owner confirms the base and ownership.

| Item/task | Status | Blocker and evidence | Unblock condition / owner | Shared files or decision dependencies | Next independent task |
|---|---|---|---|---|---|
| PCM WAV file metrics | offline-ready | Synthetic PCM 8/16/24/32-bit tests cover aggregate/per-channel peak, RMS, DC, and bounded `[start, end)` windows rounded to nearest frame; out-of-range or malformed windows fail explicitly. No actual Live capture/readback tested. | Add a verified real-capture artifact and scratch-Set readback gate; Live operator/integrator. | M6 tool registration will touch `src/enableton/tools.json`, now present from candidate `a4d9681`; integration remains parked. | Consider further offline source metrics only where the SPEC provides a clear measurement contract. |
| Recipe pattern parser and v1 validator | offline-ready | Synthetic tests cover format, required fields, documented `hit`/`layer` modes, bar divisibility, and duplicate lane/slot identifier rejection; no MIDI scheduling, clip writing, or recipe tools. | Integrator wires recipe handlers/catalog after M4 shared files are available. | `tools.json`, modes/catalogue tests are now present from candidate `a4d9681`; integration remains parked. | Continue pure recipe data validation; catalog/mode integration remains blocked. |
| Recipe JSON store | offline-ready | Temporary-directory tests cover list/show/save/override/delete; default application config path is intentionally not selected, and storage is not registered as a tool. | Configuration owner selects/implements the supported user data directory; integrator registers recipe tools. | Planned `%APPDATA%\\Enableton` location is not implemented in the base; registration uses the candidate `tools.json`; integration remains parked. | Recipe schema edge cases that do not choose global paths. |
| M6 meter polling, resample capture, routing verification, spectral/loudness analysis, master compare/device audition | Live-gated | No Live API probing or captured audio is available under this offline assignment; fake tests would not establish LOM semantics. | Approved scratch-Set probes with real Live readback, capture file verification, and explicit failed-arm exercise; Live operator. | Runtime catalogue plus Remote Script handler surfaces; the latter also contains concurrent M4 work. | Continue a separate offline, file-only analysis increment. |
| M7 generation audition/accept/discard and Browser-backed recipe build/learn | Live-gated | No Browser load, scratch-preview scene, audition, or real clip write has been exercised. | Approved scratch-Set probes with identity guards/readback and Browser-backed sample provenance; Live operator/integrator. | Catalogue/modes and Remote Script handler surfaces; do not collide with M4 changes. | Continue pure recipe data validation and offline sample-analysis utilities. |
| M6/M7 runtime catalogue registration and mission reconciliation | reconciled, parked | Candidate `main` `a4d9681` is merged into this branch, but is not confirmed as the integration point. MISSION/SPEC retain both M4 and M6/M7 content. Full offline suite: **441 passed, 27 subtests**; no M6/M7 runtime tools are registered. M4 accounting `7de7e66` and M5 `c57edc7` remain separate. | M4 owner confirms the base and ownership; then decide whether M4 accounting lands first. Runtime handlers still require their scratch-Set gates. | `tools.json`, modes, catalogue tests and Remote Script are parked for M6/M7 registration. | Continue pure offline M6/M7 work only; no shared-file edits. |

### 2026-11-11: reconciliation with candidate main (parked)

Merged local `main` `a4d9681f3d07482f7e232c7c76f5133cbf508f63` into this branch without overwriting
M4. The full offline suite is **441 passed, 27 subtests**; `compileall` and diff checks passed. The
offline M6/M7 foundations are present, but runtime registration and every Live gate remain pending.

### 2026-11-11: duplicate recipe identifiers

`validate_recipe` now rejects two lanes that reference the same slot ID and two slot definitions that
use the same slot ID. Focused synthetic tests: **37 passed, 20 subtests**; `compileall` and
`git diff --check` passed. No Live, catalogue, mode, or Remote Script change was made for this slice.

No Live, setup, doctor, or Live tool was run for these slices. This ledger records offline work on
the reconciled branch only; it does not claim M6/M7 acceptance or Live verification.
