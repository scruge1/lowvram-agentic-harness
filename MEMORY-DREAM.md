# Source-bound, bidirectional memory Dream review

**Status:** opt-in local review candidate. **No automatic memory mutation,
hidden scheduler, autonomous promotion, background model calls, task
authorization or new memory store.**

This module addresses a recurring long-project failure mode: a local
assistant treats whatever it remembered most recently as correct and
forgets the technical and architectural evidence that established the
earlier decision. The Dream review works **from the oldest evidence forward
and from the newest evidence backward**, detecting competing claims and
source drift rather than silently choosing the latest observation.

It preserves separate ownership for Claude-mem, MemPalace, Pi session
journals, ICM workspaces and verified task receipts. It does not pretend
those sources form one identical conversation history.

## Read-only deterministic entry

Run from the repository root for an already-admitted project on a local
machine with the required original evidence:

```sh
python -m harness.memory_dream \
  --home /absolute/managed-home \
  --project /absolute/existing-admitted-project < private-evidence.json
```

The input is a bounded JSON envelope with schema
`agent-home-dream-evidence/v1`, an exact existing `project_id`, and
1–64 explicitly supplied evidence records. Every record needs a source ID,
kind, topic key, actual claim, SHA-256 digest, ISO timestamp and matching
project identity. An optional `source_path` plus exact `source_quote`
allows current-file verification. Files must be within the admitted
project or supported Home session/capture trees, be regular owned
single-link files, and match both the cited digest and excerpt. Original
sources **must not be copied to this public Git repository**.

Example envelope structure (placeholders are **not** valid evidence):

```json
{
  "schema": "agent-home-dream-evidence/v1",
  "project_id": "EXACT_EXISTING_PROJECT_ID",
  "evidence": [
    {
      "project_id": "EXACT_EXISTING_PROJECT_ID",
      "source_id": "approved-decision-001",
      "source_kind": "icm",
      "claim_key": "design.decision",
      "claim_text": "The existing policy requires an independently checked source.",
      "source_sha256": "EXACT_SHA256_OF_CURRENT_ORIGINAL",
      "observed_at": "2026-11-08T18:00:00Z",
      "verification": "retrieval_only"
    }
  ]
}
```

The output is `agent-home-dream-review/v1`. It groups evidence by
claim key and reports first-to-last/last-to-first source IDs, competing
variants, exact-source qualification and the strongest *candidate*
state actually supported by the evidence. It does not output raw claim
text, home paths, credentials or full original session contents.
**Newest is not necessarily best.**

A `SOURCE_PINNED_CANDIDATE` still requires independent review. A
`CONTRADICTION_REVIEW_REQUIRED` must not be treated as a decision.
A retrieval-only summary cannot become a blessed SSOT, approval to
alter the system, or evidence that a workflow succeeded.

## Optional local model suggestions

The `analyze_local(home,project,request,config)` library function can
call an **explicitly configured local IP-literal OpenAI-compatible
endpoint**, subject to bounded content, timeout and no-redirect/no-proxy
controls. This is not invoked by the default CLI or installer.
Model responses must be valid bounded JSON whose source IDs match the
original evidence topic. Their authority is always
`UNVERIFIED_LOCAL_MODEL_SUGGESTIONS`; they cannot update ICM, create a
work order, mark memory current or perform an external effect.

A native Claude-mem tool-field adapter accepts only complete,
hash-verified, project-matched stored-field windows. It **does not**
pretend a Claude-mem observation provides independent original-source
authority, and does not connect to Claude-mem's database itself. The
existing native memory owner still handles access, selection and
redaction.

## Tests and integration boundary

```sh
python -m unittest discover -s tests -p test_memory_dream.py -v
python -m ruff check harness/memory_dream.py tests/test_memory_dream.py
```

Synthetic tests cover owner/project identity, current-source hashes,
exact excerpts, stale/foreign sources, duplicated identities, conflicting
chronology, no filesystem changes, input/secret limits, native Claude-mem
field provenance, local-stub model JSON controls, no public network
destinations and no unsafe CLI response leakage. Python 3.13 Windows
fixtures require stable `path.stat` versus `fstat` birth timestamps and
native case-normalization for stored project paths; the Linux
runtime still requires exact original project identity and ctime-based
source drift refusal. On a local rig test,
the corresponding private candidate received two proposals from a
real Q4 model, but that is *not* proof of long-term memory ranking,
research quality or an autonomous learned memory manager.

**Next necessary stage:** source-owned inventory adapters for all
supported histories, a read-only candidate/decision review board,
targeted regression tests against previously accepted rules,
explicit owner-reviewed promotion, and a scheduled trigger that can
never auto-write blessed memory or activate an unrelated project.
This public source layer does none of those on its own.
