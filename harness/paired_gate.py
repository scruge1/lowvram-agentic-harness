#!/usr/bin/env python3
"""paired_gate.py - the KEEP/REVERT paired-control measurement gate.

When you change a harness component (a prompt, a validator, a detector), how do you
know the change actually HELPED and did not just make it say "yes" more? You measure
it against a LABELED test set with BOTH positives (should pass) and negatives (should
be rejected), and you keep the change only if:

    recall ROSE   AND   false-positive-rate did NOT rise.

That AND is the whole point. Recall alone is gameable - a detector that confirms
EVERYTHING has perfect recall and is useless. The matched negatives are the trap that
catches the rubber-stamp: if false-positives rose too, the "improvement" was just
looser judgement, and the gate REVERTS.

Two failure shapes it separates (never conflate them):
  * DEAD CHANNEL   - every prediction errored/parse-failed. No signal. Not a verdict.
  * DEGENERATE     - the channel is alive but returns one constant answer for every
                     input. A smell to explain, reported, never silently "passed".

Honesty floor (ported intent): a small test set cannot CERTIFY a keep - it can only
REVERT a bad change. Below MIN_GATE_N the tool is a DIAGNOSTIC; it reports PROMISING
but refuses to certify. Point estimates at small n lie, so recall is reported with a
Wilson score confidence interval and the KEEP test uses the CI lower bound, not the point.

Generalized from a proven internal corpus-grounded critic self-improvement loop; the
measurement math (recall / false-confirm / Wilson CI / keep-iff-both) is unchanged.
Domain-specific corpus formats and prompts were removed - here a "detector" is any
callable `text -> bool` and a "corpus" is a list of labeled examples.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

MIN_GATE_N = 30   # below this, DIAGNOSTIC only: can REVERT, cannot CERTIFY a KEEP.


def wilson_ci(hits: int, n: int, z: float = 1.96):
    """Two-sided Wilson score interval. A point estimate at small n lies; report a CI."""
    if not n:
        return (None, None)
    p = hits / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return round((centre - half) / d, 3), round((centre + half) / d, 3)


def evaluate(detector, corpus) -> dict:
    """Run a `detector(text) -> bool` over a labeled corpus and measure it.

    corpus: list of {"id": str, "text": str, "expected": bool}
            expected=True  -> a positive the detector SHOULD confirm (recall)
            expected=False -> a negative the detector SHOULD reject   (false-positive)

    Returns a measurement dict (feed two of these to `gate`)."""
    pos_hits = pos_n = fp = neg_n = errors = 0
    predictions = []
    for ex in corpus:
        exp = bool(ex.get("expected"))
        try:
            pred = bool(detector(ex["text"]))
            err = False
        except Exception as e:  # noqa: BLE001
            pred, err = False, True
            errors += 1
            predictions.append(None)
            print(f"  [error] {ex.get('id')}: {e}", file=sys.stderr)
        if not err:
            predictions.append(pred)
        if exp:
            pos_n += 1
            pos_hits += (not err and pred)
        else:
            neg_n += 1
            fp += (not err and pred)
    rlo, rhi = wilson_ci(pos_hits, pos_n)
    flo, fhi = wilson_ci(fp, neg_n)
    live = [p for p in predictions if p is not None]
    return {
        "n": len(corpus),
        "recall": round(pos_hits / pos_n, 4) if pos_n else None, "recall_ci95": [rlo, rhi],
        "pos_hits": pos_hits, "pos_n": pos_n,
        "false_positive_rate": round(fp / neg_n, 4) if neg_n else None, "fp_ci95": [flo, fhi],
        "fp": fp, "neg_n": neg_n,
        "errors": errors,
        # DEAD CHANNEL: every prediction failed -> no signal, not a result.
        "dead_channel": len(corpus) > 0 and errors == len(corpus),
        # DEGENERATE: alive but one constant answer for every input -> explain, don't assert away.
        "degenerate": len(live) > 1 and len(set(live)) == 1,
    }


def gate(before: dict, after: dict, force_underpowered: bool = False) -> int:
    """KEEP the change iff recall rose (CI-lower of after > point recall of before)
    AND false-positive-rate did not rise. Returns an exit code:
        0 = KEEP (certified)   1 = REVERT / not proven
        3 = PROMISING but underpowered (grow the corpus, then re-gate)
        2 = refused (dead channel / missing data)."""
    for tag, m in (("before", before), ("after", after)):
        if m.get("dead_channel"):
            print(f"REFUSED: {tag} is a DEAD CHANNEL (every prediction errored). Fix the detector/endpoint first.")
            return 2
    if before.get("recall") is None or after.get("recall") is None:
        print("REFUSED: both runs need positives to measure recall.")
        return 2
    n = min(after.get("pos_n") or 0, before.get("pos_n") or 0)
    rb = before.get("recall") or 0
    ra = after.get("recall") or 0
    ra_lo = (after.get("recall_ci95") or [0, 0])[0] or 0
    fb = before.get("false_positive_rate") or 0
    fa = after.get("false_positive_rate") or 0
    confident_up = ra_lo > rb
    fp_ok = fa <= fb + 1e-9
    regressed = ra < rb and not confident_up
    print(f"PAIRED GATE (n={n}, MIN_GATE_N={MIN_GATE_N}):")
    print(f"  recall            {rb:.3f} -> {ra:.3f} (CI lower {ra_lo:.3f})  [{'CONFIDENT UP' if confident_up else 'not confidently up'}]")
    print(f"  false-positive    {fb:.3f} -> {fa:.3f}  [{'ok' if fp_ok else 'ROSE - rubber-stamp risk'}]")
    if after.get("degenerate"):
        print("  WARNING: after run is DEGENERATE (one constant answer for every input) - explain before trusting.")
    powered = n >= MIN_GATE_N
    if not powered and not force_underpowered:
        print(f"  POWER: n={n} < {MIN_GATE_N} -> UNDERPOWERED: cannot CERTIFY a KEEP. Diagnostic run.")
        if confident_up and fp_ok:
            print(f"  VERDICT: PROMISING but NOT CERTIFIED - grow the corpus to >={MIN_GATE_N}, then re-gate. Do NOT ship on this.")
            return 3
        print(f"  VERDICT: {'REVERT (regressed)' if regressed or not fp_ok else 'NOT PROVEN'}")
        return 1
    keep = confident_up and fp_ok
    print(f"  POWER: n={n} -> POWERED")
    print(f"  VERDICT: {'KEEP the change (certified)' if keep else 'REVERT / not proven'}")
    return 0 if keep else 1


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_gate(args) -> int:
    return gate(_load(args.before), _load(args.after), args.force_underpowered)


def _selftest() -> int:
    fails = 0

    def chk(name, cond):
        nonlocal fails
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            fails += 1

    # Wilson CI sanity: 8/23 ~ [0.19,0.55]; 15/23 ~ [0.45,0.81]
    lo, hi = wilson_ci(8, 23)
    chk("wilson 8/23", 0.17 < lo < 0.22 and 0.50 < hi < 0.58)
    chk("wilson 0/0 -> None", wilson_ci(0, 0) == (None, None))

    # a detector that only confirms text containing "vuln"
    corpus = ([{"id": f"p{i}", "text": "this has a vuln", "expected": True} for i in range(10)] +
              [{"id": f"n{i}", "text": "this is clean code", "expected": False} for i in range(10)])
    good = evaluate(lambda t: "vuln" in t, corpus)
    chk("good detector recall=1", good["recall"] == 1.0)
    chk("good detector fpr=0", good["false_positive_rate"] == 0.0)
    chk("good detector alive", not good["dead_channel"] and not good["degenerate"])

    # rubber-stamp detector: confirms EVERYTHING -> recall 1 but fpr 1 -> must REVERT vs good
    stamp = evaluate(lambda t: True, corpus)
    chk("stamp fpr=1", stamp["false_positive_rate"] == 1.0)
    chk("stamp degenerate", stamp["degenerate"])
    # gate: 'improving' from good->stamp keeps recall=1 but fpr 0->1 => REVERT (exit 1), underpowered n=10
    rc = gate(good, stamp, force_underpowered=True)
    chk("gate reverts rubber-stamp", rc == 1)

    # dead channel: detector always raises
    dead = evaluate(lambda t: (_ for _ in ()).throw(RuntimeError("boom")), corpus)
    chk("dead channel flagged", dead["dead_channel"])
    chk("gate refuses dead channel", gate(good, dead, force_underpowered=True) == 2)

    # a real improvement: weak (misses half) -> strong (catches all), fpr stays 0
    weak = evaluate(lambda t: "vuln" in t and "has" in t and len(t) > 100, corpus)  # never matches -> recall 0
    rc2 = gate(weak, good, force_underpowered=True)
    chk("gate keeps real improvement (forced-powered)", rc2 == 0)
    # same improvement, underpowered + not forced -> PROMISING (exit 3), never a silent certify
    rc3 = gate(weak, good, force_underpowered=False)
    chk("gate marks promising-not-certified when underpowered", rc3 == 3)

    print("SELFTEST OK" if fails == 0 else f"SELFTEST FAILED ({fails})")
    return 0 if fails == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="paired_gate - KEEP/REVERT paired-control measurement")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("gate", help="compare two evaluate() JSON measurements")
    g.add_argument("--before", required=True)
    g.add_argument("--after", required=True)
    g.add_argument("--force-underpowered", action="store_true",
                   help="experimentation ONLY: bypass the n>=MIN_GATE_N precondition. NEVER for a real KEEP.")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if args.cmd == "gate":
        return cmd_gate(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
