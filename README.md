# Enableton

Enableton is an Ableton Live MCP server for inspecting, editing and building a Set from an AI
client. This checkout also contains the first **producer layer**: a session brief, reference
measurements and real A/B track takes.

## Status

The Live engine and the producer slice are implemented and covered by the fake suite. The product
surface is still an MCP/CLI tool, not a finished in-Live panel. See
[docs/producer-layer.md](docs/producer-layer.md) for the phased plan and explicit limits.

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

## Producer mode

Start the MCP server with the producer-facing tool set:

```bash
uv run enableton serve --mode produce
```

The three headline tools are:

- `session_brief` — maps sections, roles, density, issues and next actions.
- `reference_analyze` — measures a WAV reference, optionally against another file.
- `takes_create` — duplicates a track into named A/B takes, dry-run by default.

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
- The take tool changes track faders and duplicates tracks; run its dry run first.
- Audio measurements are not a listening test. Producers still make the final call.

## Tests

```bash
uv run pytest -q
```

The suite uses a fake Song. Real-Live verification is a separate gate, reported in the project
status documents; a green fake suite is not proof that a Live behaviour works.