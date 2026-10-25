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
Setup checks all required templates before creating the home. Its Git-ignore
template is installed as `.gitignore`.
Choose storage with room for package environments, memory and embedding caches.
The bootstrap requires at least8GiB free before runtime provisioning; this is
headroom for that step, not a complete model/package capacity estimate. Keep the
permanent `HOME-runtimes` sibling: installed environments use its Python. Runtime
downloads resume with exact size/hash checks. Conflicts and failed partials are
retained. Global Python, Node, PATH and shell profiles are not changed. See the
[runtime sources and licences](harness/BOOTSTRAP-NOTICES.md).
The default attachment route downloads no agent model weights and starts no model
server. Memory embeddings
have their own first-use download and readiness checks.

Use `bash install.sh --home /data/my-agent --plan` for the read-only plan.
Use `--yes` to accept that displayed runtime plan in an unattended install, and
pass the existing install options directly after it. For example:

```bash
bash install.sh --home /data/my-agent --yes --profile agent \
  --base-url http://127.0.0.1:8080/v1 --model my-local-model --name Owner
```

For an opt-in local CPU candidate, without an existing endpoint:

```bash
bash install.sh --home /data/my-agent --local-cpu --plan
bash install.sh --home /data/my-agent --local-cpu --yes --name Owner
```

This route selects the exact Qwen3-VL-8B-Instruct-Q4_K_M text-only artifact
and native llama.cpp CPU release in `harness/model-service-pins.json`. Their
downloads total5,050,222,955bytes, in addition to Python, Node, agent packages,
browser and memory embeddings. Package/browser totals are unknown before
resolution. Setup requires at least eight available affinity/logical CPUs,
20GiB available RAM and20GiB free storage,
with additional headroom for later use. It uses eight CPU threads and eight batch
threads, one slot, context32768/output4096, no GPU layers and no cloud fallback.
The CPU count follows process affinity when available; it is not an exclusive
reservation or a speed guarantee.
These are explicit candidate settings, not detected fit, speed or accepted
agent task capability. The previous two-thread32K/4K report attempt failed the
600-second agent task during input prefill, with no generated report. This
eight-thread recipe is the next candidate and requires the same task qualification.
Native protocol/lifecycle evidence does not establish useful task quality.
This route does not supply a vision projector.

`--plan` creates nothing. The confirmation, or `--yes`, covers the displayed
downloads and owned model start. Managed Python checks the canonical pins and
resources before model transfer. Only `--name` and `--profile agent|pi` can be
combined with `--local-cpu`; endpoint/model/budget/transport overrides, `full`,
offline mode and resume/runtime-only modes are refused. The existing endpoint
attachment route remains the default.

Setup uses the existing owned service and factory: start before home creation,
capture the nonsecret binding, exact stop, normal package installation, then
same-port restart with the child's home lease and a fresh private key. Successful
setup leaves the model running. Use the installed managed command to launch Pi.
For model status or explicit stop, change to `HOME/runtime` and use the managed
Python: `PYTHON -m harness.model_service status --home HOME` (replace `status`
with `stop` to stop it). `PYTHON` is the managed interpreter path printed during
bootstrap. No key is printed or stored in `models.json`.
This route does not change global services, PATH or OS HOME.

If CPU setup fails, preserve `HOME-runtimes/installer-handoff.json` and
`HOME-runtimes/state/model-service/` (including `setup.json` when present).
Inspect the reported stage and native status before explicit recovery. A prior
handoff blocks replay through `--local-cpu`; this frontend adds no automatic
rollback or retry. For a partial home, use the existing doctor/resume-install
route below, then review the owned service's same-port restart separately.

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

Inside a managed Pi session, `project_create` accepts only `{"name":"example"}`.
It calls the same home factory as the CLI above: the new project is placed under
`HOME/projects/example` with its own Git root, instructions, ignore rules and
isolated ICM/board. It selects that project and clears the previous task and
discovery observations. It does not create a ready card or grant execution;
context, source intake, capability, memory and knowledge gates still apply.
A successful creation already selects the project, so another admission is not
needed just to continue setup.

Names begin with a letter or digit and contain only letters, digits, hyphens or
underscores (80 characters maximum). The tool cannot choose another path, home,
configuration or authority. Existing destinations, redirected project parents and retained project-state
namespaces refuse. A missing directory is not proof that its old board is gone. Use `project_admit` without `initialize` to adopt an existing project;
that existing route does not add Git or replace its instructions.

Creation uses the existing Linux home lease and process-owner guard. Its
90-second operation budget and105-second tool deadline apply to creation only.
On failure or cancellation, selection is cleared and any partial
project remains intact. Inspect its Git, instructions and ICM/board before
read-only adoption. Do not automatically delete, recreate or reinitialize it.
Actual Pi/Hermes inert checks covered creation, isolation, failure and cancellation
without a model request; choosing and using the tool in a model task remains
separate acceptance.

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
survive rollback. Dependency, other entry-protocol and template migrations remain held.
The reviewed research CLI controller slice below has a separate explicit route.

### Explicit research CLI controller migration

The Linux `controller-cli-v1` route adds the reviewed research CLI to an existing
controller. It accepts the pinned prior/new `main` and new `CommandParser`
definitions. All other `home.py` definitions, constants, profiles, package pins
and layout must match. The stable entry, lifetime guard, maintenance protocol and
Framework binder stay fixed. Ordinary compatible updates keep their existing
`FIXED_SOURCE` refusal policy.

Stage the complete reviewed source through `harness.maintenance` first. Run the
new controller from that exact reviewed checkout, rather than asking an older
installed controller to interpret a new command:

```bash
python -B /path/to/reviewed-checkout/harness/runtime_update.py --home HOME \
  controller-plan --operation ID
python -B /path/to/reviewed-checkout/harness/runtime_update.py --home HOME \
  controller-apply --operation ID --expected-plan PLAN_SHA256 \
  --qualification /path/to/controller-qualification.json \
  --qualification-sha256 CONTRACT_SHA256 --execute-qualified-runtime
```

The qualification schema remains `agent-home-runtime-qualification/v1`, with
scope `controller-cli-v1`. Copy the exact plan bindings `home`, `operation`,
`stage_receipt_sha256`, `candidate_sha256`, `active_sha256` and `controller`, plus
`qualified: true`, `execution_authorized: true` and retained reviewed evidence
paths/hashes. The controller binding includes old/new protected source hashes,
the executing closure and interpreter, and the retained recovery-controller path.
These fields record an explicit review; writing the contract is not that review.

Stop this home's consumers, including its owned model service and memory hub,
before activation. Apply does not restart services or change model settings.
For consumer verification, use the existing owned-service lifecycle if this home
requires its local server, then run the retained candidate controller:

```bash
python -B RETAINED_CANDIDATE/harness/runtime_update.py --home HOME \
  controller-verify --operation ID --expected-journal CURRENT_JOURNAL_SHA256
# Stop the home's model service and memory hub before rollback.
python -B RETAINED_CANDIDATE/harness/runtime_update.py --home HOME \
  rollback --operation ID --expected-journal CURRENT_JOURNAL_SHA256
```

Verification runs the actual stable doctor, read-only `research status` and normal
managed Pi `/agent-health`. Research status must contain the complete redacted
five-provider v1 contract, a real canonical ISO date and the known limits text;
unknown fields and `tested: true` refuse acceptance. No provider request or model
inference is needed. An old verifier refuses the controller pending/failure
states. An incomplete exchange keeps the existing entry-blocking sentinel; use
that retained controller's existing `recover` command with the current journal
hash. Do not replay apply or edit the sentinel. Rollback preserves personalized
files, sessions and new user data and restores the exact predecessor source and
bindings.

The reviewed controller source at `d00415fe4974bdf4d6480dc10cfbea161f6343aa`
passed an isolated installed-home migration, stable doctor, redacted research
status, normal managed Pi health and rollback check without model generation.
Rollback restored the exact predecessor and preserved personalized bytes plus
a file created after activation. The owned model service and memory hub stopped,
and exclusive home leases passed. This qualifies that controller source; the
later research-budget changes and new hosts require separate native evidence.

### Explicit agent core-source update

The separate `agent-core-source-v1` scope admits the reviewed source40 core to
source41 observer-install hooks. It requires an integrated Linux `agent` home
with the same five selected and installed packages: Pi, Hermes, MemPalace,
Framework and research. It changes runtime source only. It does not install Bun
or Claude-mem, start an observer, change package pins/profile/trust or render
templates over personal files. Observer package records or partial package
artifacts refuse this scope; ordinary settings-only directories remain data.

The controller pins six old/new function AST pairs and one added helper, then
requires every remaining home definition, CLI, constant and import to match.
Stable entry, lifecycle, maintenance and Framework binder bytes stay fixed.
The existing `gitignore.template` packaging exception accepts only its reviewed
source bytes; the home's personalized `.gitignore` is preserved. Actual payload
hashes remain distinct from AST comparison and line-ending normalization.

Stage through the existing maintenance route first, then use the exact reviewed
new controller checkout:

```bash
python -B /path/to/reviewed-checkout/harness/runtime_update.py --home HOME \
  core-source-plan --operation ID
python -B /path/to/reviewed-checkout/harness/runtime_update.py --home HOME \
  core-source-apply --operation ID --expected-plan PLAN_SHA256 \
  --qualification /path/to/core-source-qualification.json \
  --qualification-sha256 CONTRACT_SHA256 --execute-qualified-runtime
```

The qualification schema remains `agent-home-runtime-qualification/v1`. Use
scope `agent-core-source-v1`; bind the exact plan's `home`, `operation`,
`stage_receipt_sha256`, `candidate_sha256`, `active_sha256` and `core_source`, plus
reviewed evidence and explicit execution authorization. `core_source` includes
the old/new source, five-package fingerprints, executing recovery closure and
interpreter. Ordinary compatible and CLI-only contracts cannot authorize it.

Apply uses the existing stopped-consumer EX transaction and ends pending.
Run `core-source-verify` from the retained candidate controller with the current
journal hash. It checks the stable doctor, full redacted `research status` and
normal managed `/agent-health` with zero generation requests. Package drift or
consumer failure preserves a distinct unaccepted state. Recovery and rollback
reuse the existing commands and require the retained core controller/interpreter
and unchanged package bindings. Stop the home's consumers before either route.

This is a narrow source frontier. It does not combine the older research CLI
migration with core changes or authorize other installed profiles. The exact
source passed hosted Linux and Windows release gates. A separate isolated Linux
home passed actual core plan/apply/verify and exact predecessor rollback, with
the real prior verifier refusing the new pending generation. Normal doctor,
research status and native Pi health passed with zero generation requests.
The five package bindings and protected fixture files stayed unchanged; a file
created after activation also survived rollback. The owned memory hub stopped,
the exclusive lease passed, all watched donor files were preserved and the inert
loopback endpoint received zero HTTP requests.

That native evidence uses verified borrowed dependencies. It qualifies source
adoption and rollback for that fixture, without observer installation, memory
retrieval, model task quality or fresh installation claims. Other hosts and package
profiles still require their own qualified adoption.

The first agent session uses `project_admit` for its project and `project_context`
for the relevant directory before execution. Read any remaining context windows
and let their exact results reach the next model-input context. A successful
context tool call alone does not open the gate for a sibling action in the same
tool-call batch. The existing task, pause, skill and effect checks still apply.

For an already admitted project, `project_prepare({query: "relevant task terms"})`
delivers callable capabilities, relevant system tools, validated memory, project
knowledge and missing instructions through their existing native readers. An
optional `path` selects the relevant directory. Read omitted or unavailable
sections with the existing tools, and follow context `remaining_reads`. The
bounded packet must reach later model context unchanged before its observations
count. It does not admit a project, select a task or grant permission.

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
Text/JSON modes are supported. On Linux, use the managed continuation selector:

```bash
/chosen/agent-home/bin/harness-agent --continue --project /path/to/admitted-project
python /chosen/agent-home/agent-home.py start --continue --project example
```

The selector precedes Pi arguments. It uses Pi1.4's native recent-session lookup
inside this exact home/project bucket. An empty bucket returns
`no_previous_session`; a live writer returns `session_busy`. The launcher never
silently starts fresh for either refusal. Fresh and continued launches retain
an exclusive bucket lease through the actual Node lifetime, alongside the home
lease. Saved history does not grant current task authority; context and execution
gates still run. Current version3 newline-terminated history is supported;
legacy, malformed, redirected or wrong-project history is preserved and refused.

RPC, global session pickers and raw Pi `--session`, `--resume` or `--continue`
overrides remain refused. This is cooperative Linux ownership with read-only
checks for recognized unmanaged CLI owners. Hidden independent SDK writers are
outside that contract. Windows/macOS keep core inspection without this lease.
Windows command registration requires an ASCII Python interpreter path;
Unicode home and bin paths are tested. Existing homes need an explicit runtime
update before using the new command; this release does not migrate them.

Nineteen actual Linux CLI checks passed with an observer in an isolated profile
and unchanged borrowed dependencies. These establish native prompt routing,
tools, memory and cwd/session bindings. A later23-check native test also passed
actual managed cold continuation for home and project sessions, prefix/history
conservation, empty-history refusal and a live-writer collision. It used two
isolated pi-profile homes and exact borrowed dependencies without package
installation, provider HTTP or model calls. Real model continuation remains
separate acceptance.

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
for the home-configured provider cascade, `fetch` for public HTTP extraction, `render`
for a clean read-only Chromium context and `read` for saved evidence windows.
DuckDuckGo works without a key. [Optional provider setup](RESEARCH-SETUP.md)
provides official signup links and hidden terminal entry:

```text
python /chosen/agent-home/agent-home.py research setup
python /chosen/agent-home/agent-home.py research status
```

Only explicitly enabled providers are considered. Skip overrides an environment
key, and Brave stays held until storage rights cover artifacts and session
history. The model tool cannot accept keys, change provider settings or approve
rights. No personal browser profile, cookies or stealth service are used.

The source port is deliberately identified by what it contains:

| Existing script | Public adaptation | Remaining scope |
|---|---|---|
| `scripts/rig/search_core.py` | URL identity/domain grouping and configured provider request, cooldown, relevance and coverage policy | Search coverage does not establish factual corroboration |
| `scripts/rig/godmode_miner.py` | HTML/redirect provenance and source-bound schema-shard claim mining | Question-to-consensus orchestration remains separate |
| Existing browser workflow | New guarded Playwright adapter and project evidence cache/pager | The complete private browser service is not bundled |

Raw session calls and failures are reviewed privately. Public regressions use
synthetic queries and credentials; no private transcript, profile or corpus is
part of the installation.

Fetch retries eligible transient failures within one total budget. Published
arXiv HTML/abstract representations are labelled separately. Thin, successful,
unchallenged HTML can use the clean browser automatically. `allow_archive=true`
permits an eligible public archive fallback; it defaults to false. Authentication,
challenge and policy denials are retained. These fallbacks do not bypass them.
Search defaults to30 seconds, fetch to60 and direct render to40. Fetch accepts an
explicit `timeout` up to120 seconds; search and direct render accept up to60.
The default budgets stay unchanged. Fetch reserves30 seconds for native browser
settlement and at least10 seconds for browser work when the total budget permits
it. Static candidates and retries share the remaining phase. A smaller static
budget can time out before readable HTML arrives; that does not authorize a
browser request. Results retain the budget allocation and actual attempts.
These are individual network-operation budgets, not an agent-session deadline.
Partial source scope and actual selected URL remain visible in cached results.

```json
{"action":"search","query":"Python unittest documentation","max_results":3}
{"action":"fetch","url":"https://docs.python.org/3/library/unittest.html"}
{"action":"fetch","url":"https://example.org/public-javascript-page","timeout":120}
{"action":"read","artifact_id":"sha256:RETURNED_64_HEX_DIGEST","view":"text","offset":0}
```

Use `mine` after fetching evidence. It reads1–4 cached fetch/render artifact IDs;
it does not perform another search or fetch. Supply a research question and
1–32 distinct extraction fields. The tool uses the home's actual selected local
model through Pi's native model registry and request-time authentication. A
foreign/virtual model, changed selection/session, changed model configuration or
changed source binding refuses publication. No endpoint or key is accepted in
the tool request. An owner-selected local endpoint is not proof of a proxy's
upstream inference provenance.

```json
{"action":"mine","artifact_ids":["sha256:RETURNED_64_HEX_DIGEST"],"query":"What failure does this method address?","extraction_schema":["mechanism","failure_mode"],"timeout":900}
```

Mining uses shards of at most8 fields, at most1,000 output tokens per request,
and the first14,000 characters of each captured source. Truncation and the
original source scope remain explicit. Every accepted quote must occur exactly
inside the supplied window; offsets refer to that window in the cached source.
Source, actual selected model/transport, schema, prompt and operation budget are
hash-bound. `recall_bias=HIGH` retains background relevance; the default requires
on-topic claims. This is claim extraction, not verified consensus.
The character limit is not a token estimate or a promise that every local model
can fit this request. Native context/transport errors and length termination
remain failures; the tool does not raise the model's configured limits.

Malformed output, unavailable model, length termination, cancellation, deadline,
zero accepted claims and low analysed-shard yield remain typed failures. Partial
claims and failure records are retained, but failed runs mark no sources seen.
The first transport failure stops further shards; there is no automatic replay.
`timeout` is the declared mine-operation budget, default300 seconds and at most
86,400, with up to30 seconds for native ledger settlement. It does not cap the
session. A successful unchanged result can be supplied as `resume_artifact_id`
on the same mine request; this reuses the stored result without another model
call. Changed inputs or a failed result cannot qualify as a successful resume.
Cancellation before publication aborts the successful finish path. Cancellation
or admission drift observed after atomic publication holds delivery; the old
bound immutable artifact can remain for inspection. It grants no current-project
authority. Do not automatically resume or replay an uncertain operation.

Offline schema/span/identity tests and a native Pi serializer probe with
synthetic responses qualify the source path. They do not establish local model
quality or the complete question-to-consensus research journey.

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

A later joined-source check recovered84,191 characters from static extraction
and cached pages. Its DDG request timed out at20 seconds. A JavaScript fallback
failed after the preceding static request consumed most browser work time.
The phase allocation and explicit caller budget address that measured limit;
they do not establish successful acquisition from that site or full suite parity.

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

An isolated Linux component run qualified the actual Bun1.4.4 and patched
Claude-mem13.29.0 foreground lifecycle: startup and health, exact owned process,
source, data, listener and READ lease, empty drain, stop and exclusive cleanup.
Foreign-port and persisted-registry refusals passed. It recorded zero model
POSTs and capture hooks. Only two copied public packages were installed; seven
selected packages remained uninstalled. Full installation/profile admission,
generated capture and useful recall remain separate acceptance requirements.
An empty queue does not establish generation or recall quality.

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

The owned-runtime shell path has also been exercised on a fresh Linux home.
Fresh Python/Node provisioning and all five default packages passed without
borrowed environments. Network SSL failures were retained; explicit normal
installer resume completed the remaining packages in251.778 seconds. Normal
managed Pi health, stable doctor and exact owned-hub shutdown passed afterward,
without a generative request. The complete resume/health/shutdown check took
272.690 seconds. This does not claim an uninterrupted download/install or a
successful model-led project.

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

## Prepare the first checked report

After package setup, run and check a new report through the normal managed
agent from any directory:

```bash
/data/my-agent/envs/hermes/bin/python -B \
  /data/my-agent/runtime/harness/first_project.py run \
  --home /data/my-agent --name first-report
```

This explicitly invokes the configured local model with the existing home,
project and workflow gates. Native JSON output streams first, followed by a
final host JSON report; `--mode text` changes only the native stream format.
The parent retains the original manifest hash/check argv and home lease through
the launch and independent check. A failed child remains failed even when its
report passes the predicates. Files and partial projects remain in place. The
helper does not retry, resume or replace the configured model/server settings.
Its final report gives the exact installed managed command to reopen that
project. Explicit continuation is available only on the qualified Linux route.
A predicate pass still requires semantic review and inspection of the actual
model/workflow trace; fixture output is not model acceptance.

The helper selects the project identity that preparation already created. Its
prompt supplies the exact read-only admission arguments. The owner display name
and report manifest hash must not replace that identity's authority or hash.

The normal managed Pi session has no fixed ten-minute deadline. The earlier
600-second qualification runs were smoke-test budgets, not a maximum duration
for long-horizon work. A time budget exhausted before a checked result leaves
quality unassessed. Session, individual action and verifier budgets are separate;
hour-scale work needs an explicit suitable budget and preserved progress.

For supervised file work, `workflow_step` accepts `action_timeout_seconds` and
`check_timeout_seconds`. Set these for the expected operation, including related
substeps. For example, use `7200` for a two-hour action and `300` for each check.
The defaults remain585 and45 seconds. Each declared value must be an integer
from1 through86385; the host reserves15 seconds within the existing24-hour
command limit and derives the outer deadline from both checks and cleanup.
The plan and host result retain these budgets. Cancellation and failed-action
recovery keep their existing rules; extending a budget does not replay work.

For preparation without a model request, use:

```bash
python /data/my-agent/runtime/harness/first_project.py prepare \
  --home /data/my-agent --name hardware-report
```

It creates a new project through the existing Git/board path and captures
measured inventory plus configured model metadata. Missing observations stay
unknown. It writes `FIRST-PROJECT.md`, `hardware-facts.json` and a pinned
`first-project.json`. Retain the returned original `manifest_sha256` and exact
`check_argv`; use that argv as the read-only `workflow_step` verifier. The checker
reads relative to the project cwd, so an empty-directory negative control fails.
Do not recompute a replacement pin after inputs change.

Open the prepared project with the managed agent and request its report. The
checker requires exact facts and units, unchanged inputs and250–400 Unicode word
tokens. Semantic interpretation still needs review. A passed checker does not
establish model fit, service ownership, GPU selection or whether a later tuner
was executed. Preparation makes no model request and starts no services.

The first real report pilot produced a source-bound artifact, but exceeded its
requested word limit and needed scope corrections. This maintained pattern
checks those constraints during the task. Its Linux system/managed-Python tests
passed11 controls each; Windows passed10 with one symlink skip. Seven later
native checks passed through the actual installed helper, Git/Hermes identity,
original input/manifest hashes and missing-report/empty-directory refusal. That
isolated pi-profile home used four exact accepted dependency prefixes. Its hub
stopped and watched donor files stayed unchanged, with zero model/provider HTTP.
A model-produced report through this exact pattern remains separate evidence.

## Explicit owned-service installation handoff

For an already reviewed CPU service started before its new home exists, capture
the nonsecret selection and pass it to the existing home factory:

```bash
python -m harness.model_service_handoff --home /data/my-agent > selection.json
python -m harness.model_service_setup --home /data/my-agent \
  --selection selection.json --source /path/to/lowvram-agentic-harness \
  --python312 /data/my-agent-runtimes/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12 \
  --managed-node /data/my-agent-runtimes/node-v22.23.2-linux-x64/bin/node
```

Use the Python and Node paths returned by this home's reviewed runtime bootstrap.
This advanced route chooses no model and downloads no model weights. It requires
the explicit provisioned service and at least32768 context/4096 output tokens;
the smaller protocol-only smoke profile is rejected before stopping or creating
anything. Agent and Pi profiles are supported; observer/full and GPU setup remain
held. These prerequisites do not establish model quality or hardware fit.

The factory verifies the selected process lifetime before stopping it, retains
the existing service admission lock while creating/installing/checking the home,
then restarts on the same port under the installed home's lifecycle read lease.
An unexpected competing service is preserved and incompatible readback refuses.
Pi uses its native `$NAME` API-key provider. Only the final Pi child receives the
current runtime nonce. The secret is absent from models.json, setup selections
and command arguments; do not print a child environment or private api-key file.

Setup state remains in the permanent runtime sibling's
`state/model-service/setup.json`. Failed or interrupted setup is not replayed.
Inspect that record and service state, use the existing `doctor`/`resume-install`
for a partial home, then review an explicit same-port restart. The retained
failure does not authorize rebind, rollback, another model or shared-service work.
Source sequencing and ownership checks are separate from actual native factory
acceptance and a useful model-produced first project.

## Advanced owned inference candidate

`harness.model_service` provisions exact upstream llama.cpp and GGUF artifacts
inside the selected home's storage. It supports explicit plan, provision,
start, status and stop operations. It uses the permanent bootstrap sibling
before the agent home exists. The model pin JSON is included as exact static
data in the installed runtime and Python package.
Native start uses the complete checkout or generated agent runtime, which supply
the source-bound process helper.

One CPU-only native test used the pinned Qwen3-VL8B Q4_K_M text route with
context4096, output32, two threads, two batch threads and one slot. Startup took
9.740 seconds; one request returned four output tokens in2.769 seconds. Peak
sampled RSS/HWM was9,040,150,528 bytes. Exact process/socket/lifetime-lease cleanup
and original model preservation passed. This establishes protocol and lifecycle
for that fixture. Agent tool use, coding quality, vision, an8GB GPU profile and
a default newcomer model remain unqualified.

For a reviewed serving experiment, provision runtimes first with
`bash install.sh --home /data/my-agent --runtimes-only`. In the repository, use
that permanent Python to create the explicit selection:

```bash
AGENT_RUNTIME_PY=/data/my-agent-runtimes/python/cpython-3.12.13-linux-x86_64-gnu/bin/python3.12
"$AGENT_RUNTIME_PY" - <<'PY'
import json
from pathlib import Path
from harness.model_service import specification
selected = specification(model="qwen3vl-8b-instruct-q4-k-m", backend="cpu",
    context=4096, max_output=32, threads=2, batch_threads=2,
    ram_required_bytes=12 * 1024**3)
with Path("/data/my-agent-runtimes/model-selection.json").open("x") as stream:
    json.dump(selected, stream, indent=2)
PY
"$AGENT_RUNTIME_PY" -m harness.model_service --home /data/my-agent plan \
  --specification /data/my-agent-runtimes/model-selection.json
"$AGENT_RUNTIME_PY" -m harness.model_service --home /data/my-agent provision \
  --specification /data/my-agent-runtimes/model-selection.json --allow-download
"$AGENT_RUNTIME_PY" -m harness.model_service --home /data/my-agent start
"$AGENT_RUNTIME_PY" -m harness.model_service --home /data/my-agent status
"$AGENT_RUNTIME_PY" -m harness.model_service --home /data/my-agent stop
```

Review the plan's exact download sizes, hashes, licences and free-space checks
before `--allow-download`. A matching local artifact can be supplied with
`--source ARTIFACT_NAME=/absolute/file`; it is copied and hash-checked. Start
checks the declared available RAM. Status identifies the owned loopback route
and private API-key file without printing its secret. PID identity, socket
ownership and inherited lifetime leases protect the explicit owned stop path.
The stable home lease blocks runtime exchange while this consumer is active.
CUDA execution stays held until an atomic resource-owner admission route is
qualified. Agent-home model attachment and qualified first-project behavior
remain separate work; the ordinary installer still attaches an existing service.

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
| Terminal/project navigation and live-owner resume checks | Native same-home/project continuation, bucket leases and23actual managed CLI checks passed | Real model continuation and new-host adoption; raw pickers/RPC remain held |
| Maintenance/update/rollback | Source staging and compatible runtime exchange, native doctor/Pi health, rollback and interrupted-exchange recovery passed | New-host adoption; dependency, other entry-protocol and template migrations remain held |

Do not mark the whole installer accepted until every selected requirement has
its native evidence. Package tests and a successful deterministic lab demo do
not establish project quality, memory freshness or task authority. The local
SSOT controller still cannot issue `blessed`.
