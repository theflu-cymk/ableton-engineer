# Beat recipe from an audio file — fast path

Use this when the user says **“make a beat recipe from this file”**. It is written for
**140 BPM half-time / UK dubstep** material. The default path is one offline render and one
analysis pass; it does not use Live capture, freezing, flattening, resampling, or a new Live
track.

## The decision, made once

**The only required input is an absolute path to the audio file.** Ask for it and the recipe id/name,
then run the command. Do not ask for a Live track and do not wait for plugin preparation.

A Live track is needed only when the user wants a **Live reference or audition**. This build cannot
create that track, import the WAV, or insert the plugin, so in that one case the user prepares it.

| Request | Fast response |
|---|---|
| “Recipe from `C:\...\file.wav`” | Run the offline command below. No Live prep. |
| “Recipe from the track in Live” | Ask for the WAV path; the MCP cannot read arrangement audio. |
| “Put it on a new track and add RX” | Cannot create a track or insert a device on this build. Ask the user to add the WAV + RX, or use the offline path if they only need the recipe. |
| “Use the plugin already on the layer” | Not needed for analysis; the same RX 12 VST3 is invoked offline. |

## Capability boundary — Verified on Live 12.2.5

- `devices_insert` is absent; `Track.insert_device` is Live 12.3+.
- There is no `tracks_create`, no arbitrary-WAV import, and no plugin-insert tool.
- `library_*` only browses; it does not load.
- `tracks_duplicate` exists, but it duplicates existing content; it cannot replace the audio.
- `mix_resample_capture` is not the path here: an Arrangement clip with no Session clip produced a
  silent 4.16 s WAV in the 2026-11-11 test.

If the user wants a Live-side copy and has prepared a source track with the WAV and RX 12:
duplicate it with `tracks_duplicate`, name the copy `REF | <name> (RX)`, set `Drums Solo = On` on the
copy, and leave the original untouched. Do not attempt to render it through Live.

## Fixed defaults — do not re-decide these

| Parameter | Value |
|---|---|
| Plugin | `C:\Program Files\Common Files\VST3\iZotope\RX12\RX 12 Music Rebalance.vst3` |
| Quality | `Best / Offline` |
| Stem | `Drums Solo = On`, `Drums Gain = 0.00 dB` |
| Other stems | Vocal / Bass / Drums / Other; no Piano control |
| Window | 24.0 s, starting at 44.0 s, clamped to the file |
| Tempo candidate | 140 BPM; accept 138–142 |
| Meter | 4/4 |
| Grid | 1/16 |
| Recipe length | 2 bars |
| Recipe feel | sparse half-time: kick 1, snare 3, hats 2/4 |
| Confidence | 0.65 overall; downbeat medium |

## Run it

From the project root:

```bash
uv run --with pedalboard --with librosa --with soundfile python scripts/beat_recipe.py \
  --plugin "C:\Program Files\Common Files\VST3\iZotope\RX12\RX 12 Music Rebalance.vst3" \
  --source "C:\path\to\source.wav" \
  --id "artist_track.140_beat" \
  --name "Artist - Track - 140 half-time"
```

The path can instead be put in `ENABLETON_RX_PLUGIN`.

Use `--start 60` only if the user names a better drop; use `--no-save` for a read-only trial.
If the recipe id already exists, use `--overwrite` only when the user asked to replace it.

The command writes:

- `%APPDATA%\Enableton\recipes\<id>.json`
- `%APPDATA%\Enableton\analysis\<id>.analysis.json`
- `.cache\<id>.stem.wav` (audit stem; not a deliverable; remove when done)

## Procedure

1. **Resolve the source.** Absolute `.wav` path. If it is missing, ask for the path and stop.
2. **Confirm RX.** The VST3 path above must exist. If not, ask the user to repair/reinstall RX 12;
   do not substitute another plugin.
3. **Render.** 24 s mono/stereo stem through RX, `Best / Offline`, `Drums Solo`.
4. **Check the stem.** RMS must be greater than `1e-4`. A silent stem is a stop, not a recipe.
5. **Measure.** `librosa.beat_track(start_bpm=140, tightness=100, hop_length=256)`.
6. **Classify.** 30–120 Hz low share ≥ 0.50 → kick; 4–12 kHz high share ≥ 0.50 with centroid
   ≥ 6 kHz → hat; otherwise snare.
7. **Find the downbeat.** Test four beat rotations and maximize kick at step 1, snare at step 9
   (beat 3), and hats at steps 5 and 13 (beats 2 and 4). Record it as medium confidence.
8. **Quantize.** Nearest 16th. Keep events with bar indices 1–8 for the report. Do not drop
   pre-downbeat onsets silently; record their negative error in the audit report.
9. **Write the fixed sparse recipe** and the analysis file. Validate with `recipe_save` semantics.
10. **Compile, do not apply.** If a MIDI target is supplied, `recipe_apply` should produce a
    reversible plan; inspect the note count, then `ableton_plan_discard`. Never apply the plan
    unless the user explicitly asks to change the Set.

## Stop conditions

| Condition | Action |
|---|---|
| No source path | Ask once for the absolute WAV path; stop. |
| RX missing or fails to load | Report the plugin path; ask for reinstall/repair. |
| Stem silent | Stop; do not write a recipe. |
| Tempo outside 138–142 | Report the measured tempo; do not call it 140. The sparse template is not valid for an unrelated genre. |
| Fewer than 4 bars | Shorten the window; mark downbeat low confidence; do not invent a drop. |
| Live target absent | Recipe generation is still complete; skip compile. |
| User asks to replace existing recipe | Require explicit `--overwrite` / `overwrite: true`. |

## Stems and removal — Verified plugin controls

RX 12 Music Rebalance exposes exactly four music stems:

| Stem | Isolate | Remove |
|---|---|---|
| vocals | `vocal_solo = True` | `vocal_mute = True` |
| bass | `bass_solo = True` | `bass_mute = True` |
| drums | `drums_solo = True` | `drums_mute = True` |
| other | `other_solo = True` | `other_mute = True` |

There is **no Piano stem**. Piano is inside **Other**, together with guitars, keys and other
instruments; do not label an `Other` render as piano.

Use the same RX file, quality and no-Live rule:

```bash
uv run --with pedalboard --with librosa --with soundfile python scripts/rx_stem.py \
  --plugin "C:\Program Files\Common Files\VST3\iZotope\RX12\RX 12 Music Rebalance.vst3" \
  --source "C:\path\to\source.wav" \
  --stem vocals \
  --mode isolate
```

For the residual mix without vocals, use `--mode remove --stem vocals`. For the piano-bearing
bucket, use `--stem other`; the result is an **Other** stem, not a piano-only stem. `--sensitivity`
is optional, 0–100, default 50. Output defaults to
`%APPDATA%\Enableton\stems\<source> - <stem> (<mode>).wav` plus a JSON report. Use `--out` and
`--overwrite` only when needed; `--start`/`--duration` render a section instead of the full file.

## Report contract

Return these, without inflating confidence:

- absolute source path and analysis window
- measured tempo and nominal BPM
- downbeat time and confidence
- bar starts and beat times
- first two bars of events: time, bar, beat, step, event, confidence
- full event count and analysis-file path
- recipe id, path, lane patterns, and note count
- compile status (plan ready/discarded), never “applied” unless it was
- limitations: RX on a bass loop, inferred lanes, no listening test
- whether the original is untouched

## Live-side preparation (only for audition/reference)

Ask the user for exactly this, once:

> Create one audio track and tell me its exact name. Put the source WAV on it as a single
> Arrangement clip, insert **RX 12 Music Rebalance**, and set `Drums Solo = On`. Do not move or
> alter the original file. Reply with the track name and the WAV path.

Then verify the track, clip and device; duplicate only if a reference copy is wanted. This is a
capability boundary, not a preference: the MCP cannot create the track, load the WAV, or insert the
plugin.

## Worked result — 2026-11-11

- Source: `Living Denied x GPE - UK Dubstep - Bass Loops - 27 - (140) - (Dmin) (Mashup).wav`
- 24 s at 48 kHz; measured 140.625 BPM, 4/4
- downbeat 45.008 s; 41 detected events; stem RMS 0.1014
- recipe: `living_denied_gpe.140_beat`, 8 notes over 2 bars
- compiled to a plan and discarded; no Live write

That result is [Verified] for the offline signal chain and recipe validation. The downbeat and
instrument labels are [Estimated], not ground truth.
