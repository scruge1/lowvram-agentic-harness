# Dynamic model and GPU discovery (read-only)

**Status:** portable, opt-in discovery candidate. **No automatic model selection,
load/unload, GPU reservation, eviction, GPUQ coordination or agent authority.**

The full private Pi selector can discover installed models and configured routes,
but it also relies on a specific rig's existing worker owner, model manifests,
Ollama/Pi sources and GPU custody. Copying that installer into another person's
agent home would confuse an asset being present with one that is safe to launch.

The new `harness/model_inventory.py` is the reusable lower layer. It accepts
only explicitly supplied model directories, inspects file names and filesystem
metadata without reading multi-gigabyte model bytes, identifies complete GGUF
shard sets, and produces a bounded, descriptive catalogue. It also queries
all visible NVIDIA GPU cards using a fixed read-only `nvidia-smi` command.

## Usage

From the repository root:

```bash
python -m harness.model_inventory --root /absolute/path/to/models --no-gpu-probe
python -m harness.model_inventory --root /absolute/path/to/models --limit 100
```

Each additional `--root` is another explicit location. Unknown roots refuse
rather than silently search the whole computer. A root must already exist and
not itself be a symlink. The response deliberately uses root indices and
relative asset names, not machine-specific absolute paths or credentials.

`assets[].state` distinguishes `installed_unqualified` from
`incomplete_shards`. **Neither permits execution.** The `source_stat_sha256`
field is a SHA-256 digest of path/stat metadata, **not a digest of GGUF bytes**.
A selected model must be verified by an independent, correct model/backend
loader before any attempt to run it. Discovered file size is not a GPU memory
budget: weights, per-layer placement, KV cache, parallel slots, runtime
buffers, other active users and cross-GPU transport matter.

`gpu.devices[]` exposes observed index, UUID, name and total/used/free MiB
only when the entire output is valid. It does not establish ownership, current
task association, GPUQ lease, remaining context capacity or availability for
another agent. If the tool is missing, counters are malformed, identities
duplicate or data is inconsistent, the GPU inventory is `unavailable`, not
an estimated free card. No process is stopped or started.

## Guardrails

- Python 3.9+ standard library only; no daemon, server, model download,
  credentials, filesystem mutation or GPU load.
- File/time/asset/depth/root limits refuse incomplete scans rather than
  treating partial discovery as a complete catalogue.
- No directory links are traversed; file symlinks and model projectors are
  excluded. Complete GGUF shard grouping is required.
- The CLI does not infer model task capability, model architecture or
  context limits from a filename. Official GGUF metadata inspection,
  configured provider identity and live task quality belong to later stages.
- The public installer does not activate this scanner automatically. Owners
  explicitly choose the directories they intend to inventory.
- No global model transaction or context switch is inferred from reported
  free VRAM. Always use the existing owner and service lifecycle guards.

## Verification

```bash
python -m unittest discover -s tests -p test_model_inventory.py -v
```

The tests use synthetic tiny GGUF files and fake GPU CLI output. They cover
missing shards, misleading filenames, duplicate canonical roots, symlink escape
exclusion, scan bounds, source-stat changes, stale or malformed GPU counters,
read-only invocation and no-probe opt-out. Windows without symlink privileges
skips only the symlink fixture; Linux tests it.

**Still needed before full private/public parity:** owner-pinned Pi model registry
and Ollama/roster/preset adapters; exact GGUF metadata verification; live
backend-specific KV/context/parallel VRAM traces; lease-safe loading and model
release; paused-worker context checkpoint; and independent coding-task
qualification. Nothing in this read-only inventory satisfies those gates.
