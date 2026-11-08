# Bounded Pi request-intake replies

**Release scope:** model-facing presentation only. The exact native intake
state, original captured sources, frozen routing intent, task waits and
execution admission remain in the existing journal and tool-result `details`.
This feature does **not** add a board, new queue or source of authority.

## Why

On a long-running project, request-intake status may contain dozens of
retained tasks, pending messages, dependency tickets and original source text.
Sending the complete native JSON into the model on every status or route call
needlessly repeats old material and can consume limited context memory.

`adapters/pi/intake/intake-model-view.mjs` projects a bounded model view,
normally below **6,144 UTF-8 bytes**, while `details.result` retains the exact
successful native result. The projector never rewrites the result in place.
A presentation failure returns a safe recovery pointer and **must not turn an
already successful mutation into a failure requiring a retry**.

Short results remain unchanged for compatibility. Long status/state replies
include totals, clipped reason/next-action summaries, selected conversation,
waiting state, indexed pages and the SHA-256 of the complete native reply.
Large non-status reconciliation results become non-authoritative summaries
rather than appearing verbatim.

## Exact source recovery

The existing `kanban_intake_status` tool accepts optional read-only paging:

```text
kanban_intake_status({source_id:"source-id"})
kanban_intake_status({
  source_id:"source-id",
  source_offset:1024,
  source_limit:1024,
  expected_reply_sha256:"reply-hash-from-first-view",
  expected_source_sha256:"text-hash-from-first-view"
})
```

Source text offsets count **Unicode codepoints**, not UTF-16 units or bytes.
The model can follow `source_text.next_offset` until null, and must restart
when a source or native reply hash no longer matches. This is a read-only
retrieval mechanism: an old chat request, deferred idea or reconstructed
source **does not provide fresh approval**.

The tool also accepts queue, pending, wait and bound offsets/limits of up to
20 entries per model view. The *underlying public intake status* already limits
its queue snapshot to 30 and its pending snapshot to 12. Paging therefore
does **not** expose arbitrary historical rows beyond that source snapshot;
the complete native journal is maintained separately. The original capture
identified by `source_id` is not clipped by that queue snapshot.

## Verification

```bash
python -m unittest discover -s tests -p test_pi_intake_projection.py -v
python -m unittest discover -s tests -p test_pi_conversation.py -v
```

The pure projection fixture uses a synthetic 762 KB reply and validates
Unicode source reconstruction, pagination, stale cursor refusal, bounds,
clipped pending and waiting data, non-status receipt handling and unchanged
native result identity. The full-module request-intake fixture exercises
original capture through its real registered tool, extracts and rebuilds
captured source, checks invalid paging and confirms that reading the view
does not create a task.

Actual Pi 1.4 installed-loader and Linux/Windows release CI are separate
qualification gates. These tests do not measure provider-specific prompt
caching, autonomous project outcomes or actual running-model token savings.
No private transcripts, rig paths, credentials or task histories are
transferred into the public repository.
