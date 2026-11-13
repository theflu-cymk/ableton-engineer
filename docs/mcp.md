# M5 MCP server

## Status and acceptance evidence

- **[Verified]** `enableton serve --mode sound` runs the SDK stdio transport. A standard MCP
  `ClientSession` received the selected mode's 16 catalogue tools and the four session-control
  tools `ableton_start`, `ableton_screen`, `ableton_choose`, and `ableton_inspect`.
- **[Verified]** The 16 catalogue tools match `ModeSet.get("sound").tools`; `enableton serve --mode
  list` reports `sound: 16`, matching `enableton modes`.
- **[Verified]** The four session controls are listed as session controls in MCP metadata and are
  separate from mode membership. Therefore the MCP `tools/list` total is 20 for `sound`, while its
  mode-scoped catalogue count remains 16.
- **[Verified]** The stdio flow `ableton_start` → `ableton_choose(open:modes)` →
  `ableton_choose(sound)` reaches the `mode:sound` text screen; its displayed scope remains
  `sound (16 tools)`.
- **[Verified]** `ableton_inspect` read 14 tracks from **real Live** through the MCP stdio server
  on script `0.4.20` / build `a588792a3f40`; no write was made.
- **[Verified]** `ableton_guide` with `scope="all"` and `detail="full"` returns every catalogue
  tool with its input schema, flags and mode membership, plus the composition/manual-handoff
  playbook.
- **[Verified]** An unknown `tools/call` returns `isError: true` and structured
  `UNKNOWN_COMMAND` data without ending the stdio session.
- **[Verified]** A read-only `ableton_guide` MCP call returns the same JSON as the CLI `call` for
  the same arguments in a test backed by `FakeServer`/`FakeAdapter` on an ephemeral port. The MCP
  call path invokes `tools.run_tool`.
- **[Verified]** Back navigation retains the in-memory selection and report; `ableton_status` and
  `inspect_run` results populate the main screen state.
- **[Verified]** Empty apply, recipe, and settings screens report `unavailable` with a reason
  rather than presenting fabricated Live state or actions.

## Validation

- **[Verified]** `uv run --extra dev pytest -q` — 574 passed, 63 subtests passed. The MCP tests
  use a fake adapter; the real-Live `ableton_inspect` read above is the separate gate.
- **[Verified]** `uv run --with ruff ruff check src/enableton/mcp tests/test_mcp_server.py
  tests/test_mcp_session.py tests/test_mcp_stdio.py --output-format concise` — all checks passed.
- **[Verified]** `uv run --with ruff ruff format --check src/enableton/mcp
  tests/test_mcp_server.py tests/test_mcp_session.py tests/test_mcp_stdio.py` — all six changed
  Python files are formatted.
- **[Verified]** `uv run enableton serve --mode list` reports `sound` with 16 catalogue tools.
- **[Verified]** Repository-wide `uv run --with ruff ruff check . --output-format concise` is not
  clean: it reports 753 findings; it reports none in `src/enableton/mcp/` or `tests/test_mcp_*`.
  Existing findings include lines outside the `serve` branch in `src/enableton/cli.py`.
- **[Verified]** Repository-wide `uv run --with ruff ruff format --check .` is not clean: 52 files
  would be reformatted and 29 are already formatted. The `cli.py` file was not reformatted.
- **[Verified]** No Live save was run for this work. `ableton_inspect` performed one read-only
  `tracks_list` through MCP. `recipe_show`, `recipe_save`, `recipe_apply` and `recipe_verify` are
  local tools: `recipe_apply` only stores an escalation plan, and `recipe_verify` reads the
  snapshot. A rhythm recipe with a MIDI target compiles to one `notes_replace` step; it does not
  load sample slots. On `SCRATCH fortnight`, the shipped `dubstep.half_time` changed a drum clip
  from 44 to 26 notes, and `ableton_undo` restored 44; the Set was at 120 BPM against the recipe's
  140 BPM, which the result reports as a warning. `recipe_learn`, `recipe_build` and
  `recipe_refine` remain unimplemented.

## Assumptions and open questions

- **[Assumed]** The 16-tool acceptance count refers to the mode catalogue, not all entries in MCP
  `tools/list`; the four separately marked session controls make text navigation and the read-only
  escape hatch discoverable without changing `modes.json`.
- **[Verified]** A standard MCP `ClientSession` can discover and call the session controls; other
  MCP clients have not been tested.
- **[Unverified]** MCP Apps resources, elicitation, and the local `enableton ui` fallback are not
  implemented in this server package.
- **[Unverified]** Session state is in memory for one server process; persistence across process
  restarts and user configuration are not implemented here.
- **[Unverified]** Live-derived set details depend on a successful read-only `ableton_status` call;
  screens show an explicit unavailable reason until that result exists.
