# The Enableton panel

The panel is a local web window over the same bridge and tool catalogue the MCP server and CLI use.
It is for the common producer actions: seeing whether Live is connected, reading the current Set,
changing a track safely, and making the first A/B takes. It is not a second audio engine and it
does not open a second socket protocol.

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

The header is the first diagnostic. It shows:

- the connection dot and a plain-language state;
- the Live version, installed Remote Script version and loaded build digest;
- the bridge queue depth;
- a **Reconnect** button.

A `stale` build means Live is running a different script build from this checkout. Run
`uv run enableton setup --force` and restart Live, then check the header again. The same check is
available as JSON from `uv run enableton doctor --json`.

### Session

This is `session_brief`: the Set title, section map, role balance, structural issues and the next
three suggested producer moves. It is read-only. Roles are inferred from track names, not from
audio, so treat the card as a map rather than a verdict.

### Tracks

One row per track with name, type, device names, volume, mute, solo and arm state. Mute and solo
are buttons; arm is shown read-only.

The row action menu offers only the safe v1 edits:

- rename or recolour;
- set volume;
- duplicate the track;
- create A/B takes.

Destructive operations such as delete and clean-empty are deliberately absent from the panel.
They remain available through the CLI and MCP surfaces, which have their own confirmation rules.

Mute and solo use the existing `mix_snapshot_restore` tool with a single-field restore entry. That
means the panel gets the tool's existing dry run, undo token and safety checks; it does not invent
a hidden direct write.

### Action composer

The composer calls one named tool with typed arguments. `Preview change` is always a dry run. The
panel then shows the changed fields and the complete raw result, with **Apply change** and
**Cancel** buttons. Nothing is written until Apply is clicked.

The panel keeps the preview token in its own memory, binds it to the exact tool and arguments, and
consumes it on one Apply. It expires after ten minutes. A read-only tool never receives an apply
token. A write the catalogue marks as irreversible can be previewed but cannot be applied from
the panel; use the CLI or MCP tool with its own confirmation.

### Take groups

The panel finds tracks named `<track> take N` and shows which take is audible from its fader.
Each take has a **Select** control: it previews `takes_select` with the whole group and the chosen
take as active, then the normal Apply button writes the fader change. The response includes the
fader undo values; there is no one-click undo button. Each take also has **Preview discard**, which
calls `takes_discard` with `dry_run: true`; that reversible-looking preview is deliberately not
applicable from the panel because deletion is irreversible. Create takes from the tracks row menu
or the composer.

## Why writes are safe

Every panel write goes through the same path as the CLI and MCP server:

1. `POST /api/plan` forces `dry_run: true` and returns the planned changes.
2. Apply replays exactly those arguments with `dry_run: false`.
3. For catalogue writes, the existing executor takes a scratch copy of the Set, records the
   undo token and rolls back if the tool refuses or the applied trace differs from the dry run.
   `takes_create` is special-cased by the existing tool layer and performs its own duplicate and
   volume rollback; it still has to pass the panel's preview first.
4. The panel surfaces the undo token in the preview result after Apply.

The panel never writes `.als` files in place. If the Set has never been saved, a preview can still
run, but Apply refuses because there is no file to copy first. Save the Set, then preview again.

## Failure modes seen in practice

### 1. Live is closed or the Control Surface is not selected

The page still loads. The health strip turns red and the banner says `Live is not connected` with
the same hints `doctor` gives. In Live, choose **Enableton** in
**Preferences > Link, Tempo & MIDI**, then press **Reconnect**. The terminal that started the
panel has the exact error and the request path for a support report.

### 2. The loaded script is stale

The header shows a build digest, and marks it stale when it differs from this checkout. The fix is:

```bash
uv run enableton setup --force
```

Then restart Live. Live scans Remote Scripts only at startup. The panel will keep polling and will
show the new build after the restart; no panel restart is required.

### 3. A poll times out or the Set is reopened in Live

The panel uses plain polling, not websockets. If a poll fails, the UI resets to a clear
disconnected state and retries every two seconds. Reopening a Set in Live is therefore a normal
recovery: wait for the next successful status poll, or press **Reconnect**. A preview token is
single-use; if state changed, preview the edit again rather than trying to reuse an old Apply.

The same reset happens if the bridge is busy or a command exceeds its timeout. The panel does not
retry a write automatically: an interrupted Apply is never repeated silently.

## Verification

The panel tests use a fake bridge and do not need Live:

```bash
uv run pytest -q tests/test_panel.py
```

They cover the healthy status payload, the session/tracks/takes endpoints, static assets, a
plan-to-apply flow, a rejected write, single-use tokens, the bridge-unreachable 503 and the
loopback bind. Live verification is still a separate gate: a green fake suite is not proof that a
particular Live Set behaves correctly.

## Live acceptance record

**[Verified] 2026-11-13 — scratch Set only.**

- Live: `12.2.5`; Remote Script `0.4.26`; build `a7fcd016f88d`; `doctor` connected, `errors 0`.
- Scratch file: `tmp/panel-scratch/SCRATCH fortnight - panel acceptance.als`, copied from the
  existing `SCRATCH fortnight.als`; the working Set was not opened or written.
- `POST /api/plan` previewed a mute change on track index 1 (`False` to `True`), returned
  `dry_run: true`, and issued a token.
- `POST /api/apply` applied it; `/api/tracks` read back `mute: true`, and the response contained the
  exact undo token (`field: mute`, `value: false`).
- A second preview/apply restored the mute to `False` and read it back.
- The SHA-256 of the scratch `.als` was identical before and after; Live did not save the file.

**[Verified] 2026-11-13 — real take apply, A/B switch and undo.**

- The same scratch Set and build were used. The source was `snare rush` (index 9, audio, one
  arrangement clip, volume `0.85`).
- `POST /api/plan` for `takes_create` with `track_index: 9` and `count: 2` planned indices 10 and
  11, returned `dry_run: true`, and issued a token.
- `POST /api/apply` created `snare rush panel take 1` (index 10, volume `0.85`, active) and
  `snare rush panel take 2` (index 11, volume `0.0`), with the source at volume `0.0`.
- A/B was exercised with `tracks_set_volume`: take 1 to `0.0`, then take 2 to `0.85`. A fresh
  panel readback after its snapshot cache aged confirmed the switch.
- Undo used the returned `tracks_duplicate` restore entries to remove indices 10 and 11, then
  `tracks_set_volume` restored the source to `0.85`. Readback showed 32 main tracks plus 2 returns,
  the take list empty, and the source restored.
- The scratch `.als` SHA-256 stayed
  `da3c7a31a14c6d63bd32ee203015ed4bf3e4bfb1875483f374e9d609bb5d382f`.

The take copies were identical at creation; this proves duplication, fader A/B and undo, not a
musical variation. The panel now has a Select control and a discard-preview control, but no
Apply-to-undo button.

**[Verified] 2026-11-13 — real select and discard gate.**

- The panel planned and applied `takes_select` for `snare rush gate take 1` and
  `snare rush gate take 2` with `active: 2`; readback showed take 2 at `0.85` and take 1 at `0.0`.
- The returned fader undo restored take 1 to `0.85` and take 2 to `0.0` through the CLI.
- The panel previewed `takes_discard` for both takes with `can_apply: false` and no token; the CLI
  applied it only with `confirm: true`. Readback showed 32 main tracks plus 2 returns, both take
  tracks gone, and the source restored to `0.85`.
- The scratch `.als` SHA-256 remained
  `da3c7a31a14c6d63bd32ee203015ed4bf3e4bfb1875483f374e9d609bb5d382f`.
- The open scratch Set accepted an unfreeze-tracks prompt in memory; the on-disk file was not saved.

**[Verified] 2026-11-13 — panel select and discard-preview controls.**

- A two-take group was created through the panel API, then rendered as a take group in the page.
- Clicking **Select** on take 2 opened a dry-run preview listing take 1 `0.85 → 0.0` and take 2
  `0 → 0.85`, with an Apply button. Clicking Apply wrote both faders; Live read back take 1 `0.0`,
  take 2 `0.85`, and the page re-rendered take 2 as audible.
- Clicking **Preview discard** on take 1 showed `reversible: false`, `undo: []` and the irreversible
  deletion note; the Apply button was hidden. No track was deleted by the panel.
- The test takes were restored and removed through the CLI; the scratch Set returned to 32 main
  tracks and 2 returns with `snare rush` at `0.85`. The `.als` SHA-256 stayed unchanged.

**[Unverified]** Audible verification and a manual click-through of every unrelated row action. A
write made outside the panel can leave `/api/tracks` and `/api/takes` stale until the snapshot cache
ages (up to 30 seconds); `/api/session` reads fresh.
