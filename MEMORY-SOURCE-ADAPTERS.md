# Existing memory sources → unverified Dream evidence

**Status:** opt-in, source-owned conversion. No memory-store replacement, network
reader, scheduled import, model deployment, writeback or project authorization.

The public low-VRAM harness already has an independent
`validated-memory-query/v1` filter. It checks retrieved MemPalace rows against
an explicitly reviewed claim registry and the recorded source hash. That
makes a *retrieval* suitable for human-guided analysis; it does not make a
memory sentence canonical project state.

`harness.memory_dream.from_validated_mempalace_result()` converts **one
already-returned validated-retrieval hit** into an evidence window for the
bidirectional Dream reviewer. It does not invoke MemPalace, read a user palace,
create a database or append a Pi session record.

## Combining the original sources

For an existing admitted ICM project and reviewed retrieval result:

```python
from harness import memory_dream as dream

# validated_result came from the existing reviewed MemPalace query.
# Select the exact current ICM project and a deliberate topic key.
candidate = dream.from_validated_mempalace_result(
    validated_result,
    project_id=existing_project_id,
    claim_key="architecture.model-routing",
    result_index=0,
)

envelope = {
    "schema": dream.SCHEMA,
    "project_id": existing_project_id,
    "evidence": [candidate],  # add independently sourced Pi/ICM/Claude-mem windows
}
view = dream.preview(existing_home, admitted_project, envelope)
assert view["authority"] == "retrieval_only"
```

The converter requires the original validated-query schema, exact
`verified_retrieval_only` authority, non-abstention, bounded result counts,
current state, reviewed evidence class, SHA-256 source/claim digests,
a timezone-aware evidence timestamp and a safe text length. Unknown action
or authority fields and malformed drawer/absolute source locators are refused.

It creates a stable pseudonymous `mp-...` source ID bound to the original
retrieval identity, source locator, claim digest, source digest and evidence
date. It **deliberately omits the raw locator and `source_quote`** from
the Dream input. Without an independently verified current original file,
Dream must classify the result as `SOURCE_REVIEW_REQUIRED`, never
`SOURCE_PINNED_CANDIDATE` or accepted.

`from_claude_mem_tool_window()` independently converts a full,
source-digest-matched native Claude-mem tool-field window. ICM decisions
and Pi session records must still be drawn from their original files
and validated using `dream.preview()` source checks. A newer MemPalace
summary does not supersede an older owner decision merely because it
has a later timestamp.

**Project membership limitation:** the original validated-memory result
does not carry independent ICM project admission proof. The caller must
select the appropriate project and review the origin before claiming a
relevant relationship. The conversion assigns a *candidate scope*, not a
new permission or proof that the memory belongs to that project. An
untrusted original may not be opened or acted upon merely because its
content resembles a current project.

## Verification

```sh
python -m unittest discover -s tests -p test_memory_dream_mempalace.py -v
python -m unittest discover -s tests -p test_memory_dream.py -v
```

The tests use the **actual public validated-memory query** with a synthetic
original source and reviewed registry. They check source drift, sensitive
and obsolete hits, row/authority injection, spoofed remote locators,
private path omission, exact bound result counts and a real conflicting
Claude-mem historical window. All accepted output remains read-only
and unverified. No actual local model endpoint or GPU is called.

Next integration gates are source-owner adapters for native ICM and Pi
journals, independent time-scoped semantic tests, explicit owner
decision review, and a host-owned scheduled read-only Dream pass. The
public repository does not yet implement an autonomous memory manager.
