# Pi harness parity audit — 8 November 2026

**Baseline:** public main `f0d22fc28d2efb9e9e4ce47239ac946287c239a1`
(26 October 2026). This document records a **source-level comparison**, not
an assertion that the private rig, the public repository, or every chat export
have identical behavior. Original private sessions and machine-specific
configuration must remain outside the public repository.

**Objective:** make portable Pi orchestration, compact attributable context,
project continuation, dynamic local inference and independent validation
reproducible without depending on one AI provider or the private rig.

## Current upstream reconciliation — 8 November 2026

The table below is the **original 26 October baseline gap audit** and is
preserved to show what prompted the subsequent work. It is no longer a list
of still-unmerged source changes. The current public state is:

- Cross-assistant recovery/handoff documentation and candidate JSON packet:
  [PR #77](https://github.com/scruge1/stuaim/pull/77),
  merged as `2ecf689`.
- Bounded, 4 KiB SHA-paginated `system_tool_query` model view and retained
  backend details: [PR #78](https://github.com/scruge1/stuaim/pull/78),
  merged as `75c4e6d`.
- Four stable Pi structured prompt sections, native project-context
  redelivery and synthetic 1,200-message append-only compaction lifecycle:
  [PR #80](https://github.com/scruge1/stuaim/pull/80),
  merged as `237cc68`.
- Opt-in explicit-root GGUF inventory and all-card read-only NVIDIA
  observation: [PR #81](https://github.com/scruge1/stuaim/pull/81),
  merged as `f891157`.

The first three changes do not prove uninterrupted *model-generated*
summarisation quality. The inventory does not implement the private dynamic
Pi selector, GPUQ reservation, model switchover or automatic worker resume.
The original private `ledgerRan` latch must not be copied into the public
owner-scoped execution guard. Complete ChatGPT conversations are still
separate from Pi session JSONLs; a personal account export is required for
verbatim recovery and has not been ingested.

Optional hashed context-size diagnostics are being qualified separately in
[PR #82](https://github.com/scruge1/stuaim/pull/82);
a draft PR must not be represented as a released public capability.
See [the current upgrade ledger](UPGRADES.md) and [issue #79](https://github.com/scruge1/stuaim/issues/79)
for remaining negative-control gates.

## Original baseline gap comparison (historical)

| Area | Public state before this update | Evidence from recent private development | Decision |
| --- | --- | --- | --- |
| Kanban reply size | Existing 12 KiB maximum, source-hash-paged projector | Exact same projector SHA-256 `a956e2bb98ce1731e198e0304fd59d1a7c0f30b920487f3d2b4d4b132413fd2a` | **ALREADY PORTED**; do not duplicate |
| System tool catalogue | Model saw the entire backend JSON | Existing bounded 4 KiB view deployed on one rig; first 50-result page fell from about 55 KiB to about 3.2 KiB while preserving full backend data and SHA-pinned cursor | **PORTED HERE** to `adapters/pi/project-workflow/system-tool-knowledge.ts` and `system-tool-query-projection.mjs` |
| Project instruction context | Source-bound, windowed `project_context`; repeated-source detection and session-compact invalidation | Named prompt sections and compaction-redelivery candidate passed four native prompt-diff checks, two Q4 turns and six isolated lifecycle checks | **CANDIDATE ONLY**; real large-session native compaction still unqualified |
| Intake/Codex/Kanban prompt sections | Some sections still concatenate strings on `before_agent_start`; public current Kanban graph differs from private rig revision | Four-source structured prompt candidate avoids repeated full-system rewrites | **GAP**: port to public semantics only after precise versioned diff and end-to-end compaction acceptance |
| Execution ledger safety | Existing enforcement, SSOT and owner checks; separate public adapter contracts | Private `ledgerRan` was session-wide, which incorrectly unlocked an unrelated later mutation in five negative controls; stricter scoped candidate passed 11 isolated tests | **GAP**: not installed; needs actual task/card binding and approved host effect checks |
| Model and GPU routing | Explicit model configuration, catalogue and measured offload helper | Dynamic model roster and hardware resource selection tested privately; current production capacity and model residency are not portable facts | **GAP**: publish a read-only planner before claiming safe allocation/preemption |
| Long-running recovery | Independent source-bound project tasks, supervised workers and resume controls | Real Pi/worker records exist; idle Drive intake, auto-dispatch and two independently accepted consecutive tasks remain unproved as a joined flow | **GAP**: require observed host receipts and negative tests |
| Rig capture/history | Existing per-harness session stores and export guidance; no cross-provider full-fidelity archive | Native Pi sessions, scoped rig recording, partially forwarded ChatGPT instructions and historical Codex/Claude stores are different datasets | **GAP**: never advertise a complete ChatGPT conversation archive without account export and inventory reconciliation |
| Local-first governance | Host-owned `tested` SSOT cap, no arbitrary model-blessed success | Local Q4 shadow research works in bounded cases; local planner/chief and automatic GPU unloading/worker return are not qualified | **NOT RELEASED** |

## Portable source implemented by this PR

The `system_tool_query` backend still returns its original source/record-hashed
result, held in tool `details`. Only the **model-facing presentation** is reduced:

- `items_offset`, `items_limit` and `expected_reply_sha256` provide bounded,
  restartable pagination with explicit stale-source rejection.
- Maximum display size defaults to 4096 bytes and source digests, rows, offset,
  coverage and recovery instructions stay visible.
- Full backend data survives in `details`; no tool-result rows are silently
  declared nonexistent because a page was clipped.
- The projector itself is SHA-pinned on Pi extension startup. Invalid source
  bytes refuse activation, and helper digest drift refuses backend execution.
- The update does **not** shrink the underlying database, affect a model's
  configured context window, grant tool execution or modify an existing Pi
  session.
- Tests are synthetic/offline for the public source. A private rig session
  exercised the corresponding predecessor, but a **clean public installed
  home** still needs its own acceptance result.

Portable controls:
`tests/test_pi_system_tool_projection.py`,
`adapters/pi/project-workflow/test-system-tool-query-projection.mjs`,
`adapters/pi/project-workflow/test-system-tool-integration.mjs`.

Run the focused check with
`python -m unittest discover -s tests -p test_pi_system_tool_projection.py -v`.
Node 22.13+ is required for the TypeScript integration control; environments
without Node skip that particular check rather than claiming it ran.

## Priorities for the next source ports

1. **Real large-session compaction:** compare exact source pins and output
   survival through an actual Pi 1.4 compact/reopen cycle, across project
   change and session branch. Preserve the task/card context and full original
   native history; evaluate retrieval and model continuation quality.
2. **Structured prompt sections:** migrate only pinned source slices from
   public-to-private diffs, preserve mid-turn intake and already admitted
   project identity, and include a drop-in older-event compatibility test.
3. **Scoped effect gate:** a previous session-wide successful check must not
   authorize an unrelated task's mutation. Use independent host/OS scope and
   same-program negative controls; do not claim the experimental guard is
   deployed.
4. **Dynamic model planner:** no implicit GPU reservation, model swap, or
   global context cap. Verify availability under concurrent subagents and
   actual KV memory, scheduling/recovery and supported backend profiles.
5. **Durable evidence reconciliation:** group Pi sessions, native tool events,
   independent verifiers, board receipts and explicitly approved ChatGPT
   handoff records without confusing a partial chat-memory summary with
   a complete original transcript archive.

These are **not** automatically accepted follow-up work orders. Each port
requires a target-scoped branch, runnable tests and release/rollback evidence.
Do not bulk-copy private paths, model weights, user prompts, API keys, log
archives, customer records or raw tool transcripts into this MIT repository.
