# SSOT Refactor Provenance

This repository reimplements a compact, domain-neutral subset of a private production
control system. It does not copy project data or inherit upstream authority.

## Source handling

The transfer used exact committed upstream bytes, not dirty worktree files. Internal
repository names, paths, commit IDs, and blob IDs remain in the private workzone
receipts and are deliberately absent from this distributable repository. The public
provenance boundary is the invariant and negative-test inventory below.

## Transferred invariants

- Status is derived from evidence; workers do not write status.
- Requirements are conserved from a pinned target into one owning stage.
- Work follows the dependency frontier.
- Dependency products are declared as downstream materials.
- Work, material, output, verifier, runtime, and acceptance bytes are bound by
  receipts and checked again before authority is derived.
- Runtime and execution identity are host-observed. Local-model receipts name
  the exact model, checkpoint, backend, quantization, prompts, context, endpoint,
  sampling, call identity, token/byte counts, tools, trace, and raw/parsed files.
- Failed, stale, replayed, self-verified, concurrent, or mutating paths fail closed.
- Stage verification is `enforced`, not complete. Independent project acceptance
  is required for `tested` and complete.
- Candidate PRDs retain exact line-slice and multi-source bindings. Reinforcement,
  independent review, same-program negative control, absent-only publication, and
  a compact receipt precede any status advance.
- Reviewed PRDs first produce a conserved all-unresolved seed. A complete candidate
  must preserve exact requirement and acceptance bindings, single ownership, and the
  existing SSOT graph contract. Generated verifier drafts raise authority only after
  a separate read-only, negative-controlled review.

## Contract coverage

| Requirement | Action path | Evidence | Independent gate | Negative control |
|---|---|---|---|---|
| Conserve PRD leaves | project validation and stage preparation | source hashes, manifest hash, requirement IDs, work order | acceptance blocks unresolved leaves and unapproved exceptions | unresolved, waiver, and supersession tests |
| Bind materials to products | prepare, submit, verify, derived status | material and output byte records | stage verifier plus project acceptance | material drift and dependency skip tests |
| Record the real executor | prepare, submit, and downstream receipts | canonical runtime hash, call telemetry, and controller-hashed trace/raw/parsed files | host validation before work issuance and submission | invalid runtime and incomplete model-call tests |
| Reject rubber-stamp verification | stage verification and project acceptance | verifier type, same-program negative invocation, purity and result receipt | negative control must pass before the positive check runs | stage and acceptance negative-control failures |
| Serialize state changes | all mutating controller APIs | immutable records and ordered event chain | OS file lock plus process lock | thread and second-process contention tests |
| Separate verification from completion | derived status and accept | stage and acceptance receipt hashes | separately owned acceptance command | pre-acceptance completion test |
| Bound local authority | project validation | authority cap in the pinned manifest | external trust adapter required above tested | rejected blessed-cap test |
| Admit a new PRD without invented semantics | init and doctor | whole-source hash and unresolved inventory row | no work packet until reviewed contract compiles | unresolved scaffold and overwrite tests |
| Connect an arbitrary executable harness | next and host run | frontier packet, host process trace, outputs, execution and verifier receipts | controller launches the command and invokes the configured verifier | failed process, CLI separation, and `.ssot` mutation tests |
| Admit a reinforced PRD | `trusted-project admit-prd` | exact intent, PRD slices, multiple source hashes, critic checks, reviewer source, immutable checkpoint and event | reviewer identity differs from drafter and critic; output binds the exact candidate | same-program negative control, open-decision, mutation, source-drift, and verifier-drift tests |
| Compile the reviewed PRD | `trusted-project compile-ssot` | immutable unresolved seed, exact candidate, action-contract, producer, receipt, trace, and verifier hashes, conserved IDs and acceptance evidence, single stage owners, compile receipt and event | compile reviewer differs from compiler and verifier owners and binds every candidate byte and scope | omission, missing action evidence, action drift, duplicate ownership, false promotion, reviewer mutation, overwrite, and drift tests |

The coverage table states which mechanism carries each transferred requirement.
Passing a structural row does not prove output semantics; the configured verifier
and independent acceptance command must test the declared properties.

## Deliberate boundary

This compact implementation does not include protected signatures, trusted time,
remote receipt custody, hardware attestation, branch or memory isolation, blinded
candidate identities, or the full private requirement-expansion/audit corpus. Those
capabilities need deployment-specific trust adapters. The local controller therefore
rejects a `blessed` authority cap. The portable compiler does not claim that a generic
parser or model can infer arbitrary intent safely: it admits only a separately reviewed
candidate. E6d now composes the existing controller and enforcement path for portable
script execution, persistent budgets, recovery, and acceptance. Live-host proof and
host-metered model execution remain E6e.
