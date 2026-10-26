# Current project knowledge and original sources

This first Library backend uses the existing project source policy, Markdown/text
files, source manifest and derived SQLite FTS5 index. It adds no database, service,
automatic watcher, model or write permission. The selected project must already
have its normal identity. Use the installed helper and the same project state
base as that home:

```sh
PI_PROJECT_STATE_BASE=/selected/home/state/projects /selected/python -I -B \
  /selected/home/runtime/adapters/pi/project-workflow/project_knowledge.py status \
  --root /selected/project

PI_PROJECT_STATE_BASE=/selected/home/state/projects /selected/python -I -B \
  /selected/home/runtime/adapters/pi/project-workflow/project_knowledge.py query \
  --root /selected/project --current --terms 'orchard' --limit 5

PI_PROJECT_STATE_BASE=/selected/home/state/projects /selected/python -I -B \
  /selected/home/runtime/adapters/pi/project-workflow/project_knowledge.py read \
  --root /selected/project --source docs/record.md --start-line 1 --limit 20
```

Strict query validates policy/manifest/project bindings, current source bytes,
index metadata and actual stored chunks in one read-only SQLite snapshot. Changed,
added, deleted, unsupported or mismatched data does not produce current search
results. `status` explains the mismatch. Neither command rebuilds anything.

An exact current-source read can still work after an edit with `index_fresh:false`.
It returns current source SHA256, line positions, exact window/hash and a partial
flag. `--expected-sha256` refuses an old hit's binding if the current bytes changed.
The window is at most4000 characters and50 lines. Paths must be selected direct
project files; foreign paths, symlinks and hardlinks refuse.

Import, edit and deletion remain ordinary authorized project file actions. After
reviewing those effects, use the existing explicit `build --root /selected/project`
command or existing rebuild tool. An old query without `--current`, including the
existing Pi query route, remains index-snapshot retrieval and is labelled
`indexed_snapshot_not_current_validated`. It does not claim source freshness.

Inspection uses the existing source policy and at most its default2MiB per file.
The optional `--seconds` is positive and at most the existing10-second adapter
ceiling. An incomplete inspection returns typed `deferred`, with no partial
query/source body. Default policy discovery prunes excluded directories. Complex
custom recursive globs defer rather than start an unbounded scan. Operating-system
I/O can still block; this is not a hard process-runtime guarantee.

Search uses the existing literal ASCII-term FTS query, not semantic retrieval.
UTF-8 source bytes and line endings are retained. PDF/image/other original-format
extraction, Library UI/import UX and full adoption remain open. No private notes,
conversation archive, credentials or global memory are imported. For a separately
authorized stopped snapshot and readable inactive export, use the existing
[project backup helper](PROJECT-BACKUP.md); this adds no Library export engine or
active-project migration.
