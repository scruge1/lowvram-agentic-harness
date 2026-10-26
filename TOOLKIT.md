# Toolkit and developer reference

Start with the [assistant installation guide](GETTING-STARTED.md) to use the
managed Pi assistant. This page covers the separate Python toolkit, local
inference examples and project-control interfaces.

The components can be used independently:

| Component | Purpose |
|---|---|
| `harness/verify.py` | Check supplied quotes against supplied source text. It does not establish that a claim is true. |
| `harness/dispatch_retry.py` | Retry a supplied worker with explicit failure feedback. |
| `harness/paired_gate.py` | Compare a change against a labelled baseline. |
| `harness/research_ground.py` | Search, retrieve and compare supplied source claims. |
| `harness/model_catalog.py` | Select an explicitly configured model candidate. |
| `harness/hardware_probe.py` and `scripts/autotune_offload.py` | Inspect hardware and measure a selected local inference configuration. |
| [Project coordinator](adapters/pi/project-workflow/README.md) | Connect native Pi tools to the admitted project, board and retained work. |
| [Task enforcement](ENFORCEMENT.md) | Run declared actions and separate output checks within an explicit task contract. |
| [Project control](BLESSED-SSOT.md) | Track dependencies, inputs and acceptance records independently of the worker. |

An output check establishes only its declared conditions. Source agreement,
successful commands and saved records do not establish general task quality.
The included local controller cannot grant the external `blessed` authority.
See [current qualification](AGENT-HOME.md#current-qualification) before making
claims about the complete assistant.

## Local inference and Python toolkit

```bash
# 0. Know your actual hardware first -- don't guess.
python harness/hardware_probe.py

# 1. Download the model (see SETUP.md step 3), then find the --n-cpu-moe setting
#    that actually fits YOUR machine (measured, not assumed):
python scripts/autotune_offload.py plan
python scripts/autotune_offload.py run --model models/Qwen3-30B-A3B-Instruct-2507-UD-Q4_K_XL.gguf     --llama-server /path/to/llama-server --write qwen3-30b-a3b-local

# 2. Launch the server with the winning settings printed above, e.g.:
llama-server -m models/Qwen3-30B-A3B-Instruct-2507-UD-Q4_K_XL.gguf -ngl 99     --n-cpu-moe 34 --flash-attn on --cache-type-k q8_0 --cache-type-v q8_0     -c 8192 -b 2048 --host 0.0.0.0 --port 8080

# 3. Point the harness at it and run the end-to-end demo.
cp config.example.yaml config.yaml         # edit base_url if not :8080
cp models.example.yaml models.yaml         # edit to match what you actually pulled
pip install -r requirements.txt            # optional; core runs on stdlib alone
python example_run.py --config config.yaml
```

Full walkthrough (including the hardware check and what to do if nothing fits) is in
SETUP.md.

`example_run.py` dispatches a task to your local model, verifies the JSON it returns,
retries with feedback if it is wrong, checks the model's facts against the source, and
(optionally) grounds a question in cited web search. The example uses the configured model server; web research also contacts its selected sources and search provider.

Every module also self-tests with **no server and no network**:

```bash
python harness/verify.py --selftest
python harness/paired_gate.py --selftest
python harness/dispatch_retry.py --selftest
python harness/research_ground.py --selftest
python harness/model_catalog.py --selftest
python harness/hardware_probe.py --selftest
python scripts/autotune_offload.py --selftest
python -m unittest discover -s tests -v
```

## The MoE-on-8GB trick in one paragraph

A Mixture-of-Experts model like Qwen3-30B-A3B has 30B total weights but activates only
~3B per token. Most of those 30B weights are the **expert** feed-forward layers, and
only a handful of experts fire for any given token. `llama.cpp` lets you keep those
expert tensors in **CPU RAM** (`--cpu-moe`, or `--n-cpu-moe N` to keep N of them on CPU)
while everything else — attention, embeddings, shared layers — goes on the **GPU**
(`-ngl 99`). So the GPU only ever holds the small always-active part plus the KV cache
(a few GB), which fits in 8 GB, while the big rarely-touched expert bank streams from
system RAM. Both system RAM and GPU memory, including the context cache, must fit the selected workload.

## Using the harness in your own code

```python
from harness.llm import LocalLLM
from harness.dispatch_retry import dispatch, make_llm_worker, verifier_json
from harness import verify, research_ground

llm = LocalLLM()                                  # reads config.yaml / env
worker = make_llm_worker(llm)

# dispatch a task, demand JSON, retry up to 3x with the failure reason fed back
result = dispatch("Return {\"answer\": <int>} for 2+2", worker, verifier_json, max_retries=3)

# Check exact source-quote bindings; review meaning and accuracy separately.
receipt = verify.verify_claims([
    {"claim": "...", "evidence_quote": "...verbatim...", "source_text": "...full source..."}
])

# ground an answer in cited web sources (needs a search backend + key; see config)
answer = research_ground.ground("your question", backend="brave", min_sources=2)
```

## Tracking a long multi-agent project

The SSOT controller is independent of the model harness. Start from a PRD, review
the deliberately unresolved contract, and then run each frontier stage through
any executable harness:

```bash
python -m ssot.cli --root path/to/project init --prd PRD.md --project-id my-project
python -m ssot.cli --root path/to/project doctor
# Review ssot-project.json: inventory every requirement and configure stages/checks.
python -m ssot.cli --root path/to/project next
python -m ssot.cli --root path/to/project run STAGE_ID --worker my-harness \
  --runtime-file path/to/project/runtime.json -- my-agent-command --its args
python -m ssot.cli --root path/to/project accept --acceptor independent-acceptor
```

`init` never guesses PRD semantics. It pins the source and creates a non-runnable
unresolved row, so an agent can help draft the inventory but a reviewer must resolve
it before `doctor` permits work. `run` is the simple adapter boundary: the controller
launches the supplied argument array, records the process, hashes declared outputs,
and invokes the independent verifier. The lower-level `prepare`, `submit`, and
`verify` commands remain available for harnesses that manage their own processes.

Read [BLESSED-SSOT.md](BLESSED-SSOT.md) before changing `authority_cap`. The
included local controller is capped at `tested`; it rejects `blessed` unless a
separate protected trust provider is implemented.

## Supervising a task from start to finish

Install the package, review a task contract, and run the portable supervisor:

```bash
python -m pip install -e .
trusted-task doctor --root my-project --spec my-project/task.json
trusted-task run --root my-project --spec my-project/task.json
trusted-task verify-receipt --root my-project --spec my-project/task.json \
  --receipt my-project/artifacts/enforcement-receipt.json
```

This works with any harness that can be launched as an argument array. Native tool
failure visibility needs the corresponding template in `adapters/`. A trustworthy
result also needs a human-reviewed acceptance contract; prose alone is not proof.
The full operating and trust boundary is in [ENFORCEMENT.md](ENFORCEMENT.md).

For agent-led installation into another system:

```bash
trusted-task-integrate --root /path/to/target --host generic \
  --surface AGENTS.md --component enforcement --component ssot
```

This creates an unresolved target SSOT. It does not install or declare success. Follow
[AGENT-INTEGRATION.md](AGENT-INTEGRATION.md) to compile and execute the integration.

The post-install natural-language experience is specified in
[NATURAL-LANGUAGE-ORCHESTRATION-SCOPE.md](NATURAL-LANGUAGE-ORCHESTRATION-SCOPE.md).
E6a through E6d are available through `trusted-project`. The
chosen harness drafts and reinforces the PRD; the portable controller requires exact
source and line bindings, lossless stage ownership, and independent negative-controlled
review. Portable `script_no_model` stages can then run to receipt-derived `tested`.
See [TRUSTED-PROJECT.md](TRUSTED-PROJECT.md). Live Claude Code, Hermes, Pi, and
metered-model acceptance remain E6e.

## File map

```
README.md            this file
SETUP.md             step-by-step manual install (hardware check, llama.cpp + CUDA, model, run, smoke test)
FAQ.md               failure modes + exact fixes, written for a human OR an AI agent doing the install
BLESSED-SSOT.md      contract and operating guide for the harness-neutral SSOT controller
ENFORCEMENT.md       portable supervisor, adapter, retry, research, and trust boundary
ENFORCEMENT-ADAPTER-PRD.md  requirements and completion stages for the supervisor
AGENT-INTEGRATION.md  target-bound blessed-SSOT setup path for an integrating agent
NATURAL-LANGUAGE-ORCHESTRATION-SCOPE.md  scoped post-install trusted-project workflow
TRUSTED-PROJECT.md  E6a-E6d activation, PRD, SSOT, execution, and continuity contract
UPSTREAM-REFACTOR.md exact source pins, transferred invariants, and trust boundary
RELEASE-CHECKLIST.md explicit v1 completion and publication boundaries
config.example.yaml  copy to config.yaml; endpoint, retries, thresholds, search backend
models.example.yaml  copy to models.yaml; size-tiered model catalog (cold-swap fallback chain)
requirements.txt     optional extras (PyYAML, requests); core is stdlib-only
example_run.py       end-to-end demo of the whole loop against your local server
harness/
  llm.py             local OpenAI-compatible chat client + config loader
  verify.py          claim-provenance gate (exact source-quote checks)
  dispatch_retry.py  dispatch -> verify -> retry-with-feedback loop, + dispatch_cold_swap (retry on a DIFFERENT model)
  paired_gate.py     KEEP/REVERT paired-control measurement gate
  research_ground.py search -> fetch -> mine -> verify -> consensus (cited grounding)
  model_catalog.py   pick a model by size-class + rank from models.yaml, never a hardcoded tag
  hardware_probe.py  real GPU VRAM + system RAM detection (no fabricated numbers)
  enforcement.py     reviewed contract -> research -> bounded retry -> verified receipt
  integration.py     absent-only target setup SSOT bootstrap
  project.py         explicit activation and immutable project intent protocol
  prd.py             source-bound PRD binding, reinforcement, and review checkpoint
  compiler.py        lossless reviewed-PRD-to-SSOT compiler and verifier promotion
  templates/         lossless agent integration setup contract
adapters/             Claude Code, Hermes, and Pi hook templates
scripts/
  autotune_offload.py  sweeps --n-cpu-moe on YOUR machine, launches the real server, keeps the fastest that fits
  verify_ssot_release.py  one-command offline SSOT release gate
ssot/
  control.py         dependency frontier, immutable receipts, verification, acceptance, derived status
  workflow.py        safe PRD onboarding, diagnostics, frontier packets, and host runner
  cli.py             init/doctor/next/run plus lower-level control commands
examples/
  ssot-starter/      two-stage offline reference project, verifiers, and demo
  enforced-task/     composed research/retry/enforcement/SSOT acceptance demo
tests/
  test_ssot_control.py  fail-closed SSOT contract regressions
  test_enforcement.py  supervisor, bypass, research, hook, and adapter regressions
```

## License / sharing

Released under the [MIT License](LICENSE).
