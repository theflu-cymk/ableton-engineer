# Vocal alignment — reference mix to vocal stem

Use this when a vocal taken at one tempo has to sit inside a Set at another tempo. The offline
script measures the two files and emits a warp map; the bridge applies that map to one Live clip.
It does not listen, decide which take is better, or split a clip.

## What this solves

A clip's **tempo field is not exposed** by Live's LOM on 12.2.5. The clip's speed comes from its
warp markers, so the reliable route is:

1. measure the vocal against a reference that contains the same take;
2. generate source-seconds ↔ clip-beat markers;
3. set the clip's start/end markers and replace its interior warp markers.

`clips.warp_map` reads the clip's file path, bounds, sample rate and exact markers.
`clips.apply_warp_map` applies a measured map with dry-run and an undo token. Both are in Remote
Script **0.4.22**; Live must be restarted after installing that version.

## Trigger

The input is two absolute audio paths and the target timeline values:

- the vocal stem (source tempo);
- a reference mix containing the same vocal take (target tempo);
- the reference clip's arrangement start and end beats in Live;
- the vocal clip's arrangement start beat.

The reference may be a full mix; the measurement uses the 250–5000 Hz onset band and does **not**
need stem separation.

## Command

```bash
uv run --with librosa --with soundfile --with scipy python scripts/vocal_align.py \
  --vocal "C:\path\Vocals - ... - 96bpm - Bmaj.mp3" \
  --reference "C:\path\fortnight (1).mp3" \
  --source-bpm 96 --target-bpm 120 \
  --reference-start-beat 9 --reference-end-beat 379 \
  --clip-start-beat 12 \
  --out .tmp/vocal_alignment.json
```

The report includes `rate`, `lag_s`, `correlation`, `lag_windows`, `lag_spread_s`, `start_marker`,
`end_marker`, all `markers` and a ready `apply_args` object.

### Interpretation

- `lag_s` is the reference time minus the stretched vocal time. A positive value means the
  reference file is slightly later than the vocal file.
- `start_marker` and `end_marker` are clip-relative beats. The script includes the start-marker
  offset in both; do not subtract it again.
- `sample_time` is **seconds**, not samples.
- `markers` are interior markers; the first and last existing markers stay anchored.
- A `stable: true` result means the window lags vary by no more than `--max-drift-s` (default
  0.10 s). That supports a constant-rate map. A larger spread needs phrase-level work instead.

## Applying it

Read the actual clip first; do not guess from the track name:

```bash
uv run enableton call clips_warp_map --json --args '{
  "track": "4-Vocals - Taylor Swift - Fortnight (feat. Post Malone) (Official Music Video) - 96bpm - Bmaj",
  "clip": "Vocals - Taylor Swift - Fortnight (feat. Post Malone) (Official Music Video) - 96bpm - Bmaj"
}'
```

Check `file_path`, `start_marker`, `sample_rate` and `sample_length`. If the reference clip has a
nonzero `start_marker`, pass its file-time equivalent as `--reference-offset-s` and regenerate.

Dry-run, then apply:

```bash
uv run enableton call clips_apply_warp_map --json --args '{
  "track": "…", "clip": "…", "dry_run": true,
  "start_marker": 2.8142, "end_marker": 369.8142,
  "markers": [ … ]
}'
```

Change `dry_run` to `false` only after the dry-run reports the expected remove/add counts. The
response's `undo` token restores the exact old markers and bounds.

## This song — measured 2026-11-11

Files:

- vocal: `C:\Users\brian\Downloads\[fadr.com] Stems - Taylor Swift - Fortnight (feat. Post Malone)
  (Official Music Video)\Vocals - Taylor Swift - Fortnight (feat. Post Malone) (Official Music
  Video) - 96bpm - Bmaj.mp3` — 249.392 s;
- reference: `C:\Users\brian\Downloads\fortnight (1).mp3` — 190.015 s, 120 BPM version containing
  the same take.

Result from the command above:

| Field | Value |
|---|---|
| rate | 1.25 |
| lag | 0.0929 s |
| correlation | 0.4894 |
| lag spread across windows | 0.0232 s (stable) |
| start marker | 2.8142 beats |
| end marker | 369.8142 beats |
| markers | 93: every 4 beats plus an explicit end anchor; source seconds 1.758875–231.133875 |

The first marker's sample is 1.758875 s, not 0: the start marker trims the silent lead-in so the
vocal's first phrase lands on the reference timeline. The final marker is pinned at 369.8142 with
source 231.133875 s; without it, Live's hidden last marker at 468.5 beats would still stretch the
final segment. The end marker is 369.8142, which places the clip's audio end at arrangement beat
379; the old 468.5-beat clip was 25% too long because it was still playing at 96 BPM in a 120 BPM
Set.

**Verified:** the offline measurement and report. **Unverified:** any listening result, and any
Live application until the new Remote Script is loaded after a restart.

## Stop conditions

| Condition | Action |
|---|---|
| correlation below 0.2 | Do not apply; confirm the same take and tempo first. |
| lag spread above `--max-drift-s` | Do not use one constant map; align in sections. |
| start marker would be negative | Move the clip later and rerun; do not fake a negative bound. |
| reference `start_marker` nonzero | Pass its file-time offset; otherwise the map is shifted. |
| reference end unknown | Pass `--reference-end-beat`; do not infer a trimmed clip's end. |
| clip is continuous across a cut in the Set | Split it at the cut first; this workflow does not split clips. |

## Limits

- No listening or artifact judgment.
- One constant speed ratio; no per-phrase time warp.
- No clip creation, track creation, or split operation. The cut at beats 74–106 in the Set still
  needs a manual split (or a separate tool).
- The full-mix reference is a timing reference only; it is not a replacement vocal stem.
