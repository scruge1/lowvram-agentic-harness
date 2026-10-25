# Pi transcript capture

Run this once with explicit user-owned paths and the installed MemPalace Python:

```text
python -B capture.py --sessions-root ABS --state-root ABS --palace ABS --mempalace-cli ABS --session-file ABS --export-only
```

All four path arguments are required. Linux is required for the reviewed file
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
