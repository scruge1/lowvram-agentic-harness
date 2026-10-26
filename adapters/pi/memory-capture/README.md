# Pi transcript capture

Run this once with explicit user-owned paths and the installed MemPalace Python:

```text
python -B capture.py --sessions-root ABS --state-root ABS --palace ABS --mempalace-cli ABS --session-file ABS --export-only
```

All four path arguments are required for capture. Linux is required for the reviewed file
lock. `--session-file` captures only that current session inside the specified
root. Omitting it explicitly selects the whole supplied session root. The
installer must not scan old sessions or import another agent's history without
the user's instruction. A Pi settlement/shutdown notification can request one
capture; it must not request another model turn or establish task completion.

`--export-only` formats and redacts without mining. Remove it to use the native
local miner and check exact drawer/closet coverage. Mining may need a local
embedding model and can download that model on first use. Configure/cache the
selected model under the chosen home before claiming offline readiness. This
does not use a generative observer or approve cloud processing.

Original JSONL bytes remain untouched, including unreadable or thinking-only
sources. Captured exports contain readable dialogue, explicitly untrusted peer
text and tool outcome metadata. They exclude tool bodies/arguments and thinking
blocks. Redaction is best effort; keep all capture state private and outside Git.
Large-source scratch streams stay on the selected state volume.

Verify native stored coverage with:

```text
python -B verify.py --state-root ABS --palace ABS
```

Verification uses the actual captured source catalog and exact native chunks,
normalization generation, export modification time and closet witness. It does
not use private known-token probes or reread another source corpus. A successful
readback proves retained export coverage only. It does not prove history is
current, sensitive material is absent, a recalled claim is true, or an arbitrary
project is complete. No scheduler or service is installed by these scripts.

## Persisted capture status

The existing `pi_memory_capture_status` tool reads this home's persisted receipts
after native session reopen. It does not capture, mine, query a palace, download
an embedding model, scan other sessions or issue another agent turn. It reuses
the pinned helper, normal process guard and shared home lifecycle consumer.

For an explicitly selected owned root, the metadata-only CLI is:

```text
python -I -B capture.py --status --sessions-root ABS --state-root ABS
```

This read-only mode needs no palace or MemPalace executable. The installed
`memory_runtime.py --home HOME capture-status` route fixes both roots to the
selected home and refuses extra arguments.

Capture computes raw-prefix and export SHA-256 while its existing reader and
formatter already process those bytes. Versioned per-source receipts live in
the existing private `latest.json`; `sources.json` keeps its original
`[size, mtime_ns]` values for older consumers and rollback. Old rows or receipt
loss remain unverified until an explicitly selected recapture. A repeated
unchanged source does not refresh its original capture time. Failed or pending
mining stays visible without claiming stored native coverage.

Status reports historical prefix hashes, age, observed metadata changes,
unobserved tails, missing exports and declared parse deferrals. It never reads
raw bodies or rehashes gigabytes to answer a status question. A size/mtime match
is labelled as metadata only: current raw bytes remain cryptographically
unverified. Captured dialogue and tool metadata are not a complete raw
diagnostic archive. Query trust and exact native chunk verification stay
separate.

Each metadata file is bounded at 2 MiB; at most32 known sources and8 KiB of
status content are returned. Omitted known sources are explicit. Unknown/new
sessions outside the catalog are not scanned or counted as covered. Capture
still requires an explicit root or current-session notification; there is no
all-host importer, scheduler, source replacement or automatic claim promotion.
