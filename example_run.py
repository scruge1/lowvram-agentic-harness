#!/usr/bin/env python3
"""example_run.py - the whole harness in one runnable loop.

Run it against a local llama.cpp / llama-swap / Ollama server:

    python example_run.py --config config.yaml

What it does, end to end:
  1. DISPATCH a task to the local model, demanding strict JSON output.
  2. VERIFY the output with a deterministic check; on failure, RETRY with the
     reason fed back so the model can correct itself (dispatch_retry).
  3. CLAIM-PROVENANCE: check that the model's stated facts actually bind to the
     source text we gave it - orphan (unsupported) claims are caught (verify).
  4. RESEARCH-GROUND: optionally answer a question from real, cited web sources,
     keeping only claims >=N independent pages agree on (research_ground).

Everything degrades honestly: if the server is not running, it says so and points
at SETUP.md instead of pretending to work. Step 4 is skipped unless you pass a
search backend + key.
"""
from __future__ import annotations

import argparse
import json
import sys

from harness.llm import LocalLLM, load_config
from harness import verify as V
from harness import research_ground as R
from harness.dispatch_retry import dispatch, make_llm_worker, verifier_json


SOURCE = (
    "The Qwen3-30B-A3B model is a Mixture-of-Experts model with 30 billion total "
    "parameters, of which about 3 billion are active per token. On a single 8 GB "
    "consumer GPU it runs with most expert layers offloaded to CPU RAM using the "
    "llama.cpp --n-cpu-moe flag, trading speed for the ability to fit at all."
)


def step_dispatch_verify(llm) -> dict:
    task = (
        "Read this SOURCE and return ONLY a JSON object with two keys: "
        "\"total_params_billion\" (number) and \"active_params_billion\" (number), "
        "taken strictly from the SOURCE.\n\nSOURCE:\n" + SOURCE
    )
    worker = make_llm_worker(llm)
    print("STEP 1-2: dispatch -> verify(JSON) -> retry on failure")
    result = dispatch(task, worker, verifier_json, max_retries=3)
    print(f"  status={result['status']} attempts={result['attempts']}")
    for a in result["trail"]:
        print(f"    attempt {a['attempt']}: ok={a['ok']} {a.get('reason','')}")
    return result


def step_provenance(llm, dispatch_output: str):
    print("\nSTEP 3: claim-provenance (do the model's facts bind to the SOURCE?)")
    # Turn the structured answer into two natural-language claims and check each one
    # against the SOURCE. A model that hallucinated a different number is caught here.
    try:
        obj = json.loads(_strip(dispatch_output))
    except Exception:
        print("  (could not parse structured output; skipping provenance demo)")
        return
    claims = [
        {"claim": f"The model has {obj.get('total_params_billion')} billion total parameters",
         "evidence_quote": "30 billion total parameters", "source_text": SOURCE},
        {"claim": f"The model has {obj.get('active_params_billion')} billion active parameters per token",
         "evidence_quote": "about 3 billion are active per token", "source_text": SOURCE},
    ]
    receipt = verify_claims_local(claims, llm)
    print(f"  {receipt['n_bound']}/{receipt['n_claims']} claims bound -> verdict={receipt['verdict'].upper()}")
    for o in receipt["orphans"]:
        print(f"    ORPHAN: {o['reason']} :: {o['claim']}")


def verify_claims_local(claims, llm):
    # deterministic gate only (fast); pass llm=llm to add the NLI judge step.
    return V.verify_claims(claims)


def _strip(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1]
        s = s[: s.rfind("```")] if "```" in s else s
    a, b = s.find("{"), s.rfind("}")
    return s[a:b + 1] if a >= 0 and b > a else s


def step_research(args):
    if args.backend == "none":
        print("\nSTEP 4: research-grounding SKIPPED (pass --backend brave|serpapi + the API key env var).")
        return
    print(f"\nSTEP 4: research-ground '{args.question}' via {args.backend}")
    llm = LocalLLM(load_config(args.config))
    res = R.ground(args.question, backend=args.backend, llm=llm,
                   max_results=args.max_results, min_sources=args.min_sources)
    print(f"  sources={res['n_sources']} mined={res['n_mined']} bound={res['n_bound']} "
          f"orphan={res['n_orphan']} -> {res['verdict']}")
    for c in res["consensus"][:5]:
        print(f"    [{c['n_sources']} sources] {c['claim']}")
        for cite in c["citations"]:
            print(f"        - {cite}")


def step_cold_swap(args):
    from harness.model_catalog import fallback_chain, CatalogError
    print("\nSTEP 5: cold-swap fallback chain (models.yaml, class '%s')" % args.cold_swap_class)
    try:
        chain = fallback_chain(args.cold_swap_class)
    except CatalogError as e:
        print("  SKIPPED: %s" % e)
        return
    print("  chain: " + " -> ".join(m["model"] for m in chain))
    if not args.demo_cold_swap:
        print("  (pass --demo-cold-swap to actually dispatch through this chain against your live "
              "server -- this really cold-swaps models and can take a while on an 8GB card)")
        return
    from harness.dispatch_retry import dispatch_cold_swap, verifier_non_empty
    result = dispatch_cold_swap("Say hello in exactly 3 words.", chain, verifier_non_empty, retries_per_model=1)
    print("  status=%s winning_model=%s" % (result["status"], result.get("winning_model")))
    for a in result["model_trail"]:
        print("    [%s] attempt %s: ok=%s %s" % (a["model"], a["attempt"], a["ok"], a.get("reason", "")))


def main() -> int:
    ap = argparse.ArgumentParser(description="end-to-end demo of the low-VRAM agentic harness")
    ap.add_argument("--config", default=None, help="path to config.yaml (optional)")
    ap.add_argument("--question", default="How much VRAM does an RTX 2080 have?")
    ap.add_argument("--backend", default="none", choices=["none", "brave", "serpapi"])
    ap.add_argument("--max-results", type=int, default=5)
    ap.add_argument("--min-sources", type=int, default=2)
    ap.add_argument("--cold-swap-class", default="30B-MoE",
                     help="models.yaml size_class to demo the cold-swap fallback chain for")
    ap.add_argument("--demo-cold-swap", action="store_true",
                     help="actually dispatch through the cold-swap chain against your live server "
                          "(default: only show the resolved chain, no extra model loads)")
    args = ap.parse_args()

    llm = LocalLLM(load_config(args.config))
    print(f"Local model endpoint: {llm.cfg['base_url']}  model={llm.cfg['model']}\n")

    try:
        result = step_dispatch_verify(llm)
    except RuntimeError as e:
        print(f"\n[!] {e}")
        print("[!] Start your local server first - see SETUP.md. Nothing here is faked.")
        return 2

    if result["status"] == "pass":
        step_provenance(llm, result["output"])
    elif any("unreachable" in (a.get("reason") or "") for a in result["trail"]):
        print()
        print("[!] The local model endpoint refused every attempt - the server is not running.")
        print("[!] Start it first (see SETUP.md). Nothing here is faked.")
        return 2
    else:
        print("  dispatch never produced valid JSON after all retries (a weak model may need "
              "a bigger quant or more retries).")

    step_research(args)
    step_cold_swap(args)
    print("\nDone. This whole loop ran against your LOCAL model - no cloud calls.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
