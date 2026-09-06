# SETUP — step by step

Goal: a local OpenAI-compatible server running a 30B-A3B MoE model on your 8 GB GPU,
with the harness talking to it. Roughly 30–60 minutes, most of it model download.

Two paths for step 1:
- **A (easiest): prebuilt llama.cpp binaries** — no compiler needed.
- **B: build llama.cpp with CUDA yourself** — a bit faster, needs a toolchain.

If an AI coding agent will perform the installation or refactor this package into an
existing system, start with [AGENT-INTEGRATION.md](AGENT-INTEGRATION.md). It creates a
target-bound, unresolved SSOT for the setup. Do not ask an agent to follow this page
and infer completion from copied files or package tests. **FAQ.md** remains the
diagnostic reference used inside that controlled setup workflow.

---

## 0. Prerequisites

- NVIDIA GPU with 8+ GB VRAM, recent driver. Check:
  ```bash
  nvidia-smi
  ```
  You should see your card and a CUDA version (top right). Any CUDA 12.x driver is fine.
- Python 3.9+ (`python --version`).
- ~25 GB free disk for one model file.
- 32 GB system RAM strongly recommended (24 GB minimum).

---

## 1A. Get llama.cpp (prebuilt — easiest)

1. Go to the llama.cpp releases page: https://github.com/ggml-org/llama.cpp/releases
2. Download the latest **CUDA** build for your OS (e.g. `llama-*-bin-win-cuda-x64.zip`
   on Windows, or the Linux CUDA tarball).
3. Unzip it. You now have `llama-server` (and `llama-cli`). Put the folder on your PATH
   or just run it by full path.
4. Verify:
   ```bash
   ./llama-server --version
   ```

## 1B. Build llama.cpp with CUDA (alternative)

Needs `git`, `cmake`, and the CUDA toolkit (`nvcc`).

```bash
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j
# binaries land in build/bin/ (Linux) or build/bin/Release/ (Windows)
```

No NVIDIA GPU? Build CPU-only (drop `-DGGML_CUDA=ON`) — the harness is identical, just
slower. AMD GPU? use the Vulkan build (`-DGGML_VULKAN=ON`).

---

## 2. Check your hardware BEFORE downloading anything

You need to know your actual system RAM and CPU before picking a model+quant — the
`--n-cpu-moe` trick in step 4 offloads most of a 30B-MoE model's weights into system
RAM, not just VRAM, so RAM is the second real constraint here, not an afterthought.

```bash
# RAM
free -h                        # Linux
wmic memorychip get capacity   # Windows (sum the values, they're in bytes)
# or just: Task Manager -> Performance -> Memory (Windows), About This Mac (macOS)

# CPU (offload speed depends on memory bandwidth, not core count — more cores
# doesn't make --n-cpu-moe faster the way more VRAM would)
lscpu | grep "Model name"      # Linux
wmic cpu get name               # Windows
```

Rule of thumb for a ~17-18 GB Q4-class 30B-A3B GGUF: you want **at least 24 GB total
system RAM** free for the OS-cache-resident model plus your normal workload headroom.
16 GB RAM will likely thrash (the model gets evicted and reloaded from disk every
request — usable but slow). Below 16 GB, don't try a 30B model — use the `reasoner-small`
class in `models.example.yaml` (an 8B model, ~5 GB VRAM, minimal RAM) instead.

## 3. Download a model (GGUF)

Start with **Qwen3-30B-A3B-Instruct-2507** at **Q4_K_XL** — this exact model+quant is
the proven reference point for this whole repo: measured at ~19 tok/s using ~6.4 GB of
an 8 GB card's VRAM (file is ~17 GB on disk, so budget ~17-18 GB of that free RAM from
step 2 for the CPU-offloaded experts). GGUF files live on Hugging Face; check the
repo's "Files" tab for the exact filename (unsloth's dynamic quants are usually named
`UD-Q4_K_XL`, not plain `Q4_K_XL` — do not guess it, copy it).

Using `huggingface-cli` (recommended — resumable):
```bash
pip install -U "huggingface_hub[cli]"
huggingface-cli download unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF     --include "*UD-Q4_K_XL*" --local-dir ./models
```

Or the plain-`ollama` path (simpler, no manual GGUF handling, and this is what
`models.example.yaml` assumes by default):
```bash
ollama pull qwen3:30b
```

**Low on RAM (under ~24 GB) or tight on VRAM?** Drop to a smaller quant (`Q3_K_M`
class, ~14 GB) — lower quality, smaller RAM+VRAM footprint. **Want speed over size
instead, or your RAM genuinely can't fit a 30B model?** Grab a dense 7-8B model (e.g.
`Qwen2.5-7B-Instruct-Q4_K_M.gguf`, fully on GPU, 30-60+ tok/s, ~6 GB RAM/VRAM total) and
skip `--n-cpu-moe` entirely below — no MoE, no offload trick, no RAM dependency.

## 4. Run the server (the proven 8 GB-card command)

**Recommended: let the repo find YOUR number instead of guessing.**
`scripts/autotune_offload.py` probes your real VRAM/RAM, launches the real server at a
sweep of `--n-cpu-moe` settings, measures actual tok/s, and keeps the fastest one that
did not OOM:
```bash
python scripts/autotune_offload.py plan
python scripts/autotune_offload.py run     --model models/Qwen3-30B-A3B-Instruct-2507-UD-Q4_K_XL.gguf     --llama-server /path/to/llama-server     --write qwen3-30b-a3b-local
```
This can take several minutes (it launches and tears down the server multiple times).
It prints the winning `--n-cpu-moe` value and writes it into `models.yaml` under a
`local-tuned` class. Use that number below instead of `34` if it differs.

If you would rather skip autotuning and just try the known-working starting point:

This is the exact recipe measured on an 8 GB RTX 3070 — **you're on an RTX 2080, also
8 GB VRAM, but possibly different system RAM.** Same flags should work; re-measure tok/s
and adjust `--n-cpu-moe` for your actual RAM from step 2 (more offloaded experts if RAM
is tight, fewer if you have headroom to spare):

```bash
llama-server   -m models/Qwen3-30B-A3B-Instruct-2507-UD-Q4_K_XL.gguf   -ngl 99 \                  # put every non-offloaded layer on the GPU
  --n-cpu-moe 34 \           # offload 34 expert-layer cores to CPU RAM -- THIS is the 8 GB trick
  --flash-attn on \          # lower VRAM + faster attention
  --cache-type-k q8_0 \      # quantized KV cache -- more context fits in the same VRAM
  --cache-type-v q8_0   -c 8192   -b 2048 \                  # batch size
  --host 0.0.0.0 \           # 0.0.0.0 so other machines on your LAN can reach it; 127.0.0.1 for local-only
  --port 8080
```

What the flags do:
- `-ngl 99` — put as many layers as possible on the GPU; with most MoE experts pulled
  out by `--n-cpu-moe`, what's left is attention/shared layers = a few GB.
- `--n-cpu-moe 34` — offload 34 of the MoE expert-layer cores to system RAM, keep the
  rest on GPU. This is the tunable version of the old blanket `--cpu-moe` flag: **higher
  N = more offloaded = less VRAM but needs more RAM and is slower; lower N = faster but
  needs more VRAM.** 34 was the number that fit an 8 GB 3070 at ~19 tok/s with ~6.4 GB
  VRAM used and ~17-18 GB resident in system RAM. Start there; if you OOM on VRAM, raise
  it; if `free -h`/Task Manager shows you're swapping to disk, your RAM (not VRAM) is
  the bottleneck — drop to a smaller quant instead of fighting this flag.
- `--flash-attn on` + `--cache-type-k/v q8_0` — quantized KV cache, meaningfully more
  context for the same VRAM. Not optional at this VRAM tier — leave them on.
- `-c 8192` — context window; the KV cache scales with this. Drop to `-c 4096` first if
  you OOM before touching `--n-cpu-moe`.

**Only 8 GB VRAM and running something else GPU-heavy already?** Kill it first — a
vision model, a second llama-server, a game, anything holding VRAM. One 30B-class MoE
plus literally anything else does not fit in 8 GB; there is no flag that changes that.

Watch the startup log: it prints how many layers/experts went to GPU vs CPU and the
VRAM used. When you see `HTTP server listening on ...:8080` it is ready.

Smoke-test the server directly (no harness yet):
```bash
curl http://localhost:8080/v1/chat/completions   -H "Content-Type: application/json"   -d '{"model":"local","messages":[{"role":"user","content":"say hi in 3 words"}]}'
```
You should get a JSON response with the model's reply.

## 5. Point the harness at the server

```bash
cd lowvram-agentic-harness
cp config.example.yaml config.yaml
# edit config.yaml only if your base_url differs from http://localhost:8080/v1
cp models.example.yaml models.yaml
# edit models.yaml to match what you actually pulled -- this is what powers the
# cold-swap fallback chain (step 4's autotune result gets written here too, under
# the "local-tuned" class, if you used --write)
pip install -r requirements.txt          # optional: PyYAML + requests
```

Or skip the config file entirely and use env vars (models.yaml is still needed for
cold-swap, but everything else works without it):
```bash
export HARNESS_BASE_URL=http://localhost:8080/v1
export HARNESS_MODEL=local-model
```

---

## 6. Verify end to end

```bash
# offline unit checks (no server needed) -- all seven print SELFTEST OK
python harness/verify.py --selftest
python harness/paired_gate.py --selftest
python harness/dispatch_retry.py --selftest
python harness/research_ground.py --selftest
python harness/model_catalog.py --selftest
python harness/hardware_probe.py --selftest
python scripts/autotune_offload.py --selftest

# live loop against your running server -- 5 steps, the 5th shows your cold-swap chain
python example_run.py --config config.yaml
```

Expected: it prints the endpoint, dispatches a task, shows the retry attempts, reports
the JSON it accepted, runs the claim-provenance check, and (step 5) shows the model
fallback chain from `models.yaml`. If the server is down it says so plainly and exits --
it never fakes a result.

To add live web grounding (needs a free search key):
```bash
export BRAVE_API_KEY=your_key         # from https://brave.com/search/api/
python example_run.py --config config.yaml --backend brave     --question "How much VRAM does an RTX 2080 have?"
```

To actually exercise the cold-swap chain against your live server (not just see it):
```bash
python example_run.py --config config.yaml --demo-cold-swap
```

---

## 7. (Optional) run the server on boot / in the background

- **Linux:** wrap the step-3 command in a `systemd` user service, or just
  `nohup llama-server ... > server.log 2>&1 &`.
- **Windows:** run it in its own terminal, or use NSSM to install it as a service.

That is the whole install. Troubleshooting for every common failure is in **FAQ.md**.
