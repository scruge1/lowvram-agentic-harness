# Natural-Language Trusted Project Scope

Status: E6a through E6d tested at the portable script boundary; E6e live hosts open

## Product outcome

After one target-specific installation is accepted, a user can invoke the trusted
workflow in ordinary language from a supported harness:

> Build X using the trusted workflow.

The installed activation layer creates or resumes a project, develops and reinforces
its PRD, compiles a target-specific SSOT, waits at the required review gate, executes
the verified frontier through the task supervisor, and reports a receipt-derived
outcome.

The user does not repeat package installation, adapter mapping, hook configuration,
or target integration tests for every project. Each project still gets its own PRD,
requirements, stage graph, evidence, verifiers, receipts, and acceptance result.

## Required user experience

1. The user states the intended outcome in ordinary language and explicitly selects
   the trusted workflow. Explicit activation is the version-one default.
2. The system identifies the target root and whether the task is greenfield or an
   existing-system change. It reuses an existing target SSOT when present.
3. The system asks only questions whose answers materially change scope, authority,
   destructive actions, external communication, cost, credentials, or acceptance.
4. The system inspects target instructions and current files, performs required
   research, and drafts a PRD with requirements, non-goals, constraints, risks,
   dependencies, budgets, deliverables, and measurable acceptance.
5. A reinforcement pass checks omissions, contradictions, ungrounded claims,
   ambiguous acceptance, missing failure paths, and unverifiable requirements.
6. The system presents the source-bound PRD and unresolved decisions for review.
   It does not begin implementation before the configured review gate passes.
7. The compiler produces a conserved requirement inventory, dependency-ordered
   stages, materials, outputs, verifier commands, negative controls, retry policy,
   authority caps, and independent whole-project acceptance.
8. The runner executes only the current frontier. Every worker stage traverses the
   enforcement supervisor. Failure feedback is exact and retries are bounded.
9. The system persists state and can answer natural-language status, explain holds,
   and resume after process or conversation restart without reconstructing authority
   from chat.
10. Completion is derived from live receipts and independent acceptance. The system
    reports limitations and remaining open requirements with the result.

## Normative requirements

- `ORCH-001`: Provide a reusable installed skill or equivalent harness-native command
  that explicitly activates the trusted project workflow from natural language.
- `ORCH-002`: Keep the activation wording thin. The skill must call executable host
  controls; a pre-prompt alone cannot provide enforcement.
- `ORCH-003`: Resolve and bind the exact target root before reading, writing, planning,
  or issuing work. Reuse the target's existing canonical SSOT when one exists.
- `ORCH-004`: Create an immutable intent capsule containing the user's exact request,
  target identity, requested mode, known constraints, open decisions, authority
  boundaries, and a source hash.
- `ORCH-005`: Support `plan`, `execute`, `status`, `resume`, and `abandon` operations.
  Planning must never silently become execution.
- `ORCH-006`: Develop the PRD from the intent capsule, target instructions, inspected
  target state, and admitted external research. Distinguish user requirements from
  agent proposals and research-derived constraints.
- `ORCH-007`: Run a separate PRD reinforcement pass for coverage, contradictions,
  provenance, feasibility, risk, failure recovery, and measurable acceptance.
- `ORCH-008`: Preserve unresolved material decisions. Ask the user or configured
  reviewer instead of selecting a scope-changing answer without authority.
- `ORCH-009`: Require a reviewed PRD checkpoint before compiling executable stages.
  An agent may draft the PRD and verifier candidates but cannot approve its own
  semantic interpretation as independent authority.
- `ORCH-010`: Compile every applicable PRD leaf into one conserved requirement row and
  bind it to a stage, producer, output, receipt, verifier, negative control, and
  acceptance evidence. Compilation must fail on omissions or duplicate ownership.
- `ORCH-011`: Generate verifier candidates only as untrusted drafts. Deterministic
  checks, independent review, or a separately authorized verifier must promote them
  before they can raise authority.
- `ORCH-012`: Execute every worker stage through `harness.enforcement` or an equivalent
  configured hard action path. Direct harness execution is a bypass and must not
  produce project completion authority.
- `ORCH-013`: Reuse the installed host adapter, research provider, runtime identity,
  and trust configuration. Project creation must not rerun installation unless drift
  invalidates that configuration.
- `ORCH-014`: Apply explicit budgets for tokens, money, wall time, retries, research,
  storage, and side effects. Exhaustion produces a hold with evidence, not a success.
- `ORCH-015`: Require fresh authorization for destructive actions, credentials,
  purchases, publishing, external messages, deployments, or other effects outside
  the approved task boundary.
- `ORCH-016`: Persist the active checkpoint, event chain, work orders, attempts,
  receipts, unresolved decisions, and next allowed action on the filesystem.
- `ORCH-017`: Resume from those files and revalidate source, configuration, verifier,
  and dependency hashes before issuing more work.
- `ORCH-018`: Provide receipt-derived `status` output suitable for both a person and a
  calling agent. Separate drafted, reviewed, compiled, configured, running, held,
  failed, verified, tested, and blessed states.
- `ORCH-019`: Run positive, negative, stale-state, replay, bypass, interruption,
  budget-exhaustion, missing-review, verifier-drift, and resume tests.
- `ORCH-020`: Run live lifecycle tests in every claimed host. Template conformance or
  package tests cannot establish that a host invokes the activation and enforcement
  paths.
- `ORCH-021`: Archive or retain completed project evidence without mixing it into the
  next project's authority. Never use a prior project's accepted receipt as proof for
  a new objective.
- `ORCH-022`: Cap local results at `tested`. `blessed` requires the configured external
  independent authority and must not be used as a friendly synonym for success.

## Per-project filesystem contract

Use the target's native SSOT when present. Otherwise create a target-local workspace
with these logical surfaces; exact names may be adapted during installation:

```text
intent.json                 exact user request and authority boundary
PRD.md                      reviewed product authority
ssot-project.json           conserved requirements and executable stage graph
.ssot/                      immutable work orders, events, and receipts
.enforcement/               bounded task-attempt evidence
ACTIVE-CHECKPOINT.md        current state and next allowed action
```

Chat history is not a sovereign state surface.

## Activation interface

The minimum portable executable interface is:

```text
trusted-project plan "natural-language objective" --root TARGET
trusted-project execute PROJECT_OR_INTENT --root TARGET
trusted-project status --root TARGET
trusted-project resume --root TARGET
trusted-project abandon --root TARGET --reason TEXT
```

Harness skills translate ordinary language into this interface. The CLI provides one
testable path shared by Claude Code, Hermes, Pi, and generic command-line harnesses.

## Delivery phases

### E6a: Activation contract

Define the portable command protocol, intent capsule, project identity, explicit
activation wording, modes, budgets, and host-skill templates.

### E6b: PRD development and reinforcement

Build target inspection, admitted research, PRD drafting, critic passes, unresolved
decision handling, source binding, and the independent review checkpoint.

Implemented boundary: the selected harness performs inspection, research, drafting,
and critique. The portable controller admits its outputs only when every requirement
has multi-source provenance and an exact PRD line binding, all reinforcement checks
pass, all material decisions are closed, and a separate read-only reviewer plus its
same-program negative control bind the exact candidate. The result cannot execute.

### E6c: SSOT compiler

Compile a reviewed PRD into an all-unresolved seed, then require lossless semantic
adjudication and verifier promotion before the frontier opens. Never infer completion
criteria and immediately treat them as trusted.

Implemented: the chosen harness supplies the semantic candidate. The portable gate
conserves exact reviewed IDs, text, PRD lines, acceptance evidence, and single stage
ownership. Each stage binds an exact `harness.enforcement` contract, producer, task
verifier, task outputs, enforcement receipt, optional research receipt, and controller
trace. It validates the existing SSOT graph, admits verifier candidates only as
untrusted drafts, requires an independent read-only negative-controlled review, and
publishes absent-only with a revalidated receipt. It does not execute the frontier.

### E6d: Execution and continuity

Compose the SSOT controller and enforcement supervisor. Implement status, resume,
hold, abandon, budget accounting, drift revalidation, and archive boundaries.

Implemented at the portable boundary: compiled `script_no_model` actions run only
through the existing enforcement-to-SSOT path. Project events and self-hashed
execution receipts account for budgets, bind live task and stage receipts, serialize
execution, recover orphaned SSOT work, require fresh exact authorization for declared
external effects, and gate independent project acceptance. Pinned `host_metered`
profiles compile but hold until E6e proves their host telemetry.

### E6e: Host acceptance

Install the activation in Claude Code, Hermes, Pi, and the generic wrapper. Prove live
activation, enforcement, bypass rejection, interruption recovery, and independent
acceptance in isolated target fixtures.

## Version-one exclusions

- Implicit interception of every user message. Explicit activation avoids surprising
  cost or process overhead.
- Automatic approval of a model-drafted PRD, requirement inventory, verifier, waiver,
  or acceptance rule.
- Infinite retries or an unconditional promise to achieve any requested outcome.
- Automatic high-impact external actions without task-specific authority.
- Cryptographic blessing from local hashes alone.
- A requirement that every harness expose inner tool events. A generic process wrapper
  remains supported but has lower tool-level visibility.

## Completion boundary

The scope is implemented only when a fresh supported harness can receive an ordinary
language request, create a source-bound project, stop at the review gate, compile a
reviewed PRD without requirement loss, execute only verified frontier stages, recover
after interruption, reject a tested bypass, and derive final status from independent
acceptance. The same scenario must pass from a built distribution, not only a source
checkout.
