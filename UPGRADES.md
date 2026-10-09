# Distilled upgrades

Each upgrade records its exact parent source version, reusable change, validation,
and remaining adoption limits. Extend this file with later accepted changes.
Keep private transcripts, machine locators, credentials, and generated run state
out of the public repository. Git records the resulting commit after publication.

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
