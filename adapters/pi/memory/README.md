# Validated memory retrieval

This is the portable version of the source-bound memory retrieval filter.
MemPalace search results are candidate matches. Only an exact match in a
separately reviewed claim registry can return its approved safe summary.
No personal registry or memory records are included.

The filter abstains on sensitive queries before searching a palace or reading
a source. It rejects unregistered claims, changed sources, obsolete records,
unsafe summaries and invalid summary hashes. Current source bytes take priority
over a search result's recorded hash. A local source path must remain readable.
Live drawer references are checked against actual drawer content. Ambiguous
drawer identities do not gain provenance. Listing is bounded; failure to find
a drawer is an unresolved match, not proof that it does not exist.

## Configure Pi

Keep the two Python files together. Configure all these variables before loading
`validated-memory-query.ts`:

```text
PI_VALIDATED_MEMORY_PYTHON=/absolute/path/to/mempalace-environment/bin/python
PI_VALIDATED_MEMORY_HELPER=/absolute/path/to/validated_memory_query.py
PI_VALIDATED_MEMORY_POLICY=/absolute/path/to/memory_retrieval_policy.py
PI_VALIDATED_MEMORY_REGISTRY=/absolute/path/to/reviewed-claims.jsonl
PI_VALIDATED_MEMORY_HELPER_SHA256=<lowercase-sha256>
PI_VALIDATED_MEMORY_POLICY_SHA256=<lowercase-sha256>
PI_VALIDATED_MEMORY_REGISTRY_SHA256=<lowercase-sha256>
MEMPALACE_PALACE_PATH=/absolute/path/to/this-homes-palace
MEMPALACE_CONFIG_DIR=/absolute/path/to/this-homes-mempalace-config
```

Use the same isolated MemPalace environment and directories as the home's MCP
server. Both directories must exist. The helper binds them before importing
MemPalace. It never chooses the user's global default palace or configuration.
The wrapper hashes the helper, its actual sibling policy and the registry on
each invocation. Update those bindings deliberately after reviewing changes.
The initial registry is an empty JSONL file. Empty registries abstain without
loading MemPalace or downloading an embedding model.

Each registry row contains `claim_sha256`, `source_path`, `source_sha256`,
`safe_text`, `safe_text_sha256`, `state`, `evidence_class` and `observed_at`.
`claim_sha256` hashes whitespace-normalized candidate text. Source and safe-text
hashes bind their exact UTF-8 bytes. Optional fields include `claim_id`,
`valid_to` and `registry_receipt_sha256`. Source paths can name a local file or
`mempalace://drawer/<id>`. Supported evidence classes are `current_source`,
`verified_closeout`, `validated_lesson` and `raw_history`.

The registry is trusted review input. This adapter does not create claims,
promote model output, independently establish that a reviewer was correct, or
grant execution permission. Keep registry promotion separate from retrieval.

## CLI

```bash
python validated_memory_query.py --query "project lesson" --live \
  --claim-registry reviewed-claims.jsonl --limit 5
python validated_memory_query.py --query "project lesson" \
  --search-result search-result.json --claim-registry reviewed-claims.jsonl
```

`--output result.json` writes the result to that path. Offline search-result
files are supplied evidence; they do not establish live palace health. Package
tests cover the complete wrapper/helper path with explicit fixtures. A target
still needs a real authorized search, exact drawer readback and safe claim
promotion check before declaring semantic retrieval accepted.
