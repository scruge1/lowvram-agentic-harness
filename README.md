# Low-VRAM Agentic Harness

Run a **big Mixture-of-Experts model on a small consumer GPU**, and drive it with a
small **agentic harness that checks its own work, retries on failure, and grounds
answers in real cited sources**.

Independent pieces, useful together or apart:

For slow or unreliable workflows, start with [evidence-first diagnostics](DIAGNOSTICS.md).
Agents use this procedure before selecting an optimization. [Upgrade notes](UPGRADES.md)
bind each distilled change to its parent source version and state its adoption limits.

1. **Local low-VRAM inference** — how to serve a 30B-parameter MoE model (only ~3B
   active per token) on a single 8–11 GB GPU (RTX 2080 / 3060 / 4060) by keeping the
   expert layers in CPU RAM and only the attention/shared layers on the GPU. This is
   a stock `llama.cpp` feature (`--n-cpu-moe` / `--cpu-moe`), not a custom hack.
2. **The harness** (`harness/`) — a few hundred lines of dependency-light Python that
   turns a one-shot model call into a reliable loop:
   - `verify.py` — a deterministic **claim-provenance gate**: every fact the model
     states must bind to a real quote from its source, or it is dropped as a
     hallucination. No second model needed to catch the first one lying.
   - `dispatch_retry.py` — **dispatch → verify → retry**: on a verified failure the
     reason is fed back so the next attempt is a correction, not a re-roll.
   - `paired_gate.py` — a **KEEP/REVERT measurement gate** for when you tweak a prompt
     or check: keep the change only if it improves recall on a labeled test set
     *without* raising the false-positive rate (the trap that catches rubber-stamping).
   - `research_ground.py` — **search → fetch → mine → verify → consensus**: answer a
     question from real web pages, keeping only claims that ≥N independent sources
     agree on, each with its citation.
   - `model_catalog.py` + `dispatch_retry.dispatch_cold_swap()` — pick a model by
     **size class + rank** from `models.yaml` instead of a hardcoded tag, and retry a
     verified failure by **cold-swapping to a different model** (a different training
     lineage, not just a re-roll) when the same model keeps making the same mistake.
   - `hardware_probe.py` + `scripts/autotune_offload.py` — **don't trust a number
     measured on someone else's GPU.** Probes your real VRAM/RAM and sweeps
     `--n-cpu-moe` settings on your actual machine to find what fits, before you ever
     run the harness for real.
3. **Starter blessed SSOT** (`ssot/`) — a harness-neutral control plane for long
   projects. It gives any worker an immutable work order, permits work only at the
   dependency frontier, hashes same-run outputs, runs a separate host verifier, and
   derives completion from live receipts. Pi, Claude, Codex, Qwen, shell scripts, and
   people are interchangeable workers; none can bless its own output. See
   [BLESSED-SSOT.md](BLESSED-SSOT.md).
4. **Portable task enforcement** (`harness/enforcement.py`) — put any command-line
   harness behind a reviewed task contract. It admits required research, applies
   bounded process/tool/verification retries, passes exact failure feedback to the
   next attempt, checks fresh outputs with an independent negative-controlled
   verifier, and emits a receipt that the SSOT can consume. See
   [ENFORCEMENT.md](ENFORCEMENT.md).
5. **Agent-led integration** (`harness/integration.py`) — bootstrap installation into
   a specific target as its own unresolved SSOT project. The integrating agent must
   compile the target's instructions and real action paths before making changes.
   See [AGENT-INTEGRATION.md](AGENT-INTEGRATION.md).
6. **Trusted project workflow** (`harness/project.py`, `harness/prd.py`,
   `harness/compiler.py`, and `harness/executor.py`) — capture exact user intent,
   `harness/compiler.py`) — capture exact user intent, admit a reinforced and
   independently reviewed PRD, conserve every requirement in a target SSOT, and
   promote verifier drafts, execute portable script stages only through enforcement,
   account for budgets, recover interrupted work, and derive independent acceptance
   without choosing the user's model or harness. See
   [TRUSTED-PROJECT.md](TRUSTED-PROJECT.md).
7. **Pi project coordinator export** (`adapters/pi/project-workflow/`) — a
   deployment-neutral version of the qualified interactive Pi workflow. It
   admits one project, discovers actual native tools, reuses project knowledge,
   binds planning advice and verified work to an exact Kanban card, preserves
   restart/resume state, prepares closeout records, and compiles immutable
   project-local skill candidates. See
   [adapters/pi/project-workflow/README.md](adapters/pi/project-workflow/README.md).

The design principle throughout: **a weak local model is a good reader and a poor
authority.** So the harness lets the model read, extract and paraphrase, and uses
deterministic checks + cross-source agreement to decide what is actually true.

> These mechanisms are generalized from a private production system. The algorithms
> are the real, proven ones; the domain-specific parts were stripped out. This is a
> general-purpose starter harness, not a copy of that system.

## Hardware assumptions

- One consumer NVIDIA GPU with **8+ GB VRAM** (this repo targets an RTX 2080 — also
  8 GB, same class as the reference machine below).
- **System RAM is unknown for your machine and matters as much as VRAM** — the MoE
  expert layers live in CPU RAM, so a low-RAM box needs a smaller quant regardless of
  how much VRAM it has. Run `python harness/hardware_probe.py` first; it tells you the
  truth about your machine instead of assuming it matches anyone else's.
- A recent NVIDIA driver + CUDA. CPU-only also works (slower); AMD works via the
  Vulkan build of llama.cpp.

## Honest performance expectations

This is a **real measured number, not an estimate**: Qwen3-30B-A3B-Instruct-2507
(Q4_K_XL, ~17 GB on disk) on an **8 GB RTX 3070** via llama.cpp with `--n-cpu-moe 34`,
flash-attention on, q8_0 KV cache, ran at **~19 tok/s using ~6.4 GB of the 8 GB VRAM
budget**. An RTX 2080 is also 8 GB VRAM and a similar generation — expect the same
ballpark, but **system RAM is the unmeasured variable on your specific box** (the
3070 machine's RAM isn't part of this repo's numbers). Run
`python scripts/autotune_offload.py plan` first, then `run` once you have the model
     downloaded, to get YOUR real numbers instead of trusting someone else's.
Notes on that config:
- Both machines needed to close anything else GPU-heavy first — a 30B-class MoE plus
  literally any other GPU process does not fit in 8 GB.
- It **works and is genuinely usable for agentic, non-interactive work** (the harness
  runs tasks in the background and verifies them) — it is **not** a snappy chatbot.

If you want speed over size, a dense **7–8B model fits entirely in 8 GB** and will do
30–60+ tok/s. The 30B-A3B is the "surprisingly capable for its speed, given it barely
fits" option. Both are supported — it is just a config change (see `models.example.yaml`'s
`reasoner-small` class).

## Quickstart

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
(optionally) grounds a question in cited web search. Everything runs locally.

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
system RAM. That is why **system RAM, not VRAM, is the real constraint** here.

## Using the harness in your own code

```python
from harness.llm import LocalLLM
from harness.dispatch_retry import dispatch, make_llm_worker, verifier_json
from harness import verify, research_ground

llm = LocalLLM()                                  # reads config.yaml / env
worker = make_llm_worker(llm)

# dispatch a task, demand JSON, retry up to 3x with the failure reason fed back
result = dispatch("Return {\"answer\": <int>} for 2+2", worker, verifier_json, max_retries=3)

# check that a model's claims bind to a source (drops hallucinations)
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
  verify.py          claim-provenance gate (deterministic hallucination catcher)
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
