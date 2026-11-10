# Enableton — Specification

**Status:** design complete, build not started. This document supersedes `MISSION.md` and
`PROMPT.md`; where they disagree with this file, this file wins.

**How to read it.** §1–§3 are the contract. §4–§13 define the server. §14 defines what the user
sees. §18 defines how it grows. §19 is the build order and is the only section that authorises work.

---

## 1. What it is

An MCP server that lets the user's LLM interface inspect, repair, and build their Ableton Live Set.
It is **not** a chat toy and **not** a performance tool: it exists so a producer can say "the second
drop is a mess, fix the timing and give me a riser" and get a real, reversible edit to a real Set.

Four properties define it:

1. **Every capability is a tool.** No `action:` enum bundles. ~86 tools, each one operation, each
   with its own schema. The model sees a vocabulary, not a dispatcher.
2. **Modes scope the vocabulary, not the server.** A mode loads the ~30 tools that the work needs,
   so the model isn't choosing between 86. Anything out of scope is still reachable through
   escalation — modes reduce noise, they never trap capability.
3. **Reversibility instead of confirmation.** The server acts, then offers undo. It stops to ask
   only when an effect cannot be undone.
4. **Built to grow.** The core hosts capabilities; it doesn't contain them. Every new operation is
   data — a manifest entry, a handler, a mode row — and adding one touches zero core files (§18).

**Non-goals.** Stage/performance (transport exists only for auditioning), Link, real-time audio
streaming, follow actions (probe only), UI inside Live, cloud, multi-user, stem separation,
render/bounce, loudness metering beyond what resample capture can measure.

---

## 2. Verified platform facts (2026-11-09)

| Fact | Value | Consequence |
|---|---|---|
| Live edition / version | **Suite 12.2.5** (`C:\ProgramData\Ableton\Live 12 Suite`) | Extensions SDK **unavailable** (needs 12.4.5+) |
| Extensions SDK on disk | absent | not a backend on this machine |
| Transport | **Python Remote Script + LOM over local TCP** | the only surface with read + write + observers |
| Remote Scripts installed | none | installer is part of the deliverable |
| Python | 3.8.10 system; **3.11 via uv** (server) | The Remote Script runs on Live's **embedded CPython 3.11.6** (Live 12.1 release notes). It targets 3.11, stdlib only, no pip — so the earlier "be 3.8-safe" caution was unnecessary |
| `%APPDATA%` user config | `C:\Users\brian\AppData\Roaming\Enableton` | config, cache, logs, backups |
| Ableton user dir | `C:\Users\brian\Documents\Ableton` (absent) | created by installer |

Version-gated capabilities, detected at startup and reported `unavailable` with the reason — never
faked: `Clip.warp_markers` writes, `Envelope.create_event` (12.4+), `Track.insert_device` (12.3+),
`ClipSlot.create_audio_clip` (12.0.5+), Extensions-only render/audio-clip creation.

**Confirmed against documentation and third-party implementations (2026-11-09):**

| Claim | Verdict |
|---|---|
| `Track.insert_device(name, index)` is 12.3+, native devices only, no M4L or plug-ins | **confirmed** — so it is `unavailable` on this 12.2.5 install |
| `ClipSlot.create_audio_clip(path)` needs 12.0.5+ | **confirmed** — available here |
| `Browser.user_folders` is a vector; `BrowserItem` exposes `children`, `iter_children`, `uri`, `is_folder`, `is_loadable`; `browser.load_item` loads into the current context | **confirmed** |
| `song.view.highlighted_clip_slot` is how a browser load is aimed (Session view) | **confirmed** — no Arrangement equivalent exists, which is why ingest is Session-first (§10) |
| `schedule_message` is safe for marshalling from a socket thread | **false** — see §3 |
| MCP Python SDK v2 (`mcp>=2.3`) is Python 3.11+, exposes `MCPServer` and `structured_content`, and has a native `mcp.server.apps` extension serving `ui://` resources as `text/html;profile=mcp-app` | **confirmed** — the Apps layer of §14 is a supported SDK feature, not a workaround |

**Verified against the user's own Sets (2026-11-09).** 66 `.als` files under `F:\ableton songs`,
parsed directly as gzipped XML. Four inspected in detail:

| Set | tracks | BPM | scenes | locators | warp markers | devices (plugins) |
|---|---|---|---|---|---|---|
| Crust Wumble | 19 | 120 | 8 | 0 | 894 clip (+36 Sampler) | 108 (13) |
| EDMProd — Heavy Dubstep | 34 | 150 | 8 | 1, unnamed | 445 | 102 (22) |
| paper tiger heart update og | 54 | 150 | 8 | 1, unnamed | 932 | 94 (43) |
| paper tiger heart remaster | 77 | 150 | 8 | 1, unnamed | 1825 | 157 (40) |

**Verified 2026-11-09 against the running Live** (`uv run enableton status` + `inspect_structure` on
`Crust Wumble`): 17 tracks plus 2 return tracks — the 19 above counts the returns — 120 BPM, 8
scenes, **0 locators** and **18 top-level devices**.

**Corrected 2026-11-10** (`script 0.1.5`, then a direct parse of the same file):

- **108 is right, and now reproducible.** The file holds 108 device elements: 102 under `<Tracks>`
  (returns included) and 6 under `<MainTrack>` — one `AudioEffectGroupDevice` plus the five devices
  inside it. Live's snapshot read tracks and returns but not the master, so `0.1.5` said 102;
  `0.1.6` walks `song.master_track` too. **Verified** on 12.2.5 with `Crust Wumble` open:
  `devices_total: 108`, `devices_master: 6` — the rack `KIS_FREE Techno Mastering Chain` plus its
  five devices — `master_available: true`, `master_reason: null`. The 102-to-108 gap is closed.
- **The "1, unnamed locator" was a parse artifact.** The block is
  `<Locators><Locators /></Locators>` with zero `<Locator>` elements. Live's 0 was correct all
  along; `Song.locators` simply does not answer on 12.2.5 (`cue_points` does), which is what made
  `locators_available` false on 0.1.4.

**Warp markers verified on Live 2026-11-10 (`0.1.7`):** `counts.warp_markers: 894` across 334 audio
clips with `warp_markers_unreadable: 0`, matching the file's 894 markers under `AudioClip` in the
exact per-clip distribution (two 108s, one 4, twelve 3s, 319 2s). `warp_mode` uses the documented
enum; **Verified** on `0.1.8` that raw 6 names `complex_pro` (5 is REX), with no unnamed modes left
in the Set. The 930 above counted 36
instrument markers inside a Simpler `MultiSampleMap` (`SampleWarpProperties` under `Player`) as
well; those are not clip markers. `clips_warp_check` does not exist yet, and the other Sets' warp
columns remain claims to check. Treat the locator and device columns the same way.

**The User Library is not at `Documents\Ableton` on this machine.** Live's library is
redirected to `C:\Users\brian\OneDrive\Attachments\Documentos\Ableton\User Library`, while the
factory scripts stay under `C:\ProgramData\Ableton\Live 12 Suite\Resources`. A script installed at
the default path is written successfully and never loaded, so discovery is explicit:
`ENABLETON_USER_LIBRARY` wins, then `Documents`, then a shallow OneDrive search
(`setup.find_user_library`). Live scans Remote Scripts at startup, so installing over a running Live
always needs a restart.

Four consequences, each already folded into the section that owns it:

- **Duplicate track names are normal** — `instrumental` four times and `mian track` twice in one
  Set. Name references must fail loudly instead of picking the first match (§4).
- **These Sets are arrangement-first**: 315 arrangement clips against 22 in Session, eight scenes,
  and a single unnamed locator. Structure comes from clip density, and "unused" cannot mean
  "never launched" (§8).
- **Plug-ins dominate the chains**, 13–43 per Set. Native-only inserts and the lack of plug-in
  parameter access constrain the `sound` mode more than the Live version does.
- **Warp analysis is a bulk operation**, not a per-clip nicety: 445–1825 markers per Set (§20).

---

## 3. Architecture

```
┌─ LLM client (Claude / Cursor / Code) ─────────────────────────┐
│  tools/list  ──► mode-scoped tool set                          │
│  tools/call  ──► request                                      │
└───────────────────────────┬───────────────────────────────────┘
                    MCP (stdio) │
┌───────────────────────────▼───────────────────────────────────┐
│ Enableton server (Python 3.11, uv)                            │
│                                                               │
│  server.py      tool registration from manifest               │
│  session.py     view state: screen, report, selection, plan    │
│  plans/         compiler (bounded) + executor (transactional)  │
│  diagnostics/   findings, phases, repair ordering              │
│  state/         snapshot cache + invalidation                 │
│  live/adapter   LiveAdapter interface                          │
│      ├ remote.py   ── socket ──┐                              │
│      └ fake.py     (tests)     │                              │
└────────────────────────────────┼──────────────────────────────┘
                       4-byte len + JSON
┌────────────────────────────────▼──────────────────────────────┐
│ Remote Script inside Live (Python 3.8, stdlib only)           │
│  socket thread: framing + parse only                          │
│  schedule_message ──► main thread ──► dispatch table ──► LOM  │
└───────────────────────────────────────────────────────────────┘
```

**Rules that hold everywhere:**

- One connection, owned by `server.py`, injected. Nothing else opens a socket.
- One scheduler. No `setInterval`-equivalent outside it; a test greps for `threading.Timer`,
  `asyncio.sleep` loops and `while True` polls outside `state/`.
- All LOM access on Live's main thread. The socket thread parses and replies and never touches
  `song`. Work is marshalled through a **thread-safe queue drained in `update_display()`** — *not*
  `schedule_message`: the framework copies its scheduled-task list and replaces it on the main
  thread, so a task appended from the socket thread between those two steps is silently dropped and
  the request times out. A third-party bridge hit exactly this on Live 12.4.3, and it surfaces as a
  timeout rather than an error — the worst way to find out. `update_display()` must call `super()`
  first: the framework pumps its own scheduled work and components there, and an override without
  it leaves every real command timing out while ping still answers.
- One manifest generates the MCP tool schemas *and* the script's dispatch table; a drift test
  asserts the two sets are equal.

---

## 4. Protocol

**Framing.** 4-byte big-endian length + UTF-8 JSON. Max frame 8 MiB. Partial reads accumulate in a
bytearray and are re-parsed only from a complete frame — never `json.loads` on a rolling buffer.

**Envelope.**

```json
// request  (client → Live)
{"id": 17, "cmd": "track.list", "args": {...}, "timeout_ms": 2000}
// response (Live → client)
{"id": 17, "ok": true, "result": {...}, "elapsed_ms": 3}
{"id": 17, "ok": false, "error": {"code": "NOT_FOUND", "message": "...", "detail": {...}}}
```

- `id` monotonic per connection. **One in-flight request.** A second call while one is pending
  returns `LIVE_BUSY` immediately rather than queueing.
- Per-command timeouts come from the manifest (`timeout_ms`), not from `sleep`. A timeout is
  `TIMEOUT`, and the connection is *not* torn down — the reply is discarded by id.
- Watchdog: if Live hasn't answered in `timeout_ms + 500`, the tool returns `LIVE_BUSY` with the
  command name. No retry without an explicit user action.
- Paging is explicit: `{offset, limit}` with `next_offset` in the result. Defaults: 200 items for
  lists, 2000 notes for MIDI.

**Error codes** (12, closed set): `BAD_REQUEST`, `UNKNOWN_COMMAND`, `BAD_ARGS`, `NOT_FOUND`,
`AMBIGUOUS_REF`, `LIVE_BUSY`, `LIVE_ERROR`, `UNSUPPORTED`, `PRECONDITION_FAILED`, `TIMEOUT`,
`DISCONNECTED`, `INTERNAL`.

Every error is a structured object, and the MCP text content is one sentence a producer can act on
plus the code. Never a stack trace, never prose-only.

**IDs.** No UUIDs in tool args by default. Objects are addressed by **reference**:

```json
{"track": {"name": "Bass layer"}}          // resolved at execution
{"track": 3}                              // index, resolved at execution
{"clip": {"track": {"name":"Drums"}, "slot": 2}}
```

References resolve at execution time, never cached across writes.

Names are **not unique** in real Sets: one of the user's has four tracks called `instrumental` and
two called `mian track`. Resolution is therefore strict — a name matching one object resolves, a
name matching several returns `AMBIGUOUS_REF` listing the candidate indexes, and it is never
silently "the first one". `{name, index}` disambiguates without a second read.

The snapshot is invalidated by
any mutation the server performs, and by `ableton_status` when the user says Live changed
underneath it.

---

## 5. Tool catalogue

### 5.1 Naming

`<domain>_<verb>` — singular, one operation, no `action` parameter. Domains: `tracks`, `clips`,
`notes`, `sections`, `devices`, `mix`, `master`, `library`, `gen`, `inspect`, `transport`, plus the
unprefixed core tools.

Domains are **not** modes. A tool has exactly one name and may be exposed by several modes
(`tracks_gain_stage` appears in both `prep` and `mix`).

### 5.2 Catalogue

| Domain | Tools |
|---|---|
| core (10) | `ableton_start`, `ableton_status`, `ableton_guide`, `ableton_screen`, `ableton_choose`, `ableton_escalate`, `ableton_plan_apply`, `ableton_plan_discard`, `ableton_undo`, `ableton_save` |
| transport (4) | `transport_play`, `transport_stop`, `transport_locate`, `transport_set_loop` |
| inspect (8) | `inspect_run`, `inspect_report`, `inspect_finding`, `inspect_plan`, `inspect_autofix`, `inspect_unused`, `inspect_structure`, `inspect_export` |
| tracks (10) | `tracks_gain_stage`, `tracks_set_volume`, `tracks_set_pan`, `tracks_set_sends`, `tracks_name_and_color`, `tracks_group_by_role`, `tracks_duplicate`, `tracks_set_routing`, `tracks_delete`, `tracks_clean_empty` |
| clips (10) | `clips_warp_check`, `clips_align_to_grid`, `clips_fix_loop_points`, `clips_set_warp_mode`, `clips_copy`, `clips_duplicate_range`, `clips_trim`, `clips_transpose`, `clips_clear`, `clips_rename` |
| notes (8) | `notes_read`, `notes_quantize`, `notes_transform`, `notes_humanize`, `notes_strum`, `notes_replace`, `notes_overlaps`, `notes_scale_lock` |
| sections (7) | `sections_map`, `sections_create_locators`, `sections_move`, `sections_copy`, `sections_delete`, `sections_clear_range`, `sections_scenes_from_sections` |
| devices (9) | `devices_read_chain`, `devices_set_parameter`, `devices_insert`, `devices_delete`, `devices_move`, `devices_bypass`, `devices_set_macro`, `devices_load_preset`, `devices_browse_presets` |
| mix (7) | `mix_levels_report`, `mix_headroom`, `mix_meter_poll`, `mix_spectral_report`, `mix_snapshot_save`, `mix_snapshot_restore`, `mix_routing_report` |
| master (5) | `master_chain_read`, `master_set_gain`, `master_device_audition`, `master_loudness_capture`, `master_compare` |
| library (4) | `library_folders`, `library_browse`, `library_search`, `library_place` |
| gen (4) | `gen_gesture`, `gen_audition`, `gen_accept`, `gen_discard` |
| recipe (6) | `recipe_list`, `recipe_show`, `recipe_learn`, `recipe_build`, `recipe_refine`, `recipe_delete` |

**Total: 92 tools.** Any new domain adds tools to the catalogue and tools to a mode — and requires
zero edits to core files.

### 5.3 Manifest

`src/enableton/tools.json` is the single source of truth. One entry per tool:

```json
{
  "name": "tracks_gain_stage",
  "domain": "tracks",
  "summary": "Normalise track output levels toward a headroom target.",
  "description": "Sets each track's volume so that its loudest observed peak sits `headroom_db` below 0 dBFS. Tracks in groups keep their relative balance. Dry-run by default.",
  "examples": ["gain stage the drums to -6", "even out all the track levels"],
  "input": { "type": "object", "properties": { "...": {} } },
  "timeout_ms": 4000,
  "writes": true,
  "reversible": true,
  "needs": ["levels"],
  "min_live": null,
  "cmd": "tracks.gain_stage"
}
```

Fields: `name`, `domain`, `summary` (one line for the tool list), `description` (for the model —
when to use it, what it changes, what it refuses), `examples` (producer-language phrases for the
prompt screen and the guide — the teaching surface is data too), `input` (JSON Schema), `timeout_ms`,
`writes`, `reversible`, `needs` (adapter features), `min_live`, `cmd` (the script command),
`deprecated` (absent unless retiring, §18.2).

Generated from it: the MCP tool definitions, the script's dispatch table, the `ableton_guide`
command sheet, the CLI help, and the test fixtures. Drift test: every `cmd` in the manifest has a
handler in the script, and every handler has a manifest entry — asserted by importing the script's
handler map, not by regex.

### 5.4 Every write tool's contract

- `dry_run: true` by default for anything bulk or destructive; a `dry_run` result is a
  `Plan` (below) with no effects.
- Returns `{applied, skipped, undo_hint, snapshot_stale}`.
- Never returns "success" for a partial application — partial is a failure with the failing step
  named.
- Never `sleep`s. Verification is a re-read, not a wait.

---

## 6. Modes

Selection at startup: `enableton serve --mode auto` (default). Static for the session — `tools/list`
never changes, because `tools/list_changed` is unreliable across clients (Claude Desktop ignores
it, Cursor doesn't support it, Claude Code can drop tools mid-session).

| Mode | Loaded tools | For |
|---|---|---|
| `auto` | core + `inspect_run/report/finding/plan` + `tracks_gain_stage` + `clips_warp_check` + `notes_overlaps` + `mix_headroom` + `library_folders/browse/search` | default; triage and everyday edits |
| `inspect` | core + inspect (8) + `mix_headroom`, `mix_levels_report` + `clips_warp_check` + `notes_overlaps` | audits, reports, no edits |
| `prep` | core + `inspect_run/report` + tracks (10) + `clips_warp_check/align_to_grid/fix_loop_points/set_warp_mode` + `sections_create_locators` | set hygiene before writing |
| `edit` | core + notes (8) + clips (10) + `inspect_finding` | MIDI and clip surgery |
| `arrange` | core + sections (7) + `clips_copy/duplicate_range/trim` | structure of the timeline |
| `build` | core + library (4) + gen (4) + clips (6) + `tracks_duplicate` + `sections_scenes_from_sections` + `recipe_list/show/build` | making sections from loops, including from recipes |
| `recipe` | core + recipe (6) + library (4) + `gen_audition/accept/discard` + `clips_copy/duplicate_range` | learning recipes from audio and refining them; consuming one is `build`'s job too |
| `sound` | core + devices (9) + `library_search/browse` + `mix_spectral_report` | chains, presets, macros |
| `mix` | core + mix (7) + tracks (10) + `devices_set_parameter` + `master_chain_read` | balance, gain, routing |
| `master` | core + master (5) + `mix_snapshot_save/restore`, `mix_meter_poll`, `mix_spectral_report` + devices (9) | final chain and audition |

Every mode is ≤ 34 tools including the 14 core. `enableton serve --mode list` prints this table.
This is the initial set, not a fixed list: a mode is a row in `modes.json`, so a new one is a data
change (§18.5).

**Artifacts cross modes.** A tool is not owned by the mode that *authors* its object. Recipes are
authored in `recipe` and consumed in `build`; mix snapshots are saved in `mix` and restored in
`master`. Whenever a mode produces a reusable artifact, every mode that builds with that artifact
loads its read and use tools — consumption is the normal path, so it must never require escalation.
Escalation is for surprises, not for the main road.

**Modes never trap.** If the model needs something outside the mode, `ableton_escalate` reaches it
(§7), and the mode's guide text says so. The mode chip in the UI always shows the current scope so
the user knows which vocabulary is live.

---

## 7. Escalation and plans

`ableton_escalate({intent, context})` compiles a **bounded plan** against the *full* catalogue:

```json
{
  "plan_id": "p_7f2",
  "steps": [
    {"n": 1, "tool": "tracks_group_by_role", "args": {"dry_run": true}, "why": "3 drum tracks ungrouped"},
    {"n": 2, "tool": "clips_align_to_grid", "args": {"tracks": ["Drums"], "bars": [64, 128]}, "why": "Bass layer +47 ms"}
  ],
  "effects": {"tracks": 3, "clips": 7, "notes": 412},
  "reversible": true,
  "requires": ["levels"],
  "unavailable": [{"tool": "clips_set_warp_mode", "reason": "needs warp-marker write (Live 12.4+)"}],
  "expires_at": "…"
}
```

- Compilation is greedy over findings + intent, capped at **12 steps / 3 phases**. If it can't fit,
  it returns the plan it has plus `truncated: true` and what it left out — never silently drops.
- The plan is *data*; the model reads it and can edit steps before applying.
- `ableton_plan_apply({plan_id})` executes **transactionally**: snapshot the affected objects,
  run top to bottom, stop at the first failure, restore, and return both the failure and the
  restore result.
- `ableton_plan_discard({plan_id})` deletes it. Plans expire after 10 minutes.
- `inspect`-escalation (audits reached from outside `inspect` mode) is **off by default**; a mode
  that needs it enables it explicitly. Audits are expensive and noisy.

---

## 8. Diagnostics

A **finding** is the unit of everything the server knows is wrong:

```json
{
  "id": "f_3a1",
  "kind": "alignment.drift",
  "severity": "warn",            // info | warn | error
  "confidence": 0.92,            // 0–1, honest
  "title": "Bass layer drifts +47 ms from drums",
  "evidence": {"bars": [64, 128], "drift_ms": [47, 51, 49], "method": "onset cross-correlation"},
  "location": {"track": {"name": "Bass layer"}, "clip": {"slot": 0}},
  "fix": {"mode": "prep", "tool": "clips_align_to_grid", "args": {"bars": [64,128]}},
  "objective": "tightness",
  "needs_listening": false       // true → the fix is audition-only
}
```

Fields are mandatory: `id`, `kind`, `severity`, `confidence`, `title`, `location`, and `fix`
**or** `needs_listening: true` (never neither).

**Tiers.** `inspect_run({tier})` — `fast` (snapshot only: naming, grouping, empties, routing, warp
modes), `standard` (+ note analysis, overlap, level report), `deep` (+ meter polling and spectral
report; takes real time and is audible in `deep` only for capture). Default `standard`.

**Set shape.** The four Sets inspected are arrangement-first: 315 arrangement clips against 22 in
Session, eight scenes, one unnamed locator. So `inspect_structure` derives sections from
arrangement clip density and scene use — never from locators, which these Sets effectively don't
have — and `inspect_unused` means tracks with no clips, scenes with no clips, and arrangement
clips outside any named section. "Never launched" is not observable through the LOM and is not
claimed.

**Phases.** `inspect_plan` orders repairs, because findings don't repair in the order they're found:

1. grid (grid settings, loop points) → 2. alignment (warp, drift, offsets) → 3. notes (overlaps,
quantise, length) → 4. hygiene (naming, colour, empty, grouping) → 5. routing (sends, groups,
routing types) → 6. **gain** (auto) → 7. spectral (audition only) → 8. master (audition only).

Rules: a phase never runs while a later phase's fix depends on it; `needs_listening` findings are
never auto-applied; `error` severity blocks auto-apply of anything downstream in its phase.

`inspect_autofix({phases, checkpoint})` runs phase by phase, re-reads after each, and stops with a
report if the finding count goes *up*.

---

## 9. Safety

Reversibility is the mechanism; confirmation is the exception.

| Effect | Behaviour |
|---|---|
| Single-track param write | applies immediately, `undo_hint` returned |
| Bulk under 20 objects | applies immediately, snapshot copy of touched objects held for undo |
| Bulk over 20 objects | `dry_run` first, plan shown, then apply |
| Multi-step plan | snapshot → apply → verify → keep snapshot until `ableton_undo` or 10 min |
| Write into user's Places folder | **confirm** — cannot be undone |
| Save `.als` | **confirm** — writes outside the session |
| Delete without an undo-able path | **confirm** |
| Render / bounce | out of scope |

`ableton_undo({scope})` restores our last transaction (Live's own undo is linear and can't unwind a
multi-step plan stepwise). `ableton_save({mode:"copy", name})` writes to the staging dir.

Backups: before the first write of a session, the Set is copied to
`%APPDATA%\Enableton\backups\<set>-<timestamp>.als` if it has unsaved changes. Original files are
never written in place.

---

## 10. Library and ingest

The Browser is the library. `library_folders()` lists `browser.user_folders` (Places) — expanded,
because it's a vector and only items have `.children`. Folder names are the aliases the user says
out loud ("riddim").

- `library_browse({folder, offset, limit})`, `library_search({query, folder})` — index keyed by
  `uri`, never by name alone.
- `library_place({item_uri, track, slot, scene})` — `song.view.highlighted_clip_slot` +
  `browser.load_item`; `clip_slot.create_audio_clip` where version allows; otherwise manual drag
  with a precise instruction.
- Analysis path comes from `clip.file_path` **after** load. Never guess the path from the browser
  item.

Ingest for section building: `library_place` → `clips_duplicate_range` → `sections_scenes_from_sections`.

---

## 11. Audio review

Three tiers, in the order of cost:

1. **Source analysis** — instant, files only. Warp status, length, tempo/key estimate, DC offset,
   headroom of the source file.
2. **Meter polling** — `mix_meter_poll({tracks, ms})`. Meters are 0.0–1.0;
   `output_meter_level` has a 1 s hold — poll faster than the hold or the number lies.
3. **Resample capture** — master → a scratch `Resampling` track → WAV in
   `Samples/Recorded/` → analysis. **Real time and audible.** Requires arming with
   `input_routing_type = Resampling`; an invalid routing arm is a silent no-op, so verify the
   routing actually took before firing.

`mix_spectral_report` and `master_loudness_capture` are tier 3 and always flagged as audible.
Any claim about the master that can't be measured is reported as `unknown`, not estimated.

---

## 12. Generation and recipes

### 12.1 Gestures

A gesture catalogue, not a black box. Each gesture is `{metric, energy, structural, harmonic}`:

| Gesture | What it produces |
|---|---|
| `halftime` | half-speed variant of a source clip, with the implied drum edit |
| `double_time` | double-time variant |
| `cut_time` | trimmed/stuttered version at matched energy |
| `drop` | 4–8 bar silence→impact preceded by the section's loudest material |
| `riser` | frequency or energy ramp into the next section |
| `fill` | last-bar variation from the section's own material |

`gen_gesture({gesture, source, bars, seed})` writes **only** into a scratch scene
`__enableton_preview`. `gen_audition` plays it, `gen_accept` moves it into place,
`gen_discard` deletes it. No tempo automation by default — tempo changes are a stated,
separate request.

Derived audio (reverse, trim, crossfade, stretch) is written to
`%APPDATA%\Enableton\cache\derived\` so sources are never modified.

### 12.2 A recipe is data

A **recipe** is a named, reusable way of building something, written as JSON: a pattern, the kind of
sound each part needs, and where to look for those sounds. It is not code and not a prompt — it is a
document you can read, edit, diff, and hand to someone else.

```json
{
  "id": "dubstep.half_time",
  "name": "Dubstep — half-time step",
  "version": 1,
  "kind": "rhythm",
  "status": "shipped",
  "tempo": {"bpm": 140, "feel": "half_time", "grid": "1/16"},
  "length_bars": 2,
  "lanes": [
    {"slot": "kick",  "pattern": "x.......x.......", "velocity": 1.0,  "swing": 0.0},
    {"slot": "snare", "pattern": "....x.......x...", "velocity": 0.92, "humanize": 0.04},
    {"slot": "hat",   "pattern": "x.x.x.x.x.x.x.x.", "velocity": 0.50, "humanize": 0.12},
    {"slot": "stab",  "pattern": "..............x.", "velocity": 0.70}
  ],
  "slots": [
    {"slot": "kick",  "mode": "hit", "from": "riddim/drums/one shots", "select": "lowest_centroid", "count": 1},
    {"slot": "snare", "mode": "hit", "from": "riddim/drums/one shots", "select": "high_transient",  "count": 1},
    {"slot": "hat",   "mode": "hit", "from": "riddim/drums/one shots", "select": "shortest_decay",  "count": 1},
    {"slot": "stab",  "mode": "hit", "from": "riddim/drums/one shots", "select": "random",          "count": 1}
  ],
  "source": {"kind": "learned", "file": "…/refs/dubstep_140.wav", "window_s": [0, 8], "confidence": 0.81},
  "notes": "snare on 3, ghost hats on 16ths, kick doubles on the 1"
}
```

A slot's `mode` is `hit` (one-shots placed at pattern positions) or `layer` (a whole loop placed
underneath and trimmed to the pattern's length) — so a recipe can ask for "a loop" as easily as
"a kick".

### 12.3 Patterns are text

Sixteen steps per bar, one character each: `x` hit, `X` accent, `o` ghost, `.` rest, `|` bar line.
A pattern written this way is legible in a chat message, editable by hand, and diffable in git. The
model can author one directly ("more of a drill pattern: kick on 1, snare on 3, rolling hats") and
the user can correct a single character without touching anything else.

### 12.4 Learning a recipe from audio

`recipe_learn({source, scope, window, name, kind})` — `source` is a file, a loaded clip, or the
current Set. `scope` is one of:

| `scope` | What it produces |
|---|---|
| `hit` | one sound file → a **slot sample**, classified by spectral centroid, decay and transient sharpness into kick / snare / hat / perc / stab, with a confidence |
| `window` | file + timestamp window (`{"at": "0:32", "for": 8}`) → a **pattern**: tempo, feel and per-lane steps from that passage |
| `whole` | the whole song → tempo, feel, a representative pattern from the loudest 8 bars, and an energy curve that section building can use |

The pipeline is tempo estimation on the window, grid alignment, onset detection per frequency band,
then lane assignment. It is honest about its limits:

- every lane carries its own `confidence`; nothing is presented as certain because the tempo was.
- if tempo or feel is below 0.6 confidence the draft comes back with `needs_confirmation: true` and
  the specific question — "is this 140 half-time or 70 straight?" — instead of a guess.
- a learned recipe is saved as `status: "draft"`. `recipe_refine` is how a human turns a draft into
  a recipe: fix a lane, move a hit, reassign a slot, confirm the tempo.
- a draft can be built without confirming, but only with an explicit `accept_drafts`, and the
  scratch scene is named so nobody forgets it was unconfirmed.

### 12.5 Building from a recipe

"create a dubstep drum beat using loops from my riddim one shots folder" resolves to one call:

```json
{"recipe": "dubstep.half_time", "slots_from": {"*": "riddim/drums/one shots"}, "bars": 2}
```

This works from `build` mode directly: `recipe_list`, `recipe_show` and `recipe_build` are loaded
there beside the loop tools, so the ordinary path never leaves the mode. Learning and refining a
recipe is `recipe` mode's work; building with one is `build` mode's work, and both are the same
tools.

`recipe_build` then:

1. **resolves slots** — `library_search` inside the named Places folder, then tier-1 source analysis
   on the candidates to score them against the slot's `select` rule. No filesystem scanning: the
   Browser is the index (§10).
2. **assembles** — `place_audio` by default: one audio track per slot, clips placed on the grid with
   the pattern's velocity and humanise applied. Safe, sample-accurate, and needs only
   `create_audio_clip` or a browser load into a slot.
3. **or** uses `rack` — one MIDI clip into a Drum Rack, which needs hotspot loading into pads. That
   is version-fragile, so it is all-or-nothing: if any pad can't be filled the strategy is refused
   with a reason rather than leaving a half-loaded rack.
4. **writes only into `__enableton_preview`**, then `gen_audition`, `gen_accept` or `gen_discard`.

It returns what landed where — per slot the sample chosen, its score, and the confidence it was
picked with — so "why does the kick sound wrong" has an answer other than "the model decided".

### 12.6 Where recipes live

- shipped starters in `src/enableton/recipes/*.json`, marked `status: "shipped"`
- user recipes in `%APPDATA%\Enableton\recipes\<id>.json`, overriding a shipped recipe with the same
  id — the shipped file is never modified
- `recipe_list` / `recipe_show` read; `recipe_refine` edits; `recipe_delete` removes a user recipe
  only
- recipes are portable: sharing one is copying a file, with no server and no account
- every recipe carries `version`, and `recipe_build` refuses a recipe whose schema version it does
  not know rather than guessing at the fields

Adding a genre is a JSON file — no code, no release (§18.10).

### 12.7 What it refuses

| Situation | Behaviour |
|---|---|
| a slot's folder has no candidates | names the slot and stops; never substitutes from another folder |
| recipe tempo vs Set tempo differs by more than 10% | refuses and asks, instead of stretching quietly |
| a pattern length doesn't divide `length_bars` | `BAD_ARGS` naming the lane |
| building an unconfirmed draft without `accept_drafts` | refuses, naming the field that would allow it |
| a slot is `layer` but the folder holds only one-shots | names the mismatch and offers the `hit` alternative |

---

## 13. Server-side session state

One state object, shared by every view. Nothing about the session lives in the client.

```python
Session(screen="main", report=None, selection=None, plan=None, mode="auto")
```

- `screen` — `main | modes | mode:<name> | prompt | apply | recipe | settings`
- `report` — last `inspect_run` result + `scanned_at`
- `selection` — the reference the mode screen is scoped to (track, clip, bars)
- `plan` — active plan id
- `mode` — the loaded tool set

Screens read this; every action writes it. Hence the chat view, the MCP App and `enableton ui`
cannot disagree, and `ableton_start` after a restart resumes where the user left off.

---

## 14. The user experience

### 14.1 Starting

The user types **`Start Enableton`** (or `/mcp__enableton__start`, or `enableton start`). The server
instructions tell the model to call `ableton_start` on any session-opening message or any request
about the Set's health.

`ableton_start` returns a **screen payload**:

```json
{
  "screen": "main",
  "text": "…the same content as plain text…",
  "structured": {"set": {"name": "Riddim WIP", "bpm": 140},
                 "counts": {"findings": 14}, "modes": [], "actions": []},
  "ui": {"resource": "ui://enableton/main"}
}
```

In clients that support **MCP Apps**, `ui` renders the interactive panel; everywhere else the
`text` is what the user reads. The payload is identical either way — one code path, two renderers.

### 14.2 Main screen

```
┌─ ENABLETON ───────────────────── Live 12.2.5 · connected ─┐
│ Set: "Riddim WIP"  140 BPM  F# minor  24 tracks  6 scenes │
│ Last scan: 12 min ago                                     │
│ ● 14 findings  ● 4 alignment  ● 3 notes  ● 6 gain  ● 1 routing │
│ [ Run diagnostic ]  [ Fix all (12) ]                      │
│ BY MODE  prep 7 · edit 3 · mix 6 · master 2   [ open ]     │
│ [ Custom prompt ]   [ Settings ]   [ Undo last fix ]       │
└───────────────────────────────────────────────────────────┘
```

Connection problems are not a dead screen: the text names the exact fix (which control surface to
select, which port is closed) and offers Retry.

### 14.3 Modes screen → mode screen

`Diagnose` runs tiered progress and lands on **modes**, each row with fix counts split into
auto / needs-listening. Choosing a mode opens its finding list: one row per finding, with
`[explain]` (evidence) and `[preview]` (audition) where applicable, checkboxes, and
**Apply selected / Apply all / Back**.

**Fix all runs phases, not modes** — the button says so, so the execution order isn't a surprise.

### 14.4 Prompt entry — main vs mode

Same component, different scope, always shown as a chip:

| Where | Scope | Target | Hints |
|---|---|---|---|
| main | `auto` | whole set | cross-mode commands, section building, master review |
| mode | that mode | current selection | that mode's commands, plus a "will escalate" list |

### 14.5 Prompt screen

```
┌─ CUSTOM PROMPT ─────────── scope: prep · track 3 ─┐
│ ▸ ▏                                               │
│ TRY   "tighten loop points on this clip to whole bars" │
│       "gain stage every drum track to -6 dB"          │
│ IN PREP   tracks_gain_stage · clips_fix_loop_points …  │
│ NOT HERE  master_chain_read → master (will escalate)   │
│ [ Run ]                     [ Show all commands ]      │
└───────────────────────────────────────────────────┘
```

This is the teaching surface: producer-language examples, real command names underneath, and an
explicit line when something leaves the mode. `/` filters the full command sheet for the scope.

### 14.6 Recipe screen

```
┌─ RECIPE · Dubstep — half-time step ─────────── 140 · half-time ─┐
│ learned from dubstep_140.wav 0:00–0:08 · confidence 0.81 ✓      │
│                                                                 │
│  kick   x.......x.......   ●●●●○   kick_04.wav   (0.91)         │
│  snare  ....x.......x...   ●●●●●   snare_02.wav  (0.88)         │
│  hat    x.x.x.x.x.x.x.x.   ●●●○○   hat_11.wav    (0.74)         │
│  stab   ..............x.   ●●●○○   stab_03.wav   (0.69)         │
│                                                                 │
│  [ Audition ]  [ Build 2 bars ]  [ Edit pattern ]  [ Back ]     │
└─────────────────────────────────────────────────────────────────┘
```

Confidence is per lane, and the sample chosen for each slot is visible and replaceable before
anything is built. Editing a pattern is typing sixteen characters.

### 14.7 Fallbacks, in order

1. **MCP App** where supported (Claude web/desktop; ChatGPT and Slack implement the standard).
2. **Text screens** with numbered choices — `ableton_choose` ids, so "2" or "prep" works.
3. **Elicitation** where supported — flat primitive schemas only, so it handles choices, not lists.
4. **`enableton ui`** — the same App served on `127.0.0.1` for clients with neither.

No screen may be reachable only through one renderer. Every screen has a text form, and a test
asserts it.

---

## 15. CLI

```
enableton setup      install the Remote Script, write config
enableton doctor     environment + connection + version report
enableton serve      run the MCP server (--mode auto)
enableton status     connection, set summary, finding counts
enableton inspect    run a tier, print findings (--json)
enableton plan       compile and print a plan without applying
enableton run        apply a plan id
enableton undo       undo last transaction
enableton trace      per-request trace log
enableton guide      print the command sheet for a mode
enableton backup     copy the current Set
enableton ui         serve the App locally
enableton logs       tail the request log
```

Exit codes: `0` clean, `1` findings present (`inspect`), `2` connection failure. Machine-readable
with `--json` everywhere.

---

## 16. Config, paths, logging

`%APPDATA%\Enableton\config.json`:

```json
{
  "port": 9878,
  "remote_script_dir": "C:\\Users\\brian\\Documents\\Ableton\\User Library\\Remote Scripts",
  "modes": {"default": "auto", "inspect_escalation": false},
  "targets": {"headroom_db": -6.0, "gain_stage_ceiling_db": -9.0},
  "recipes": {"dir": "%APPDATA%\\Enableton\\recipes", "accept_drafts": false},
  "backups": {"on_first_write": true, "keep": 10},
  "log": {"level": "info", "keep_days": 14}
}
```

Port is configurable because 9877 is the well-known default and is often taken. Nothing is
hardcoded to a machine path; the Windows defaults exist only as fallbacks.

Logs: `%APPDATA%\Enableton\logs\requests.jsonl` — one line per tool call: id, tool, args hash,
snapshot reads, elapsed, result code. Readable by the user, never written into the `.als`.

---

## 17. Repository layout

```
enableton/
  pyproject.toml
  src/enableton/
    __main__.py  cli.py  server.py
    tools.json  modes.json        # data: the catalogue and the mode views
    manifest.py  modes.py  registry.py
    protocol/   framing.py  codes.py  client.py  version.py
    live/       adapter.py  conformance.py  remote.py  fake.py
    state/      snapshot.py  session.py  config.py
    diagnostics/findings.py  phases.py
    plans/      compiler.py  executor.py
    apps/       main.html  resources.py
    plugins.py                    # optional third-party loader (§18.7)
    recipes/      *.json          # shipped starter recipes
    recipes.py                    # load, validate, learn, build
  remote_script/Enableton/
    __init__.py  server.py  dispatch.py  handlers/*.py
  tests/        fixtures/  contracts/   (fake Live, protocol, drift, modes, plans,
                                        screens, golden tool schemas)
  docs/         adr/  README.md
```

`registry.py` discovers handler modules and cross-checks them against `tools.json` at startup. The
four extension seams and their worked examples are defined in §18; `README.md` repeats the short
version for anyone who never reads a spec.

---

## 18. How it grows

This app will be updated for years. The design accommodates that structurally rather than
optimistically: **the core is the smallest thing that can host capabilities, and it does not
contain them.** Everything a producer can do is data — a manifest entry, a handler function, a mode
row. Growth touches those three files and no core file.

### 18.1 The four seams

| Seam | What you write | Core files touched |
|---|---|---|
| Capability | one `tools.json` entry + one handler function | 0 |
| Domain | a handler module + manifest rows + mode rows | 0 |
| Mode | one row in `modes.json` | 0 |
| Adapter | a `LiveAdapter` implementation | 0 (one registration line in `live/__init__.py`) |

### 18.1a Adding a tool, end to end

`clips_set_gain` — a tool that didn't exist before, added without reopening the core.

**1 — `tools.json`:**

```json
{
  "name": "clips_set_gain",
  "domain": "clips",
  "summary": "Set an audio clip's gain.",
  "description": "Applies `gain_db` to a clip's own gain stage. Audio clips only: MIDI clips have no gain, so it returns UNSUPPORTED naming the clip rather than silently touching the track.",
  "examples": ["pull this loop down 3 dB", "match this clip to the one below it"],
  "input": {
    "type": "object",
    "properties": {
      "clip": {"$ref": "#/definitions/clip_ref"},
      "gain_db": {"type": "number", "minimum": -70, "maximum": 6}
    },
    "required": ["clip", "gain_db"]
  },
  "timeout_ms": 1500,
  "writes": true,
  "reversible": true,
  "needs": ["audio_clips"],
  "cmd": "clips.set_gain"
}
```

**2 — `handlers/clips.py`:**

```python
def set_gain(ctx, args):
    clip = ctx.resolve(args["clip"])                 # reference → object, at execution
    if not clip.is_audio_clip:
        raise Precondition("UNSUPPORTED", "MIDI clips have no gain stage")
    ctx.stage(clip, "gain")                          # snapshot for undo
    clip.gain = db_to_linear(args["gain_db"])
    return {"clip": ctx.describe(clip), "gain_db": args["gain_db"]}
```

**3 — the script side, only when the command is new:** `remote_script/Enableton/handlers/clips.py`:

```python
def set_gain(args, song):
    clip = resolve_clip(song, args["clip"])
    clip.gain = db_to_linear(args["gain_db"])
    return {"gain": clip.gain}
```

**4 — `modes.json`:** add `clips_set_gain` to `mix` and `prep`.

That is the change. The MCP schema, the model's tool list, the guide sheet, the prompt-screen
examples, the CLI help, the script dispatch table and the test fixtures all derive from the manifest.
No dispatch edit, no second copy of the schema, no help text to remember to update.

**If the capability isn't there yet**, that is one field, not a rewrite: `"needs": ["audio_clips"]`.
The script probes and reports features; on a build without it the tool is hidden and reported
`unavailable` with the reason. Write it once; it lights up when Live does.

The same rule closes a hole in diagnostics: a finding's `fix.tool` must be a catalogue tool, checked
at startup, so a finding can never point at a repair the server doesn't have.

**Prohibitions that keep this true:** no `switch` on tool name outside dispatch; handlers never
import each other (shared logic lives in `state/` or `plans/`); core modules import nothing from
`handlers/` or `plugins/` — asserted by a test, not a convention.

### 18.2 Tool names are the API

- A shipped name is a contract. Its semantics don't change; its args only gain **optional** fields.
- Renaming or removing is a deprecation: `"deprecated": {"since": "0.4", "replaced_by":
  "clips_set_gain", "remove_after": "0.6"}`. The tool keeps working, the guide marks it, the
  server logs a warning. Removal only at a major.
- **Args are closed.** An unknown key is `BAD_ARGS`, never ignored. A typo that silently does
  nothing is the worst failure mode in a tool like this, and the reference implementation has it.
- **Contract snapshots.** `tests/contracts/*.json` hold every tool's schema. An accidental rename or
  type change fails a test; updating a snapshot is a deliberate, reviewable commit.

### 18.3 Protocol handshake and skew

The envelope carries `"v": 1`. On connect the script sends `hello` with
`{protocol, server, live, features[]}`, and the server refuses to proceed on a protocol mismatch
(`UNSUPPORTED`, naming both versions and the fix: `enableton setup`).

Skew is normal — people update the server and forget the Remote Script. So the server hides any
tool whose `needs` aren't in `features[]` and reports them as `unavailable` with "Remote Script is
out of date; run `enableton setup`". Degrade, never break.

### 18.4 Feature detection, not version branches

Nothing anywhere asks `if live_version == "12.2.5"`. The script probes objects and reports
features: `warp_markers_read`, `warp_markers_write`, `insert_device`, `envelopes`,
`create_audio_clip`, `meters`. Tools declare `needs` and `min_live`; missing means `unavailable`
with a reason. A Live upgrade lights up capabilities with no code change; a downgrade removes them
without an exception at call time.

### 18.5 Adding a mode, end to end

A mode is a row. Nothing in a mode is executable, so a new one can't break an existing one.

```json
{
  "name": "drums",
  "summary": "Drum programming and groove",
  "tools": [
    "notes_read", "notes_quantize", "notes_transform", "notes_humanize", "notes_strum",
    "notes_overlaps", "notes_scale_lock", "notes_replace",
    "clips_warp_check", "clips_align_to_grid", "clips_fix_loop_points", "clips_copy",
    "clips_duplicate_range",
    "gen_gesture", "gen_audition", "gen_accept", "gen_discard",
    "library_browse", "library_search", "library_place"
  ],
  "default_scope": "selected_track",
  "examples": [
    "straighten the hats but keep the swing",
    "add a fill on the last bar before the drop",
    "halftime the break and keep the kick"
  ],
  "escalate": true
}
```

That row alone makes `--mode drums` work, adds it to `--mode list`, puts it on the modes screen with
its own fix counts, generates its `ableton_guide` sheet from the tools' summaries and examples, and
changes the model's tool set to those 20 plus the 14 core.

| Field | Meaning |
|---|---|
| `name` | CLI flag, escalate target, saved preference |
| `summary` | one line on the modes screen |
| `tools` | must exist in the catalogue — validated at startup |
| `default_scope` | `set` \| `selected_track` \| `selected_clip` — what the prompt box targets |
| `examples` | producer-language prompts shown on the prompt screen and in the guide |
| `escalate` | whether the mode may reach beyond itself (true everywhere today) |

**Rules that keep modes additive:**

- A mode references tools; it never defines behaviour. Two modes exposing the same tool share one
  implementation — that is the fix for the duplication that made the reference implementation
  unmaintainable.
- **Artifact consumers load the artifact's tools.** `build` loads `recipe_list/show/build` because it
  builds from recipes; `master` loads `mix_snapshot_restore` because it auditions against saved
  mixes. A consumer mode that can only reach its own building blocks is a mode that traps
  capability, and the authoring mode is not the place a producer should have to go to make a beat.
- A mode needs no novel tools. Three of the ten initial modes are pure recombinations.
- A mode that needs a tool which doesn't exist yet is a tool addition first (§18.1a), then a row.
- Removing a mode is deleting a row. Session state stores the name and an unknown name falls back
  to `auto`, so removal needs no migration.
- Renaming a mode changes a CLI flag and a saved preference — a config migration (§18.7), not a
  tool break.
- Modes are fixed for the session (§6), so a new row takes effect on restart. That is the one
  deliberate delay in the system, and it buys a stable `tools/list`.

### 18.6 Adapter seam with a conformance suite

`live/conformance.py` is a test suite every backend must pass: read the set, a track, a clip, a
chain; write a volume; write a note; fail a precondition correctly; report features truthfully.
The fake adapter passes it in M0, the Remote Script in M1, an Extensions backend later — with no
domain changes. Adding a backend means implement, pass, register.

### 18.7 Updating config and cache

`config.json` carries `"version": 1` and a chain of pure old→new migration functions, each tested.
Everything derived — sample index, derived audio, analysis results — carries a `cache_version` and
is **discardable by construction**: the server must work correctly with an empty cache. No user
data ever lives only in the cache.

### 18.8 Third-party extensions

`config.plugins: [path]`, each a directory with `tools.json` + `handlers/`. Loaded after core,
through the same validation (schema, duplicate-effect rejection, `needs`), namespaced
`<plugin>_<tool>` so it cannot collide with core. Off unless configured. This is roughly sixty
lines because the manifest already *is* the extension format — it is not a plugin runtime, and core
never imports a plugin.

### 18.9 What must not change casually

The framing, the closed error-code set, reference resolution, the phase order, and the meaning of
`dry_run`. These are the load-bearing frictions: change one and every handler, test and client
understanding shifts with it. Any change to `server.py`, `plans/executor.py` or `protocol/` needs
an ADR in `docs/adr/` — a short file saying what changed, why, and what breaks.

### 18.10 Recipe packs

A recipe is the cheapest kind of growth: adding a genre is one JSON file in
`src/enableton/recipes/`, or one learned recipe in the user's own directory. No handler, no manifest
entry, no mode row, no release. The validation that applies to tool definitions applies here too: a
recipe is checked at load time — pattern characters, lane/slot agreement, `length_bars`
divisibility, known schema version — and a malformed recipe fails naming its file and field, not
with a stack trace in the middle of a build.

### 18.11 Tests that protect growth

| Test | Fails when |
|---|---|
| drift | a `cmd` has no handler, or a handler has no manifest entry |
| duplicate effect | two tools have the same effect and overlapping preconditions |
| mode coverage | a tool is in no mode, or a mode exceeds 34 |
| conformance | any registered adapter breaks the contract |
| contracts | a tool schema changed without a deliberate snapshot update |
| isolation | core imports from `handlers/` or `plugins/` |
| recipe validation | a shipped or user recipe has a bad pattern, an unknown slot, or an unknown version |
| artifact consumption | a mode that builds from an artifact cannot reach the artifact's tools (`build` → `recipe_*`, `master` → `mix_snapshot_*`) |

---

## 19. Build order

Each milestone is done when its acceptance test passes — measured, not asserted.

**M0 — Skeleton.** `pyproject.toml`, manifest loader + schema generation, mode loader, framing,
transport client, Remote Script skeleton with two commands (`song.summary`, `track.list`), fake
Live server, installer, `doctor`. *Accept:* `pytest -q` green; `enableton doctor` against the fake
reports connected; manifest↔handler drift test passes; `ableton_status` returns a real summary from
the fake.

**M1 — Read path.** Snapshot cache + invalidation; `inspect_structure`, `inspect_unused`,
`mix_levels_report`, `mix_headroom`, `clips_warp_check`, `notes_overlaps`; paging; traces.
*Accept:* against two of the user's real Sets — `Crust Wumble.als` (19 tracks, 120 BPM, 22 Session
clips) as the readable case and `paper tiger heart remaster.als` (77 tracks, 1825 warp markers) as
the stress case — three questions answered from the data, and a trace shows the snapshot read count
per request (target ≤ 1).

**M2 — Write path + safety.** Executor, snapshot/restore, `tracks_gain_stage` and
`clips_duplicate_range`. *Accept:* dry-run trace matches applied trace; forced mid-plan failure
restores state exactly (object-by-object diff); double-apply is a no-op.

**M3 — Diagnostics.** Findings, phases, `inspect_run/plan/autofix`, `ableton_escalate`,
`ableton_plan_apply`. *Accept:* count on the modes screen equals findings per mode before and after;
autofix halts when count rises; `needs_listening` never auto-applies.

**M4 — Full catalogue + modes.** All 86 tools, all 9 modes, guide generation. *Accept:* drift test
green; each mode ≤ 34 tools; every tool appears in ≥ 1 mode; every mode's escalate path reaches
every tool.

**M5 — UX.** `ableton_start`, screens, MCP App bundle, text fallback, elicitation, `enableton ui`.
*Accept:* every screen renders as text with working `ableton_choose` ids; scope chip matches loaded
tool set; back navigation preserves selection and counts; a full flow completes with Apps disabled.

**M6 — Audio tiers.** Meter polling, resample capture, spectral report, `master_loudness_capture`.
*Accept:* capture produces a WAV, analysis reads it, routing-verification catches a failed arm.

**M7 — Library, build, generation, recipes.** Browser folders, place, gestures,
audition/accept/discard, then `recipe_list/show/learn/build/refine` with a starter pack.
*Accept:* the user's own sentence — "create a dubstep drum beat using loops from my riddim one
shots folder" — produces a playable 2-bar pattern whose every sample came from that folder; and
`recipe_learn` on an 8-second reference recovers tempo and half-time feel with a confidence shown
per lane, refusing to guess below 0.6.

---

## 20. Performance targets

Measured in M1/M4 and reported as numbers, not feelings.

| Operation | Target |
|---|---|
| Server startup | ≤ 300 ms |
| Property set (single) | p50 8 ms |
| 1k-note read | ≤ 25 ms |
| 40-track summary | ≤ 120 ms |
| Gain stage across 40 tracks | ≤ 400 ms |
| Snapshot reads per tool call | ≤ 1 |
| Sockets / scheduler instances | exactly 1 / 1 |
| `recipe_learn`, 8 s window | ≤ 900 ms (source-file analysis, no Live round-trip) |
| `recipe_build`, 2 bars / 4 slots | ≤ 2.5 s including sample scoring |

**Scale is measured, not assumed.** The user's Sets run 19, 34, 54 and 77 tracks, with 445–1825 warp
markers and up to 315 arrangement clips. Paging above 40 tracks is mandatory rather than polite, and
the 77-track Set is the stress fixture for every number above: a target met only on a 20-track Set
isn't met.

---

## 21. Risks

| Risk | Mitigation | Trigger |
|---|---|---|
| LOM drift across Live versions | probe at startup, feature-detect, `needs`/`min_live` in manifest | a read that worked stops returning |
| Warp-marker writes are version-fragile | gate `clips_set_warp_mode` / `clips_align_to_grid` writes behind detection, fall back to "nudge + listen" | `add_warp_marker` errors or markers don't persist |
| Remote Script install breaks | `doctor` preflight with exact instructions, config-driven path | socket doesn't answer after setup |
| Live's linear undo can't unwind a plan | our own snapshot transaction + `ableton_undo` | partial plan leaves the Set changed |
| 92 tools overwhelms the model anyway | modes cap at 34; `summary` is one line; guide is generated | model picks wrong tool repeatedly |
| MCP Apps support is uneven | text fallback is mandatory and tested | a screen exists only in the App |
| Resample capture is audible and slow | flagged before running, never implicit | user surprised by sound |
| Two capabilities with the same effect | registry rejects duplicates; effect+precondition test | a duplicate slips into the catalogue |
| Tool names harden into an accidental API that can't change | deprecation window + contract snapshots + closed args | a rename breaks a client workflow with no warning |
| A learned recipe encodes the wrong tempo or feel | per-lane confidence, draft status, explicit confirm before build | a build sounds like the wrong genre |
| Recipe build half-loads a Drum Rack | `place_audio` is the default; `rack` is gated and all-or-nothing | a rack appears with empty pads |
| A recipe's folder holds nothing usable | slot resolution stops and names the slot and folder | a beat builds from unexpected sounds |
| Growth adds core coupling over time | isolation test; ADR required for core edits | a handler import appears in `server.py` |

---

## 22. Open questions

1. **Which Set to test on** — resolved. `F:\ableton songs` holds 66 Sets; `Crust Wumble.als` is the
   M1 readable fixture and `paper tiger heart remaster.als` the stress fixture. M2 still needs a
   scratch copy made before any write test.
2. **Does the App open automatically on `ableton_start`,** or only when asked? Default: automatic
   on first run, remembered after that.
3. **Live 12.4.5 upgrade** — unlocks warp-marker writes, envelopes, `insert_device`. Default: stay
   on 12.2.5, gate those capabilities as `unavailable`.
4. **Meter polling interval** for `mix_meter_poll` — default 100 ms, capped at 5 s total.
5. **Starter recipe pack** — ship six to eight genre rhythms (dubstep half-time, drill, trap,
   garage, house, breaks) so a first session has something to build with, or ship none and learn
   only from the user's references? Default: a small pack marked `status: "shipped"`, overridable
   by id.
