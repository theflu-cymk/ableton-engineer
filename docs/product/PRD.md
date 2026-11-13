# Enableton MVP product requirements

**Status:** integration draft, 2026-11-12. Owner decisions are in [DECISIONS.md](DECISIONS.md).
**Technical authority:** [../../SPEC.md](../../SPEC.md) owns design; this document owns product scope.
**Release input:** the Supreme Potato launch checklist, reconciled in [ROADMAP.md](ROADMAP.md).

## Product summary

Enableton is a local MCP server that lets a producer use an AI client to understand a real Ableton
Live Set, make a small reversible change, and hear or inspect the result. The product should feel
like a **co-producer with context, alternatives and proof**, not a catalogue of 87 commands.

The MVP is a **technical MCP tool with a producer-facing `produce` mode**. It is not a standalone
DAW, a hosted service, a replacement for Live, or a promise of unlimited LOM access.

## Product decision proposal

| Question | Recommendation | Status |
|---|---|---|
| Standalone app or MCP tool? | MCP server with producer workflow mode | Proposed, needs owner approval |
| Primary surface | `enableton serve --mode produce` | Proposed |
| Engine | Keep the current custom Enableton server/Remote Script | Proposed |
| Panel | Local loopback panel as an additive surface; no separate app | Implemented for this build; release shape proposed |
| Release | One-user beta before public | Open |

The local loopback panel is implemented and documented in [../panel.md](../panel.md). A separate
in-Live or standalone app remains a different product shape with its own UX, packaging and support
scope; it is not part of this MVP.

## Target user

Independent producers who:
- use Ableton Live 12 on Windows;
- are comfortable installing a Python tool and selecting a Control Surface;
- already use an MCP-capable assistant;
- want help with a bounded production decision, not a fully automatic song generator;
- will report reproducible issues and can preserve/back up their own Sets.

The initial supported matrix is **not yet approved**. Windows + Live 12.2.5 is the development
environment, not a universal compatibility promise.

## Problem

A producer does not need another list of tools. They need answers to:
- What is in this Set, and what is actually happening in the section I care about?
- What is the next useful move, and why?
- Can I hear an alternative without destroying the current version?
- How does my take or mix compare with a reference?
- How do I undo this and get back to where I was?

The current engine can answer many low-level questions, but the producer experience still requires
knowing tool names, JSON arguments and dry-run conventions. The MVP closes that gap with a small
producer vocabulary and a safe first workflow.

## Product thesis: Analyze / Suggest / Create take

### Analyze

Read one snapshot and return a producer brief: sections, roles, density, sparse areas, duplicate
names, empty tracks and next actions. This is context, not a score.

**Current:** `session_brief`.

### Suggest

Offer evidence-backed next actions and measured comparisons. Do not invent a “better” arrangement,
claim to hear anything, or hide a tool list behind prose.

**Current:** `session_brief.next_actions`, reference deltas, existing diagnostics. There is no
separate generative suggestion engine yet.

### Create take

Duplicate a real track into named alternatives, leave one audible, lower the others, and make the
operation reversible. The producer chooses what to keep.

**Current:** `takes_create` duplicate workflow with a verified real apply, fader A/B and undo on a
scratch Set. Takes are identical until edited; select/discard/variation are planned, not present.

## MVP workflows

The external release checklist requires three reliable workflows. We keep those as the proof set,
but wrap them in producer language.

### Workflow A — Analyze and tidy

**Producer sentence:** “Tell me what is going on in this Set, then show me the safest cleanup.”

1. Read the Set with `session_brief`.
2. Point at sections/tracks with evidence.
3. Show bounded cleanup actions from existing inspect/repair tools.
4. Do not auto-apply `needs_listening` changes.
5. End with a before/after count and a preserved original.

**External mapping:** inspect/repair.

### Workflow B — Make and choose a take

**Producer sentence:** “Give me two versions of this bass line and let me A/B them.”

1. Resolve a unique track.
2. Dry-run `takes_create` and show planned names, indices and fader changes.
3. Apply only on a backed-up scratch Set.
4. A/B with a dedicated select tool (planned) or `tracks_set_volume` as the interim.
5. Undo and verify the original track/fader state.

**External mapping:** arrangement editing.

### Workflow C — Shape against a reference

**Producer sentence:** “Compare this capture with my reference and help me choose one targeted
change.”

1. Capture a bounded section through the existing resample path.
2. Measure it with `reference_analyze`; compare a reference file.
3. Show deltas, unavailable values and limitations.
4. Suggest one bounded track/device change, not a mastering promise.
5. Apply, re-read, and undo on failure.

**External mapping:** sound/device work.

## Functional requirements

| ID | Requirement | Current status |
|---|---|---|
| FR-1 | Install the Remote Script into the actual User Library; explain Control Surface selection and Live restart. | `setup` exists; clean-machine proof missing |
| FR-2 | First-run diagnostics show package, running script, build digest, port and compatibility; unsupported versions fail before writes. | `doctor` shows script/build/port; no compatibility gate or first-run UX |
| FR-3 | Generate usable MCP client configuration from the actual install path for approved clients. | Absent / unverified |
| FR-4 | `session_brief` returns sections, roles, issues and next actions from one snapshot. | Implemented; real blank-Set read verified |
| FR-5 | `reference_analyze` returns basic WAV measurements and optional advanced values, with explicit unavailable reasons. | Implemented; real WAV verified |
| FR-6 | `takes_create` plans and creates real named duplicate takes with dry-run, undo and rollback. | Dry-run and real apply/A-B/undo verified on a scratch Set |
| FR-7 | The producer can select/discard takes without editing fader numbers. | Planned; not implemented |
| FR-8 | Takes can become real alternatives through a bounded variation operation. | Planned; not implemented |
| FR-9 | Capture → compare → one bounded change works as a producer flow. | Pieces exist; orchestration missing |
| FR-10 | Every write identifies a fresh target, preserves the original and reports partial failure honestly. | Existing safety invariants; producer workflow not fully gated |
| FR-11 | A local “where did we leave off” memory records goal, decisions and accepted takes outside the `.als`. | Planned; not implemented |
| FR-12 | Release materials include setup, troubleshooting, changelog, legal/privacy/support inputs and version labels. | README exists; legal/support/demo/version decisions open |

## Non-functional requirements

- **Safety:** no user `.als` in place; dry-run and undo for bulk writes; scratch copy before a real
  apply; no hidden write when a capability is unavailable.
- **Evidence:** separate fake tests, real-Live readback and audition. A measurement is not a
  listening test. A green suite is not product proof.
- **Recoverability:** show where the scratch copy is; document restore and uninstall.
- **Compatibility:** fail closed outside an approved matrix.
- **Privacy:** local processing by default; audit any optional external service before making a
  claim. Do not invent a policy.
- **Support:** no release until an owner supplies a contact and response expectation.
- **Accessibility/clarity:** every screen/flow has a text form; no producer step depends on reading
  raw JSON.

## Acceptance criteria

### Product-level

- A producer can start a session, get a brief, create a take and undo it without seeing the full
  tool catalogue.
- One real sentence-to-outcome demo runs end to end on a backed-up scratch Set.
- The producer can see why the action was suggested, what changed and how to undo it.
- No working Set or source WAV is modified without explicit apply.
- The product never claims it heard something it only measured.

### Evidence-level

- `session_brief` on a real Set has a named real-Live call and a fresh read-back.
- `takes_create` dry-run matches the applied plan, and undo restores the source and removes the take
  tracks; this passed through the panel on a backed-up scratch Set.
- `reference_analyze` reports a real capture and clearly separates measured/unavailable fields.
- A real fader A/B selection changes what is audible, and undo restores the source; panel select/discard
  is still absent.
- Setup has a clean-machine transcript, not just a command list.
- Compatibility, legal, support and beta gates have named owners and evidence.

### Definition of done

A feature is not done because the fake suite is green. It is done when the milestone's named
real-Live call returns real data and the human-visible limitation is recorded.

## Out of scope for this MVP

- A polished in-Live panel or standalone app.
- Automatic song generation or “make it radio-ready” promises.
- Mastering, stem separation, render/bounce, cloud sync, multi-user collaboration.
- Full plug-in parameter access, hidden device controls, or GUI automation.
- A universal Live/OS/client compatibility claim.
- Invented legal terms, support addresses or refund policies.
- A public Gumroad launch before the checklists and beta are complete.

## Success metrics

Use measurements, not vibes:

- Time from install to a healthy `doctor` on a clean supported machine.
- Percentage of producer sessions that complete without an undocumented manual fix.
- Number of real-Live gates with a named command and read-back.
- Take apply/undo success rate on a scratch Set.
- Number of release blockers with an owner and evidence.
- Beta participant completion of each of the three workflows.

Do not set a public date before D-10 (release channel), D-11 (matrix), D-13 (legal/support) and D-15
(demo) have owners.

## Open product questions

1. Is the MVP shape approved: MCP + producer mode, with the local panel as an additive surface?
2. Which exact Live editions/versions, Windows versions and MCP clients are supported?
3. Is the first release a one-user beta or a public launch?
4. Who owns legal/privacy/refund/support inputs?
5. What is the public name and version scheme?
6. Is the additive panel accepted as part of the release shape, and what does it imply for support
   and compatibility?
7. Which real song may be used for the demo and beta, with consent?
