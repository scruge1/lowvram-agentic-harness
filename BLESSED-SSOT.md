# Starter Blessed SSOT

This repository includes a small, harness-neutral control plane for long-running
agent work. It is separate from the local-model harness. Use either component
without the other.

The worker can be Pi, Claude Code, Codex, Qwen, an OpenAI-compatible client, a
shell script, or a person. A worker cannot mark its own stage complete. The host
controller derives status from exact files, receipts, dependencies, and separate
verifier commands.

## What this version preserves

- One canonical `ssot-project.json` with stable PRD stage IDs.
- A conserved requirement inventory. Each applicable requirement has exactly one
  owning stage; every source has an exact hash; unresolved requirements block
  acceptance; waivers and supersessions need independent evidence.
- An acyclic dependency graph and a derived current frontier.
- Declared material-to-product edges and one producer for each output.
- Immutable work orders with exact target, dependency, verifier, and manifest hashes.
- Host-observed runtime identity, including exact local-model identity and settings.
- A cross-process controller lock around every state mutation.
- Same-run output checks. A pre-existing unchanged output is not production.
- Host-written producer receipts. A model-authored success claim has no authority.
- Separate, read-only verifier commands with required same-program negative
  controls. A verifier that changes project bytes fails.
- Stale target, stale verifier, changed output, replay, self-verification, and skip rejection.
- Hash-chained append-only events and immutable JSON receipts.
- Whole-project independent acceptance and an explicit local authority cap.

## What it does not claim

This is a compact reference implementation. It is not the private source workflow,
does not contain private project data, and has not inherited production authority.
Local hashes are tamper-evident only. A user who controls the filesystem and code
can rewrite both. Add an external signer, protected event store, trusted clock,
and independent operator identity when that threat matters.

Use a small SSOT work directory that contains exact copied or mounted target
inputs. The read-only verifier check hashes every non-state file in that work
directory before and after execution. Do not place model weights, build caches,
or an unrelated monorepo inside it.

The included example has `authority_cap: tested`. Passing it proves that the
reference workflow functions. This controller rejects `blessed`: that state needs
an external signer or protected trust service, not another field in local JSON.

## Project contract

Create `ssot-project.json` in the project root:

```json
{
  "schema_version": 1,
  "project_id": "my-project",
  "authority_cap": "tested",
  "target": {"files": ["PRD.md"]},
  "requirements": [
    {
      "id": "REQ-001",
      "text": "Build the requested artifact.",
      "scope_class": "project_specific",
      "source": {
        "path": "PRD.md",
        "locator": "section:Output",
        "sha256": "REPLACE_WITH_SHA256_OF_PRD"
      },
      "disposition": "applicable",
      "owner_stage": "build"
    }
  ],
  "stages": [
    {
      "id": "build",
      "objective": "Build the requested artifact.",
      "acceptance": "The artifact contains the required result.",
      "depends_on": [],
      "requirements": ["REQ-001"],
      "materials": ["PRD.md"],
      "trace_output": "artifacts/run-trace.json",
      "outputs": ["artifacts/result.json", "artifacts/run-trace.json"],
      "properties": ["artifact contains the required result"],
      "verifier": {
        "owner": "host-checker",
        "type": "deterministic_property",
        "argv": ["{python}", "checks/verify_result.py"],
        "negative_control": {
          "argv": ["{python}", "checks/verify_result.py", "--negative-control"]
        },
        "files": ["checks/verify_result.py"],
        "timeout_seconds": 60
      }
    }
  ],
  "acceptance": {
    "owner": "independent-acceptor",
    "type": "deterministic_property",
    "argv": ["{python}", "checks/accept_project.py"],
    "negative_control": {
      "argv": ["{python}", "checks/accept_project.py", "--negative-control"]
    },
    "files": ["checks/accept_project.py"],
    "timeout_seconds": 60
  }
}
```

Paths are exact, relative files. The controller rejects paths outside the project
and duplicate output producers. Commands are argument arrays and run with
`shell=False`. `{python}` resolves to the interpreter running the controller.

## Workflow

For a new project, initialize from the exact PRD:

```bash
python -m ssot.cli --root . init --prd PRD.md --project-id my-project
python -m ssot.cli --root . doctor
```

Initialization is intentionally incomplete. It hashes the PRD and creates one
whole-source requirement with `disposition: unresolved`. Replace that row with a
reviewed, lossless requirement inventory. Configure stage ownership, dependency
and material edges, declared outputs, independent verifiers with negative controls,
and whole-project acceptance. `doctor` will not issue work while any part remains
unresolved or invalid. This prevents a parser or model from silently inventing the
meaning of an arbitrary PRD.

The simplest operational path lets the controller launch the worker:

```bash
python -m ssot.cli --root . next
python -m ssot.cli --root . run build --worker any-harness \
  --runtime-file runtime.json -- my-agent-command --its args
python -m ssot.cli --root . accept --acceptor independent-acceptor
```

`next` returns read-only packets for every stage on the current dependency frontier.
`run` passes the command an exact environment contract: `SSOT_PROJECT_ROOT`,
`SSOT_RUN_ID`, `SSOT_STAGE_ID`, `SSOT_EXPECTED_OUTPUTS`, and
`SSOT_TELEMETRY_PATH`. The stage must declare `trace_output` as one of its outputs.
The host writes that trace, rejects changes to protected `.ssot` state, records
same-run output bytes, and invokes the stage verifier.

Local-model and remote-model harnesses must write their call telemetry JSON to
`SSOT_TELEMETRY_PATH`. Script workers need no additional telemetry file. The model
telemetry schema is the same one enforced by the lower-level submission API.

Harnesses that already own process execution can use the lower-level path:

```bash
# Inspect the graph and current frontier.
python -m ssot.cli --root . status

# Create one immutable work order. Give its JSON to any worker or harness.
python -m ssot.cli --root . prepare build --worker qwen-local \
  --runtime-file runtime-qwen.json

# The worker writes only the declared outputs. Then the host records their bytes.
python -m ssot.cli --root . submit RUN_ID --worker qwen-local \
  --execution-file execution.json

# The host runs the separately configured verifier.
python -m ssot.cli --root . verify RUN_ID

# After every stage is verified, run whole-project independent acceptance.
python -m ssot.cli --root . accept --acceptor independent-acceptor
```

If a worker crashes, close its order before retrying:

```bash
python -m ssot.cli --root . abandon RUN_ID --reason "worker process stopped"
```

Never edit `.ssot` records to make a stage pass. Fix the output, create a new work
order, and retain the failed or abandoned run as evidence.

For a local model, the runtime file records the host-observed executor, harness
and version, attempt/fallback identity, provider and model families, exact
checkpoint and served ID, backend, quantization, endpoint, prompt/context SHA-256
digests, and sampling object. Script and person workers use the smaller shape in
`examples/ssot-starter/runtime-script.json`.

On the lower-level path, the host creates `execution.json` after the call. Every execution records
`host_observed`, `status`, `duration_ms`, and a `trace_file` that is also a
declared stage output. Model executions also require `model_call_id`, byte and
token counts, `tool_calls`, and declared raw and parsed output files. The
controller hashes those files itself; it does not trust model-supplied hashes.

## Status meaning

- `scaffolded`: files exist but have not passed contract compilation.
- `compiled`: the project contract and conserved inventory validate.
- `configured`: a host-issued work order exists.
- `enforced`: every stage has a live verifier receipt, but independent acceptance
  has not passed.
- `tested`: independent acceptance passed under a `tested` authority cap.

`complete` is true only at `tested`. `stages_verified` exposes the earlier enforced
state. Local files cannot establish `blessed` authority.

Changing the PRD, project manifest, verifier code, target bytes, dependency receipt,
material bytes, runtime receipt, or output bytes invalidates dependent completion
automatically.

## Compose it with the task supervisor

The SSOT controls the project graph. `harness.enforcement` controls one worker task.
Use them together when a stage needs research, corrective retries, or native harness
tool-failure feedback:

1. Declare the task result, research receipt, enforcement receipt, and SSOT trace as
   stage outputs.
2. Run `python -m harness.enforcement run` as the SSOT stage worker command.
3. Configure the stage verifier to call `verify_receipt()` or
   `trusted-task verify-receipt` against the live enforcement receipt.
4. Keep whole-project acceptance separate from that stage verifier.

The complete offline composition is in `examples/enforced-task`. Its first worker
attempt fails verification. Attempt two uses the exact failure feedback and passes.
The SSOT then independently verifies and accepts the project at `tested`.

See `UPSTREAM-REFACTOR.md` for the exact source commits and the boundary between
transferred behavior and stronger capabilities that remain external.

## Try the offline example

Copy the example before running it so generated evidence stays out of this repository:

```bash
cp -R examples/ssot-starter /tmp/ssot-starter
PYTHONPATH="$(pwd)" python /tmp/ssot-starter/demo.py
```

On Windows PowerShell:

```powershell
Copy-Item examples\ssot-starter "$env:TEMP\ssot-starter" -Recurse
$env:PYTHONPATH = (Get-Location).Path
python "$env:TEMP\ssot-starter\demo.py"
```

Run the contract regression suite with:

```bash
python -m unittest discover -s tests -v
```

Run the full dependency-free release gate with:

```bash
python scripts/verify_ssot_release.py
```

The exact v1 completion boundary is in `RELEASE-CHECKLIST.md`.
