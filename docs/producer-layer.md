# Producer layer

This is the first vertical slice of the producer-facing Enableton experience: the backend
vocabulary plus the additive local panel documented in [panel.md](panel.md).

## Product thesis

Enableton should feel like a co-producer with context, alternatives and proof, not a larger tool
menu. The producer should see three verbs: **Analyze**, **Suggest**, **Create take**. The low-level
catalogue remains the engine underneath.

## Implemented in the current slice

**[Verified in the fake suite]** The `produce` mode exposes:

- `session_brief` — sections, name-based roles, clip density, sparse sections, duplicate names,
  empty tracks and producer next actions, all from one snapshot.
- `reference_analyze` — basic PCM WAV measurements (peak, RMS, crest factor, headroom, DC,
  channels, stereo balance) and optional advanced analysis (integrated LUFS, spectral bands,
  centroid, stereo correlation) when numpy, soundfile and pyloudnorm are installed.
- `takes_create` — duplicates a real track 1–8 times, names the copies, leaves take 1 audible and
  lowers the source and other takes to fader zero. Dry-run by default. It returns duplicate and
  volume undo tokens and attempts a rollback after a failure.
- Supporting tools: `tracks_list`, `tracks_set_volume`, `sections_map`, `inspect_structure`,
  `mix_levels_report`, `mix_headroom`, `mix_resample_capture`, transport locate/play/stop and
  `ableton_undo`.

**[Verified on real Live 2026-11-12]** `session_brief` read the open untitled 120 BPM Set twice;
the track count changed while Live was open, and the brief reflected the new count rather than a
cached value. `takes_create` dry-run planned two takes of `1-MIDI` and wrote nothing. The current
open Set was blank, so the 25-track REZZ Set was not available for this read.

**[Verified on real Live 2026-11-13]** On a backed-up scratch Set, the panel applied two takes of
`snare rush`, fader A/B switched between them, and the returned undo removed both copies and
restored the source. The scratch `.als` hash was unchanged; the working Set was not opened.

**[Verified on a real captured WAV 2026-11-12]** `reference_analyze` measured the 2.101 s,
44.1 kHz, stereo 24-bit capture `8-Audio 0001 [2026-11-10 220442].wav`: peak `-5.38 dBFS`, RMS
`-18.33 dBFS`, crest `12.95 dB`, LUFS `-16.97`, spectral centroid `1638.3 Hz`, stereo correlation
`0.684`. The capture came from the earlier resample work; no new audio was recorded for this gate.

The fake suite proves internal consistency only. The real gate above is the separate evidence.

## Deliberate limits

- Roles are inferred from track names, not audio.
- `reference_analyze` is measurement, not an audition. It cannot decide whether a reference is
  good or whether a mix is finished.
- Takes begin as identical duplicates. The producer or a later variation feature must edit each
  copy into a real alternative.
- A/B is fader-based (`0.0` is treated as off). It is reversible, but it is not a dedicated mute
  command.
- The local panel exists, but it is deliberately narrow: read-only take groups, no
  `takes_select`/`takes_discard`, no one-click undo, and no audible check.
- No automatic save/export. The existing save limitation is unchanged.

## Next phases

### 1. Real-Live acceptance

- `session_brief`, `reference_analyze`, the take dry-run and a two-take apply/A-B/undo are now
  verified on real Live; the take run used a backed-up scratch Set.
- Re-run the take gate on a fresh scratch copy after any take/executor change.

### 2. Take variations

- Add a `variation` argument to `takes_create`: velocity scale, transpose, duration scale, or a
  device-parameter delta.
- Add `takes_select` so the producer can make take 2 audible without exposing fader values.
- Add `takes_discard` with a confirmation gate, because deleting tracks is irreversible.

### 3. Reference Lens

- Capture the selected section through the existing resample path.
- Compare the captured master to a reference profile and report deltas, not targets.
- Add section-energy and low-end/Kick-bass measurements using stems when the producer supplies
  them.
- Do not call this mastering.

### 4. Session memory

- Persist the producer goal, decisions and accepted takes per Set, outside the `.als`.
- Surface "where did we leave off" from that local state.
- Keep the source of truth in the Set and the memory a convenience, never a hidden edit.

### 5. Producer panel

- The local panel exists with status, session brief, tracks, safe row actions and a dry-run/apply
  composer; takes are read-only.
- Next: expose select/discard only after those tools exist, add a clear undo affordance, and keep
  the dry-run plan readable.
- Do not turn the panel into a separate product shape or hide a write behind one click.

## Acceptance for a sellable slice

- One real sentence-to-outcome demo works end to end on a backed-up Set.
- The producer can see why a take exists, what changed and how to undo it.
- The reference report clearly separates measured values from unavailable values.
- No take or analysis writes to the working Set without an explicit apply.
- The app never claims it heard something it only measured.