# Agent-home installer

Status: development candidate. The bootstrap, request intake/task waits,
Framework binding, evidence-bound recovery, bounded native compaction, current
session capture, validated recall and hierarchical project context are implemented.
Native source tests and
fresh dependency setup are separate evidence. Remaining adoption boundaries
are retained below.

## Run from a repository checkout

On Linux x86_64 with glibc, install Git, curl, tar, coreutils and flock first.
The bootstrap installs its own pinned Python and Node beside the new agent home.
Its process-API self-check must pass before agent packages are installed. Hosts
without usable Linux pidfd APIs are refused with the owned runtime retained.

```bash
git clone https://github.com/scruge1/lowvram-agentic-harness.git
cd lowvram-agentic-harness
bash install.sh
```

The wizard asks for a new agent-home directory, shows its download/storage plan,
then asks for the local OpenAI-compatible endpoint and exact model ID. It creates
a dedicated home. Existing agent profiles,
memory databases, services and project directories are not migrated by setup.
Setup checks all 14 required templates before creating the home. Its Git-ignore
template is installed as `.gitignore`.
Choose storage with room for package environments, memory and embedding caches.
The bootstrap requires at least8GiB free before runtime provisioning; this is
headroom for that step, not a complete model/package capacity estimate. Keep the
permanent `HOME-runtimes` sibling: installed environments use its Python. Runtime
downloads resume with exact size/hash checks. Conflicts and failed partials are
retained. Global Python, Node, PATH and shell profiles are not changed. See the
[runtime sources and licences](harness/BOOTSTRAP-NOTICES.md).
No agent model weights or GPU server are downloaded or started. Memory embeddings
have their own first-use download and readiness checks.

Use `bash install.sh --home /data/my-agent --plan` for the read-only plan.
Use `--yes` to accept that displayed runtime plan in an unattended install, and
pass the existing install options directly after it. For example:

```bash
bash install.sh --home /data/my-agent --yes --profile agent \
  --base-url http://127.0.0.1:8080/v1 --model my-local-model --name Owner
```

After a failure, preserve both directories and inspect their logs. Correct the
stated cause, then use `bash install.sh --home /data/my-agent --yes --resume-install`
without initial install options. Resume retains the existing home configuration
and verified package steps. `--runtimes-only` provisions just the owned Python
and Node. Neither option accepts another home, interpreter or Node override.

For an existing reviewed Python3.12/Node22.19+ installation, the direct entry
remains `python -m harness.home install --python312 /path/to/python3.12`. The
dependency-free core supports Python3.9+.

For a fully specified command, put the global home option before the action:

```bash
python -m harness.home --home /data/my-agent install --profile full \
  --python312 /usr/bin/python3.12 --base-url http://127.0.0.1:8080/v1 \
  --model my-local-model --name Owner
python /data/my-agent/agent-home.py doctor
python /data/my-agent/agent-home.py start
python /data/my-agent/agent-home.py project example
python /data/my-agent/agent-home.py start --project example
python /data/my-agent/agent-home.py memory status
python /data/my-agent/agent-home.py palace status
/data/my-agent/bin/mempalace status
```

On Windows, use `py -3` for the core if `python` is unavailable. The pinned board
adapter uses Linux file locks, and the reviewed process owner requires Linux
`/proc`, pidfds and child-subreaper support. Windows/macOS currently support the
core scaffold; package-stack setup refuses those hosts. This is not a
cross-platform process sandbox.

Use `--profile core --offline` to create only the dependency-free scaffold.
The default `agent` profile includes Pi, the Hermes board, MemPalace, Agent
Framework and the owned public-research environment/browser. Use `--profile full`
explicitly to add Claude-mem with Bun and the Harness2/DeepSeek laboratories.
The reduced `--profile pi` retains Pi, board, memory and the model-free Framework
decision helper without the research dependencies. None of these profiles starts
a generative model server or allocates a GPU.
`--offline` on another profile retains the requested package list but does not
install it; doctor reports those dependencies missing.

Set `--context-window` and `--max-output` from the actual server configuration.
Defaults32768/4096 are configured limits, not detected capabilities or memory fit.
One measured first-project request used10,830 input tokens before useful work;
the former8192 default could not hold that request. Its32K/4K report journey
still failed to deliver an artifact. Supply the actual supported server limits;
increasing configuration values does not expand the server or qualify the model.
The installer sets native compaction reserves to fit the selected context.
Image input stays disabled until the selected model/projector path is tested.

Inspect the intended storage volume and discover existing local services before
creating a home:

```bash
python -m harness.home onboard inspect --destination /data/my-agent
python -m harness.home onboard discover
python -m harness.home onboard discover --base-url http://127.0.0.1:8131/v1
```

Discovery makes bounded `GET /models` requests without credentials, redirects
or environment proxies. It does not load or select a model. A local server can
proxy remote inference; its listing does not establish local execution, memory
fit or tool capability. Inventory retains the existing first-GPU probe scope.

Select `install --model-profile llama-cpp-qwen` only for Qwen served by
llama.cpp with its Qwen chat template. This uses Pi's native model metadata so
the default thinking level `off` reaches `chat_template_kwargs.enable_thinking`.
The default `generic-local` leaves backend-specific controls unset. Model names
do not select a profile, and this profile is not qualified for Ollama. The native
serializer was exercised without network traffic; a subsequent real local-model
report task still failed to produce its artifact. Transport correctness does not
establish model task acceptance.

After a failed installation, inspect the private command logs and exact failure.
Correct the cause, then use `agent-home.py resume-install --python312 <path>`.
Already recorded package steps are retained. Setup never overwrites a home or
automatically replays an uncertain external effect. An interrupted package step
is not automatically accepted from its directory's presence.

For runtime source maintenance, use the source-only staging commands from a
reviewed repository checkout:

```bash
python -m harness.maintenance --home /data/my-agent inspect
python -m harness.maintenance --home /data/my-agent repair-plan
python -m harness.maintenance --home /data/my-agent plan --source /path/to/reviewed-checkout
python -m harness.maintenance --home /data/my-agent stage \
  --source /path/to/reviewed-checkout --operation update-001 --expected-plan PLAN_SHA256
python -m harness.maintenance --home /data/my-agent verify-stage --operation update-001
python -m harness.maintenance --home /data/my-agent withdraw \
  --operation update-001 --expected-receipt RECEIPT_SHA256
```

Use the exact plan/receipt hashes returned by the preceding commands. Planning
does not execute candidate code. Staging retains candidate and predecessor bytes
under the home's update state, checks source/import/package bindings and refuses
drift, unqualified dependencies and replay. Personalized context, credentials,
sessions, boards, palaces and active runtime remain in place. Withdrawal retires
staged bytes. Withdrawal is not active-runtime rollback.

Compatible runtime updates use `python -m harness.runtime_update --home HOME`.
Run `plan --operation ID` after staging. Before `apply`, retain an explicit
`agent-home-runtime-qualification/v1` JSON contract with scope
`compatible-runtime-only`, `qualified: true`, `execution_authorized: true`, the
plan's exact `home`, `operation`, `stage_receipt_sha256`, `candidate_sha256`, and
an `evidence` list of absolute file paths and SHA256 values. The operator must
actually review and qualify those bytes; creating this file is not verification.

```bash
python -m harness.runtime_update --home HOME apply --operation ID \
  --expected-plan PLAN_SHA256 --qualification /path/to/qualification.json \
  --qualification-sha256 CONTRACT_SHA256 --execute-qualified-runtime
python -m harness.runtime_update --home HOME verify --operation ID \
  --expected-journal JOURNAL_SHA256
python -m harness.runtime_update --home HOME rollback --operation ID \
  --expected-journal CURRENT_JOURNAL_SHA256
```

Explicitly stop the home's memory hub first with `agent-home.py palace stop`.
The exclusive lifetime lease refuses active consumers. Apply exchanges only a
compatible runtime and its exact bindings, retains the predecessor and journal,
and ends pending consumer acceptance. Verify runs the stable doctor and normal
managed Pi `/agent-health` command without inference. It accepts only the actual
configured tools, model and memory discovery. An interrupted exchange blocks
normal entry. Use `recover --operation ID --expected-journal CURRENT_SHA256` from
the retained reviewed controller to restore that predecessor. Keep the journal
and stage receipt; withdrawal refuses an operation used by runtime exchange.
Personalized files, credentials, sessions, boards, packages and new user data
survive rollback. Dependency, entry-protocol and template migrations remain held.

The first agent session uses `project_admit` for its project and `project_context`
for the relevant directory before execution. Read any remaining context windows
and let their exact results reach the next model-input context. A successful
context tool call alone does not open the gate for a sibling action in the same
tool-call batch. The existing task, pause, skill and effect checks still apply.

## Launch from any directory

A fresh home includes a command bound to its absolute launcher:

```bash
/chosen/agent-home/bin/harness-agent --status
/chosen/agent-home/bin/harness-agent --project /path/to/admitted-project
```

On Windows use `bin/harness-agent.cmd`. The actual OS HOME stays unchanged.
The managed home supplies its instructions, model, tools, memory and native
session directory. An admitted project keeps its working directory. An unrelated
directory opens the home; launch does not adopt it as a project.

To register a shorter command in an explicitly selected directory:

```bash
python /chosen/agent-home/agent-home.py command install --bin-dir /chosen/user-bin
python /chosen/agent-home/agent-home.py command status --bin-dir /chosen/user-bin
python /chosen/agent-home/agent-home.py command remove --bin-dir /chosen/user-bin
```

Add `--default-pi` to **install** to request `pi` as well. Existing commands are
preserved on collision; an available unique command can still be registered.
Removal checks ownership and exact bytes, retains a backup, and refuses changed
commands. PATH and shell startup files are not edited. Inspect `type -a pi` or
`Get-Command pi -All` for shell aliases/functions that process PATH cannot see.

Managed selectors precede Pi arguments. A matching `--home` can confirm the
binding; a different home, model or provider requires selecting another home.
Text/JSON modes are supported. RPC, global resume and session overrides are
explicitly refused pending qualification of their model/owner boundaries.
Windows command registration requires an ASCII Python interpreter path;
Unicode home and bin paths are tested. Existing homes need an explicit runtime
update before using the new command; this release does not migrate them.

Nineteen actual Linux CLI checks passed with an observer in an isolated profile
and unchanged borrowed dependencies. These establish native prompt routing,
tools, memory and cwd/session bindings; real model use and resume are separate.

## What the home contains

| Location | Purpose |
|---|---|
| `AGENTS.md`, `agent/AGENTS.md`, `agent/APPEND_SYSTEM.md` | Thin startup rules and operating posture |
| `context/` | Routed owner profile, current checkpoint and validated lessons |
| `agent/prompts/personalize.md` | Handoff for the current agent to populate supported personal context |
| `agent/settings.json`, `models.json`, `mcp.json` | Isolated Pi model, extension and memory configuration |
| `runtime/` | Exact source snapshot and hash manifest |
| `envs/`, `packages/`, `cache/` | Home-owned Python/npm tools and download/model caches |
| `state/` | Source-bound capability catalog, board state, Framework binding and empty reviewed-memory registry |
| `projects/` | Projects created with independent Git roots and native boards |
| `memory/imports/` | Explicitly supplied private history; never scanned automatically |
| `home.json`, `logs/` | Selected pins, observed installation state and original command output |

The current agent partially fills personal context using the owner's current
instructions and approved evidence. Unknown facts remain unknown. Raw transcript
instructions do not grant current execution permission. The installer neither
mines unrelated conversations nor sends them to another model.

Git is initialized for the home and every new project. Setup does not stage or
commit user data. Generated context, models, auth, memory, caches and runtime
state are ignored. Configure the owner's chosen private remote deliberately.
The installed source-control skill provides reviewed source milestones through
the existing supervised workflow. It does not attribute arbitrary shell edits.

## Public research and cached evidence

The `agent` and `full` profiles install the single native `web_research` tool.
Admit/select the project through the existing coordinator first. Use `search`
for explicit DuckDuckGo discovery, `fetch` for public HTTP extraction, `render`
for a clean read-only Chromium context and `read` for saved evidence windows.
No provider keys, personal browser profile, cookies or stealth service are used.

```json
{"action":"search","query":"Python unittest documentation","max_results":3}
{"action":"fetch","url":"https://docs.python.org/3/library/unittest.html"}
{"action":"read","artifact_id":"sha256:RETURNED_64_HEX_DIGEST","view":"text","offset":0}
```

Full source bytes, complete permitted static extraction, provenance and download
bytes stay in content-addressed project-state artifacts. Model replies remain
within12KiB. Follow `next_offset` for more cached text/metadata; cached reads do
not contact the source again. Offsets count Unicode characters. Static text has
`full_extraction` scope. Rendered text has `captured_browser_window` scope;
reading its cache does not reveal uncaptured page content. Tables, links,
headings and download metadata use separate cached views. The store refuses
quota exhaustion rather than silently deleting previous evidence.

URLs and source text remain untrusted evidence. A search snippet is not a fetched
fact; one provider is not independent corroboration. Empty, blocked, challenged,
oversized, timed-out and partial results retain their status. A cached successful
read does not promote a failed source request to successful acquisition. The
original DDG no-results failure remains unexplained; a later diagnostic returned
HTTP200/three hits. Native installed search, static fetch and complete cached
recovery passed. A normal Pi-tool browser check returned3,022 characters in4.126s
with partial-resource status and the unchanged40-second default.

Browser network requests pass through the reviewed public HTTP route, including
DNS/redirect checks and bounded streaming. Native routing preserves CSP/CORS;
unintercepted browser networking is denied. Downloads use explicitly labelled
host-fetch/browser-blob bytes with matching hashes. This does not establish
general authenticated browsing or original download-UI parity.

This text-research route omits image, media and font requests before the shared
fetch queue. Each omission records `nonessential_text_resource` and its resource
type, with partial-result status. A native slow-image fixture reproduced a queued
JavaScript timeout before this change. Pages that depend on resource load events
can remain partial; this is not a full visual rendering route. CSS, JavaScript,
data and explicit download operations keep their existing checks and deadlines.

The dependency plan pins16 tested Python runtime distributions and Playwright's
matching Chromium revision1248. Source/native-file inventory is recorded under
`state/research-installation.json`; generated Python bytecode is excluded.
Resuming installation refuses a changed selected package/dependency plan.

## Stable home lifecycle boundary

Fresh Linux homes keep `home-lifecycle.py` beside the stable `agent-home.py`,
outside the replaceable runtime. The launcher checks the guard bytes and takes
a shared lifetime lease before importing runtime code. Managed Pi children and
the owned memory hub retain their own lease. Guarded memory/research commands
check pending activation before executing their runtime helper. An exclusive
update lease refuses a busy home; pending activation refuses ordinary entry.

This is coordination between managed entrypoints, not an OS sandbox. Older
homes and unmanaged direct Pi commands do not gain this boundary automatically.
Windows retains core inspection without Linux lease enforcement. Source staging
still does not activate or roll back an active generation.

## Read bounded board replies

Rare board displays and project-maintenance schemas use native deferred exposure.
Use `tool_search` for the needed name, check the loaded result, then call that
tool. This includes list/show/create/comment, hierarchy/decomposition, knowledge
rebuild and closeout/skill/memory-candidate preparation. Intake, context, selection
and workflow tools stay direct. Native discovery is fuzzy; a matching query does
not establish permission or source correctness. Existing restored active tools
are preserved. Without discovery, the previous direct schema surface remains.

Successful show, list, create, move, comment, decomposition and hierarchy replies
use a bounded model view, at most12KiB of UTF-8 JSON. The original complete
backend reply remains in host `details`. Routing, source matching, idempotence,
completion witnesses and Framework decisions still use complete controller
data. Existing task bodies, comments and board history are not rewritten.

`kanban_show`, `kanban_list` and `kanban_hierarchy` accept a nested `view` object.
Those display options are removed before backend request validation. Use returned
offsets and `raw_reply_sha256` to request more data:

| Need | View options |
|---|---|
| More task body | `body_offset` |
| Earlier comment IDs | `before_id` |
| One comment's complete body | `comment_id`, then `offset` |
| Any own top-level task field | `task_field`, then `offset`; pages contain its serialized JSON |
| More fetched list entries | `items_offset`, optionally `items_limit` up to20 |
| More returned hierarchy nodes | `hierarchy_offset` |
| More dependency or containment IDs | `relation_offset` |
| Guard against changing source | `expected_reply_sha256` from the previous raw reply hash |

Offsets are Unicode codepoints for text and indexes for collections. A changed
reply hash produces an explicit stale-cursor result. Restart paging against the
new hash. List paging covers the backend's fetched limit, at most100 cards;
it is not unlimited board pagination. Hierarchy paging does not clear the
backend's depth/truncation limit. Prerequisite edges and decomposition containment
remain distinct. Mutation acknowledgements omit old history. A latest observed
comment ID is not proof that this call created it during concurrent writes.

The12KiB cap applies to supported model views. Other actions, complete host
details and the existing1MiB adapter transport limit remain unchanged. This
does not establish whole-context token savings, faster model inference or a
bound on tool-definition schemas. The installer includes the projector's
`.mjs` source and hash in its runtime snapshot.

Qualification passed21 pure projection cases,20 actual native reply/controller
checks and the existing35 Pi/Hermes/Framework/context checks. In one isolated
synthetic card case, matched decoded tool content fell from105,410 to7,599bytes
(92.79%). Matched provider tool-message envelopes fell from106,886 to8,076bytes
(92.44%). These use the actual installed SDK/provider serializers, with no
inference. Full host details stayed unchanged. This measures one tool reply,
not complete requests, token counts or end-to-end latency.

## Reuse existing engineering work

The installed `reuse-first-engineering` skill ports the existing working method:
recover the owner's complete outcome and prior decisions, inspect actual native
capabilities and source, directly reuse a working implementation, then compare
the result with independent checks and the best retained baseline. Preserve
the reasoning behind the existing architecture when making it portable.

Pi discovers the skill through its normal metadata. Read the selected
`SKILL.md` for substantive engineering and only the needed section of its
`references/reuse-and-comparison.md`. Do not inject every reference into each
request. A workflow using this procedure declares
`required_skills: ["reuse-first-engineering"]`; the existing gate requires that
selected skill to have been read before the action. The posture guides skill
selection; this is not a claim that semantic reuse is independently enforced.

Fourteen native, model-free consumer checks passed, including real standard
library reuse and independent edge/negative checks. Actual model-driven
selection and first-project quality remain separate acceptance work.

## Save reviewed project source

Read the installed `source-control` skill before a source milestone. It uses
the existing `workflow_step` and its project, task, context, pause, failure and
process-ownership gates. No second execution tool or commit scheduler is added.
The milestone action must use the configured Python and installed
`runtime/harness/source_checkpoint.py`, with its project root equal to workflow
`cwd`. Its only declared output is the operation's admission receipt. The
verifier must call that same helper with the project-relative receipt path;
a different model-supplied predicate cannot establish Git delivery.

Create an explicitly reviewed JSON inventory under the project's
`.icm/workspace/artifacts/source-control/` directory. `safe_files` is an array
of objects containing an absolute `path` and the complete file `sha256`.
Supply the complete inventory's hash, a unique operation, commit message and
existing task reference. The helper verifies inventory, source, staged and
committed bytes. It supports a new repository's first commit and retains
unrelated unstaged work. An occupied index, source drift, a nested repository
or an escaped inventory stops the operation. Files remain unchanged by the
helper. Git transformations that change staged bytes must be resolved before
an exact-byte checkpoint can pass.

The default is a local commit. Push delivery requires all three explicit
options: `--push-remote`, `--expected-push-url` and `--expected-branch`.
The current branch and single configured push URL must match, and readback
must find the exact commit at that remote ref. Use the owner's established
credentials; do not embed them in URLs. A push failure retains the local commit
and a pending receipt. Inspect it before recovery. Never repeat an operation,
force a push, reset the index or discard another session's work.

This portable helper reuses the reviewed checkpoint algorithm. It does not
copy a private source allowlist, credential store or Forgejo privacy API. The
caller must establish source ownership, review the chosen files and authorize
any remote delivery. A task label records context; it grants no permission.
Local commits, remote delivery and deployed behavior remain separate facts.

Git references: [explicit-path commits](https://git-scm.com/docs/git-commit)
and [remote ref readback](https://git-scm.com/docs/git-ls-remote).

Qualification passed21 real-Git controls and22 native Pi/Hermes/guarded-workflow
checks. The native path made an actual commit and independently read it back.
It exercised skill omission, wrong project/verifier/output, reload, intake,
pause, occupied index, complete failure inspection, explicit recovery and replay
refusal. Remote tests used isolated local bare repositories. No live project,
external push or generative model was involved.
The same native probe loaded the current portable operating posture through
Pi's actual resource loader and verified its full text and six required clauses
in the session prompt before and after reload. This proves prompt delivery,
not model obedience or whole-prompt token savings.

## Pinned tools and readiness

Reviewed25October2026. Pins are candidates for this installer, not a promise of
complete native integration. Installed, running, tested and accepted remain
separate fields. Locks/freezes and full command logs stay in the private home.

| Tool | Exact selected artifact | Integration boundary |
|---|---|---|
| Pi | `@earendil-works/pi-coding-agent@1.4.0` | Local provider configuration; selected coordinator extensions |
| Hermes board | commit `866332bfb52c46e543143b2620a9aeee8bce9c77` | Existing pinned board adapter, no second dispatcher |
| MemPalace | `mempalace==3.11.0` | Home-owned palace and loopback single-writer hub; synthetic connected capture/recall passed, new-host freshness remains separate |
| Microsoft Agent Framework | `agent-framework-core==1.21.0` | Isolated environment and exact target-bound read-only decisions; native board remains canonical |
| Public research | `ddgs==9.16.1`, `httpx==0.28.1`, `beautifulsoup4==4.15.0`, `playwright==1.64.1`; complete16-distribution plan in `harness/research_install.py` | Owned Python/cache/browser; source evidence and bounded project artifact views |
| Harness2 | commit `1cfe254e8d25b15f37048c3730134686abe60335` | Experimental package; prior model quality hold still applies |
| Bun | `1.4.4`, explicit Linux CPU/libc artifact | Home-owned runtime for the observer; binary hash recorded |
| Claude-mem | `claude-mem@13.29.0` | Isolated local provider/settings, owned worker checks and native Pi event hooks |
| DeepSeek Harness | `@deepseek-ai/dsh@0.2.1-rc.2` | Isolated optional laboratory, not default task routing |

Claude-mem package installation alone supplies its SDK. This installer also
writes the explicit local-compatible endpoint/model, disables hosted quota
fallback, cloud sync, ambient transcript watching and telemetry, and installs
Pi event hooks. Its data, port and PID belong to the selected home. Before
capture, the adapter verifies the worker's version, source path, process
lifetime, data directory and actual selected provider. An occupied foreign
port is held. It is never stopped or adopted as this home's worker.

`memory start|status|stop` manages that exact observer. `memory search --query
"terms"` performs SQLite FTS keyword retrieval with original observation IDs
and bounded complete API delivery. Chroma is disabled for this new observer;
MemPalace supplies separate semantic recall. Hook delivery does not establish
observer output quality or freshness. No global Claude/Codex profile is edited.

The existing private preservation fork is not stock13.29.
Never migrate an existing store during fresh-home setup. Such a migration needs
complete SQL/vector/project-identity parity, shadow-generation testing and native
drain/restart/rollback qualification. Incomplete compatible-provider settings can
fall back to a hosted provider; do not activate that configuration.

Pi transcript capture runs on settlement/shutdown notifications for only the
current home-owned session. It preserves original JSONL bytes, supports a
single readable prompt and records exact native chunk/closet coverage. It does
not scan old sessions or create a second transcript archive. Initial mining
can download a local embedding model into the home-owned cache; offline
readiness still needs an actual memory write/search/readback.

Use the installed `bin/mempalace` launcher for direct memory commands. Native
MCP, capture and validated recall also enter through the home-owned
`harness/memory_runtime.py` wrapper. It binds the actual interpreter, package
versions, Chroma ONNX source and CPU embedding-cache destination before importing
MemPalace. Chroma's MiniLM default does not obey `HF_HOME` or `XDG_CACHE_HOME`
alone. Calling an environment's bare MemPalace executable skips this wrapper.
Normal `agent-home.py start` verifies and starts the home's native MemPalace
loopback hub before Pi. Native MCP, CLI and capture require that owned ready
single writer. `agent-home.py palace start|status|stop` provides explicit control;
`memory start|status|stop` controls the separate Claude-mem observer. Initial
palace setup does not start the hub. MemPalace retains small native registry and
lock metadata in `~/.mempalace`, with the real `HOME` preserved; bulk palace data
and embedding caches stay in the selected home. Cache bindings and service
readiness remain separate from actual capture, mining, recall and complete
pipeline acceptance.

Validated recall starts with an empty claim registry and abstains. Raw memory
hits do not become facts. Reviewed safe summaries must bind exact current
source bytes, state and source identity. Shared promotion remains separate.

Fresh homes use deferred MCP exposure. First call native `tool_search` with
`{"query":"mcp__mempalace__mempalace_search","limit":1}`. Then call the
canonical memory tool only if the returned loaded name is
`mcp__mempalace__mempalace_search`. Search ranks candidates; a query is not an
exact-name guarantee. Refine discovery if it returns another tool. Discovery loads its
schema for the next model request; it does not query memory or satisfy memory
readiness. Pi retains discovered tools on the session branch. Use `/mcp` to
inspect connection and exposure; use `/reload` after editing MCP configuration
outside the session. Source support does not establish qualification of a new
exposure setting or its memory/intake path on the selected host.

Current-source native qualification passed30 checks with an offline-generated
home and unchanged installed dependencies. Matched provider tool-schema JSON
changed61,683 ->26,241bytes (57.46% less) before memory discovery. All47 memory
tools remain registered; required workflow/context tools stay active. Actual
recall, semantic error refusal, reload and reconnect passed. A search JSON error
without MCP `isError` no longer satisfies recall readiness. This is a synthetic
native shadow test, not a fresh package install or a model-driven new-host task.

Pi1.4 includes native MCP reconnect/shutdown behavior. The historical custom
bridge is not copied on top of that native bridge. Native health, idle exit,
restart and exact memory readback still require acceptance on the chosen host.

The [project-context gate](adapters/pi/context/README.md) uses Pi's own ancestor
instruction selection and the admitted workspace routes. It delivers applicable
instruction bodies in bounded source-hashed windows and at most64lines/4KiB of
the current checkpoint. Source changes invalidate prior delivery. Reload,
compaction and branch navigation require fresh delivery; context for one project
or topic does not admit another. The two required internal Pi APIs have explicit
1.4.0 source pins. This gate does not supply the separate task/comment refresh
behavior from the private system or prove final-provider consumption.

## Current qualification

The current source snapshot passes the offline release gate on Linux and
Windows: 21 checks, including all seven self-tests. Ruff 0.16.10 also passes.
The earlier explicit full installation passed on Linux as one normal command:
all eight components installed and doctor returned no failures. Native startup
loaded eight extensions and30 tools with the selected owner instructions and
model limits, without a generative model request or configuration mutation.

The connected memory test passed24 checks. One stdio MCP connection stayed open
across an MCP write, transcript capture, native CLI mining and recall of distinct
captured content. All six expected chunks and closet witnesses were read back.
Unchanged repeat, tamper refusal, exact restoration, original JSONL conservation
and owned-process shutdown passed. Pi's normal `mcp list` connected to47 tools
with Node22.23.2. The174.5MB CPU embedding cache stayed on the selected archive
volume; true HOME was preserved. These checks used public synthetic content
and made no generative model or GPU calls.

An earlier fresh Linux candidate installed all eight components, passed doctor,
and passed a native29-tool startup before the latest context and hub changes.
The context gate separately passed17 model-free native groups, including actual
Pi instruction selection, read/grep behavior, delivery, bounds, reload,
compaction, project switches and refusal cases. Pi/Hermes/Framework composition
with the context gate then passed35 checks using an isolated real board and
native session. Its memory readiness was explicit fixture data. It made no
model calls and does not qualify memory health, task execution or an unpaused
model wakeup. Those checks do not establish the final home and memory composition.

Real model behavior retains its own acceptance boundary. Source installation
and model-free tests do not establish whole-system parity.

Upstream references: [Pi configuration](https://github.com/earendil-works/pi/blob/v1.4.0/packages/coding-agent/docs/configuration.md),
[Pi extensions](https://github.com/earendil-works/pi/blob/v1.4.0/packages/coding-agent/docs/extensions.md),
[Pi MCP](https://github.com/earendil-works/pi/blob/v1.4.0/packages/coding-agent/docs/mcp.md),
[MemPalace](https://github.com/MemPalace/mempalace/tree/v3.11.0),
[Claude-mem](https://github.com/thedotmack/claude-mem/tree/v13.29.0),
[Agent Framework](https://pypi.org/project/agent-framework-core/1.21.0/),
[Harness2](https://github.com/google-research/harness2/tree/1cfe254e8d25b15f37048c3730134686abe60335).

## Export inventory and remaining work

The comparison covers the substantial19September Pi export, later September
memory/context work, October10 main release, October19 draft upgrades and current
October24 Pi evidence. Current checkpoints supersede older session claims.
Only reusable behavior is exported. Personal data, host paths, credentials,
private runtime source and active session identifiers stay outside this repo.

| Requirement | Current public state | Remaining acceptance |
|---|---|---|
| Home location, thin instructions, personalization handoff | Implemented | Normal current-agent handoff |
| Reuse-first engineering and selective native skills | Thin posture and native skill/reference installed;14 scripted native checks passed | Real selected-model discovery, reuse and useful first-project quality |
| Local model routing and isolated packages | Fresh full one-command Linux install, doctor and30-tool startup passed | Real selected-model request and new-host acceptance |
| Per-project Git and board creation | Implemented; native board/context composition passed35 checks | First ordinary project and outcome acceptance |
| Optional planning adviser, direct card select, saved navigation | Model-free native composition passed35 checks | Normal model-driven use |
| Linux owned-process execution | Reviewed guard exported | New-host positive, negative, timeout and owner-loss controls |
| Native request capture and exact intent/source routing | Coherent intake138 closure exported | Normal native input and mid-turn invalidation tests |
| Root outcome, hierarchy, triage leaf specification and cancellation | Current backend exported | Source-bound retained-work tests; no general root acceptance claim |
| Framework read-only decisions over the native board | Actual Framework/Pi/Hermes/context composition passed35 checks with a generated target binding | Normal model-driven use and root-outcome acceptance; no duplicate dispatcher/database |
| Quiet intake and compact live state | Intake source exported | Final-provider coverage; separate private task/comment refresh behavior remains unexported |
| Bounded Kanban model replies and explicit paging |21 pure cases,20 native reply/controller checks and35 existing composition checks passed; full host details retained | New-host adoption; backend transport and tool-definition size are separate |
| Hierarchical project instructions and bounded checkpoint delivery | Current context gate exported;17 native groups,35 composition checks and30-tool startup passed | Model-driven use; no final-provider attestation |
| Read-loop containment and evidence-bound recovery | Read-loop079 and exact failure-read/recovery gates exported | Full native model-path adoption; matching recovery evidence/receipt only clears its own latch |
| Quiet session/task waits and receipt-driven one-time wakeups | Task-waits138 source exported | Watcher/race/pause/cancel/reload checks; interactive wakeup pilot still open upstream |
| Local-provider bounded native compaction | Public native API and exact target selectors exported | Native API tests passed with synthetic stream; real summary quality remains model-specific |
| Action failure dominates verifier success |25 native controls passed: nonzero action stays failed despite predicate-valid output; controller/helper/tool agree | New-host adoption; separate private ledger tools are not installed |
| MCP lifecycle and health | Native Pi1.4 connected47 tools; owned hub startup/idempotence/shutdown and connected recall passed | Long-idle reconnect and new-host lifecycle checks |
| Deferred MCP schemas and canonical recall readiness |30 current-source native checks; actual recall, error refusal, reload/reconnect; matched initial schema bytes57.46% lower | New-host/model-driven adoption; no whole-request token or latency claim |
| Validated memory retrieval, exact chunks and promotion | Empty safe registry abstention and synthetic native capture/mining/exact readback passed | Reviewed promotion, new-host freshness and private-history acceptance |
| Pi/Codex/Claude session capture and raw archive distinction | Current-session Pi capture and local observer hooks exported | Existing Codex/Claude history imports remain opt-in; whole private archive/replica system is not copied |
| Source milestones, scoped commits and remote verification | Reviewed CLI/skill,21 real-Git controls and22 native supervised-workflow checks passed | New-host adoption; automatic all-session attribution remains open |
| Terminal/project navigation and live-owner resume checks | Not exported | Fresh/known-live-owner collision and native resume controls |
| Maintenance/update/rollback | Source staging and compatible runtime exchange, native doctor/Pi health, rollback and interrupted-exchange recovery passed | New-host adoption; dependency, entry-protocol and template migrations remain held |

Do not mark the whole installer accepted until every selected requirement has
its native evidence. Package tests and a successful deterministic lab demo do
not establish project quality, memory freshness or task authority. The local
SSOT controller still cannot issue `blessed`.
