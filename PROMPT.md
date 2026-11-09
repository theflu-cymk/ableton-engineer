# Build Prompt — "Ableton Engineer"

## Objective

Build a locally-run application that acts as the user's Ableton Live engineer: it reads the
user's Live Set, understands it, answers questions about it, and performs multi-step production
work on the user's behalf. Design it so the capability surface can grow for years without the
core being rewritten.

Deliver in this order: a capability map, then an architecture that can carry it, then the
smallest end-to-end vertical slice. Do not start with UI.

---

## 1. Modularity — required structure

- **Everything that touches Live is a Capability**, declared as data, not as ad-hoc code paths:
  `{ id, description, params schema, preconditions, reads/writes, required adapter feature,
  live-version floor, undo strategy, dry-run support }`.
- **One registry.** Capabilities self-register by module import or directory scan. Adding a
  capability must require zero edits to core files — no central `switch`, no growing `if/else`
  chain, no god-object "AbletonService".
- **One executor.** No capability may talk to the Ableton bridge, filesystem, or network
  directly. All effects funnel through a single executor that owns validation, dry-run,
  transaction boundaries, logging, and rollback.
- **Interfaces at every seam.** Intent interpretation, planning, capability execution, Live
  adapter, persistence, and audio analysis each sit behind a typed interface with at least two
  plausible implementations (one may be a fake used in tests). Domain code imports interfaces
  only, never concrete adapters.
- **No hidden coupling.** Capabilities compose by declaring dependencies on other capabilities
  or on read-model queries, not by calling each other's internals. No circular imports.

## 2. Expandability — required structure

- **Adapter layer, not a single integration.** One `LiveAdapter` interface (read model + mutation
  primitives + capability introspection), with multiple backends behind it. The same app must be
  able to run on whichever surface the user's Live edition can support.
- **Runtime capability detection.** At startup the adapter reports what it supports. A capability
  whose requirements are unmet reports `unavailable` with a human-readable reason; it never
  throws at call time and never silently does a different thing.
- **Version-tolerant.** Probe the Live build and adapter features; degrade gracefully instead of
  assuming one version forever. Record detected versions in the app's diagnostics.
- **Extension points documented.** README explains, concretely, how to add a new capability, a
  new adapter, and a new domain with worked examples.

## 3. Efficiency — "no duplicated processes, no wasted work"

This section is testable. Treat each line as an acceptance criterion, not a sentiment.

- **Single ownership of each resource.** Exactly one process owns the Live connection. No module
  may open its own socket, spawn its own helper, or instantiate its own client. Injected singleton,
  owned by the app entrypoint.
- **Single scheduler.** One timer/scheduler owns all recurring work. No competing polling loops.
  No `setInterval` anywhere outside the scheduler module.
- **Idempotent startup.** Running setup twice (or reconnecting) yields one connection, one
  registration per capability, one background worker. Duplicate registration must fail a test.
- **Read once, share.** Live Set state is read into a single cached snapshot with explicit
  invalidation after mutations. Capabilities query the snapshot; they do not rescan the Set
  independently. Same rule for the sample index and any audio analysis cache.
- **No duplicate capability implementations.** Two capabilities with the same effect and
  overlapping preconditions is a defect — the registry must reject it in tests.
- **One plan per request.** A user request resolves to a single plan and executes once. Emit a
  per-request trace (steps, cache hits, elapsed) so repeated work is visible, not guessed at.
- **Measured, not asserted.** Any performance claim in your report needs a number you produced:
  process count, timer count, snapshot read count, wall time before/after.

## 4. Platform reality — design against these facts, then verify them

Ableton exposes several surfaces with very different reach. Do not design a plan that assumes
one surface does everything.

- **Extensions SDK** (JS/TS, runs in Node beside Live; Live 12.4.5+ **Suite beta**):
  read/write tracks, clips, scenes, cue points, device parameters, MIDI notes; create audio clips
  from files; render a track's pre-FX arrangement audio to WAV; tempo/scale/grid reads; modal
  HTML UI panels; full Node access (fs, net, child processes).
  **Limits:** run-once per invocation, no observers/events; **no transport control** (no play,
  stop, record, clip/scene launch); no automation envelope read/write; built-in devices only (no
  third-party plug-in insertion); not real-time.
- **Python Remote Script + Live Object Model over a local socket** (AbletonOSC / LiveMCP pattern):
  transport, clip/scene launching, change observers, browser and sample access, much fuller object
  model; no Suite requirement; but user-installed and fragile across Live versions.
- **Max for Live:** real-time observers, transport, audio/MIDI in the signal path, custom devices.
  Requires Suite + M4L; runs inside Live.
- **Ableton Link:** tempo/phase/start-stop sync between apps. Not a control API.

**Consequence:** no single surface covers "Ableton engineer." Build one `LiveAdapter` interface
and at least two backends (Extensions + Remote Script and/or M4L), selected by detection. This is
the main reason the adapter seam exists.

**Verify before building.** Confirm each dimension above against the user's actual installed Live
edition and version. Record findings in `CAPABILITIES.md`. If reality differs from this prompt,
update the document and your plan — do not silently work around it.

## 5. Capability exploration — deliverable before implementation

Produce `CAPABILITIES.md`:

1. Matrix of candidate engineer capabilities → which surface provides it → difficulty → risk →
   what is impossible today.
2. A ranked shortlist for the first release, with reasoning.
3. Explicit list of workarounds needed for gaps.

Candidate domains to evaluate:

- **Set understanding:** summarise structure, sections, tempo/key, device chains, routing, unused
  material, mix problems. Read-only, high value, lowest risk — start here.
- **Arrangement & composition:** section reordering, clip duplication/consolidation, silence
  trimming, fill generation, MIDI transforms (voicing, strum, humanise, quantise variants).
- **Mix & gain staging:** level, pan, sends, group routing, headroom analysis, mix snapshots.
- **Metering & loudness:** requires metering path (M4L meters or captured audio), not the
  Extension API.
- **Audio analysis:** key/BPM detection, similarity, stem separation — note Live's stem separation
  is UI-only, so this needs external processing on rendered stems.
- **Browser & sample search:** tag/index local libraries, find alternatives to a sound in use.
- **Racks, macros, mapping:** build/map instrument and effect racks; note built-in-device limit.
- **Automation generation:** blocked in the Extension API today — plan around it (upfront editing,
  M4L, or Remote Script) rather than discovering it mid-build.
- **Transport & performance:** launching scenes/clips, setlist ordering, live cueing — requires
  M4L or Remote Script; never route this through Extensions.
- **Session hygiene:** collect-all-and-save, versioned saves, backup snapshots, project auditing,
  dead-file detection.
- **Undo & transactional safety:** Live's undo is linear; multi-step edits need snapshot-based
  rollback of your own.
- **Render & bounce automation:** stem renders, version bounces, delivery formatting.
- **Conversational layer:** natural-language intent → plan; memory of the user's taste, project
  history, and preferences, stored outside the Live Set.

## 6. Safety rules for anything that touches the user's Sets

- Dry-run / plan preview for every destructive or bulk operation, with an explicit confirm.
- Save a copy before multi-step destructive edits; support rollback.
- Never overwrite user files in place. Write to a staging directory and move deliberately.
- No hardcoded machine paths; all paths come from config with sane Windows defaults.
- Structured errors with the failing step, and a request log the user can read.

## 7. Milestones and definition of done

- **M0 — Findings.** `CAPABILITIES.md`, adapter interface, registry design, risk list. No
  implementation. Stop and show this.
- **M1 — Read path.** One adapter, read-only: dump a Set summary and answer three real questions
  about the user's own project.
- **M2 — Write path.** Two capabilities end-to-end on a scratch Set, with dry-run, rollback, and a
  test each.
- **M3 — Second adapter.** Prove the interface is real by adding a second backend with no changes
  to domain code.
- **M4 — Efficiency audit.** Process/timer counts, snapshot reads per request, duplicate-work
  check, before/after numbers.

## 8. Working agreements

- Small, reviewable increments; one concern per change.
- Tests required for registry invariants (no duplicates, params validate, preconditions gate) and
  for dry-run/bypass behaviour.
- Every new dependency justified in one line; prefer the standard library and what is already
  installed.
- When a requirement conflicts with platform reality, say so and propose the alternative. Never
  fake a capability or stub it as if it worked.
- Ask only blocking questions before M0; otherwise state assumptions and proceed.
- Declare explicit non-goals for this phase (e.g. real-time performance control, cloud sync, UI
  polish) so scope creep is visible.

## 9. Open questions to resolve in M0

- Which Live edition and exact version is installed? (Decides whether Extensions is even available.)
- Is real-time performance control in scope, or studio/arrangement work only?
- Is an LLM expected for intent parsing, and is its key already available?
- Which surface will the user actually install — Extension, Remote Script, or both?
- Where should assistant memory live (files, local DB)?
