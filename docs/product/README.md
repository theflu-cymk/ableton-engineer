# Enableton product pack

**Status:** integration draft, 2026-11-13. This pack describes the current tree and the product
direction; it is not a release certificate.

**Evidence tags used in this pack:** **[Verified]** means a command, source file, real-Live read or
artifact was checked; **[Assumed]** means a planning assumption; **[Unverified]** means the claim
has not been run on the required surface.

## Read this in order

1. **[HANDOFF.md](HANDOFF.md)** — what a new team or LLM needs to start safely.
2. **[AGENT_WORKSTREAMS.md](AGENT_WORKSTREAMS.md)** — how four agents split, branch, check in and merge.
3. **[CURRENT_STATE.md](CURRENT_STATE.md)** — what is actually implemented and measured today.
4. **[PRD.md](PRD.md)** — the proposed MVP and its acceptance criteria.
5. **[DECISIONS.md](DECISIONS.md)** — what is approved, proposed, open or blocked.
6. **[ROADMAP.md](ROADMAP.md)** — the recommended sequence and immediate next tasks.
7. **[RELEASE_READINESS.md](RELEASE_READINESS.md)** — the release owner's evidence checklist.

The technical design remains in [../../SPEC.md](../../SPEC.md), project conventions in
[../../AGENTS.md](../../AGENTS.md), and the current producer slice in
[../producer-layer.md](../producer-layer.md). If a product document conflicts with `SPEC.md` on
technical design, stop and reconcile; do not silently pick one.

## The one-sentence direction

Enableton should be a **producer-facing MCP workflow** — Analyze, Suggest, Create take — backed by
real Live reads and reversible writes, with a local panel as an additive front door. It is not a
larger tool menu and not a standalone DAW.

## Current snapshot

- **[Verified]** Repository: `Enableton`, package version `0.1.0`, branch `main`; baseline
  `a473577`, with the panel implementation committed.
- **[Verified]** Live 12.2.5, Remote Script `0.4.26`, build `a7fcd016f88d`, connected, `errors 0`,
  not stale at the 2026-11-13 check.
- **[Verified]** The open Live Set is the unsaved `SCRATCH fortnight - panel acceptance` copy: 32
  main tracks plus 2 returns. An unfreeze-tracks prompt was accepted in memory; the on-disk file is
  unchanged. The original working Set was not opened or written.
- **[Verified]** Catalogue: 89 tools in 9 modes. `produce` is one of them and contains 21 resolved
  tools. The producer headline tools are `session_brief`, `reference_analyze`, `takes_create`,
  `takes_select` and `takes_discard`.
- **[Verified]** The full fake suite passed after this slice. A green fake suite is **not**
  real-Live proof.
- **[Verified]** The producer slice has real evidence for a read-only brief, a take dry-run, a
  two-take panel apply with fader A/B and undo, panel select/undo and discard preview, a real WAV
  reference measurement and a panel mute apply/undo. No take was applied to a working Set. No
  audible test was run.
- **[Verified]** The local panel exists at `enableton panel`; it has Select and preview-only discard
  controls, no discard Apply button, no persistent memory and no take variation tool yet.
- **[Verified]** The tree has no `LICENSE`, EULA, privacy policy, refund policy, support contact or
  demo video. Those are release blockers, not documentation chores to invent.

## Why this pack exists

The Supreme Potato product documentation at
`E:\Projects\copilot-worktrees\EnAbleton\theflu-cymk-supreme-potato\docs\product` is a useful
**release and owner-decision framework**. It is also describing a **different codebase**:

| Dimension | Supreme Potato product docs **[Verified from that path]** | This checkout **[Verified from this repo]** |
|---|---|---|
| Product/code name | EnAbleton | Enableton |
| Backend | Pinned `mcp-server-ableton-live` package and generated Remote Script | Custom Python server + `remote_script/Enableton` |
| Reported version | `0.1.0b1`, upstream `1.8.1`, protocol `1.8.1-ext.15` | package `0.1.0`; Remote Script `0.4.26` |
| Tool count | 242 (156 upstream + 86 additions) | 89 catalogue entries at this snapshot |
| Port | 9877 | 9878 |
| Current focus | Commercial release checklist and owner decisions | Working Live engine plus the first producer slice |
| Strongest evidence | Release-gate framing and required business inputs | Real-Live protocol/write gates and the new producer workflow |

**Do not copy the external counts, version numbers, package architecture or setup claims into this
repo.** Use that pack for its release discipline: the ten launch milestones, compatibility matrix,
legal/privacy/support blockers, one-user beta and demo-video requirement.

## What is genuinely new here

The external pack defines three technical workflows: inspect/repair, arrangement editing, and
sound/device work. This checkout adds the product thesis that those capabilities should be reached
through producer language:

1. **Analyze** — make sense of the Set and a reference before asking for an edit.
2. **Suggest** — explain the next useful move with evidence, not a generic tool list.
3. **Create take** — produce a real, reversible alternative and let the producer choose.

The three external workflows remain the **release proof set**; the producer verbs become the
**experience** over them. That is the reconciliation this pack recommends.

## The best path forward, in one screen

1. **Do not migrate to the external package.** The current engine is already real-Live verified and
   has stronger write safety. Migrating would discard working gates.
2. **Finish the producer slice on a scratch Set** before adding more surface: apply one take set,
   verify A/B and undo, then add select/discard and one real variation.
3. **Make `produce` the demonstrated interface**, while leaving `auto` as the compatibility default
   until the product owner approves the change.
4. **Use the external release checklist without pretending it is satisfied.** Setup, compatibility,
   legal, support, demo and beta are still open.
5. **Treat the panel as an additive surface, not a replacement.** MCP/CLI remains the engine
   surface; the panel is the producer front door and exposes only documented safe actions.

## First action

Read [HANDOFF.md](HANDOFF.md), then run the baseline checks in its “First 30 minutes” section. Use the
current unsaved scratch Set only for reversible work; for another write gate, make a fresh backed-up
scratch copy of a real song and never apply to the working Set.
