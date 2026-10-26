"""Immutable question/request bindings in the existing research ArtifactStore.

Planning fields reuse godmode_research.plan's topic-specific angles, schema,
source-priority and recall intent (source SHA256
0445b7b70849fb9ec71cd0553ff87996161d42617cb7096cfb684d2c56cee80b).
The main agent supplies the plan. This module performs no inference or I/O
outside that store, and a plan grants no permissions or execution authority.
"""
from __future__ import annotations

import re

from harness.research_runtime import check_deadline, digest, require, wire
from harness.research_mining import FIELD
from harness.web_research import _public_url

NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,39}\Z")
PLAN_BYTES = 32768
MANIFEST_BYTES = 65536
MAX_ACQUISITIONS = 268  # 128 requested URLs, fetch+render, and 12 angle searches.


def bounded_text(value, maximum):
    require(isinstance(value, str) and 1 <= len(value.strip()) <= maximum, "Invalid bounded planning text")
    return value


def name(value):
    require(isinstance(value, str) and NAME.fullmatch(value), "Invalid research request/angle ID")
    return value


def plan(request):
    query = bounded_text(request.get("query"), 1000)
    fields, angles = request.get("extraction_schema"), request.get("angles")
    priorities, bias = request.get("source_priorities", []), request.get("recall_bias", "MEDIUM")
    require(isinstance(fields, list) and 1 <= len(fields) <= 32 and len(set(fields)) == len(fields)
            and all(isinstance(f, str) and FIELD.fullmatch(f) for f in fields), "Use 1 through 32 distinct extraction fields")
    require(isinstance(angles, list) and 1 <= len(angles) <= 12, "Use 1 through 12 research angles")
    for row in angles:
        require(isinstance(row, dict) and set(row) == {"id", "query"}, "Malformed research angle")
        name(row["id"])
        bounded_text(row["query"], 1000)
    require(len({x["id"] for x in angles}) == len(angles), "Repeated angle ID")
    require(isinstance(priorities, list) and len(priorities) <= 8, "Too many source priorities")
    for value in priorities:
        bounded_text(value, 64)
    require(bias in {"MEDIUM", "HIGH"}, "Unsupported recall bias")
    value = {"schema": "research-question-plan/v1", "ok": True, "status": "planned", "query": query,
             "extraction_schema": fields, "angles": angles, "source_priorities": priorities, "recall_bias": bias,
             "planner": "main_agent", "authority": "untrusted_source_evidence"}
    require(len(wire(value)) <= PLAN_BYTES, "Research question plan exceeds 32 KiB")
    return value


def load_plan(store, artifact_id, identity, deadline=None):
    check_deadline(deadline)
    record = store.get(artifact_id)
    require(record["action"] == "plan" and record.get("identity_sha256") == identity, "Question plan/project identity differs")
    value = record["payload"]
    require(value == plan(value), "Question plan fields differ from the planning contract")
    return value


def angle(plan_value, angle_id):
    rows = [x for x in plan_value["angles"] if x["id"] == angle_id]
    require(len(rows) == 1, "Unknown research angle")
    return rows[0]


def search_binding(store, request, identity, deadline=None):
    key = request.get("research_plan_id")
    value = load_plan(store, key, identity, deadline)
    row = angle(value, request.get("angle_id"))
    require(request.get("query") == row["query"], "Search query differs from its planned angle")
    return {"research_plan_id": key, "angle_id": row["id"], "query": row["query"]}


def retrieval_plan(store, request, identity, deadline=None):
    key = request.get("research_plan_id")
    value = load_plan(store, key, identity, deadline)
    rows = request.get("requests")
    require(isinstance(rows, list) and 1 <= len(rows) <= 128, "Declare 1 through 128 retrieval requests")
    require(len(wire(rows)) <= MANIFEST_BYTES, "Requested retrieval manifest exceeds 64 KiB")
    for row in rows:
        check_deadline(deadline)
        require(isinstance(row, dict) and {"id", "url", "angle_id"} <= set(row)
                and not set(row) - {"id", "url", "angle_id", "search_artifact_id", "hit_index"}, "Malformed retrieval request")
        name(row["id"])
        angle(value, row["angle_id"])
        bounded_text(row["url"], 4096)
        _public_url(row["url"])  # Syntax/public-literal check only; no DNS/network.
        if "search_artifact_id" in row or "hit_index" in row:
            record = store.get(row.get("search_artifact_id"))
            require(record["action"] == "search" and record.get("identity_sha256") == identity
                    and record.get("research_binding") == {"research_plan_id": key, "angle_id": row["angle_id"],
                                                           "query": angle(value, row["angle_id"])["query"]},
                    "Search provenance differs from the original question/angle")
            hits, index = record["payload"].get("hits"), row.get("hit_index")
            require(isinstance(hits, list) and type(index) is int and 0 <= index < len(hits)
                    and hits[index].get("url") == row["url"], "Requested URL differs from the exact cached search hit")
    require(len({x["id"] for x in rows}) == len(rows), "Repeated retrieval request ID")
    result = {"schema": "research-retrieval-plan/v1", "ok": True, "status": "planned",
              "research_plan_id": key, "requests": rows, "coverage": "this explicit requested manifest only"}
    require(len(wire(result)) <= MANIFEST_BYTES, "Requested retrieval manifest exceeds 64 KiB")
    return result


def load_retrieval(store, key, identity, deadline=None):
    check_deadline(deadline)
    record = store.get(key)
    require(record["action"] == "retrieval_plan" and record.get("identity_sha256") == identity, "Retrieval plan/project identity differs")
    value = record["payload"]
    require(value == retrieval_plan(store, value, identity, deadline), "Retrieval manifest fields differ")
    return value


def acquisition_binding(store, request, identity, deadline=None):
    if request["action"] == "search":
        require(not {"retrieval_plan_id", "request_id"} & set(request), "Search uses question/angle binding, not a retrieval request")
        return search_binding(store, request, identity, deadline)
    key = request.get("retrieval_plan_id")
    manifest = load_retrieval(store, key, identity, deadline)
    return request_binding(manifest, key, request)


def request_binding(manifest, key, request):
    """Pure check against this operation's already validated immutable manifest."""
    require(request.get("research_plan_id", manifest["research_plan_id"]) == manifest["research_plan_id"], "Retrieval question differs")
    rows = [x for x in manifest["requests"] if x["id"] == request.get("request_id")]
    require(len(rows) == 1 and request.get("url") == rows[0]["url"], "Retrieval URL/request differs from the declared manifest")
    require("angle_id" not in request, "Retrieval angle comes from the declared request")
    return {"research_plan_id": manifest["research_plan_id"], "retrieval_plan_id": key,
            "request_id": rows[0]["id"], "angle_id": rows[0]["angle_id"], "url": rows[0]["url"]}


def mining_intent(store, request, identity, deadline=None):
    manifest_id, key = request.get("retrieval_plan_id"), request.get("research_plan_id")
    manifest = load_retrieval(store, manifest_id, identity, deadline)
    require(manifest["research_plan_id"] == key, "Mining question/retrieval plan differs")
    value = load_plan(store, key, identity, deadline)
    for field in ("query", "extraction_schema", "recall_bias"):
        require(field not in request or request[field] == value[field], "Mining intent differs from the original question/schema/recall")
    bindings = []
    for artifact_id in request.get("artifact_ids", []):
        check_deadline(deadline)
        record = store.get(artifact_id)
        binding = record.get("research_binding")
        require(isinstance(binding, dict) and binding.get("retrieval_plan_id") == manifest_id
                and record.get("identity_sha256") == identity, "Mining source is not bound to this requested manifest")
        require(record["action"] in {"fetch", "render"}, "Mining requires fetched/rendered source data")
        expected = request_binding(manifest, manifest_id, {k: v for k, v in binding.items() if k != "angle_id"})
        require(binding == expected, "Mining source/request binding differs")
        bindings.append({"artifact_id": artifact_id, **binding})
    return value, {"research_plan_id": key, "retrieval_plan_id": manifest_id, "sources": bindings}


def requested_score(store, request, identity, deadline):
    """Validate every supplied outcome, then score; presence alone is no coverage."""
    from harness import research_consensus as consensus
    key, manifest_id = request.get("research_plan_id"), request.get("retrieval_plan_id")
    value, manifest = load_plan(store, key, identity, deadline), load_retrieval(store, manifest_id, identity, deadline)
    require(manifest["research_plan_id"] == key, "Consensus question/retrieval plan differs")
    for field in ("query", "extraction_schema"):
        require(field not in request or request[field] == value[field], "Consensus question/schema differs")
    ids = request.get("artifact_ids", [])
    acquisitions = request.get("acquisition_artifact_ids", [])
    fulfillments, search_fulfillments = request.get("fulfillments", []), request.get("search_fulfillments", [])
    require(isinstance(fulfillments, list) and len(fulfillments) <= 128 and all(isinstance(x, dict)
            and set(x) == {"request_id", "acquisition_artifact_id", "mining_artifact_id"} for x in fulfillments), "Invalid requested fulfillment choices")
    require(isinstance(search_fulfillments, list) and len(search_fulfillments) <= 12 and all(isinstance(x, dict)
            and set(x) == {"angle_id", "artifact_id"} for x in search_fulfillments), "Invalid search fulfillment choices")
    require(all(x["request_id"] in {r["id"] for r in manifest["requests"]} for x in fulfillments)
            and len({x["request_id"] for x in fulfillments}) == len(fulfillments), "Unknown or repeated request fulfillment")
    require(all(x["angle_id"] in {r["id"] for r in value["angles"]} for x in search_fulfillments)
            and len({x["angle_id"] for x in search_fulfillments}) == len(search_fulfillments), "Unknown or repeated search fulfillment")
    require(isinstance(ids, list) and len(ids) <= 32 and len(set(ids)) == len(ids), "Use up to 32 distinct mining results")
    require(isinstance(acquisitions, list) and len(acquisitions) <= MAX_ACQUISITIONS
            and len(set(acquisitions)) == len(acquisitions), "Use at most 268 distinct acquisition outcomes")
    require({row["search_artifact_id"] for row in manifest["requests"] if "search_artifact_id" in row} <= set(acquisitions),
            "Supply every requested URL's bound search outcome")
    total = 0
    outcomes, searches, mines = {}, [], {}
    for artifact_id in acquisitions:
        check_deadline(deadline)
        record = store.get(artifact_id)
        total += len(wire(record))
        require(total <= store.maximum, "Acquisition coverage exceeds the 32 MiB artifact byte budget")
        require(record.get("identity_sha256") == identity and record["action"] in {"search", "fetch", "render"}, "Invalid acquisition/project outcome")
        binding = record.get("research_binding")
        require(isinstance(binding, dict) and binding.get("research_plan_id") == key, "Acquisition is not bound to the original question")
        expected = ({"research_plan_id": key, "angle_id": binding.get("angle_id"),
                     "query": angle(value, binding.get("angle_id"))["query"]} if record["action"] == "search" else
                    request_binding(manifest, manifest_id, {k: v for k, v in binding.items() if k != "angle_id"}))
        require(binding == expected, "Acquisition/request binding differs")
        payload = record["payload"]
        require(type(payload.get("ok")) is bool and isinstance(payload.get("status"), str), "Malformed acquisition health")
        source_complete = (payload.get("requested_source_complete") is True if record["action"] == "fetch" else
                           payload.get("document", {}).get("truncated") is False and payload.get("document", {}).get("offset") == 0)
        row = {"artifact_id": artifact_id, "action": record["action"], "status": payload["status"], "ok": payload["ok"],
               "source_complete": source_complete, "content_scope": payload.get("content_scope", "captured_browser_document"),
               "reason": str(payload.get("reason") or "")[:500]}
        if record["action"] == "search":
            searches.append({**row, "angle_id": binding["angle_id"]})
        else:
            require(binding["retrieval_plan_id"] == manifest_id, "Acquisition belongs to another requested manifest")
            outcomes.setdefault(binding["request_id"], []).append(row)
    # The scorer validates each complete source/prompt/schema/health chain once.
    # Reuse its validated input/claim projection, never a caller-supplied cache.
    result = consensus.score(store, ids, identity, query=value["query"], extraction_schema=value["extraction_schema"], deadline=deadline) if ids else {
        "ok": False, "status": "all_failed", "complete": False, "consensus_established": False, "coverage_complete": False,
        "query": value["query"], "extraction_schema": value["extraction_schema"], "clusters": [], "inputs": [], "input_claims": 0}
    for entry in result["inputs"]:
        check_deadline(deadline)
        saved = store.get(entry["plan_artifact_id"])
        spec = saved["payload"]["spec"]
        binding = spec.get("research_binding")
        require(isinstance(binding, dict) and binding.get("research_plan_id") == key
                and binding.get("retrieval_plan_id") == manifest_id, "Mining result is not bound to the requested plan")
        for source in binding["sources"]:
            require(source["artifact_id"] in acquisitions, "Supply every mining source acquisition outcome")
            window = next(x for x in spec["sources"] if x["artifact_id"] == source["artifact_id"])
            mines.setdefault(source["request_id"], []).append({"artifact_id": entry["artifact_id"],
                "source_artifact_id": source["artifact_id"], "status": entry["status"], "healthy": entry["operationally_healthy"],
                "analysis_scope": {k: window[k] for k in ("content_scope", "input_chars", "source_chars", "input_truncated")},
                "claims": sum(x["artifact_id"] == source["artifact_id"] and x["mining_artifact_id"] == entry["artifact_id"]
                              for x in result["claim_rows"])})
    rows = []
    for requested in manifest["requests"]:
        check_deadline(deadline)
        attempts, analysis = outcomes.get(requested["id"], []), mines.get(requested["id"], [])
        choice = next((x for x in fulfillments if x["request_id"] == requested["id"]), None)
        eligible = [{"request_id": requested["id"], "acquisition_artifact_id": m["source_artifact_id"], "mining_artifact_id": m["artifact_id"]}
                    for m in analysis if m["healthy"] and any(x["artifact_id"] == m["source_artifact_id"] and x["ok"] and x["source_complete"] for x in attempts)]
        selection = "explicit" if choice else "unique_eligible" if len(eligible) == 1 else "ambiguous" if eligible else "no_eligible"
        if choice is None and len(eligible) == 1:
            choice = eligible[0]
        chosen = next((x for x in attempts if choice and x["artifact_id"] == choice["acquisition_artifact_id"]), None)
        proof = next((x for x in analysis if choice and x["artifact_id"] == choice["mining_artifact_id"]
                      and x["source_artifact_id"] == choice["acquisition_artifact_id"]), None)
        require(choice is None or chosen is not None and proof is not None, "Fulfillment must select supplied bound acquisition and matching mining proof")
        status = ("unattempted" if not attempts else "acquisition_failed" if not any(x["ok"] for x in attempts)
                  else "partial_acquisition" if not any(x["ok"] and x["source_complete"] for x in attempts)
                  else "unmined" if not analysis else "mine_failed" if not any(x["healthy"] for x in analysis)
                  else "ambiguous_fulfillment" if len(eligible) > 1 else "fulfillment_not_selected")
        if chosen is not None:
            status = ("acquisition_failed" if not chosen["ok"] else "partial_acquisition" if not chosen["source_complete"]
                      else "mine_failed" if not proof["healthy"] else "scored" if proof["claims"] else "healthy_no_relevance")
        rows.append({**requested, "status": status, "fulfillment": choice, "selection": selection,
                     "analysis_scope": proof["analysis_scope"] if proof is not None else None,
                     "acquisitions": attempts, "mining": analysis})
    complete = all(x["status"] in {"scored", "healthy_no_relevance"} for x in rows)
    angle_rows = []
    for a in value["angles"]:
        attempts = [x for x in searches if x["angle_id"] == a["id"]]
        choice = next((x for x in search_fulfillments if x["angle_id"] == a["id"]), None)
        eligible = [x for x in attempts if x["ok"]]
        selection = "explicit" if choice else "unique_eligible" if len(eligible) == 1 else "ambiguous" if eligible else "no_eligible"
        if choice is None and len(eligible) == 1:
            choice = {"angle_id": a["id"], "artifact_id": eligible[0]["artifact_id"]}
        selected = next((x for x in attempts if choice and x["artifact_id"] == choice["artifact_id"]), None)
        require(choice is None or selected is not None, "Search fulfillment must select a supplied bound outcome")
        angle_rows.append({"angle_id": a["id"], "outcomes": attempts, "fulfillment": choice, "selection": selection,
                           "fulfilled": selected is not None and selected["ok"]})
    complete = complete and all(x["fulfilled"] for x in angle_rows)
    result["requested_coverage"] = {"research_plan_id": key, "retrieval_plan_id": manifest_id,
        "requests": rows, "angles": angle_rows, "search_outcomes": searches, "complete": complete,
        "scope": "complete declared request/window accounting with uniquely eligible or explicit fulfillment; analysis may be prefix-truncated. Audit includes supplied outcomes only, not every ever-issued attempt, whole-page/web analysis or semantic truth"}
    result["coverage_complete"] = complete
    result["supplied_mining_status"] = result["status"]
    if complete:
        relevant = any(x["status"] == "scored" for x in rows)
        result.update(ok=relevant, complete=relevant, status="scored" if relevant else "no_relevant_claims")
    else:
        result.update(ok=False, complete=False, status="incomplete_requested_coverage")
    result["run_identity_sha256"] = digest(wire({"consensus": result.get("run_identity_sha256"), "plan": key,
        "retrieval_plan": manifest_id, "mining": ids, "acquisitions": acquisitions,
        "fulfillments": fulfillments, "search_fulfillments": search_fulfillments}))
    require(len(wire(result)) <= store.maximum, "Requested coverage/result exceeds the artifact byte budget")
    check_deadline(deadline)
    return result
