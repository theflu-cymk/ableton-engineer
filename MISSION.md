# Enableton — Mission plan

Written 2026-11-09. **`SPEC.md` owns the design and wins any conflict**; this file owns sequencing,
gates and the verified state of the machine. `PROMPT.md` is the origin brief and is now history.
The earlier TypeScript/Node plan this file used to contain is **withdrawn** — the code on disk is
Python 3.11 + `uv`, and that is correct.

---

## 1. Verified on this machine (2026-11-09)

| Fact | Value | How verified |
|---|---|---|
| Live edition / version | **Suite 12.2.5** | exe `ProductVersion`, `C:\ProgramData\Ableton\Live 12 Suite` |
| Extensions SDK | **unavailable** — needs 12.4.5+, install is 12.2.5 | version compare |
| Backend | **Python Remote Script + LOM over local TCP** | only surface with read + write + observers here |
| Python (server) | **3.11.17 via uv** | `uv run python -V` |
| Runtime dependency | `mcp>=2.3` only | `pyproject.toml` |
| Test runner | pytest 9.2.0 via the `dev` extra | `uv sync --extra dev` |
| Sets root | **`F:\ableton songs`** — **66 working Sets + 126 backups = 192 `.als`** | `find` scan |
| `.als` format | gzip container (magic `1f 8b`) → compressed XML | `head -c 4` on a real Set |
| M1 readable fixture | `F:\ableton songs\in hell Project\Crust Wumble.als` | located |
| M1 stress fixture (unread) | `F:\ableton songs\beat Project\paper tiger heart remaster.als` | located |
| M1 acceptance second fixture | `F:\ableton songs\Fortnight\fortnight Project\fortnight.als` | real snapshot + regression test |
| ABL user library at `Documents\Ableton` | absent — library is redirected (see `SPEC.md` §2) | directory listing |
| Existing Remote Scripts | none — the installer is part of the deliverable | directory listing |

Reconciled: `SPEC.md` says "66 `.als` files"; a naive scan says 192. Both are right — 66 are working
Sets, 126 live in `Backup\` directories. **Any scan or fixture walk must exclude `/Backup/`**, and a
test should assert that, or every count in the spec is wrong by 3×.

---

## 2. State of the build (measured, not claimed)

`uv run pytest -q` is green as of `4d4978a`; the suite's count is deliberately not quoted here, because it changes with every test. Read-path reports committed through `78f8a8b`; `notes_overlaps` is live-verified on `0.2.0` against `fortnight`. The M2 acceptance gates are **real-Live verified on `0.2.3`**: duplicate dry-run matched apply, double-apply was a no-op, exact restore included the clip name, and a forced real mid-plan failure restored the arrangement object-for-object. M2 is complete. M3 is **complete and real-Live verified on `0.2.4`**: the three-fader autofix dropped findings from 25 to 22, a controlled count-rise probe halted and rolled back, `ableton_escalate` produced a stored plan that `ableton_plan_apply` executed from a separate CLI process, and `modes --findings` showed the per-mode counts before and after. All 14 needs-listening findings stayed out of every plan and apply. M4 is in progress: `ableton_guide` now returns the generated command sheet through the MCP tool surface, `enableton inspect`, `enableton plan` and `enableton run` are implemented, and `devices_read_chain`, `master_chain_read` and `sections_map` answer from one snapshot. The catalogue is now 65 tools in 7 modes (`auto 34`, `inspect 23`, `prep 22`, `edit 21`, `arrange 16`, `sound 15`, `mix 21`); the inspect domain has all 8 tools, the notes domain has all 8 (`notes_read` is **Verified on real `0.2.8`** from 46 notes in a real session clip plus an audio clip's unavailable reason; all six writes are **Verified on real `0.2.10`**: quantize, transform, humanize, strum, replace and scale-lock each changed the same 46-note clip and restored it exactly, and seeded humanize reproduced identically), the new `edit` mode loads them, and `tracks_set_pan` plus `clips_rename` are implemented and **Verified on real `0.2.7`**: pan `0.0 → 0.2` on `MUSIC | vOCALS` and a unique arrangement-clip rename both applied, read back from a fresh snapshot, restored exactly, and read back again. **Real `0.2.6` is verified**: `doctor` reported script `0.2.6`, build `d9d5fefaad68`, no `stale`; play/stop, locate (bar 10 → 36 beats, confirmed by the following snapshot), loop set/clear, and loop/playhead restoration all passed.

### Device bypass unavailable; warp-mode write (2026-11-10, `0.2.14`)

**Device bypass is unavailable on Live 12.2.5.** Real scratch attempts on `SCRATCH fortnight` failed because `Device.is_active` has no setter on both device classes tested: `PluginDevice` (`TDR Nova`) and `Eq8Device` (`Remove Mud`). Each attempt ran through the transactional scratch copy and rolled back (`restore.ok: true`); the working device remained active. The attempted `devices_bypass` tool was removed from the catalogue rather than shipped as a write that always fails. This is **Verified** for those two devices on real Live; whether any future Live build exposes a writable path is **Unverified**.

**Warp mode is Verified on real `0.2.14`.** `doctor` reported script `0.2.14`, build `819aec56e3e0`, no `stale`, `errors 0`. On `SCRATCH fortnight`, `VOCALS | Clean lead duplicate 37 [muted]` / arrangement clip `Enableton gate rename` was `complex` (4), warping on, with 2 markers. `clips_set_warp_mode` changed it to `beats` (0), a fresh `clips_warp_check` read back `beats`, and the undo token restored `complex` (4) exactly; warping and the 2 markers were unchanged. The same call also passed on `0.2.13`; `0.2.14` differs only by removing the impossible device tool, and the final restart gate repeated the `complex 4 -> beats 0 -> complex 4` result. No user Set was written: the scratch `.als` mtime remained `2026-11-10 04:19:41`.

### Loop-point write (2026-11-10, `0.2.16`)

**Verified on real `0.2.16`.** `doctor` reported script `0.2.16`, build `1931c2a5be95`, no `stale`, `errors 0` before and after the gate. On `SCRATCH fortnight`, `snare rush` / arrangement clip `SML_Ultra_Riddim2_Kit03_Snare-roll` was looped with loop `0.0–32.0`, warping `beats`, 3 markers, and arrangement boundaries `283.8117–300.3311`. `clips_fix_loop_points` changed the loop range to `0.0–8.0`; a fresh dry-run read back `0.0–8.0`; the arrangement start/end and warp state were unchanged. The undo token restored `0.0–32.0`, and a fresh snapshot still reported the same boundaries. `Clip.length` moved from `32.0` to `8.0` while looped because Live defines it as the loop length; the arrangement boundaries were checked separately and did not move. No user Set was written: the scratch `.als` mtime remained `2026-11-10 04:19:41`.

**A defect found on real `0.2.15`:** the first gate targeted an unlooped clip, where `loop_end` is the clip end. Setting it to `8.0` changed the reported length from `59.8888` to `8.0` before restore. The tool now refuses unlooped clips with `UNSUPPORTED`, and the gate was repeated on the looped clip above. The failed attempt was fully restored and the working Set was not written.

### Catalogue expansion: locators, clip edits, track routing (2026-11-10, `0.3.0`)

**Implemented; the real-Live gate has not run yet.** The catalogue grew from 41 to 52 tools and from
3 to 7 modes. The then-current suite was **Verified green** against the fake LOM; that proves the
handlers are internally consistent, **not** that Live accepts these writes.

New tools (11): `sections_create_locators`, `sections_delete`, `sections_scenes_from_sections`,
`clips_copy`, `clips_transpose`, `clips_clear`, `tracks_duplicate`, `tracks_set_routing`,
`mix_routing_report`, `library_folders`, `library_browse`.

New modes: `prep 19`, `arrange 14`, `sound 9`, `mix 17`; `auto` stays at the 34-tool cap, `edit` is
21 and `inspect` 22. Every tool still appears in at least one mode.

Three limits shaped the design and are **Assumed** until the real gate:

- `Locator.time` is read-only on 12.2.5, so a marker move is a delete plus a create. No
  `sections_move` was added, because it cannot be done in place.
- A cue is toggled at the playhead with `Song.set_or_delete_cue()`, so writing where a cue already
  exists deletes it. `sections_create_locators` reads first and refuses an occupied bar; both
  locator writers put the playhead back afterwards.
- Live has no Session↔Arrangement clip-copy primitive, so `clips_copy` refuses that pair with the
  reason rather than approximating it. `clips_clear` likewise refuses audio, because emptying an
  audio clip would delete material the tool cannot restore.

`setup --force` installed 15 files and removed 11 stale `__pycache__` files. `doctor` still reports
script `0.2.16`, build `1931c2a5be95`, and `stale` against this repo's build `15586a5c8528`; Live
holds the old build in RAM until it restarts.

**Next gate (Unverified until run):** after a Live restart, `doctor` must report script `0.3.0` and
build `15586a5c8528` with no `stale`, then each new write is exercised on `SCRATCH fortnight` with
a dry run, an apply, a fresh read-back and an exact restore.

### Device chain writes (2026-11-10, `0.3.5`)

**Implemented; the real-Live gate has not run.** Five tools, catalogue 52 → 57:

- `devices_set_parameter` — track, device and parameter each resolve by exact name or by index.
  A duplicate device name is `AMBIGUOUS_REF` with the candidate indexes, a value outside the
  parameter's own min/max is refused before Live sees it, and so is a disabled parameter. The undo
  token carries the old number.
- `devices_set_macro` — resolves `Macro N` on a rack and refuses a device without it, because
  macros belong to racks; the number is bounded 1–16.
- `devices_move` — calls `Track.move_device`, then reads the chain back and confirms both the length
  and the device that landed at the target index. The undo token moves it back from where it
  actually ended up.
- `devices_delete` — a one-way door on 12.2.5: `insert_device` is 12.3+, so there is no undo token.
  It applies only with `confirm: true` and is declared `reversible: false`. The plan executor now
  refuses an irreversible tool inside a multi-step plan, because a later failure would leave the Set
  changed with nothing to roll back.
- `devices_browse_presets` — read-only preset folders and presets from the instruments,
  audio-effects and MIDI-effects categories, with a folder cap stated in the result and a reason
  for every category that cannot be read.

`devices_insert` and `devices_load_preset` are **not** shipped: `insert_device` needs 12.3 and no
manifest-level gate is enforced, so the tool would raise at call time; the browser's only load path
(`Browser.load_item`) targets the current selection, not a named device. `devices_bypass` stays out
because `is_active` is read-only on this build.

Modes, counting the five injected core tools the way `enableton modes` does: `sound` 9 → 14,
`mix` 17 → 18; `auto` stays at the 34-tool cap. `uv run pytest -q` →
**354 passed, 7 subtests**, including a new test that the executor refuses a multi-step plan
containing `devices_delete`.

**A real-Live find, fixed in `0.3.2` (Verified).** On loaded `0.3.1`,
`devices_browse_presets` answered `NOT_FOUND` for `EQ Eight`, a folder the real browser holds. The
folder scan stopped at 8 because `MAX_FOLDERS` was doing double duty as scan cap and page size, so
the lookup gave up and reported absence. The scan now reads every folder and slices the page
afterwards: a named device is found wherever it sits, the paging total is real, and `child_count` is
paid only by the folders on the page. Covered by two tests — 12 filler folders ahead of `EQ Eight`,
and a 20-folder walk that pages to the end. The read-only browse worked against the real browser
otherwise: 8 instrument folders and 8 audio-effect folders listed with real URIs and preset counts.

On `0.3.2` the paging fix was **Verified** on the real browser — 93 preset folders across
instruments, audio effects and MIDI effects, with `next_offset` walking the list — but `EQ Eight`
was still `NOT_FOUND`, this time with `0 folders searched`. Live reports a device's preset folder
as `is_folder: False` while still giving it children, and the named lookup required `is_folder`;
the fake had modelled those folders as True, which is why 323 tests said otherwise. `0.3.3` matches
by name, refuses a name present in two categories with `AMBIGUOUS_REF`, and the fake now reports
`is_folder: False` so the suite can catch the same mistake.

**A second real-Live find, fixed in `0.3.3` (Verified).** The first applied write came back
`PRECONDITION_FAILED: applied trace did not match the dry-run trace`, and the executor rolled it
back: a fresh read showed `Utility / Stereo Width` still at `1.0`. Three of the five tools returned
a field only when applying — `applied`, `moved`, and `requires_confirm` inside the deleted row — so
their applied trace could never equal their own preflight. Every payload is now identical in both
modes; `devices_move` reports only `from_index`/`to_index` and verifies the landing internally;
quantised parameters are snapped to the step Live stores before the write; and `_write` raises if
Live reads back a different number. The Set was unchanged by the failed attempt.

**Found and fixed in `0.3.4`:** no tool listed a device's parameters, so the gate recovered
`Stereo Width` by paging `parameter_index` until each refusal named its neighbour. The new
`devices_read_parameters` returns one page of the vector with each parameter's exact name, value,
display string, min, max, quantised flag and enabled flag — the read that makes
`devices_set_parameter` usable without guessing. Catalogue 57 → 58; `sound` 9 → 10 named tools and
`inspect` 17 → 18, which is 15 and 23 with the five core tools. The next real-Live gate reads the
parameters of `Utility` first, then writes one of them.

**Master fader (same build, `0.3.5`).** `master_set_gain` writes
`song.master_track.mixer_device.volume`, the fader the snapshot does not carry and
`mix_levels_report` therefore reports as unmeasured. The payload is identical in dry-run and apply
modes, a read-back that disagrees with the request is a Live error, and the undo token carries the
exact prior number. Catalogue 58 → 59; `mix` 18 → 19 with the five core tools. Nine new tests cover
the dry run, apply, read-back, exact restore, range refusal, a Set with no master track, and the
executor applying it for real.

**Device gate on `0.3.4` (Verified).** `doctor` reported script `0.3.4`, build `f4484257c3ce`, no
`stale`. The Set was `SCRATCH fortnight`,
`F:\ableton songs\Fortnight\fortnight Project\SCRATCH fortnight.als`. `devices_read_parameters`
listed `Utility` (track 24, device 4): 12 parameters, `Stereo Width` at index 4, value `1.0`.
`devices_set_parameter` moved it `1.0` → `0.5`, a fresh dry run read back `0.5`, and the undo token
restored `1.0` exactly; a scratch copy was taken. `devices_browse_presets` found `EQ Eight` with 5
presets after the name fix. The duplicate `Flanger Rebound` devices were refused as `AMBIGUOUS_REF`
with indexes 4 and 5. `devices_delete`'s dry run reported `requires_confirm`, and the unconfirmed
apply wrote nothing.

**Three more real-Live finds, fixed in `0.3.5`.**
- `devices_set_macro` resolved `Macro N` by name. The real `808 Core Kit` rack exposes `Low Gain`,
  `Mid Gain`, `High Gain`, `Gain`, `Drive Amount`, `Drive Tone`, `Glue`, `Vintage` at indexes 1–8,
  then `Macro 9`–`Macro 16` at 9–16. Macros now resolve by position, so a renamed macro still
  answers to its number.
- `devices_move` called `Track.move_device`, which 12.2.5 does not expose. The LOM's mover here is
  `Song.move_device(device, track, position)`; the handler tries the track form first and falls back
  to the song form, verifying the landing either way. **Assumed** until the next gate: the fallback
  is exercised against the fake and against the documented signature, not yet against Live.
- The executor's error payload dropped the tool's code, so an unconfirmed delete surfaced as
  `LIVE_ERROR: write failed and was rolled back`. `_error_payload` now carries `code`, and
  `run_tool` raises with it, so the caller sees `PRECONDITION_FAILED` and the confirm instruction.
  Covered by a fake test; the real-Live confirmation needs the next restart.

**Gate run on real `0.3.6` (Verified).** `doctor` reported script `0.3.6`, build `f844ded966e5`, no
`stale`. The Set was `SCRATCH fortnight`,
`F:\ableton songs\Fortnight\fortnight Project\SCRATCH fortnight.als`.
- `devices_set_macro` on `808 Core Kit` (track 11, `DRUMS | Remix 808 kit`, device 0): macro 1
  resolved to the renamed parameter `Low Gain` at parameter index 1, value `63.35280227661133`.
  Applied `0.25`, a fresh dry run read back `0.25`, and the undo token restored
  `63.35280227661133` exactly. A real rack macro reports its own units, not 0..1.
- `devices_delete` previewed `Flanger Rebound` on track 29
  (`BASS | Riddim wobble + phase + flange [muted]`) with `reversible: false` and
  `requires_confirm: true`; the unconfirmed apply was refused with `PRECONDITION_FAILED` and the
  confirm instruction, and wrote nothing. A confirmed delete removed the duplicate at index 5,
  taking the chain from 6 devices to 5 with a scratch copy first.
- `master_set_gain` moved the master `0.85` → `0.55`, a fresh dry run read back `0.55`, and the
  undo token restored `0.85`.
- `mix_snapshot_save` wrote a snapshot of 32 tracks, 2 returns, 68 sends and 137 fields with no
  unreadable field.

**Two defects the gate found, fixed in `0.3.7` (Unverified until the next restart).**
- `devices_move` worked backward (3 → 2) but not forward: `2 -> 3` was a no-op and `2 -> 4` landed
  at 3. `Song.move_device` indexes the chain *before* the device is removed, so a forward move
  needs the position raised by one. `_move` now compensates, verifies where the device landed on
  whichever mover it used, and raises rather than reporting a move that did not happen; the
  handler's own check caught the bad landing and rolled the failed attempt back. The fake mirrors
  the pre-removal indexing (**357 passed, 7 subtests**).
- `mix_snapshot_restore` compared rounded numbers: the snapshot stored four-decimal faders, so
  Live's `0.794921875` came back as `0.7949` and a dry run reported eight changes where four were
  real. Snapshots, change rows and undo tokens now carry the exact value. The four fields the
  probe perturbed were put back and re-read as `0.85`, pan `0.0`, send `0.0`.

**`0.3.7` forward move still failed (Verified).** On the restarted `0.3.7` build, `2 -> 3` raised
`Live did not move 'Remove Mud' to index 3` and rolled back. The compensation never ran: `_move`
found the start index by object identity, and Live returns a fresh proxy on every `track.devices`
access, so `start` fell back to `to_index` and the forward attempt list collapsed to the single
no-op position. `0.3.8` takes the resolved `device_index` from both callers, tries each candidate
position even when one raises, and the fake resolves a device by name when identity fails. The
snapshot half of the `0.3.7` gate never ran; both are Verified on `0.3.9` below.

**Macro units, fixed and Verified in `0.3.9`.** `devices_set_macro` documented "normally 0 to 1",
but the real rack's `Low Gain` macro reads `63.35` on a 0..127-style range. The manifest now says
`value` is in the macro's native units, and `fraction` takes 0..1 of that range and maps it.
Exactly one of the two is required; the undo token is unchanged.

**Verified on `0.3.9`** (build `fa017e4ba642`, `doctor` clean with no `stale`, on `SCRATCH fortnight`):

- `devices_move` on `Remove Mud` (`BASS | Remix midbass`, index 24): backward `3 -> 2` and forward
  `2 -> 3` each landed at the requested index and each undo token put it back. The chain returned to
  `Wobbly Flag Bass, Saturator, Auto Filter, Remove Mud, Utility`. This is the exact case `0.3.6`
  and `0.3.7` both failed; the forward compensation is real now, not a no-op.
- `mix_snapshot_save` wrote `m_7182b8d5` with 32 tracks, 2 returns, 68 sends, 137 fields and no
  unreadable rows. Perturbing two faders, a pan and a send produced exactly four dry-run changes,
  apply left zero, and undo brought back exactly four. The values came back raw
  (`0.8500000238418579`, `0.33000001311302185`, `0.42000001311302185`), so rounding is gone.
- `devices_set_macro` macro 1 on the `808 Core Kit` rack (`DRUMS | Remix 808 kit`, track 11): range
  `0 .. 127`, sitting at `63.35280227661133`. `fraction: 0.5` wrote `63.5` — the exact midpoint —
  read back `63.5`, and the undo token restored `63.35280227661133` exactly. The earlier `value`
  path remains the native-units form.

### Track cleanup shipped (`0.4.0`)

**Implemented and real-Live Verified on `0.4.4` (evidence at the end of this section).**
`tracks_delete` and `tracks_clean_empty` (catalogue 61 →
63, both in `prep`) delete a resolved track or every empty one. Neither is reversible on this build,
so both declare `reversible: false`: a dry run reports what would go, an apply without `confirm:
true` raises `PRECONDITION_FAILED` and writes nothing, a Set that would be left with no tracks is
refused, and every delete checks the count fell by exactly one and that the next track moved into
the freed index. `tracks_clean_empty` refuses a named track that holds clips instead of skipping
it, and deletes in descending index order. Autofix never plans an irreversible tool, so the
empty-track finding now reports "cannot be undone" rather than "not implemented". `Song.delete_track` takes an **int index**, not a track object: on `0.4.1` the object form raised
`Python argument types in Song.delete_track(Song, Track) did not match C++ signature:
delete_track(ASong, int)`. The M2 duplicate restore passed a track object, so that rollback path was
latently broken; `0.4.2` uses the index in both the restore and the new delete.

**`0.4.0` failed its first gate (Verified).** `tracks_clean_empty` raised `INTERNAL: tracks.clean_empty
failed: Main, Group and Return Tracks have no arrangement clips` on `SCRATCH fortnight`: Live raises
when `arrangement_clips` is read on a group track, and `song.tracks` includes them. Nothing was
written. `0.4.1` reports `(None, None)` for a group without reading its clips, never lists a group
as empty, and refuses `tracks_delete` on a group outright because deleting it would take the tracks
inside it too.

**`0.4.1` exposed a tool-surface defect (Verified).** On the `0.4.1` gate, `tracks_duplicate`
created its copy and then the executor rejected the apply: `applied trace did not match the dry-run
trace`. The dry run and the applied result had different shapes, and `_clean` strips only `dry_run`
and `undo`, so any apply through `run_tool` failed after the write. `tracks_delete` and
`tracks_clean_empty` were written the same way and would have failed identically; the gate never
reached them. The rollback left one copy (`9-Audio`), which was deleted by name with the same tool.
`0.4.2` returns one payload on both paths — names and undo tokens stay in `undo` — and two new tests
apply `tracks_clean_empty` and `tracks_duplicate` through `run_tool` so the trace check is exercised
against the fake. The same gate proved `Song.delete_track`'s real signature: the object form raises a
C++ type error, so `_restore_duplicates` was fixed to pass the index as well.

**Live renumbers default audio-track names when positions shift (Verified).** Duplicating `8-Audio`
made Live rename the existing `16-…` and `21-…` tracks to `17-…` and `22-…` as their indices moved,
so a name-by-name comparison of the track list is not a valid post-write check. `0.4.3` verifies a
delete by the track count alone, because the follower-name check false-failed a correct delete on a
renumbered track; the gate compares kind, clip counts and device counts instead of names.

**Verified on `0.4.4`** (build `0e541593c21c`, `doctor` clean with no `stale`, on `SCRATCH fortnight`):

- `tracks_clean_empty` over the whole Set listed only `8-Audio` — no group track, no return, no
  false positive — with `requires_confirm: true`.
- A duplicate of `8-Audio` landed at index 8 as `9-Audio`; renamed to a gate name, it was listed by
  name and then deleted through `tracks_clean_empty` with `count: 1`, returning the Set to 34 rows
  and the same structural projection (kind, session fill, arrangement clips, device count).
- A duplicate of a clip-bearing track landed at index 2 as `3-Vocals …`; the `tracks_delete` dry run
  reported 2 arrangement clips and 0 session clips, an apply without `confirm` returned
  `PRECONDITION_FAILED` and wrote nothing, a named `tracks_clean_empty` returned
  `PRECONDITION_FAILED` ("is not empty"), and the confirmed delete removed it and restored the
  34-row structure exactly.
- A group track (`REVocals`) was refused by `tracks_delete` with `PRECONDITION_FAILED` and stayed.
- Every applied step went through `run_tool`, so the dry-run/apply trace check passed each time;
  the Set was not saved, and Live's default audio-track renumbering was observed again.

### Section move and transaction undo (`0.4.6`)

**Verified on `0.4.6`** (build `981ecb5b07b5`, `doctor` clean with no `stale`, on `SCRATCH fortnight`).

The first `0.4.5` gate failed at its first write, before any move: `sections_create_locators` asked
for bar 1 and Live put the cue at beat 368, the old playhead. Live applies `current_song_time`
between display ticks, so a handler cannot seek and toggle in the same call. The same run exposed
`sections_delete` returning `deleted: 0` on the dry run and `deleted: n` on apply, which made the
executor roll every delete back on a trace mismatch. Both are fixed in `0.4.6`: cue handlers are
resumable steps, the bridge keeps the request pending until the next `update_display`, and the fake
now models the tick so a regression fails in the suite. The failed probe's auto-named cue `2` at
beat 368 was gone after the restart because the Set had not been saved; the gate confirmed the
baseline held one locator.

- Baseline: one locator (`1` at beat 64.7414), 34 tracks, playhead 372.0.
- `sections_create_locators` created `Enableton gate move` at bar 1 and put the playhead back
  unchanged — the first real proof that the deferred seek/toggle path works.
- `sections_move` gave the same `moved` payload in dry run and apply; the marker landed at bar 5
  (beat 16) with its name, the old beat was clear, the locator count was unchanged, and the
  playhead was preserved. `scratch_copy` is the only extra key on the applied single-tool result
  and is envelope metadata, not part of the tool payload.
- `ableton_undo` restored the marker to bar 1 (`ok: true`, `restored: 1`); a second undo refused
  with `PRECONDITION_FAILED: no applied transaction to undo`.
- An occupied destination was refused with `PRECONDITION_FAILED`, naming the marker already at bar
  9; both markers stayed in place.
- `tracks_set_pan` took `2-Vocals …` from raw pan `0.0` to `0.25`, and `ableton_undo` restored
  exactly `0.0`.
- After cleanup the locator list, the 34-row track projection and the playhead matched the
  baseline exactly. The Set was not saved.

- `sections_move` selects one locator by exact bar or unique name and moves it to `to_bar` as a
  create at the destination followed by a delete at the source, because `Locator.time` has no
  setter on 12.2.5. An occupied destination is refused instead of replaced, the locator keeps its
  name, the playhead is put back, and the undo token moves the cue back.
- `ableton_undo` consumes the transaction record the executor now writes after every applied write:
  tool name, script command and the tool-owned restore tokens, kept for 10 minutes under
  `%APPDATA%\Enableton\transactions` (injectable root in tests). It refuses when nothing is stored,
  when the record expired, or when the current Set is not the Set the transaction was applied to.
  Restores replay in reverse; the record is cleared after the attempt and failures are reported
  rather than retried, because replaying half an undo is not idempotent.
- Both are in the catalogue (65 tools) and reachable: `sections_move` in `arrange`, `ableton_undo`
  in `prep` and `arrange`. The fake tests prove internal consistency only; the gate below is the
  first real-Live proof.

**Accounting:** the previously wrong rows are corrected in the current table below.
`tracks_delete`, `tracks_clean_empty`, `ableton_undo` and `sections_move` are implemented and
covered by their gates; of the seven-row bounded audit, only `devices_insert`, `devices_bypass` and
`devices_load_preset` remain absent.

### M4 catalogue audit (2026-11-10)

**Method.** 65 unique tools in `tools.json`; each was matched against a named real-Live result in
this file. A green fake test, an implemented handler or a mention in a tool list is not evidence.
Counts and mode membership were read from the JSON, not copied from prose. Branch state at
`b7c2e11`.

**Mechanical checks (Verified).** 65 tools; per-mode totals including the five core tools:
`auto 34`, `inspect 23`, `prep 22`, `edit 21`, `arrange 16`, `sound 15`, `mix 21`. Every non-core
tool is in at least one mode, every mode escalates, no mode exceeds 34, and no mode names a tool
missing from the catalogue. `pytest -q tests/test_drift.py tests/test_modes.py tests/test_manifest.py`
→ **21 passed**. `doctor` at audit time: script `0.4.6`, build `981ecb5b07b5`, no `stale`.
`status`: `SCRATCH fortnight`, 32 tracks, 2 returns, 11 scenes, 1 locator,
137 arrangement / 113 Session clips, 114 devices, playhead 372.0.

**Verified on real Live — 51 tools.** 35 applied a change or wrote a report file; 16 are read-only
with a real result:

- notes: `notes_read` (0.2.8); `notes_quantize`, `notes_transform`, `notes_humanize`, `notes_strum`,
  `notes_replace`, `notes_scale_lock` (0.2.10); `notes_overlaps` (0.2.0).
- clips: `clips_duplicate_range` (0.2.3), `clips_rename` (0.2.7), `clips_set_warp_mode` (0.2.14),
  `clips_fix_loop_points` (0.2.16), `clips_warp_check`.
- tracks: `tracks_list`, `tracks_set_sends` and `tracks_name_and_color` (0.2.12),
  `tracks_set_volume` (M3 autofix), `tracks_set_pan` (0.2.7, again on 0.4.6), `tracks_delete` and
  `tracks_clean_empty` (0.4.4), `tracks_duplicate` (apply and retry on 0.4.7, cleanup on 0.4.8).
- devices: `devices_read_chain`, `devices_read_parameters`, `devices_browse_presets`,
  `devices_set_parameter` (0.3.4), `devices_set_macro` (0.3.6, again on 0.3.9), `devices_move`
  (0.3.9), `devices_delete` (0.3.6).
- master and mix: `master_chain_read`, `master_set_gain` (0.3.6), `mix_headroom`,
  `mix_snapshot_save` (0.3.6), `mix_snapshot_restore` (0.3.9).
- sections and transport: `sections_map`; `sections_create_locators`, `sections_move` and
  `sections_delete` (0.4.6); `transport_play`, `transport_stop`, `transport_locate`,
  `transport_set_loop` (0.2.6).
- core and inspect: `ableton_status`, `ableton_escalate`, `ableton_plan_apply`, `ableton_undo`,
  `inspect_structure`, `inspect_unused`, `inspect_run`, `inspect_plan`, `inspect_autofix`,
  `inspect_export`.

`ableton_guide` is the one tool with no Live call to gate: it builds the command sheet locally and
its MCP surface is covered by the suite.

**Caveat on the three bulk track writes.** The duplicate-name guard is **Verified on real `0.4.7`**
for all three tools. `tracks_set_volume` and `tracks_set_pan` are Verified for a uniquely named
track with exact undo; `tracks_gain_stage` still has no measured write and remains in the no-gate
table. The old "writes every match" defect is fixed, not merely re-gated.

**No real-Live gate yet — 13 tools.**

| Tool | Modes | Evidence today | The gate must prove |
|---|---|---|---|
| `sections_scenes_from_sections` | arrange | 0.3.0 handler, fake tests | scenes created at real locators, read back, and a working cleanup path |
| `clips_copy` | edit, arrange | 0.3.0 handler | Session→Session and Arrangement→Arrangement copies; Session↔Arrangement refusal; exact undo |
| `clips_transpose` | edit, arrange | 0.3.0 handler | a real MIDI transpose and exact note restore |
| `clips_clear` | edit | 0.3.0 handler | a real MIDI clear and exact restore; audio refusal |
| `tracks_gain_stage` | prep | restore path on 0.2.1; no measured write | a real measured peak and exact volume undo |
| `tracks_set_routing` | prep, mix | 0.3.0 handler | real input/output names, type before channel, exact restore |
| `mix_routing_report` | inspect, mix | 0.3.0 handler | a real routing table |
| `library_folders` | sound | 0.3.0 handler | real browser roots and paging |
| `library_browse` | sound | 0.3.0 handler | a real folder page and its children |
| `inspect_report` | auto, inspect, prep | fake tests | a report from a real findings run |
| `inspect_finding` | auto, inspect, edit | fake tests | a real finding fetched by id |
| `mix_levels_report` | auto, inspect, mix | fake tests | real faders; the master stays unmeasured with a reason |
| `ableton_plan_discard` | core | fake tests | create → discard → second discard returns false |

**Three bundles, one reset each.**

- **A — clip and section writes:** `clips_copy`, `clips_transpose`, `clips_clear`,
  `sections_scenes_from_sections`. No known code prerequisite, but check the scene handler's
  cleanup path before writing: `Song.delete_scene` may be irreversible on this build and must not be
  discovered mid-gate.
- **B — track identity and routing:** `tracks_set_routing`, `mix_routing_report`,
  `tracks_duplicate`, plus a re-gate of `tracks_set_volume`, `tracks_gain_stage` and
  `tracks_set_pan`. Blocked until the duplicate-name and duplicate-idempotency findings are fixed in
  one build with tests.
- **C — reads, reports and local surface:** `library_folders`, `library_browse`, `inspect_report`,
  `inspect_finding`, `mix_levels_report`, `ableton_plan_discard`. The note-overlap rounding fix and a
  fresh `notes_overlaps` read belong in this reset because no write is involved.

**Defects that must land before their gate (from the M1–M3 review).**

- **Duplicate track names write to every match — confirmed in code.** In
  `remote_script/Enableton/handlers/tracks.py`, `set_volume`, `gain_stage` and `set_pan` build
  `targets` with `track.name in wanted`, so a duplicated name changes every matching track;
  `_one_track` already refuses ambiguity for sends, name/colour, routing, delete and duplicate.
  **Unverified on real Live** until a duplicate is exercised. Blocks bundle B and invalidates the
  "unique names only" part of the three bulk writes above.
- **Duplicate-plan applies are not idempotent through `run_tool`** — review finding, not reproduced
  here. Blocks the `tracks_duplicate` re-gate.
- **Rounding can hide tiny note overlaps** — review finding; the existing `notes_overlaps` evidence
  counts 0.0001-beat intersections, so this is a report-correctness defect, not a missing gate.
  Fix and re-read in bundle C.

**Status of the `0.3.6` blocker.** That gate is already recorded as Verified in §2: on `0.3.6`,
build `f844ded966e5`, `devices_set_macro` moved `Low Gain` `63.35280227661133 → 0.25 →` back exactly, a confirmed `devices_delete` removed one duplicate, `master_set_gain` moved
`0.85 → 0.55 → 0.85`, and `mix_snapshot_save` wrote 32 tracks / 2 returns / 68 sends / 137 fields.
Live is now on `0.4.6`; re-running `0.3.6` would mean downgrading the installed script for an
already-passed gate, so the current read-only `doctor`/`status` output is the correct evidence.

**Branches.** `m4-offline-accounting-5317737` at `7de7e66` is superseded by the accounting section
below. It is based before `0.4.6`; its 61-tool counts and deferred rows would regress the current
ledger. Do not merge it. `m5-serve` is independent (8 files, +814 lines) and should merge only when
M5 starts, which §3 forbids before M4 is green.

### Unavailable-capability accounting (2026-11-11, current)

**Unavailable** means the capability does not exist on this Live build; **deferred** means it is
implementable or feasible but deliberately not shipped. At `a4d9681`, `tools.json` has 65 unique
tools. The seven-row bounded audit is now closed for `sections_move`, `tracks_delete`,
`tracks_clean_empty` and `ableton_undo`; all four are implemented and covered by their gates. The
three rows below remain absent; the other 24 catalogue gaps are outside this bounded accounting.

| SPEC capability | Disposition and evidence |
|---|---|
| `devices_insert` | **Unavailable, Verified** from SPEC §2's LOM version gate: `Track.insert_device` requires Live 12.3+, so it is unavailable on Live 12.2.5. No real insert attempt was made. |
| `devices_bypass` | **Unavailable, Verified** on real Live 12.2.5 for `PluginDevice` and `Eq8Device`; `Device.is_active` has no setter. Future-build support remains **Unverified**. |
| `devices_load_preset` | **Unavailable, Assumed**: the known browser load path appears to target the current selection, not a resolved device, but this was never probed. A settable `song.view.hotswap_target` may permit a resolved-device load, so this needs a probe. |

This accounting is documentation-only; no runtime reporting or Live capability changed.

### Bundle B gate on `0.4.7` (2026-11-10)

**Verified loaded build.** `doctor` reported script `0.4.7`, build `0606e8763f6e`, no `stale`,
Live 12.2.5, `super_errors 0`. The Set was `SCRATCH fortnight`,
`F:\ableton songs\Fortnight\fortnight Project\SCRATCH fortnight.als`: 32 tracks, 2 returns, 11
scenes, 1 locator, 137 arrangement / 113 Session clips, 114 devices, playhead 372.0. Baseline
duplicate names were `BASS | Operator sub` at 17/25 and `BASS | Factory chops [muted]` at 27/31.
The Set file mtime stayed `2026-11-10 04:19:41`, size 1,555,091 bytes; the Set was not saved.

**Verified on real Live.**

- **Ambiguity guard.** All six dry calls (`tracks_set_volume`, `tracks_set_pan` and
  `tracks_gain_stage` against both duplicate names) returned `AMBIGUOUS_REF` before any change;
  every duplicate row kept its index, volume and pan.
- **`tracks_set_volume`.** `8-Audio` moved `0.8500000238418579 -> 0.70`, a fresh read returned
  `0.7`, and `ableton_undo` restored `0.8500000238418579` exactly. A scratch copy was made first.
- **`tracks_set_pan`.** `8-Audio` moved `0.0 -> 0.2`, a fresh read returned `0.2`, and
  `ableton_undo` restored `0.0` exactly.
- **Duplicate idempotency.** The first applied `tracks_duplicate` created one copy at index 8
  (Live named it `9-Audio`), taking the Set to 33 tracks. An identical second `run_tool` call in
  the same process left the count at 33, returned the same `created` plan, and carried no second
  `scratch_copy`. The retry did not duplicate again.

**Duplicate cleanup failed, then was recovered.** The applied undo token was
`{"track_index": 8, "name": ""}` because Live had not assigned `9-Audio` when the handler read
`new_track.name`; restore refused with "the track at that index has a different name". A restore
with `{"track_index": 8}` alone deleted `9-Audio`, returned the Set to 32 tracks, and put
`8-Audio`/`REDRUMS` back at 7/8. `0.4.8` omits an empty name from the token and has a test that
renames the copy after the apply. This is a real defect the fake could not show. `0.4.8` is loaded as build `dc6e1b4e6405` with **396 passed, 7 subtests**. On the re-gate, the token
was `{"track_index": 8}` with no empty name; the first apply made 33 tracks, the identical retry
stayed at 33 with no second `scratch_copy`, and the tool's own restore deleted `9-Audio` and returned
the Set to 32 tracks with `8-Audio`/`REDRUMS` at 7/8 and baseline volume/pan. The Set mtime stayed
`2026-11-10 04:19:41`; `doctor` after reported `0.4.8`, build `dc6e1b4e6405`, `ran 13`, `errors 0`,
`super_errors 0`, no `stale`.

**Routing is not gateable on this build.** `mix_routing_report` returned real output-type names,
but all 32 rows had `input_channel` and `output_channel` as `<Track.RoutingChannel object at
0x...>` and an empty `type`. A dry `tracks_set_routing` on `snare rush` predicted
`REDRUMS -> Sends Only`, but its undo token also carried the two channel object reprs; the output
channel list has one entry with no display name, and the output-type list contains two
indistinguishable `Main` entries. No routing write was applied: the tool cannot build an exact
restore token for the channel fields. This invalidates the `mix_routing_report` and
`tracks_set_routing` rows until the handler carries identifiers (the LOM's `identifier` field)
and resolves restore by them.

**`0.4.9` routing identifiers (real read Verified; write gate failed before writing).** The
handler reads `identifier` beside `display_name`, uses the identifier when a channel has no display
name instead of an object repr, carries both label and identifier in the report and undo token,
and resolves restore by identifier first. `mix_routing_report` also derives each track's kind when
Live does not expose `track_type`. The fake suite was **399 passed, 7 subtests**; that proves
handler consistency only.

After the 2026-11-11 restart, `doctor` reported script `0.4.9`, build `68c44768f8d8`, no `stale`.
On `SCRATCH fortnight`, `mix_routing_report` returned 32 tracks and showed that Live 12.2.5 does
**not** expose routing identifiers here: the available output types include two indistinguishable
`Main` entries, the sole output-routing channel has neither name nor identifier (`?`), and every
row was flagged for a null or nameless channel. A dry run of `tracks_set_routing` on `snare rush`
(`REDRUMS` -> `Sends Only`) returned an undo token that also contained the unchanged
`input_type: Ext. In`; a dry-run restore refused that field because Live does not list `Ext. In`
in `available_input_routing_types`. No apply was made; the scratch `.als` mtime and size were
unchanged.

**`0.4.10` routing gate (Verified for an unambiguous route).** The token now carries only fields
the call actually changes, so an unchanged input type cannot block restore. A regression test
covers a current input type absent from the available list; the fake suite is **400 passed, 7
subtests**. After the second restart, `doctor` reported script `0.4.10`, build `294c9c9c1043`, no
`stale`, `ran 13`, `errors 0`, `super_errors 0`; `status` reported `SCRATCH fortnight` with 32
tracks, 2 returns and 11 scenes. A dry run of `snare rush` `REDRUMS` -> `Sends Only` returned only
`output_type` in the undo token, and its dry-run restore reported `missing: []`. The apply changed
the route, a fresh `mix_routing_report` read `Sends Only`, and the restore read `REDRUMS` again in
the final report. Scratch copies were made at `SCRATCH-fortnight-20261111T010807Z.als` and
`SCRATCH-fortnight-20261111T010809Z.als`; the staging `.als` mtime and size were unchanged. This
verifies the unambiguous route only: Live exposes two indistinguishable `Main` output types and a
nameless sole output channel, so those remain unaddressable by this build; `mix_routing_report`
still flags all 32 rows for null channels.

**`0.4.11` index-based routing (index behavior Verified; response metadata defect found).** A
shared `routing.py` derives a signature from label, identifier, `category`, `attached_object` and
`layout`, then matches the current value to its option index. Both the report and the writer expose
`*_index`; `tracks_set_routing` accepts a name or an index for each field, refuses both at once,
and stores the previous index in the undo token. Restore selects by index first and verifies the
label/identifier still match, so two `Main` options cannot silently swap. The report no longer
flags a null channel, and a nameless channel with a resolved index is addressable rather than
unreadable. The fake suite was **403 passed, 7 subtests**, including duplicate `Main` and
nameless-channel apply/restore.

On real `0.4.11`, `8-Audio` resolved its two `Main` output types at indexes **1** and **19**, and
its nameless output channel at **0**. Selecting index 19 changed the report to index 19; restoring
the token returned it to index 1. The nameless channel selected and restored at index 0 with
`missing: []`. The gate found one defect: the response reported `track_index: 1` instead of the
track's real index 7, because the token-building loop reused the variable. The undo token held 7,
so restore worked. No Set was written; the scratch `.als` mtime and size stayed unchanged.

**`0.4.12` track-index fix (Verified on real `0.4.12`).** The track index is distinct from the
option index, and a regression test asserts both the response and the undo token carry the real
track index. The fake suite is **403 passed, 7 subtests**. `doctor` before and after the gate
reported script `0.4.12`, build `255792c12695`, no `stale`, `ran 22`, `errors 0`, `super_errors 0`;
`status` reported `SCRATCH fortnight` with 32 tracks. On `8-Audio` (track index 7), the two `Main`
output types resolved at indexes 1 and 19. The dry run and apply both reported `track_index` 7;
the undo token carried 7, `output_type` `Main` and index 1. Applying index 19 changed the report to
index 19; restoring the token returned it to index 1. The nameless output channel applied and
restored at index 0 with `missing: []`. Four scratch copies were made under the Enableton backup
folder; the staging `.als` mtime and size were unchanged. This verifies the index path and the
corrected response metadata.

**`0.4.13` zero-option report fix (Verified on real `0.4.13`).** A nameless current routing value
is now flagged only when that field has at least one selectable option. On `SCRATCH fortnight`,
`mix_routing_report` returned 32 rows; 19 rows had `input_channels: 0`, and none carried an
`input_routing_channel` reason. The report's `flagged` list was empty. `8-Audio` (track index 7)
still read `input_channel: null`, `input_channels: 0`, output type `Main` at index 1 and the
nameless output channel at index 0, with no reason. `doctor` before and after reported script
`0.4.13`, build `e9fb28eabb94`, no `stale`, `ran 2`, `errors 0`, `super_errors 0`. The fake suite
is **404 passed, 7 subtests**; the staging `.als` mtime and size were unchanged.

**Gain staging cannot write on this build.** A dry `tracks_gain_stage` over the whole Set returned
`changes: 0` and `skipped: 32`; every real `Track.peak_db` read was `None`. The audit's
"`tracks_gain_stage` (0.2.1)" evidence was only the restore path (`0.85 -> 0.5` through a restore
token), not a measured-peak normalization. Real 12.2.5 exposes meters (`output_meter_level`,
0..1) rather than `peak_db`; a measured write needs that fallback and playback before it can be
claimed.

**Verdict.** Bundle B is **not green**. Volume, pan, ambiguity, duplicate idempotency and duplicate
cleanup are Verified on real Live (`0.4.7` writes, `0.4.8` cleanup); routing indexes are Verified
on real `0.4.12`, including duplicate `Main` 1/19 and nameless channel 0. `mix_routing_report` no
longer flags zero-option input channels: 19 such real rows are clean and `flagged` is empty.
`tracks_gain_stage` remains a blocker. No user Set was written.

### Tracks sends and name/colour (2026-11-10, `0.2.12`)

**Verified on real `0.2.12`.** `doctor` reported script `0.2.12`, build `05e390922f63`, no `stale`, `errors 0`. The gate checked the Set name and file path before writing: `SCRATCH fortnight`, `F:\ableton songs\Fortnight\fortnight Project\SCRATCH fortnight.als`. On `MUSIC | vOCALS` (index 5) the before state was colour `16725558` and sends `A-Reverb 0.0`, `B-Delay 0.0`. Sends were applied as `0.21` and `0.09`, read back from a fresh `tracks_list`, and restored exactly to `0.0` / `0.0`. Name and colour were then applied as `GATE 0.2.12 VOCALS` and RGB `9160191`; a fresh read by index returned the exact name and colour; the undo token restored `MUSIC | vOCALS` / `16725558` exactly, with sends still `0.0` / `0.0`. `tracks_list` now returns `color` and a per-return `sends` map.

The first real read found a defect the fake could not: Live's `Track.color` is packed `0xRRGGBB`, not a palette index. `0.2.11`'s `0..69` validation rejected the real value and made an undo token containing `16725558` unreplayable; `0.2.12` accepts `0..16777215`, and the tool description records that Live snaps a requested RGB to its nearest track colour. No user Set was written: the scratch `.als` still has its pre-gate mtime `2026-11-10 04:19:41`.

**The real-Live gate has been passed once (2026-11-09).** `uv run enableton status` returned a real
summary from Live 12.2.5 — 4 tracks, 2 returns, 8 scenes, 120 BPM, 2 devices, `is_playing false` —
with the script reporting `0.1.4`, `build 8639fd918559` matching this repo, and `display`/`drains`
advancing between two `doctor` calls (432 → 437). That is one command's worth of evidence, on an
untitled Set: enough to prove the transport, the main-thread queue and `resolve_song`, not enough to
call M1 done.

### What the first real read found (2026-11-09, `Crust Wumble`)

Four defects that only real material exposed, each fixed with a test. The suite was green with every
one of them present, which is the point:

| Defect | Symptom on the real Set | Fix |
|---|---|---|
| bars floored instead of rounded up | `bars: 95` beside a section ending at bar 96 | `math.ceil` in `_total_bars` |
| section `clips` counted bar incidences | 520 "clips" in a Set holding 315 | distinct `clips` + `clip_spans` |
| "unity" tested `volume >= 0.999` | flag listed nothing; Live's 0 dB is 0.85 | read `str_for_value`, fall back to 0.85 |
| return tracks counted as waste | A-Reverb and B-Delay reported unused | `kind == "return"` excluded |

Measured, not assumed: **every command performed exactly 1 live read** (five commands, `doctor`'s
`ran` counter moving by +1 each time), so M1's ≤ 1 target holds for the tools that exist.

### What the second real read found (2026-11-10, `Crust Wumble`, script `0.1.5`)

**Verified.** The restart loaded `0.1.5`; `doctor` reported `build b1576889f228` with no `stale`
line, so the digest gate from `AGENTS.md` closed on real evidence.

- **The locator false negative was the attribute name.** `captured` came back
  `locators_attribute: cue_points`, `locators_reason: null`, count 0 — `Song.locators` does not
  answer on 12.2.5 and `cue_points` does. A direct parse of the file shows
  `<Locators><Locators /></Locators>` and **zero** `<Locator>` elements, so 0 is the truth and the
  fixture table's "1, unnamed" was a parser counting the empty wrapper.
- **Devices: 102 read, 108 in the file.** The gap is the master chain. All 108 device elements sit
  under `<Tracks>` (102) plus `<MainTrack>` (6: one `AudioEffectGroupDevice` and the five devices
  inside it). `snapshot.get` walked `tracks` and `return_tracks` only, so the master was invisible.
  `0.1.6` reads `song.master_track` through the same recursive walk and adds
  `counts.devices_master`; `counts.devices_total` now includes it.

**Verified after the restart onto `0.1.6` (2026-11-10):** `doctor` reported `script 0.1.6`,
`build 6f6efe415c7e`, no `stale`. On the Set Live opened — an untitled 4-track default —
`captured.master_available` was `true` with `master_reason: null`, and `master_track.device_count`
was 0, matching `counts.devices_master: 0` and `devices_total: 2`. So `song.master_track` answers
on 12.2.5, and an empty master reads as empty rather than as an error.

**Verified with `Crust Wumble` open (2026-11-10):** `status` reported `devices_total: 108` from 18
top-level devices across 17 tracks and 2 returns. The raw snapshot's `master_track` held exactly the
six file devices: `KIS_FREE Techno Mastering Chain` (`AudioEffectGroupDevice`) containing
`EQ Eight`, `Saturator`, `Multiband Compression`, `Mastering - Add Sustain` and `Limiter`.
`counts.devices_master` was 6, `master_available` true, `master_reason` null. The 102 → 108 gap is
closed on real Live, not just in a fixture.

### Warp state verified (2026-11-10, `0.1.7`)

`0.1.7` gives every audio clip — arrangement and Session — `warping`, `warp_mode` (raw enum plus
name) and `warp_markers` (count, or `None` with `warp_markers_reason`), plus `counts.warp_markers`
and `counts.warp_markers_unreadable`.

**Verified with `Crust Wumble` open:** 894 markers across 334 audio clips,
`warp_markers_unreadable: 0`. The `.als` holds 930 `<WarpMarker>` elements, but only 894 sit inside
its 334 `<AudioClip>` elements; the other 36 are instrument markers in a Simpler `MultiSampleMap`
(`SampleWarpProperties` under `Player`). The per-clip distribution matched exactly (two 108s, one 4,
twelve 3s, 319 2s), so 894 is the correct clip total and the table's 930 conflated clips with an
instrument.

The same read exposed an enum bug: one clip returned `warp_mode: 6` with no name. The LOM documents
**5 = REX, 6 = Complex Pro**; the shipped table had 5 = Complex Pro and no REX. `0.1.8` corrects it
and a test walks all seven values.

**Verified after the restart onto `0.1.8`** (`build 21f8e371499b`, no `stale`): Crust Wumble read
894 markers again with `warp_markers_unreadable: 0`, and the mode-6 clip now reports
`warp_mode_name: "complex_pro"` with 3 markers. Mode counts were 277 `beats`, 56 `complex` and 1
`complex_pro`; no audio clip had an unnamed mode.

**Also verified on `paper tiger heart` (2026-11-10, `0.1.8`):** 14 tracks, 73 arrangement and 66
Session clips, 139 audio clips, `counts.warp_markers: 547`, `warp_markers_unreadable: 0`, every mode
`beats`. A direct parse of `paper tiger heart.als` finds the same 547 markers under its 139
`AudioClip` elements. This is **not** the 77-track stress fixture: `paper tiger heart remaster.als`
holds 1825 markers (1787 under 245 clips) and has not been read live yet.

**Substitute stress read — `paper tiger heart update og` (2026-11-10, `0.1.8`):** 52 tracks plus 2
returns, 324 arrangement clips, 299 audio clips, `counts.warp_markers: 932`,
`warp_markers_unreadable: 0`, every mode `beats`. The snapshot took **412.6 ms** and was **83,739
bytes**. The file holds the same 932 markers under its 299 `AudioClip` elements and the per-clip
distribution matches exactly (`{164: 1, 81: 1, 3: 93, 2: 204}`). This is a **substitute**, not the
M1 acceptance fixture: the 77-track remaster has still not been loaded.

### `clips_warp_check` (2026-11-10)

The first missing M1 report is built: a snapshot-only report with paging, per-clip flags for
unreadable markers, zero markers and unknown modes, and summaries of warp state and modes. Warping
off is counted, not flagged — it is a legitimate state, and the snapshot cannot know whether a clip
was meant to follow tempo.

**Verified against `paper tiger heart update og*`:** 299 audio clips, 932 markers, 127 warping on and
172 off, every mode `beats`, `flagged: 0`, `markers_unreadable: 0`. Suite **127 passed**. No Remote
Script change, so no version bump or restart was needed — the report reads the snapshot that
`0.1.8` already produces.

### `mix_headroom` (2026-11-10)

Snapshot-only fader report: Live's own dB display per track, counts above/at/below unity, silent,
muted and soloed, and an explicit refusal to turn fader trim into a headroom number. `headroom`
carries `measured: false` with the reason and `mix_meter_poll` as the missing capability; the master
fader is reported unavailable because the snapshot carries only the master device chain.

**Verified on `paper tiger heart update og*`:** 54 tracks, 54 faders measured, span 0.0 to -16.0 dB,
no faders above unity, 14 muted, 1 soloed, no silent tracks. Suite **131 passed**. No Remote Script
change, no restart.

### `mix_meter_poll` (2026-11-11, `0.4.14`)

**Verified on real `0.4.14` against `SCRATCH fortnight`.** The Remote Script samples
`output_meter_level` and the instantaneous left/right meters on later display ticks through
`Deferred`, so the main thread never blocks. `doctor` reported script `0.4.14`, build
`2d3a0a801a4d`, no `stale`, `errors 0`. A stopped poll (`ms: 200`) returned 35 rows (32 tracks,
2 returns, master `Main`), all `available`, with honest zeros and an explicit not-playing note. A
poll during playback from bar 9 (`ms: 600`) returned 7 samples over 625 ms: master peak `0.897554`
(0.94 dB headroom), loudest track `REVocals` `0.966257`, 9 rows carrying signal. The transport was
stopped and the playhead restored to 372.0. Offline suite **457 passed, 42 subtests**.
`mix_headroom` still reports headroom as unmeasured; wiring measured peaks into it is a separate
slice.

### Current-file acceptance read — `fortnight` (2026-11-10, `0.1.8`)

The current Set is `fortnight*` (unsaved). Four reports — `inspect_structure`, `inspect_unused`,
`mix_headroom`, `clips_warp_check` — shared one `SnapshotCache`; `cache.trace` held exactly **one**
`snapshot.get` (375 ms, 250 clips, 32 tracks). The ≤ 1 read target therefore held across all four
questions, not just one tool.

**Verified data:** 32 tracks plus 2 returns, 137 arrangement and 113 Session clips, 250 clips total;
58 audio clips with 487 warp markers, modes `beats` 56 / `complex` 1 / `complex_pro` 1, warping off
43 and on 15, no flags; 34 faders spanning +4.0 to -16.8 dB, 20 muted, 0 soloed; 114 devices.

**File reconciliation:** `Fortnight\fortnight Project\fortnight.als` parses as 301 clips, 108 audio
and 587 markers, but 50 audio clips are `FreezeSequencer` renders on two frozen MIDI tracks (100
markers), and one `MidiClip` sits under a Groove. Excluding those gives **250 clips / 58 audio / 487
markers**, exactly matching Live, with modes 56 / 1 / 1. This is a file-scan trap, not a snapshot
defect: future `.als` comparisons must exclude `FreezeSequencer` audio clips and Groove MIDI clips.

**User-approved M1 acceptance fixture (2026-11-10):** because the 77-track remaster has never
loaded, `fortnight` replaces it as the second fixture. `tests/test_acceptance_read_path.py` replays
the captured snapshot through four reports and asserts exactly one `snapshot.get`. The remaster
remains unread and no longer blocks the fixture gate.

### `notes_overlaps` (2026-11-10, `0.2.0`)

Snapshot-backed same-pitch collision report. The Remote Script reads each MIDI clip's notes once
and stores only bounded collision pairs (`MAX_NOTE_OVERLAPS_TOTAL = 2000`), plus the note count,
truncation flag and the source that answered. The report pages pairs, marks itself incomplete when
capture was truncated or a note vector could not be read, and returns `unavailable` carrying the
snapshot's own reason.

**Verified on the real Set (`0.1.9`, restarted Live):** `enableton status` returned `Crust Wumble`,
120 BPM, 8 scenes, 17 tracks + 2 returns, 315 arrangement and 22 Session clips, 18 top-level / 108
total devices in **363 ms**. A keyed comparison against `in hell Project\Crust Wumble.als` (clips
keyed by track and arrangement start, never by name) matched tempo, tracks, returns, scenes,
locators, 108 devices total, per-track device counts on **19 of 19** rows, per-track arrangement and
Session counts, and 894 warp markers with **no per-clip disagreement**.

**Defect found by that read, fixed in `0.2.0`:** notes were read with
`getattr(clip, "notes", [])`. Live 12.2.5 reads notes through `get_all_notes_extended()`; the legacy
attribute did not answer, and the `getattr` default turned "cannot read" into "this clip is empty".
Two clips holding 412 and 799 `<MidiNoteEvent>` elements (parsed straight out of the `.als`, both
main-lane arrangement MIDI clips) reported `note_count: 0` beside `notes_available: true`. `0.2.0`
reads `get_all_notes_extended()` first, falls back to the legacy vector, records `notes_source` per
clip plus `counts.notes_sources` and `captured.notes_reason`, and reports an unreadable clip as
`note_count: null` with its reason — never zero.

**Tested:** **146 passed**, 7 subtests, three of them new (extended API preferred and named; legacy
vector still accepted; clip with no note API unavailable rather than empty). `setup --force`
installed `0.2.0`: repo and install digests both `de1dad141c14`, 9 stale `__pycache__` files removed.

**Live gate passed for `0.2.0` (2026-11-10, restarted Live).** `doctor` reported script `0.2.0`,
`build de1dad141c14` with no `stale`, and `status` confirmed `fortnight` (32 tracks, 137 Arrangement
and 113 Session clips). `notes_overlaps` read **3,364 notes across 192 MIDI clips** and found **16
same-pitch overlaps in 14 clips**; `complete: true`, 0 truncated and 0 unreadable. That is the
real-Live acceptance call. The earlier Crust Wumble 412/799-note clips were not separately re-read
after this restart. All 16 collisions are 0.0001 beat: the tool currently counts any positive
intersection, so these are boundary-level rather than necessarily audible overlaps.

### M2 write safety foundation (2026-11-10, `0.2.1`)

The first M2 slice is implemented. `src/enableton/plans/executor.py` preflights every step with
`dry_run`, compares the applied trace to that preflight, makes a timestamped copy of the Set before
the first applied call, and reverses tool-owned undo tokens when a step fails. `tracks_gain_stage`
now returns the track index and exact undo values, and accepts the executor's `restore` token.
`run_tool` routes an applied gain stage through the executor instead of calling the handler directly.

**Tested at that milestone:** **160 passed**, 7 subtests; the current suite is **216 passed**.
New safety tests cover dry-run trace equality, scratch-copy
bytes and pre-write timing, refusal when the Set has no path, exact rollback after a synthetic
second-step failure, and double-apply on one executor. `clips_duplicate_range` has handler tests for
the half-open bar window, predicted destinations, applied changes, exact clip-list restoration,
transactional rollback, double-apply, and an unavailable duplicate primitive reporting a reason.

**Real scratch-Set write verified (2026-11-10, `0.2.1`, restarted Live):** `doctor` reported script
`0.2.1`, `build d70bd71e8360` with no `stale`. On `SCRATCH fortnight`, `run_tool` applied the
`tracks_gain_stage` restore path to REVocals: 0.85 -> 0.5, creating a timestamped
`%APPDATA%\Enableton\backups` copy first, then restoring 0.85 exactly. Two applied calls produced
two copies. This verifies the scratch-copy and exact-restore path on real Live. The forced mid-plan
failure is still covered by the fake executor test, not real Live.

### `clips_duplicate_range` real gate (2026-11-10, `0.2.3`)

**First real verification on `0.2.2`:** `doctor` reported script `0.2.2`, build `4e23159ea418`, Live 12.2.5, no `stale`. The loaded Set was
`SCRATCH fortnight.als` (32 tracks, 137 arrangement clips), not the user's working `fortnight` Set.

On `DRUMS | Remix 808 kit`, bars 17-18 contain one clip, `RMX | drums | 1`, at beat 64.0. A dry run
predicted exactly one copy at beat 372.0. The transactional apply made a timestamped
`%APPDATA%\Enableton\backups` copy first, created the clip, and its applied trace matched the
dry-run trace. A second `apply` on the same executor returned `already_applied: true` and left the
arrangement unchanged. The tool's undo token deleted the created clip; the before/after comparison
of every arrangement clip was exact.

A second real plan applied one duplicate and then raised a forced `RuntimeError` on its second step.
`PlanExecutor` restored through the first step's undo token, reported `restore.ok: true`, and the
arrangement matched the pre-plan object list exactly. This is the forced mid-plan failure gate, run
against real Live rather than the fake.

**Defect found by the real call:** the restore response read the clip's name after `delete_clip`,
so `changes[0].clip` came back as `""` even though deletion succeeded. `0.2.3` captures the name
before deleting; the fake now blanks a deleted clip's name so the test can catch this.

**Verified on `0.2.3` (2026-11-10, restarted Live):** `doctor` reported script `0.2.3`, build
`3a5bf26b368b`, Live 12.2.5, no `stale`. The same real duplicate/apply/undo sequence returned
`changes[0].clip: "RMX | drums | 1"` on restore, double-apply remained `already_applied: true`, and
the full arrangement diff was exact. A repeated two-step forced failure on `0.2.3` restored through
the undo token with `restore.ok: true` and an exact object diff.

M2's acceptance gates are met on the loaded build. The current `fortnight` Set must not be used for
writes; the test ran on `SCRATCH fortnight.als`.

### M3 diagnostics, apply and rollback (2026-11-10, `0.2.4`)

**Verified** on `SCRATCH fortnight.als`, confirmed by its path before any write. `doctor` reported
script `0.2.4`, build `c9e993ad42da`, Live 12.2.5, connected, no `stale`. `inspect_run` returned 25
findings: 3 `auto`, 22 `inspect`, 14 `needs_listening`, 9 `info`, 16 `warn`, 0 `error`, with note
data available. The findings were 14 MIDI same-pitch overlaps, 6 empty tracks, 2 duplicate track
names and 3 faders above unity. `inspect_plan` produced exactly 3 gain steps, kept the 14
needs-listening findings out of the steps, and returned the 8 unimplemented hygiene fixes as
`unavailable` with their tool names. Dry-run autofix reported the same 25/25 counts and wrote
nothing.

`inspect_autofix` with `dry_run: false` then applied exactly those three `tracks_set_volume` steps
on the three above-unity faders. It returned `applied: true`, `counts_before.total: 25`,
`counts_after.total: 22`, `by_mode.auto: 0`, `by_mode.inspect: 22`, 14 needs-listening findings and
no error, after creating a timestamped `%APPDATA%\Enableton\backups` scratch copy. A direct
snapshot read confirmed all three faders were at `0.85`. The post-apply report still held the same
14 needs-listening findings; none entered the plan or the apply.

**Controlled real-Live halt-and-rollback:** using a test-only detector keyed to a real fader value,
autofix wrote the probe track from `0.85` to `0.5`; the detector then added a finding, raising
the count from 1 to 2. Autofix returned `stopped: finding_count_rose`, `rolled_back: true`,
`counts_after_change.total: 2`, `counts_after.total: 1`, and `restore.ok: true`; the direct read
showed the fader back at `0.85`. The standard report remained at 22 findings. This is a controlled
probe of the guard, not a production finding.

The 25-finding real `inspect_run` exposed a bug the fake suite had not covered: it paged `Finding`
dataclasses rather than dictionaries, so JSON serialization failed. `run()` now converts at the
output boundary, and the test asserts `json.dumps` on the result.

M3's **autofix acceptance** is met: per-mode counts tracked the findings before and after, a real
count rise halted and rolled back, and `needs_listening` never auto-applied. The write was on the
scratch Set, not the working `fortnight` Set.

**Escalation and stored-plan apply (Verified):** after temporarily raising one muted scratch track
to `1.0`, `modes --findings` showed `auto: 1`, `inspect: 22` (23 total). `ableton_escalate` with
intent `gain` produced plan `p_385f5f76`, one `tracks_set_volume` step, `reversible: true`, no
needs-listening findings and a 10-minute expiry. A separate `enableton call ableton_plan_apply`
process loaded that plan from `%APPDATA%\Enableton\plans`, applied it transactionally, reported
`applied: true`, `counts_before.total: 23`, `counts_after.total: 22`, `by_mode.auto: 0`, and
`discarded: true`; the direct fader read was `0.85`. `modes --findings` then showed `auto: 0`,
`inspect: 22` (22 total). `ableton_plan_discard` and the expiry path are covered by
`tests/test_plans.py`; no real discard was run. M3 is complete.

| Area | On disk |
|---|---|
| server | `src/enableton/`: `cli.py`, `manifest.py`, `modes.json`, `modes.py`, `reports.py`, `setup.py`, `tools.json`, `tools.py`, plus `live/`, `protocol/`, `state/` packages |
| remote script | `remote_script/Enableton/`: `dispatch.py`, `errors.py`, `framing.py`, `server.py`, `handlers/` |
| tests | `tests/` incl. `test_acceptance_read_path.py`, `test_bridge.py`, `test_build_digest.py`, `test_drift.py`, `test_framing.py`, `test_manifest.py`, `test_modes.py`, `test_snapshot.py`, `test_adapter_conformance.py`, `test_cli.py`, `test_setup.py` |

M0's acceptance test is green. M1's read path is closed on real evidence: all six reports are
implemented, `Crust Wumble` and `fortnight` have been read, and the one-read acceptance test is
green. M2 and M3 are complete on real evidence. **Mission 4 (full catalogue + modes) is in progress.**

---

## 3. Mission sequence

One milestone per mission; a mission ends when its acceptance test passes as a **measurement**.

| # | Spec | Scope | Done-when (from `SPEC.md` §19) |
|---|---|---|---|
| **1** | M0 | gap audit, then close M0 | `pytest` green ✔; `enableton doctor` against the fake reports connected; drift test green; `ableton_status` returns a real summary from the fake; a written gap report names each uncovered M0/M1 item |
| 2 | M1 | read path | against `Crust Wumble.als` (19 tracks, 120 BPM, 22 Session clips) **and** `fortnight.als` (32 tracks, 250 clips; user-approved replacement for the unread 77-track remaster): three questions answered from the data, the trace shows **snapshot reads ≤ 1 per request**, and `tests/test_acceptance_read_path.py` replays the captured second snapshot for four answers at one read. `notes_overlaps` is implemented in `0.2.0`, which reads the extended note API after `0.1.9` read an absent legacy attribute and reported zero; its live gate passed on `fortnight` (3,364 notes, 16 overlaps). |
| 3 | M2 | write path + safety | dry-run trace matches applied trace; a forced mid-plan failure restores state exactly (object-by-object diff); double-apply is a no-op; a scratch copy exists before any write. M2 acceptance gates passed on real `0.2.3`: dry-run trace matched apply, double-apply was a no-op, a scratch copy preceded every write, exact restore (including the restored clip name) passed, and a forced real mid-plan failure restored the arrangement object-for-object. |
| 4 | M3 | diagnostics | per-mode finding counts equal before/after; autofix halts when the count rises; `needs_listening` never auto-applies. Passed on real `0.2.4`: 25 → 22 after autofix, a controlled 1 → 2 rise halted and rolled back, 14 needs-listening findings stayed out, and an escalated stored plan applied from a separate CLI process with modes counts 23 → 22. |
| 5 | M4 | full catalogue + modes | drift test green; every mode ≤ 34 tools; every tool in ≥ 1 mode; escalation reaches every tool |
| 6 | M5 | UX | every screen renders as text with working `ableton_choose` ids; scope chip matches the loaded tool set; a full flow completes with Apps disabled |
| 7 | M6 | audio tiers | capture produces a WAV, analysis reads it, routing verification catches a failed arm |
| 8 | M7 | library, build, recipes | the user's own sentence — "create a dubstep drum beat using loops from my riddim one shots folder" — builds a playable 2-bar pattern whose every sample came from that folder; `recipe_learn` recovers tempo and half-time feel with per-lane confidence and refuses below 0.6 |

**Verified offline foundation (synthetic unit tests only; does not satisfy M6 or M7 acceptance):**
the PCM WAV analyzer measures file-level sample peak, RMS, duration, and DC offset; the recipe
pattern/validator utilities parse 16-step bars, enforce the version-1 shape, and reject duplicate
lane/slot IDs; `RecipeStore` lists, shows, saves, and deletes validated recipes with shipped/user
precedence. None uses Live or claims actual capture, spectral/LUFS analysis, meter polling, routing
verification, audition, or recipe building.

**Resample-capture preconditions (Verified 2026-11-11, `0.4.14`, read-only).** On `SCRATCH
fortnight`, `tracks_set_routing` dry-runs resolved `Resampling` at input index 0 on `REVocals`
(index 0) and on the empty audio track `Unused` (index 26), currently `Ext. In`; nothing was
written. The Set's `Samples/Recorded` folder exists (34 WAVs). `Song.record_mode`, the post-arm
routing readback and the recorded clip's `file_path` remain untested; no capture has been run.

**Unverified; later scratch-Set gates required:** real resample capture and WAV readback, failed-arm
detection, Live meter/LOM behavior, spectral and loudness reports, device audition, generation
preview/accept/discard, and Browser-backed recipe learning/building.

Missions 2 and 3 are complete. Mission 4 is in progress; everything after is catalogue breadth on a
proven frame. **Do not start Mission 5 before Mission 4 is green.**

---

## 4. Decisions locked for this build

- **Python 3.11 + uv**, `mcp>=2.3`, pytest as the only dev dependency. The Remote Script is
  **stdlib-only** on Live's embedded CPython.
- **Feature detection, never version branches.** No `if live_version == "12.2.5"` anywhere; the
  script reports `features[]`, tools declare `needs`/`min_live`, absent means `unavailable` + reason.
- **One socket, one in-flight request, one scheduler.** `LIVE_BUSY` rather than queuing.
- **All LOM access on Live's main thread**, marshalled through a thread-safe queue drained in
  `update_display()` — *not* `schedule_message`, whose dropped-task failure mode surfaces as a
  timeout.
- **Reversibility over confirmation.** Snapshot before bulk/plan writes; `%APPDATA%\Enableton` holds
  config, logs and backups; **a user `.als` is never written in place**.
- **Remote Script discovery is explicit**: `ENABLETON_USER_LIBRARY`, then `Documents`, then a
  shallow OneDrive search — the default path is a silent no-op on this machine.
- **No LLM inside the server.** The LLM is the MCP client; the server exposes vocabulary.

---

## 5. Risks added for this environment

| Risk | Mitigation | Trigger |
|---|---|---|
| Two authoritative docs drift apart | `SPEC.md` wins; this file is sequencing only, never design | a conflict appears in a diff |
| `Backup\` Sets triple every count | exclude `/Backup/` in scans and fixtures; assert it in a test | a Set count or fixture list looks 3× too big |
| `F:` is removable or unmounted | preflight names the missing root; never crash; never write to `F:` except an explicit staging dir | a read or rollback test fails with a drive error |
| `dev` extra isn't synced, so tests "don't exist" | `uv sync --extra dev` is part of the check command | `pytest: program not found` |
| A path in a doc holds a control byte (a real `\a` became `0x07` in `SPEC.md`) | validate path strings on load; fixed today | a path that exists won't open |
| Already-landed work gets rewritten by a fresh mission | gap audit first, one milestone per mission | a mission deletes or restructures green code |
| Live's linear undo can't unwind a plan | our own snapshot transaction + `ableton_undo` | a partial plan leaves the Set changed |

`SPEC.md` §21 remains the full register; the rows above are the ones this machine adds.

---

## 6. Open decisions

| Decision | Default | Needs the user |
|---|---|---|
| Upgrade Live to 12.4.5+ | **stay on 12.2.5**, gate those capabilities `unavailable` | only if warp-marker writes / envelopes / `insert_device` are wanted soon |
| Scratch copy location for M2 | `%APPDATA%\Enableton\backups\` — nothing on `F:` | confirm, if they'd rather it sat beside the song |
| MCP App auto-opens on `ableton_start` | automatic on first run, then remembered | no |
| Meter poll interval | 100 ms, capped at 5 s total | no |
| Starter recipe pack | small shipped set, overridable by id | no |

---

## 7. What M4 needs

M3 is closed on real evidence: `inspect_run` found 25 issues, the three-fader autofix dropped that
to 22, a controlled real count rise halted and rolled back, and needs-listening findings never
entered a step. Escalation now produces a stored, expiring plan that a separate CLI process can
apply transactionally, and `modes --findings` reports the per-mode counts. M4 is in progress: the
normal MCP `ableton_guide` tool now returns the same generated command sheet as `enableton guide`,
and `enableton inspect`, `enableton plan` and `enableton run` are implemented. The local read path
also has `devices_read_chain`, `master_chain_read` and `sections_map`; a real read of `REVocals`
returned 2 devices (2 nested), the master chain returned 9 devices, and the arrangement map returned
one derived section with one named locator, all from one shared snapshot. M4 still audits the full
catalogue: the drift test must stay green, every mode must stay at or below 34 tools, every tool
must appear in at least one mode, and every mode's escalation path must reach every tool. This is
catalogue and mode coverage, not new Live semantics; keep the M3 evidence intact while expanding
the surface. The catalogue is now 39 tools across 3 modes, so M4 is not complete. The ten-tool tracks domain now has five implemented — `tracks_gain_stage`, `tracks_set_volume`, `tracks_set_pan`, `tracks_set_sends` and `tracks_name_and_color` — plus the extra `tracks_list` read tool; the two new writes are **Verified on real `0.2.12`** (see §2). The notes domain is complete in code: `notes_read` is **Verified on real `0.2.8`** (`doctor`: script `0.2.8`, build `ad895342f68e`, no `stale`): `FORTNIGHT | drums | Drop 5.2` on `DRUMS | Remix 808 kit` (session slot 9) returned 46 notes matching the snapshot's `note_count`, source `extended`, pitches 36–42; a 10-note page plus a 40-offset page reassembled to the same 46-note vector, and a real audio clip returned `notes_available: false` with `clip is not a MIDI clip`. All 24 gate checks passed. The six writes share one exact-vector undo and 12 focused tests. Their real gate is **Verified on `0.2.10`** (`doctor`: script `0.2.10`, build `7dd268762eab`, no `stale`, `errors 0`): each of quantize, transform, humanize, strum, replace and scale-lock changed `FORTNIGHT | drums | Drop 5.2` from the same 46-note baseline and restored the exact pre-write vector, 55/55 checks, with seeded humanize reproducing identically. The first `0.2.9` gate exposed a real defect: Live's `Clip.set_notes` **adds** rather than replaces, so the scratch clip grew 46 → 334; `0.2.10` clears with `remove_notes_extended` before adding, and the fake now mirrors the append. The scratch clip was recovered from its on-disk 46-note vector; no user Set was written. The new `edit` mode covers notes, clip edits and finding lookup. The inspect domain is complete: `inspect_export` writes an atomic, versioned JSON audit, and a real Live export produced a 3,043-byte document with four findings and matching counts. `tracks_set_pan` and `clips_rename` add dry-run and exact-restore writes with dedicated tests. Their real gate is **Verified on `0.2.7`** (`doctor`: script `0.2.7`, build `046387053c7b`, no `stale`): on `MUSIC | vOCALS`, pan `0.0 → 0.2` and the unique arrangement clip `EXTENDED VERSE | bar 8 → GATE 0.2.7 VERSE` were applied, confirmed by a fresh snapshot, restored through the returned undo tokens, and confirmed again with the clip count and start intact. An earlier gate attempt left `REVocals` pan at `0.25`; it was restored to `0.0`, the value recorded in all seven Live automatic backups and in both on-disk Sets. The gate script reported 24/25 checks only because one assertion compared the snapshot's rounded `start` to the handler's exact float; the restore used the exact value.

The transport domain is complete in code: `transport_stop`, `transport_locate` and
`transport_set_loop` join the existing `transport_play`, with closed arguments and eight focused
tests. **Verified on real `0.2.6`:** `doctor` reported script `0.2.6`, build `d9d5fefaad68`, no
`stale`; play/stop, locate, loop set/clear and restoration passed all 12 state checks.
`transport_locate` returned the target 36 beats for bar 10 and the following snapshot confirmed it.
The original loop (start 8.0, length 16.0, disabled) and playhead (0.0) were restored. The earlier
`0.2.5` probe found Live's one-tick readback lag; `0.2.6` fixes it and has a regression test for it.
