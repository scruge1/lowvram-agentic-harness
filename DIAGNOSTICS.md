# Evidence-first diagnostics

When a task reports slowness, investigate the measured constraint before changing
code, adding capacity, replacing a model, or introducing a cache. Apply this rule
at task intake and before selecting an optimization. Use the existing project
authority and telemetry. Keep unrelated work moving.

## First questions

1. What is slow, for whom, under which workload, and compared with what baseline?
2. Are the measurements comparable: same environment, load, inputs, cache state,
   success status, and measurement boundary? Record sample count and p50/p95/p99
   when available. One request time is a clue, not a latency distribution.
3. Where does elapsed time go? Follow one request or task through its stages.
   Separate queue waits, CPU work, storage, network calls, and response handling.
   Concurrent spans can overlap; do not sum them into an invented total.
4. Which check would distinguish the leading causes? Prefer an existing trace,
   query plan, counter, or bounded profile over a broad new audit.
5. Does one reversible change improve the same workload while preserving
   correctness, error rate, resource use, and recovery? Retain the before/after
   measurements and failed attempts. State what remains unmeasured.

## Endpoint example

Suppose `/users` takes 18 ms, `/orders` 180 ms, `/login` 210 ms, and `/products`
19 ms. These values identify investigation targets. They do not prove a database
bottleneck or establish that either slower route violates its service objective.

First inspect a representative trace for each slow route and compare it with a
fast route under the same conditions. For `/orders`, check query count and duration,
N+1 access, joins, rows scanned, lock waits, connection-pool waits, external calls,
and serialization. Inspect a query plan if the trace points to database time.
For `/login`, separate user lookup, password-hash verification, identity-provider
calls, session storage, and rate-limit checks. Deliberate password-hash cost can
explain latency; reducing that protection is not a performance acceptance test.

If traces are absent, use existing request logs and platform metrics first.
Propose the smallest missing timing point. Adding production instrumentation,
load generation, or configuration changes still follows the target's authority.
Do not log passwords, tokens, request bodies, or personal data to diagnose timing.

## Check contract disclosure in the model request

When an answer omits a required label, inspect the exact serialized messages
before changing models or retrying. A host-side contract or metadata field does
not establish that the model received the label's name. Preserve the original
prompt and answer, and separate a controller disclosure defect from model
instruction failure.

The local client can check required literal text in the bytes it will send:

```python
from harness.llm import LocalLLM

reply = LocalLLM().ask(
    "Review the supplied report.",
    system='Required gap labels: ["scope_unknown", "runtime_unknown"].',
    required_prompt_literals=("scope_unknown", "runtime_unknown"),
)
```

The option checks text-message content after JSON serialization and refuses
locally before transport if required text is absent. Extra message metadata does
not count. Default calls retain their existing payload. Literal presence is a
disclosure check; response validation and independent semantic review still
determine whether the answer meets the contract. A prompt correction alone does
not grant retry permission or make unchanged evidence new work.

## Apply the same questions to agent work

| Stage | Useful evidence | Common incorrect conclusion |
| --- | --- | --- |
| Instruction and memory loading | Loaded bytes/tokens, retrieval duration, freshness | A smaller file proves lower admitted model context |
| Coordinator and model | Queue delay, first tool latency, generation duration | A worker timeout also bounds the model planner |
| Tool and peer transport | Send, arrival, start, reply, and acknowledgement times | Message submission proves execution |
| Runtime and resource admission | Actual interpreter, required APIs, pool/GPU waits | Matching version strings prove capability |
| Worker and verifier | Separate runtimes, exact outputs, negative-control result | A missing verifier script proves absent outputs were rejected |
| Result delivery | Source receipt, served response, visible result, later use | Source tests prove a user saw or reused the result |

A local process exit does not establish remote or descendant quiescence. Preserve
unknown completion states and the existing owner's retry hold. More parallel work
can make a constrained queue slower; measure before increasing concurrency.

## Shared resources and timeout boundaries

Separate a worker's job-idle limit, replacement-startup limit, and the host's
total attempt limit. A job can stop reporting progress while the process remains
alive. Retiring that worker and starting another are separate operations. A
replacement that misses its readiness deadline does not establish why the first
job stalled or why the replacement failed.

Retain the native event times, worker identity, retry number, selected deadlines,
retirement result, replacement readiness, and final owned-child settlement. Use
explicit timestamp offsets when joining events. Keep diagnostic suggestions such
as memory pressure separate from measured causes. Preserve unknown file,
function, CPU, and garbage-collection attribution. Check the existing owner and
resource evidence before choosing another run or changing a limit.

After a failed analyzer run, require normal publication and freshness checks
before using its graph for impact analysis. An outer controller's successful
exit, partial parse files, progress percentages, and a core function's return
are separate observations; none establishes a usable published graph.

For a comparison, retain the original input guard. A file skipped by the language
parser can still contribute to scanned paths or graph structure. Establish which
stage excludes it before normalizing a changed-file list. Matching commit IDs and
dirty-file lists do not freeze file contents. A later attempt on current input
must keep its own freshness checks and cannot establish speedup against a
different input generation.

A foreground request can time out while a background summary holds the same
single worker slot. Inspect who holds that resource when the request arrives.
Join request, summary and backend task identities before attributing time to a
model. Separate queue wait, prompt processing, generation and final delivery.

Review the timers and their handler order. An idle timeout measures silence; a
total ceiling bounds the attempt; a turn-wait limit can release the caller while
background work continues. Releasing that wait does not release the worker slot.
Equal limits can select different handlers depending on which condition is tested
first. Check successful completion, timeout and cancellation separately. Do not
infer remote cancellation or resource release from a local cancelled future.

Retain output obtained while settling a timed-out child. A second `communicate`
can return a stored-request acknowledgement or a reply after the original wait
expired. Preserve available stdout and stderr, their hashes, the observed exit
status, and whether each observation is partial or complete. A timeout still
means the original attempt did not complete within its window. Retained output
does not authorize a resend or establish remote cancellation.

Bound retained evidence and label truncation. Distinguish the hash of retained
bytes from the hash and size of all available bytes. An evidence cap applied
after `communicate` is not a streaming memory limit. If local child settlement is
unknown, keep its owned handle and available partial output; report uncertainty.
Verify this path separately from a normal return that arrives after the deadline.

Internal transport streaming and visible reply streaming can be separate
settings. Qualify response headers, complete stream framing and tool-call parsing
on the existing route before adopting a change. A synthetic formatting result
still does not prove native tool execution or a useful reply reached the user.

Measure latency from monotonic spans or event timestamps with established meaning
and immutability. Align time zones and clock sources before joining logs. A status
record's `updated_at` can change after completion and measure later bookkeeping.
Keep the original failure and its boundaries when a later readiness check passes.

## Separate platform setup from the requested command

A document-only request can still cause its host to prepare a runtime before
reading the document. For example, the legacy elevated Windows sandbox can
apply host permissions during setup. The task's intended output does not bound
those setup effects. Inspect the existing owner's setup readiness and effect
authority before repeating a stalled launch.

Unchanged configuration and source hashes do not prove unchanged host
permissions. Record bootstrap failures separately from command or hook results.
A matching OS or CLI version also does not prove an optional backend is available;
use a bounded compatibility check that preserves the required permissions.
Do not weaken the permission profile just to obtain a passing result.

Persist the selected observation before waiting for cleanup. Record a process's
exit separately from pipe-drain completion and descendant settlement. Identify
owned processes before stopping them; do not infer ownership from a similar name.

See the current [Windows sandbox documentation](https://learn.chatgpt.com/docs/windows/windows-sandbox)
for platform setup effects and compatibility checks. This guidance does not
authorize machine permission changes or install a sandbox backend.

## Verify bindings between checked sources

A caller and its checker can each match a reviewed file hash while selecting
incompatible versions. Check the relationship between them as well as each file.
For a checker that pins its input, verify both edges using host-reviewed values:

```python
from hashlib import sha256

assert caller_manifest["checker_sha256"] == sha256(checker_bytes).hexdigest()
assert checker_manifest["input_sha256"] == sha256(input_bytes).hexdigest()
```

Extract declarations from verified data or source without executing unchecked
code. Test the assembled packet: a matching pair passes, a stale pair refuses,
and the required caller identity still applies. File custody, runtime capability
and action permission remain separate checks.

A checker can refuse before its structured error handler runs. Retain bounded
stderr and the exit status before parsing stdout. Preserve that failed attempt.
After a source correction, review and select the corrected packet explicitly;
do not weaken the hash check or replay the original attempt.

## Exercise the operation used by the runtime

An adapter can build a valid output schema while its actual operation still
requires another workflow's route or source prefix. Test the exported operation
that the runtime calls, with the exact assembled packet and owner binding.
Inspect its route, source-prefix, request, model and endpoint checks.

Use the target adapter's existing inspection path. A deliberate freshness
refusal can establish that argument checks passed before SDK setup. It does not
establish SDK preparation. Then, where supported, prepare the exact request
through the SDK while stopping before provider dispatch. Record the reached
boundary, prepared-request count, provider-payload count, tool state, session
persistence and child settlement. Keep each claim within that boundary.

Do not weaken route checks or create a second runner to make a probe pass.
A failure before counters are created leaves them unobserved, not measured
zero. Preparation without a provider payload is not a model answer or review
verdict. Preserve the original failed attempt and its admission state.

## Verify shared-history readers before new writes

A new record can pass a new parser while an older scheduled reader rejects it.
Check the active readers of that same history, including the scheduled entry and
recovery path. Validate retained records and a detached candidate with their
original bindings. Do not persist a test row or call a model to check format fit.
Run available pure adapter schema checks on the exact packet too. A successful
constructor or loader does not prove that a later route guard accepts the input.

Select compatible readers before the first new-format write. Verify the actual
scheduled entry, source pins, cadence and resource limits. A successful manual
run under a lock does not make an older timer compatible after that lock closes.
Preserve unrelated scheduled jobs and verify their bytes separately.

After a new-format row exists, recovery must keep a compatible reader or use a
separately selected admission hold. Do not restore an incompatible parser,
delete history or reset an uncertain reservation to make validation pass.
Check the first normal scheduled result and a later idle tick. Installed code
and a valid schedule do not establish useful advice or continuous operation.

## Verify evidence reaches the worker

A stored task can fit its body limit while its tool response exceeds a smaller
delivery limit. Metadata, repeated body views and serialization can increase the
response size. The host may then replace it with a preview and a file reference.
A successful tool call does not prove that the model received the evidence.

Compare the stored source, complete serialized tool response and retained
model-facing messages. Record the units each limit uses: bytes, characters or
tokens. Check both per-result and per-turn limits, truncation and offload behavior.
If the preview names a recovery tool, verify that the worker can actually call it.
Do not expand file access merely to bypass a failed delivery path.

When a bounded projection fits the task, preserve the raw source separately and
label the projection as selected excerpts. Keep every review question, authority
restriction, required fact and explicit unknown. A short response with selected
phrases present can still omit a requirement. Distinguish this host verification
from whether the worker can inspect the complete original source.

Rehearse the complete native response through its actual serializer and delivery
logic using the worker's limits. Leave room for changed metadata. Then verify a
fresh native response and the retained model-facing content before accepting the
input path. Source fit, successful execution, correct review content and later
useful consumption are separate acceptance claims.

## Process observation

The host-run stage trace and trusted-task command records include
`process_observation`: `outcome` (`exited`, `timed_out`, or `os_error`),
`observed_exit_code`, `duration_ms`, and `descendant_quiescence`.
The observed exit is null when the host did not receive a completed-process
status. An OS error can arise during launch or later subprocess handling;
this outcome does not prove that no child started. The observed status distinguishes
a worker's actual exit124 or exit127 from the
runner's timeout124 or launch-failure127. Existing `exit_code` behavior remains.
Duration covers launch and subprocess waiting, including output capture; it
does not measure queue wait, verification, delivery, or separate pipe-drain time.
Descendant quiescence remains unknown. These fields do not authorize a retry.
The compact object contains no command, path, output or exception text. The
surrounding existing trace still contains argv/stdout/stderr and must not be
published as a sanitized diagnostic without a separate privacy review.

## Errors hidden by a generic response

A protective error can be correct while concealing the failing stage. Preserve
the original attempt and inspect existing records first. If they contain only
the generic response, add diagnostics at the catch boundary that still has the
original exception. Keep the public response, admission checks, cleanup,
deadlines and retry policy unchanged.

Use fixed host stage labels and an allowlist of exception classes. Do not log
exception text, locals, source lines, credentials, prompts or raw stderr. For
example, inside the existing exception handler:

```python
# stage is a fixed host label, such as "spawn" or "validate_result".
try:
    name = type(error).__name__
    safe_name = name if name in {"ValueError", "OSError", "TimeoutError"} else "OtherError"
    logger.warning("operation_failed stage=%s exception_class=%s", stage, safe_name)
except BaseException:
    pass  # A failed diagnostic must not replace the original failure.
# Continue the existing failure and cleanup path.
```

An allowlisted module label and line number can identify a failing check without
exporting a path or traceback text. If recording stream metadata, label hashes
and sizes as the **retained capped buffers**. Overflow or unsettled readers can
leave the full stream unknown. Do not call a buffer snapshot an exit, cleanup or
remote-outcome proof. Absence of a matching task at one snapshot is scoped
evidence, not permission to resubmit an uncertain request.

Check the diagnostic change against the same success and failure paths. Compare
return values, exceptions, process calls, lock release and cleanup with the
previous source. Also check that a failed logger preserves those outcomes.
Source tests qualify the diagnostic change; only a later authorized normal-path
observation can identify the live cause. Keep the earlier failed case failed.

## Per-process CPU samples

Cumulative CPU time is not current CPU load. Sample the same process generation
twice and divide its CPU-time change by elapsed monotonic time. Record PID plus
creation identity, the interval, and the normalization basis. The following
calculation uses 100% for one logical CPU; a multithreaded process can exceed 100%.
Host-normalized percentages require a separately stated logical CPU count.

```python
def process_cpu_percent(before, after):
    # Samples: (process_generation, monotonic_seconds, cpu_seconds).
    generation0, time0, cpu0 = before
    generation1, time1, cpu1 = after
    elapsed = time1 - time0
    cpu_delta = cpu1 - cpu0
    if generation0 is None or generation0 != generation1:
        raise ValueError("Missing or changed process generation")
    if elapsed <= 0 or cpu_delta < 0:
        raise ValueError("Incomparable process samples")
    return 100.0 * cpu_delta / elapsed
```

For example, 30 CPU seconds in a 60-second interval means 50% of one logical CPU.
Use the existing platform observer for the samples; this calculation does not
create a sampler or manage processes. Reject missing or changed identities rather
than joining a reused PID. Wall-clock intervals can change with clock adjustments;
if only those intervals exist, retain that limitation with the result.

High CPU use identifies an investigation target. It does not establish ownership,
the cause of a failed task, or permission to stop a process. Inspect the existing
owner, launch evidence and effect boundary before cleanup. A later readiness
response can coexist with an older helper still running; retain both observations
and leave unmeasured permission changes or descendant settlement unknown.

## Compact finding format

Use the existing task record: symptom and objective; observation and runtime;
stage timings; leading hypothesis and alternatives; next discriminating check;
change and before/after result; unresolved limits. Separate observation, inference,
and proposal. No new board, controller, scheduler, or store is required.

## Adoption boundary

The repository instructions and shipped project skill ask agents to apply this
procedure. They do not add a runtime hook or prove adoption by another harness.
Verify that the target loads the changed instructions, applies them to a real
performance task, and records a measured decision through its normal workflow.
