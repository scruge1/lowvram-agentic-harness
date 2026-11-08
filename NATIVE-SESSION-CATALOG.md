# Source-bound native Pi session catalogue

**Scope:** opt-in, local, read-only discovery of existing Pi 1.4 session
headers for one already-admitted project. No session writer, migration,
message parser, browser UI or AI inference is introduced.

The objective is project continuity across restarts and assistant changes.
Native Pi JSONL sessions are historical source material; a summary or model
memory is not a verbatim substitute. This catalogue makes it possible to
locate existing native sessions without dumping their contents to a model or
starting another instance that could corrupt a live writer's history.

## Usage (Linux managed Home)

From the public repository root:

```sh
python -m harness.session_catalog \
  --home /absolute/path/to/managed-home \
  --project /absolute/path/to/existing-admitted-project
```

This command requires the exact existing `.icm/project.json` identity and
the project's existing managed Home state ownership. It uses the same
`managed_launch.session_directory` path convention as the installed Pi 1.4
launcher. It **does not create** a missing session directory, initialize
a project, select a session, acquire a writer lock or resume a model.

It returns at most 20 records initially, each containing only native session
ID, created/updated timestamp, file byte size and a
`native_pi_session_header_only` source label. The response includes
`snapshot_sha256`, `total`, `offset`, and `next_offset`. For a further
page, pass its previous fingerprint:

```sh
python -m harness.session_catalog \
  --home /absolute/path/to/managed-home \
  --project /absolute/path/to/existing-admitted-project \
  --offset 20 --limit 20 \
  --expected-snapshot-sha256 PREVIOUS_SNAPSHOT_HASH
```

If the underlying session-file set, metadata, contents length or identity
changes, paging refuses and the caller must restart at offset zero.
A checksum of metadata is a **listing cursor**, not a digest of all session
contents or a statement that no unseen historical chats exist.

## Boundaries and provenance

- Requires Linux, the current owner UID, a regular single-link native JSONL,
  a valid native header and matching exact current project root.
- No session body, raw prompt, tool result, full filesystem path or credentials
  are returned in the listing.
- Invalid/oversized headers, duplicate session IDs, symlinks, moved or changing
  files, changed ICM project identity and foreign session buckets fail closed.
- The caller gets no execution privilege from seeing a session ID. Reopening
  any session must still use the existing cooperative writer lease and
  project admission flow, not this read-only module.
- The scanner is **not** automatically enabled by the public installer;
  it is a separate operator-invoked inspection command.
- This is **not** a ChatGPT, Gemini or Claude data export. Those products
  have separate histories and retention rules. A complete cross-provider
  archive still requires each original source, source digests and coverage
  reconciliation rather than reconstructing absent conversations.

## Verification

```sh
python -m unittest discover -s tests -p test_session_catalog.py -v
python -m ruff check harness/session_catalog.py tests/test_session_catalog.py
```

Tests use disposable synthetic project headers, including pagination,
changed-source refusal, foreign project and Home identities, missing buckets,
oversized or invalid headers, duplicate IDs, symlink containment, no message
body leaks and CLI no-write behavior. Host-specific symlink tests may skip
on Windows because creating them requires elevated privileges.

The source is derived from an independently tested private Agent Home
read-only session catalogue, **not** its Tauri desktop views or private
session records. Its public adapter is independently versioned and must
pass the normal Linux/Windows release suite before inclusion in `main`.
