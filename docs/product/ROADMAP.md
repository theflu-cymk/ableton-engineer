# Roadmap and gates

**Status:** integration draft, 2026-11-13. No dates: owner decisions and supported environments are
still open.

This roadmap is **implementation-first**, because the producer slice already exists and has partial
real-Live evidence. It still maps to the external ten-item launch checklist; it does not replace it.

## Principles

- Finish the producer loop before widening the catalogue.
- One real-Live acceptance call per feature; fake tests are internal consistency only.
- No working `.als` writes; use a backed-up scratch Set.
- Keep the current custom engine; do not migrate to the external package.
- Release claims require owners, evidence and a compatibility matrix.
- Do not set a public launch date until the blockers in [DECISIONS.md](DECISIONS.md) close.

## Phase 0 — Baseline and scope

**Goal:** a new team can start from a clean, understood tree.

The four-role split, branch/worktree commands and merge queue are in
[AGENT_WORKSTREAMS.md](AGENT_WORKSTREAMS.md).

- Commit the panel baseline and preserve the existing producer slice; exclude `tmp/` artifacts.
- Confirm `SPEC.md` / `AGENTS.md` / `MISSION.md` drift and this pack's authority.
- Run `uv run pytest -q`, `uv run enableton doctor`, `uv run enableton status --json`.
- Approve or reject D-02/D-03: custom Enableton MCP with producer mode as the MVP.
- Decide the public name and the supported matrix owner.

**Exit gate:** a new session has a baseline commit, a known test/doctor result and an approved or
explicitly open product shape. No code feature work starts on a dirty mystery tree.

## Phase 1 — Producer slice acceptance

**Goal:** prove the workflow that makes this product different.

- Run `session_brief` on a backed-up real song, not the blank Set.
- Run `takes_create` dry-run on a unique track; inspect the planned indices and faders.
- Apply one take set on the scratch copy; verify source/take volumes and A/B.
- Undo; verify the source and take tracks are restored.
- Apply one reference measurement to the capture produced by that session.
- Record exact commands, Set path, scratch-copy path and results.

**Exit gate:** one real sentence-to-outcome producer flow on a backed-up scratch Set; no working
song written; a named real-Live call for each step.

**Do not claim:** generated variations, audible improvement or panel take selection.

## Phase 2 — Producer usability

**Goal:** remove the need to know fader values and tool names.

The local panel has landed as the additive front door for the safe v1 actions. Do not widen it with
take select/discard or destructive operations until the underlying producer tools exist.

- Add `takes_select` (choose audible take) with explicit state.
- Add `takes_discard` with confirmation/irreversibility handling.
- Add one real `variation` path (velocity, transpose, duration or one device delta).
- Add local session memory: goal, decisions, accepted take and “where we left off”.
- Add a producer-facing reference/capture workflow, not a raw file path requirement.
- Decide whether `produce` becomes the default mode; keep `auto` until approved.

**Exit gate:** a producer can create, select, compare, keep and discard a take without editing raw
JSON or fader numbers; memory survives a server restart.

## Phase 3 — Setup, compatibility and clients

**Goal:** make installation and connection trustworthy.

- Clean-machine `setup` transcript using the actual User Library discovery.
- First-run diagnostics: package version, running script, build, port, compatibility.
- Fail-closed unsupported Live/OS/client gate before writes.
- Port conflict handling and an approved port policy.
- Uninstall/restore path that does not touch Sets or source media.
- Generated config for approved MCP clients (Claude Desktop/Cursor if those are the approved pair).

**Exit gate:** install → Control Surface → connect → `doctor` → uninstall/restore on a clean supported
machine, with no undocumented manual fix and no song modification.

## Phase 4 — Release workflow proof and preservation

**Goal:** evidence for the three external workflows and safe recovery.

- **Analyze/repair:** before/after findings, bounded repair, needs-listening exclusion.
- **Arrangement/take:** preview, apply, read-back, undo on a scratch Set.
- **Sound/device or reference:** parameter read-back, explicit unavailable controls, measurement
  separation.
- Safe save/copy flow, backup location, restore transcript and retention policy.
- Confirm no `.als` is modified by install, analysis, dry-run or failed apply.

**Exit gate:** each workflow has initial state, target, preview, apply, read-back, preservation and
limitations; fake and live evidence are labeled separately.

## Phase 5 — Release materials and business inputs

**Goal:** ship only what the owner can support.

- README/quick start/troubleshooting/changelog current for the shipped build.
- `LICENSE` and owner-reviewed EULA/privacy/refund terms; no invented policy.
- Support contact, response expectation and escalation path.
- Version scheme: package, Remote Script and protocol separately identified.
- Clean repository: no Sets, credentials, private reports, `tmp/` artifacts or commercial samples.
- Real producer demo video with consent and no private project data.

**Exit gate:** every required material is present and approved; no placeholder legal/support text;
repository scan is clean.

## Phase 6 — Beta and launch

**Goal:** one consenting producer proves the experience before public availability.

- Run a one-user beta on the approved environment.
- Record setup, all three workflows, failures, recovery and feedback.
- Resolve safety/data blockers and update claims.
- Public go/no-go only after all ten checklist items and owner sign-off.

**Exit gate:** signed release checklist; beta report; no unchecked blocker; public claims match the
tested matrix and demo.

## External checklist traceability

| External item | Phase | Current status |
|---|---|---|
| 1. User Library install + setup check + Control Surface | 3 | `setup` exists; clean-machine proof absent |
| 2. First-run config, port, version, uninstall | 3 | Partial diagnostics; no UX |
| 3. Claude Desktop/Cursor config | 3 | Absent |
| 4. Three reliable workflows + evidence | 1/4 | Producer slice partial; full proof absent |
| 5. Safe save/copy + backup | 4 | Scratch/undo exists; product flow absent |
| 6. README/troubleshooting/changelog/legal/support | 5 | README exists; legal/support absent |
| 7. Compatibility gate | 3 | Not implemented as a gate |
| 8. Demo video | 5 | Absent |
| 9. Clean repo + version consistency | 5 | Panel baseline committed; version scheme open |
| 10. Product-shape decision | 0 | Proposed, not approved |

## Immediate task queue

Do these in order unless an owner changes the priority.

1. **Preserve the committed baseline.** Keep the panel baseline clean; exclude `tmp/` artifacts and
   do not let the next session inherit an unexplained diff.
2. **Re-read the authoritative docs.** `SPEC.md`, `AGENTS.md`, this pack, `docs/producer-layer.md`.
3. **Run the baseline.** Full fake suite, `doctor`, `status --json`.
4. **Choose a safe song. [Done]** The panel acceptance used a backed-up scratch copy; the working
   Set was not opened. Use a fresh scratch copy for further writes.
5. **Prove the brief. [Done]** `session_brief` read the scratch Set; a broader song comparison remains
   useful before release.
6. **Prove the take dry-run. [Done]** `takes_create` planned two takes and wrote nothing.
7. **Apply one take set. [Done]** Panel apply, fader A/B and undo passed on the scratch copy; the
   `.als` hash was unchanged.
8. **Implement `takes_select` / `takes_discard`.** Use the existing transaction/undo conventions.
9. **Add one variation.** Keep it bounded and reversible; do not call identical copies variations.
10. **Build the capture → reference → one-change loop.** Measure; do not claim audition.
11. **Write the real workflow evidence** into `RELEASE_READINESS.md`.
12. **Record panel v1 as landed.** Keep setup/compatibility as the next surface work; do not widen
    the panel before `takes_select`/`takes_discard` exist.

## Exit criteria for this roadmap

The roadmap is complete when a one-user beta can install, connect, run the three workflows, recover
from a failure, and uninstall on the approved matrix — and the public release checklist is signed.
