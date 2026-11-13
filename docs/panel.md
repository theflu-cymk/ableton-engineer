# The Enableton panel

The panel is a local web window over the same bridge and tool catalogue the MCP server and CLI use.
It is deliberately minimal: a patch-browser-style recipe catalog is the default view, and a compact
Set view keeps the current A/B takes and track context nearby. It is not a second audio engine, it
does not render or audition audio, and it does not open a second socket protocol.

The panel ships inside the existing `enableton` package. It has no build step, no npm dependency
and no external assets: the HTML, CSS and JavaScript are served by the same Python process.

## Start it

```bash
uv run enableton panel
```

The page opens at <http://127.0.0.1:9879/>. The panel listens on loopback only; the Live bridge
remains on its usual port, 9878. To print the URL instead of opening a browser:

```bash
uv run enableton panel --no-browser
```

Use `--port` only when 9879 is already occupied:

```bash
uv run enableton panel --port 9880
```

Stop the panel with `Ctrl+C` in that terminal. A port of 9878 is refused because it belongs to the
bridge.

## What the screens show

### Header

A connection dot and one plain-language state (`Live 12.2.5`, `Live offline`, or a stale-script
warning), plus **Reconnect**. The detailed build digest stays in the terminal and in
`uv run enableton doctor --json`; it is not repeated across the header.

Recipes are local JSON, so the catalog and the recipe detail pane keep working while Live is
offline. Staging and running a recipe need Live because the recipe compiler preflights the plan
against the open Set.

### Recipes

The default view is a three-column patch browser:

- **Search** matches the recipe name, id, flavor, tags, description, notes and ingredient ids. `/`
  focuses the field. Every whitespace-separated token must match.
- **Facets** filter by kind and by tag. Counts follow the current search and source/status filters,
  so a large catalog stays navigable as it grows.
- **Source** filters shipped versus user recipes. **Status** filters shipped, user, draft and broken
  recipes. **Sort** orders by name, recently changed, BPM, kind or source.
- The list supports arrow keys, Home/End, and Enter. The selected row stays visible while the detail
  pane updates.

The detail pane shows the flavor, tempo/feel, tags, description, resolved ingredients, unresolved
source bindings, manual checkpoints and the expected structural fingerprint. It never dumps raw
recipe JSON. Tags are clickable filters.

A user recipe that overrides a shipped id is marked **Overrides shipped**. A broken user file is
shown as a **Broken** row with its validation error; it does not hide the rest of the catalog. A
recipe with no executable step of its own and no executable child recipe is marked **Reference
only**; its Stage button is disabled and the detail pane explains that it records a direction, not
a runnable plan.

### Staging a recipe: the cue

**Stage recipe** calls `recipe_apply`. That compiles the recipe into a stored, validated plan. It
does not write Live. The cue drawer then shows the chain that is about to run:

- one numbered row per executable step, with a plain-language description, target and the recipe's
  `why` note;
- the exact plan id and a ten-minute expiry;
- any manual checkpoints, split into **Before staging** and **After the run**;
- warnings such as a tempo mismatch.

Nothing is written until **Run**. Run re-reads the stored plan, verifies that its steps still match
the digest the browser was shown, and applies that plan through the existing transactional
`ableton_plan_apply` path. The cue token is in-memory, single-use and expires with the plan. If the
plan changed, expired or was discarded, the panel refuses and nothing is written.

**Discard** deletes the stored plan without touching Live.

The panel does not render the recipe, synthesize a preview, draw a waveform, or claim what the
result will sound like. Auditioning stays in Live. Manual checkpoints are shown as producer work,
not as a hidden model decision.

#### Rhythm targets

A rhythm recipe replaces the notes in an existing MIDI clip. When the selected recipe needs a
target, the detail pane lists MIDI clips from the open Set and asks for one. The clip is not
created or renamed. If the Set has no MIDI clips, the panel says so rather than inventing one.

#### Track roles

Workflows name tracks by role (`DRUMS`, `BASS`, `PAD`, and so on). The detail pane lists every role
the compiled recipe references and maps it to a real track in the current Set. An exact name is
selected by default; otherwise the producer chooses the target track. The resulting
`track_bindings` are passed to `recipe_apply`; the panel does not guess a mapping.

### Set

The Set tab is a compact context view, not a mixer dashboard:

- the Set name, tempo, bar count and track/return counts;
- take groups with **Select** and **Preview discard**;
- one row per track with type, volume, mute and solo.

Mute and solo stage a single-field `mix_snapshot_restore` change through the same cue drawer. The
panel has no row-action composer, no custom-tool JSON box and no raw preview JSON. Delete and
clean-empty remain absent from the panel and stay on the CLI/MCP surfaces with their own
confirmation rules.

The take **Select** control stages `takes_select` for the whole group and the chosen take. Its Run
writes the fader change and returns the fader undo values. **Preview discard** stages
`takes_discard` with `dry_run: true`, but that cue has no Run button: deletion is irreversible and
stays in the CLI with `confirm: true`.

### Undo

After a successful Run, the cue offers **Undo last write**. It calls the existing `ableton_undo`
tool, which replays the tool-owned restore tokens kept for the last applied transaction. The record
lasts ten minutes and is refused when the current Set is not the Set the transaction touched. This
is the last Enableton write, not a general-purpose Live undo stack.

## Why writes are safe

Every panel write goes through an existing engine path:

1. `POST /api/plan` forces `dry_run: true` for a single tool and returns the planned changes.
2. `POST /api/cue` calls `recipe_apply`, which validates and preflights a recipe but never writes
   Live. The stored plan is the cue.
3. **Run** verifies the plan digest and calls `ableton_plan_apply`; a single-tool cue replays the
   exact preview arguments with `dry_run: false` through `POST /api/apply`.
4. The executor takes a scratch copy of the Set, records undo tokens and rolls back if a step
   refuses or the applied trace differs from the dry run.
5. `takes_create` keeps its own duplicate and volume rollback; it still passes the same preview
   first.

The panel keeps tokens in its own memory, binds them to the exact tool and arguments (or the exact
recipe plan), consumes them on one Run, and expires them after ten minutes. A read-only tool never
receives an apply token. A write the catalogue marks as irreversible can be previewed but has no
Run button.

The panel never writes `.als` files in place. If the Set has never been saved, a preview can still
run, but Apply/Run refuses because there is no file to copy first. Save the Set, then stage again.

## API routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/api/status` | connection report |
| GET | `/api/session` | `session_brief` |
| GET | `/api/tracks` | current tracks |
| GET | `/api/takes` | take groups and controls |
| GET | `/api/recipes` | enriched, resilient recipe catalog |
| GET | `/api/recipes/<id>` | full recipe, resolved ingredients, contract |
| GET | `/api/recipe-targets` | MIDI tracks and clips for rhythm targets |
| POST | `/api/cue` | compile a recipe into a stored plan and return a cue token |
| POST | `/api/cue/run` | verify and apply that exact plan once |
| POST | `/api/cue/discard` | delete the stored plan without touching Live |
| POST | `/api/plan` | dry-run one tool and return a preview token |
| POST | `/api/apply` | apply one previewed tool exactly once |
| POST | `/api/undo` | restore the last applied Enableton transaction |

Every route returns a JSON envelope. Errors use the same `{ok: false, error: {code, message,
status}}` shape as the rest of the panel.

## Failure modes seen in practice

### 1. Live is closed or the Control Surface is not selected

The header shows `Live offline`, and the Set tab shows an offline notice. The recipe catalog still
works. In Live, choose **Enableton** in **Preferences > Link, Tempo & MIDI**, then press
**Reconnect**. The terminal that started the panel has the exact error.

### 2. The loaded script is stale

The header shows `Live connected · restart script`. The fix is:

```bash
uv run enableton setup --force
```

Then restart Live. Live scans Remote Scripts only at startup. The panel keeps polling and will show
the new build after the restart; no panel restart is required.

### 3. A recipe cannot compile

The cue says why in plain language. Common reasons:

- a rhythm recipe has no target clip;
- a workflow names a track role that is not in the Set and no mapping was chosen;
- an ingredient is a sample or instrument binding this build cannot resolve;
- the recipe is reference-only and has no executable steps.

The panel does not fabricate a step or silently skip an ingredient. Choose a target, map the role,
or edit the recipe JSON.

### 4. A poll times out or the Set is reopened in Live

The panel uses plain polling, not websockets. If a poll fails, the UI shows the offline state and
retries every three seconds. Reopening a Set is therefore a normal recovery: wait for the next
successful status poll, or press **Reconnect**. A cue token is single-use; if state changed, stage
the recipe again rather than trying to reuse an old Run.

The panel does not retry a write automatically: an interrupted Run is never repeated silently.

## Verification

The panel tests use a fake bridge and do not need Live:

```bash
uv run pytest -q tests/test_panel.py
```

They cover the healthy status payload, session/tracks/takes endpoints, static assets, a
plan-to-apply flow, single-use tokens, the bridge-unreachable 503, the loopback bind, the enriched
catalog, a broken user recipe that does not hide the rest, recipe detail, MIDI target discovery,
cue-to-run with undo, manual checkpoints, track-role bindings and cue discard.

## Live acceptance record

**[Verified] 2026-11-13 — minimal panel and real recipe catalog.**

- Live: `12.2.5`; Remote Script `0.4.26`; build `a7fcd016f88d`; connected, not stale.
- The open Set was `victim denied` (25 main tracks + 2 returns, 140.0001 BPM). The panel read it;
  only catalog, snapshot and plan-compilation calls were made. No Run/Apply was clicked and the
  panel made no Live write.
- `GET /api/recipes` returned 14 recipes. The catalog showed shipped and user recipes, merged tags,
  BPM ranges, track roles, manual-count and `needs_target` metadata.
- `GET /api/recipe-targets` returned 12 MIDI tracks with their arrangement and Session clips.
- `POST /api/cue` for `triaal — exact fader balance` first returned `manual_required` with four
  checkpoints and no token. Repeating with `manual_confirmed: true` returned nine ordered
  `tracks_set_volume` steps and a cue token. `POST /api/cue/discard` deleted the plan. No Live write
  was made.
- In the browser, search `triaal` narrowed the catalog to 6 of 14 recipes; BPM sort placed the
  72–76 BPM recipes before the 138–142 BPM ones; the Rhythm kind facet narrowed the list to 2 and
  selected the first result.
- The browser staged `dubstep.half_time` into the existing MIDI clip `Chords MIDI / Track 1`
  (`arrangement`, 26 notes), showed the single ordered step and its `why`, enabled Run only after
  staging finished, and then discarded the cue. No Live write was made.
- **[Unverified]** No audible check and no real recipe Run/Apply. The cue path was verified through
  plan creation and discard; the transactional apply path is covered by the existing fake tests and
  the earlier real panel gates below.

**[Verified] 2026-11-13 — earlier panel select and discard gate.**

- The panel planned and applied `takes_select` for `snare rush gate take 1` and
  `snare rush gate take 2` with `active: 2`; readback showed take 2 at `0.85` and take 1 at `0.0`.
- The returned fader undo restored take 1 to `0.85` and take 2 to `0.0` through the CLI.
- The panel previewed `takes_discard` for both takes with `can_apply: false` and no token; the CLI
  applied it only with `confirm: true`. Readback showed 32 main tracks plus 2 returns, both take
  tracks gone, and the source restored to `0.85`.
- The scratch `.als` SHA-256 remained
  `da3c7a31a14c6d63bd32ee203015ed4bf3e4bfb1875483f374e9d609bb5d382f`.

**[Verified] 2026-11-13 — earlier take apply and A/B gate.**

- `takes_create` planned indices 10 and 11 for `snare rush` (index 9, volume `0.85`); Apply created
  two named takes, with take 1 active at `0.85` and take 2 at `0.0`.
- A/B was exercised with `tracks_set_volume`; a fresh readback confirmed the switch. Undo removed
  both copies and restored the source. The scratch `.als` hash stayed unchanged.

**[Verified] 2026-11-13 — earlier mute gate.**

- A panel mute preview changed track index 1 from `False` to `True`; Apply wrote it and the response
  contained the exact prior value as undo. A second preview/apply restored it. The scratch `.als`
  hash was unchanged.

**[Unverified]** Audible verification, a real recipe Run, and a click-through of every Set control.
