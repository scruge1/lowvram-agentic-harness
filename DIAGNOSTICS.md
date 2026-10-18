# Evidence-first diagnostics

## Retain complete source lines

A short source quote can stop before a necessary qualification. Prefer a model
selection such as `{source_index, line_number}` and let the host derive the
complete selected line from its existing bound source window:

```python
from harness.line_evidence import resolve_numbered_line

derived = resolve_numbered_line(
    numbered_excerpt, bound_reference["span"], line_number,
    excerpt_sha256=bound_reference["excerpt_sha256"],
    content_sha256=bound_reference["content_sha256"],
)
```

The window contains exact contiguous `N: text` lines, at most64 lines and8,000
UTF-8 bytes. Its content hash covers unnumbered lines joined with LF. Keep the
expected hashes in the existing owner-bound request; model-supplied replacement
hashes do not authenticate a source. The helper checks consistency with the
supplied reference and performs no file reads or whole-file verification.

Retain original model selections alongside the derived text, source identity and
request binding. Recompute derived evidence before acceptance. Reject blank and
Markdown heading-only factual witnesses. A present complete line can still be
irrelevant or omit another clause's support: location, hashes and valid JSON do
not establish entailment, current runtime state or execution authority.

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

Check question completeness separately from support for individual claims. A
response can cite every stated claim correctly while omitting the conclusion
the user requested. Bind the review to the protected owner question and verify
that the serialized reviewer request contains that task context. A model-supplied
restatement does not establish the owner's requirement. If the host compiles
review criteria, label that projection and bind it to the original question's
hash. Preserve the original requirements and raw source. Keep existing prompt
limits; measure the complete request and remove duplicated instructions rather
than clipping requirements or source evidence.

Preserve the producer answer, reviewer decision and any independent assessment
with their separate reasons. A settled `hold` is not a timeout merely because an
aggregate state groups held and uncertain attempts together. Verify the normal
next tick: it should preserve the attempt and make no model call for unchanged
held work. One successful pipeline and an idle tick do not prove sustained
useful work or accepted content. A wording correction alone does not admit a
retry of the retained attempt.

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

## Check capacity before reserving work

When several callers share one model slot, check the existing backend metadata
before consuming a new attempt. Busy or unknown metadata should defer that work
without creating a reservation. Keep the existing locked novelty and authority
checks at dispatch. An idle observation is not an exclusive lease: another
caller can arrive between the observation and dispatch. Reuse an existing
request lease when one is qualified; a GPU memory allowance alone is not one.

Use the actual route and its documented metadata schema. Bound the read through
the existing owned transport. Require explicit successful exit and settlement;
a settled child can still have timed out or exited unsuccessfully. Preserve an
unsettled child's owned handle and stop admission through the existing owner.
Do not start another probe while that custody remains unresolved.

This standalone example classifies an already decoded, bounded metadata result
for a qualified single-slot schema. The owning reader must reject duplicate
JSON keys, non-finite values, wrong endpoints and redirects before this step.
It retains the full result and process evidence separately.

```python
def capacity_state(receipt, slots):
    if type(receipt) is not dict or receipt.get("settled") is not True:
        raise RuntimeError("retain owned handle; metadata custody unresolved")
    code = receipt.get("exit_code")
    if type(code) is not int or code != 0 or receipt.get("timeout") is not False:
        return "unknown"
    if type(slots) is not list or len(slots) != 1 or type(slots[0]) is not dict:
        return "unknown"
    slot = slots[0]
    if type(slot.get("id")) is not int or slot["id"] != 0:
        return "unknown"
    busy = slot.get("is_processing")
    if type(busy) is not bool:
        return "unknown"
    return "busy" if busy else "snapshot_idle"


clean = {"settled": True, "exit_code": 0, "timeout": False}
idle = [{"id": 0, "is_processing": False}]
assert capacity_state(clean, idle) == "snapshot_idle"
assert capacity_state(clean, [{"id": 0, "is_processing": True}]) == "busy"
assert capacity_state({**clean, "exit_code": 1}, idle) == "unknown"
assert capacity_state({**clean, "timeout": True}, idle) == "unknown"
assert capacity_state(clean, [{"id": 0, "is_processing": "false"}]) == "unknown"
```

Place this classification before the existing reservation call, rather than in
a persistence callback used after reservation. Check the busy and unknown paths
for zero reservation and queue writes. Qualify the actual loaded function and
its process owner separately from pure classification. A successful metadata
read does not prove that the normal dispatch branch ran, a useful job completed,
all routes use the check, or an uncertain prior attempt can be replayed.

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

Bind file checks to the existing owner's file roles. An advisory lock can have
a different accepted mode from private inputs or backups. Check the exact lock
path, regular-file type, owner, group, mode, link count and size. Check the held
descriptor against the named file and retain the existing lock protocol. A
reviewed compatibility correction for one fixed lock does not relax private-file
checks or authorize changing host permissions.

Persist the selected observation before waiting for cleanup. Record a process's
exit separately from pipe-drain completion and descendant settlement. Identify
owned processes before stopping them; do not infer ownership from a similar name.

See the current [Windows sandbox documentation](https://learn.chatgpt.com/docs/windows/windows-sandbox)
for platform setup effects and compatibility checks. This guidance does not
authorize machine permission changes or install a sandbox backend.

## Verify bindings between checked sources

A caller and its checker can each match a reviewed file hash while selecting
incompatible versions. Check the relationship between them as well as each file.
Bind the bytes produced by the actual runtime encoder. Compact JSON and JSON
with spaces can decode to the same value while having different hashes. Reuse
the existing runtime freeze or serialization function. Record artifact and native
byte counts and hashes separately, then check decoded equality when comparing
representations. Keep the exact native hash check; do not replace it with
semantic equality. Retain a failed observation and select any corrected
qualification explicitly before another attempt.

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

Keep the production pin declarations intact in those tests. Supply reviewed
bytes at the read boundary instead of replacing the expected hash with the hash
of whatever the fixture supplies. Check the actual old input at its old path,
then verify that substituting the new input at that path refuses. A test that
changes the selected pin can hide an incompatible production declaration.

When loading reviewed code, verify its selected hash before module initialization,
then compile and execute those same held bytes. Importing the pathname after a
successful hash check reads it again; the earlier check does not bind that later
read. Preserve the existing module identity and relative-path requirements.

A checker can refuse before its structured error handler runs. Retain bounded
stderr and the exit status before parsing stdout. Preserve that failed attempt.
After a source correction, review and select the corrected packet explicitly;
do not weaken the hash check or replay the original attempt.

Export a bounded failure stage and message from the outer owner when the normal
handler cannot run. Preserve the primary failure stage after a successful receipt
write; report a receipt-write failure separately. A later read-only reconciliation
can establish the observed source, scheduler and history state. It does not turn
the original attempt into success or grant an automatic retry.

## Capture volatile state immediately before use

A shared snapshot can change while an action waits for review. Keep the reviewed
action, source bytes and target set fixed. Then use the existing owner path to
capture fresh state and conditionally perform that selected action in one finite
sequence. Preserve the freshness checks at each effect; do not make an old
snapshot optional or approve new actions from whatever the next read returns.

This standard-library fixture constructs an output map in memory. The owner
supplies its fixed scope before either observation. These are independent fixture
cases, not execution permission or an automatic retry:

```python
from copy import deepcopy
from hashlib import sha256

source = b"fixture bytes"
reviewed_scope = ("construct_fixture", "fixture.txt", sha256(source).hexdigest())
owner_selected_scope = reviewed_scope
state = {"rows": ["retained"]}
early = deepcopy(state)
state["rows"].append("other work")


def construct_output(snapshot, selected_scope):
    if selected_scope != reviewed_scope or snapshot != state:
        return None
    return {"fixture.txt": source}


assert construct_output(early, owner_selected_scope) is None
fresh = deepcopy(state)
assert construct_output(fresh, owner_selected_scope) == {"fixture.txt": source}
assert construct_output(fresh, ("different_action",)) is None
state["rows"].append("changed before use")
assert construct_output(fresh, owner_selected_scope) is None
```

Retain separate complete capture and action receipts. Bind the action to the
actual captured bytes, metadata and full history map, then verify the required
before/after invariants. Preserve any earlier failed attempt as failed. A new
conditional attempt needs its own owner selection; never loop until a guard passes.

Use one shared deadline for the sequence, including transport and cleanup. If an
existing read-only audit hook persists for a Python process, use separate owned
processes for capture and writing. A new module does not remove that hook. Reuse
the existing locks, source checks and finite transport rather than adding another
controller. A current mismatch does not by itself prove a past failure's cause.

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

## Check the owner's actual callback arguments

Two components can pass their own checks and still disagree at the boundary.
For example, an owner may call `read(path)` while its supplied reader requires
`read(path, limit)`. Check every actual call shape before publication. A missing
default can fail before the owner acquires its first lock or emits state evidence.

Keep the strict reader unchanged. If the existing owner contract supplies a
default limit, adapt only that calling convention:

```python
from inspect import signature


def bind_owner_reader(strict_read):
    def owner_read(path, limit=2_000_000):
        return strict_read(path, limit)

    for arguments in (("owner.lock",), ("state.json", 64_000)):
        signature(owner_read).bind(*arguments)
    return owner_read
```

The signature check does not call the reader. Use call shapes from the actual
owner, including keyword arguments where applicable. Then exercise that owner
with authorized fixtures, stopping before unselected effects. Include legitimate
empty lock files when the existing reader permits them. Retain its size, path,
ownership, permission and stable-read checks. Verify both forward and recovery
bindings if they share the adapter.

Exercise the outer recovery entry with its complete valid selection too. A pure
helper can pass while an earlier exact-key guard rejects fields that the entry
later requires. Verify that the supplied values reach the real validation and
that a wrong value refuses. Stop before unselected effects; this does not prove
native recovery, and a consumed start attempt cannot serve as a fresh recovery
start.

An argument check proves neither an OS lock nor a publication. Preserve a failed
invocation as failed; absent state or receipt fields are unobserved. A corrected
adapter needs its own selected invocation and native result.

## Separate quote selection from attribution

When evidence must quote an answer, let the model select the quote and derive
its field on the host. Give the host exact fields from the bound candidate,
not a field map supplied by the model:

```python
from harness.quote_evidence import attribute_quote

derived = attribute_quote("The queue is empty.", {
    "observation": "The queue is empty.",
    "scope": "The service status is unknown.",
})
assert derived["field"] == "observation"
assert derived["utf8_spans"] == [{"start": 0, "end": 19}]
```

Absent or multiple-field matches refuse. Repeated matches in one field retain
all UTF-8 byte spans, including overlaps. Keep the raw response unchanged and
store derived evidence separately, bound to the request, candidate and extractor
source hashes. Hash shape alone does not prove those bindings.

Attribution does not establish relevance. An unrelated exact quote still fails
the review. Check a complete answer, an incomplete answer and individual missing
requirements. Keep source support and answer completeness separate; a coverage
component alone cannot authorize final acceptance or execution.

## Give a source reviewer explicit claim text

If a reviewer receives claim IDs separately from a large answer, check whether it
must repeatedly resolve each ID back to a field. Compare a direct ordered claim
view against that representation while keeping the answer, sources, model,
instructions, output schema and budgets fixed. Treat this as a hypothesis until
the comparison runs; smaller input alone does not prove better or faster work.

Build the view on the host from the validated, bound answer. A recommendation
enum can use its existing owner-defined meaning. Keep the raw enum separately;
do not invent a meaning from model output:

```python
raw_fields = {
    "recommendation": "keep",
    "observation": "The observation is dated.",
}
# Selected and validated by the existing protected owner, not by the reviewer.
enum_meanings = {
    "keep": "Preserve the documented rule; no new action permission is granted.",
}
claim_units = [
    {"id": field, "text": enum_meanings[text]
     if field == "recommendation" else text}
    for field, text in raw_fields.items()
]
raw_recommendation = raw_fields["recommendation"]
assert claim_units[1]["text"] == raw_fields["observation"]
assert raw_recommendation == "keep"
```

Use the existing validated field extractor and ordering. Reject an enum without
an admitted meaning. Retain the original answer bytes and citations unchanged,
even when the source-phase view omits duplicate metadata. Verify their exact
source association first. Bind the view to the original request, answer bytes,
source windows and selected owner-contract version. Reconstruct it from those
protected inputs at acceptance; model-supplied IDs or hashes cannot define it.

Keep source-free answer completeness separate from source support. Give neither
component the other's verdict as evidence. Preserve explicit unknowns as typed
unknowns, and retain raw model selections separately from host-derived text.
Check a complete positive and a relevant contradiction through the actual
adapter. A bounded pair is not general reviewer accuracy, deployment or useful
continuous operation. If owner policy later changes, version it and interpret
old history under its original contract. Do not add a citation or wording patch
for each failed response.

## Compare Python source with the same parser

AST dump formats can differ between Python runtimes. A fingerprint mismatch
from two machines does not establish a code change, even with line attributes
excluded. First compare full source hashes. When selected function structure
matters, parse both exact source byte strings together:

```python
from harness.source_compare import compare_named_functions

result = compare_named_functions(
    b"def f(): return 1\n",
    b"# moved\ndef f(): return 1\n",
    ["f"],
)
assert result["all_selected_functions_equal"]
assert not result["source_bytes_equal"]
```

The helper records both source hashes, the parser version and each selected
function's AST hash. Missing, nested-only or duplicate top-level names refuse.
It parses source without executing it. Keep native-file provenance separate:
a retained copy can represent an observed file only when its full byte hash
matches that dated observation. Matching selected functions says nothing about
changed globals, other functions, loaded runtime identity or actual behaviour.

## Keep evaluation case labels outside model inputs

A case name such as `missing_comparison` can reveal the intended defect through
a request ID or binding. Omitting the expected-answer field is not enough.
Inspect the assembled instructions, user data and metadata that actually reach
the model, including any case names copied into those fields.

When creating a new detached test request, assign its ID before building the
binding. Keep the label and expected answer in a separate host record:

```python
from uuid import uuid4


def prepare_review_case(candidate, case_label, expected_decision):
    request_id = f"review-{uuid4().hex}"
    model_data = {"request_id": request_id, "candidate": candidate}
    private_expected = {
        "request_id": request_id,
        "case_label": case_label,
        "expected_decision": expected_decision,
    }
    return model_data, private_expected
```

Send only `model_data` through the existing reviewed request builder. Keep
`private_expected` outside provider input. Retain the original request ID in
both records so later grading can join the result. Do not rewrite an existing
production request, binding or receipt to make it fit this example.

Check the actual prepared payloads, not only the helper's return values. Keep
candidate content, grading criteria and legitimate wording unchanged; an
ordinary word such as "complete" in a policy is not itself a leaked case label.
Opaque IDs alone do not prove a blind evaluation. Preserve any contaminated
result and separate a corrected test from native adoption or general accuracy.

## Check the decoder's schema subset

A valid JSON Schema does not prove that a decoder enforces every constraint.
Compare the actual provider payload, returned JSON, strict host validation and
the converter source or compiled grammar for the installed backend.

For example, this representation makes empty evidence explicit:

```json
{"type": "array", "minItems": 0, "maxItems": 0, "const": []}
```

In [this pinned converter source](https://github.com/ggml-org/llama.cpp/blob/9dcf84e5ae2718947188b539aab8b9c2b15d3ba1/common/json-schema-to-grammar.cpp),
array bounds are handled inside the branch requiring `items` or `prefixItems`.
An array schema without either reaches a generic array fallback. The `const`
branch instead encodes the exact empty array. This describes that revision;
verify each target's actual converter and supported schema subset.

Keep host validation strict. A model can make the correct judgment but return
malformed evidence. Preserve that failed response and its actual rejection;
do not normalize it into a successful result. Test a fresh request with unchanged
candidate, criteria and limits after a narrow schema correction. Separate source
fit and finite model results from universal decoder enforcement or deployment.

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

Resolve the effective limit before treating a rehearsal refusal as a runtime
failure. A test can deliberately use a conservative floor while the native
runtime scales its budget with the context window. Check constructor behavior,
profile configuration, tool registration overrides and the actual delivery path.
Label substituted registry entries or configuration readers as fixtures. Check
both result and turn budgets. Do not raise a production limit to fix a refusal
that occurred only under a fixture's smaller limit.

## Make the worker's completion action explicit

If complete evidence arrives but a worker generates text until its deadline,
inspect its actual loaded instructions and native tool sequence. A prose answer
is not necessarily the workflow's required review transition. Test a narrow
instruction change through the existing role surface before adding an engine,
changing models or increasing the deadline. The
[advisory review example](examples/advisory-review-instructions.txt) asks an
already admitted worker to submit a short review through its existing tool, then
stop. Its word limit is guidance, not a host-enforced token or time bound.

Keep source, model settings, tools and deadline comparable. Preserve the failed
run. An existing owner may select one continuation with exact task, origin,
failed-row and source bindings; that does not create a general retry policy.
Check the new prompt, complete evidence, tool arguments and return, final stop,
process settlement, independent content review and delivery separately. One
successful continuation does not establish causal improvement or sustained work.

Inspect the owner's completion operation before using it to close the task.
Completion can remove scratch workspaces, create a separate approval history
row, recompute dependencies or invoke hooks. Keep durable evidence in its
existing owner-controlled location before selecting those effects. Do not delete
receipts merely to make an accepted advisory show a completed status. A reviewed
result and its native task status can remain distinct and explicit.

## Budget each model request separately

A producer request can fit while the independent reviewer request exceeds the
same limit. The reviewer can include instructions, the original binding, source
excerpts, the complete candidate, claim IDs and repeated critical fields. Measure
its final serialized bytes as a separate boundary. Do not infer fit from the
producer, source-file size or candidate size alone.

This synthetic example builds both requests without files, network or a model:

```python
import json


def bounded_json_request(instruction, body, max_bytes):
    payload = json.dumps(
        body, ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    request = instruction.encode("utf-8") + b"\nDATA\n" + payload
    if len(request) > max_bytes:
        raise ValueError("complete request exceeds byte limit")
    return request


evidence = {"facts": ["x" * 100]}  # Synthetic size data, not factual evidence.
limit = 240
producer = bounded_json_request("Produce an advisory.", evidence, limit)
assert len(producer) <= limit
review_body = {
    "binding": {"request_id": "synthetic-1", "generation": "a" * 64},
    "candidate": {"advice": "y" * 90},
    "sources": evidence,
}
try:
    bounded_json_request("Review the complete advisory.", review_body, limit)
except ValueError:
    pass  # Refuse this review request; do not dispatch or retry the producer.
else:
    raise AssertionError("oversized reviewer request was accepted")
```

Use the actual serializers and retained model-facing messages in the owning
system; this example does not reproduce an SDK or grant execution authority.
Count UTF-8 bytes after escaping, and check outer result-frame limits separately.
Byte limits and token limits are different constraints.

Exercise small and larger allowed candidates without removing binding fields,
policy or uncertainty. A narrow margin for one ASCII fixture is not a bound for
all allowed Unicode, quotes or answer lengths. Recheck the actual request before
dispatch. Preserve an earlier producer result if review input is refused.

If a compact evidence projection is selected, retain and bind its original
source. Preserve each requirement, authority limit and explicit unknown. A
reference such as "keep the required unknowns" is sufficient only when their
full values remain visible in both actual requests. Do not replace evidence
with hashes or assume unavailable recovery tools will supply it. Source fit,
prepared SDK context, physical provider delivery and useful review remain
separate claims.

## Separate host envelope size from model input size

Measure the host envelope and each model request independently. A host envelope
can contain a duplicate answer even when the exact original answer bytes are
already retained and passed as a separate argument. An explicit reference format
can remove that duplicate without removing evidence from either model phase.

Keep the original raw-byte digest, binding, complete sources and claim IDs.
Resolve the reference from the supplied original bytes, then apply the existing
strict candidate, citation, source, claim-order and join checks. Require one exact
format and key set; old or mixed formats must refuse. Preserve native controls
that read fields such as claim IDs. A hash alone cannot supply model evidence:
the complete answer must still reach each phase that requires it.

This synthetic example measures representation size and byte identity. It uses
no files, network, model, recovery tool or execution authority:

```python
import hashlib
import json


def encode(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


candidate_raw = b'{"advice": "Synthetic documentary advice."}'
digest = hashlib.sha256(candidate_raw).hexdigest()
expanded = {
    "binding": {"request_id": "opaque-example"},
    "candidate_sha256": digest,
    "candidate": json.loads(candidate_raw),
    "sources": [{"text": "Complete synthetic evidence."}],
    "claims": ["advice"],
}
reference = {key: value for key, value in expanded.items() if key != "candidate"}
reference["kind"] = "host-candidate-reference/v1"
assert set(reference) == {"kind", "binding", "candidate_sha256", "sources", "claims"}
assert reference["kind"] == "host-candidate-reference/v1"
assert hashlib.sha256(candidate_raw).hexdigest() == reference["candidate_sha256"]

restored = {key: value for key, value in reference.items() if key != "kind"}
restored["candidate"] = json.loads(candidate_raw)
assert encode(restored) == encode(expanded)
assert len(encode(reference)) < len(encode(expanded))


def model_input(body):
    return encode({"candidate": body["candidate"], "sources": body["sources"]})


assert model_input(restored) == model_input(expanded)
# Equivalent parsed values do not authorize replacement of retained raw bytes.
altered_raw = candidate_raw + b" "
assert json.loads(altered_raw) == restored["candidate"]
assert hashlib.sha256(altered_raw).hexdigest() != reference["candidate_sha256"]
```

Keep all existing request and aggregate bounds. A smaller host envelope can
admit an answer whose model input still exceeds its own cap. Refuse that input
before dispatch; never trim it or raise the limit to complete the example.
Compare complete phase bytes before and after the change, then qualify the
actual decoder, SDK context and normal execution path separately. Source-level
equivalence does not establish provider delivery, lower latency or model accuracy.

## Retain the exact serialized context

A context hash alone cannot recover the messages it identifies. SDKs can add
timestamps or other fields before the hash boundary. Capture the exact serialized
text used by that hash once, then retain the text beside the digest. Rebuilding a
similar object later does not establish which context was prepared.

Retaining only a parsed object can also lose the original field order when
custody sorts nested keys. An exact JSON string survives that outer sorting.
Parse it for inspection and hash its original UTF-8 bytes for comparison. Keep
the existing serializer and hash domain; do not translate between serializers.

This standalone example uses synthetic data and no files, network or model:

```python
import hashlib
import json


def read_context(receipt, max_bytes=16384):
    if set(receipt) != {"prepared_json", "prepared_sha256"}:
        raise ValueError("unexpected receipt fields")
    text = receipt["prepared_json"]
    if not isinstance(text, str) or not 0 < len(text.encode("utf-8")) <= max_bytes:
        raise ValueError("missing or oversized context")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != receipt["prepared_sha256"]:
        raise ValueError("context digest mismatch")
    context = json.loads(text)
    if not isinstance(context, dict):
        raise ValueError("context must be an object")
    return context


prepared = {
    "model": "synthetic-local-model",
    "messages": [{"role": "user", "content": "Synthetic input", "timestamp": 1234}],
    "tools": [],
}
# Capture once at the actual boundary, including dynamically added metadata.
snapshot = json.dumps(prepared, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
receipt = {
    "prepared_json": snapshot,
    "prepared_sha256": hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
}
stored = json.dumps(receipt, sort_keys=True, ensure_ascii=False)
restored = json.loads(stored)
assert read_context(restored) == prepared
assert restored["prepared_json"] == snapshot

# The same parsed values with sorted keys do not preserve the original bytes.
sorted_snapshot = json.dumps(prepared, sort_keys=True, separators=(",", ":"))
assert json.loads(sorted_snapshot) == prepared
assert hashlib.sha256(sorted_snapshot.encode("utf-8")).hexdigest() != receipt["prepared_sha256"]
```

Keep complete-result limits as well as the inner context limit. JSON escaping
can enlarge the outer frame. Preserve an oversize refusal rather than truncating
the context or accepting a hash-only fallback. This example checks retention;
the owner still verifies the expected roles, complete content, source binding,
freshness and permitted actions. Prepared SDK context and physical provider
delivery are separate observations. A matching digest grants no authority.

## Bound a complete source section

If an instruction source exceeds the reader's body cap, refuse it or maintain a
smaller complete source section. A prefix is not a complete section. Preserve
the original requirements and history, and distinguish the hash of the whole
input from the hash of the returned body.

```python
from harness.source_read import complete_section

view = complete_section(approved_source_bytes, "Current", max_body_bytes=4096)
context = view["body"].decode("utf-8")
```

This pure helper matches exact literal H2 lines, preserves source bytes and line
ranges, and refuses absent, duplicate or oversized sections. It performs no file
or network access. The owner still supplies a stable authorized source snapshot,
identity, freshness and admission checks; these hashes do not establish them.
Keep source-format checks specific to the target rather than treating this as a
general Markdown parser. Package tests do not qualify a native reader or broker.

## Compare file metadata through the same API

Qualify source reads on the actual service interpreter. A working maintenance
interpreter does not prove the service has the same file-metadata behavior.
Windows pathname `stat` and handle `fstat` can report different `ctime` values
for the same unchanged file. Keep the timestamp check; compare two handle
snapshots instead. See the [CPython issue](https://github.com/python/cpython/issues/157671)
and [Windows timestamp documentation](https://docs.python.org/3.13/library/os.html#os.stat_result.st_ctime).

```python
from pathlib import Path
from harness.source_snapshot import stable_snapshot
from harness.source_read import complete_section

snapshot = stable_snapshot(Path("PROJECT-STATE.md").absolute())
view = complete_section(snapshot["source"], "Current")
```

The caller must authorize that exact canonical path. The snapshot refuses
observed file replacement, metadata drift, aliases, multiple links and byte-limit
violations. It compares all seven identity/size/time fields before and after the
read and through a second handle; both handles are closed on failure. It grants
no authority, owner attestation, continuous pathname lock or OS time bound.
After a wrapper failure, retain the original outcome and inspect its actual
error stage before changing the runtime, dropping a check or replaying effects.

## Check the pin against the actual read budget

A valid hash declaration can still select a file that the reader cannot open
within its byte limit. Check the maintained pin's declared size against the
selected budget before I/O. Test that path through the actual bounded reader;
a fixture that supplies hash-approved bytes can hide an incompatible limit.

`pinned_snapshot` reuses the existing consistent-handle reader. Its byte budget
is mandatory. It checks the declared size before opening the file, then checks
the actual stable bytes against both the size and SHA256 pin.

```python
import hashlib
from pathlib import Path
import tempfile
from harness.source_snapshot import pinned_snapshot

payload = b"public source example\n"
with tempfile.TemporaryDirectory() as folder:
    source = Path(folder).resolve() / "state.bin"
    source.write_bytes(payload)
    snapshot = pinned_snapshot(
        source, len(payload), hashlib.sha256(payload).hexdigest(), max_bytes=256)
    assert snapshot["source"] == payload
    try:
        pinned_snapshot(source, 257, "a" * 64, max_bytes=256)
    except ValueError:
        pass
    else:
        raise AssertionError("An impossible pin must refuse before reading")
```

The owner selects the authorized canonical path, pin and budget. The helper
does not authenticate that owner or increase the budget from the file's own
size. An oversized pin needs an explicit owner disposition; it is not a reason
for an automatic larger read or a replay of an uncertain operation. Qualify
the consumer's real interpreter and entry path as well as maintenance tests.

## Keep comparison time domains explicit

Preserve the original timestamp literal and its offset. Normalize comparison
values to UTC; refuse missing offsets. A zone conversion can change the calendar
day. Do not combine a local date with a UTC time or treat a display label as
evidence that a parser preserved UTC.

```python
from datetime import datetime, timezone

def utc_timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("An explicit timestamp offset is required")
    return parsed.astimezone(timezone.utc)

source_literal = "2030-07-02T00:15:00+01:00"
assert utc_timestamp(source_literal).isoformat() == "2030-07-01T23:15:00+00:00"
assert utc_timestamp("2030-07-01T23:16:00Z") > utc_timestamp(source_literal)
try:
    utc_timestamp("2030-07-01T23:16:00")
except ValueError:
    pass
else:
    raise AssertionError("A naive timestamp must refuse")
```

This is comparison evidence, not a freshness lease or an OS deadline. Keep
monotonic time for local wait budgets. After a verification failure, inspect
the actual runtime before restarting it: a failed time comparison can reject
a working process. Retain that failed receipt and qualify a later observation
separately.

## Separate capture, publication and answer accuracy

A normal read can schedule a complete collector while returning an older cached
snapshot. Fresh capture files can precede publication of that snapshot in memory.
Use the existing cache readiness interface and coherent source observations;
do not infer completed publication from file freshness alone. Account for all
guarded readers that the normal refresh can invoke, even for a single-project
request. Bound successful status observations and local waiting, and state any
unbounded blocking I/O. Do not retry failed HTTP calls or relax age checks to
produce success.

Check each requested source. Returning current instructions does not complete
a request for a separate project brief. Inspect the complete returned report
and source fields within the full-frame budget; a report count alone is not
preservation evidence. Distinguish brief report fields from original document
bodies and a retained native response from an independent upstream capture.

Keep retrieval, delivery and final-answer accuracy separate. Compare quoted
dates with their exact source values. A response that grants no action
permission does not establish whether an existing owner authorization exists.
The runtime owner must check authority before action. These are acceptance
requirements, not a claim that this package supplies a general answer verifier.

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

## Preserve complete numeric values in log projections

Prefer structured counters from the existing observer. When a bounded log
projection is necessary, preserve the complete numeric literal. A pattern that
starts after a comma can turn `12,345 tokens` into `345 tokens` and suggest a
false context limit. This small example supports nonnegative decimal quantities
with optional standard comma grouping; signed, scientific and malformed forms
remain unmatched:

```python
from decimal import Decimal
import re

UNIT_VALUE = re.compile(
    r"(?<![\w.,+\-\u2212])"
    r"(?P<number>(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?)"
    r"\s*(?P<unit>tokens|ms|seconds)\b",
    re.IGNORECASE,
)

def numeric_units(text):
    return [
        (Decimal(match["number"].replace(",", "")), match["unit"].lower())
        for match in UNIT_VALUE.finditer(text)
    ]

assert numeric_units("12,345 tokens; 2.5 seconds") == [
    (Decimal("12345"), "tokens"), (Decimal("2.5"), "seconds")
]
assert numeric_units("12,34 tokens; -7 tokens; 1e3 tokens; 1.2.3 ms") == []
```

Keep the original failed projection and mark its numeric conclusions unqualified.
Correcting the parser does not correct an old measurement or justify another
runtime query. A recognized number and unit still do not identify the counter's
meaning, request, model, timing stage or cause. Bind those through the existing
source and observation contract before selecting an optimization.

## Separate fresh observations from new work

When a periodic worker repeats the same review, compare its actual admitted
input before changing the model or scheduler. A capture timestamp or a count of
changes in the latest run can change while the material being reviewed stays
the same. Hashing the whole status file can turn housekeeping into new work.

Reacquire the authorized current sources at each assembly. Validate their
schema, freshness and physical read constraints first. Then form an explicit,
versioned material projection for that use case. Keep the raw source hashes
with the observation; the material digest does not replace them. For example,
this pure projection expects an already validated capture-metadata record:

```python
import hashlib
import json


def review_material_key(validated):
    material = {name: validated[name] for name in (
        "contract", "export_count", "manifest_path_size_sha256")}
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


first = {"contract": "capture-metadata/v1", "export_count": 3,
         "manifest_path_size_sha256": "a" * 64,
         "captured_at": 100, "changed_this_run": 2}
refreshed = dict(first, captured_at=200, changed_this_run=0)
changed = dict(refreshed, manifest_path_size_sha256="b" * 64)
assert review_material_key(first) == review_material_key(refreshed)
assert review_material_key(first) != review_material_key(changed)
```

The field selection is a domain decision, not a universal deduplication rule.
This example identifies metadata about paths and sizes, not file contents.
Same-size text edits, complete capture coverage and downstream consumer use
remain unproved. Include a content identity when the actual task requires one.
Freshness validation must still run even when the material digest is unchanged.

Reuse the existing owner lock and snapshot path. Acquire current data once for
an assembly, retain the admitted snapshot, and make loaded guards check that
immutable snapshot. Repeated current-file reads during one model request can
mix observations or reject an unrelated capture refresh. For unchanged
material, reuse the original retained evidence instead of rewriting its date
or inventing a new work identifier. A finite count or byte quota must hold at
exhaustion; it does not establish permanent unattended operation.

Keep failure scope narrow. A missing or stale current-data record can use an
owner-defined data-hold result after source and custody checks. A corrupt
immutable snapshot, changed code pin, wrong identity or lost lock remains a
protected failure. Do not catch every `ValueError` around the entire assembly
and silently continue. Small JSON can also raise `OverflowError` during numeric
conversion or `RecursionError` during parsing; classify those only at the
intended current-data boundary. If the implementation uses a typed exception,
verify the loaded callback and provider use the same class instance.

Check the real normal path after source tests: actual acquisition and retained
snapshot, complete prepared input, producer and independent reviewer output,
process settlement, then a later unchanged-material cycle with no duplicate
model call. A cold assembly or an SDK preparation without inference establishes
only that earlier stage. Test an actual data outage separately before claiming
that other routes continue during it. Use existing telemetry and receipts;
this procedure adds no scheduler, store or execution authority.

## Check the method that the composed worker executes

A passing helper test can miss a guard inherited by the real worker. Before
changing admission, inspect the actual class resolution order, bound method,
loaded module and constructor dependencies. A test double that supplies its own
reader does not establish the behavior of an inherited production reader.

This small example checks the resolved method without calling it:

```python
class EvidenceGuard:
    def check(self, evidence_generation):
        if evidence_generation != self.generation:
            raise ValueError("Evidence generation differs")


class Worker(EvidenceGuard):
    generation = "current"


worker = Worker()
expected = EvidenceGuard.check  # Obtained from the independently checked module.
assert type(worker).check is expected
assert worker.check.__self__ is worker
assert worker.check.__func__ is expected
```

Identity checks need the real loaded object and independently checked source;
file presence alone is insufficient. Check separately pinned dependencies too:
updating a factory's source hash does not update a reviewer's own literal gate
hash or its relative caller path. Exercise the real composed constructor before
publication. Keep a failed qualification and use a new forward candidate.

Keep a narrow negative classification separate from positive admission. A known
invalid result can be reported as held without consuming the scheduler's model
slot, after its required source and custody checks. That must not admit valid
evidence from the wrong generation, relax required fields, reset an uncertain
attempt or catch arbitrary integrity failures. Verify both the specific negative
case and the unchanged positive refusal through the real composed host.

Then observe normal scheduled cycles: which routes were visited, which model
phase actually ran, and whether retained work changed. Visiting every route with
no model call proves bounded traversal and model-free idle for those cycles.
It does not prove useful work, fairness under load or continuous operation.

## Check versioned startup paths before publication

A new filename and matching manifest hashes can still contain an old literal
self-location guard. Check the candidate's own expected path, parent references,
contract hash and generated manifest together. Update only the references whose
meaning changed; a retained parent version can still be correct.

Run the existing effect-free validation prefix with the candidate bound to its
intended installed filename before publication. A staging filename can produce a
different result. Record whether this checked candidate bytes or installed bytes.
After publication, check the actual installed guard before the first service
start. Source consistency alone does not prove startup readiness.

Include the consumer's required profile environment in that check. A correct
file and path can still refuse when its expected home variable is absent. Isolate
one context difference before changing the guard. In an existing owned validator
process, scope an in-process override and restore both absent and empty values:

```python
import os

prior = os.environ.get("APP_HOME")
try:
    os.environ["APP_HOME"] = expected_profile  # Host-reviewed string.
    actual_guard(expected_profile)
finally:
    if prior is None:
        os.environ.pop("APP_HOME", None)
    else:
        os.environ["APP_HOME"] = prior
```

This changes process-wide state; use an isolated validator without concurrent
consumers. For an existing child-process check, supply its environment directly.
Keep interpreter, user, path and capabilities explicit when comparing results.
Passing a fixture context still needs the actual installed check.

Keep the point where the service-start command is issued explicit. A wrapper
failure before that point is different from an uncertain start command. Preserve
the failed program and receipts. Use one reviewed forward correction and the
existing owner lifecycle; do not infer permission to retry an uncertain start.
Verify the new process identity, readiness, unchanged settings and released owner
handles. Restore availability before unrelated qualification work. A connected
process still needs a separate user-facing behavior check.

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
