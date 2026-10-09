# Version 1 Completion Boundary

Version 1 is a portable, harness-neutral, local `tested` control package. It is
complete when an unrelated user can copy the repository and complete the offline
example without Hunt, Fold, Pi, Claude, Codex, Qwen, a model server, or network
access.

## Required for code completion

- Exact upstream source commits and relevant Git blobs are recorded.
- Every requirement has an ID, scope class, source locator, and source SHA-256.
- Applicable requirements have one stage owner. Unresolved requirements block
  acceptance. Waivers and supersessions retain typed, independent evidence.
- Stage dependencies, materials, products, properties, and producer ownership
  fail closed on omission, drift, replay, or bypass.
- Work orders, producer receipts, verifier receipts, acceptance receipts, and the
  append-only event chain bind exact bytes.
- Every mutation uses the process and OS controller lock.
- Runtime identity is fixed before work. Host-observed execution telemetry and
  controller-hashed trace/raw/parsed files are fixed at submission.
- Every stage verifier and the project acceptance gate run a same-program negative
  control before their positive check.
- `complete` is false at stage verification and true only after live independent
  acceptance. Local authority is capped at `tested`.
- Unit tests cover positive, negative, bypass, stale-state, replay, interruption,
  concurrency, source drift, waiver, supersession, and local-model receipt paths.
- The copied offline example reaches `tested`. Existing harness self-tests remain
  green. The source example contains no generated `.ssot` state or artifacts.
- User documentation describes the contract, CLI, trust boundary, and provenance.
- New-project initialization pins the source but remains unresolved and non-runnable.
- `doctor` blocks incomplete contracts, `next` emits read-only frontier packets,
  and the host runner records and verifies arbitrary executable workers.
- Host-run workers cannot change protected `.ssot` state. Model workers must provide
  the required call telemetry through the controller-provided path.
- The portable task supervisor validates bounded retry, research, output, verifier,
  and receipt contracts before launching an arbitrary command-line harness.
- Research admission binds consensus citations to hashed source records. Failed
  checks feed exact feedback into a bounded next attempt.
- Claude Code, Hermes, and Pi templates cover their required tool-result and
  completion events. Offline tests do not imply live-host verification.
- The copied composed example reaches `tested` after research admission, one failed
  attempt, corrective retry, enforcement receipt verification, and SSOT acceptance.
- Agent-led setup has an absent-only target bootstrap and a lossless setup PRD.
  Bootstrap must remain unresolved, refuse a competing SSOT, bind declared target
  surfaces, and reject path escape or overwrite attempts.
- Package proof and template presence cannot satisfy target integration. Live-host,
  bypass, interruption, rollback, and independent target acceptance remain required
  in each generated setup SSOT.
- Natural-language activation can admit a reviewed PRD without choosing a harness or
  model provider. Every requirement must bind exact PRD lines and one or more typed
  sources. A distinct critic and independent reviewer must pass reinforcement and a
  same-program negative control. The result remains unable to execute.
- Reviewed-PRD compilation preserves an immutable all-unresolved seed, then requires
  exact requirement and acceptance conservation, one stage owner, the existing SSOT
  graph checks, complete verifier drafts, and a separate read-only compile review.
  Every stage also binds its exact enforcement contract, producer, task verifier,
  outputs, enforcement receipt, optional research receipt, and controller trace.
  Publication is absent-only and remains unable to execute through `trusted-project`.

Run the executable gate:

```bash
python scripts/verify_ssot_release.py
```

Code completion requires `status: tested` from that command plus a clean Ruff
check. This is the release-candidate boundary.

The `Offline release` GitHub workflow runs the same gate and the package's
explicit lint policy on Linux/Python3.11 and Windows/Python3.13 for pull requests
and main updates. A failed run is failed package evidence. Required-check branch
policy is a separate owner setting; this workflow does not configure it or
authorize deployment. Check pins against upstream releases during maintenance,
validate candidates, and retain the previous accepted commit for recovery.

## Not required for version 1

- A specific agent harness or model provider.
- A live model, GPU benchmark, cloud service, or network call.
- Hunt domain data or full Hunt workflow parity.
- Protected signatures, trusted time, remote receipt custody, hardware
  attestation, or OS-backed human identity.
- `blessed` authority. The local controller rejects that claim.
- Live Claude Code, Hermes, and Pi activation and metered-model adapters. E6d
  portable script execution is included; E6e must keep untested hosts explicit.

These are deployment adapters or later hardening layers. Their absence must remain
visible; it must not be represented as local proof.

## Required for delivery completion

Delivery is a separate gate after code completion:

- choose the repository name and public/private visibility;
- choose and add a license if the repository will be distributed beyond the
  intended friend;
- create a standalone Git repository and reviewed initial commit;
- scan the exact committed tree for credentials, private Hunt data, generated
  receipts, model files, and accidental parent-repository content;
- push the reviewed commit to the intended remote and verify a fresh clone.

Do not call GitHub delivery complete until those publication actions pass.

## Historical qualification — 6 September 2026

The expanded enforcement, integration-bootstrap, E6a activation, E6b PRD admission,
E6c SSOT compilation, E6d execution/continuity, and SSOT code
boundary passed on 2026-09-06:

- `python scripts/verify_ssot_release.py`: 21 checks, `status: tested` on Python 3.11;
- the same 21-check release gate: `status: tested` on Python 3.10;
- 90 tests pass, including hard-path project execution, budget, authorization,
  bypass, drift, and interrupted-work recovery cases;
- all seven pre-existing harness self-tests pass;
- the copied two-stage host-runner project and the composed enforced-task project
  both reach live independent acceptance at `tested`;
- a copied target integration bootstrap remains deliberately unresolved with
  `no_installation_authority` and a red `doctor` result;
- a copied E6a activation captures exact intent and reproduces the same derived status
  without granting PRD or execution authority;
- that copied project admits a reinforced, independently reviewed PRD, compiles a
  lossless SSOT, executes only through enforcement, accounts for usage, and reaches
  independent `tested` acceptance;
- the built wheel contains `harness/compiler.py`, `harness/executor.py`, the project command, and the
  integration and trusted-project templates;
- Ruff reports no findings; and
- the release verifier found no generated SSOT or enforcement state in either source
  example.

## Current delivery — 9 October 2026

The standalone repository is published at
[scruge1/lowvram-agentic-harness](https://github.com/scruge1/lowvram-agentic-harness)
with public visibility and the MIT license. Parent-linked upgrades are recorded
in `UPGRADES.md`.

Live Claude Code, Hermes, and Pi adapter acceptance remains separate from offline
package conformance. Hosted CI, required-check branch policy, and target deployment
must each have their own current evidence.
