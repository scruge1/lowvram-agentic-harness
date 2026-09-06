# Portable Task Enforcement

The enforcement layer supervises one bounded task. The worker can be any command-line
agent harness. The supervisor, not the worker, owns research admission, retry limits,
output freshness checks, verifier execution, and the final receipt.

## End-user result

A user provides a reviewed `task.json` contract. It defines:

- the objective and worker command;
- the files that the worker must produce;
- the allowed retry classes and finite attempt budget;
- an optional research command and minimum independent-source count;
- a separate verifier with a same-program negative control; and
- the output path for the host-written enforcement receipt.

The supervisor then runs this sequence:

```text
validate contract -> admit research -> run worker -> inspect tool events
                  -> verify fresh outputs -> retry with exact feedback
                  -> write receipt -> independently revalidate receipt
```

This is a trustworthy executor only relative to the reviewed contract. An accepted
receipt proves that the declared research and checks passed against the recorded
bytes. It does not prove that an arbitrary prose objective was complete or correct.
The package does not generate a verifier from the worker's own answer and call that
independent proof.

## Install and run

Python 3.9 or later is required. The enforcement core has no runtime dependencies.

```bash
python -m pip install -e .
trusted-task doctor --root path/to/project --spec path/to/project/task.json
trusted-task dry-run --root path/to/project --spec path/to/project/task.json
trusted-task run --root path/to/project --spec path/to/project/task.json
trusted-task verify-receipt --root path/to/project \
  --spec path/to/project/task.json \
  --receipt path/to/project/artifacts/enforcement-receipt.json
```

Run `examples/enforced-task/demo.py` from a copied example directory for a complete
offline proof. It admits two hashed source records, rejects the first worker output,
feeds the verifier failure into attempt two, verifies the corrected output, and has
the outer SSOT perform independent project acceptance.

When an agent will integrate this package into an existing system, do not begin with
manual adapter copying. Bootstrap a target-local setup SSOT first:

```bash
trusted-task-integrate --root /path/to/target --host claude-code \
  --surface AGENTS.md --component enforcement --component ssot
```

See `AGENT-INTEGRATION.md`. Bootstrap authority is only `scaffolded`; the target's
own instruction, hook, bypass, test, rollback, and acceptance paths must be compiled
and proved before the installation reaches `tested`.

## What is enforced without a host adapter

The portable supervisor sees a foreign harness as one process. It can still enforce:

- exact command and control-file hashes;
- required research admission before work;
- process and verification retries;
- exact failure feedback between attempts;
- current-attempt output production;
- verifier immutability and negative controls; and
- receipt revalidation against current files and the hash-chained event log.

It cannot see each tool call inside the foreign harness.

## What a host adapter adds

The templates in `adapters/` connect native Claude Code, Hermes, or Pi lifecycle
events to `trusted-task hook`. While the supervisor is running, it supplies the
policy and event-directory environment variables. The adapter records tool success
or failure and blocks normal completion while a failure remains unresolved, subject
to the finite inner retry budget. The outer supervisor then decides whether another
full attempt is allowed.

Never replay an unknown side-effecting operation automatically. The adapter asks the
agent to correct or explicitly abandon the failed operation. The task contract caps
both inner prompts and outer attempts.

The normalized protocol and template contents have offline tests. The current
release does not claim live-host verification for the three templates.

## Research boundary

When research is required, the research command must return JSON with:

- `verdict: "grounded"`;
- hashed `source_records` for at least the declared source count;
- one or more consensus claims;
- distinct citation URLs meeting the source floor; and
- a non-empty evidence quote for each cited URL.

`harness.research_ground` produces this shape. A custom command may do the same. The
supervisor hashes the complete admitted receipt and includes that hash in its final
receipt. Hashes prove byte identity, not source truth. Strong deployments should keep
retrieved source bodies in protected evidence storage and use a trusted fetch path.

## Use with the blessed SSOT

Use one enforcement receipt as a declared stage output. Configure the SSOT stage
verifier to call `trusted-task verify-receipt`. The SSOT then adds requirement
conservation, dependency ordering, immutable work orders, whole-project acceptance,
and derived project status around the task supervisor.

This repository caps local authority at `tested`. A local user can rewrite the
controller, verifier, and receipts. Cryptographic `blessed` authority requires a
protected external signer or receipt custodian.
