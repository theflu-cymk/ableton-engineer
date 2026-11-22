# Native bass-music recipes — dubstep, riddim, deathstep, tearout

Research synthesis behind the shipped recipe pack. It answers one question: **what are the sounds, and
how do you make each of them with Live's own instruments** — Operator, Wavetable, Analog, Drift,
Simpler/Sampler, Drum Rack and the stock effects — so that a recipe can hand a producer a real next
move instead of a preset name they may not own.

Evidence tags follow `AGENTS.md`: **Verified** means someone ran it here, **Assumed** means inferred
from a source without running it, **Unverified** means a claim to check. Almost everything about
sound design below is **Assumed** from a tutorial or a manual, because nothing in this doc was
auditioned. What is **Verified** is the mechanical part: every recipe file validates, every shipped
rhythm compiles, and the pack is guarded by `tests/test_recipe_store.py`.

## The hard limit that shapes the pack

`Track.insert_device` needs Live **12.3**; this machine runs **12.2.5** (`SPEC.md` §2). Enableton
therefore cannot create an Operator, a Wavetable, a Drum Rack, or a track to hold them. It also has
no way to author a synth patch. So the pack has three honest shapes:

| Kind | What it can do | What it cannot do |
|---|---|---|
| `style` (checklist) | Names the exact native devices, the parameter ranges and the order of moves; `recipe_show` resolves its ingredients. Twenty of them also carry a four-beat `audition` phrase | The audition phrase, into an existing MIDI clip on the track its role resolves to; the other six process a bus, layer stack or sample and stay **reference only** |
| `rhythm` (pattern) | Writes real MIDI notes into an **existing** MIDI clip through `notes_replace`, inside a plan with a dry run and undo. Grids: 1/16, 1/8T, 1/16T | Choose or load samples, or create the clip it writes into |
| `workflow` (arrangement) | Writes real section locators through `sections_create_locators`, dry-run first, with an exact locator rollback | Move audio, reorder sections, or set tempo (`transport_set_tempo` has no `dry_run`, so a plan refuses it) |

That is why a "recipe" here is never a claim that the sound exists: it is a plan for the producer's
hands plus, where the LOM allows it, a real write.

## The four styles at a glance

| | Tempo / feel | Snare | Bass centre | Drums | Form |
|---|---|---|---|---|---|
| **Dubstep** | 138–142, half-time | on beat 3 | wobble mid + clean sine sub | sparse, swung hats, layered snare | build → drop, 8- or 32-bar blocks |
| **Riddim** | 140–150, half-time | on beat 3 (some variants 2 and 4) | one short motif, triplet bounce, heavy distortion | minimal; kick, hat, clap | one motif repeated through the drop |
| **Deathstep** | 140–150, half-time | on beat 3, often layered | inharmonic FM growl, formant, separate sub | blast-beat kick flurries between drops | long dread intro, violent drops |
| **Tearout** | 140–150, half-time | on beat 3 | growl/gun/siren family, constant variation | rugged half-time, ghosted percussion | two drops, second heavier |

Sources: genre summaries and production guides listed at the end. Tempo and placement agree across
sources; the *feel* differences are the useful part, not the numbers. **Assumed.**

## Dubstep

### Drums
Kick on 1, snare or clap on 3, sixteenth hats slightly late, short kick tail so it does not boom into
the bass. Layering a snare with a clap and a noise burst is standard. Native path: a Drum Rack, one
pad per element, with the Operator kick recipe below for a synthesised kick. **Assumed** (EDMProd,
Native Instruments, Soundtrap).

### The sub
A separate sine sub, mono, one voice, gentle glide, high-cut above ~120 Hz, sidechained to the kick.
Do not let the wobble patch carry the fundamental: filter movement on a sub is a mix fault, not a
sound. Native path: Operator, Osc A sine, other oscillators off, filter off. **Assumed.**

### The wobble (Operator)
The classic patch, in the order the tutorials build it:

1. Osc A **Saw D** (or square) at 0 dB; Osc B **sine at about −12 dB**, unmodulated, as the sub. **Assumed**
2. Filter **OSR-24** low-pass, cutoff ≈ 100 Hz, resonance ≈ 0.30. **Assumed**
3. A **MIDI LFO** device before Operator, mapped to filter cutoff: **square**, **1/4** synced, amount ≈ 70 %, **retrigger on**. The external LFO keeps Operator's envelopes free for amplitude. **Assumed**
4. Talking variant: LFO to 1/2 bar, more resonance, **Redux** hard downsample 15–24 after the synth. **Assumed**
5. **Saturator** (Analog Clip, drive +6 dB, output −3 dB), then **EQ Eight** (30 Hz low cut, dip at 300–500 Hz if boxy). **Assumed**
6. **Multiband Dynamics** (OTS preset) at 20–30 % wet, and a **Compressor** keyed from the kick at 4:1 for 3–4 dB. **Assumed**

Recipe: `dubstep.wobble_operator`. Sub: `dubstep.sub_operator`.

### Composition
Half-time at 140 means the bar is 70 BPM wide; the bass gets the space the snare leaves. Builds work by
subtraction — filter the bass, drop the sub, then bring both back. **Assumed.**

## Riddim

Riddim is dubstep reduced to a loop: one short bass motif, repeated, with the variation in the sound
rather than the notes. The bounce is usually triplet-based, which matters for the engine (below).

### Patch principles, mapped to native devices
| Principle (source wording) | Native equivalent |
|---|---|
| Simple core tone: square, saw-square, or FM | Wavetable Basic Shapes with Classic PW/sync, or Operator 2-op FM |
| Clean sub layer underneath | Operator sine, separate track |
| Mono, short glide 20–40 ms | Wavetable Global → Mono + Glide, or Operator Voices 1 + Glide |
| Short LFO on position / FM amount / cutoff | Wavetable matrix: LFO 1 → Osc position or FM amount, 1/8 or 1/16 |
| Stacked distortion of different characters | Saturator → Redux (or Erosion), then EQ Eight |
| Short notes, space between them | Note length and rests in the MIDI clip, not synth settings |

**Assumed** — the sources describe Serum; the mapping to Wavetable/Operator is inference, and the
timings are starting points.

Recipe: `riddim.triplet_operator`. Bounce pattern: `riddim.bounce_140` — authored on `1/8T`, so its
notes sit on real triplet positions rather than a sixteenth grid (see below).

### Triplets are rendered, not approximated
`recipe_rhythm` renders three grids, and the grid decides the bar length the pattern parser demands:

| `tempo.grid` | Steps per 4/4 bar | Step length |
|---|---|---|
| `1/16` | 16 | a quarter of a beat |
| `1/8T` | 12 | a third of a beat |
| `1/16T` | 24 | a sixth of a beat |

A 12-step bar on a 1/16 grid is a validation error, not a silently shifted rhythm, and an unknown
grid is refused with the supported set named. `riddim.bounce_140` is authored on `1/8T`: its accented
three-hit cluster starts on beat one and its third hit sits two thirds of the way through the beat,
which is exactly the position a 1/16 grid cannot play. Swing is refused on triplet grids — it delays
"every second 1/16", which is a straight-grid idea — and the render summary reports `grid` and
`steps_per_bar` so the caller can see what was written. `1/16T` is supported and covered by tests but
no shipped recipe uses it yet.

## Deathstep

Deathstep is dubstep's half-time lurch plus death-metal tonality: cavernous sub, serrated mid-range
growls, chromatic dissonance, blast-beat kick flurries, cinematic dread. **Assumed** (Melodigging,
Recording Arts Canada's TenGraphs interview).

### The growl (Operator)
1. Two-operator FM: A sine at 0 dB, B sine at **Coarse 3–8**, short decay on B so the modulation is
   strongest at the attack. **Assumed**
2. Detune B off a whole-number ratio to make the harmonics inharmonic. **Assumed**
3. A formant stage — narrow band-pass in Auto Filter, or **Corpus** tuned to a low vowel — swept across
   the note. **Assumed**
4. Split the sub **before** distortion (filter the growl at 100–120 Hz, keep a separate sine sub). **Assumed**
5. Stack two distortion characters (Saturator → Redux/Erosion), then EQ Eight to tame 2–5 kHz. **Assumed**
6. Chromatic phrase with minor-second moves and a pitch drop at the end of the bar. **Assumed**
7. Resample and pitch/chop the audio for the second drop. **Assumed**

Recipe: `deathstep.growl_operator`.

### The screech (Wavetable)
Attack Magazine's foghorn patch is the closest documented native recipe for a high, tearing lead:
**FM oscillator effect, tune 100 %, amount ≈ 30 %**, **24 dB low-pass ≈ 200 Hz, resonance ≈ 25 %**, a
filter envelope that opens then closes, and a long amp decay. For a deathstep screech, add a downward
pitch envelope, a resonant high-pass around 500–800 Hz and a short 1/8 delay. **Assumed** (the FM and
filter values are the tutorial's; the rest is applied practice).

Recipe: `deathstep.screech_wavetable`.

### Drums and form
Kick flurries and double-kick fills between drops; the half-time snare stays the anchor; long intro,
violent drop, no pop chorus. Recipe: `deathstep.kick_flurry_140` (a Drum Rack MIDI pattern: isolated
hits in bar one, a full sixteenth flurry in bar two, snare on 3, swung ghost hats).

## Tearout

Tearout keeps the dubstep low end and pushes distortion, modulation and call-and-response to the
front: growls, guns, sirens, resampled fills, and a second drop that is heavier than the first rather
than different. **Assumed** (Melodigging, and the genre breakdown describing siren-like high tones).

Native families worth keeping separate, because each is a different patch shape:

| Family | Native starting point |
|---|---|
| **Wobble** | `dubstep.wobble_operator` — saw + sine sub, synced square LFO |
| **Growl** | `deathstep.growl_operator` — inharmonic FM + formant + staged drive |
| **Gun / machine-gun** | Short FM or Wavetable stab, 1/32–1/64 repeated notes, tight amp envelope, no reverb on the sub |
| **Screech / siren** | `deathstep.screech_wavetable`, `tearout.siren_lead` — high FM, pitch automation, band-pass |
| **Filtered fill** | The same growl with an Auto Filter band-pass macro, resampled and chopped |

Existing shipped recipes cover the checklist side of this: `tearout.growl`, `tearout.gun_layers`,
`tearout.gun_click`, `tearout.gun_body`, `tearout.gun_glue`, `tearout.gun_sub_pitch`,
`tearout.filtered_fill`, `tearout.sample_gun`, `tearout.spectral_sample`, plus the native technique
recipes `ableton.operator_bass`, `ableton.wavetable_bass`, `ableton.drift_growl`.

New here: `tearout.siren_lead` (the high layer that answers a growl) and `tearout.call_response_140`
(the phrasing: three growl hits, a gap for the tail, an answer displaced later in bar two).

## What the YouTube transcripts added

The mission asked for video tutorials specifically. Retrieval took two routes; the second worked.

**Method and failures.** The first attempt fetched a transcript-hosting page
(`https://youtubetotranscript.com/transcript?v=rJQbh9Y67XM`), which returned the service's own error —
`Web fetch is temporarily unavailable. Try again later or continue without web results.` — with no
transcript body; repeating that URL would have reproduced the same failure. **Verified** (observed in
this session) for both the error text and the empty body.

The second route installed `youtube-transcript-api` in a throwaway environment
(`uv run --with youtube-transcript-api`) and fetched the caption tracks directly. It returned cue
sheets for all five videos on the first attempt — 182, 117, 139, 77 and 456 cues — so the retrieval is
**Verified**; no video failed and no retry was needed. The captions are auto-generated, so the wording
is rough in places ("e notes" for "eighth notes", "30 second notes" for "1/32nd notes"). Every
parameter below is **Assumed**: read from the caption text, not auditioned. Video links are in the
sources list.

### Pyramind — Operator + Corpus (rJQbh9Y67XM)
- Start with a **sine in Operator's first oscillator**, then turn on the second with **one of the
  sawtooth waves** to add harmonics. Pull that operator's envelope **peak all the way up** and dip it
  so the sound "ducks down and then comes in" — the transcript's shortcut to a gritty dub bass.
- Add a **third operator that modulates the second**: stacked FM rather than parallel layers.
- **Pitch envelope on**, **very short decay**, **peak up**, for punch on the attack.
- **Corpus**: the **pipe** and **tube** resonators "sound the best with bass-style synths". Click
  **frequency** to switch from a fixed frequency to **key scale** so it transposes; choose **low** for
  the fundamental when playing chords; the **off delay / off decay** tab sets the tail after key
  release; **decay** shortens the resonance; **radius** enlarges the tube and makes it more resonant.
  Corpus has a built-in limiter and saturation, so trim the Operator level and back off its gain.
  Dry/wet: "just a little bit more" for this kind of dubstep texture, 10–20 % when it is only a hint.

**Assumed** — caption text, not auditioned. **Tie:** this is the source for `deathstep.growl_operator`'s
formant step, which names "Corpus tuned to a low vowel" without values; the tube/pipe choice, the
key-scale frequency switch and the off-decay/radius/decay moves fill that step in. Corpus's built-in
limiter is why the step ends on gain staging rather than more drive.

### Dubspot — Simpler wobble (QcMtxpUAKcQ)
- Source: a **hybrid square + saw** (or PWM square) with Simpler's loop on.
- **12 dB band-pass**, not low-pass, because the transcript wants "a more dramatic effect"; frequency
  ≈ **100 Hz**, filter envelope on, **envelope amount ≈ −20**. The negative amount is what produces
  the "thump or pop" at the start of the note.
- LFO synced to Live's clock at **1/8**, LFO amount → cutoff. The LFO rate is MIDI-mapped with a
  **minimum of 1/8 and a maximum of 1/32** so it never runs away.
- **Voices 1 + Glide** for the mono slide; velocity → filter frequency; spread for chorus.

**Assumed** — caption text, not auditioned. **Tie:** a *different* Dubspot patch from the Operator one
already cited, and it tightens `dubstep.wobble_operator`. Step 2 now carries the documented band-pass
variant — **12 dB band-pass ≈ 100 Hz with envelope amount ≈ −20** for the thump — so low-pass is not
the only shape. Step 3 keeps **1/4** as the half-time default, records **1/8** as the rate this tutorial
performs with, and gains the **Voices 1 + Glide** mono slide the recipe had left out.

### Push Patterns — Wavetable growl (nbmxDxKji9M)
- Two wavetables layered, the second turned down; **Mono**, **sub oscillator on**.
- **Envelope 2** shaped up-then-down → **Matrix** → **oscillator position** on *both* oscillators
  (scanning), then the same envelope → **filter cutoff**.
- **LFO 2** re-triggered, slow attack, rate at a musical **1/16**, → **frequency cut**; drive into the
  filter, then a Reverb.

**Assumed** — caption text, not auditioned. **Tie:** this supplies the native equivalent of Serum's
wobble that the riddim table only sketched — **an envelope scanning oscillator position plus a 1/16
retriggered LFO on cutoff**, all in Wavetable. It is now written into `riddim.triplet_operator`'s
modulation step, whose LFO line already said 1/8 or 1/16.

### dnksaus — Operator tearout bass (PFmBcZujMwk)
- **Multiband compression first**, with the sub trimmed so the master limiter is not doing the work.
- **Draw harmonics** into the oscillator shape, use the filter's distortion mode, and set **velocity →
  filter frequency** with an envelope on the cutoff.
- Keep distorting, then filter harder: **map scale to a macro** driving an Auto Filter **band-pass**,
  **resample** the result to an audio track, and repeat — "consolidate that, get Wavetable".

**Assumed** — caption text, not auditioned. **Tie:** `ableton.operator_bass` is built from this
transcript step for step (multiband first → drawn harmonics and filter distortion → velocity to filter
frequency → band-pass macro → resample). The band-pass macro and resample contrast are the same moves
`tearout.filtered_fill` uses for its phone-filtered fill.

### Matt Tinkler — Drift FM (KQlGU3LTWMk)
- Low-pass down to **20 Hz**, then Drift's **frequency modulation** with the LFO **fixed at 1:1** so its
  rate tracks the oscillator pitch; map the LFO to oscillator pitch, adjust the ratio and shape, and
  let an envelope control the LFO amount; raise the oscillator level for saturation.

**Assumed** — caption text, not auditioned. **Tie:** `ableton.drift_growl` is built from this tutorial.
The transcript confirms its **1:1 tracking LFO** step and the **20 Hz** low-pass starting point.

## Shared mix chain

Four moves cover most of the mix in all four styles: **split sub from mid**, **mono below ~100 Hz**,
**one Drum Buss across the drum group**, **sidechain the mid bass to the kick**. Then gain stage to
about −6 dBFS peak and check the drop in mono. Recipe: `bass_music.mix_chain`. **Assumed.**

## Composition

Two arrangement maps circulate: compact eight-bar blocks (EDMProd) and a longer 32/16-bar form (KAN
Samples). They disagree; the pack ships the compact one and says so in the recipe notes.

`bass_music.arrangement_140` is the only recipe here that writes to the Set without a MIDI target:

```
INTRO  1 · BUILD 1  9 · DROP 1A 17 · DROP 1B 25 · DROP 1C 33
BREAK 41 · BUILD 2 49 · DROP 2 57 · OUTRO 81
```

It calls `sections_create_locators` once, so it is reversible, dry-run first, and refuses rather than
replaces an occupied bar. The per-genre adaptation (riddim shortens the drops, tearout makes the
second drop the loudest, deathstep lengthens the intro) lives in its manual checkpoints.

## Recipe index

| Recipe | Kind | Writes | Style |
|---|---|---|---|
| `dubstep.wobble_operator` | style | audition notes | Operator wobble chain |
| `dubstep.sub_operator` | style | audition notes | clean sine sub |
| `dubstep.half_time` | rhythm | MIDI notes | half-time drum/bass pattern (existing) |
| `riddim.triplet_operator` | style | audition notes | riddim motif principles |
| `riddim.bounce_140` | rhythm | MIDI notes | triplet bounce motif (1/8T) |
| `deathstep.growl_operator` | style | audition notes | FM growl + formant + split sub |
| `deathstep.screech_wavetable` | style | audition notes | Wavetable FM screech |
| `deathstep.kick_flurry_140` | rhythm | MIDI notes | kick flurry + half-time snare |
| `tearout.siren_lead` | style | audition notes | siren layer |
| `tearout.call_response_140` | rhythm | MIDI notes | call-and-response phrasing |
| `bass.loud_rack` | style | device parameters | loudness rack |
| `bass_music.mix_chain` | style | nothing | sub/mid/drum-bus chain |
| `bass_music.arrangement_140` | workflow | section locators | 140 half-time map |

## Running them

```bash
uv run enableton recipes                       # every recipe, with what can actually run
uv run enableton recipes --tag riddim          # narrow by tag, kind, text or runnable
uv run enableton recipes --kind rhythm --runnable
uv run enableton recipe riddim.triplet_operator --show   # read one recipe; no Live needed
uv run enableton recipe riddim.bounce_140 \
  --target-track "DRUMS | Remix 808 kit" \
  --target-clip "RMX | drums | 1" \
  --location arrangement --apply               # compile, then write the plan
uv run enableton recipe bass_music.arrangement_140 --manual-confirmed --apply   # checkpoint: save + clear the bars first
uv run enableton menu                          # Recipes → pick a row → confirm
```

Listing, `--show`, and compiling a recipe that declares no executable steps are local reads: they
work with Live closed. A target (whose clip length and tempo come from the Set) or `--apply` opens
the socket, so only those paths need Live running.

Twenty of the twenty-six style recipes carry a four-beat **audition phrase**: applying one writes
that phrase into an existing MIDI clip on a track you choose, so the patch you built from the manual
checklist is immediately audible. `bass.loud_rack` instead declares five **device moves** and writes
those parameter values on a track that already carries Multiband Dynamics, Saturator and EQ Eight.
The remaining five — `bass_music.mix_chain`, `tearout.filtered_fill`, `tearout.gun_click`,
`tearout.gun_glue`, `tearout.growl_fatten` — need a sample load, a device insertion, a rack/group or
routing this build has no step for; each fails at compile time with the step, the operation, the
ingredient and the remedy.

## Applying a style recipe

A style recipe has no lanes; its `audition` block (or `device_moves` list) names the ingredient role
that makes the sound. Discover that role, then point the role at a track in the ways below.

```bash
# 1. what exists, and what can write
uv run enableton recipes --kind style --runnable
uv run enableton recipe dubstep.wobble_operator --show   # ingredients: role, kind, source

# 2a. the Set already hosts the device: let the CLI find the track
uv run enableton recipe dubstep.wobble_operator \
  --target-clip "wobble test" --location session --manual-confirmed --apply

# 2b. bind the role to the track yourself (use the role names --show printed)
uv run enableton recipe riddim.triplet_operator --binding core="BASS" \
  --target-clip "triplet test" --location arrangement --manual-confirmed --apply

# 2c. or name the track directly
uv run enableton recipe deathstep.growl_operator \
  --target-track "GROWL" --target-clip "growl test" --location session \
  --manual-confirmed --apply

# 3. a processing recipe writes device parameters, on the track that already has the devices
uv run enableton recipe bass.loud_rack --target-track "BASS" --manual-confirmed --apply
uv run enableton recipe bass.loud_rack --binding ott="BASS" \
  --binding saturation="BASS" --binding eq="BASS" --manual-confirmed --apply
```

For an audition the target must be an existing MIDI clip: the plan replaces its whole note vector
(the stored plan restores the previous notes on undo), and creating a clip is a separate write. A
device-parameter recipe needs a track (`--target-track` or a binding) but no clip. `--manual-confirmed`
means the recipe's `before_apply` checkpoints — the sound-design work in its `manual` list — are
done; otherwise the CLI prints them and refuses.

Track resolution is explicit target first, then `--binding <role>=<track>`, then a device match: the
Set is scanned for MIDI tracks whose devices match the ingredient's `source` (for example
"Ableton Operator"). One match is used; several matches list the candidates and ask for `--binding`;
none names the ingredient and the binding flag. `--slot`/`--location` only say which clip a duplicate
name means.

The reported payload is the contract. For an audition, `render.strategy` is `audition`,
`render.note_count` and `render.notes` are exactly the notes written, and
`render.track`/`render.resolved_by` say which track was used and how it was chosen. For a processing
recipe, `render.strategy` is `device_parameters`, `render.moves` lists every
track/device/parameter/value written, and `render.unresolved_ingredients` names what the plan did not
touch (`bass.loud_rack` leaves `clipper` to you, since the recipe declares no move for it). Parameter
names are Live's native names, tagged **Assumed**; a name this Live build does not expose fails in
preflight rather than silently doing nothing.

A recipe that cannot write returns `status: "unavailable"` with the step it would need, the entity
and the operation this build cannot perform:

```
recipe 'bass_music.mix_chain' cannot run any step: step 1 would need `devices_load` to add
ingredient 'mono' (instrument, 'Utility'), and that tool is not reversible or dry-run, so it cannot
appear in a plan; this build cannot insert devices; remedy: load 'Utility' yourself and bind the role
to that track with `--binding mono=<track>`, add a device_moves entry, or perform the manual
checkpoints by hand
```

```
recipe 'tearout.gun_click' cannot run any step: step 1 would need a sample-loading operation
(`clips_create_session_audio` needs a file path this recipe does not carry, and `recipe_build` is
unimplemented) for ingredient 'click' (sample, 'Short percussion or noise'), and this build cannot
load a library sample inside a reversible plan; remedy: place the sample on a track yourself and bind
the role with `--binding click=<track>`, add an audition or device_moves entry, or perform the manual
checkpoints by hand
```

What each remaining blocker means:

| Recipe | Entity | Operation this build cannot perform |
|---|---|---|
| `bass_music.mix_chain` | `mono` (instrument, `Utility`) | `devices_load`: inserting a device is not reversible/dry-run |
| `tearout.filtered_fill` | `source` (sample, `Resampled tearout bass`) | loading a library sample (`recipe_build` is unimplemented) |
| `tearout.gun_click` | `click` (sample, `Short percussion or noise`) | loading a library sample |
| `tearout.gun_glue` | `layers` (instrument, `Sub, body, click and tonal layers`) | `devices_load` / building a layer group |
| `tearout.growl_fatten` | `split` (instrument, `Serum splitter`) | `devices_load` / creating a split rack |

## Gaps

- **No device creation** on Live 12.2.5, so no recipe can build the chain for you.
- **No shipped 1/16T recipe.** The grid renders (tests cover it) but every shipped rhythm is 1/16 or
  1/8T, so nothing exercises half-time sixteenth triplets in the pack itself.
- **No sample-slot resolution**: `recipe_build` is unimplemented, so a slot's `from`/`select` stays a
  declaration and MIDI rendering ignores it.
- **No one has heard these patches**: the audition phrase only makes a patch playable in a clip;
  nobody has listened, and every parameter value is a tutorial starting point.
- **Style apply writes a test phrase or parameter values, not a device chain**: the audition is a
  four-beat motif, not a composed part, and it replaces the target clip's existing notes (restorable
  by undo); device moves only change parameters of devices that already exist.
- **No measured verification** of any style checklist; `recipe_verify` has nothing to measure for
  them because they carry no `expected` fingerprint.

## Sources

Used for the specific numbers above:

- Dubspot, *Making a dubstep bass in Ableton Live* — Operator saw + sine sub, OSR-24 ≈ 100 Hz / 0.30, synced square LFO, Saturator, EQ, OTT, sidechain: https://blog.dubspot.com/video-tutorial-making-a-dubstep-bass-in-ableton-live
- Synthtopia, Dubspot Operator + Redux talking-bass follow-up: https://www.synthtopia.com/content/2010/12/03/ableton-live-wobble-bass-tutorial
- Quadrophone, wobble bass walkthrough (Operator LFO → filter, Analog LFO 1): https://quadrophone.com/synthesis/make-a-wobble-bass
- EDMProd, *How to make dubstep* (140 BPM, eight-bar structure) and *How to make riddim like Subtronics*: https://www.edmprod.com/how-to-make-dubstep · https://www.edmprod.com/how-to-make-riddim
- KAN Samples, dubstep arrangement map (32/16-bar form): https://kansamples.com/blogs/learn/dubstep-track-arrangement
- Attack Magazine, Wavetable foghorn (FM 100 % / 30 %, 24 dB LP 200 Hz, resonance 25 %): https://www.attackmagazine.com/technique/synth-secrets/drum-n-bass-foghorn-bass-with-wavetable
- Aulart, Operator kick and snare from scratch (pitch envelope, Drum Buss boom): https://www.aulart.com/blog/create-a-custom-kick-drum-with-ableton-operator · https://www.aulart.com/blog/create-a-snare-in-ableton
- Garnish Music Production, FM drums and FM bass technique (algorithm 1C3M, inharmonic B): https://edu.garnishmusicproduction.com/ableton-advanced-fm-making-fm-drum-sounds
- Melodigging, deathstep and tearout genre notes: https://www.melodigging.com/genre/deathstep · https://www.melodigging.com/genre/tearout
- Recording Arts Canada, TenGraphs on deathstep (distortion, granular textures, resampling): https://recordingarts.com/record/introduction-of-deathstep
- Genre AI and Presetdrive riddim summaries (motif repetition, mono glide, stacked distortion): https://genre-ai.app/genre/riddim · https://www.presetdrive.com/how-to-make-riddim-bass-in-serum-complete-sound-design-guide
- Bass Kleph, Drum Buss explained (compressor, boom, crunch): https://www.basskleph.com/blog/mixing-drums-with-ableton-drum-buss
- Ableton, Live Instrument Reference (Operator shells, Wavetable matrix): https://www.ableton.com/en/manual/live-instrument-reference

YouTube tutorials, fetched as caption tracks with `youtube-transcript-api` (the route that worked; see
"What the YouTube transcripts added" above):

- Pyramind, Operator + Corpus dubstep bass: https://www.youtube.com/watch?v=rJQbh9Y67XM
- Dubspot, Simpler wobble bass: https://www.youtube.com/watch?v=QcMtxpUAKcQ
- Push Patterns, Wavetable growl bass: https://www.youtube.com/watch?v=nbmxDxKji9M
- dnksaus, Operator tearout bass: https://www.youtube.com/watch?v=PFmBcZujMwk
- Matt Tinkler, Drift FM bass: https://www.youtube.com/watch?v=KQlGU3LTWMk

Where a value came from one tutorial, the recipe's `why` field names it. The five video transcripts
above were retrieved directly on 2026-11-21; the transcript-hosting page tried first failed with a
service error and returned nothing.
