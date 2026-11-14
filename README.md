# Enableton

**Enableton** is an Ableton Live MCP server for inspecting, editing and building a Set from an AI
client. This checkout also contains the first **producer layer**: a session brief, reference
measurements and real A/B track takes.

| | |
|---|---|
| Product | **Enableton** |
| Package | `enableton` `0.1.0` (`uv run enableton`) |
| Repository | `theflu-cymk/ableton-engineer` (this repo) |
| Remote Script | `0.4.26` |
| Control Surface in Live | `Enableton` |
| Python | 3.11 or newer |
| Verified against | Ableton Live 12.2.5 on Windows |
| Tool catalogue | 89 tools in 9 modes; 21 in `produce` |

## Project lineage

**Enableton** is the live project. **EnAbleton** (`theflu-cymk/EnAbleton`) is archived and kept for
reference only. They are different codebases, and their numbers do not transfer:

- EnAbleton was built on the pinned `mcp-server-ableton-live` package with a generated Remote
  Script. It reported 242 tools (156 upstream + 86 additions), release `v0.1.0-beta.2`, protocol
  `1.8.1-ext.15` and Python 3.12–3.14.
- Enableton is a custom Python server plus `remote_script/Enableton`: package `0.1.0`, Remote
  Script `0.4.26`, Python 3.11 or newer.

Tool counts, version strings, port numbers, Python ranges and setup steps in the EnAbleton README
describe the archived codebase. Use the table above for this checkout.

Run one bridge per Live install. Select the `Enableton` Control Surface; the earlier AbletonMCP
surface is retired and should not be left where Live can select it.

## Status

The Live engine, the producer slice and the local web panel are implemented and covered by the
fake suite. The panel is the everyday entry point; the MCP server and CLI remain available for
automation and the full tool catalogue. See [docs/panel.md](docs/panel.md) for the panel guide and
[docs/producer-layer.md](docs/producer-layer.md) for the producer-layer limits.
For the reconciled product direction, current evidence, owner decisions, roadmap and release
gates, start at [docs/product/README.md](docs/product/README.md).

Verified environment for this checkout: **Ableton Live 12.2.5 on Windows**, Python 3.11, and an
installed Enableton Remote Script. Other versions are not claimed supported.

## Install
```bash
uv sync
uv run enableton setup
```

Then, in Live:

1. Open **Preferences > Link, Tempo & MIDI**.
2. Put `Enableton` in an empty Control Surface slot.
3. Run `uv run enableton doctor` and confirm the script and build are current.

Live scans Remote Scripts only at startup. After changing `remote_script/`, run
`uv run enableton setup --force`, restart Live, and run `doctor` again.

## Panel

Open the local producer window:

```bash
uv run enableton panel
```

It opens <http://127.0.0.1:9879/> by default. Use `--no-browser` to print the URL instead, or
`--port` if 9879 is occupied. The panel binds loopback only, has no build step, and loads no CDN
assets or external fonts. Its default view is a patch-browser-style recipe catalog with search,
kind/tag facets, source/status filters and sorting; staging a recipe shows the exact ordered plan
and writes nothing until Run. A compact Set view keeps take groups and track mute/solo nearby.
There is no audio render, audition or raw JSON.
See [docs/panel.md](docs/panel.md) for every screen
and the failure modes.

## Producer mode

Start the MCP server with the producer-facing tool set:

```bash
uv run enableton serve --mode produce
```

The five headline producer tools are:

- `session_brief` — maps sections, roles, density, issues and next actions.
- `reference_analyze` — measures a WAV reference, optionally against another file.
- `takes_create` — duplicates a track into named A/B takes, dry-run by default.
- `takes_select` — makes one take audible and returns fader undo tokens.
- `takes_discard` — previews take deletion; an apply requires `confirm: true` and cannot be undone.
The rest of the catalogue is available through `ableton_guide`, `ableton_inspect` and
`ableton_escalate`.

## Reference analysis extras

Basic WAV measurements work with the standard library. For integrated LUFS, spectral bands and
stereo correlation:

```bash
uv sync --extra analysis
```
If the optional packages are not installed, the report says so instead of inventing numbers.

## Safety

- Read tools never modify a Set.
- Writes use dry runs and undo tokens where the underlying command supports them.
- `.als` files are never written in place by this project.
- The take tools duplicate tracks, change faders and can delete takes; run `takes_create` and
  `takes_select` dry runs first, and use the discard confirmation deliberately.
- Audio measurements are not a listening test. Producers still make the final call.

## Tests

```bash
uv run pytest -q
```

The suite uses a fake Song.
Real-Live verification is a separate gate, reported in the project
status documents; a green fake suite is not proof that a Live behaviour works.
