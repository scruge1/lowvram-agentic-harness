# Trusted Project Activation

`trusted-project` is the executable activation boundary for the post-install natural-
language workflow. E6a captures exact intent. E6b admits a source-bound PRD only after
a separate reinforcement pass and an independent, negative-controlled review. E6c
conserves that PRD in a reviewed SSOT graph. E6d executes its frontier through the
portable enforcement supervisor, accounts for budgets, persists recovery evidence,
and runs independent acceptance.

The chosen harness drafts the PRD and reports. This package does not impose a model
provider or second planner. `script_no_model` actions can run portably. A
`host_metered` action remains held until its pinned host adapter supplies live usage
evidence in E6e.

## Explicit activation

The installed skill template is `harness/templates/trusted-project-skill.md`. A host
should invoke it only when the user explicitly asks for the trusted, receipt-gated,
or blessed-SSOT workflow. Ordinary requests are not intercepted in version one.

The skill calls this portable interface:

```bash
trusted-project plan "Build X" --root /exact/target
trusted-project execute "Build X" --root /exact/target
trusted-project execute PROJECT_ID --root /exact/target
trusted-project status PROJECT_ID --root /exact/target
trusted-project resume PROJECT_ID --root /exact/target
trusted-project abandon PROJECT_ID --root /exact/target --reason "reason"
trusted-project admit-prd PROJECT_ID --root /exact/target \
  --contract candidate/admit-prd.json
trusted-project compile-ssot PROJECT_ID --root /exact/target \
  --contract candidate/compile-ssot.json
```

`plan` and `execute` preserve the exact request. Optional repeatable
`--constraint` and `--open-decision` values become immutable intent fields.
Execution also accepts repeatable
`--authorization STAGE=TARGET_RELATIVE_PATH` values for stages that declare external
effects.

## Target and SSOT behavior

The intent binds the resolved target path, filesystem identity, and exact state of
known root instruction and configuration surfaces. If one of those surfaces changes,
`status` and `resume` return `held_target_drift`.

If `ssot-project.json` exists, the intent records `reuse_existing` and its exact hash.
If `.ssot` exists without a manifest, activation returns
`held_authority_ambiguous`. Otherwise the intent records `new_project_pending`.
E6a and E6b do not create or modify the project SSOT. E6c publishes a new manifest
only when activation recorded `new_project_pending`, or validates the exact unchanged
root manifest when activation recorded `reuse_existing`. It never overwrites a
manifest that appeared after activation.

## PRD admission

The harness writes four candidate files inside the target: the PRD, its structured
manifest, a separate reinforcement report, and the admission contract. The contract
names the drafter and a distinct reviewer command:

```json
{
  "schema_version": 1,
  "project_id": "PROJECT_ID",
  "drafter_identity": "chosen-harness",
  "prd_path": "candidate/PRD.md",
  "manifest_path": "candidate/prd-manifest.json",
  "reinforcement_path": "candidate/prd-reinforcement.json",
  "reviewer": {
    "owner": "independent-reviewer",
    "argv": ["{python}", "review_prd.py"],
    "files": ["review_prd.py"],
    "timeout_seconds": 60,
    "negative_control": {
      "argv": ["{python}", "review_prd.py", "--negative-control"],
      "files": ["review_prd.py"],
      "timeout_seconds": 60
    }
  }
}
```

Each manifest requirement has a unique ID, measurable acceptance, an exact PRD line
slice, and one or more sources. Source classes are `user`, `target`, `research`, and
`agent_proposal`. Target and admitted-research sources bind a contained file path and
SHA-256. User sources bind `intent.request`. Agent proposals bind their own text.

The reinforcement report binds the PRD and manifest hashes. A critic distinct from
the drafter must pass all seven checks: coverage, contradictions, provenance,
feasibility, risk, failure recovery, and measurable acceptance. Any issue or open
decision holds admission.

The reviewer must be distinct from both drafter and critic. Its negative-control
invocation uses the same program and returns:

```json
{"verdict":"negative_control_pass","reviewer_identity":"independent-reviewer"}
```

Its positive invocation returns one JSON object that binds the exact project, intent,
three candidate hashes, ordered requirement IDs, empty open decisions, and
`verdict=approved`. The host checks that both invocations are read-only.

On success, the controller publishes an absent-only checkpoint under
`.trusted-project/projects/PROJECT_ID/prd/`, writes a self-hashed receipt, and appends
the `prd_reviewed` event. Source, reviewer, artifact, receipt, or event drift makes
later status fail closed.

## SSOT compilation

The chosen harness supplies a complete `ssot-project.json`, a separate
`verifier-candidates.json`, and this small compiler contract:

```json
{
  "schema_version": 1,
  "project_id": "PROJECT_ID",
  "compiler_identity": "chosen-harness-compiler",
  "manifest_path": "candidate/ssot-project.json",
  "verifier_candidates_path": "candidate/verifier-candidates.json",
  "reviewer": {
    "owner": "independent-ssot-reviewer",
    "argv": ["{python}", "review_ssot.py"],
    "files": ["review_ssot.py"],
    "negative_control": {
      "argv": ["{python}", "review_ssot.py", "--negative-control"],
      "files": ["review_ssot.py"]
    }
  }
}
```

Every reviewed PRD ID and text must occur exactly once. Its exact PRD line binding
and acceptance evidence must survive unchanged. Each requirement must be applicable,
have one owner stage, and bind its acceptance evidence to that stage's properties.
The existing SSOT validator then checks dependency order, materials, unique outputs,
verifier commands, same-program negative controls, and independent project
acceptance.

Each stage must also contain an `action` binding with `kind=harness.enforcement`, a
producer identity, a separate task-verifier owner, the exact enforcement-contract
path and SHA-256, and its receipt path. It also declares `usage_mode`, `effects`, and
an optional pinned runtime profile. The task outputs, enforcement receipt,
optional research receipt, and controller trace must all be declared stage outputs.
This makes the E6d action path explicit before the compiler raises state.

Verifier candidates enter only as `untrusted_drafts`. Their owner, argument arrays,
negative control, and source hashes must exactly match every stage verifier and the
project acceptor. The independent compile reviewer must bind the reviewed-PRD receipt,
candidate manifest, verifier-candidate file, ordered requirements, and verifier
scopes. It must also pass a same-program negative control and remain read-only.

E6c preserves the pre-adjudication all-unresolved seed, candidate, verifier drafts,
reviewer pins, and self-hashed receipt under the project directory. It authenticates
the expected new `ssot-project.json` surface in the `ssot_compiled` event. Any other
authority-surface, source, manifest, verifier, receipt, or event drift fails status.

## Budgets

Without `--budget-file`, E6a records a capture-only default with zero model calls,
zero paid cost, zero attempts, zero research, and zero external side effects. This
permits intent capture only.

A budget file must be inside the target and contain exactly:

```json
{
  "cost_usd": 2.5,
  "external_side_effects": 0,
  "model_tokens": 50000,
  "outer_attempts": 3,
  "research_sources": 10,
  "storage_bytes": 100000000,
  "wall_seconds": 7200
}
```

E6d revalidates the budget file on every status or resume. It reserves the maximum
declared attempts before launch, records actual accepted attempts, wall time, research
sources, output bytes, and declared external effects, and blocks project acceptance
when a cap is exceeded. An interrupted or failed launch retains its conservative
attempt reservation. Model tokens and paid cost remain zero only for
`script_no_model`; unproved host metering holds.

## Execution and continuity

`execute PROJECT_ID` uses the compiled action only. It launches
`harness.enforcement` through `ssot.workflow.run_stage_command`; a direct worker call
cannot create the enforcement, producer, stage-verification, and project-execution
receipt chain. The controller serializes whole-project execution with a crash-
releasing OS lock, revalidates all compiled and live control bytes, and abandons an
orphaned SSOT work order before resume.

Every completed stage adds a self-hashed receipt under `execution/`. Status
independently rechecks the enforcement receipt, SSOT verification receipt, action
contract, optional authorization, budgets, and live SSOT acceptance. A declared
external effect needs a target-local authorization object that exactly names the
project, stage, ordered effects, authorizer, issue time, and expiry. It must be no
more than one hour old and unexpired when the stage starts.

The portable controller distinguishes `configured`, `running`, `held_execution`,
`held_budget_exhausted`, `failed`, `verified`, `tested`, and `abandoned`. Local
independent acceptance raises the result only to `tested`; `blessed` still requires
the configured external authority.

## State

Each project is stored under:

```text
.trusted-project/projects/PROJECT_ID/
  intent.json
  events/
  prd/                         after E6b acceptance only
    admission-contract.json
    PRD.md
    prd-manifest.json
    prd-reinforcement.json
    review-receipt.json
  ssot/                        after E6c acceptance only
    compiler-contract.json
    unresolved-seed.json
    ssot-project.json
    verifier-candidates.json
    compile-receipt.json
  execution/                   after E6d verified stage execution
    STAGE_ID.json
```

The intent is absent-only. Events are sequence-bound, hash-chained, and individually
self-hashed. Status is derived from these files and current target surfaces. Local
hashes are tamper-evident, not externally authenticated.

## Current boundary

E6a through E6d provide the portable intent-to-tested lifecycle for
`script_no_model` actions. Generic subprocess lifecycle and bypass behavior are tested
from a built distribution. Live Claude Code, Hermes, Pi, and metered-model adapters
remain E6e and cannot be inferred from portable tests.
