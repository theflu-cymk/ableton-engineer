# Release readiness

**Status:** template and current assessment, 2026-11-12. **This product is not release-ready.**
An unchecked item is a blocker, not a task someone may assume is done.

**Legend:** `[x]` verified with named evidence; `[~]` partially exists but lacks the required proof;
`[ ]` not done; `[blocked]` needs an owner/input that does not exist in the repo.

## Product and scope

- [~] Product shape: MCP + `produce`, with the additive local panel. D-18 is accepted for this
  build; the release commitment still needs owner approval (D-02/D-03).
- [ ] Target user, OS, Live edition/version and MCP client versions stated and tested.
- [ ] One real producer workflow demonstrated end to end on a backed-up scratch Set.
- [ ] One-user beta completed with consent; feedback and blockers dispositioned.
- [ ] Public/private release channel and owner go/no-go recorded.

## Setup, safety and compatibility

- [~] `setup` installs the Remote Script; clean-machine install transcript does not exist.
- [~] `doctor` reports connection, script version, build, port, counters and stale state.
- [ ] Unsupported Live/OS/client versions rejected before any write, with actionable recovery text.
- [ ] Port selection/conflict handling is tested or a fixed-port deviation is explicitly approved.
- [ ] Fresh install, replacement, modified-install refusal, rollback, restore and uninstall are
  verified.
- [ ] MCP client config is generated from the actual path and tested with approved clients.
- [x] The engine does not write a user `.als` in place by design; scratch/executor paths exist.
- [x] Producer writes use dry-run/undo/scratch; a two-take panel apply, fader A/B and undo were
  verified on a backed-up scratch Set, including removal of both copies and source-volume restore.
- [x] The panel binds loopback only, serves no external assets, and its preview tokens are in-memory,
  single-use and expiring.
- [x] Real panel mute apply/undo on a scratch Set: preview, read-back and restore verified; the
  scratch `.als` SHA-256 was unchanged. See [../panel.md](../panel.md#live-acceptance-record).
- [ ] Installation and every setup/test path leave the open Set unchanged; record proof.

## Workflow proof

### Analyze and tidy

- [x] `session_brief` has a real Live read.
- [~] `session_brief` has not been run on the saved 25-track song during this slice.
- [~] Existing inspect/repair tools have historical Live gates; current build re-proof incomplete.
- [ ] One producer-facing before/after evidence record exists.

### Make and choose a take

- [x] `takes_create` dry-run verified on real Live.
- [x] Real panel apply verified: two named take tracks created with isolated faders.
- [x] Fader A/B verified; both copies removed and source volume restored by the returned undo tokens.
- [ ] `takes_select` / `takes_discard` implemented.
- [ ] One real variation implemented; identical copies are not a variation.
- [x] Producer-facing A/B evidence recorded in [../panel.md](../panel.md#live-acceptance-record).

### Panel

- [x] `enableton panel` starts a loopback page; status, session, tracks, takes and static assets
  were exercised against real Live.
- [x] A real dry-run/apply/undo of one mute field passed on a backed-up scratch Set.
- [x] Real panel take apply, A/B and undo passed on the scratch Set.
- [ ] Manual UI click-through of every row action and panel take select/discard are not verified.

### Reference and sound

- [x] `reference_analyze` measured a real capture with basic and advanced values.
- [~] Capture → compare → targeted change is not an integrated producer flow.
- [ ] One real reference-driven change is applied, read back and reversed.
- [ ] Measurement vs audition is clearly separated in user-facing copy.

## Preservation and support

- [~] Scratch backup and transaction undo exist in the existing engine.
- [ ] User-confirmed safe save/copy flow exists.
- [ ] Backup location, retention and restore instructions match observed behavior.
- [ ] Support contact and response expectation supplied.
- [ ] Uninstall leaves Sets/source media intact and is documented.

## Release materials

- [x] Repository README exists.
- [~] Quick start/troubleshooting are partial; release version/behavior not certified.
- [ ] `LICENSE` present and appropriate; EULA reviewed.
- [ ] Privacy policy and data-flow audit supplied, including any optional external processing.
- [ ] Refund policy supplied/reviewed.
- [ ] Support email/contact present and monitored.
- [ ] Changelog current for the shipped build.
- [ ] Real producer demo video recorded, reviewed and consented.
- [ ] Clean repository: no Sets, credentials, private reports, `tmp/` artifacts or unlicensed media.
- [ ] Package/Remote Script/protocol versions consistently labeled for release.
- [ ] All ten external launch checklist items traced to evidence.

## Current blockers

1. **No approved product shape.** D-02/D-03 are proposals.
2. **No A/B select/discard tool.** Producers must use raw fader values for the A/B switch.
3. **No integrated reference workflow.** Measurement exists; capture-to-change does not.
4. **No setup/compatibility/client UX** matching the release checklist.
5. **No legal/privacy/support assets.** Do not invent them.
6. **No beta or demo.** Both are external deliverables.
7. **Version scheme unresolved.** Package `0.1.0` and Remote Script `0.4.26` are not the same thing.
8. **Documentation drift.** AGENTS/MISSION/mcp docs contain stale status lines; this pack records the
    current interpretation but does not rewrite historical evidence.

## Evidence rules

- Name the command, target Set/path, build and date for every real-Live claim.
- Label fake/unit, real-Live readback and audition separately.
- Do not use a test count as proof of behavior; do not quote a fixed suite count in release copy.
- Do not claim compatibility from one machine.
- Do not claim a feature is audible because a file measured differently.
- A failed or partial run is evidence; report it.

## Sign-off

| Role | Name | Decision/date | Evidence or blocker |
|---|---|---|---|
| Product owner |  |  |  |
| Engineering owner |  |  |  |
| Support owner |  |  |  |
| Legal/privacy reviewer |  |  |  |
| Release owner |  |  |  |
| Go/no-go |  |  |  |

A public release requires all owners above. Missing names are blockers, not formatting gaps.
