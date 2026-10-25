# Applicable project context

`registerProjectContext(pi, { project: () => activeProject })` adds the current
hierarchical instruction and checkpoint gate. The coordinator supplies its
existing admitted project identity. This module creates no task store or
execution authority.

The `project_context` tool selects applicable ancestor instructions with Pi's
public `loadProjectContextFiles` API. It adds the admitted workspace's instruction
file, router and a checkpoint head of at most64lines/4KiB. It does not scan
sibling topics. Instruction files are delivered in source-hashed windows of
at most8KiB within a32KiB response. Documents above128KiB require a maintained
thin router. Native read-only instruction inspection remains available when
identity or routing needs repair.

Executing a read does not immediately open the gate. Its exact successful body
must reach a later model-input `context` hook. Same-batch reads, partial results,
path-only claims and changed sources do not establish delivery. Native-injected
instructions count only when both their path and exact current body occur in
the system prompt. Reload, branch navigation and compaction clear delivery
evidence. Project roots and instruction subtrees remain separate. Declared
execution directories and output subtrees must also have their context read.

## Native API binding

Set `PI_PROJECT_CONTEXT_PI_PACKAGE` to the absolute root of the installed
`@earendil-works/pi-coding-agent` package. Set `PI_CODING_AGENT_DIR` to the
selected agent profile. The standalone fallback for the agent directory is
Pi's normal user profile; no private machine path is embedded.

The package is pinned to1.4.0. `resolveReadPath` and `ensureTool` are internal
APIs, so `project-context-runtime.ts` verifies their exact published JavaScript
hashes before loading the actual installed modules. Node22.19 or newer is
required by Pi. The native Jiti loader is tested with this binding. These two
API pins are not an integrity claim for all transitive package dependencies;
the installer also retains its normal exact package/lock identity. Review and
qualify a new Pi release before changing these pins.

## Verification

Run the model-free native qualification against an isolated fixture directory:

```bash
node tests/test_pi_project_context.mjs \
  --pi-package /absolute/path/to/pi-coding-agent \
  --context /absolute/path/to/adapters/pi/context \
  --fixture-parent /absolute/path/to/owned-test-output
```

This exercises Pi's actual extension loader, tool-call runner, read and recursive
grep tools with explicit project fixtures. It checks body delivery, hierarchy,
bounds, UTF-8, source changes, reload, compaction, project switches, identity and
path escape refusals, and internal API drift. It makes no model requests and
does not establish model obedience, final-provider attestation or project
acceptance. The owning coordinator still applies task/source admission,
pause, failure, skill and effect checks.
