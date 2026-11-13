# Product decision log

**Status:** integration draft. This file records decisions and owner inputs; it does **not** infer
approval. A decision is only approved when the owner/date/evidence columns say so.

**Status values:** Accepted (project constraint or explicitly approved), Proposed (recommended,
needs owner), Open (needs information), Blocked (external input required).

## Current decisions

| ID | Decision | Status | Owner / date | Evidence or consequence |
|---|---|---|---|---|
| D-01 | `SPEC.md` owns technical design; `AGENTS.md` owns safety conventions; `MISSION.md` owns historical sequencing but its status lines and counts can lag this tree. This pack owns the current product/release interpretation until the owner updates MISSION. | **Accepted for this pack** | Project convention | Do not silently reconcile a conflict; record it here. |
| D-02 | Keep the custom Enableton Python server + custom Remote Script as the base. Do not migrate the MVP to the external `mcp-server-ableton-live` package. | **Proposed** | Engineering/product owner | The current engine has real-Live gates; migration would discard them. External docs describe another codebase. |
| D-03 | MVP shape is a technical MCP server with a producer-facing `produce` mode; the local panel is an additive loopback surface, not a replacement engine. | **Proposed** | Product owner | The stdio server remains the engine. The panel is implemented and covered by D-18. |
| D-04 | Producer experience uses three verbs: Analyze, Suggest, Create take. The 89-tool catalogue is engine vocabulary, not the primary menu. | **Proposed** | Product owner | `produce` mode exists; `session_brief`, `reference_analyze`, `takes_create`, `takes_select` and `takes_discard` are the current slice. |
| D-05 | “Suggest” means evidence-backed next actions and measured deltas, not autonomous generation or a hidden LLM. | **Accepted direction** | Product/engineering | `session_brief.next_actions` and reference deltas are current examples. |
| D-06 | `takes_create` v0 uses real duplicate tracks and fader-based A/B; takes are identical until edited. | **Accepted for slice** | Engineering | Real dry-run, two-take panel apply, fader A/B and undo verified on a scratch Set. |
| D-07 | Reference analysis reports measurements and unavailable values; it never claims an audition or mastery. | **Accepted** | Engineering | Real WAV measurement verified; limitations are explicit in the tool. |
| D-08 | No user `.als` is written in place; writes use dry runs, scratch copies and undo where available. | **Accepted invariant** | Project convention | AGENTS and existing executor/scratch code. |
| D-09 | No LLM runs inside the server; the MCP client supplies intelligence. | **Accepted** | `SPEC.md` | Tool server exposes vocabulary and data only. |
| D-10 | The first release is a consented one-user beta before any public availability. | **Open** | Product owner | From external release pack; no beta has run. |
| D-11 | Supported Live editions/versions, OS versions and MCP client versions must be explicitly tested and recorded. | **Open** | Product + engineering | Current evidence is Windows Live 12.2.5 plus an unspecified MCP host; not a matrix. |
| D-12 | Default local bridge port remains 9878 until a configuration/port decision is implemented and tested. | **Proposed** | Engineering | Current verified port; external docs' 9877 does not apply. |
| D-13 | Legal terms, privacy, refund policy and support contact are owner-supplied release blockers. | **Blocked** | Product/legal/support | No LICENSE/EULA/privacy/refund/support asset in this checkout. Do not invent. |
| D-14 | Package and installed Remote Script versions remain separately identified; do not claim one equals the other. | **Open** | Release owner | Package `0.1.0`, script `0.4.26`. External checklist asks for a consistent product version; decide the scheme. |
| D-15 | A real producer workflow demo is an external release deliverable, not code. | **Open** | Marketing/product | No demo video; must use consented material. |
| D-16 | Product naming: keep `Enableton` in code/docs for now; decide the public “EnAbleton” spelling separately. | **Proposed** | Product owner | External pack uses EnAbleton; current package is Enableton. |
| D-17 | Take variation and session memory are post-slice features; select has a panel control and discard is panel preview-only. | **Accepted scope** | Engineering | Select/discard are in the manifest and have real scratch-Set evidence; variation and memory are absent. |
| D-18 | Add a local, loopback-only producer panel over the same bridge: status, session brief, tracks with safe row actions, dry-run/apply composer, take Select and preview-only discard. It adds no dependency and exposes no destructive Apply path. | **Accepted for this build** | Owner brief, 2026-11-13 | Panel implementation, fake suite, real scratch-Set mute, take apply/A-B, panel select/undo and confirmed discard preview. |

## Mapping to the external owner inputs

The Supreme Potato pack's D-1…D-11 remain the commercial checklist. This is the reconciled mapping:

| External | Local decision | Current reconciliation |
|---|---|---|
| D-1 product shape | D-03/D-18 | Producer-facing MCP mode plus the additive local panel; the owner still needs to approve the release shape. |
| D-2 supported matrix | D-11 | Still open. Do not claim broad compatibility. |
| D-3 port behavior | D-12 | Current port 9878; port selection is not a shipped UX. |
| D-4 release channel | D-10 | Recommend one-user beta; no beta has run. |
| D-5 legal terms | D-13 | Blocked; no legal assets. |
| D-6 privacy/data | D-13 | Blocked; audit optional external data flows before copy. |
| D-7 support/refund | D-13 | Blocked; no contact or terms. |
| D-8 workflow owners/proof | D-04/D-05 | Current producer slice has evidence; three release workflows still need full records. |
| D-9 save/copy/backup | D-08 | Scratch/undo exists; product save flow and retention policy remain open. |
| D-10 demo video | D-15 | Open; no video. |
| D-11 version/labeling | D-14 | Open; package and script versions differ by design today. |

## Decision protocol

1. Record the decision, owner, date, evidence and effect on `PRD.md`/`ROADMAP.md`.
2. Do not treat a recommendation as approved.
3. If a decision changes product shape, scope, safety or a release claim, stop and get owner
   confirmation before writing code.
4. If a legal/privacy/support input is missing, mark the release blocked; do not draft a substitute
   policy.
5. Re-check this log when a stale MISSION/AGENTS statement conflicts with the current tree.

## Immediate decisions needed

- Approve or reject D-02/D-03: custom Enableton MCP with producer mode as the MVP.
- Name and audience: Enableton vs EnAbleton; one-user beta vs public launch.
- Supported matrix and port behavior.
- Confirm the additive panel's release shape (D-18 is accepted for this build, not yet a release
  commitment).
- Version scheme for package and Remote Script.
- Legal/privacy/support owners and inputs.
