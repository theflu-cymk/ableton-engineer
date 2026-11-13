# Enableton handoff

**Snapshot:** 2026-11-13. **Status:** integration draft; the working tree is not a release.
**Audience:** a new engineer, producer-operator or LLM taking over this repository.

Read [README.md](README.md) first for the product pack index, then this file, then
[CURRENT_STATE.md](CURRENT_STATE.md).

## The short version

Enableton is a custom Python MCP server that controls Ableton Live 12.2.5 through a Remote Script.
The engine has broad inspect/edit/mix/arrangement capability. The current product direction is
narrower: a producer should use **Analyze / Suggest / Create take**, not the full tool catalogue.

The producer slice exists but is only partly accepted:

- `session_brief` — real Live read verified.
- `reference_analyze` — real WAV measurement verified.
- `takes_create` — real dry-run, apply, fader A/B and undo verified on a backed-up scratch Set.
- `takes_select` / `takes_discard` — real select/undo and confirmed discard verified on the scratch Set.
- Local web panel — implemented, with real mute and take preview/apply/undo acceptance.
- No take variation and no persistent memory. Panel select/discard buttons are not implemented.

**Your first job is not to add features.** Preserve the committed baseline and review the take
acceptance record before adding variation.

## How to split the work

The team plan is [AGENT_WORKSTREAMS.md](AGENT_WORKSTREAMS.md). It defines four roles:

| Role | Branch | Outcome |
|---|---|---|
| **A0** integrator / release captain | `integration/producer-mvp` | Baseline, shared files, merge queue, Live gate token |
| **A1** producer core | `feat/producer-core` | take variation, panel take controls, real take gate |
| **A2** live / audio | `feat/live-audio` | Capture restore fix, Remote Script, real audio gate |
| **A3** setup / release / UX | `feat/setup-release` | Setup, compatibility, client config, release docs |

Do not have four agents share one checkout. Each gets a Git worktree and its own `uv` environment.
A0 owns `tools.json`, `modes.json`, `tools.py` and the merge queue; only A2 edits
`remote_script/`; only one agent may drive Live at a time. Read the plan before creating a branch.

## Authority: which document wins

| Question | Read | Precedence |
|---|---|---|
| Technical design | [../../SPEC.md](../../SPEC.md) | Design authority |
| Safety, install, LOM traps | [../../AGENTS.md](../../AGENTS.md) | Project convention |
| Current product/evidence | This pack, especially [CURRENT_STATE.md](CURRENT_STATE.md) | Current interpretation |
| Historical sequencing | [../../MISSION.md](../../MISSION.md) | Historical; status lines can be stale |
| Producer slice | [../producer-layer.md](../producer-layer.md) | Current slice and limits |
| MCP server details | [../mcp.md](../mcp.md) | Behavior evidence, but some versions/counts are stale |
| Troubleshooting | [../troubleshooting.md](../troubleshooting.md) | Counter triage before code changes |
| External release input | Supreme Potato `docs/product` path recorded in [README.md](README.md) | Requirements input; **not** this codebase |

If these conflict, stop and record the conflict. Do not silently pick the convenient one. In
particular, `AGENTS.md` still says `enableton serve` is a stub until M5; the current tree implements
stdio serve. `MISSION.md` still narrates an earlier tool count and milestone state.

## Current verified environment

| Item | Value |
|---|---|
| Repo | `Enableton`, package `0.1.0` |
| Branch / baseline | `main` / `a473577`; panel implementation committed |
| Python | 3.11.17 via `uv` |
| Live | Ableton Live 12.2.5 |
| Remote Script | `0.4.26`, build `a7fcd016f88d`, installed and loaded |
| Bridge | TCP `127.0.0.1:9878`, length-prefixed JSON |
| Open Set | scratch `SCRATCH fortnight - panel acceptance`, 32 main tracks + 2 returns; unsaved |
| Catalogue | 89 tools, 9 modes, `produce` 21 |
| Producer evidence | brief + WAV read + panel mute/take apply + select/undo + confirmed discard |
| Save/export | no product save tool; native Live only |

`doctor` at this snapshot reports `connected yes`, `errors 0`, no `stale`. That is not proof the main
thread is healthy by itself; `display` and `drains` must be advancing too.

## First 30 minutes

Run these from the repo root, in order.

```bash
# 1. Never start with an unexplained dirty tree.
git status --short
git log -3 --oneline

# 2. Restore the complete dev/analysis environment without dropping either extra.
uv sync --extra dev --extra analysis

# 3. Internal consistency only.
uv run pytest -q

# 4. Real connection. Check script/build/errors and that display/drains advance.
uv run enableton doctor

# 5. First real read. Confirm which Set is open before doing anything else.
uv run enableton status --json

# 6. See the producer vocabulary, not the whole catalogue.
uv run enableton modes
uv run enableton guide --mode produce
```

Do not run `setup --force`, restart Live or bump the Remote Script unless you changed
`remote_script/`. The producer slice is client-side.

### What to do if the tree is dirty

The panel baseline is committed. If the tree is dirty before a feature edit:

1. Inspect the diff and decide what belongs to this work; do not discard user work.
2. Commit only your own work; do not add unrelated changes, `tmp/` artifacts or user Sets.
3. Only then create a new branch or begin changes.

The project convention is one writer and a committed baseline before handing the tree on. If you
cannot commit because the owner must review it, record that explicitly and do not pretend the tree is
clean.

## First meaningful task: prove a take on a scratch Set

The scratch Set used for panel and take acceptance is open and unsaved. The take gate is recorded;
make a fresh backed-up scratch copy before another write, and never treat this copy as a working
song.

1. Choose a real song and make a **scratch copy**; do not edit the working `.als`.
2. Open the scratch copy in Live.
3. Run:

```bash
uv run enableton status --json
uv run enableton call session_brief --json
uv run enableton call takes_create --json \
  --args '{"track":"<unique track name>","count":2}'
```

4. Inspect the dry-run: planned indices, names, source/takes volumes, no changes.
5. Back up the scratch Set again if needed, then apply with `"dry_run": false`.
6. Read back the track list and volumes.
7. Use the returned undo tokens or `ableton_undo`; verify the source and copied tracks are restored.
8. Record the exact Set path, build, commands and results in
   [RELEASE_READINESS.md](RELEASE_READINESS.md).

If the source track has a duplicate name, use `track_index` and ensure the source name is unique
before applying a volume restore. If the source has no clips, the dry-run still works but the take is
not musically useful.

**Acceptance passed on 2026-11-13:** one two-take set applied through the panel on the backed-up
scratch Set; fader A/B, select/undo and confirmed discard passed; the working Set and scratch `.als`
hash were unchanged. Take variation remains open.

## Architecture you must understand

```text
MCP client
   |  MCP over stdio
   v
src/enableton/mcp/transport.py
   |  MCPServer, mode-scoped tools, session controls
   v
src/enableton/tools.py
   |  manifest lookup, local producer reports, run_tool/executor
   v
LiveAdapter (remote or fake)
   |  one TCP connection
   v
src/enableton/protocol/client.py
   |  4-byte big-endian length + UTF-8 JSON
   v
remote_script/Enableton/
   |  socket thread -> thread-safe queue -> update_display() -> dispatch -> LOM
   v
Ableton Live 12.2.5
```

### Non-negotiable implementation rules

- One connection; one in-flight request; second call gets `LIVE_BUSY`.
- All LOM access on Live's main thread.
- Do not use `schedule_message` for socket-thread work; queue it for `update_display()`.
- `update_display()` calls `super().update_display()` first.
- Never use `callable(song)` to distinguish properties from methods.
- Never call `self.log_message` directly; use the safe logging path.
- One manifest drives MCP schemas and Remote Script dispatch; run the drift test.
- Tests never bind port 9878; use port 0.
- An unavailable capability reports `unavailable` with a reason.
- Never write a user `.als` in place.

Read [../../AGENTS.md](../../AGENTS.md) and [../troubleshooting.md](../troubleshooting.md) before
changing transport or Remote Script code.

## Repository map

| Path | What it owns |
|---|---|
| `src/enableton/producer.py` | `session_brief` |
| `src/enableton/panel.py` | loopback panel HTTP app, previews and apply tokens |
| `src/enableton/panel_assets/` | the panel's HTML, CSS and browser JavaScript |
| `src/enableton/reference.py` | WAV reference measurements and comparison |
| `src/enableton/takes.py` | duplicate/rename/fader A/B take workflow |
| `src/enableton/tools.py` | catalogue dispatch, local tools, executor routing |
| `src/enableton/tools.json` | tool schemas and metadata |
| `src/enableton/modes.json` | mode membership; `produce` is a row |
| `src/enableton/mcp/` | MCP server, stdio transport, text screens |
| `src/enableton/protocol/` | client, framing, error codes |
| `src/enableton/live/adapter.py` | backend seam |
| `src/enableton/live/fake.py` | fake LOM for fast tests |
| `src/enableton/plans/` | transaction/executor/undo store |
| `src/enableton/state/` | snapshot cache and scratch copy |
| `src/enableton/audio_analysis.py` | stdlib PCM WAV baseline |
| `remote_script/Enableton/` | Live-side socket, dispatch and handlers |
| `tests/` | fake-Live suite and contracts |
| `docs/product/` | this reconciled product pack |
| `docs/M6_M7_STATUS.md` | parked capture/audio ledger; known restore defect |
| `MISSION.md` | historical sequence and gate evidence |
| `SPEC.md` | design authority; older file names/tool lists |

`src/enableton/server.py` does **not** exist in this tree. `src/enableton/mcp/transport.py` is the
actual MCP server entrypoint. Do not create a parallel server because a diagram says so.

## How to use the current producer slice

```bash
# Open the local producer panel.
uv run enableton panel

# Start the MCP server with producer vocabulary.
uv run enableton serve --mode produce

# Or call one tool directly from a shell.
uv run enableton call session_brief --json
uv run enableton call reference_analyze --json \
  --args '{"path":"F:/path/to/reference.wav","compare_to":"F:/path/to/current.wav"}'
uv run enableton call takes_create --json \
  --args '{"track":"BASS","count":2}'
```

### `session_brief`

Returns sections, roles, density, issues and next actions from one snapshot. Roles are inferred from
track names, not audio. Return buses are excluded from working-track counts. It is read-only.

### `reference_analyze`

Basic PCM WAV only: peak, RMS, crest, headroom, DC, channels, stereo balance. With the optional
`analysis` extra it adds LUFS, spectral bands, centroid and correlation. Missing optional packages
produce an explicit unavailable block. It is a measurement report, not an audition.

### `takes_create`

Duplicates a unique track, names copies, sets the source and all but take 1 to volume zero, and
returns duplicate/volume undo tokens. It does not create different musical material. `takes_select`
switches the audible take and returns fader undo tokens; `takes_discard` requires `confirm: true`
and is irreversible.

## Current product direction and what is missing

The product should show three verbs:

1. **Analyze** — `session_brief`, existing diagnostics, measured reference.
2. **Suggest** — evidence-backed next actions and deltas, not autonomous generation.
3. **Create take** — real alternatives with audition and undo.

The external release checklist also requires three workflows: inspect/repair, arrangement editing and
sound/device work. Do not drop them; map them into the producer experience:

- Analyze/tidy = inspect/repair.
- Make a take = arrangement editing.
- Reference/sound shaping = sound/device work.

Missing before the slice is sellable:

- one actual take variation;
- session memory;
- integrated capture → reference → change;
- setup/compatibility/client UX;
- legal/support/demo/beta.

See [ROADMAP.md](ROADMAP.md) for the order.

## Known traps and stale claims

- **Fake tests are not Live proof.** The fake Song is better behaved than Live. Real bugs found on
  Live include `Song.delete_track` needing an index, `set_notes` appending rather than replacing,
  routing identifiers being absent, and file flush timing.
- **`setup` without `--force` writes 0 files** when an install exists.
- **A file on disk is not the loaded script.** `doctor` compares the loaded build digest.
- **Port competition:** `AbletonMureka` can bind 9878 first.
- **`display` frozen while `connected yes`** means the socket thread is alive but the main thread is
  not; inspect `drains` and `last_super_error`.
- **Capture restore is defective on this build.** Resampling can remove `Ext. In`; the current
  remediation is `No Input`. Do not claim exact restore. See `docs/M6_M7_STATUS.md`.
- **`tracks_gain_stage` did not have a real measured-peak write** in the M4 audit; do not claim it.
- **The open Set is a scratch copy.** It has accepted an unfreeze prompt in memory; the on-disk
  `.als` is unchanged. Never treat it as a working song.
- **External docs use a different architecture:** 242 tools, port 9877, package versions and a
  generated bridge. Do not import those into this repo.
- **Current docs drift:** `AGENTS` serve-stub bullet, `MISSION` counts, `docs/mcp.md` counts/versions.

## What not to do

- Do not edit a user `.als` in place.
- Do not use the working song as a scratch Set.
- Do not apply a take without a backup and user awareness.
- Do not call identical duplicate tracks “variations.”
- Do not claim an audible result from a measurement.
- Do not claim take variation, panel select/discard buttons, persistent memory or audible
  verification exists. Real take select/undo and confirmed discard are verified; the panel's v1
  limits are in [../panel.md](../panel.md).
- Do not bump the Remote Script for client-only producer work.
- Do not invent legal, privacy, support or refund text.
- Do not copy the external product's tool counts or install claims.
- Do not start a broad refactor before the producer loop is proven.

## How to make a Remote Script change

If and only if `remote_script/` changes:

1. Bump `SCRIPT_VERSION` in `remote_script/Enableton/server.py`.
2. `uv run enableton setup --force`.
3. Restart Live.
4. `uv run enableton doctor` — the version **and** build digest must match this repo; `stale` means
   Live is still running the old copy.
5. Add a test for every `server.py` change.

The producer tools are client-side, so this four-step cycle is not needed for them.

## Definition of done

A feature is done when:

- its named real-Live call returned real data;
- a fresh read-back confirms the effect;
- failure and partial failure are reported honestly;
- the user-visible limitation is written down;
- the working Set and source media are untouched or explicitly preserved;
- fake tests are described as fake tests, not as proof.

## Handoff checklist

- [ ] Read `SPEC.md`, `AGENTS.md`, this pack and `docs/producer-layer.md`.
- [ ] Read `docs/product/AGENT_WORKSTREAMS.md`; identify your role, branch and owned files.
- [ ] Inspect `git status`; do not overwrite uncommitted work.
- [ ] Create or confirm a baseline commit (exclude `tmp/` and user Sets).
- [ ] Run full fake suite, `doctor` and `status`.
- [ ] Confirm the open Set before any write.
- [ ] Create a backed-up scratch copy of a real song.
- [ ] Run `session_brief` on it.
- [x] Run `takes_create` dry-run; confirm nothing changed.
- [x] Apply one take set on the scratch copy; verify A/B and undo.
- [x] Select a take, verify undo, and confirm the discard gate.
- [x] Record the evidence.
- [x] Update `CURRENT_STATE.md` if the state changed.
- [x] Use the panel only for the safe v1 actions documented in [../panel.md](../panel.md).

## Questions that need an owner

1. Is the MVP shape approved: MCP + `produce`, with the local panel as an additive surface?
2. What exact Live/OS/MCP client matrix is supported?
3. Is the first release a one-user beta or public launch?
4. Who supplies legal, privacy, refund and support inputs?
5. Is the public name Enableton or EnAbleton?
6. What is the version scheme for package vs Remote Script?
7. Which real song may be used for demo/beta, with consent?
8. Is the additive panel accepted as part of the product surface (D-18), and what release shape
   does it imply?

Do not answer these by assumption in code or marketing copy. Record them in
[DECISIONS.md](DECISIONS.md).

## Prompt for the next LLM

Use this as the first instruction in a new session:

```text
You are taking over Enableton. Read docs/product/README.md, docs/product/HANDOFF.md,
docs/product/CURRENT_STATE.md, SPEC.md, AGENTS.md and docs/producer-layer.md before changing
anything. The tree may be dirty; do not overwrite user work. The current product direction is
Analyze / Suggest / Create take, not the full catalogue. The panel baseline is committed and the
take create/select/discard gate passed on a scratch Set. Run the fake suite and doctor, then work on
take variation. Do not claim memory, panel select/discard buttons, or audible verification exists.
Record evidence with Verified/Assumed/Unverified tags.
```
