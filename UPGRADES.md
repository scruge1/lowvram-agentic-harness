# Distilled upgrades

Each upgrade records its exact parent source version, reusable change, validation,
and remaining adoption limits. Extend this file with later accepted changes.
Keep private transcripts, machine locators, credentials, and generated run state
out of the public repository. Git records the resulting commit after publication.

## Shared-resource timing diagnostics — 2026-10-10

Parent commit: `8254cd8f0d6fafa17f22bb9191b1605ec4cf3d3a`.

Change: `DIAGNOSTICS.md` explains background/foreground contention, timer handler
order, internal versus visible streaming, and immutable latency measurements.
Use existing task identities and stage timings to distinguish queue delay from
model or transport failure before selecting an optimization.

Distilled lesson: releasing a caller's wait does not release the resource held by
its background task. Equal timer limits can choose different handlers. A mutable
status update is not an event completion timestamp. A successful synthetic stream
check is separate from native execution and user-visible delivery.

Scope: public diagnostic guidance only. No runner, deadline, model, provider,
queue, service or target configuration changes. Offline package checks and hosted
checks are reported with the PR; each consumer still needs normal-path adoption.

## Observed process failures — 2026-10-09

Parent commit: `44382fbb713bf66c5ed271282cd110191a7b7355`.

Change: the existing host-run stage trace and trusted-task command records add
`process_observation`. It distinguishes a returned child status from a host
timeout or launch failure, keeps the measured duration, and leaves descendant
quiescence unknown. Actual exits124/127 are distinct from synthetic runner
statuses124/127. Existing exit handling, retry contracts and gates remain.

Distilled lesson: generic failure reporting can lose the observation needed to
choose the next diagnostic check. Preserve fixed structured metadata without
copying commands, output, paths or exception text into that compact object.
The original traces still contain their existing detailed fields and require
privacy review before sharing. Missing observations remain unknown; a later
successful run does not establish the cause of a historical failed attempt.

Validation: actual disposable child exits124/127, a missing executable and a
one-second host timeout exercise both runners. Stage failures remain abandoned
with frontier state preserved. Package and hosted checks are separate evidence.
No installed private reader, runtime, model, queue or permission change follows
from this public source upgrade. Each consumer still needs normal-path adoption.

## Native command-hook and bootstrap diagnostics — 2026-10-09

Parent commit: `9b279dd0370f355130f86055db38a8e8a436c355`.

Change: `AGENT-INTEGRATION.md` documents Codex's `Bash` name for shell and
`exec_command` hooks, with configuration and rejection examples.
`DIAGNOSTICS.md` separates platform bootstrap effects, hook rejection, backend
refusal, process exit, and observation cleanup.

Distilled evidence: a wrong command matcher did not produce a hook event;
the corrected matcher produced an independently accepted native rejection.
The isolated test used invocation-only trust and a refusing backend as a safety
backstop. Separate native startup diagnostics showed permission setup activity
during a document-only request. These findings do not prove ordinary execution,
complete enforcement, or a repaired platform.

Scope: documentation and public examples only. No package worker, permission
profile, hook installation, runtime configuration, service or memory behavior
changes. Offline package validation is reported in the PR. Each target still
needs its own admitted setup and normal-path acceptance.

## Evidence-first diagnostics — 2026-10-08

Parent commit: `9f7a9c3671ae68a45480a80849107c517af22cc1`.

Change: `DIAGNOSTICS.md` supplies a compact investigation procedure and endpoint
example. `AGENTS.md` routes performance symptoms to it. The packaged trusted-project
skill carries the procedure, and integration requirement `SETUP-024` requires
target-specific measurements and adoption evidence.

Distilled lessons from parent-system work:

- A verifier must be available in both positive and negative working directories.
  Missing-program errors do not demonstrate semantic rejection. Check the actual
  negative reason. Treat unchanged verifier source as input and fresh reports as
  outputs. Preserve failed artifacts and source-bound recovery evidence.
- Test required process APIs through the component's actual interpreter. A machine
  can have several valid runtimes with different capabilities.
- Separate planner latency, tool transport, worker execution, verification, and
  delivery. A timeout covering one stage does not cover the entire task.
- Separate source acceptance, actual execution, visible delivery, and later reuse.
  Keep unresolved ownership or completion states explicit.

Validation found a Windows checkout fault: example PRD bytes were converted to
CRLF while contracts pin LF source hashes. The same conversion affected the pinned
Pi workspace initializer. `.gitattributes` now preserves LF for the example tree
and Pi project-workflow export. Source hashes remain exact; no verifier is weakened
or repinned.

Scope: guidance, packaged instruction templates, and fixture byte preservation. No supervisor, timeout,
negative-control implementation, service, provider, or global memory activation
changes in this upgrade. Package validation is recorded in the PR. Target adoption
and performance improvement require normal-path evidence from each target owner.

## Pi negative-control rejection contract — 2026-10-08

Parent commit: `940d746c7dc5e45191307cea495320b4fbc71ffe`.

Change: the generated Pi verifier wrapper accepts only exit 1 as the supplied
predicate's negative rejection. Exit 0 and all other codes fail the negative
control. Missing-program errors, unexpected failures, timeout statuses, and
cancellation cannot qualify through this wrapper's former broad nonzero check.
The adapter guide documents absolute verifier availability and cwd-relative
output reads. Regression checks exercise the actual generated wrapper using
subprocesses, including an unavailable relative Python script.

Limit: exit 1 still needs a reviewed predicate and evidence of the rejection
reason. This is not general semantic goal acceptance or native-session deadline
coverage. The portable export changes only; installed helpers remain unchanged
until their owners review the new hash, qualification, and adoption.

## Idea intake and work release — 2026-10-09

Parent commit: `d9accac237a588c6ba0903d65e7739f140018940`.

Change: `IDEA-INTAKE.md` separates capturing and refining ideas from releasing
active work. Repository instructions route to it; the packaged trusted-project
skill carries the same rule. Reuse existing project authority, queues, owners,
and capacity checks instead of treating every new topic as a replacement goal.

Scope: guidance and packaged instructions. No scheduler, controller, GPU lease,
execution permission, or runtime changes. Offline package validation and source
publication are distinct from target adoption. Normal intake, prioritisation,
release, and completed work must be observed before claiming target enforcement.

## Offline release CI — 2026-10-09

Parent commit: `a21fbfc06092ce46362dfdc8829b6b506d079be8`.

Change: the existing offline release gate now has a GitHub Actions workflow for
Linux/Python3.11 and Windows/Python3.13. It runs on pull requests and main updates,
with a 15-minute job limit. Checkout and Python setup are pinned to exact current
upstream release commits; lint uses Ruff0.16.10.

The package explicitly retains its accepted E4/E7/E9/F lint rule scope. Current
Ruff defaults include additional rules; their adoption requires a separate
compatibility review of API behavior and source-pinned adapter bytes. The budget
path repair below is the runtime change. Maintainers refresh tool pins through tested updates and
retain previous accepted commits for recovery.

Scope: public package CI evidence. Required-check branch protection, target
deployment authority, live smoke tests, and runtime rollback remain separate
owner gates. A passing hosted check cannot confer blessed authority.

The first hosted Windows run reached the existing 240-second unit-suite timeout.
The release driver now reports timeout exit124 with captured output tails so
failures identify the last test. Time limits and failure acceptance are unchanged.
A real child-process regression verifies both output streams and timeout failure.

Hosted Windows diagnostics identified a budget-path validation loop: a short-name
ancestor did not compare equal to the resolved target root, so traversal repeated
the drive root. The walk now compares canonical identity after checking original
path links, retains raw parent checks around `..`, and holds at a filesystem root
that cannot reach the target. Containment and symlink rejection remain in place.
No deadline is increased. Nonzero command diagnostics are labelled separately
from timeout so expected rejection checks are not described as package failure.
