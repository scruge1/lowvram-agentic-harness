#!/usr/bin/env python3
"""verify.py - deterministic, model-free claim-provenance gate.

The load-bearing idea of the harness: a weak local model WILL confidently state
things its source never supported. So we do not trust the model to grade itself.
We decompose an output into atomic CLAIMS; every claim must BIND to a backing
source datum or it is an ORPHAN (a hallucination), caught by a claim->source
RESOLVER, not by another model call.

A claim record (one JSON object per line) is:
  {"claim": "<assertion>", "evidence_quote": "<verbatim span from source>",
   "source_text": "<the full source text>"}

Verdict = PASS iff every claim binds.

Adapted for standalone use from a proven internal verification spine (itself
ported from an image-metadata ledger and a genealogy fact-auditor). The algorithm
is unchanged; only logging and model endpoints were made generic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

MIN_QUOTE_LEN = 25
DEFAULT_FLOOR = 0.6


def _log(level, source, message, ctx=None):
    if level in ("WARN", "ERROR"):
        print(f"[{level}] {source}: {message} {ctx or ''}", file=sys.stderr)


STOP = {
    "a", "an", "the", "and", "or", "but", "if", "of", "to", "in", "on", "at",
    "for", "with", "by", "from", "as", "is", "are", "was", "were", "be", "been",
    "being", "it", "its", "this", "that", "these", "those", "can", "could",
    "will", "would", "may", "might", "do", "does", "did", "not", "no", "so",
    "than", "then", "when", "while", "you", "your", "their", "they", "any",
    "all", "some", "into", "out", "up", "down", "over", "under", "via", "per",
    "has", "have", "had", "which", "who", "what", "how", "we", "i",
}


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", str(s)).lower()
    return re.sub(r"\s+", " ", s).strip()


def content_tokens(s: str) -> set:
    s = unicodedata.normalize("NFKC", str(s)).lower()
    out = set()
    for t in re.findall(r"[a-z0-9][a-z0-9._/+-]*", s):
        t = t.strip("._/+-")
        if t and t not in STOP and len(t) > 1:
            out.add(t)
    return out


def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


NEG_CUES = {"not", "no", "never", "none", "neither", "nor", "without", "cannot",
            "cant", "wont", "dont", "doesnt", "didnt", "isnt", "arent", "wasnt",
            "werent", "lacks", "lack", "fails", "fail", "unable", "absent"}


def _neg_count(s: str) -> int:
    s = unicodedata.normalize("NFKC", str(s)).lower()
    s = s.replace("n't", " not ")
    toks = set(re.findall(r"[a-z]+", s))
    return len(toks & NEG_CUES)


_NUMWORD = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
    "hundred": 100, "thousand": 1000, "million": 1000000, "billion": 1000000000,
}


def numerics(s: str) -> set:
    s = unicodedata.normalize("NFKC", str(s)).lower()
    out = set()
    for m in re.findall(r"\d[\d,]*\.?\d*", s):
        out.add(m.replace(",", "").rstrip("."))
    for w in re.findall(r"[a-z]+", s):
        if w in _NUMWORD:
            out.add(str(_NUMWORD[w]))
    return out


def check_claim(rec: dict, floor: float = DEFAULT_FLOOR):
    """(a) provenance (b) quote-in-source (c) span-bind (d) negation-polarity
    (e) numeric-exactness. Returns (bound: bool, reason: str)."""
    claim = rec.get("claim")
    quote = rec.get("evidence_quote")
    source = rec.get("source_text")
    if not claim or not quote:
        return False, "missing claim or evidence_quote"
    if not source:
        return False, "provenance: no source_text"
    if len(normalize(quote)) < MIN_QUOTE_LEN:
        return False, f"quote < {MIN_QUOTE_LEN} chars normalized"
    if normalize(quote) not in normalize(source):
        return False, "quote_not_in_source (fabricated provenance)"
    claim_toks = content_tokens(claim)
    if not claim_toks:
        return False, "claim has no content tokens"
    overlap = len(claim_toks & content_tokens(quote)) / len(claim_toks)
    if overlap < floor:
        missing = sorted(claim_toks - content_tokens(quote))[:6]
        return False, f"span_bind {overlap:.2f} < {floor} (claim tokens absent from quote: {missing})"
    if (_neg_count(claim) % 2) != (_neg_count(quote) % 2):
        return False, "negation_mismatch (overlap but opposite meaning)"
    missing_nums = numerics(claim) - numerics(quote)
    if missing_nums:
        return False, f"numeric_mismatch (claim numbers absent from quote: {sorted(missing_nums)})"
    return True, "bound"


_ENTAIL_SYS = (
    "You are a strict natural-language-inference judge. Decide ONLY whether the SOURCE "
    "quote supports the CLAIM. Judge support, not truth. Do not use outside knowledge. "
    "Paraphrase counts; inference beyond the source does not. Answer with EXACTLY one "
    "word: entail | contradict | neutral."
)


def entail_claim(claim: str, quote: str, llm):
    """`llm` is a harness.llm.LocalLLM. Returns (entailed: bool, reason: str)."""
    prompt = f"SOURCE: {quote}\nCLAIM: {claim}\nAnswer with one word (entail | contradict | neutral):"
    try:
        out = llm.ask(prompt, system=_ENTAIL_SYS, temperature=0, max_tokens=8).lower()
    except Exception as e:
        return False, f"entail_unreachable ({e}) - escalate, not a silent pass"
    label = "entail" if "entail" in out else ("contradict" if "contradict" in out else "neutral")
    return (label == "entail"), f"entail:{label}"


def verify_claims(claims, floor=DEFAULT_FLOOR, llm=None) -> dict:
    """Run claim-provenance over a list; return a machine-checkable receipt.
    If `llm` is given, run the NLI judge on claims that PASS the cheap gates."""
    orphans = []
    bound = 0
    n_entailed = 0
    for i, rec in enumerate(claims):
        ok, reason = check_claim(rec, floor)
        if ok and llm is not None:
            ent_ok, ent_reason = entail_claim(rec.get("claim", ""), rec.get("evidence_quote", ""), llm)
            n_entailed += 1
            if not ent_ok:
                ok, reason = False, ent_reason
        if ok:
            bound += 1
        else:
            orphans.append({"index": i, "claim": (rec.get("claim") or "")[:120], "reason": reason})
    n = len(claims)
    receipt = {
        "job_class": "claim_provenance",
        "n_claims": n, "n_bound": bound, "n_orphan": len(orphans), "n_entailed": n_entailed,
        "orphans": orphans, "floor": floor,
        "verdict": "pass" if (n > 0 and not orphans) else ("escalate" if n else "empty"),
        "ts_epoch": time.time(),
    }
    _log("INFO" if receipt["verdict"] == "pass" else "WARN", "verify.claim_provenance",
         f"verdict {receipt['verdict']}", {"bound": bound, "orphan": len(orphans)})
    return receipt


def _load_jsonl(path: Path):
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def cmd_verify(args) -> int:
    claims = _load_jsonl(Path(args.claims))
    receipt = verify_claims(claims, args.floor)
    if args.receipt:
        Path(args.receipt).write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[claim-provenance] {receipt['n_bound']}/{receipt['n_claims']} bound, "
          f"{receipt['n_orphan']} orphan -> verdict={receipt['verdict'].upper()}")
    for o in receipt["orphans"]:
        print(f"  ORPHAN [{o['index']}] {o['reason']}: {o['claim']!r}")
    return 0 if receipt["verdict"] == "pass" else 1


def cmd_selftest(args) -> int:
    """Runtime presses back: a real claim binds; a fabricated quote, an over-general
    claim, a negation flip and a numeric mismatch are all caught."""
    src = ("Firecrawl is the fastest way for agents to discover and use Firecrawl. "
           "It returns clean markdown and structured JSON output for any page.")
    cases = [
        ({"claim": "Firecrawl returns clean markdown and structured JSON output",
          "evidence_quote": "It returns clean markdown and structured JSON output for any page",
          "source_text": src}, True),
        ({"claim": "Firecrawl returns clean markdown output",
          "evidence_quote": "Firecrawl claims to triple your revenue overnight guaranteed forever",
          "source_text": src}, False),
        ({"claim": "Firecrawl integrates with Salesforce CRM billing and SAP payroll",
          "evidence_quote": "Firecrawl is the fastest way for agents to discover and use Firecrawl",
          "source_text": src}, False),
        ({"claim": "Firecrawl does not return clean structured JSON output",
          "evidence_quote": "It returns clean markdown and structured JSON output for any page",
          "source_text": src}, False),
        ({"claim": "Firecrawl supports exactly 500 pages per crawl",
          "evidence_quote": "Firecrawl supports 50 pages per crawl on the free tier",
          "source_text": "Firecrawl supports 50 pages per crawl on the free tier."}, False),
    ]
    ok = True
    for i, (rec, expect) in enumerate(cases):
        bound, reason = check_claim(rec)
        status = "PASS" if bound == expect else "FAIL"
        if bound != expect:
            ok = False
        print(f"  [{status}] case {i}: bound={bound} expected={expect} ({reason})")
    receipt = verify_claims([c[0] for c in cases])
    vok = receipt["verdict"] == "escalate" and receipt["n_orphan"] == 4
    print(f"  [{'PASS' if vok else 'FAIL'}] batch verdict={receipt['verdict']} "
          f"n_orphan={receipt['n_orphan']} (expected escalate / 4)")
    ok = ok and vok
    print("SELFTEST OK" if ok else "SELFTEST FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="verify - claim-provenance gate")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("verify")
    c.add_argument("--claims", required=True, help="jsonl of claim records")
    c.add_argument("--floor", type=float, default=DEFAULT_FLOOR)
    c.add_argument("--receipt", default=None)
    args = ap.parse_args()
    if args.selftest:
        return cmd_selftest(args)
    if args.cmd == "verify":
        return cmd_verify(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
