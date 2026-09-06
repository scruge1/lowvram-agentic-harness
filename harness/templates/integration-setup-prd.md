# Trusted Task Integration Setup PRD

This PRD governs installation and refactoring into one specific target system. The
integrating agent must preserve every requirement below in the target's SSOT
inventory. It may parameterize paths and harness names. It must not delete controls.

## Authority boundary

- `SETUP-001`: Initialization creates a source-bound `scaffolded` project only. It
  does not prove that the package is installed, connected, enforced, tested, or
  blessed.
- `SETUP-002`: If the target already has an SSOT or equivalent canonical project
  ledger, extend that authority. Do not create a competing project authority.
- `SETUP-003`: The final local authority cannot exceed `tested`. Protected signing,
  receipt custody, trusted time, or stronger identity must remain external gates.

## Target discovery and contract compilation

- `SETUP-010`: Read the target's instruction hierarchy and record precedence,
  including repository, subtree, harness, security, deployment, and writeback rules.
- `SETUP-011`: Inventory existing agent harnesses, commands, hooks, tool lifecycle
  events, task/PRD systems, retry logic, research paths, verifiers, receipts, secrets
  boundaries, and completion paths before selecting changes.
- `SETUP-012`: Bind every normative source and selected configuration surface to its
  exact path, size, and SHA-256 before work. Mark missing or external surfaces open.
- `SETUP-013`: Decompose this PRD and target-specific requirements into a lossless
  inventory. Each applicable row needs one owner stage, producer, receipt, verifier,
  negative control, acceptance evidence, and current state.
- `SETUP-014`: A reviewer independent from the integrating worker must compare the
  compiled inventory with this PRD and every target authority source before action.
  A structurally green `doctor` result does not prove semantic completeness.

## Integration design

- `SETUP-020`: Select only required components: task enforcement, project SSOT,
  host adapter, local inference, and research provider. Record exclusions and why
  they do not remove a target requirement.
- `SETUP-021`: Map every real worker, tool-failure, completion, verification, and
  acceptance action path. Prompt instructions alone are not enforcement.
- `SETUP-022`: Define exact configuration changes, dependencies, credentials,
  generated state, ownership, startup behavior, and platform-specific commands.
- `SETUP-023`: Capture a reversible pre-change snapshot and a tested rollback path.
  Never overwrite an unknown target configuration with an example file.

## Staged implementation

- `SETUP-030`: Use dependency-ordered stages. Separate discovery, contract
  compilation, design, implementation, testing, and independent acceptance.
- `SETUP-031`: Give each stage one bounded objective, one producer, unique output and
  receipt paths, an exact verifier, a negative control, and one next allowed state.
- `SETUP-032`: Run integration workers through the target SSOT action path. Record
  exact runtime identity, commands, material bytes, outputs, and failure evidence.
- `SETUP-033`: Keep secrets out of prompts, receipts, logs, source control, and copied
  examples. Record only secret identifiers or presence checks when required.

## Test and acceptance

- `SETUP-040`: Run package offline tests, but do not use them as target integration
  proof.
- `SETUP-041`: Run live positive, negative, tool-failure, retry-budget, stale-state,
  replay, interruption, rollback, and completion-bypass tests on the selected host.
- `SETUP-042`: Prove that every applicable real completion path traverses the gate.
  A template file or configured hook that the host never invokes is a failure.
- `SETUP-043`: Recheck target instruction and configuration bytes for drift before
  acceptance. Unreviewed drift returns the project to an earlier state.
- `SETUP-044`: Use an independent whole-integration acceptance command. The worker or
  integrating agent cannot accept its own installation.
- `SETUP-045`: Write a target-local operating guide, rollback guide, current status,
  open limitations, and exact resume command before handoff.

## Candidate stage order

1. `discover-target`
2. `compile-contract`
3. `design-integration`
4. `apply-integration`
5. `test-action-paths`
6. `accept-integration`

This order is a starting contract. The integrating agent may add target-required
stages. It must retain every requirement and dependency needed for safe integration.
