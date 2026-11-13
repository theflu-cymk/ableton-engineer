# Agent workstreams and integration plan

**Status:** proposed operating plan, 2026-11-12. Read [HANDOFF.md](HANDOFF.md) first.
**Assumption:** four agents total, including one integrator. If only three agents are available, fold
A3 into A0; do not drop A1 or A2.

The goal is to finish the producer MVP **together** without two agents editing the same hot file,
without two agents driving Live at once, and without an unreviewed branch becoming the release.

## 1. Roster

| Agent | Role | Branch | Primary outcome |
|---|---|---|---|
| **A0** | Integrator / release captain | `integration/producer-mvp` | Clean baseline, shared-file ownership, merge queue, release evidence |
| **A1** | Producer core | `feat/producer-core` | Finish take workflow: select, discard, variation, real scratch-Set gate |
| **A2** | Live / audio | `feat/live-audio` | Fix capture restore/size behavior; own Remote Script and real audio gate |
| **A3** | Setup / release / UX | `feat/setup-release` | Setup, compatibility, client config, producer-readable docs/release gates |

A0 is a role, not a fifth agent. The product owner remains the human owner; agents do not approve
D-xx decisions or release claims.

## 2. Ownership matrix

### Owned exclusively

| Path | Owner | Rule |
|---|---|---|
| `src/enableton/producer.py`, `takes.py`, `reference.py` | A1 | A1 only; A0 reviews |
| `src/enableton/tools.json`, `modes.json` | A0 | Single writer; workers request entries |
| `src/enableton/tools.py` | A0 | A1 proposes producer dispatch changes; A0 lands them |
| `src/enableton/mcp/transport.py`, `mcp/session.py`, `tui.py` | A3 | A0 reviews; A1/A2 do not edit |
| `src/enableton/setup.py`, `cli.py` | A3 | A0 reviews |
| `remote_script/Enableton/**` | A2 | A2 only; four-step install/restart/doctor gate |
| `docs/M6_M7_STATUS.md` | A2 | A2's own audio/capture evidence ledger |
| `tests/test_producer_layer.py` | A1 | A1 may add; A0 can add contracts |
| `tests/test_capture*` | A2 | A2 only |
| `tests/test_manifest.py`, `tests/test_modes.py` | A0 | Catalogue/mode contracts; workers request |
| `tests/test_cli.py` | A3 | CLI behavior; A0 reviews |
| `docs/product/**` | A3 | A0 may edit this file and the index only |
| `src/enableton/live/fake.py` | A0 | Shared fake behavior; workers request changes |
| `README.md` | A3 | A0 can request a link update |
| `AGENTS.md`, `SPEC.md`, `MISSION.md` | Human owner + A0 | Do not rewrite; record drift |

### Shared hot spots

These files are conflict magnets. **Only the named owner commits to them**, even if another agent
needs a change:

| Hot spot | Owner | Worker protocol |
|---|---|---|
| `src/enableton/tools.json` | A0 | A1/A2/A3 put exact tool JSON and mode row in the PR body; A0 applies |
| `src/enableton/modes.json` | A0 | Same; A0 applies after the feature exists |
| `src/enableton/tools.py` | A0 | A1 supplies handler/import diff; A0 applies |
| `src/enableton/mcp/transport.py` | A3 | A0 reviews; no parallel edit |
| `src/enableton/live/fake.py` | A0 | A1/A2 request fake changes; no parallel edit |
| `remote_script/Enableton/server.py` | A2 | A2 owns version bump; no one else edits |
| `README.md`, `docs/product/**` | A3 | A0 can edit index/handoff; A1/A2 send evidence text |
| `uv.lock`, `pyproject.toml` | A0 | Dependency changes require an approved reason |

**No two open PRs may touch the same hot spot at the same time.** A0 merges one, then asks the next
worker to rebase. This is slower than parallel editing and much cheaper than resolving a broken
manifest or a half-merged Remote Script.

## 3. Contract freeze before coding

A0 writes a short contract note in the integration branch before feature work begins. The exact
signatures are product/engineering decisions, but the boundaries should be frozen:

| Contract | Owner | Minimum shape |
|---|---|---|
| `takes_select` | A1 | Explicit `takes` list plus `active` take name or 1-based number; optional `volume` (defaults to the loudest positive fader, or 0.85 when the group is silent); dry-run by default; apply lowers the other takes to 0 and returns fader undo |
| `takes_discard` | A1 | Delete a selected take; explicit confirmation; irreversible unless a safe trash path exists |
| take variation | A1 | Bounded, reversible, real MIDI/audio/device change; no fake “variation” flag |
| session memory | A1 | Local JSON outside the `.als`; goal, decisions, accepted take, resume text |
| capture restore | A2 | No route left on `Resampling`; fallback to `No Input` when exact value is unavailable |
| capture size wait | A2 | Stable file size before returning; no premature `file_bytes` |
| setup/doctor/compat | A3 | No direct main-path writes; fail closed on unsupported versions |
| client config | A3 | Generated from actual install path; no hardcoded user path in the repo |

If a contract changes after coding starts, A0 updates the note and all affected agents rebase before
continuing. Do not discover an interface difference during integration.

## 4. Branch and worktree bootstrap

The current tree is **dirty**. A0 must first create the baseline, then create integration and worker
branches.

### A0: baseline once

```bash
git switch main
git status --short
git diff
git add <reviewed files>          # exclude tmp/, user .als, .venv, secrets
git commit -m "chore: baseline producer workflow and product handoff"
git push origin main             # owner-authorized only

git switch -c integration/producer-mvp origin/main
git push -u origin integration/producer-mvp
```

If the owner wants the baseline split into smaller commits, do that before creating the integration
branch. Do not start four workers from a mystery diff.

The local branches `m4-offline-accounting-5317737`, `m5-serve` and
`theflu-cymk-m6-audio-tools` are historical. Do not base the new work on them unless A0 explicitly
confirms a needed commit. `origin/main` is the base.

### A1/A2/A3: one worktree and branch each

Do not let two agents share one checkout. Use separate Git worktrees so branches, `.venv`, caches and
Live state do not collide.

```bash
git fetch origin
git worktree add ../enableton-a1 -b feat/producer-core origin/integration/producer-mvp
git worktree add ../enableton-a2 -b feat/live-audio origin/integration/producer-mvp
git worktree add ../enableton-a3 -b feat/setup-release origin/integration/producer-mvp

# In each worktree:
uv sync --extra dev --extra analysis
```

A0 works in a fourth worktree/branch for `integration/producer-mvp` or directly on that branch from a
clean checkout. Use `git worktree list` and remove a worktree only after its PR is merged.

Each agent has its own:
- working directory and branch;
- `uv` environment;
- terminal session;
- PR number and review thread.

No agent runs `git add -A` across the repo; stage only files it owns. Never commit `tmp/`,
`.venv/`, `.pytest_cache/`, `__pycache__/`, `.als` files, recorded WAVs, logs, credentials, `.env`
files or private reports. The current `tmp/` directory is scratch.

## 5. Check-in protocol

### Commit shape

Use small commits with a scope:

```text
feat(producer): add takes_select and take state readback
fix(capture): restore routing with No Input fallback
test(producer): cover discard confirmation and undo
docs(product): record take gate evidence
chore(integration): register producer tools and modes
```

One logical change per commit. Tests and the code they cover stay together. Do not mix formatting,
renames, generated files and behavior in one commit.

### Required checks before every PR

```bash
uv run pytest -q
git diff --check
```

Add when relevant:

```bash
uv run enableton doctor
uv run enableton status --json
uv run enableton call <tool> --json --args '<safe args>'
```

For a Remote Script change, the **four-step gate is mandatory**:

1. bump `SCRIPT_VERSION` in `remote_script/Enableton/server.py`;
2. `uv run enableton setup --force`;
3. restart Live;
4. `uv run enableton doctor` — version and build digest match, no `stale`.

A green fake suite is not a substitute. State exactly what was tested against the fake and what was
tested against real Live.

### PR rules

- Open a **draft PR early** so the other agents can see the contract.
- Target `integration/producer-mvp`, never `main` directly.
- One feature per PR; target less than roughly 400 changed lines when practical.
- Do not edit a file outside your ownership matrix. If you must, request the owner's change in the PR.
- Include the exact commands and results.
- Include a **Not verified** section. It is required, not embarrassing.
- Rebase on `origin/integration/producer-mvp` before asking for review:
  ```bash
  git fetch origin
  git rebase origin/integration/producer-mvp
  git push --force-with-lease
  ```
  Never force-push another agent's branch. Never rewrite a branch after A0 has started a merge
  unless A0 asks.
- A0 reviews the contract, shared-file impact and evidence; A0 is the only merger.

### PR body template

```markdown
## What changed
- ...

## Ownership
- Files owned:
- Shared files requested (A0 to apply):

## Contract
- New/changed tool or API:
- Backward compatibility:

## Evidence
- Fake tests:
- Real-Live call (command, Set/scratch path, build, result):
- Audition (yes/no; if no, say so):

## Safety
- Scratch copy:
- Undo/rollback:
- Working Set untouched:

## Not verified
- ...

## Risk / rollback
- ...
```

## 6. Real-Live serialization

There is one Live bridge on port `9878` and one main thread. Agents can write code and run fake tests
in parallel, but **only one agent may drive Live at a time**.

A0 owns the gate token. Before a real write:

1. Request the token from A0 in the PR/thread.
2. Confirm the Set path and that it is a **scratch copy**.
3. Record build, script version, commands, before state and after state.
4. Run only that workstream's write.
5. Restore/stop and release the token.

Rules:

- A1 may run `session_brief` and `reference_analyze` without a write token; file analysis is offline.
- A1 needs the token for `takes_create` apply, A/B and undo.
- A2 needs the token for any capture/meter/audio write.
- A3 never writes Live; setup/docs are offline.
- No two agents restart Live or run `setup --force` at the same time.
- A2's Remote Script restart invalidates every other agent's connection assumptions; A0 pauses the
  queue until `doctor` is clean.
- A0 records the gate in `RELEASE_READINESS.md` or the integration PR, including the scratch path and
  what was not auditioned.

## 7. Sprint and merge sequence

No dates until the owner approves scope. Use gates.

### Sprint 0 — baseline and contracts

- A0: baseline commit, integration branch, branch protection, ownership matrix, contract note.
- A1/A2/A3: read the pack, propose contracts, inspect their owned files.
- No feature code merged until the baseline and contracts exist.

**Gate:** clean integration branch; full fake suite and `doctor`/`status` recorded.

### Sprint 1 — parallel implementation

- **A1:** `takes_select` and `takes_discard` are implemented and passed a real scratch-Set gate;
  next is one bounded variation with fake tests and a separate real gate.
- **A2:** capture restore fallback and size stability; Remote Script `0.4.27`; fake tests; then one
  serialized real capture.
- **A3:** setup/doctor/compat/client-config design and implementation; no Live writes.
- **A0:** merge queue, manifest registrations, full-suite checks, docs index.

**Gate:** each branch passes its own fake tests and has a reviewable PR; no hot-spot collision.

### Sprint 2 — integration and real acceptance

- A0 merges A1, then A2, then A3 (or another order if dependencies demand), registering manifests in
  the integration branch.
- A1 runs the real scratch take apply/A-B/undo gate.
- A2 runs the real capture/restore gate.
- A3 runs the clean-machine setup/doctor/client check from a fresh location.
- A0 runs the full suite, `git diff --check`, `doctor`, `status` and records evidence.

**Gate:** one integration SHA; all three real gates recorded; no working Set modified.

### Sprint 3 — release candidate

- A1: reference/capture producer flow or session-memory slice, only if the take loop is green.
- A2: final capture evidence and any remaining audio limitation.
- A3: release materials, compatibility matrix, legal/support blockers (owner-supplied only).
- A0: release candidate, evidence review, beta go/no-go.

**Gate:** release checklist has no unchecked code-evidence item; owner/legal/support/beta items are
explicitly open or signed.

## 8. Merge order and conflict rules

Recommended order:

1. **A1 producer core** — no Remote Script change; A0 registers tools.
2. **A2 live/audio** — Remote Script; install/restart/doctor; serialized real gate.
3. **A3 setup/release** — docs/setup/UX; no Live writes.
4. **A0 integration → main** — only after the full acceptance.

If A1 needs a capture behavior from A2, merge the smallest A2 contract first; do not merge a
half-finished capture branch just to unblock A1.

Conflict rules:

- A0 resolves shared-file conflicts; the worker does not “win” by rebasing a hot spot.
- Rebase worker branch onto integration after each A0 merge.
- If a conflict touches a contract, stop and update the contract before resolving.
- Do not merge `main` into a feature branch; rebase.
- Do not squash two agents' work into one anonymous commit; preserve authorship.
- Integration to main uses a reviewed merge/squash with a release note naming the gates.

## 9. Per-agent acceptance

### A0 — integrator

- Clean baseline commit, protected `main`, integration branch.
- No direct feature changes outside shared files.
- Full suite and `git diff --check` after every merge.
- Shared manifests registered only after code exists.
- Real Live gate token log and release evidence.
- Final integration SHA and release note.

### A1 — producer core

- **[Done]** `takes_select` / `takes_discard` behavior, fake tests and real scratch-Set select/undo
  and confirmed discard.
- One real variation, not an alias for identical duplicates.
- Real scratch-Set apply/A-B/undo.
- Exact evidence, including the `takes_create` dry-run and apply.
- No user `.als` write.

### A2 — live/audio

- Capture restore fallback and size-stability behavior.
- `SCRIPT_VERSION` bump, forced install, Live restart, matching `doctor` build.
- Real capture with WAV verification and no leftover `Resampling` route.
- No unrelated Remote Script handlers changed.

### A3 — setup/release

- Setup/doctor/compatibility/client config behavior, with no invented legal/support text.
- Clean-machine transcript and no song modification.
- Release docs traceable to evidence; stale claims removed.
- No Live writes.

## 10. Stop conditions

Stop and ask the human owner if:

- a product-shape, supported-matrix, legal, privacy, support or release-channel decision is needed;
- a write would touch a working Set, a source WAV or a user's media;
- the Remote Script build does not match `doctor`;
- a shared hot spot has two open PRs;
- a real-Live gate cannot be serialized;
- a test or gate fails in a way that is not understood;
- an agent is asked to claim audition, compatibility or release readiness without evidence.

Do not “fix” a blocker by weakening a test, inventing a policy, or applying a write to make a demo.

## 11. Copy-paste agent prompts

### A0

```text
You are A0, integrator/release captain for Enableton. Read docs/product/README.md,
docs/product/HANDOFF.md, docs/product/CURRENT_STATE.md, docs/product/AGENT_WORKSTREAMS.md,
SPEC.md and AGENTS.md. The tree is dirty; establish and commit a clean baseline before
creating integration/producer-mvp. You own tools.json, modes.json, tools.py, the merge
queue and the real-Live gate token. Do not write feature code outside shared files. Review
each worker PR for ownership, tests and evidence; merge A1, A2, A3 in a controlled order;
run full suite/doctor/status after each merge; record every real-Live gate and every
not-verified item. Never push main until the owner approves the release candidate.
```

### A1

```text
You are A1, producer core. Work in your own worktree on feat/producer-core, based on
origin/integration/producer-mvp. Read docs/product/AGENT_WORKSTREAMS.md and
docs/producer-layer.md. Own producer.py, takes.py, reference.py and
tests/test_producer_layer.py. Do not edit tools.json, modes.json, tools.py, the Remote
Script or docs/product. takes_select and takes_discard are already implemented and have a real
scratch-Set gate; do not redo them. Implement one real bounded variation, with fake tests
first. Request manifest registration from A0 with exact JSON. Do not apply a real write until
A0 grants the Live gate token and you have a backed-up scratch Set. Record what you did not
verify, especially audition.
```

### A2

```text
You are A2, live/audio. Work in your own worktree on feat/live-audio, based on
origin/integration/producer-mvp. Read docs/product/AGENT_WORKSTREAMS.md,
docs/M6_M7_STATUS.md, AGENTS.md and docs/troubleshooting.md. You own
remote_script/Enableton/** and capture tests. Fix the resample routing restore and
file-size stabilization; bump SCRIPT_VERSION, run setup --force, restart Live and require
doctor to show the matching build and zero errors. Request the Live gate token from A0;
use only a backed-up scratch Set. Do not touch producer files, shared manifests or docs
outside your evidence note. Do not claim exact restore until it is verified.
```

### A3

```text
You are A3, setup/release/UX. Work in your own worktree on feat/setup-release, based on
origin/integration/producer-mvp. Read docs/product/AGENT_WORKSTREAMS.md and the product
pack. Own setup.py, cli.py, mcp/session.py, mcp/transport.py, tui.py, README.md and
docs/product/** except this file/index updates owned by A0. Do not edit producer code,
shared manifests or the Remote Script. Build setup/diagnostics/compatibility/client
configuration and release materials. Do not invent legal, privacy, support or refund
text. Do not write Live. Record evidence with Verified/Assumed/Unverified.
```

## 12. Definition of a perfect handoff

The tree is ready to hand to the next team only when:

- `main` is clean and the integration branch is at a known SHA;
- every open PR has an owner, a contract and a “not verified” line;
- A0 has a merge queue and a real-Live token log;
- the take apply/A-B/undo gate has a named command and scratch path;
- the capture restore gate has a named build and WAV;
- setup has a clean-machine transcript;
- release blockers are explicitly owner/legal/support items, not hidden assumptions;
- `CURRENT_STATE.md`, `RELEASE_READINESS.md` and the PR evidence agree;
- no agent is working directly in another agent's worktree or on `main`.

If any item is false, the handoff is a **work-in-progress**, not a release.
