# Harness Enforcement Layer PRD

Status: E1 through E6d tested; E6e live-host acceptance remains separate

## Product outcome

A user can define a bounded task, its evidence policy, its retry policy, and its
acceptance command. The package can then supervise any command-line agent harness
from research through independently verified output while retaining an auditable
attempt trail.

An integrating agent can also bootstrap the installation itself as a target-bound
SSOT project. Setup is not complete when files are copied. It is complete only when
the target system's instructions, action paths, configuration, rollback, bypasses,
and live acceptance have been compiled and tested in that target.

Trustworthy means that the configured checks and evidence requirements passed. It
does not mean that an arbitrary natural-language objective was proved correct.

## Requirements

- `ENF-001`: Provide one versioned, harness-neutral task contract with an objective,
  worker argument array, declared outputs, retry limits, optional research policy,
  deterministic verifier, negative control, and receipt output.
- `ENF-002`: Validate the contract before execution. Reject shell strings, unsafe
  paths, missing verification, missing negative controls, and unsupported policy.
- `ENF-003`: When research is required, run it before the worker and admit only a
  machine-readable grounded receipt that meets the configured source floor.
- `ENF-004`: Launch the worker with `shell=False`, an exact prompt/context file, and
  environment variables that adapters can consume.
- `ENF-005`: Retry failed worker processes and rejected outputs only within the
  declared budget. Feed the exact failure reason into the next attempt.
- `ENF-006`: Never blindly replay a side-effecting inner tool operation. Host adapters
  must record tool failures and block normal completion until the failure succeeds,
  is explicitly abandoned, or returns to the outer supervisor for a new attempt.
- `ENF-007`: Hash the task contract, research evidence, outputs, verifier programs,
  process traces, and ordered attempt events into a host-written final receipt.
- `ENF-008`: The final receipt is an SSOT-consumable declared output. A task is not
  successful until the independent verifier and its negative control pass.
- `ENF-009`: Provide thin Claude Code, Hermes, and Pi adapter templates that translate
  native lifecycle events into the same normalized enforcement protocol.
- `ENF-010`: Provide `doctor`, dry-run, positive, failure, retry, stale, bypass, and
  adapter conformance tests. Do not claim a host adapter is live-tested when only its
  generated configuration has been checked.
- `ENF-011`: Preserve the local authority cap. A user with filesystem and process
  control can disable adapters or rewrite local code, so local completion is `tested`,
  never cryptographically `blessed`.
- `ENF-012`: Provide an absent-only integration bootstrap that creates a source-bound,
  unresolved SSOT scaffold in the target root. Refuse to create a competing SSOT when
  the target already has one.
- `ENF-013`: Provide a lossless setup PRD for an integrating agent. It must cover
  target instruction precedence, existing harness and hook discovery, selected
  components, exact pre-change bytes, staged implementation, rollback, positive and
  negative tests, bypass and interruption tests, live-host proof, independent
  acceptance, and truthful authority caps.
- `ENF-014`: Make the agent handoff explicit: the bootstrap has `scaffolded` authority,
  must be compiled into target-specific requirements and verifiers, and cannot claim
  installation success from package tests or template presence alone.
- `ENF-015`: After accepted target integration, provide the reusable natural-language
  trusted-project workflow defined in `NATURAL-LANGUAGE-ORCHESTRATION-SCOPE.md`.
  Preserve every `ORCH-*` requirement as a separately traceable normative leaf.

## End-user boundary

The user must define reviewable acceptance. The system may scaffold that contract,
but it must not infer arbitrary intent or invent a verifier from a prose task and
then treat its own guess as authority.

The first portable release supervises command-line harnesses and provides adapter
templates. A fully installed adapter can observe inner tool failures. Without an
adapter, the supervisor can enforce research, process retries, output provenance,
and final verification, but it sees the foreign harness as one process.

## Ordered stages

1. `E1-contract`: task schema, validation, and failure taxonomy.
2. `E2-supervisor`: research admission, worker attempts, feedback, verification,
   receipts, and SSOT-compatible output.
3. `E3-adapters`: normalized hook protocol and Claude/Hermes/Pi templates.
4. `E4-acceptance`: negative and bypass tests, offline example, documentation, and
   release-gate integration.
5. `E5-integration-setup`: target-bound setup bootstrap, setup PRD, agent operating
   guide, fail-closed tests, and composed release-gate coverage.
6. `E6-natural-language-projects`: reusable activation, PRD development and
   reinforcement, SSOT compilation, enforced execution, continuity, and live-host
   acceptance. E6a activation, E6b reviewed-PRD admission, E6c lossless SSOT
   compilation, and E6d portable execution/continuity are tested. E6e remains open
   in the order
   defined by the linked scope.
