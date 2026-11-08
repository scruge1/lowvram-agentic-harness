# Pi source parity: stop public/private drift becoming invisible

**Status:** read-only source inspection. This utility does **not** copy files,
install a Pi extension, infer semantic equivalence, reconcile model memory,
promote authority, schedule work or merge a repository branch.

The public low-VRAM harness and a private rig can evolve independently.
A source-level gap cannot be identified reliably by remembering what an AI
assistant said it changed. The underlying installed bytes and public Git
source revision must be inspected instead.

`scripts/pi_source_parity.py` compares explicitly mapped source files using
SHA-256 of the actual bytes and reports whether each is byte-identical,
different or missing. The report includes **only logical component IDs,
hashes, sizes and statuses**, not source bodies or machine-specific paths.

## Running the audit

Make a private copy of
`examples/pi-source-parity-map.example.json` and correct each
`installed` path for your local Pi extension tree. The example intentionally
uses generic filenames; private installations may use versioned filenames.

The two root directories and mapping are supplied explicitly:

```bash
python scripts/pi_source_parity.py \
  --public-root /path/to/lowvram-agentic-harness \
  --installed-root /path/to/your/pi/extensions \
  --mapping /private/location/pi-parity-map.json \
  --strict-drift > /private/location/parity-receipt.json
```

Run from a host where **both source trees are actually accessible**. The
public source root should be checked out at a known Git revision; record that
revision separately with `git rev-parse HEAD`. With `--strict-drift`, exit 0
requires every mapped pair to match; exit 2 means a
**complete but review-required** inventory. Exit 1 means invalid/unavailable
source boundaries, and does not claim any source matched.

The manifest schema is `pi-source-parity-map/v1` with 1–128 unique
`{id, public, installed}` records. Paths are canonical POSIX relative
paths beneath the two separately supplied roots; absolute paths, traversal,
symlinks and duplicate mapped files are refused. Regular files are read
through bounded 32 MiB streaming digests; source changes during a read
invalidate the audit. The tool does not execute source code.

## What the result means

- `byte_identical`: exact bytes match; this is **not** independent proof that
  the installed process has reloaded, or that the code is correct.
- `needs_review`: source differs. This could be an intended rig-specific
  adapter, a newer private feature, a safer public guard or unrelated code.
  **Do not replace either version automatically.**
- `missing_public`, `missing_installed` or `missing_both`: the mapping
  cannot establish parity, even if another similar file exists elsewhere.

The report does not declare a newer version based on file timestamps.
A source mismatch must be reconciled against exact commit/source identity,
original developer test evidence, safety/permission requirements and
independently reproduced negative controls. Use a separate feature branch,
portable fixtures, clean installed Pi acceptance and Linux/Windows CI.
Keep current running Pi processes and owner-held GPU services unchanged.

A SHA-256 file hash can reveal that a private program matches a known public
version. **Treat complete private audit receipts as private engineering
evidence**. Do not publish private manifests, credentials, transcripts,
repository paths, hostnames or complete installed-source hashes by default.

This parity report is not a backup of ChatGPT, Claude, Codex, Gemini or Pi
session histories. Verbatim conversation recovery remains an independently
scoped archival task. See
[CROSS-ASSISTANT-CONTINUITY.md](CROSS-ASSISTANT-CONTINUITY.md).

## Tests

```bash
python -m unittest discover -s tests -p test_pi_source_parity.py -v
```

Checks include identical and different file pairs, complete missing-source
states, unsafe paths, malicious/oversized mapping, duplicate IDs and source
paths, same-root false parity, oversized source files, symlink escapes and
redacted CLI failures. Tests create only disposable synthetic files.
