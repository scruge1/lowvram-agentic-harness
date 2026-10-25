# Agent-home installer

Status: development candidate. The bootstrap, request intake/task waits,
Framework binding, evidence-bound recovery, bounded native compaction, current
session capture, validated recall and hierarchical project context are implemented.
Native source tests and
fresh dependency setup are separate evidence. Remaining adoption boundaries
are retained below.

## Run from a repository checkout

Install Git and Python first. The dependency-free core supports Python3.9+.
The isolated full tool stack uses Python3.12 and Node22.19+.

```bash
git clone https://github.com/scruge1/lowvram-agentic-harness.git
cd lowvram-agentic-harness
python -m harness.home install --python312 /path/to/python3.12
```

The wizard asks for a new agent-home directory, local OpenAI-compatible endpoint
and exact model ID. It creates a dedicated home. Existing agent profiles,
memory databases, services and project directories are not migrated by setup.
Setup checks all 11 required templates before creating the home. Its Git-ignore
template is installed as `.gitignore`.
Choose storage with room for package environments, memory and embedding caches.
No agent model weights or GPU server are downloaded or started. Memory embeddings
have their own first-use download and readiness checks.

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
The default `full` profile includes Pi, the Hermes board, MemPalace, Agent
Framework, Claude-mem with Bun, and the Harness2 and DeepSeek laboratory packages.
Use the reduced `--profile pi` explicitly for Pi, the board, MemPalace and the
model-free Framework decision helper.
`--offline` on another profile retains the requested package list but does not
install it; doctor reports those dependencies missing.

Set `--context-window` and `--max-output` from the actual server configuration.
Defaults8192/2048 are unprobed configuration limits, not detected capabilities.
The installer sets native compaction reserves to fit the selected context.
Image input stays disabled until the selected model/projector path is tested.

After a failed installation, inspect the private command logs and exact failure.
Correct the cause, then use `agent-home.py resume-install --python312 <path>`.
Already recorded package steps are retained. Setup never overwrites a home or
automatically replays an uncertain external effect. An interrupted package step
is not automatically accepted from its directory's presence.

The first agent session uses `project_admit` for its project and `project_context`
for the relevant directory before execution. Read any remaining context windows
and let their exact results reach the next model-input context. A successful
context tool call alone does not open the gate for a sibling action in the same
tool-call batch. The existing task, pause, skill and effect checks still apply.

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
Git initialization is not the newer source-milestone enforcement feature.

## Pinned tools and readiness

Reviewed25October2026. Pins are candidates for this installer, not a promise of
complete native integration. Installed, running, tested and accepted remain
separate fields. Locks/freezes and full command logs stay in the private home.

| Tool | Exact selected artifact | Integration boundary |
|---|---|---|
| Pi | `@earendil-works/pi-coding-agent@1.4.0` | Local provider configuration; selected coordinator extensions |
| Hermes board | commit `866332bfb52c46e543143b2620a9aeee8bce9c77` | Existing pinned board adapter, no second dispatcher |
| MemPalace | `mempalace==3.11.0` | Home-owned palace and loopback single-writer hub; complete memory pipeline acceptance remains open |
| Microsoft Agent Framework | `agent-framework-core==1.21.0` | Isolated environment and exact target-bound read-only decisions; native board remains canonical |
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
The fresh default full installation passed on Linux as one normal command:
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
| Local model routing and isolated packages | Fresh full one-command Linux install, doctor and30-tool startup passed | Real selected-model request and new-host acceptance |
| Per-project Git and board creation | Implemented; native board/context composition passed35 checks | First ordinary project and outcome acceptance |
| Optional planning adviser, direct card select, saved navigation | Model-free native composition passed35 checks | Normal model-driven use |
| Linux owned-process execution | Reviewed guard exported | New-host positive, negative, timeout and owner-loss controls |
| Native request capture and exact intent/source routing | Coherent intake138 closure exported | Normal native input and mid-turn invalidation tests |
| Root outcome, hierarchy, triage leaf specification and cancellation | Current backend exported | Source-bound retained-work tests; no general root acceptance claim |
| Framework read-only decisions over the native board | Actual Framework/Pi/Hermes/context composition passed35 checks with a generated target binding | Normal model-driven use and root-outcome acceptance; no duplicate dispatcher/database |
| Quiet intake and compact live state | Intake source exported | Final-provider coverage; separate private task/comment refresh behavior remains unexported |
| Hierarchical project instructions and bounded checkpoint delivery | Current context gate exported;17 native groups,35 composition checks and30-tool startup passed | Model-driven use; no final-provider attestation |
| Read-loop containment and evidence-bound recovery | Read-loop079 and exact failure-read/recovery gates exported | Full native model-path adoption; matching recovery evidence/receipt only clears its own latch |
| Quiet session/task waits and receipt-driven one-time wakeups | Task-waits138 source exported | Watcher/race/pause/cancel/reload checks; interactive wakeup pilot still open upstream |
| Local-provider bounded native compaction | Public native API and exact target selectors exported | Native API tests passed with synthetic stream; real summary quality remains model-specific |
| Action failure dominates verifier success | Existing source needs newer ledger parity | Actual full host-action and model-facing result checks |
| MCP lifecycle and health | Native Pi1.4 connected47 tools; owned hub startup/idempotence/shutdown and connected recall passed | Long-idle reconnect and new-host lifecycle checks |
| Validated memory retrieval, exact chunks and promotion | Empty safe registry abstention and synthetic native capture/mining/exact readback passed | Reviewed promotion, new-host freshness and private-history acceptance |
| Pi/Codex/Claude session capture and raw archive distinction | Current-session Pi capture and local observer hooks exported | Existing Codex/Claude history imports remain opt-in; whole private archive/replica system is not copied |
| Source milestones, scoped commits and remote verification | Git initialization only | Portable source-checkpoint CLI/skill; automatic all-session attribution remains open upstream |
| Terminal/project navigation and live-owner resume checks | Not exported | Fresh/known-live-owner collision and native resume controls |
| Maintenance/update/rollback | Exact initial pins and retained failures | Candidate update, complete dependency closure, target activation and rollback |

Do not mark the whole installer accepted until every selected requirement has
its native evidence. Package tests and a successful deterministic lab demo do
not establish project quality, memory freshness or task authority. The local
SSOT controller still cannot issue `blessed`.
