# Distilled upgrades

Each upgrade records its exact parent source version, reusable change, validation,
and remaining adoption limits. Extend this file with later accepted changes.
Keep private transcripts, machine locators, credentials, and generated run state
out of the public repository. Git records the resulting commit after publication.

## Defer shared-slot work before reservation — 2026-10-17

Parent commit: `ed0b668dfd1c23c51b02d3edb19219dc21646dae`.

Change: `DIAGNOSTICS.md` adds a standalone standard-library classification
example and a procedure for checking backend capacity before reserving new work.
Explicit exit status, timeout and settlement are separate checks. Busy or unknown
metadata defers work; unresolved child custody retains the owned handle and
stops further admission through the existing owner.

Distilled lesson: a timeout after reservation can leave an uncertain attempt.
An idle status snapshot does not reserve the backend, and a GPU memory queue
does not establish a request lease. Preserve uncertain history and qualify each
route and normal dispatch path before claiming wider adoption.

Validation: run the synthetic classification and refusal cases plus the existing
offline release gate before publication. This exports guidance and pure example
code, with no backend request, scheduler, lease implementation or private data.
Package checks do not establish native admission, job completion or continuous
useful operation.

## Retain the serialized context beside its hash — 2026-10-17

Parent commit: `093cd4f34bcc9c610cb60fb08103a530bf7046ea`.

Change: `DIAGNOSTICS.md` adds a runnable standard-library example that preserves
the exact context JSON text across custody that sorts object keys. It bounds the
retained bytes, checks their digest and recovers the complete object for review.

Distilled lesson: timestamps and other SDK metadata can make later reconstruction
impossible. A parsed object can lose the insertion order used by the original
hash. Retain one serialization at the actual hash boundary, with the existing
serializer and hash domain. Keep failure evidence and existing outer-frame caps;
do not replace a refused full result with hash-only success.

Validation: run the standalone synthetic example and the complete existing
offline release gate before publication. This adds guidance and public example
code, not a runtime collector or private source material. Package checks do not
prove target adoption, source fidelity, inference or physical provider delivery.

## Keep production declarations in operation checks — 2026-10-17

Parent commit: `0e047ae400b4ad6f7973e40fafc24d74b0b71344`.

Change: `DIAGNOSTICS.md` extends the existing source-binding and owner-operation
procedures. Fixtures must preserve the actual pin declarations and supply the
reviewed old or new bytes at the read boundary. Recovery checks must reach the
outer selection guard with the fields and values its later operation requires.

Distilled lesson: replacing a production hash in a fixture can hide a wrong
baseline selection. Testing only a later helper can miss an impossible exact-key
guard. Preserve both original failures; qualify the corrected packet and its
fresh recovery path separately. A normal start receipt is not general recovery
acceptance or permission to reuse a consumed attempt.

Validation: run the existing complete offline self-tests and release checks
before publication. This is guidance applied to existing code examples; it adds
no runtime component, target acceptance claim or private deployment material.

## Preserve grouped numbers in diagnostic projections — 2026-10-17

Parent commit: `951725fd8cf1fe6469dd18240425c5080da0c373`.

Change: `DIAGNOSTICS.md` includes runnable standard-library code that keeps
complete comma-grouped quantities and rejects malformed, signed and scientific
suffix matches. Structured telemetry remains the preferred input. No runtime
parser, collector, controller or new inference dependency is installed.

Distilled lesson: a numeric-only metadata projection can preserve privacy while
still reporting a false value. Token suffixes cannot establish a context budget
or explain a slow summary. Retain the failed projection, distinguish a
tool-enabled request from actual tool execution, and leave provider queue and
generation time unmeasured when the evidence does not separate them.

Validation: run the embedded example and the existing complete offline release
gate before publication. Exact-commit hosted checks are recorded after they
finish. These package checks do not repair old observations or prove parser
adoption, semantic fidelity or performance on another runtime.

## Match owner callback invocation contracts — 2026-10-17

Parent commit: `76ca83040d32397d928c9a6fde1b80ec02af17c4`.

Change: `DIAGNOSTICS.md` adds a runnable standard-library example that supplies
an existing owner's default read limit and checks its actual positional call
shapes without performing a read. It preserves the strict reader and requires
actual owner-path checks, legitimate empty-file handling and both forward and
recovery bindings. No new runtime helper or controller is added.

Distilled lesson: individually qualified components can disagree about callback
arguments. A live refusal before the first lock exposed a required argument
where the owner expected a default. The narrow adapter correction preserved
reader policy. Source checks, a selected guarded publication and later normal
work are separate evidence; a successful publication does not accept a model's
answer. The original failed invocation must remain failed.

Validation: run the example's invocation checks and the existing full offline
release gate before publication. Exact-commit hosted checks are recorded after
they finish. These package checks do not qualify another host's owner, locks,
publication, model output or continuous operation.

## Supply explicit claim text and preserve raw answers — 2026-10-17

Parent commit: `8d14a1f13696a3a60f9f287612aed09ca05c4fb9`.

Change: the diagnostic guide includes a small host-side code example for an
ordered claim view. It retains non-enum text exactly, uses only an existing
owner-defined recommendation meaning and preserves the raw enum separately.
It requires original answer/citation custody, source association, owner-version
binding and acceptance-time reconstruction. Reuse the existing field extractor;
this adds no new runtime helper, controller, registry or model dependency.

Distilled lesson: valid references and complete retained lines can still leave
the model resolving indirect field IDs or an ambiguous enum. One bounded private
positive/contradiction comparison passed after direct claim text replaced that
indirection, with the answer, sources, schema, model, instructions and budgets
fixed. The positive had relevant witnesses for all factual clauses; the negative
refused the actual unsafe clause. Earlier failures remain retained. This is not
a general causal, performance or semantic-accuracy claim.

Validation: documentation-only change; the existing full offline release gate
and exact-head hosted checks are recorded after they run. Package checks and a
bounded private pair do not prove target adoption or useful continuous work.
Owner-policy changes still require versioned native admission and ordinary work.

## Resolve complete numbered source lines — 2026-10-17

Parent commit: `a6881b052adced5daf5c5496378b1fe48ef11fc8`.

Change: `harness.line_evidence.resolve_numbered_line` verifies a bounded numbered
window against expected excerpt and unnumbered-content hashes. It resolves one
exact integer line reference and retains the complete line with its hashes.
Blank and Markdown heading lines refuse as factual witness locations. The helper
does not read files, execute source, authenticate supplied references or judge
whether a line supports a claim.

Distilled lesson: a fixed-length source quote can omit the clause that matters.
Selecting a location and deriving complete text avoids that byte loss. A later
model test still selected a wrong supporting line, despite correct full-line
retention. That result remained held; a valid location did not become semantic
acceptance. Keep raw model selections separate from host-derived source text.

Public validation: eight focused tests cover late clauses, Unicode identity,
exact numbering, both hash bindings, integer and span validation, headings,
inclusive byte/line limits and source-free error messages. Full release and
exact-head hosted results are recorded after validation. No private reviewer
adoption or general semantic accuracy follows from this portable helper.

## Compare paired source bytes with one Python parser — 2026-10-17

Parent commit: `7701943e57ef354aa583813a5d058224b292f614`.

Change: `harness.source_compare.compare_named_functions` takes both byte strings
and selected top-level function names. It records byte identity separately from
same-parser AST comparisons, binds both source hashes and records the parser
version. Missing, nested-only or duplicate names refuse. Source is not executed.

Distilled lesson: a read-only installed-source capture produced different AST
hashes even for a byte-identical caller. Those cross-runtime hashes were not
accepted as code-difference evidence. Matching the observed checker hash to an
exact retained copy allowed both versions to be parsed in one process; all five
selected functions then matched. Original false comparison flags were preserved
and their interpretation was superseded. This did not establish current process
population, loaded code, downstream execution or refresh permission.

Public validation: eight focused tests cover formatting, body changes, changed
globals outside selected functions, no execution, ambiguity, async functions,
Unicode byte limits and invalid inputs. The complete release gate and exact-head
platform checks are recorded separately after validation/publication. AST hashes
are not portable semantic proofs or whole-program equivalence.

## Qualify the decoder's empty-array representation — 2026-10-17

Parent commit: `21e35857ef2655bdac6a8882d810df217f777212`.

Change: `DIAGNOSTICS.md` supplies an explicit `const: []` empty-evidence schema
and the exact upstream converter branch that motivates it. It keeps payload,
decoder conversion, strict host validation and semantic correctness separate.

Distilled lesson: a single-omission review identified the missing explanation
and supported the other two, but emitted prose inside unsupported evidence.
The strict parser correctly refused it. The examined converter skips array
bounds when an array schema has neither items nor prefixItems. Its earlier
constant branch supports an explicit empty-array literal.

Source-workflow validation: adding only the constant preserved the schema's
intended meaning in 15 finite validator checks. Three fresh single-omission
model cases then passed independent checks of the exact judgment pattern,
relevant quotes, host attribution and valid empty evidence. Candidate bytes,
criteria, parser and execution limits were unchanged. The old failure remains
failed. No compiled converter witness, universal accuracy or live adoption is
claimed. Full source review remains a separate obligation.

Public scope: documentation and a copyable schema literal only. Executable code
is unchanged from the parent that passed the local 21-check release gate and
both hosted platform jobs. This change passes `git diff --check`; its own hosted
checks are recorded separately after publication.

## Derive quote attribution on the host — 2026-10-17

Parent commit: `0b285ba995e76087a0d4f20be588c6c793526b9a`.

Change: `harness.quote_evidence.attribute_quote` resolves an exact model-selected
quote against host-bound fields. It refuses absent or multiple-field matches,
returns every UTF-8 byte span within the unique field, and records field and
quote hashes. It preserves overlapping occurrences without normalization.
The raw response, request and candidate bindings remain the caller's responsibility.

Distilled lesson: choosing a field identifier can be unnecessary model work.
Separate quote selection from deterministic attribution. Exact membership still
does not prove that a quote supports the requested conclusion. An earlier answer
with unrelated but exact quotes stays incorrect after attribution.

Private source validation: one incomplete-answer and one complete-answer model
test matched their expected coverage decisions; all three positive quotes were
independently checked for relevance. This is a limited component pair, not broad
accuracy, source support, useful continuous operation or target adoption.

Public validation: all 21 release checks passed on Windows/Python3.11, including
the unit suite and seven offline self-tests. Eight focused tests cover ambiguity,
absent matches, Unicode byte offsets, overlaps, unchanged inputs, invalid inputs
and the distinction between membership and meaning. Local Ruff0.11.8 and
`git diff --check` passed; pinned hosted lint remains a separate check.
The helper has no I/O, inference, scheduler, persistent state or admission effect.

## Review the requested conclusion as well as individual claims — 2026-10-17

Parent commit: `3f15bc680d47bbd3f785ab9e0f66a10af503e793`.

Change: `DIAGNOSTICS.md` distinguishes claim support, question completeness,
native reviewer outcome and later idle behavior. It requires protected task
context in the actual review request and preserves prompt and retry limits.

Distilled lesson: a real scheduled local producer and separate reviewer call
completed, and the next two ordinary ticks made no model call for the retained
held attempt. The answer preserved citations and uncertainty but omitted the
requested central distinction. An independent review identified that omission;
the native reviewer held for a different reason. Its settled explicit hold was
stored under an aggregate held-or-uncertain state. Keep those observations and
reasons separate. Operational success does not establish accepted content.

Source-workflow validation: retained raw responses, exact request and source
bindings, normal scheduler events and unchanged history/state/queue snapshots
were independently compared. This qualifies one pipeline and two idle cycles,
not sustained useful operation, every input route or revised reviewer policy.
The owner-question disclosure correction remains a separate source candidate.

Public validation: the existing release checker passed all 21 checks, including
the unit-test command and seven offline self-tests, on Windows/Python3.11.
`git diff --check` passed. Hosted checks follow publication.

Public scope: diagnostic guidance only; no executable, model, scheduler, retry
or prompt-limit change. Target policy adoption remains separately qualified.

## Bind installation checks to actual file roles — 2026-10-16

Parent commit: `a0f33e626259ef6cd62957c6a62695c29d06768c`.

Change: `DIAGNOSTICS.md` checks the existing owner's exact lock metadata without
relaxing private-input checks. It also requires checking selected source bytes
before module initialization, executing those same held bytes, and preserving
the primary failure stage when a receipt is written successfully.

Distilled lesson: a private-file check can reject a valid existing advisory lock
with a different mode. Reconcile the actual failed attempt before selecting a
narrow compatibility correction. Keep the original failure, source pins and
history; do not change permissions or retry automatically to obtain a pass.

Source-workflow validation: 28 CPU control groups passed, including actual lock
admission and receipt methods with simulated metadata and storage. They did not
qualify Linux filesystem effects. A separate corrected native operation verified
five source replacements and the scheduler entry under the existing locks,
preserving source-history bindings with zero model calls or history writes.
That result does not prove later useful work or continuous operation.

Public validation: all seven offline self-tests passed on Windows/Python3.11;
`git diff --check` passed. Hosted validation follows this documentation commit.

Public scope: diagnostic guidance only. No executable behaviour, installation,
permission, model, scheduler or retry policy changes in this package. Existing
target owners must qualify their own operation.

## Preserve file checks across Windows runtimes — 2026-10-16

Parent commit: `450459f9134e3d166d3a3b856497b9662754ded4`.

Change: `harness.source_snapshot.stable_snapshot` supplies bounded regular-file
bytes to the existing pure section reader. It compares `fstat` metadata on the
held source and a second named-file handle, retaining device, inode, mode, link
count, size, modification time and change time. Both descriptors have explicit
cleanup. Pathname/handle `ctime` differences do not require removing drift checks.

Distilled lesson: qualify the actual interpreter and operation. Isolated runtime
startup, remote transport, file stability, HTTP retrieval and native consumption
are different stages. A later working runtime or snapshot does not change an
earlier failed attempt into success; continue verification without replaying an
already completed publication or restart.

Validation: seven focused public tests passed on Windows/Python3.11 and3.13,
covering real atomic publication, byte limits, replacement-file identity,
in-place drift, failed-handle cleanup, hard links and relative paths. The full
local release gate passed all21 checks and all seven offline self-tests on3.11.
Exact-head platform CI is a separate acceptance check tracked on the pull request.

Scope: an explicit read-only filesystem helper, with no credentials, inference,
network, persistent state or automatic retry. The caller owns source authorization.
This is not an OS deadline, continuous lock, native-reader adoption or deployment
claim. Separate private runtime evidence does not qualify this public package.

## Return complete bounded source sections — 2026-10-16

Parent commit: `8596174d435da292ef3f0d8a54eaeacc1b87ca83`.

Change: `harness.source_read.complete_section` returns one complete literal H2
section from immutable UTF-8 bytes, with body/source hashes and line bounds.
Absent, duplicate or oversized sections refuse; no prefix or summary is returned.
The helper performs no filesystem, network, inference or authority operation.

Distilled lesson: a canonical document can contain a small Current section and
large historical evidence. Keep the complete Current within its existing body
cap while preserving requirements and history. A section hash is different from
a full-source hash, and a fresh source read does not prove live runtime truth.

Validation: seven focused public unit tests cover exact body/line/hash binding,
one-byte budget edges, UTF-8 bytes, CRLF/final lines, ambiguity, invalid inputs
and a body containing the entire source. The complete unit suite and all seven
offline self-tests passed on Windows/Python3.11. Private source-reader tests and a local canonical
read are separate evidence; no native broker adoption is claimed here.

Scope: a pure portable public helper and guidance. It is not a Markdown parser,
stable filesystem snapshot, remote attestation, authentication, active runtime
check or deployment. Existing target readers require their own owner adoption.

## Qualify the actual adapter operation — 2026-10-16

Parent commit: `f6db4a7ed8becbf9e45f674f6383afc2583f799d`.

Change: `DIAGNOSTICS.md` separates schema checks, actual operation argument
checks and SDK preparation before provider dispatch. Reuse the existing target
inspection path and finite runner; retain strict route and source bindings.

Distilled lesson: a reused reviewer built a valid schema but its operation
still required the previous workflow's route. It failed before producing a
verdict or recording preparation counters. A schema-only test missed that
guard. Null counters must remain unobserved, not be reported as measured zero.

Validation in the source workflow: tests exercised the actual corrected export
up to a deliberate freshness refusal. A separate native SDK inspection then
recorded one prepared request, zero provider payloads, no tools or session file,
and a settled child. The original held attempt remained unchanged. Those checks
do not prove a model verdict, server grammar, semantic quality or live adoption.

Public validation: the full unit suite and all seven offline self-tests passed
on Windows with Python 3.11. Hosted validation follows source publication.

Scope: public guidance only; executable behaviour is unchanged. No runtime,
provider, permission, retry policy or scheduler change follows from this
documentation.

## Check required contract text before model transport — 2026-10-16

Parent commit: `268a270abfc27a93b4263ff1ebb9ce9d78f87798`.

Change: `LocalLLM.chat` and the forwarding `ask` path accept optional
`required_prompt_literals`. The client checks text content from the exact JSON
payload before transport. Missing contract text refuses locally; metadata alone
does not satisfy the check. Calls without requirements retain their payload.
`DIAGNOSTICS.md` provides the public usage example.

Distilled lesson: a controller required two exact labels but omitted both names
from the model-facing prompt. The answer remained rejected by its validator.
Correct disclosure and preserve the original attempt; changing the prompt does
not establish novelty or grant another execution.

Validation: eight transport-mocked regression tests cover the missing contract,
metadata-only disclosure, actual serialized messages, default payload, invalid
requirements, non-text content, Unicode and cross-message fragments. All seven
offline self-tests and the complete unit suite passed on Windows with Python
3.11. Ruff checks passed for the changed Python files. Hosted validation follows
source publication; these local checks do not establish target adoption.

Scope: an optional public client guard and diagnostic guidance. Literal presence
does not establish complete instructions, response correctness, server grammar
enforcement or target adoption. Existing response and semantic checks remain.

## Preserve reader compatibility during scheduled rollout — 2026-10-16

Parent commit: `7c857913839cea275b73bb6273f4cf72549ac623`.

Change: `DIAGNOSTICS.md` checks every active reader of shared history before a
new-format write. It separates detached format validation, installed scheduler
selection, a normal scheduled result and later idle behaviour.

Distilled lesson: a successful manual run can leave the next old timer unable
to read its result. Publish compatible readers first. After the new record is
stored, recovery must preserve compatible parsing and the original history.

Validation: the parent workflow reproduced rejection by the old parser, checked
retained history and a detached candidate, and read back the installed scheduled
entry. These checks establish format and rollout evidence; they do not establish
model correctness, later useful consumption or continuous operation.

Public validation: all seven offline self-tests passed on Windows with Python
3.11. The change is documentation only; executable behaviour is unchanged.

Scope: public diagnostic guidance only. No runtime, permission, model, scheduler,
retry policy or target adoption changes are made by this documentation.

## Preserve safe failure-stage diagnostics — 2026-10-16

Parent commit: `d539d832e571044d150f8a963e99be22228e27a0`.

Change: `DIAGNOSTICS.md` adds a portable logging example and checks for an error
whose underlying stage is hidden by a generic response. Keep fixed stage labels,
allowlisted exception classes and retained-buffer metadata separate from raw
errors and operational outcome claims.

Distilled lesson: a protective hold can be correct while its cause remains
unknown. Diagnose the original attempt before another submission. Logging must
preserve the original exception, cleanup, admission and retry behavior.

Validation: ten independent synthetic differential controls passed for the
parent workflow's candidate diagnostics, including failure paths, cleanup and
logger failures. At that source qualification, the live cause was unknown and
the candidate was not deployed. These controls do not establish live diagnosis
or adoption. This public change is guidance and example code only.
Public validation: all seven offline module self-tests and 131 unit tests passed
on Windows with Python 3.11. No target adoption follows from these checks.

## Verify worker evidence delivery — 2026-10-16

Parent commit: `09a7b7dc17dcca5500f54642246e84ce3d1a4160`.

Change: `DIAGNOSTICS.md` checks the complete serialized tool response and retained
model-facing messages, including duplicate context, size units, offload and
available recovery tools. Compact projections must preserve task requirements,
authority restrictions and explicit unknowns as well as selected evidence.

Distilled lesson: a valid stored-body hash and successful tool result do not
establish evidence delivery. A preview can refer to recovery tools that the
worker cannot use. Fitting a response does not prove semantic completeness.

Validation: the parent workflow retained an actual delivery failure and checked
a corrected projection against the native serializer and offload function.
Fresh target input, review quality and later useful consumption remain pending.
Public validation: seven offline module self-tests and 131 unit tests passed on
Windows with Python 3.11. These checks do not establish target adoption.

Scope: diagnostic guidance only. No runtime, permissions, tools, model, deadline,
scheduler or automatic retry changes. No target adoption or publication claim.

## Verify caller and checker source bindings — 2026-10-15

Parent commit: `74211bc42f2e802224e8457fe0a66e8ce74d2d08`.

Change: `DIAGNOSTICS.md` adds the two source-binding comparisons and asks for a
control over the assembled packet. A checker must still refuse the wrong source
or caller. Bootstrap failures retain their original exit and diagnostic evidence.

Distilled lesson: independently correct file hashes do not prove that a caller,
checker and selected input form a compatible set. A stale nested pin can refuse
before structured output, even when the caller selected the intended input.

Validation: the parent workflow retained the original refusal, passed controls
for the corrected pair and completed its normal publication and startup path.
Public validation: seven offline module self-tests and 131 unit tests passed on
Windows with Python 3.11. These checks do not establish target adoption.

Scope: diagnostic guidance and illustrative comparisons only. No runtime,
permission, model, scheduler, retry policy or target adoption changes.

## Separate worker recovery from graph acceptance — 2026-10-11

Parent commit: `bc49e9c9e6787df8a1871f317742ad5532238dd8`.

Change: `DIAGNOSTICS.md` separates job-idle, replacement-startup, and total
attempt deadlines. It asks for native events and owned-child settlement, keeps
runtime suggestions distinct from measured causes, and requires normal graph
publication and freshness before impact analysis. Input comparisons distinguish
parser filtering from scanned-path and graph-structure filtering.

Distilled lesson: a parser can hit its idle limit and its replacement can fail
readiness before the outer attempt expires. A successful controller exit still
does not establish analyzer completion. A parser-skipped file can affect graph
input, so a changed dirty list cannot be dismissed without source evidence.

Validation: source review of existing filter, graph, parser, and worker paths,
plus retained events from a finite failed attempt. Public offline package checks
are reported separately in the PR; no new runtime test or retry is introduced.

Scope: diagnostic guidance only. No analyzer, worker, deadline, ignore rule,
provider, model, scheduler, installation, or target-authority change. Target
instruction loading and normal task adoption remain separate acceptance gates.

## Bound release output collection after a timeout — 2026-10-10

Parent commit: `6bd3a96672c7cd2f91f35d6c4afd9e6708d859f1`.

Change: the release checker sends output to temporary files. It waits for the
exact child with the existing deadline, then allows three seconds for settlement
after a timeout and kill attempt. Output reads use a separate reader offset and
the initially observed size, with at most 80,000 bytes sampled per stream and
20,000 decoded characters returned. Metadata identifies sampled bytes, their
hash, truncation and observed stability. Changing snapshots fail the gate.
An unsettled child remains owned; its exit and descendant state stay unknown.

Distilled lesson: Windows `subprocess.run` can collect pipe output without a
deadline after killing a timed-out child. A descendant holding the pipe can
extend the wait. The original one-second deadline returned after 5.169 seconds
in an inert reproduction. Successful child exit can leave the same pipe open.

Validation: local controls cover both inherited-handle cases, timeout output,
nonzero exit, bounded large output, changing snapshots and kill denial with
unknown settlement. Full package and hosted results belong in the PR.

Scope: public release checker only. File output avoids pipe EOF waits; it does
not cancel descendants, impose a disk quota or prove that later writes stopped.
The deadline bounds process waiting and sampled output size, not arbitrary
filesystem stalls, process creation or total operating-system latency.

## Preserve evidence during timeout settlement — 2026-10-10

Parent commit: `3be10b70e37ca36e1ca6d072571675ba6cd1c966`.

Change: `DIAGNOSTICS.md` describes output custody during finite child settlement.
Keep partial and complete observations, bounded retained bytes, hashes, observed
exit status, and explicit truncation. Preserve uncertainty and the retry hold.

Distilled lesson: a timeout handler can collect an acknowledgement or reply while
stopping its child, then lose those bytes when it raises an incomplete failure
record. A test for normal late returns does not cover this exception path.

Validation: an inert reproduction confirmed the loss. The corrected source passed
three targeted controls for partial and complete settlement evidence, bounded
output with unknown settlement, and an actual inert child timeout. Public package
checks are reported separately in the PR.

Scope: public diagnostic guidance only. No runtime, transport, timeout, retry,
evidence store or target deployment change. Target owners must qualify their
actual cleanup and durable evidence paths.

## Scoped migration of a saved tool contract — 2026-10-10

Parent commit: `4bb667f2221d99634a20cedd1bd37b0dda372092`.

Change: optional pure `harness.tool_schema.migrate_known_tool_schema` replaces
one known saved definition with one reviewed available definition in an exact
host-supplied scope. Unknown cases keep the original pin. A successful result is
an independent JSON snapshot. Other tools, persistence and execution stay with
the target owner. `tool_function_sha256` exposes the bounded canonical function
fingerprint used for comparison.

Distilled lesson: current installed bytes can coexist with an older restored
conversation schema. Check the actual forwarded contract before attributing an
omitted argument to the model. Preserve intentional pinning; qualify a narrow
known-contract migration through native persistence and request readback.

Validation: seven offline groups cover exact replacement, scope and policy
holds, unknown content, unavailable or foreign tools, snapshot isolation,
idempotence, malformed wrappers, non-JSON/nonfinite data and bounded output.
Package and hosted results are reported in the PR. This public export installs
nothing in a target and grants no authority. Actual target adoption, argument
compliance, useful work and delivery remain separate evidence requirements.

## Exact byte-edit preconditions — 2026-10-10

Parent commit: `5d4844a0f6b27afb1e2b169fe8258179128169c6`.

Change: optional `harness.source_edit.replace_exact_once` refuses absent,
repeated, overlapping or ineffective byte edits. Integration guidance explains
why a filename-only inverse comparison can conceal a missing inherited pin and
why selected-map checks remain necessary.

Distilled lesson: a successful source hash or inverse comparison does not prove
that every intended edit happened. Assert each edit's precondition and verify
the target's full native pin selection before claiming startup acceptance.

Validation: six offline unit groups cover the missing inherited-pin case,
ambiguous and overlapping matches, ineffective edits, input types, exact binary
preservation and explicit inverse deletion. Package and hosted checks are
reported with the PR.
Scope: pure in-memory source check only. No file publication, service operation,
admission or target adoption is provided by this upgrade.

## Runtime and CI lock alignment — 2026-10-10

Parent commit: `6f843658de0874ac204c39ba2daadc6543620b32`.

Change: optional `harness.runtime_lock` checks explicit runtime and CI locks before
an existing installation step. Shared versions must match and CI must retain all
runtime distribution hashes. It permits test-only additions and refuses ambiguous
or unsupported syntax. The public adapter adds explicit CLI paths, bounded reads
and handled failures to the parent-system source checker.

Distilled lesson: source changes can invalidate earlier CI/runtime alignment while
the old check remains green. Reconcile against the current maintainer's runtime
definition, run standalone fixtures explicitly, and repair fixture dependencies
without weakening assertions. Retain failed attempts and exact tested trees.

Validation: compatibility, version/hash drift, duplicate aliases, unsupported or
unhashed input, size limits and actual CLI success/refusal are in the existing
offline unit suite. Package and hosted checks are reported with the PR.
Scope: read-only source-lock checks; no package installation, release permission
or deployed-image acceptance. Consumers must adopt it on their actual CI path.

## Effective admission and process CPU diagnostics — 2026-10-10

Parent commit: `337f2db008b49e07a9e8b6f359f7dbdc9532aca1`.

Change: `AGENT-INTEGRATION.md` gives a native metadata example where an enabled
hook remains untrusted. `DIAGNOSTICS.md` adds a portable CPU-delta calculation,
process-generation checks, monotonic timing and an explicit one-logical-CPU basis.

Distilled lesson: configured hooks, runtime readiness, actual invocation and task
results are separate observations. Busy processes can coexist with readiness.
CPU use does not establish process ownership, historical failure cause or cleanup
authority. Preserve old failures and unknown effects when later checks succeed.

Scope: public guidance and a pure calculation example. No sampler, hook trust,
runtime binding, process stop, permission or service change. Offline package and
hosted checks are reported with the PR; normal-path target adoption remains open.

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
