#!/usr/bin/env python3
"""dispatch_retry.py - dispatch a task to a worker, VERIFY the output, retry on
verified failure with the failure reason fed back in.

This is the spine that turns a one-shot model call into an agentic loop. A weak
local model often gets it wrong on the first try; the trick that makes it usable is
not a bigger model, it is a CHECK plus a RETRY that tells the model exactly what was
wrong so the next attempt can fix it:

    for attempt in range(max_retries + 1):
        output = worker(task, feedback)      # feedback carries prior failures
        ok, reason = verifier(output)        # a DIFFERENT function grades it
        if ok: return success
        feedback += reason                   # the model learns what to fix

Two design rules carried over from the proven internal pipeline:
  * The verifier is a DIFFERENT substrate from the worker (a deterministic check, a
    test runner, or a separate judge) - never the worker grading itself. That is the
    whole reason a weak worker can be trusted here.
  * Failure must be LOUD and fed back, never swallowed. A retry with no feedback just
    rolls the dice again; a retry WITH the reason is a correction.

`worker` : callable(task: str, feedback: str) -> str
`verifier`: callable(output: str) -> (ok: bool, reason: str)
Both are pluggable. Defaults wire the local model as the worker and a non-empty check
as the verifier, but the point is you pass your own - e.g. verify.verify_claims for
provenance, or a subprocess that runs your test suite.
"""

from __future__ import annotations

import argparse
import json
import sys

try:
    from .llm import LocalLLM, load_config
except ImportError:  # run as a script, not a package
    from llm import LocalLLM, load_config


def make_llm_worker(llm=None, system=None):
    """A worker backed by the local model. Prior failure reasons are appended to the
    prompt so each retry is a correction, not a re-roll."""
    llm = llm or LocalLLM()

    def worker(task: str, feedback: str) -> str:
        prompt = task
        if feedback:
            prompt += (
                "\n\nYour previous attempt was REJECTED for this reason - fix it "
                f"and try again:\n{feedback}"
            )
        return llm.ask(prompt, system=system)

    return worker


# --- a few ready-made verifiers (all callable(output) -> (ok, reason)) ------------
def verifier_non_empty(output: str):
    return (
        bool(output and output.strip()),
        "" if output and output.strip() else "empty output",
    )


def verifier_json(output: str):
    """Output must parse as JSON (a common structured-output contract)."""
    try:
        json.loads(_strip_fences(output))
        return True, ""
    except Exception as e:  # noqa: BLE001
        return (
            False,
            f"output is not valid JSON ({e}). Return ONLY a JSON value, no prose or code fences.",
        )


def verifier_contains(*required):
    def v(output: str):
        low = (output or "").lower()
        missing = [r for r in required if r.lower() not in low]
        return (
            not missing,
            "" if not missing else f"output is missing required content: {missing}",
        )

    return v


def _strip_fences(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[-1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: s.rfind("```")]
    return s.strip()


def dispatch(task, worker, verifier, max_retries: int = 3) -> dict:
    """Run the dispatch->verify->retry loop. Returns a receipt with status, the number
    of attempts, the accepted output (if any), and the full attempt trail."""
    feedback = ""
    attempts = []
    for i in range(max_retries + 1):
        try:
            output = worker(task, feedback)
            worker_err = None
        except Exception as e:  # noqa: BLE001
            output, worker_err = "", str(e)
        if worker_err:
            attempts.append(
                {"attempt": i, "ok": False, "reason": f"worker error: {worker_err}"}
            )
            feedback = f"worker error: {worker_err}"
            continue
        ok, reason = verifier(output)
        attempts.append(
            {
                "attempt": i,
                "ok": ok,
                "reason": reason,
                "output_preview": (output or "")[:200],
            }
        )
        if ok:
            return {
                "status": "pass",
                "attempts": i + 1,
                "output": output,
                "trail": attempts,
            }
        feedback = reason
    return {
        "status": "failed",
        "attempts": max_retries + 1,
        "output": None,
        "reason": attempts[-1]["reason"] if attempts else "no attempts",
        "trail": attempts,
    }


def dispatch_cold_swap(
    task, model_configs, verifier, retries_per_model: int = 2, make_worker=None
) -> dict:
    """Like dispatch(), but escalates across DIFFERENT MODELS on repeated verified
    failure instead of only retrying the same one -- a cold-swap fallback chain.

    Why this matters on a single 8GB card: you can't hold two 30B-class models in
    VRAM at once, so "try a different model" always costs a real load-time swap
    (seconds to a minute, depending on the model and whether the OS page cache is
    warm). That cost is worth paying when a model is STRUCTURALLY wrong for a task
    (not just unlucky) -- a different training lineage sometimes succeeds where the
    first one keeps making the same mistake no matter how the feedback is worded.

    `model_configs`: list of dicts, best-first, each with at least a "model" key
    (e.g. from model_catalog.fallback_chain("30B-MoE")). Each is merged onto the
    current LocalLLM config so `base_url`/`api_key` are inherited from the caller's
    normal config -- only `model` (and anything else you put in the dict) overrides.
    `make_worker(llm)`: factory returning a worker(task, feedback) callable for that
    LocalLLM. Defaults to make_llm_worker.

    Returns a receipt shaped like dispatch()'s, plus "model_trail": which model
    handled each attempt, so you can see exactly when (and whether) a swap happened.
    """
    try:
        from .llm import LocalLLM, load_config as _load_config
    except (
        ImportError
    ):  # Support the documented `python harness/dispatch_retry.py` path.
        from llm import LocalLLM, load_config as _load_config
    make_worker = make_worker or make_llm_worker
    base_cfg = _load_config()
    model_trail = []
    for m_idx, model_cfg in enumerate(model_configs):
        cfg = dict(base_cfg)
        cfg.update(model_cfg)
        llm = LocalLLM(cfg)
        worker = make_worker(llm)
        result = dispatch(task, worker, verifier, max_retries=retries_per_model)
        model_name = model_cfg.get("model", "?")
        for a in result["trail"]:
            model_trail.append(
                {
                    **a,
                    "model": model_name,
                    "model_rank": model_cfg.get("rank", m_idx + 1),
                }
            )
        if result["status"] == "pass":
            return {**result, "model_trail": model_trail, "winning_model": model_name}
    return {
        "status": "failed",
        "attempts": len(model_trail),
        "output": None,
        "reason": f"all {len(model_configs)} model(s) in the fallback chain failed verification",
        "trail": [t for t in model_trail],
        "model_trail": model_trail,
        "winning_model": None,
    }


def _selftest() -> int:
    fails = 0

    def chk(name, cond):
        nonlocal fails
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            fails += 1

    # a worker that fails twice, then (seeing feedback) succeeds on the 3rd attempt
    state = {"n": 0}

    def flaky_worker(task, feedback):
        state["n"] += 1
        return "DONE" if state["n"] >= 3 else "not yet"

    r = dispatch("do the thing", flaky_worker, verifier_contains("done"), max_retries=3)
    chk("retries until pass", r["status"] == "pass" and r["attempts"] == 3)
    chk("trail records each attempt", len(r["trail"]) == 3)

    # a worker that never satisfies the verifier -> failed after max_retries+1
    r2 = dispatch(
        "x", lambda t, f: "nope", verifier_contains("impossible"), max_retries=2
    )
    chk("gives up after max_retries", r2["status"] == "failed" and r2["attempts"] == 3)

    # feedback is actually threaded to the worker
    seen = {"fb": []}

    def fb_worker(task, feedback):
        seen["fb"].append(feedback)
        return "bad" if len(seen["fb"]) < 2 else "good"

    dispatch("t", fb_worker, verifier_contains("good"), max_retries=3)
    chk("first feedback empty, later non-empty", seen["fb"][0] == "" and seen["fb"][1])

    # verifiers
    chk("json verifier accepts fenced json", verifier_json('```json\n{"a":1}\n```')[0])
    chk("json verifier rejects prose", not verifier_json("hello")[0])
    chk("non-empty rejects blank", not verifier_non_empty("   ")[0])

    # worker exception is caught, fed back, not raised
    r3 = dispatch(
        "t",
        lambda t, f: (_ for _ in ()).throw(RuntimeError("boom")),
        verifier_non_empty,
        max_retries=1,
    )
    chk(
        "worker error handled as failure",
        r3["status"] == "failed" and "boom" in r3["trail"][0]["reason"],
    )

    # cold-swap: model A always fails verification, model B always passes -> escalates
    calls = {"model-A": 0, "model-B": 0}

    def fake_make_worker(llm):
        name = llm.cfg["model"]

        def worker(task, feedback):
            calls[name] += 1
            return "wrong" if name == "model-A" else "RIGHT"

        return worker

    r4 = dispatch_cold_swap(
        "task",
        [{"model": "model-A", "rank": 1}, {"model": "model-B", "rank": 2}],
        verifier_contains("right"),
        retries_per_model=1,
        make_worker=fake_make_worker,
    )
    chk(
        "cold-swap escalates to model-B after model-A exhausts retries",
        r4["status"] == "pass" and r4["winning_model"] == "model-B",
    )
    chk(
        "cold-swap tried model-A first (retries_per_model+1 attempts)",
        calls["model-A"] == 2,
    )
    chk(
        "cold-swap model_trail records both models",
        {t["model"] for t in r4["model_trail"]} == {"model-A", "model-B"},
    )

    r5 = dispatch_cold_swap(
        "task",
        [{"model": "model-A", "rank": 1}],
        verifier_contains("right"),
        retries_per_model=1,
        make_worker=fake_make_worker,
    )
    chk(
        "cold-swap reports failed when every model in the chain fails",
        r5["status"] == "failed",
    )

    print("SELFTEST OK" if fails == 0 else f"SELFTEST FAILED ({fails})")
    return 0 if fails == 0 else 1


def cmd_run(args) -> int:
    """Dispatch a single prompt to the local model with a non-empty verifier (a live
    smoke test of the loop against your running server)."""
    llm = LocalLLM(load_config(args.config))
    worker = make_llm_worker(llm)
    verifier = verifier_json if args.expect_json else verifier_non_empty
    r = dispatch(args.task, worker, verifier, max_retries=args.max_retries)
    print(json.dumps({k: v for k, v in r.items() if k != "output"}, indent=2))
    if r["status"] == "pass":
        print("\n--- accepted output ---\n" + r["output"])
    return 0 if r["status"] == "pass" else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="dispatch_retry - dispatch/verify/retry loop"
    )
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    run = sub.add_parser("run", help="dispatch one prompt to the local model")
    run.add_argument("--task", required=True)
    run.add_argument("--config", default=None)
    run.add_argument("--max-retries", type=int, default=3)
    run.add_argument("--expect-json", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if args.cmd == "run":
        return cmd_run(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
