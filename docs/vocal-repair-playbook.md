# Vocal repair — one command

Use this when the user asks to repair a vocal track. The default is **one command** that reads the
saved recipe, takes the newest bounce, measures it, selects only the justified RX modules, applies the
Nectar chain, and writes a new candidate plus a JSON report. It never writes the source, and it never
claims to have heard the result.

This is a standalone offline audio workflow. It is not a Live `RecipeStore` recipe and it does not
change the Remote Script.

## Trigger — repair a vocal track

```bash
uv run --with pedalboard --with librosa --with soundfile python scripts/vocal_repair.py --auto
```

The command prints `recipe`, `selected`, `output`, `report`, `chain`, `pitch` and input/output levels.
Read the JSON report before describing what was done.

## The saved recipe — Verified 2026-11-11

Path: `%APPDATA%\Enableton\vocal-repair\recipes\vocal_repair.minimal.json`

It is machine configuration outside the repo. It necessarily contains this machine's bounce folder
and plug-in paths; keep those values out of `src/` and `remote_script/`.

| Field | Saved value | Meaning |
|---|---|---|
| `source.latest_in` | `F:\ableton songs\Fortnight\fortnight Project\Samples\Processed\Bounce` | Folder scanned for the default source |
| `source.pattern` | `*VOCALS*.wav` | Filename filter |
| `pitch.key` | `C#maj` | Manually confirmed key for this song |
| `pitch.strength` | `35` | Conservative Pitch strength, not the generic 50 |
| `nectar.enabled` | `true` | Auto-Level, Compressor, De-esser and Pitch |
| `nectar.modules` | `auto_level`, `compressor`, `deesser`, `pitch` | Nectar order is fixed by the runner |
| `auto_rx.declip_if_clipped` | `true` | De-clip only when the measurement finds clipping |
| `auto_rx.denoise_if_noise_floor_dbfs_at_or_above` | `-50.0` | De-noise when the floor is this high or higher |
| `auto_rx.deess_if_sibilance_share_at_or_above` | `0.012` | RX De-ess only above this 4–10 kHz share |
| `plugins.rx_dir` | `C:\Program Files\Common Files\VST3\iZotope\RX12` | RX VST3 folder |
| `plugins.nectar_dir` | `C:\Program Files\Common Files\VST3\iZotope` | Nectar VST3 folder |
| `output.directory` | `%APPDATA%\Enableton\vocal-repair` | Candidate and report folder |
| `output.suffix` | ` - C#maj repaired` | Appended to the source stem |

### Why these thresholds

On the bounce used to derive the recipe (full file, **Verified**): peak `-9.655 dBFS`, RMS
`-25.185 dBFS`, `0` clipped samples, noise floor `-38.408 dBFS`, 4–10 kHz share `0.006811`. The rules
therefore selected **denoise only**. RX De-ess did not qualify because the share was below `0.012`;
the Nectar De-esser still ran. That matches the conservative full render made before the recipe
existed.

One-command smoke test, 6 s window, **Verified 2026-11-11**: input peak `-12.915 dBFS`, RMS
`-25.632 dBFS`, noise floor `-38.134 dBFS`, sibilance share `0.008813`; selected `denoise`; chain
`denoise, nectar:auto_level, nectar:compressor, nectar:deesser, nectar:pitch`; pitch root
`C♯ / D♭`, scale `Major`, strength `35`; source SHA-256 unchanged. A full-length auto render has not
been run yet — the earlier full-length candidate used the same modules through the manual path.

## Auto-selection rules

| Measurement | Module selected automatically |
|---|---|
| `clipped_samples > 0` | RX De-clip |
| noise floor at or above `-50 dBFS` | RX Voice De-noise |
| sibilance share at or above `0.012`, and Nectar De-esser not enabled | RX De-ess |

Never auto-selected: **De-plosive, Mouth De-click, De-reverb**. Those need an audible symptom that
these measurements cannot establish. Add one explicitly with `--rx-modules` only after a real listen.

`--rx-modules` disables metric selection and uses exactly the list supplied. `--auto` and no
`--rx-modules` uses the rules above.

## Key and tuning

The recipe stores `C#maj` and strength `35`. That key came from a manual readout. Neither Auto-Key nor
Live Key exposes its detected key to the host, so the runner does not detect key.

- **Same song:** leave the recipe alone; `--auto` applies `C♯ / D♭`, `Major`, strength `35`.
- **Different song:** confirm the key and pass `--key Dmin`, or update the recipe only after a
  confirmed readout. `--no-pitch` keeps Auto-Level, Compressor and De-esser but skips tuning.
- **No confirmed key:** do not guess. Use `--no-pitch` or `--analyze-only`.

Nectar's root control uses the combined label `C♯ / D♭` (U+266F / U+266D), not ASCII `C#`. The runner
maps every sharp and flat spelling; do not send ASCII `C#` directly to the plug-in.

### Key readout, when a key is not stored

1. Put Auto-Key on the master/mix bus, not the solo vocal, and play at least five seconds of the
   song's main progression. Auto-Key's file mode on a mixdown also works.
2. Read the key and scale from the Auto-Key Central Display. For Live Key, read the display on the
   master-chain copy. Neither result can be read programmatically by this build.
3. Pass it explicitly, for example `--key Dmin`.
4. Do not click Send to Auto-Tune expecting Nectar to update. Auto-Key sends to compatible Antares
   plug-ins only; Nectar Pitch is set by this runner.

## Source and plug-in discovery

- Source: newest `.wav`, `.aif`, `.aiff` or `.flac` by modification time in `source.latest_in` that
  matches `source.pattern`. It does not walk `F:\ableton songs` recursively and never enters
  `/Backup/`.
- `--source` overrides discovery; `--recipe` overrides the recipe path.
- Plug-in folders come from `plugins.rx_dir` / `plugins.nectar_dir`, then `--rx-dir` /
  `--nectar-dir`, then `ENABLETON_RX_DIR` / `ENABLETON_NECTAR_DIR`.
- A missing source, recipe, plug-in folder or unknown module exits non-zero rather than substituting.

## Outputs

Base name: `%APPDATA%\Enableton\vocal-repair\<source stem> - C#maj repaired.wav`.

If that file exists, the runner appends ` 2`, ` 3`, … instead of failing. `--overwrite` reuses the
base name; `--out` uses an exact path. The JSON report sits beside the WAV with the same stem plus
`.json`. Output is 24-bit PCM. The runner refuses an output path equal to the source.

## Commands

```bash
# normal one-command repair
uv run --with pedalboard --with librosa --with soundfile python scripts/vocal_repair.py --auto

# short integration check; this is a section, not the finished candidate
... --auto --duration 8

# measure only; writes an analysis JSON, no audio
... --auto --analyze-only

# another song, with a confirmed key
... --auto --source "C:\path\vocal.wav" --key Dmin

# keep the Nectar chain but do not tune
... --auto --no-pitch

# manual RX override; disables metric selection
... --auto --rx-modules denoise,deess
```

`--start` and `--duration` process a section. Do not present a section render as the finished
candidate.

## Installed capabilities — Verified 2026-11-11

RX 12 VST3s: De-clip, De-plosive, Mouth De-click, Voice De-noise, De-reverb, De-ess, Repair Assistant
(23 exposed parameters; its proposal UI is not automated), Spectral De-noise, De-hum, De-click, Breath
Control and Music Rebalance.

Nectar 4 VST3s: the main plug-in (819 parameters), Auto-Level, Compressor, DeEsser, Equalizer, Pitch,
Breath Control, Gate, Saturation, Delay, Reverb, Dimension and Voices. No `assistant` parameter is
exposed; **Vocal Assistant remains a manual UI step.**

Auto-Key is installed at `C:\Program Files\Common Files\VST3\Antares\Auto-Key.vst3` (version
`1.0.1`). Its only host-visible parameter is `bypass`. Processing an 8-second segment left
`raw_state` byte-for-byte unchanged, and it exposes no key, scale, tempo or detection result.

Live Key is a Max for Live audio effect (`MxDeviceAudioEffect`), not a VST3. The master copy sits
inside `KIS_FREE Techno Mastering Chain`. Its controls are `Analyze`, `Target Root`, `Target Scale`,
`Set Live Scale`, `Follow Live Key` and `Hepta / Penta`; there is no explicit detected-key parameter.
Pressing `Analyze` on the track-8 copy left `Target Root` at `C` and `Target Scale` at `Major`, so
those controls cannot be treated as the detection result. `devices_read_parameters` addresses regular
tracks only; `master_chain_read` does not expose master device parameters.

The MCP has no `devices_insert`, `tracks_create`, arbitrary-WAV import or render/export tool.
`mix_resample_capture` is not a substitute for an Arrangement render.

## Procedure when asked to repair a vocal

1. Run `--auto`.
2. Read the report: `recipe.id`/`path`, `source_selection`, `auto_selection` reasons,
   `modules_requested`, `chain` parameters, `key_source`, `pitch_scale`, `pitch_root`,
   `pitch_strength`, `source_analysis`, `output_analysis`.
3. Confirm `source_file` and `output_file` differ. The script never writes the source; the 2026-11-11
   run also compared the source SHA-256 before and after and it was unchanged.
4. Report the candidate and report paths, the selected modules and why, the Nectar chain, the key and
   strength, and the measured before/after levels.
5. Say plainly that nobody auditioned it. The candidate must be A/B'd at matched loudness. If a module
   pumps, lisps, sounds watery or dulls consonants, back it off or remove it.
6. List the limitations below. Never say "fixed", "sounds better" or "verified by ear".

## If the user wants the repair inside Live

This build cannot insert devices. Ask the user, once, to add the source WAV to a track and insert the
chosen RX/Nectar devices themselves, then tell you the track name. You may inspect and adjust exposed
parameters, duplicate the track for safety, and report the chain, but do not claim to have rendered
or auditioned it. Offline rendering remains the reliable path.

## Report contract

- recipe id and path, source path, source-selection reason
- analysis window and measured source peak/RMS, clipping, noise floor, sibilance share
- `auto_selection` with a reason per module, or `--rx-modules` as the manual override
- every stage and parameter actually applied
- whether Pitch was applied; key, scale, root label and strength
- output WAV and JSON report paths
- **not claimed:** listening or artifact assessment
- missing: Auto-Key and Live Key programmatic readouts, Vocal Assistant, Repair Assistant proposal,
  RX spectral editing, Live device insertion

## Missing / not automated

- No audio audition or artifact judgment. Measurements cannot establish that a repair sounds good.
- Auto-Key's detection result and Live Key's detected key cannot be read programmatically.
- Nectar Vocal Assistant, RX Repair Assistant's proposal analysis and RX standalone spectral editing
  are not automated.
- No Live device insertion or audio import; no Live device or clip is changed by this workflow.
- Full save/restore and the M2/M3 gates are unrelated; this script does not touch a Set.
