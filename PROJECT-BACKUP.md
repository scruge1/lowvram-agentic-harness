# Project snapshots and verified exports

Use the installed `harness/project_backup.py` helper with the selected home's
Python interpreter. This first capture route requires Linux and an integrated
home lifecycle guard. Stop managed agents, the owned memory hub and other home
consumers first. A busy lease or pending update refuses capture.

```sh
"/selected/python" -I -B /selected/home/runtime/harness/project_backup.py capture \
  --home /selected/home --project /selected/home/projects/example \
  --destination /selected/backups/example-001
```

The JSON result contains `manifest_sha256`. Retain that exact value outside the
snapshot when moving or storing it. Restore into a new, absent destination:

```sh
"/selected/python" -I -B /selected/home/runtime/harness/project_backup.py restore \
  --snapshot /selected/backups/example-001 --manifest-sha256 EXACT_SHA256 \
  --destination /selected/exports/example-001
```

The snapshot includes the selected project, its self-contained `.git` directory,
and its exact home-bound project state, including Kanban and the knowledge index.
It includes untracked project files. No agent credentials, native session
history, packages or global memory outside those trees are selected. Keep the
destination private. Linked Git worktrees, external Git object stores, symlinks,
special files and hardlinks are refused in this first route.

Capture checks the installed identity helper, original path-bound project
identity, source membership and content. It holds the existing exclusive home
lease. Each SQLite backup pins a committed snapshot with `BEGIN` and a schema
read before the native backup API. Committed WAL rows are included; transient
SQLite journals and lock sidecars are not raw file copies. Native integrity,
board tenant and knowledge-manifest bindings are checked before publication.
The lease covers cooperating managed users. Detected external source changes
refuse publication; it does not prevent an unmanaged process from writing files.

Default limits are4GiB and20,000 entries, including Git. Use explicit
`--max-bytes` and `--max-files` when needed. The selected destination volume must
have headroom. `--copy-seconds` and `--validation-seconds` default to180 each.
Capture has a copy phase and an independent validation phase. Restore validates
the input, copies it, then independently validates the export; each validation
has its own allowance. File loops and native SQLite callbacks check deadlines.
These checks do not establish a hard bound on blocked operating-system I/O.

Successful restore reports `verified_export` and `activated:false`. It verifies
manifest membership, file hashes, Git location and SQLite data in the new tree.
The original identity bytes and paths are retained. It does not admit the export
as a new project, rewrite state paths, merge a board or enable execution there.
Later active adoption requires its own supported migration route.

An existing destination is never overwritten. A failed operation retains its
partial destination and `failure.json`; it cannot be used as an accepted snapshot.
Inspect that evidence and choose a new destination. No automatic retry, remote
archive, retention deletion or scheduler is added.
