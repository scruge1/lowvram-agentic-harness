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
