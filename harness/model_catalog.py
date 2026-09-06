#!/usr/bin/env python3
"""model_catalog.py -- pick a model by SIZE CLASS + RANK, never a hardcoded tag.

Generalized from a proven internal pattern: never scatter literal model names through
calling code, because model names churn (a better quant, a fresher release, a new
lab's model) but call sites shouldn't. One YAML file is the source of truth; every
caller asks for a *class* ("what's my best 30B-class MoE right now?") and gets back
whatever is currently ranked #1 in that class.

This is also what makes COLD-SWAP RETRY (see dispatch_retry.dispatch_cold_swap)
possible without hardcoding a fallback chain in code: rank 1, 2, 3... in a class
already IS the fallback order.

models.yaml shape:

    size_classes:
      30B-MoE:
        - rank: 1
          model: "qwen3:30b"          # what you pass as `model` to the /v1 endpoint
          backend: ollama              # informational -- doesn't change how you call it
          vram_gb: 6.4                 # real measured footprint w/ --n-cpu-moe offload, not the full weight size
          note: "Qwen3-30B-A3B-Instruct-2507. ollama pull qwen3:30b, or llama.cpp --n-cpu-moe"
        - rank: 2
          model: "hf.co/unsloth/Nemotron-3-Nano-30B-A3B-GGUF:Q4_K_M"
          backend: ollama
          vram_gb: 6.5
          note: "different training lineage (NVIDIA) -- a genuine second opinion, not a reskin"

Every entry needs: rank, model. Everything else is informational (surfaced to you,
never parsed for control flow) so the file stays honest about what's actually known
vs guessed.
"""
from __future__ import annotations

from pathlib import Path

try:
    from .llm import _read_yaml
except ImportError:  # run as a script
    from llm import _read_yaml

DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent.parent / "models.yaml"


class CatalogError(Exception):
    pass


def load_catalog(path=None) -> dict:
    """Load models.yaml. Returns {} if the file doesn't exist yet -- resolve() then
    raises a clear CatalogError rather than a confusing KeyError deep in a dict."""
    p = Path(path) if path else DEFAULT_CATALOG_PATH
    if not p.exists():
        return {}
    data = _read_yaml(p)
    return data or {}


def classes(catalog: dict | None = None) -> list[str]:
    catalog = catalog if catalog is not None else load_catalog()
    return sorted((catalog.get("size_classes") or {}).keys())


def resolve(size_class: str, rank: int = 1, catalog: dict | None = None) -> dict:
    """Return the catalog entry for size_class at the given rank (1 = best).
    Raises CatalogError (not KeyError) with a message that tells you what to fix --
    a silent wrong-model fallback is worse than a loud one."""
    catalog = catalog if catalog is not None else load_catalog()
    size_classes = catalog.get("size_classes") or {}
    if not size_classes:
        raise CatalogError(
            "no models.yaml found (or it's empty). Copy models.example.yaml to "
            "models.yaml and fill in what you've actually pulled. See SETUP.md.")
    if size_class not in size_classes:
        raise CatalogError(
            f"size_class {size_class!r} not in models.yaml. Known classes: "
            f"{sorted(size_classes.keys())}")
    members = sorted(size_classes[size_class], key=lambda m: m.get("rank", 999))
    for m in members:
        if m.get("rank") == rank:
            return m
    raise CatalogError(
        f"no rank={rank} entry in class {size_class!r}. Available ranks: "
        f"{[m.get('rank') for m in members]}")


def fallback_chain(size_class: str, catalog: dict | None = None) -> list[dict]:
    """All entries in a class, best-first -- the cold-swap order for
    dispatch_retry.dispatch_cold_swap."""
    catalog = catalog if catalog is not None else load_catalog()
    size_classes = catalog.get("size_classes") or {}
    if size_class not in size_classes:
        raise CatalogError(f"size_class {size_class!r} not in models.yaml.")
    return sorted(size_classes[size_class], key=lambda m: m.get("rank", 999))


def _selftest() -> int:
    demo = {
        "size_classes": {
            "30B-MoE": [
                {"rank": 1, "model": "qwen3:30b", "vram_gb": 6.4},
                {"rank": 2, "model": "hf.co/unsloth/Nemotron-3-Nano-30B-A3B-GGUF:Q4_K_M", "vram_gb": 6.5},
            ],
            "8B": [{"rank": 1, "model": "qwen3:8b", "vram_gb": 5.2}],
        }
    }
    fails = 0

    def chk(name, cond):
        nonlocal fails
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            fails += 1

    chk("empty catalog raises CatalogError, not KeyError",
        _raises(lambda: resolve("30B-MoE", catalog={}), CatalogError))
    chk("unknown class raises CatalogError",
        _raises(lambda: resolve("999B", catalog=demo), CatalogError))
    r1 = resolve("30B-MoE", rank=1, catalog=demo)
    chk("rank=1 resolves to qwen3:30b", r1["model"] == "qwen3:30b")
    r2 = resolve("30B-MoE", rank=2, catalog=demo)
    chk("rank=2 resolves to the second-substrate nemotron", "Nemotron" in r2["model"])
    chk("unknown rank raises CatalogError",
        _raises(lambda: resolve("30B-MoE", rank=9, catalog=demo), CatalogError))
    chain = fallback_chain("30B-MoE", catalog=demo)
    chk("fallback_chain is best-first, full length",
        len(chain) == 2 and chain[0]["model"] == "qwen3:30b")
    chk("classes() lists both classes", set(classes(demo)) == {"30B-MoE", "8B"})

    print("SELFTEST OK" if fails == 0 else f"SELFTEST FAILED ({fails})")
    return 1 if fails else 0


def _raises(fn, exc_type) -> bool:
    try:
        fn()
        return False
    except exc_type:
        return True
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    print(__doc__)
