---
name: source-control
description: Save an explicitly reviewed source milestone through the existing workflow_step and verify its exact Git commit and optional remote delivery.
---

Read the selected project's instructions, checkpoint and source ownership first.
Keep the current root outcome and selected task. A task reference records the
caller's context; it does not grant permission or establish file ownership.

Use native inspection to review the actual Git root, changed files and index.
Keep credentials, raw transcripts, databases, models, media, caches and generated
state out of source. Leave other sessions' work untouched. An occupied index
requires coordination. Do not reset, stash, force-add or stage the whole tree.

After a useful verified milestone, create a reviewed inventory under the project
directory `.icm/workspace/artifacts/source-control/` through `workflow_step`.
The inventory is JSON: `safe_files` contains objects with an absolute `path` and
the current complete file `sha256`. Review every exact file before including it.
Bind the complete inventory's SHA-256. Do not include an unrelated file because
it is dirty. Resolve missing Git author configuration with the owner; do not
invent an identity or change global Git settings.

The installed helper is `{{HOME}}/runtime/harness/source_checkpoint.py`.
Run this absolute helper through
`workflow_step`, using the project's exact root as `cwd` and the installed Python:

```text
ACTION: python -B {{HOME}}/runtime/harness/source_checkpoint.py
  --project-root PROJECT --task-ref EXISTING_TASK
  --message "Save reviewed source milestone" --operation UNIQUE_OPERATION
  --inventory PROJECT/.icm/workspace/artifacts/source-control/reviewed.json SHA256
VERIFY: python -B {{HOME}}/runtime/harness/source_checkpoint.py
  --verify .icm/workspace/artifacts/source-control/UNIQUE_OPERATION/admission.json
OUTPUT: .icm/workspace/artifacts/source-control/UNIQUE_OPERATION/admission.json
REQUIRED_SKILLS: source-control
```

Supply actual argv arrays and real absolute paths. `python` above means the
exact interpreter in the installed `everyday-runtime.json`, not a guessed
environment. The project root must match workflow `cwd`. The verifier's receipt path
must stay relative to `cwd`; its absent-file rejection is also tested in an
empty directory. The helper defaults to a local commit. It does not initialize
another repository or infer source attribution from an arbitrary shell action.

Push only when the current owner instruction authorizes that delivery. Supply
all three explicit options: `--push-remote`, `--expected-push-url`, and
`--expected-branch`. Do not put credentials in a URL. The helper checks the
current branch, configured push target and actual remote ref. It does not infer
whether a hosted repository is private. Use the owner's established credential
helper. A local commit and a verified remote delivery are separate results.

After a failure, inspect the saved operation and complete workflow failure.
The local commit or staged files may already exist. Preserve them and unrelated
edits. Never replay an operation or reset the index to obtain a cleaner result.
Record the exact pending delivery or recovery step. A verified source commit
does not establish deployed behavior, model quality or root-outcome acceptance.
