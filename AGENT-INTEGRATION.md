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
