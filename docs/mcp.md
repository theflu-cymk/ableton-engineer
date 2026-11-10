# M5 MCP server

## Status and acceptance evidence

- **[Verified]** `enableton serve --mode sound` runs the SDK stdio transport. A standard MCP
  `ClientSession` received the selected mode's 14 catalogue tools and the three session-control
  tools `ableton_start`, `ableton_screen`, and `ableton_choose`.
- **[Verified]** The 14 catalogue tools match `ModeSet.get("sound").tools`; `enableton serve --mode
  list` reports `sound: 14`, matching `enableton modes`.
- **[Verified]** The three screen controls are listed as session controls in MCP metadata and are
  separate from mode membership. Therefore the MCP `tools/list` total is 17 for `sound`, while its
  mode-scoped catalogue count remains 14.
- **[Verified]** The stdio flow `ableton_start` → `ableton_choose(open:modes)` →
  `ableton_choose(sound)` reaches the `mode:sound` text screen; its displayed scope remains
  `sound (14 tools)`.
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

- **[Verified]** `uv run --extra dev pytest -q tests/test_mcp_server.py tests/test_mcp_session.py
  tests/test_mcp_stdio.py` — 10 passed.
- **[Verified]** `uv run --extra dev pytest -q` — 333 passed, 7 subtests passed. The MCP tests use
  fake/stub adapters or exercise only the local stdio screen and catalogue paths.
- **[Verified]** `uv run --with ruff ruff check src/enableton/mcp tests/test_mcp_server.py
  tests/test_mcp_session.py tests/test_mcp_stdio.py --output-format concise` — all checks passed.
- **[Verified]** `uv run --with ruff ruff format --check src/enableton/mcp
  tests/test_mcp_server.py tests/test_mcp_session.py tests/test_mcp_stdio.py` — all six changed
  Python files are formatted.
- **[Verified]** `uv run enableton serve --mode list` reports `sound` with 14 catalogue tools.
- **[Verified]** Repository-wide `uv run --with ruff ruff check . --output-format concise` is not
  clean: it reports 753 findings; it reports none in `src/enableton/mcp/` or `tests/test_mcp_*`.
  Existing findings include lines outside the `serve` branch in `src/enableton/cli.py`.
- **[Verified]** Repository-wide `uv run --with ruff ruff format --check .` is not clean: 52 files
  would be reformatted and 29 are already formatted. The `cli.py` file was not reformatted.
- **[Unverified]** No Live connection, setup, Remote Script operation, or write tool was run for
  this work. Real-Live readback and audition remain unverified.

## Assumptions and open questions

- **[Assumed]** The 14-tool acceptance count refers to the mode catalogue, not all entries in MCP
  `tools/list`; the three separately marked session controls make text navigation discoverable to
  standard MCP clients without changing `modes.json`.
- **[Verified]** A standard MCP `ClientSession` can discover and call the session controls; other
  MCP clients have not been tested.
- **[Unverified]** MCP Apps resources, elicitation, and the local `enableton ui` fallback are not
  implemented in this server package.
- **[Unverified]** Session state is in memory for one server process; persistence across process
  restarts and user configuration are not implemented here.
- **[Unverified]** Live-derived set details depend on a successful read-only `ableton_status` call;
  screens show an explicit unavailable reason until that result exists.
