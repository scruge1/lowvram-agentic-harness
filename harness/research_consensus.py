"""Deterministic scoring of cached, source-bound mining results; no inference.

Scoring/tiers and lexical grouping adapted from godmode_research.py, source
SHA256 0445b7b70849fb9ec71cd0553ff87996161d42617cb7096cfb684d2c56cee80b.
Numeric distribution/full-set semantics adapted from img_consensus.py, source
SHA256 d2763b2a5845d13143a91f4871e73901446931b907b7a8927963af7efbaffae5.
Domain priors are scoring policy, not proof of authority or editorial independence.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import time
from urllib.parse import urlsplit

from harness import research_mining as mining
from harness.research_runtime import check_deadline, digest, require, text_view, wire
from harness.web_research import canonical_url, coverage_domain

AUTHORITY = [
    (r"(^|\.)arxiv\.org$|(^|\.)ar5iv\.org$|(^|\.)openreview\.net$|(^|\.)nature\.com$|(^|\.)science\.org$|"
     r"(^|\.)ncbi\.nlm\.nih\.gov$|(^|\.)acm\.org$|(^|\.)ieee\.org$|(^|\.)aclanthology\.org$|"
     r"(^|\.)doi\.org$|(^|\.)openalex\.org$|(^|\.)semanticscholar\.org$", 1.0, "primary/venue/DOI prior"),
    (r"(^|\.)deepmind\.com$|(^|\.)deepmind\.google$|(^|\.)research\.google$|(^|\.)ai\.googleblog\.com$|"
     r"(^|\.)openai\.com$|(^|\.)anthropic\.com$|(^|\.)sakana\.ai$|(^|\.)microsoft\.com$|(^|\.)meta\.com$", 0.85, "originating-lab blog prior"),
    (r"(^|\.)github\.com$|(^|\.)github\.io$|(^|\.)readthedocs\.(?:io|org)$|(^|\.)huggingface\.co$", 0.70, "implementation/docs prior"),
    (r"(^|\.)medium\.com$|(^|\.)substack\.com$|(^|\.)distill\.pub$|(^|\.)lesswrong\.com$", 0.50, "practitioner-blog prior"),
    (r"(^|\.)reddit\.com$|(^|\.)stackexchange\.com$|(^|\.)stackoverflow\.com$|(^|\.)news\.ycombinator\.com$|(^|\.)quora\.com$", 0.30, "forum prior"),
]
REL_WEIGHT = {1: 0.20, 2: 0.70, 3: 1.0}
STOP = frozenset(("the a an and or of to in on for with is are be as by that this it its into from at we our "
                  "not no can must should will each over across other only also more most than then thus which "
                  "these those such they them their he she his her use used using via per etc eg ie vs").split())
THRESHOLD = 0.4
POLICY = "source-claim-scoring/v1"
NUMBER = re.compile(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][-+]?\d+)?(?:\s*[x×]\s*\d+)?(?:\s*[A-Za-z%][A-Za-z0-9/%^_-]*)?")


def authority_of(url, codex_candidates=None):
    host = (urlsplit(url).hostname or "").lower()
    for pattern, score, reason in AUTHORITY:
        if re.search(pattern, host):
            return score, reason
    if codex_candidates and host in codex_candidates:
        candidate = codex_candidates[host]
        return max(0.10, min(0.80, float(candidate.get("authority", 0.5)))), "unverified candidate prior"
    return 0.10, "unknown-domain floor"


def claim_weight(claim, codex_candidates=None):
    authority, _ = authority_of(claim.get("source_url", ""), codex_candidates)
    confidence = float(claim.get("confidence", 0.5))
    if not (claim.get("evidence_span") or "").strip():
        confidence = min(confidence, 0.25)
    return authority * REL_WEIGHT.get(int(claim.get("relevance", 0)), 0.0) * confidence


def _independent_sources(claims):
    # Retain the legacy formula's name, but expose its actual weaker meaning.
    return len({coverage_domain(c.get("requested_source_url") or c["source_url"]) for c in claims})


def cluster_score(claims, freshness, codex_candidates=None):
    weights = sorted((claim_weight(c, codex_candidates) for c in claims), reverse=True)
    if not weights:
        return {"cluster_score": 0.0}
    max_weight, mean_top3 = weights[0], sum(weights[:3]) / min(3, len(weights))
    count = _independent_sources(claims)
    independence = min(1.0, math.log2(1 + count) / math.log2(5))
    quality = min(1.0, sum(bool((c.get("evidence_span") or "").strip()) for c in claims) / len(claims))
    score = 100 * (0.40 * max_weight + 0.25 * mean_top3 + 0.20 * independence + 0.10 * quality + 0.05 * float(freshness))
    return {"cluster_score": round(score, 2), "max_claim_weight": round(max_weight, 3),
            "mean_top3": round(mean_top3, 3), "independent_sources": count,
            "source_independence": round(independence, 3), "evidence_quality": round(quality, 3),
            "freshness": round(float(freshness), 3)}


def tier(claims, comp, codex_candidates=None):
    max_auth = max((authority_of(c["source_url"], codex_candidates)[0] for c in claims), default=0)
    max_rel = max((c["relevance"] for c in claims), default=0)
    max_conf = max((c["confidence"] for c in claims), default=0)
    has_evidence = any(c.get("evidence_span") for c in claims)
    if max_auth >= 0.90 and max_rel >= 3 and max_conf >= 0.75 and has_evidence:
        return "CANONICAL"
    if comp.get("cluster_score", 0) >= 65 and comp.get("independent_sources", 0) >= 2:
        return "CORROBORATED"
    if comp.get("cluster_score", 0) >= 45 or max_auth >= 0.80:
        return "EMERGING"
    return "FRINGE_AUTHORITATIVE_SINGLETON" if max_auth >= 0.70 else "FRINGE_LOW_AUTHORITY"


def _content_tokens(text):
    return frozenset(w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) >= 3 and w not in STOP)


def _jaccard(a, b):
    return len(a & b) / (len(a) + len(b) - len(a & b)) if a and b else 0.0


def numeric_literals(text):
    # Verbatim evidence values, including their written units. No conversion,
    # averaging, or claim that different contexts are a proven contradiction.
    return tuple(sorted(set(match.group().strip() for match in NUMBER.finditer(text))))


def validate_mine(store, artifact_id, identity_sha256, deadline=None):
    check_deadline(deadline)
    record = store.get(artifact_id)
    require(record["action"] == "mine" and record.get("identity_sha256") == identity_sha256, "Use mining results bound to the current project identity")
    payload = record["payload"]
    plan_record = store.get(payload.get("plan_artifact_id"))
    require(plan_record["action"] == "mine_plan" and plan_record.get("identity_sha256") == identity_sha256, "Mining plan/project identity changed")
    saved = plan_record["payload"]
    spec = saved["spec"]
    rebuilt = mining.prepare({"query": spec["question"], "extraction_schema": spec["extraction_schema"],
                              "artifact_ids": [s["artifact_id"] for s in spec["sources"]],
                              "recall_bias": "HIGH" if spec["recall_floor"] == 1 else "MEDIUM",
                              "mine_timeout_seconds": spec["mine_timeout_seconds"],
                              **({k: spec["research_binding"][k] for k in ("research_plan_id", "retrieval_plan_id")}
                                 | {"identity_sha256": identity_sha256} if "research_binding" in spec else {})},
                             store, spec["model"], text_view, wire, digest)
    check_deadline(deadline)
    require(all(saved.get(key) == value for key, value in rebuilt.items())
            and payload.get("run_identity_sha256") == rebuilt["run_identity_sha256"]
            and payload.get("model") == spec["model"] and payload.get("mine_timeout_seconds") == spec["mine_timeout_seconds"],
            "Mining source/prompt/schema/model identity differs")
    expected = len(rebuilt["sources"]) * len(rebuilt["shards"])
    require(type(payload.get("expected_shards")) is int and payload["expected_shards"] == expected and all(type(payload.get(k)) is int and 0 <= payload[k] <= expected
            for k in ("attempted_shards", "analysed_shards"))
            and payload["analysed_shards"] <= payload["attempted_shards"]
            and type(payload.get("analysed_rate")) in (int, float)
            and payload["analysed_rate"] == payload["analysed_shards"] / expected, "Invalid mining health counters")
    require(type(payload.get("complete")) is bool and type(payload.get("ok")) is bool
            and payload["complete"] == payload["ok"] == (payload.get("status") == "ok")
            and payload.get("status") in {"ok", "partial_failure", "zero_claims", "low_yield", "all_failed", "cancelled", "deadline"},
            "Invalid mining completion status")
    require(payload.get("seen_source_artifacts") == ([s["artifact_id"] for s in rebuilt["sources"]] if payload["complete"] else []), "Invalid mining seen scope")
    require(isinstance(payload.get("failure_ledger"), list) and len(payload["failure_ledger"]) <= expected + 1
            and isinstance(payload.get("response_hashes"), list) and len(payload["response_hashes"]) <= expected,
            "Invalid mining failure/response coverage")
    slots, failed, run_failures = {}, {}, 0
    for row in payload["response_hashes"]:
        check_deadline(deadline)
        require(isinstance(row, dict) and set(row) == {"source", "shard", "status", "text_sha256"}
                and type(row["source"]) is int and 0 <= row["source"] < len(rebuilt["sources"])
                and type(row["shard"]) is int and 0 <= row["shard"] < len(rebuilt["shards"])
                and row["status"] in {"ok", "model_error", "malformed", "cancelled", "deadline", "length", "model_changed"}
                and isinstance(row["text_sha256"], str) and mining.HASH.fullmatch(row["text_sha256"]), "Invalid mining response binding")
        key = row["source"], row["shard"]
        require(key not in slots, "Repeated mining response binding")
        slots[key] = row["status"]
    for row in payload["failure_ledger"]:
        check_deadline(deadline)
        require(isinstance(row, dict), "Malformed mining failure row")
        if row.get("scope") == "run":
            run_failures += 1
            require(set(row) == {"scope", "status", "analysed_rate", "minimum_analysed_rate", "reason"}
                    and run_failures == 1 and row["status"] == payload["status"]
                    and type(row["analysed_rate"]) in (int, float) and row["analysed_rate"] == payload["analysed_rate"]
                    and row["minimum_analysed_rate"] == mining.MIN_ANALYSED_RATE
                    and isinstance(row["reason"], str) and len(row["reason"]) <= 1000, "Mining run failure status differs")
            continue
        key = row.get("source"), row.get("shard")
        require(set(row) == {"source_artifact_id", "source", "shard", "status", "reason"}
                and isinstance(row["reason"], str) and len(row["reason"]) <= 300
                and type(key[0]) is int and 0 <= key[0] < len(rebuilt["sources"])
                and type(key[1]) is int and 0 <= key[1] < len(rebuilt["shards"])
                and key not in failed and row.get("source_artifact_id") == rebuilt["sources"][key[0]]["artifact_id"]
                and row.get("status") in {"not_attempted", "model_error", "malformed", "cancelled", "deadline", "length", "model_changed"},
                "Invalid mining failure/source binding")
        failed[key] = row["status"]
    require(run_failures == int(payload["status"] in {"all_failed", "low_yield", "zero_claims", "cancelled", "deadline"}),
            "Missing or unexpected mining run failure row")
    good = set()
    for s in range(len(rebuilt["sources"])):
        check_deadline(deadline)
        for n in range(len(rebuilt["shards"])):
            key = s, n
            if key not in slots:
                require(failed.get(key) == "not_attempted", "Missing mining response coverage")
            elif slots[key] == "ok" and key not in failed:
                good.add(key)
            else:
                require(failed.get(key) == slots[key] or slots[key] == "ok" and failed.get(key) == "malformed", "Mining failure coverage differs")
    require(len(slots) == payload["attempted_shards"] and len(good) == payload["analysed_shards"], "Mining analysed coverage differs")
    rows = payload.get("claims")
    require(isinstance(rows, list) and len(rows) <= expected * 32, "Invalid mining claim count")
    origins = {source["artifact_id"]: store.get(source["artifact_id"])["payload"].get("requested_url") or source["source_url"]
               for source in rebuilt["sources"]}
    validated = []
    fields = {"field", "claim", "relevance", "confidence", "evidence_span"}
    for row in rows:
        check_deadline(deadline)
        require(isinstance(row, dict), "Malformed stored mining claim")
        sources = [(i, source) for i, source in enumerate(rebuilt["sources"]) if source["artifact_id"] == row.get("artifact_id")]
        require(len(sources) == 1, "Claim source is outside its mining plan")
        s, source = sources[0]
        require(row.get("field") in spec["extraction_schema"], "Claim field is outside its mining schema")
        n = spec["extraction_schema"].index(row["field"]) // mining.SHARD_FIELDS
        require((s, n) in good, "Claim belongs to a failed mining shard")
        values, _ = mining.claims(wire({"claims": [{k: row.get(k) for k in fields}]}).decode(),
                                  rebuilt["shards"][n], source, spec["recall_floor"])
        require(values == [row], "Stored claim/source hash or exact evidence offsets differ")
        origin = origins[source["artifact_id"]]
        for url in (origin, row["source_url"]):
            require(isinstance(url, str), "Invalid cached source URL")
            parsed = urlsplit(url)
            require(parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password,
                    "Invalid cached source URL")
        validated.append({**row, "mining_artifact_id": artifact_id,
                          "requested_source_url": origin})
    status = ("all_failed" if not good else "low_yield" if len(good) / expected < mining.MIN_ANALYSED_RATE
              else "zero_claims" if not validated else "partial_failure" if failed else "ok")
    require(payload["status"] in {"cancelled", "deadline"} or payload["status"] == status, "Mining status contradicts full-set coverage")
    require(type(payload.get("completed_sources")) is int and payload["completed_sources"] == sum(all((s, n) in good for n in range(len(rebuilt["shards"])))
            for s in range(len(rebuilt["sources"]))), "Mining source completion coverage differs")
    require(type(payload.get("dropped_background_claims")) is int and 0 <= payload["dropped_background_claims"] <= expected * 32 - len(validated),
            "Invalid mining background coverage")
    operationally_healthy = len(good) == expected and payload["status"] in {"ok", "zero_claims"}
    return spec, payload, validated, operationally_healthy


def score(store, artifact_ids, identity_sha256, *, query=None, extraction_schema=None, deadline=None):
    deadline = time.monotonic() + 30 if deadline is None else deadline
    require(type(deadline) in (int, float) and math.isfinite(deadline), "Invalid scoring deadline")
    check_deadline(deadline)
    require(isinstance(artifact_ids, list) and 1 <= len(artifact_ids) <= 32 and len(set(artifact_ids)) == len(artifact_ids), "Use 1 through 32 distinct mining artifacts")
    claims, inputs, intent, input_bytes = [], [], None, 0
    for artifact_id in artifact_ids:
        check_deadline(deadline)
        spec, payload, rows, healthy = validate_mine(store, artifact_id, identity_sha256, deadline)
        current = {"query": spec["question"], "extraction_schema": spec["extraction_schema"]}
        require(intent is None or intent == current, "Mining topics or extraction schemas differ; do not mix research questions")
        intent = current
        claims.extend(rows)
        entry = {"artifact_id": artifact_id, "run_identity_sha256": payload["run_identity_sha256"],
                       "plan_artifact_id": payload["plan_artifact_id"], "model": payload["model"],
                       "source_artifact_ids": [s["artifact_id"] for s in spec["sources"]], "recall_floor": spec["recall_floor"],
                       "status": payload["status"], "complete": payload["complete"], "claim_count": len(rows),
                       "operationally_healthy": healthy, "no_relevant_claims": healthy and not rows,
                       "attempted_shards": payload["attempted_shards"], "analysed_shards": payload["analysed_shards"],
                       "expected_shards": payload["expected_shards"], "dropped_background_claims": payload["dropped_background_claims"],
                       "failure_ledger": payload["failure_ledger"]}
        input_bytes += len(wire(rows)) + len(wire(entry))
        require(input_bytes <= store.maximum, "Consensus input/claim byte budget exceeded; split the batch; no rows were dropped")
        inputs.append(entry)
    require((query is None or query == intent["query"]) and (extraction_schema is None or extraction_schema == intent["extraction_schema"]), "Requested consensus intent differs from cached mining")
    background = [c for c in claims if c["relevance"] <= 1]
    promoted = [c for c in claims if c["relevance"] > 1]
    row_indices = {id(row): index for index, row in enumerate(claims)}
    leaders = []
    for row in promoted:
        check_deadline(deadline)
        tokens = _content_tokens(row["claim"])
        signature = (row["field"], numeric_literals(row["claim"]), numeric_literals(row["evidence_span"]))
        best, similarity = None, THRESHOLD
        for index, leader in enumerate(leaders):
            if index % 64 == 0:
                check_deadline(deadline)
            match = _jaccard(tokens, leader["tokens"]) if signature == leader["signature"] else 0.0
            if match >= similarity:
                best, similarity = leader, match
        if best is None:
            leaders.append({"tokens": tokens, "signature": signature, "rows": [row]})
        else:
            best["rows"].append(row)
    clusters, numeric = [], {}
    for leader in leaders:
        check_deadline(deadline)
        rows = leader["rows"]
        scored, urls, snapshots = [], set(), set()
        for row in sorted(rows, key=lambda c: (-claim_weight(c), c["source_url"], c["claim"])):
            check_deadline(deadline)
            url = canonical_url(row["requested_source_url"])
            snapshot = row["source_text_sha256"]
            if url not in urls and snapshot not in snapshots:
                scored.append(row)
            urls.add(url)
            snapshots.add(snapshot)
        comp = cluster_score(scored, 0.5)
        clusters.append({"field": rows[0]["field"], "claim": rows[0]["claim"], "tier": tier(scored, comp), **comp,
                         "scored_claims": len(scored), "duplicate_references": len(rows) - len(scored),
                         "domain_coverage_proxy": comp["independent_sources"],
                         "claim_indices": [row_indices[id(row)] for row in rows]})
    for row in claims:
        check_deadline(deadline)
        for value in numeric_literals(row["evidence_span"]):
            numeric.setdefault(row["field"], {}).setdefault(value, []).append(row)
    distributions = []
    for field, values in sorted(numeric.items()):
        check_deadline(deadline)
        spread = []
        for value, rows in sorted(values.items()):
            check_deadline(deadline)
            spread.append({"literal": value, "domain_coverage_proxy": _independent_sources(rows),
                           "unique_snapshots": len({r["source_text_sha256"] for r in rows}),
                           "claim_indices": [row_indices[id(row)] for row in rows]})
        distributions.append({"field": field, "status": "CONTESTED_LITERALS" if len(values) > 1 else "SINGLE_LITERAL",
                              "comparison": "written evidence literals; no unit conversion, averaging or proven contradiction",
                              "values": spread})
    clusters.sort(key=lambda c: (-c["cluster_score"], c["field"], c["claim"]))
    healthy = all(row["operationally_healthy"] for row in inputs)
    status = ("all_failed" if not any(row["analysed_shards"] for row in inputs) else "partial_coverage" if not healthy
              else "no_relevant_claims" if not claims else "background_only" if not promoted else "scored")
    result = {"ok": status == "scored", "status": status, "complete": status == "scored", "consensus_established": False,
            "reason": "Deterministic policy scoring only. Lexical similarity, model grades and domain counts do not prove truth, contradiction or editorial independence.",
            **intent, "policy": POLICY, "cluster_method": "lexical-jaccard-0.4; field/numeric-signature partition",
            "embedding_route": "not_used_no_qualified_route", "freshness_policy": "legacy coefficient0.5; document age not measured",
            "inputs": inputs, "input_claims": len(claims), "claim_rows": claims, "background_claims": len(background),
            "background_claim_indices": [row_indices[id(row)] for row in background], "clusters": clusters,
            "coverage_complete": healthy,
            "numeric_evidence": distributions, "coverage": "all supplied mining inputs retained; not coverage of the whole web",
            "run_identity_sha256": digest(wire({"project": store.project, "artifacts": artifact_ids, "intent": intent,
                                               "policy": POLICY, "source_sha256": digest(Path(__file__).read_bytes())}))}
    require(len(wire(result)) <= store.maximum, "Consensus result exceeds the artifact byte budget; split the batch; no rows were dropped")
    check_deadline(deadline)
    return result
