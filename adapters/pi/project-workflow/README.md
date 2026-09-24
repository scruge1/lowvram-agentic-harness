# Pi Project Workflow

This directory contains the portable Pi coordinator layer qualified by the
project-lifecycle controls. It adds project identity, a project-local Hermes
board, capability discovery, project knowledge retrieval, external planning
advice, supervised file changes, closeout records, and project-local skill
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

- Pi coding agent with the extension API used by the TypeScript files.
- Python 3.9 or newer for the portable supervisor components.
- A dedicated Python environment containing `hermes-agent` 0.21.1 from commit
  `866332bfb52c46e543143b2620a9aeee8bce9c77` for `pi_kanban.py`.
- The reviewed portable task runtime from this repository or an equivalent
  runtime with a pinned manifest and `harness/enforcement.py` hash.
- Optional sessionless Codex wrappers for `codex-plan-consult.ts`. The wrapper
  contract is external to this package. Pi must treat its result as advice.

`pi_kanban.py` also checks the exact source hashes of the two Hermes modules it
uses. A different Hermes build fails closed until it receives an independent
review and the pins are deliberately updated.

## Install

Copy the files to one trusted directory on the Pi host. Copy these extensions
to the Pi extension directory, or link them from the trusted directory:

- `agent-capabilities.ts`
- `codex-plan-consult.ts`
- `everyday-workflow.ts`
- `pi-kanban.ts`

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
PI_CODEX_PYTHON=/absolute/path/to/python3
PI_CODEX_PLAN_WRAPPER=/absolute/path/to/codex_plan_consult.py
PI_CODEX_CAPABILITY_WRAPPER=/absolute/path/to/codex_capability_setup.py
```

`PI_PROJECT_STATE_BASE` and `PI_CODEX_PYTHON` are optional. Their defaults are
`~/.local/state/pi-projects` and `python3`. All other bindings are required.
Missing paths or mismatched hashes fail closed. Do not put credentials in these
files or variables.

Reload Pi after changing extension bytes or process environment. Use
`agent_capabilities` to confirm the configured and active tool registry. That
observation proves registration only, not tool health.

## Intended Flow

1. Call `project_admit` for the exact project root.
2. Call `agent_capabilities` and save its project-bound snapshot.
3. Query `system_tool_query` for relevant system capabilities.
4. Search local Pi MemPalace for validated lessons and recent session history.
   Use SystemPalace only as a wider implementation-history escalation.
5. Query project knowledge before planning.
6. Draft a plan and call `codex_plan_consult` on the exact active card.
7. Apply the returned critique as advice. Keep user authority and local tool
   capability separate from the adviser.
8. Execute each mutation through `workflow_step` or another reviewed supervisor.
9. Attach the verified receipt to the same card and use valid Hermes state
   transitions.
10. Prepare closeout, rebuild project knowledge, and persist validated lessons
   through an independently configured memory route.
11. Read the stored MemPalace drawer back exactly. Use
   `project_memory_candidate_prepare` to bind the verified closeout to that
   drawer. The immutable candidate is written under
   `.icm/workspace/wiki/memory-candidates/`, which the existing project index
   already includes. Reject source drift and sensitive summary text.
12. Compile a project-local skill candidate only from a verified closeout. Shared
   installation remains a separate review and promotion action.

`tool_knowledge.py` builds a hash-bound SQLite FTS catalog from maintained JSONL
capability registries. `system-tool-knowledge.ts` exposes read-only query and
status tools. Configure `PI_SYSTEM_TOOL_HELPER`, `PI_SYSTEM_TOOL_DATABASE`, and
`PI_SYSTEM_TOOL_HELPER_SHA256`. Catalog results are retrieval guidance. They do
not prove that a tool is installed, loaded, healthy, or authorized.

The coordinator can answer questions and inspect with native read-only tools.
The everyday gate blocks raw shell, write, and edit mutations. It requires an
actual native capability observation and exact delivered `SKILL.md` bytes before
supervised work. A failed run must be read from its saved failure record before
another workflow action.

## Qualification Boundary

Offline tests cover identity, knowledge, immutable skill compilation, private
binding removal, and source pins. The original host controls also covered native
tool blocking, reload/resume, dependency edges, exact-card audit routing,
closeout, memory round trip, and project-local skill compilation.

Those results do not qualify a new host automatically. Run native positive and
negative controls after installation. Do not infer Hunt-farm readiness, semantic
task completion, shared-skill promotion, physical-action authority, or proof
authority from this adapter.
