# Enforced Task Example

Copy this directory before running it. The offline research command emits the same
receipt shape as `harness.research_ground`. The first worker output is rejected. The
supervisor writes the verifier reason to the feedback file, launches attempt two,
and accepts only the corrected output.

```bash
trusted-task doctor --root . --spec task.json
trusted-task run --root . --spec task.json
```

Without installation, run from the repository root:

```bash
python -m harness.enforcement doctor --root examples/enforced-task --spec examples/enforced-task/task.json
python -m harness.enforcement run --root examples/enforced-task --spec examples/enforced-task/task.json
```

Use a copied directory for the second form because it creates `.enforcement/` and
`artifacts/` evidence.
