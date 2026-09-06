#!/usr/bin/env python3
"""research_ground.py - ground an answer in real, cited web sources.

The methodology, generalized from a proven internal craft-research pipeline:

    question -> SEARCH (get candidate source URLs)
             -> FETCH  (pull each source's real text)
             -> MINE   (local model extracts atomic {claim, evidence_quote} pairs
                        FROM that text, not from its own memory)
             -> VERIFY (every mined claim must bind to the fetched source via the
                        claim-provenance gate - a claim whose quote is not really in
                        the page is dropped as a fabrication)
             -> CONSENSUS (keep claims independently supported by >= N sources)
             -> answer, every claim carrying its source citations

Why this shape: it converts "the model says X" into "these >=N independent pages say
X, and here is the verbatim line from each." A weak local model can MINE and PARAPHRASE
adequately; it is a poor source of facts on its own. So we let it read and extract, and
we let the provenance gate + cross-source agreement decide what is true. The model is
the reader, not the authority.

Search backend is PLUGGABLE and no key is hardcoded:
  * brave   -> needs env BRAVE_API_KEY   (https://brave.com/search/api/)
  * serpapi -> needs env SERPAPI_KEY     (https://serpapi.com/)
  * none    -> offline; you pass sources in yourself (or wire your own, e.g. a
               Perplexity / Exa / Tavily call - return [{"title","url"}] and the rest
               of the pipeline is unchanged).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request

try:
    from . import verify as V
    from .llm import LocalLLM, load_config
except ImportError:
    import verify as V
    from llm import LocalLLM, load_config

UA = "Mozilla/5.0 (compatible; lowvram-harness-research/1.0)"


# --- SEARCH (pluggable) -----------------------------------------------------------
def search(query: str, backend: str = "none", max_results: int = 5):
    if backend == "brave":
        return _brave(query, max_results)
    if backend == "serpapi":
        return _serpapi(query, max_results)
    if backend == "none":
        return []
    raise ValueError(f"unknown search backend: {backend} (brave | serpapi | none)")


def _get_json(url: str, headers=None, timeout=30):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _brave(query, n):
    key = os.environ.get("BRAVE_API_KEY")
    if not key:
        raise RuntimeError(
            "BRAVE_API_KEY not set (get one at https://brave.com/search/api/)"
        )
    url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
        {"q": query, "count": n}
    )
    data = _get_json(
        url,
        headers={
            "User-Agent": UA,
            "X-Subscription-Token": key,
            "Accept": "application/json",
        },
    )
    return [
        {"title": w.get("title", ""), "url": w.get("url", "")}
        for w in (data.get("web", {}).get("results") or [])[:n]
        if w.get("url")
    ]


def _serpapi(query, n):
    key = os.environ.get("SERPAPI_KEY")
    if not key:
        raise RuntimeError("SERPAPI_KEY not set (get one at https://serpapi.com/)")
    url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(
        {"q": query, "num": n, "api_key": key}
    )
    data = _get_json(url)
    return [
        {"title": w.get("title", ""), "url": w.get("link", "")}
        for w in (data.get("organic_results") or [])[:n]
        if w.get("link")
    ]


# --- FETCH ------------------------------------------------------------------------
def fetch(url: str, timeout: int = 30, max_chars: int = 20000) -> str:
    """Fetch a URL and reduce it to readable text (scripts/styles stripped, tags
    removed, whitespace collapsed). Deliberately dependency-free - good enough to mine
    claims from; swap in trafilatura/readability for higher-quality extraction."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        html = r.read().decode("utf-8", "replace")
    html = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


# --- MINE (local model extracts grounded claims) ----------------------------------
_MINE_SYS = (
    "You extract atomic factual claims from a SOURCE text. For each claim, copy a "
    "VERBATIM quote from the source that supports it (at least 25 characters, copied "
    "exactly). Do not add facts the source does not state. Return ONLY a JSON array: "
    '[{"claim": "...", "evidence_quote": "...verbatim..."}].'
)


def mine_claims(source_text: str, llm, max_claims: int = 8, extractor=None):
    """Extract {claim, evidence_quote} pairs from one source. `extractor` lets a test
    inject a deterministic function instead of the model. Returns raw pairs (unverified)."""
    if extractor is not None:
        return extractor(source_text)[:max_claims]
    prompt = (
        f"SOURCE:\n{source_text[:8000]}\n\nExtract up to {max_claims} atomic claims "
        f"with verbatim supporting quotes. JSON array only:"
    )
    out = llm.ask(prompt, system=_MINE_SYS, temperature=0)
    arr = _extract_json_array(out)
    return [
        p
        for p in arr
        if isinstance(p, dict) and p.get("claim") and p.get("evidence_quote")
    ][:max_claims]


def _extract_json_array(text: str):
    text = (text or "").strip()
    a, b = text.find("["), text.rfind("]")
    if a >= 0 and b > a:
        try:
            arr = json.loads(text[a : b + 1])
            return arr if isinstance(arr, list) else []
        except json.JSONDecodeError:
            return []
    return []


# --- CONSENSUS --------------------------------------------------------------------
def _similar(a: str, b: str, thresh: float = 0.5) -> bool:
    ta, tb = V.content_tokens(a), V.content_tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= thresh


def consensus(bound_claims, min_sources: int = 2):
    """Cluster verified claims by token overlap; a claim is CONSENSUS iff it is
    independently supported by >= min_sources distinct sources. Returns the consensus
    claims each with their citation URLs."""
    clusters = []
    for c in bound_claims:
        placed = False
        for cl in clusters:
            if _similar(c["claim"], cl["rep"]):
                cl["members"].append(c)
                cl["sources"].add(c["source_url"])
                placed = True
                break
        if not placed:
            clusters.append(
                {"rep": c["claim"], "members": [c], "sources": {c["source_url"]}}
            )
    out = []
    for cl in clusters:
        if len(cl["sources"]) >= min_sources:
            out.append(
                {
                    "claim": cl["rep"],
                    "n_sources": len(cl["sources"]),
                    "citations": sorted(cl["sources"]),
                    "evidence": [
                        {"quote": m["evidence_quote"], "url": m["source_url"]}
                        for m in cl["members"]
                    ],
                }
            )
    out.sort(key=lambda x: x["n_sources"], reverse=True)
    return out


def ground(
    question,
    backend="none",
    sources=None,
    llm=None,
    max_results=5,
    min_sources=2,
    floor=V.DEFAULT_FLOOR,
    extractor=None,
):
    """Full pipeline. `sources` (list of {"url","text"}) skips search+fetch - pass it
    for offline use or your own retriever. Returns a grounded, cited answer."""
    llm = llm or (LocalLLM() if extractor is None else None)
    if sources is None:
        hits = search(question, backend=backend, max_results=max_results)
        sources = []
        for h in hits:
            try:
                sources.append({"url": h["url"], "text": fetch(h["url"])})
            except Exception as e:  # noqa: BLE001
                print(f"  [fetch-fail] {h['url']}: {e}", file=sys.stderr)
    all_bound = []
    n_mined = n_orphan = 0
    for src in sources:
        pairs = mine_claims(src["text"], llm, extractor=extractor)
        for p in pairs:
            n_mined += 1
            rec = {
                "claim": p["claim"],
                "evidence_quote": p["evidence_quote"],
                "source_text": src["text"],
            }
            ok, _reason = V.check_claim(rec, floor)
            if ok:
                all_bound.append(
                    {
                        "claim": p["claim"],
                        "evidence_quote": p["evidence_quote"],
                        "source_url": src["url"],
                    }
                )
            else:
                n_orphan += 1
    cons = consensus(all_bound, min_sources=min_sources)
    source_records = [
        {
            "url": src["url"],
            "sha256": hashlib.sha256(src["text"].encode("utf-8")).hexdigest(),
            "chars": len(src["text"]),
        }
        for src in sources
    ]
    return {
        "question": question,
        "n_sources": len(sources),
        "n_mined": n_mined,
        "n_bound": len(all_bound),
        "n_orphan": n_orphan,
        "min_sources": min_sources,
        "source_records": source_records,
        "consensus": cons,
        "verdict": "grounded"
        if cons
        else "ungrounded (no claim met the consensus floor)",
    }


def _selftest() -> int:
    """Offline: two sources agree on one real fact and each carries one unsupported
    'fact'. Consensus must surface the agreed, provenance-bound claim and drop the rest."""
    fails = 0

    def chk(name, cond):
        nonlocal fails
        print(f"  [{'PASS' if cond else 'FAIL'}] {name}")
        if not cond:
            fails += 1

    src_a = (
        "RTX 2080 cards ship with 8 GB of GDDR6 memory on the reference design. "
        "The card also cures baldness according to this blog."
    )
    src_b = (
        "Every RTX 2080 has 8 GB of GDDR6 memory available to the GPU. "
        "It was manufactured on Mars, obviously."
    )
    sources = [
        {"url": "http://a.example/x", "text": src_a},
        {"url": "http://b.example/y", "text": src_b},
    ]

    # deterministic extractor (no model): returns one real + one absurd claim per source
    def extractor(text):
        # source-specific verbatim quote (>=25 chars, real substring of THIS source);
        # both sources yield the SAME claim text so consensus can cluster them.
        q = (
            "ship with 8 GB of GDDR6 memory on the reference design"
            if "reference" in text
            else "RTX 2080 has 8 GB of GDDR6 memory available to the GPU"
        )
        out = [{"claim": "The GPU has 8 GB of GDDR6 memory", "evidence_quote": q}]
        if "baldness" in text:
            out.append(
                {
                    "claim": "The RTX 2080 cures baldness",
                    "evidence_quote": "The card also cures baldness according to this blog",
                }
            )
        if "Mars" in text:
            out.append(
                {
                    "claim": "The RTX 2080 was manufactured on Mars",
                    "evidence_quote": "It was manufactured on Mars, obviously",
                }
            )
        # a fabricated-provenance claim (quote NOT in source) - must be dropped
        out.append(
            {
                "claim": "The RTX 2080 has 48 GB of memory",
                "evidence_quote": "the RTX 2080 has 48 GB of memory for enterprise workloads",
            }
        )
        return out

    res = ground(
        "how much memory does an RTX 2080 have?",
        sources=sources,
        extractor=extractor,
        min_sources=2,
    )
    chk("verdict grounded", res["verdict"] == "grounded")
    claims = [c["claim"] for c in res["consensus"]]
    chk(
        "memory fact reached consensus (2 sources)",
        any("8" in c and "gddr6" in c.lower() for c in claims),
    )
    chk(
        "baldness dropped (only 1 source)",
        not any("baldness" in c.lower() for c in claims),
    )
    chk("mars dropped (only 1 source)", not any("mars" in c.lower() for c in claims))
    chk("fabricated 48GB quote never bound", res["n_orphan"] >= 2)
    chk(
        "json-array extractor: fenced",
        _extract_json_array('```json\n[{"claim":"a"}]\n```') == [{"claim": "a"}],
    )
    chk(
        "similar: overlap",
        _similar("rtx 2080 8gb memory", "the rtx 2080 has 8gb memory"),
    )
    chk("similar: disjoint", not _similar("cat dog fish", "quantum ram voltage"))

    print("SELFTEST OK" if fails == 0 else f"SELFTEST FAILED ({fails})")
    return 0 if fails == 0 else 1


def cmd_ground(args) -> int:
    llm = LocalLLM(load_config(args.config))
    res = ground(
        args.question,
        backend=args.backend,
        llm=llm,
        max_results=args.max_results,
        min_sources=args.min_sources,
    )
    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0 if res["consensus"] else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="research_ground - cited, provenance-verified web grounding"
    )
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    g = sub.add_parser("ground")
    g.add_argument("--question", required=True)
    g.add_argument("--backend", default="none", choices=["none", "brave", "serpapi"])
    g.add_argument("--config", default=None)
    g.add_argument("--max-results", type=int, default=5)
    g.add_argument("--min-sources", type=int, default=2)
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if args.cmd == "ground":
        return cmd_ground(args)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
