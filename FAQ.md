# FAQ / Install Troubleshooting

Written so that **another AI coding agent** (Claude Code, Codex, etc.) can install this
for a non-technical user and fix problems without guessing. Each entry is
**Q: symptom → A: exact diagnostic command → exact fix command**. Run the diagnostic
first; only apply the fix its output points to. Do not invent filenames, URLs, or
versions — read them from the diagnostic output or the model repo's Files tab.

> Agent operating note: never fabricate a success. If a step's verification command
> does not print the expected output, report the actual output — do not proceed as if
> it passed. The one command that must pass before declaring the install done is
> `python example_run.py --config config.yaml` against a live server.

---

## Server / GPU

**Q: `nvidia-smi` is not found or errors.**
Diagnostic:
```bash
nvidia-smi || echo "NO NVIDIA RUNTIME"
```
Fix: install/repair the NVIDIA driver for the user's card. If the machine genuinely has
no NVIDIA GPU, build/run llama.cpp CPU-only (omit `-DGGML_CUDA=ON` and the `-ngl`/`--cpu-moe`
flags). The harness is unchanged; it will just be slower.

**Q: `llama-server` starts but loads everything on CPU (no GPU used).**
Diagnostic — look at the startup log for a line like `offloaded 0/N layers to GPU`, and:
```bash
nvidia-smi   # while the server runs: VRAM "Memory-Usage" should be a few GB, not ~0
```
Fix: you are running a non-CUDA build. Get the CUDA prebuilt binary (SETUP.md §1A) or
rebuild with `-DGGML_CUDA=ON` (§1B). Confirm with `llama-server --version` mentioning CUDA.

**Q: CUDA version mismatch / `cudaErrorInsufficientDriver` / library load error.**
Diagnostic:
```bash
nvidia-smi | grep -i "CUDA Version"      # driver's max supported CUDA
```
Fix: download the llama.cpp CUDA build whose CUDA version is **≤** the number shown, or
update the driver. Prebuilt CUDA 12.x binaries work with any 12.x-capable driver.

**Q: Out of memory on the GPU (`CUDA out of memory` / `failed to allocate` at load).**
This is the most common one on an 8 GB card. Apply in order, re-testing each:
```bash
# 1. shrink the context (KV cache lives on the GPU)
llama-server -m MODEL.gguf -ngl 99 --n-cpu-moe 40 -c 4096 --port 8080
# 2. if still OOM, raise --n-cpu-moe further (more experts pushed to CPU RAM, slower but fits)
#    -- or just run scripts/autotune_offload.py, which does this search for you
# 3. if still OOM even at max --n-cpu-moe, offload fewer non-expert layers to GPU, e.g. -ngl 20
# 4. if still OOM, drop context further (-c 2048) or use a smaller quant (Q3_K_M)
```

**Q: I don't want to guess --n-cpu-moe by hand -- is there a faster way?**
Yes -- this is the recommended path, not a fallback:
```bash
python scripts/autotune_offload.py plan
python scripts/autotune_offload.py run --model models/YOUR-MODEL.gguf --llama-server /path/to/llama-server --write MODEL_TAG
```
It probes real VRAM/RAM (`harness/hardware_probe.py`), launches the real server at
several `--n-cpu-moe` settings from safest to fastest, measures actual tok/s, and keeps
the fastest one that did not OOM. If something else is holding GPU VRAM, it reports
that too (add `--evict-others` only if you want it to close those processes for you --
it never does this silently).

**Q: Out of memory / heavy swapping in SYSTEM RAM (machine freezes, disk thrashes).**
Diagnostic: watch RAM while the model loads (`free -h` on Linux, Task Manager on Windows).
Fix: the expert layers do not fit in RAM. Use a smaller quant (Q3_K_M ~14 GB, or Q2_K),
or a smaller model. 30B-A3B at Q4 wants ~24–32 GB system RAM.

**Q: It loads but generation is painfully slow (<2 tok/s).**
Expected-ish on 8 GB (see README performance section), but to improve:
```bash
# keep a FEW expert layers on the GPU instead of all-on-CPU; tune N up until just-fits
llama-server -m MODEL.gguf -ngl 99 --n-cpu-moe 30 -c 4096 --port 8080
# nvidia-smi should now show VRAM near-full but not OOM. Lower N = more on GPU = faster.
```
Or switch to a dense 7–8B model that fits fully in VRAM for 30–60+ tok/s.

---

## Model download

**Q: Model download fails / 401 / file not found.**
Diagnostic:
```bash
huggingface-cli whoami 2>/dev/null || echo "not logged in (fine for public models)"
```
Fix: verify the exact filename on the repo's Files tab (do NOT guess casing/quant). Some
repos are gated — accept the license on the HF website, then `huggingface-cli login`.
Use `huggingface-cli download` (resumable) rather than curl for large files.

**Q: Which quant file do I pick?**
- 8 GB card, 32 GB RAM → `Q4_K_M` (best quality that fits comfortably).
- Tight RAM → `Q3_K_M` or `Q2_K`.
- Want speed, don't need 30B → a dense `7B`/`8B` `Q4_K_M`, no `--cpu-moe`.
Verify the file downloaded whole:
```bash
ls -la models/*.gguf     # size should match the HF listing (~18 GB for 30B-A3B Q4_K_M)
```

---

**Q: What other models can I cold-swap to (a "second substrate" for retries)?**
Real, checked answers as of when this repo was written:
- **Qwen3-30B-A3B-Instruct-2507** (`ollama pull qwen3:30b`) -- the proven default,
  already in `models.example.yaml` rank 1.
- **NVIDIA Nemotron-3-Nano-30B-A3B** (`ollama pull hf.co/unsloth/Nemotron-3-Nano-30B-A3B-GGUF:Q4_K_M`)
  -- a real, different-lineage 30B-A3B (NVIDIA, not Alibaba), already rank 2. Genuinely
  useful as a second opinion in `dispatch_cold_swap` -- not a reskin of the same model.
- **Muse-Glimmer-30B** (`hf.co/unsloth/Muse-Glimmer-30B-GGUF` or the mradermacher
  variant) -- real, agentic/Hermes-tuned. **Whether it's MoE or dense wasn't confirmed
  before shipping this repo** -- check the model card yourself before assuming it
  behaves like the two A3B models above.
- **A 30B-class Gemma MoE does not exist** (checked against ollama's own Gemma3
  library at the time of writing) -- Gemma 3's largest text model is a **dense 27B**
  (`ollama pull gemma3:27b`). If you were told otherwise, it was likely confused with
  one of the two Qwen/Nemotron models above, or a future release this repo predates.

Add any of these to `models.yaml` under the `30B-MoE` class at the next rank; nothing
else in the harness needs to change.

## Harness

**Q: `python example_run.py` says the endpoint refused the connection.**
Diagnostic:
```bash
curl -s http://localhost:8080/v1/models || echo "SERVER NOT UP"
```
Fix: start `llama-server` (SETUP §3) and confirm its log says `listening on ...:8080`.
If the server is on another port/host, set `HARNESS_BASE_URL` or edit `config.yaml` to match.

**Q: The harness connects to Ollama instead of llama.cpp — what URL?**
Ollama speaks the same API under `/v1`:
```bash
export HARNESS_BASE_URL=http://localhost:11434/v1
export HARNESS_MODEL=qwen3:30b-a3b     # must be the exact tag from `ollama list`
```
(For Ollama the MoE offload is automatic; there is no `--cpu-moe` flag to pass.)

**Q: dispatch keeps failing the JSON verifier — the model won't return clean JSON.**
Diagnostic: read the `attempt` lines it prints; if the model wraps JSON in prose/fences,
the verifier already strips ``` fences, so the issue is a weak/instruction-poor model.
Fix: raise `--max-retries`, use a larger quant, or use an instruct-tuned model. This is a
model-capability limit, not a harness bug — the harness is correctly refusing bad output.

**Q: `research_ground` returns `ungrounded` / no consensus.**
That is the correct answer when fewer than `min_sources` pages agree on a provenance-bound
claim. To loosen: `--min-sources 1` (weaker guarantee) or raise `--max-results`. To use
live search you must set a backend + key:
```bash
export BRAVE_API_KEY=...   # https://brave.com/search/api/   (backend brave)
# or SERPAPI_KEY=...        # https://serpapi.com/            (backend serpapi)
```
To use Perplexity/Exa/Tavily instead, implement `search()` in `harness/research_ground.py`
to return `[{"title","url"}]` — the rest of the pipeline is unchanged.

**Q: `ModuleNotFoundError: yaml`.**
Fix: `pip install pyyaml` — or ignore it; the harness has a built-in minimal YAML fallback
and still reads `config.example.yaml`. Env vars work with zero dependencies.

**Q: `ModuleNotFoundError: harness` when running example_run.py.**
Fix: run it from the repo root, or set `PYTHONPATH` to the repo root:
```bash
cd lowvram-agentic-harness && python example_run.py --config config.yaml
```

---

## Sanity checklist for an agent finishing the install

These checks are evidence inside the target setup SSOT. They are not, by themselves,
authority to report an agent-led integration complete. Start that workflow with
`AGENT-INTEGRATION.md` and retain the commands and results in target-local receipts.

Run all of these; every one must show the stated result before reporting success:
```bash
python harness/hardware_probe.py --selftest   # -> SELFTEST OK
python harness/model_catalog.py --selftest    # -> SELFTEST OK
python harness/verify.py --selftest           # -> SELFTEST OK
python harness/paired_gate.py --selftest      # -> SELFTEST OK
python harness/dispatch_retry.py --selftest   # -> SELFTEST OK (includes cold-swap tests)
python harness/research_ground.py --selftest  # -> SELFTEST OK
python scripts/autotune_offload.py --selftest # -> SELFTEST OK
curl -s http://localhost:8080/v1/models       # -> JSON, not a connection error
python example_run.py --config config.yaml    # -> dispatch passes, provenance verdict printed, exit 0
```
If the last command exits non-zero because the model is too weak to return valid JSON,
that is a model choice, not a broken install — say so, and suggest a larger quant.
