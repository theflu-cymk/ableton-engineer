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
| M1 stress fixture | `F:\ableton songs\beat Project\paper tiger heart remaster.als` | located |
| ABL user library at `Documents\Ableton` | absent — library is redirected (see `SPEC.md` §2) | directory listing |
| Existing Remote Scripts | none — the installer is part of the deliverable | directory listing |

Reconciled: `SPEC.md` says "66 `.als` files"; a naive scan says 192. Both are right — 66 are working
Sets, 126 live in `Backup\` directories. **Any scan or fixture walk must exclude `/Backup/`**, and a
test should assert that, or every count in the spec is wrong by 3×.

---

## 2. State of the build (measured, not claimed)

`uv run pytest -q` → **98 passed**. Committed through `e5a12db`.

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

| Area | On disk |
|---|---|
| server | `src/enableton/`: `cli.py`, `manifest.py`, `modes.json`, `modes.py`, `reports.py`, `setup.py`, `tools.json`, `tools.py`, plus `live/`, `protocol/`, `state/` packages |
| remote script | `remote_script/Enableton/`: `dispatch.py`, `errors.py`, `framing.py`, `server.py`, `handlers/` |
| tests | `tests/` incl. `test_bridge.py`, `test_build_digest.py`, `test_drift.py`, `test_framing.py`, `test_manifest.py`, `test_modes.py`, `test_snapshot.py`, `test_adapter_conformance.py`, `test_cli.py`, `test_setup.py` |

M0's acceptance test is green. M1 (snapshot, reports) is partly built. **Mission 1 therefore starts
with a gap audit against `SPEC.md` §19**, not with a rewrite — writing code over already-landed work
is the expensive failure mode here.

---

## 3. Mission sequence

One milestone per mission; a mission ends when its acceptance test passes as a **measurement**.

| # | Spec | Scope | Done-when (from `SPEC.md` §19) |
|---|---|---|---|
| **1** | M0 | gap audit, then close M0 | `pytest` green ✔; `enableton doctor` against the fake reports connected; drift test green; `ableton_status` returns a real summary from the fake; a written gap report names each uncovered M0/M1 item |
| 2 | M1 | read path | against `Crust Wumble.als` (19 tracks, 120 BPM, 22 Session clips) **and** `paper tiger heart remaster.als` (77 tracks, 1825 warp markers): three questions answered from the data, and the trace shows **snapshot reads ≤ 1 per request** |
| 3 | M2 | write path + safety | dry-run trace matches applied trace; a forced mid-plan failure restores state exactly (object-by-object diff); double-apply is a no-op; a scratch copy exists before any write |
| 4 | M3 | diagnostics | per-mode finding counts equal before/after; autofix halts when the count rises; `needs_listening` never auto-applies |
| 5 | M4 | full catalogue + modes | drift test green; every mode ≤ 34 tools; every tool in ≥ 1 mode; escalation reaches every tool |
| 6 | M5 | UX | every screen renders as text with working `ableton_choose` ids; scope chip matches the loaded tool set; a full flow completes with Apps disabled |
| 7 | M6 | audio tiers | capture produces a WAV, analysis reads it, routing verification catches a failed arm |
| 8 | M7 | library, build, recipes | the user's own sentence — "create a dubstep drum beat using loops from my riddim one shots folder" — builds a playable 2-bar pattern whose every sample came from that folder; `recipe_learn` recovers tempo and half-time feel with per-lane confidence and refuses below 0.6 |

Missions 2 and 3 are the ones that prove the whole architecture; everything after is catalogue
breadth on a proven frame. **Do not start Mission 5 before 2–3 are green.**

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

## 7. What Mission 1 needs

Nothing blocking. It audits the existing code against `SPEC.md` §19, closes M0, and stops before
touching M1 behaviour. For Mission 3 it will need the scratch copy of `Crust Wumble.als` — read-only
until then.
