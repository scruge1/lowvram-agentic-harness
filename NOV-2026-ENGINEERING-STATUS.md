# November 2026 engineering status and public upstream plan

**Recorded:** 2026-11-08
**Public baseline:** main at f0d22fc28d2efb9e9e4ce47239ac946287c239a1 (2026-10-26)
**Scope:** sanitized synthesis of current development direction, not a code
transfer or an acceptance certificate for the private system.

This document distinguishes the **public implementation**, **privately tested
candidates**, and **proposals**. Nothing described as a candidate is silently
installed by the public bootstrap. There is no claim that all private
experiments, their test suites, or their performance transfer to another host.

## Public source adoption postscript — later on 8 November 2026

This was initially a **26 October baseline** summary and proposal; the
following changes have now been committed, independently reviewed against
source and merged after full Linux/Windows offline CI:

- Cross-assistant handoff guide/JSON packet: PR #77, `2ecf689`.
- Source-pinned, bounded Pi system-tool projection: PR #78, `75c4e6d`.
- Native Pi 1.4 stable prompt sections and append-only synthetic large
  compaction lifecycle: PR #80, `237cc68`.
- Opt-in bounded GGUF and physical multi-GPU discovery: PR #81, `f891157`.

These are **public source releases**, not a claim of parity with the
installed private Pi harness or a new release of the desktop Agent Home.
Actual independent model-generated long-compaction quality, host-scoped
unattended task acceptance, dynamic GPU lease-safe loads and complete
cross-provider chat archives remain unqualified. The initial historical
table below is preserved as evidence of the gaps identified before these
merges. The latest source-level parity is in
[PI-HARNESS-PARITY-2026-11.md](PI-HARNESS-PARITY-2026-11.md).

## Primary objective

Deliver a small-footprint, **model-independent agentic workflow** capable of
long project continuity, reproducible work, explicit tool execution,
provenance-aware retrieval, failure recovery and independent verification.
Model choice is subordinate to correct work and actual hardware fit.

The portable control plane, model serving backend, agent harness, user-facing
desktop control plane and project history **must remain separable**. A local
worker may eventually assume more orchestration when it independently passes
the relevant acceptance gates; model availability alone does not grant that
authority.

## Public and private status

| Workstream | Currently public | Recent development / evidence | Upstream status |
| --- | --- | --- | --- |
| Project continuity | Git-backed projects, Pi workflow, reviewed SSOT with independent tests | Cross-assistant recovery, session export and canonical handoff procedure prepared | Documentation and candidate template in this branch; no auto-import |
| Pi context lifecycle | Native session continuation, model/tool controls, diagnostic guidance | Investigation found repeated unchanged context/tool retrieval and compaction overhead; a structured-prompt hook candidate passed syntax, a two-turn local-model case and six focused context-lifecycle checks | Candidate **not installed or qualified for unattended rollout** |
| Task results and Kanban | Existing bounded project-board tools and retained evidence | Output duplication/overly verbose board replies reviewed and selective reductions tested | Port only exact validated adapter changes with regression controls |
| Inference configuration | Hardware probing, model catalog and explicit CPU/MoE offload autotuning | Workload-aware consideration of one/multiple GPUs, context and KV-cache budgets, loaded-model state, concurrent subagents and backend alternatives | Read-only planning candidate outside this repo; no automatic GPU allocation |
| Long-context work | Explicit selected-model context, independent execution checks | High-context local agent workflows under test; compaction/retrieval accuracy is more important than advertised maximum context | Needs target-specific long-session replay and quality tests |
| Desktop product | Command-line Pi home is current entry point | User-facing app direction: chat first, history, project boards, settings, plugins, file explorer and readable model controls | Separate product in development, **not** claimed as shipped here |
| Streaming/always-on services | Existing process/latency diagnostics and lifecycle guards | Investigating RAM, persistent service footprint, idle/wakeable inference rigs and possible implementation alternatives | Measure first. No Rust rewrite or performance improvement claimed |
| Local orchestration | Portable SSOT reaches local tested under independent acceptance | Long-term objective is dynamic loading of larger open-weight models for strategic oversight and then releasing GPUs to workers | No autonomous local leadership released; external supervision remains where required |

Private qualification results must be re-run with **exact source pins,
configuration, model identity and negative controls** before they become public
implementation claims. A proposed architecture or exploratory benchmark is
not runtime acceptance. Existing draft pull requests also need their own
merge and adoption reviews.

## 1. Context and Pi session efficiency

The target is not simply 'more tokens'. Context sent to the model should be
relevant, attributable and stable across compaction.

- Retrieve unchanged material once, retain source identity, and avoid reprinting
  the same large instruction/board/catalog chunks on every tool call.
- Treat saved session data as **historical evidence**. Distill reviewed project
  decisions into project-owned files; do not let a transcript summary redefine
  architecture, task authority or acceptance.
- Record pre-/post-compaction recovery quality, instruction survival,
  tool-call correctness, elapsed time, input/output token usage and loss of
  important constraints.
- Test actual multi-turn project work with real harness hooks and native tool
  results, not just isolated prompt formatting or synthetic model replies.
- Reject stale context or missing source pins when those could invalidate an
  action. Avoid arbitrary short session durations that interrupt useful work.

**Gate to upstream:** pinned adapter source; documented hook lifecycle and
reload path; unchanged-data deduplication controls; compaction reconstruction;
conflict tests; rollback; live task evidence with stable outputs. Candidate
tests alone cannot bypass this gate.

## 2. Inference, VRAM and model selection

A model's nominal parameter count or configured context window is not enough
to choose a deployment. Evaluate model weights (including quantization),
available GPU and system memory, KV cache at the **actual** context, compute
and PCIe costs, active requests, subagent concurrency and backend behaviour.

- Preserve a **backend-agnostic** capability description. Distinguish serving
  API compatibility from model quality and tool-calling reliability.
- Compare one GPU, multiple GPUs and CPU/MoE offload through *measured*
  throughput, latency, memory use, stability and real task success.
- Reserve memory for the system, framework, KV cache, tools and concurrent
  agents. The largest model that loads is often not the best workflow.
- Let a resource planner be **read-only** until the active owner can acquire
  and release hardware safely and demonstrate rollback without interrupting
  other workers.
- Do not hardcode a single model, quantization or 64K/128K/256K claim as
  universally suitable. Publish task profiles and concrete model revisions
  only after reproducible measurement.

**Gate to upstream:** reproducible hardware/model manifest, pinned backend
build, memory traces, exact context usage, tool-calling tests and verified
tasks/hour on the target profile. No claim that an experimental private GPU
planner is available in the public installer.

## 3. Long-running processes and local-first control

The aim is economical, recoverable, long-duration task execution—not an
unbounded process detached from oversight.

- Keep lightweight, persistent control services separate from optional
  heavyweight inference GPU reservations.
- Before rewriting a streaming service in Rust or another language, measure
  its real steady-state RSS, allocator behaviour, event-loop/CPU load,
  reconnects, transport buffering and end-to-end latency.
- Model cold starts, sleeping rigs and degraded resources explicitly; failure
  to wake a device must not silently bypass an agent's acceptance contract.
- Maintain independent completion authority: logs, model confidence, board
  state and cached answers are not success receipts.

**Gate to upstream:** baseline and post-change measurements on the same
workload, memory and latency regression tests, failure injection, clean stop
and restart, and evidence-preserving recovery.

## 4. Cross-assistant portability

See [CROSS-ASSISTANT-CONTINUITY.md](CROSS-ASSISTANT-CONTINUITY.md) and
[examples/continuity/handoff.template.json](examples/continuity/handoff.template.json).
The immediate public contribution is an explicit migration procedure for
Gemini CLI, Code Assist and Gemini Apps exports, followed by reviewed project
context and independent checks. Exporting transcripts is **not** equivalent to
restoring project authority or importing live sessions across products.

## 5. Next publication sequence

1. **Documentation:** review this ledger, portable continuity procedure and
   candidate handoff template. Confirm no private session bodies, credentials,
   paths or internal source identifiers escaped. This is the current PR scope.
2. **Pi hook port:** isolate the minimal tested changes from the private
   candidate, retain source provenance in the private workzone, recreate
   portable tests and check a clean installed public home before merging.
3. **Resource planner:** publish only read-only capability/profiling contracts
   first. Defer allocation, preemption and model cold-swapping until owner and
   lease safety tests pass.
4. **Real cross-assistant pilot:** have another assistant reconstruct one
   pinned open-source example, run a reviewed task and obtain independent
   acceptance. Record failures and correction cost as well as success.
5. **Separate UI release:** qualify navigation, project persistence, settings,
   permissions and file operations without exposing unfinished private
   desktop components as installed features.

This public project remains in early development. The current Linux x86_64
bootstrap has the broadest support; Windows and macOS are explicitly smaller
direct-install routes. See [GETTING-STARTED.md](GETTING-STARTED.md) and
[RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md). No status in this file modifies
those support boundaries.
