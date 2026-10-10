# Agent-Led Integration

Use this path when an agent will install or refactor the package into another system.
Do not ask the agent to copy an adapter and report success.

## Find the target authority first

Before running the bootstrap, read the target's root and subtree instructions and
locate its existing PRD, ledger, SSOT, deployment workflow, or equivalent authority.
If one exists, add the packaged setup requirements and stages to that authority. Do
not run the new-project bootstrap.

The command detects this package's `ssot-project.json` and `.ssot` names. It cannot
semantically identify every custom ledger name. Authority discovery is therefore an
explicit precondition, not an inferred guarantee.

## Codex command-hook adapter

Use `--host generic` for Codex integration. Its native hook names can differ
from the function names visible to the model: shell calls and `exec_command`
match `Bash`; patch calls match `apply_patch`, `Edit`, or `Write`.

For example, this project-local configuration selects the reviewed command
policy. The policy script must already exist; this package does not install it.

```json
{
  "hooks": {
    "PreToolUse": [{
      "matcher": "^Bash$",
      "hooks": [{
        "type": "command",
        "command": "python3 /absolute/path/check_command.py",
        "timeout": 10
      }]
    }]
  }
}
```

Replace the command with the target's reviewed interpreter and script invocation.
A command policy can return this structured rejection:

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Rejected by the reviewed command policy."
  }
}
```

Review the actual project admission and current hook definition before use.
A listed handler is not execution proof. Qualification needs its native event,
the expected input and rejection reason, and evidence of the resulting effect.
A backend failure alone is not a successful hook rejection. Keep fixture results
separate from ordinary profile use and other tool paths.

Inspect effective admission as well as configuration. For example, native
registry metadata can contain both:

```json
{"enabled": true, "trustStatus": "untrusted"}
```

This handler is configured but lacks the required trust. It does not establish
that its registration or policy ran. Use the target's supported admission path
and retain the exact reviewed definition. Do not grant trust merely to clear a
warning. A later readiness result does not establish a past hook invocation or
successful task. Recheck the actual event and result on the intended route.

These examples add no runtime enforcement to this package. Consult the current
[Codex hook documentation](https://learn.chatgpt.com/docs/hooks#tool-coverage)
for supported names, trust requirements, and coverage limits.

## Check byte edits before deriving a pinned source candidate

Python's `bytes.replace` silently returns unchanged bytes when its source value
is absent. A successful filename edit and inverse comparison can therefore hide
a missing pin edit. Use the optional pure helper for an expected single edit:

```python
from harness.source_edit import replace_exact_once

source = b"PIN='old'\n"
candidate = replace_exact_once(source, b"PIN='old'", b"PIN='new'")
```

Missing, repeated and overlapping matches, empty needles, unchanged edits and
non-byte inputs are refused. An explicit deletion is allowed with `new=b""`.
The helper returns bytes; it does not read, write, publish or start anything.

Check each intended edit, not just the final inverse comparison. If a pin comes
from a parent map and is absent from the local source, use an explicit reviewed
map override and verify the complete selected map and its cardinality. A token
match does not establish semantic pin coverage, admission or runtime behaviour.
Keep the target's existing candidate hash, protected publication, native startup
and rollback checks. This package does not install the helper into a target.

## Check the tool contract that the model actually receives

Installed plugin bytes and an unchanged core version do not prove that a
conversation uses the new tool schema. A host can intentionally restore saved
definitions after rebuilding an agent. Compare the target function hash at the
actual request boundary with the reviewed definition and the saved session pin.
Missing observations remain unknown. Keep intentional pinning for other tools.

The optional pure `harness.tool_schema.migrate_known_tool_schema` accepts one
reviewed old-to-new function hash, one tool name and one exact scope. Unknown
scope, hashes, shape or unavailable fresh definitions return the original pin.
A matching case returns an independent JSON snapshot; inputs stay unchanged.
Only ordinary `{"type": "function", "function": ...}` definitions are supported,
bounded to128KiB after JSON serialization. `tool_function_sha256` hashes the
canonical UTF-8 JSON **function field**, excluding the fixed outer wrapper.

The host supplies authenticated scope and reviewed expectations. Model output
cannot establish these values or raise authority. The host must first confirm
that the fresh definition is registered and enabled, preserve other definitions
and their order, and retain admission and execution checks. Returning a schema
does not persist it. Verify the native saved pin and actual forwarded function
hash before calling adoption complete. The helper performs no IO, reset, reload,
session creation or execution and does not provide a concurrent admission fence.
An explicit required argument is a contract declaration; observe actual caller
arguments and successful use before claiming compliance or enforcement.

## Keep runtime and CI dependency locks aligned

When a target already uses fully pinned Python runtime and CI locks, qualify them
through its existing maintenance and release owner. This optional checker reads
two explicit files and fails if a runtime package is absent from CI, its version
differs, or a runtime distribution hash is missing from CI:

```bash
python -m harness.runtime_lock --runtime /path/to/requirements.lock \
  --ci /path/to/requirements-ci.txt
```

CI-only test/build packages and additional distribution hashes are allowed.
Supported input is UTF-8 text with `name==version` pins, SHA-256 hash lines,
comments and optional continuation backslashes, up to 2 MiB per file. Duplicate
normalized package names, unhashed pins, URLs, includes, ranges and conditional
markers are refused. Compile a supported target-specific lock first; the checker
is not a general requirements resolver or semantic version comparator.

Run it before dependency installation on the existing CI path if the owner adopts
it. It does not install packages, change locks, inspect a running image, or select
runtime successors. Matching source locks does not prove interpreter, platform,
installed package or deployed image parity. Retain the normal build, actual image
and rollback checks. This package itself has no required third-party core lock.

When source advances, inspect current tests and their actual invocation. A
standalone fixture's `__main__` path may need explicit execution alongside pytest.
Preserve assertions and isolation when repairing fixture imports or dependencies.
An older green check remains tied to its original source, runtime and test scope.

## Create the target setup SSOT

Run the bootstrap against the root that contains the system being changed:

```bash
trusted-task-integrate \
  --root /path/to/target-system \
  --host claude-code \
  --surface AGENTS.md \
  --surface .claude/settings.json \
  --component enforcement \
  --component ssot
```

Use only existing target-relative files for `--surface`. At least one exact target
instruction or authority surface is required. Repeat the option for every instruction
or configuration input already known to the operator. Valid hosts are
`claude-code`, `hermes`, `pi`, and `generic`. Valid components are `enforcement`,
`ssot`, `local-inference`, and `research`.

Without an installed console command, run:

```bash
python -m harness.integration --root /path/to/target-system --host generic \
  --surface README.md
```

The command creates three target-root files without overwriting anything:

- `trusted-task-integration-prd.md`: the complete portable setup requirements;
- `trusted-task-integration-target.json`: selected host, components, declared
  target surfaces, and exact bootstrap hashes; and
- `ssot-project.json`: a source-bound but deliberately unresolved SSOT scaffold.

If the target already has `ssot-project.json` or `.ssot`, the command stops. Add the
setup requirements and stages to that existing authority instead of creating another
one.

## Instruction to the integrating agent

Give the agent this exact task:

> Read the target's instruction hierarchy first. Then read
> `trusted-task-integration-prd.md`, `trusted-task-integration-target.json`, and
> `ssot-project.json`. Preserve every SETUP requirement. Discover the target's real
> harness, hook, retry, research, verification, completion, bypass, rollback, and
> writeback paths. Replace the unresolved row with a target-specific lossless
> inventory. Configure dependency-ordered stages, unique receipts, exact verifiers,
> same-program negative controls, and independent acceptance. Run `blessed-ssot
> --root . doctor`. Do not change the target while doctor is red. Have a separate
> reviewer compare the compiled inventory with every setup and target authority
> source; a green doctor checks structure, not semantic completeness. Execute only
> the current frontier and retain every failed or abandoned run. Do not report the
> integration complete until live positive, negative, bypass, interruption,
> rollback, and whole-project acceptance gates pass.

## Expected progression

```text
scaffolded -> compiled -> configured -> enforced -> tested
```

The integrating agent may add target-required stages. It must not skip the candidate
order in the setup PRD without recording a verified dependency reason.

Package tests prove the shipped implementation. They do not prove that a target hook
loads, a target harness obeys it, all completion paths traverse it, rollback works,
or the user's system accepts the integration. Those claims need target-local receipts.

Local setup ends at `tested`. A protected external signer or receipt custodian is
required before any deployment may use `blessed` as cryptographic authority.
