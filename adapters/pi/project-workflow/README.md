# Pi Project Workflow

This directory contains the portable Pi coordinator layer qualified by the
project-lifecycle controls. It adds project identity, a project-local Hermes
board, capability discovery, project knowledge retrieval, external planning
advice, applicable hierarchical project context, supervised file changes,
closeout records, and project-local skill
candidates. It also compiles project-local memory claim candidates from exact
MemPalace readbacks without promoting them into shared recall.

The components preserve separate authority boundaries:

- Board state is workflow state only.
- Knowledge results are retrieval guidance only.
- Codex responses are planning advice only.
- `workflow_step` proves only its supplied predicate.
- A closeout or skill candidate is guidance only.
- A memory claim candidate is guidance only until a separate promotion path
  verifies the live source and accepts it into a reviewed registry.
- Model output cannot promote itself, approve physical actions, or create SSOT
  authority.

## Runtime Dependencies

- Pi coding agent1.4.0 with the qualified extension and project-context APIs.
- Python 3.9 or newer for the portable supervisor components.
- A dedicated Python environment containing `hermes-agent` 0.21.1 from commit
  `866332bfb52c46e543143b2620a9aeee8bce9c77` for `pi_kanban.py`.
- The reviewed portable task runtime from this repository or an equivalent
  runtime with a pinned manifest and `harness/enforcement.py` hash.
- Optional sessionless Codex wrappers for `codex-plan-consult.ts`. The wrapper
  contract is external to this package. Pi must treat its result as advice.

`pi_kanban.py` also checks the exact source hashes of the three Hermes modules it
uses. A different Hermes build fails closed until it receives an independent
review and the pins are deliberately updated.

## Install

For a fresh home, use the repository's [agent-home installer](../../../AGENT-HOME.md).
It asks for the destination and local model, installs the selected dependencies,
and creates the target-specific bindings. Normal setup uses:

```bash
python -m harness.home install --profile full --python312 /path/to/python3.12
```

The manual bindings below describe this coordinator. A complete installation
also retains the sibling `../intake/` and `../context/` directories and the
generated Framework binding. Copying only `pi-kanban.ts` loses required imports.

Copy the files to one trusted directory on the Pi host. Copy these extensions
to the Pi extension directory, or link them from the trusted directory:

- `agent-capabilities.ts`
- `everyday-workflow.ts`
- `pi-kanban.ts`

`codex-plan-consult.ts` is optional. Install it only when a separate planning
adviser is wanted and its wrappers are configured. The coordinator can select
and execute owner-authorized work without this adviser.

Keep the Python helpers together. `pi_kanban.py` resolves
`init_workspace.py` beside itself. The other project helpers are imported from
the same directory.

Create `everyday-runtime.json` beside `everyday-workflow.ts` from
`everyday-runtime.example.json`. Replace every placeholder with an absolute
path or a lowercase SHA-256. The extension rejects helper or runtime drift.

Set these variables in the Pi process environment:

```text
PI_PROJECT_KANBAN_PYTHON=/absolute/path/to/hermes-python
PI_PROJECT_KANBAN_ADAPTER=/absolute/path/to/pi_kanban.py
PI_PROJECT_KANBAN_ADAPTER_SHA256=<sha256 of pi_kanban.py>
PI_PROJECT_STATE_BASE=/absolute/path/to/project-state
PI_PROJECT_CONTEXT_PI_PACKAGE=/absolute/path/to/pi-coding-agent-package
PI_CODING_AGENT_DIR=/absolute/path/to/agent-profile
PI_CODEX_PYTHON=/absolute/path/to/python3
PI_CODEX_PLAN_WRAPPER=/absolute/path/to/codex_plan_consult.py
PI_CODEX_CAPABILITY_WRAPPER=/absolute/path/to/codex_capability_setup.py
```

`PI_PROJECT_STATE_BASE` and `PI_CODEX_PYTHON` are optional. Their defaults are
`~/.local/state/pi-projects` and `python3`. The `PI_CODEX_*` bindings apply only
to the optional adviser. The other Kanban bindings are required.
Missing paths or mismatched hashes fail closed. Do not put credentials in these
files or variables.

The context package binding selects the exact installed Pi1.4.0 package, with
source pins for its two internal native APIs. See the
[context binding contract](../context/README.md). The agent-home installer sets
the profile directory. Standalone context use follows Pi's normal user-profile
default if `PI_CODING_AGENT_DIR` is absent. Intake has its own
[Framework/runtime bindings](../intake/README.md).

Reload Pi after changing extension bytes or process environment. Use
`agent_capabilities` to confirm the configured and active tool registry. That
observation proves registration only, not tool health.

## Intended Flow

The supplied verifier must return 0 when declared outputs satisfy its predicate
and 1 when they do not. It must read outputs relative to its current working
directory. Its executable and script must remain available when run in the empty
negative-control directory, for example through absolute paths. Other exit codes,
including Python's missing-script exit 2, do not qualify as predicate rejection.
This exit contract rejects unexpected failures; it does not prove that an arbitrary
program's exit 1 has the intended semantic cause. Review the predicate and its
negative evidence separately. Existing installations need an owner-reviewed helper
hash update; changing public source does not activate this correction.

1. Call `project_admit` for the exact project root.
2. Call `project_context` for the relevant directory. Read remaining windows
   until the applicable sources have been delivered to a later model-input
   context. A completed tool call in the same batch is insufficient.
3. Call `agent_capabilities` and save its project-bound snapshot.
4. Query `system_tool_query` for relevant system capabilities.
5. Search local Pi MemPalace for validated lessons and recent session history.
   Use a separately configured system palace for wider implementation history.
6. Query project knowledge before planning.
7. Reuse the relevant existing card with `kanban_select`, or create a bounded
   card with `kanban_create` when the owner request requires new work. Creating
   another card preserves an existing selection. Draft a plan for that card.
8. Use `codex_plan_consult` only when useful or requested. Apply its critique
   as advice. Keep user authority and local capability separate from the adviser.
9. Execute each mutation through `workflow_step` or another reviewed supervisor.
10. Attach the verified receipt to the same card and use valid Hermes state
   transitions.
11. Prepare closeout, rebuild project knowledge, and persist validated lessons
   through an independently configured memory route.
12. Read the stored MemPalace drawer back exactly. Use
   `project_memory_candidate_prepare` to bind the verified closeout to that
   drawer. The immutable candidate is written under
   `.icm/workspace/wiki/memory-candidates/`, which the existing project index
   already includes. Reject source drift and sensitive summary text.
13. Compile a project-local skill candidate only from a verified closeout. Shared
   installation remains a separate review and promotion action.

`tool_knowledge.py` builds a hash-bound SQLite FTS catalog from maintained JSONL
capability registries. `system-tool-knowledge.ts` exposes read-only query and
status tools. Configure `PI_SYSTEM_TOOL_HELPER`, `PI_SYSTEM_TOOL_DATABASE`, and
`PI_SYSTEM_TOOL_HELPER_SHA256`. Catalog results are retrieval guidance. They do
not prove that a tool is installed, loaded, healthy, or authorized.

`resource_status({})` and `/resource-status` read only the current `AGENT_HOME`.
The loaded capability adapter and Python helper must match that home's source
manifest. The helper uses the existing shared lifecycle consumer and owned
model-service status checks. It never starts, stops, downloads or reserves a
model. Existing resource-wait IDs stay unchanged; use `kanban_intake_status` for
their original reason, trigger and receipt. A status read earns no progress.

Host RAM and CPU affinity are snapshots, not exclusive allocations or model-fit
proof. Attached endpoint configuration does not prove service ownership. Busy
state and request queue length remain unknown. New GPU starts stay held by the
existing admission rule. Retained setup/recovery phases remain labelled as
historical or unresolved; a health response cannot erase them. The returned
owned-stop argv is operator guidance only. It invokes no release action and
requires explicit instruction and the existing exact-lifetime checks.

Questions and draft plans can receive a normal answer without forced cards,
checkpoints or intake polls. The existing native journal retains uncommitted
conversation as deferred context. `kanban_intake_status` exposes up to twelve
160-character previews; `source_id` retrieves a complete captured source.
Deferred context is not approval. Bind new work or controls to the current
explicit owner source. Legacy pending inputs and frozen uncertain routing
intents remain pending and recover through their existing route.

An ordinary status answer does not pause or replace approved work. The existing
retained-task decision can continue its authorized ready task after the answer.
Explicit pause, scope/failure/dependency holds stay independent. Neither the
conversation phase nor deferral creates progress or root acceptance.

Routing fresh approved work selects its own card in the current admitted
project. Older approvals remain in the retained queue. An exact retry can
recover selection after the route was saved; retrying an older source cannot
replace navigation for a newer conversation. This does not change projects,
promote a card, cancel older work, or clear an independent hold.

If the current original source explicitly approved execution but the agent
classified it as effect-free question/control, `kanban_intake_route` accepts
`reclassify_current:true` with the corrected task/amendment. It preserves the
original classification and freezes the replacement before board effects. The
original explicit approval is still required. Deferred/stale sources, changed
project identities and frozen effectful intents cannot use this correction.

Queued input or an unsent editor draft suppresses automatic continuation at
the intake checks, including after its awaited projection. Editor text remains
unchanged. A later extension can still await after intake returns: the stock
Pi1.4 final core commit has no synchronous editor veto. That separate native
race remains open; these extension checks do not claim to close it.

The coordinator can answer questions and inspect with native read-only tools.
Project and task selection persist in the native session branch. Startup and
branch navigation revalidate project, board and card identities through the
pinned adapter. Missing or changed identities block execution. A new input
preserves selection; it does not automatically change projects. Reload and
project changes require fresh capability, system-tool, memory and project
knowledge observations. Execution also checks the live card status and its
prerequisites. Selection and a runnable card do not grant user permission.

The context gate uses Pi's actual ancestor/override instruction selection and
the admitted workspace router. It reads a bounded checkpoint head and delivers
instruction bodies in source-hashed windows. Changed sources invalidate prior
delivery. Compaction, reload and branch navigation clear delivery evidence.
Project and topic scopes stay separate. Execution directories and declared
output subtrees need their applicable context. Native instruction inspection
remains available for missing or broken routes. This establishes delivery at
the context hook; later provider transformations remain a separate boundary.

The everyday gate blocks raw shell, write, and edit mutations. It requires an
actual native capability observation and exact delivered `SKILL.md` bytes before
supervised work. A failed run must be read from its saved failure record before
another workflow action. Refusals name the exact native
`read` call. Omit `offset` and `limit`; partial or truncated evidence does not
satisfy complete inspection. Inspection and prerequisite checks do not clear a
failure. The next recovery must bind that run and concrete changed evidence;
only its exact successful host verification resolves that inspected failure.
Oversized diagnostics remain held; this route does not add a paged reader or
qualify natural model-driven repair.

## Bounded board views

`pi-kanban.ts` imports `kanban-reply-projector.mjs`. Keep both files and the
runtime manifest together. The installer copies `.mjs` modules explicitly.
Supported successful board replies project only `content` to at most12KiB;
`details` remains the exact original backend object. Do not replace it with
the summary: completion witnesses hash whole task rows, intake reads exact
source bodies and idempotence comments, and Framework uses complete hierarchy
and truncation fields.

Show/list/hierarchy tools accept nested `view` options, which are stripped before
the unchanged backend call. Text pages use Unicode codepoints. Comments use
stable numeric IDs. Any own top-level task field can be recovered as serialized
JSON. List and hierarchy pages describe the fetched backend result, not the
whole database or a deeper graph. Pin `expected_reply_sha256` while paging;
changed results return a stale-cursor notice. Mutation acknowledgements omit
history and do not claim the newest observed comment belongs to that write.

This is a model-view boundary. Full host data, unrelated actions and the1MiB
adapter transport guard remain unchanged. Native read/project_context delivery
is not truncated. Tool-definition size and inference latency are separate
measurements. The pure helper has21 portable contract cases. The actual native
reply/provider/controller probe passed20 checks, and the existing35 composition
checks still pass. In one synthetic case the decoded model content was
105,410bytes before projection and7,599bytes afterwards. Matched provider
envelopes were106,886 and8,076bytes. Full task rows, comments and completion
witness hashes remained unchanged; actual Framework completion also passed.
No inference or live-board claim is supplied by those fixture results.

## Qualification Boundary

Offline tests cover identity, knowledge, immutable skill compilation, private
binding removal, and source pins. The original host controls also covered native
tool blocking, reload/resume, dependency edges, exact-card audit routing,
closeout, memory round trip, and project-local skill compilation.

Those results do not qualify a new host automatically. Run native positive and
negative controls after installation. Do not infer Hunt-farm readiness, semantic
task completion, shared-skill promotion, physical-action authority, or proof
authority from this adapter.

The portable selection contract test executes the complete TypeScript
coordinator with explicit native-API and backend fixtures under Node22.13 or
newer. It covers operation without an adviser, input and reload continuity,
changed identities, missing cards and unmet prerequisites. This is an adapter
contract test, separate from live Pi/Hermes adoption. The current coordinator
also registers the complete [intake138 closure](../intake/README.md). Keep that
directory and its generated Framework binding together. Source capture,
retained-work continuation, quiet waits and receipt handling need their own
native positive and refusal checks; board readiness alone is not authorization.

The standalone context qualification passed17 groups using the actual Pi1.4.0
loader, tool-call runner and native read/grep tools with explicit project
fixtures. Pi/Hermes/Framework composition with that context gate then passed35
checks on an isolated real board and native session. Memory readiness was
explicit fixture data. No model calls, memory-health claim, task execution or
unpaused model-wakeup proof is supplied by that composition. The final fresh-home
startup separately passed with eight extensions and30 tools. Preserve the
different scopes when reporting target adoption.

Fresh homes route MemPalace MCP, capture, validated retrieval and the installed
`bin/mempalace` command through their home-owned memory-runtime wrapper. Its
process-local CPU cache binding is required because Chroma MiniLM does not use
the generic Hugging Face/XDG cache variables alone. A direct environment
executable skips that binding. The separate synthetic connected-memory test
passed24 controls, including same-open MCP mutation, capture mining, exact six
chunks/closet witnesses, recall, repeat, tamper refusal and owned shutdown. It
does not establish private-history claims or new-host freshness.

Reviewed Git milestones use the existing `workflow_step`, not another execution
tool. Recognized checkpoint actions require a complete current `source-control`
skill read even if `required_skills` is omitted. Their project root must match
workflow `cwd`. The declared operation receipt and exact installed-helper
verifier are required before execution; an arbitrary predicate cannot supply
Git commit or remote proof. Existing intake, task, project-context, pause,
failure and process-owner checks still apply. This is a narrow installed-helper
route, not attribution or enforcement of every shell Git operation.


## One managed child

`task_agent` runs one serial native Pi child on the currently selected, runnable,
source-authorized **hierarchy child** card. First create/decompose and select the
card with the existing board tools. Complete normal parent discovery, applicable
project-context delivery and skill reads before delegating. Supply a short `task`
and explicit `timeout_seconds` in1..86385. This is a productive child-operation
budget, not a session or whole-project limit; each supervised action still uses
its declared action/check budgets. There is no default600-second child policy.

This is a new integration of Pi1.4 public SDK APIs. It is not an upstream core
`task_agent` tool or a transplant of a private worker launcher. The child has a
fresh native in-memory session and the same owned local model/configuration.
The model/auth runtime reads the same agent directory normally. The adapter
does not copy API keys into arguments or records. Different providers, models, routing headers,
config sources and extension provider overrides are held. The existing parent
retains its home/resource lease and project session writer lease.

Only a fixed subset of existing inspection, discovery, research and
`workflow_step` tools is offered. Calls use native parent `executeTool`, with its
existing source, context, skill, failure and process-ownership checks. No child
project/intake/card lifecycle or recursive child tool is exposed. Parent effects
outside this active child's nested tool calls are held until it settles. This
is cooperative ownership, not a hostile-code sandbox. The child cannot load a
new topic's context into the parent's prompt mid-operation; missing parent
context stays held for parent inspection before a later delegation.

The child loads normal prompt/skill/context resources without registering a
second coordinator, memory capture extension or MCP connection. Its task prose
is delegated data, never fresh owner approval. Source/model/input changes,
cancellation and the declared deadline cancel or hold delivery. Actual calls,
assistant messages and native usage fields are bounded to256KiB and retained in
the parent's native journal and tool details. The model receives a summary of at
most12KiB, with actual final text, reported tool outcomes, receipt/output locators
and an exact record digest. Omitted text/calls/locators are marked; the summary
never claims complete evidence. Child completion is untrusted output; the parent
still verifies artifacts, integrates the card and checks the root outcome.

Use the supplied `inspect` arguments with read-only `task_agent_inspect` to recover
large records. Follow each returned `next` argument set. Offsets count Unicode
code points, not bytes or lines; every serialized model-facing JSON window is at most12KiB.
Pages bind the exact native record digest, original capture/route source and
currently admitted project. They expose no arbitrary file selector and perform
no inference, project mutation, progress credit, approval or replay. Without a
digest, `call_id` returns bound metadata first, including an unfinished start
when no result survived. Inspection stays available during a pause or unresolved
child hold. `complete_record` describes one selected record only; it does not
mean the whole attempt/history is present or its task is accepted.

There is no saved child JSONL or child resume. After parent loss, an unmatched
native child-start record holds effects and automatic continuation. Inspect the
retained journal and partial host artifacts before routing a fresh explicit
owner resume. A model work checkpoint cannot clear this uncertainty. A matching
`returned` result closes the start; failed, cancelled, deadline, delivery-held or
unknown results keep the hold even if the parent failure hook was never saved.
The existing failure/pause rules keep their separate meanings.
Never automatically replay an interrupted child.

`tests/test_pi_managed_child_native.mjs` qualifies the SDK/tool integration with
synthetic provider responses, real Hermes and supervised fixture actions. Its
scoped `--case positive` and `--case lifetime` controls distinguish successful
return from parent-loss ownership/reopen checks. An explicit memory-result
fixture avoids memory service calls. These are not a real-model delegation,
whole managed CLI, full-profile or semantic-quality acceptance claim. Research-only
continuation accounting through nested child results is not qualified; no
progress is inferred from child text or receipt metadata.
