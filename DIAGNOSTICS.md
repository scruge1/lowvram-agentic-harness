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
