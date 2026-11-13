# Current state

**Snapshot:** 2026-11-13. This describes the working tree, not a released artifact.
**Evidence:** [Verified] = checked in this tree or through Live; [Assumed] = planning assumption;
[Unverified] = not exercised on the required surface.

## At a glance

| Area | Current state | Evidence |
|---|---|---|
| Package | `Enableton 0.1.0`, Python `>=3.11`; local runtime 3.11.17 via `uv` | [Verified] `pyproject.toml`, `uv run python -V` |
| Git | branch `main`, panel baseline `a473577`; select/discard slice in this pass | [Verified] `git status`, `git log` |
| Live | 12.2.5; connected; Remote Script `0.4.26`; build `a7fcd016f88d`; `errors 0`; not stale | [Verified] `uv run enableton doctor` after restart, 2026-11-13 |
| Open Set | scratch `SCRATCH fortnight - panel acceptance`, 120 BPM, 32 main tracks + 2 returns; no take tracks | [Verified] `enableton status`, 2026-11-13 |
| Catalogue | 89 tools; 9 modes; `produce` has 21 resolved tools | [Verified] `tools.json`, `modes.json`, `enableton modes` |
| Producer tools | `session_brief`, `reference_analyze`, `takes_create`, `takes_select`, `takes_discard` | [Verified] manifest and source |
| Producer evidence | brief, WAV reference, take create/apply, panel select/undo and discard; real scratch-Set gate | [Verified] real calls on 2026-11-12 and 2026-11-13 |
| Writes | Mute, two takes and select were applied/undone; discard removed both takes after confirm; no `.als` saved or changed | [Verified] panel/CLI apply, undo, discard and SHA-256 check, 2026-11-13 |
| Tests | full fake suite green after this slice; not a substitute for Live | [Verified] `pytest -q` |
| UI / memory | Local web panel implemented; no persistent producer memory | [Verified] source, live panel, and tests |

## Architecture as implemented

```text
MCP host or CLI
      |
      | MCP over stdio, or `enableton call`
      v
src/enableton/
  mcp/transport.py      MCPServer, mode-scoped tools, session controls
  panel.py              loopback HTTP panel, preview/apply tokens
  panel_assets/         HTML, CSS and browser JavaScript
  tools.py              manifest dispatch + local producer tools
  live/adapter.py       adapter seam
  protocol/client.py    one TCP connection, one in-flight request
      |
      | 4-byte big-endian length + UTF-8 JSON, port 9878
      v
remote_script/Enableton/
  server.py             Control Surface, socket thread, main-thread queue
  dispatch.py           command table
  handlers/*.py         LOM reads/writes
      |
      v
Ableton Live 12.2.5 / LOM
```

**[Verified]** The package does not contain a `src/enableton/server.py` entrypoint; the MCP server is
implemented in `src/enableton/mcp/transport.py`. Old SPEC/MISSION diagrams that show `server.py`
are design-era names, not the current file map.

### Important implementation facts

- **[Verified]** `enableton serve` is implemented, not a stub. The current AGENTS bullet that says it
  is a stub until M5 is stale for this working tree. `enableton serve --mode list` works.
- **[Verified]** `session_brief` is local and snapshot-backed; it excludes return tracks from the
  working-track count and roles.
- **[Verified]** `reference_analyze` is file-only and can run without a Live connection. Basic WAV
  measurement uses the standard library; advanced LUFS/spectral/stereo values require the analysis
  extra.
- **[Verified]** `takes_create` uses real `tracks.duplicate`, rename and volume commands. It is
  dry-run by default, uses fader zero as “off”, returns undo tokens and attempts rollback.
- **[Verified]** The panel serves `/api/status`, `/api/session`, `/api/tracks`, `/api/takes`,
  `/api/plan` and `/api/apply`; it binds `127.0.0.1:9879` and uses the same client and tool paths as
  the CLI. Its preview tokens are in-memory, single-use and expire after ten minutes.
- **[Verified]** The producer tools and the panel are part of the panel baseline commit.

## Panel acceptance: what is real

- **[Verified]** The panel rendered the live scratch Set after Live was restarted with the current
  `a7fcd016f88d` build; its header showed `Live connected`, the session brief, the track rows and
  the read-only take list.
- **[Verified]** A real panel dry run previewed a single mute field, applied it on the scratch Set,
  read the field back as `true`, and returned the exact prior value as an undo token.
- **[Verified]** Applying the undo token restored the field to `false`; the scratch `.als` SHA-256
  was unchanged before and after, so Live did not save it.
- **[Verified]** The panel planned and applied a two-take set on `snare rush` (indices 10 and 11),
  with take 1 at `0.85`, take 2 and the source at `0.0`. A/B moved take 1 to `0.0` and take 2 to
  `0.85`; undo removed both copies and restored the source. The scratch `.als` hash stayed unchanged.
- **[Verified]** Real `takes_select` via the panel selected take 2, read it back at `0.85` with take 1
  at `0.0`, and the returned fader undo restored the prior state.
- **[Verified]** Real `takes_discard` was previewed by the panel with `can_apply: false` and no token;
  the CLI removed both takes after `confirm: true` and read back 32 main tracks with the source
  restored. This is irreversible deletion, not undo.
- **[Unverified]** A manual click-through of every UI control, panel buttons for take select/discard,
  and audible verification. The fake suite covers the plan/apply and discard paths but is not Live proof.
  An unfreeze-tracks prompt was accepted on the scratch Set during the gate; it is an in-memory
  freeze-state change, and the on-disk `.als` hash stayed unchanged.

## Producer slice: what is real

### `session_brief`

- **[Verified]** Read the open blank Set through real Live and returned its 4 working tracks,
  tempo, empty-track issue and producer next actions.
- **[Verified]** A real call before a fix returned 6 including return buses; the code now filters
  `kind == "return"` and a regression test covers it.
- **[Unverified]** A real read of the saved 25-track REZZ song, because that Set is not open.

### `reference_analyze`

- **[Verified]** Measured the existing 2.101 s, 44.1 kHz, stereo 24-bit WAV
  `8-Audio 0001 [2026-11-10 220442].wav`:
  peak `-5.38 dBFS`, RMS `-18.33 dBFS`, crest `12.95 dB`, LUFS `-16.97`, centroid `1638.3 Hz`,
  stereo correlation `0.684`.
- **[Verified]** Advanced analysis is installed in this environment (`numpy 2.4.6`,
  `scipy 1.17.1`, `soundfile 0.14.0`, `pyloudnorm 0.2.0`).
- **[Verified]** It is measurement only; it does not audition or declare the reference “good”.

### `takes_create`

- **[Verified]** Real dry-run on `1-MIDI` planned take indices 1 and 2, source volume `0.85`, with
  no track created.
- **[Verified]** Real panel apply on `snare rush` created two named take tracks; a CLI fader change
  switched A/B, and the returned undo tokens removed both copies and restored the source.
- **[Verified]** Real panel select, undo and confirmed CLI discard passed on the scratch Set.
- **[Unverified]** Panel UI buttons for select/discard and any audible check.
- **[Verified]** Takes are identical copies at creation; they are not generated variations.

### `takes_select` / `takes_discard`

- **[Verified]** `takes_select` accepted two take names and selected take 2; dry-run, apply and
  undo returned the expected fader changes.
- **[Verified]** `takes_discard` returned a preview with `can_apply: false` in the panel; the CLI
  apply required `confirm: true`, deleted both named takes and reported no undo token.
- **[Verified]** A source track name is rejected; take names must belong to one group.

## Existing engine breadth

The 89-tool catalogue includes:
- core status, guide, inspect and plan tools;
- track, clip, note, device and mix writes;
- arrangement/section tools;
- transport and capture;
- recipe tools;
- the five producer tools.

This breadth is **engine capability**, not the intended producer menu. The product pack recommends
`produce` as the demonstrated surface and keeps `auto` as the default until that is approved.

## Real-Live evidence that predates this pack

The following is historical evidence, not a claim that the current build repeats it:

- **[Verified, historical]** The read path, write executor, scratch copy, forced mid-plan rollback,
  diagnostics, device parameters, routing, notes, transport, capture and meter polling have real
  Live gates recorded in `MISSION.md` on earlier builds. The current `0.4.26` build has a fresh
  doctor/status read and the producer reads, not a full re-run of every historical gate.
- **[Verified, historical]** The resample capture produced a real WAV and analyzed it, but its
  routing restore failed; the track was remediated to `No Input`. See
  `docs/M6_M7_STATUS.md` for the detailed defect and open fallback work.
- **[Verified, historical]** `tracks_gain_stage` lacked a real measured-peak write on 12.2.5 at the
  time of the M4 audit; do not assume that gap is closed.
- **[Unverified]** Every historical gate has not been re-run against the current `0.4.26` build by
  this docs pass.

## Current gaps and contradictions

### Product gaps

1. **No take variation.** Take 2 is an identical copy.
2. **No producer memory.** The brief is stateless; there is no “where did we leave off”.
3. **Panel v1 is deliberately narrow.** Takes are read-only in the browser; select/discard exist in
   the CLI/MCP tools but are not UI buttons. Discard is deliberately not applicable from the panel.
4. **No reference capture orchestration.** Analysis works on a file; capture → compare is manual.
5. **No audible verification.** Measurement is not listening.

### Release gaps

- No install/config UX matching the external ten-item checklist.
- No generated Claude Desktop/Cursor configuration.
- No supported compatibility matrix; no startup rejection of unsupported Live versions.
- No uninstall/restore UX.
- No legal/privacy/refund/support assets; no `LICENSE` in this checkout.
- No demo video, beta, or version-consistency decision.
- The panel baseline is committed; a release scan and version decision remain.

### Documentation drift

| Document | Drift / action |
|---|---|
| `AGENTS.md` | Says `enableton serve` is a stub until M5; current code has stdio serve. Treat the rule as historical until the owner updates the file. Other safety rules remain authoritative. |
| `MISSION.md` | Historical sequencing and evidence; its “M4 in progress / 39 tools / 76 tools” narrative is behind this tree. Do not copy counts from it; update that ledger only after reconciling with its owner. |
| `docs/mcp.md` | Records an earlier 0.4.20 / 16-tool acceptance and a test count. Use its M5 behavior lessons, not its numbers, as current evidence. |
| `docs/M6_M7_STATUS.md` | Records a parked branch and a known capture-restore defect. Do not assume those changes are accepted on `main`. |
| `SPEC.md` | Design authority, but its file map and tool list are older than this tree. Reconcile before implementing. |
| `docs/product/*` | This pack: current product/evidence interpretation. It does not override `SPEC.md` technical design. |

## Comparison with the Supreme Potato pack

### Keep from that pack

- The ten launch milestones and traceability to release evidence.
- Product-shape decision D-1 as an explicit owner decision.
- Supported Live/OS/client matrix and fail-closed compatibility.
- A clean-machine setup test, not “works on my machine”.
- Safe save/copy, backup, restore and uninstall proof.
- Legal/privacy/support/refund gates; no invented policy.
- One consenting beta before public launch.
- A real producer demo, with consent and no private Sets.

### Do not import

- The 242-tool count, `0.1.0b1`, `1.8.1` bridge, port 9877 or generated-bridge architecture.
- `src/enableton/server.py` as the current entrypoint.
- The claim that unit/fake tests prove Live compatibility.
- Any statement that release gates are complete; that pack itself says they are not.

### Reconcile

- **Product shape:** external recommends a technical MCP tool. This repo's direction is a technical
  MCP tool **with a producer-facing workflow**, plus an additive local panel. The panel is a
  loopback-only surface over the same bridge, not a replacement for the MCP/CLI engine.
- **Three workflows:** external requires inspect/repair, arrangement editing and sound/device work.
  This repo adds Analyze/Suggest/Create take. Use the producer verbs as the experience and the three
  external workflows as the release proof set.
- **Name:** external says EnAbleton; this package is Enableton. Treat naming as a product decision,
  not a code rename.

## What not to do next

- Do not apply a take to a working Set just to make a demo.
- Do not call `takes_create` a variation generator.
- Do not claim take variation, panel select/discard buttons or audible verification exists. Real
  take apply, fader A/B, select/undo and confirmed discard are verified on a scratch Set.
- Do not copy external tool counts or setup steps.
- Do not bump the Remote Script unless you are changing `remote_script/`; the producer tools are
  client-side.
- Do not say the fake suite proves the product works.
- Do not add legal/support text the owner has not supplied.
