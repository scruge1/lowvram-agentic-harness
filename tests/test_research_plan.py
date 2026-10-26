"""Immutable requested-set chains; synthetic native-shaped producer data only."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from harness import research_mining as mining
from harness import research_plan as plan
from harness import research_runtime as runtime


class PlannedCorpus:
    def __init__(self, root, binding=None, identity="1" * 64):
        self.binding = binding or {"project_id": "synthetic", "board_id": "project:synthetic", "canonical_root": str(root)}
        self.identity = identity
        self.store = runtime.ArtifactStore(root, self.binding)
        self.input = {"query": "How does the method work?", "extraction_schema": ["method"],
                      "angles": [{"id": "mechanism", "query": "method mechanism documentation"}]}
        self.plan = self.put("plan", plan.plan(self.input))
        self.acquisitions = []

    def put(self, action, payload, binding=None):
        record = {"schema": "project-research-artifact/v1", "project": self.binding,
                  "identity_sha256": self.identity, "action": action, "payload": payload}
        if binding is not None:
            record["research_binding"] = binding
        return self.store.put(record)

    def search(self, urls, ok=True):
        bound = plan.search_binding(self.store, {"research_plan_id": self.plan, "angle_id": "mechanism",
                                                 "query": self.input["angles"][0]["query"]}, self.identity)
        key = self.put("search", {"ok": ok, "status": "ok" if ok else "network_error",
                                  "hits": [{"url": u} for u in urls]}, bound)
        if key not in self.acquisitions:
            self.acquisitions.append(key)
        return key

    def manifest(self, count=1, search=None):
        rows = [{"id": "page" + str(n), "angle_id": "mechanism", "url": f"https://example.org/page-{n}"} for n in range(count)]
        if search:
            rows[0].update(search_artifact_id=search, hit_index=0)
        self.manifest_id = self.put("retrieval_plan", plan.retrieval_plan(self.store,
            {"research_plan_id": self.plan, "requests": rows}, self.identity))
        return self.manifest_id

    def fetch(self, n=0, *, ok=True, complete=True):
        url = f"https://example.org/page-{n}"
        bound = plan.acquisition_binding(self.store, {"action": "fetch", "retrieval_plan_id": self.manifest_id,
            "request_id": "page" + str(n), "url": url}, self.identity)
        key = self.put("fetch", {"ok": ok, "status": "ok" if ok else "network_error", "requested_url": url,
            "selected_url": url, "text": "The method uses a sustained hypothesis experiment execution revision loop.",
            "content_scope": "full_extraction" if complete else "abstract", "requested_source_complete": complete}, bound)
        self.acquisitions.append(key)
        return key

    def mine(self, sources, *, empty=False, failed=False):
        request = {"research_plan_id": self.plan, "retrieval_plan_id": self.manifest_id,
                   "identity_sha256": self.identity, "artifact_ids": sources}
        prepared = mining.prepare(request, self.store, {"provider": "local", "id": "synthetic-no-inference"},
                                  runtime.text_view, runtime.wire, runtime.digest)
        key = self.put("mine_plan", {"ok": True, "status": "prepared", **prepared})
        claim = {"field": "method", "claim": "The method uses a sustained hypothesis experiment execution revision loop.",
                 "relevance": 3, "confidence": 1.0, "evidence_span": "sustained hypothesis experiment execution revision loop"}
        rows = [{"source": i, "shard": 0, "status": "model_error" if failed else "ok",
                 "text": "" if failed else json.dumps({"claims": [] if empty else [claim]})} for i in range(len(sources))]
        result = mining.finish(prepared, rows)
        result["plan_artifact_id"] = key
        return self.put("mine", result)

    def score(self, mines=None, acquisitions=None, **extra):
        return plan.requested_score(self.store, {"research_plan_id": self.plan, "retrieval_plan_id": self.manifest_id,
            "artifact_ids": mines or [], "acquisition_artifact_ids": self.acquisitions if acquisitions is None else acquisitions,
            **extra}, self.identity, time.monotonic() + 30)


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.c = PlannedCorpus(Path(self.temp.name).resolve())

    def tearDown(self):
        self.temp.cleanup()

    def ready(self, count=1):
        self.c.search(["https://example.org/page-0"])
        self.c.manifest(count)
        return [self.c.fetch(n) for n in range(count)]

    def test_main_agent_plan_is_immutable_data_not_policy_or_permission(self):
        value = plan.load_plan(self.c.store, self.c.plan, self.c.identity)
        self.assertEqual(value["planner"], "main_agent")
        self.assertEqual(value["authority"], "untrusted_source_evidence")
        self.assertNotIn("authority_candidates", value)
        self.assertEqual(self.c.put("plan", value), self.c.plan)
        self.assertIn("main_agent_plan_data_not_permission", runtime.projection(self.c.store.get(self.c.plan), self.c.plan)["content_scope"])

    def test_text_count_and_serialized_utf8_limits_are_explicit(self):
        for change in ({"angles": []}, {"angles": self.c.input["angles"] * 13}, {"query": "x" * 1001},
                       {"extraction_schema": ["a"] * 2}, {"source_priorities": ["x"] * 9}):
            with self.assertRaises(ValueError):
                plan.plan({**self.c.input, **change})
        huge = {**self.c.input, "query": "漢" * 1000,
                "angles": [{"id": "angle" + str(n), "query": "漢" * 1000} for n in range(12)]}
        with self.assertRaisesRegex(ValueError, "32 KiB"):
            plan.plan(huge)
        self.c.manifest()
        rows = [{"id": "page" + str(n), "angle_id": "mechanism", "url": "https://example.org/" + "a" * 4000} for n in range(128)]
        with self.assertRaisesRegex(ValueError, "64 KiB"):
            plan.retrieval_plan(self.c.store, {"research_plan_id": self.c.plan, "requests": rows}, self.c.identity)

    def test_search_query_angle_and_exact_hit_url_cannot_be_substituted(self):
        key = self.c.search(["https://example.org/page-0"])
        self.c.manifest(search=key)
        value = self.c.store.get(self.c.manifest_id)["payload"]
        bad = copy.deepcopy(value)
        bad["requests"][0]["url"] += "?different=true"
        with self.assertRaisesRegex(ValueError, "exact cached search hit"):
            plan.retrieval_plan(self.c.store, bad, self.c.identity)
        with self.assertRaisesRegex(ValueError, "query differs"):
            plan.search_binding(self.c.store, {"research_plan_id": self.c.plan, "angle_id": "mechanism", "query": "other"}, self.c.identity)
        with self.assertRaisesRegex(ValueError, "URL/request differs"):
            plan.acquisition_binding(self.c.store, {"action": "fetch", "retrieval_plan_id": self.c.manifest_id,
                "request_id": "page0", "url": "https://example.org/unrequested"}, self.c.identity)

    def test_success_requires_healthy_bound_mining_not_artifact_presence(self):
        sources = self.ready()
        result = self.c.score()
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["requested_coverage"]["requests"][0]["status"], "unmined")
        key = self.c.mine(sources)
        result = self.c.score([key])
        self.assertTrue(result["ok"])
        self.assertTrue(result["coverage_complete"])
        self.assertFalse(result["consensus_established"])
        self.assertEqual(result["requested_coverage"]["requests"][0]["mining"][0]["artifact_id"], key)

    def test_failed_and_unattempted_requests_are_retained_beside_success(self):
        self.c.search(["https://example.org/page-0"])
        self.c.manifest(3)
        good = self.c.fetch()
        failed = self.c.fetch(1, ok=False)
        result = self.c.score([self.c.mine([good])])
        self.assertFalse(result["ok"])
        rows = result["requested_coverage"]["requests"]
        self.assertEqual([x["status"] for x in rows], ["scored", "acquisition_failed", "unattempted"])
        self.assertEqual(rows[1]["acquisitions"][0]["artifact_id"], failed)

    def test_partial_abstract_or_browser_capture_does_not_complete_requested_source(self):
        self.c.search(["https://example.org/page-0"])
        self.c.manifest()
        partial = self.c.fetch(complete=False)
        result = self.c.score([self.c.mine([partial])])
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["requested_coverage"]["requests"][0]["status"], "partial_acquisition")

    def test_model_failure_and_healthy_no_relevance_are_distinct(self):
        source = self.ready()[0]
        bad = self.c.score([self.c.mine([source], failed=True)])
        self.assertEqual(bad["requested_coverage"]["requests"][0]["status"], "mine_failed")
        empty = self.c.score([self.c.mine([source], empty=True)])
        self.assertTrue(empty["coverage_complete"])
        self.assertFalse(empty["ok"])
        self.assertEqual(empty["status"], "no_relevant_claims")
        self.assertEqual(empty["requested_coverage"]["requests"][0]["status"], "healthy_no_relevance")

    def test_failed_or_missing_angle_queries_cannot_disappear(self):
        self.c.manifest()
        source = self.c.fetch()
        key = self.c.mine([source])
        self.assertFalse(self.c.score([key])["coverage_complete"])
        failed = self.c.search([], ok=False)
        result = self.c.score([key])
        self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["requested_coverage"]["search_outcomes"][0]["artifact_id"], failed)

    def test_unbound_foreign_or_mixed_intent_and_duplicate_outcomes_refuse(self):
        source = self.ready()[0]
        key = self.c.mine([source])
        with self.assertRaisesRegex(ValueError, "distinct acquisition"):
            self.c.score([key], acquisitions=self.c.acquisitions * 2)
        with self.assertRaisesRegex(ValueError, "question/schema differs"):
            self.c.score([key], query="A different topic")
        with self.assertRaisesRegex(ValueError, "plan/project identity"):
            plan.load_plan(self.c.store, self.c.plan, "2" * 64)
        unbound = self.c.put("fetch", self.c.store.get(source)["payload"])
        with self.assertRaisesRegex(ValueError, "not bound"):
            self.c.score([key], acquisitions=[unbound])
        request = {"research_plan_id": self.c.plan, "retrieval_plan_id": self.c.manifest_id,
                   "artifact_ids": [source], "identity_sha256": self.c.identity, "query": "other"}
        with self.assertRaisesRegex(ValueError, "Mining intent differs"):
            mining.prepare(request, self.c.store, {}, runtime.text_view, runtime.wire, runtime.digest)

    def test_manifest_parent_search_and_explicit_fulfillment_are_required_without_erasing_other_captures(self):
        search = self.c.search(["https://example.org/page-0"])
        self.c.manifest(search=search)
        source = self.c.fetch()
        key = self.c.mine([source])
        with self.assertRaisesRegex(ValueError, "bound search outcome"):
            self.c.score([key], acquisitions=[source])
        newer = self.c.store.get(source)
        newer["payload"]["text"] += " Additional capture."
        self.c.acquisitions.append(self.c.store.put(newer))
        self.assertTrue(self.c.score([key])["coverage_complete"])
        self.assertEqual(len(self.c.score([key])["requested_coverage"]["requests"][0]["acquisitions"]), 2)
        self.assertTrue(self.c.score([key], fulfillments=[])["coverage_complete"])

    def test_failed_fetch_then_complete_render_and_healthy_mine_fulfills_url_with_failure_audit(self):
        self.c.search(["https://example.org/page-0"])
        self.c.manifest()
        failed = self.c.fetch(ok=False)
        source = self.c.store.get(failed)
        source["action"] = "render"
        source["payload"] = {"ok": True, "status": "ok", "page_url": "https://example.org/page-0",
                             "document": {"text": "sustained hypothesis experiment execution revision loop", "truncated": False, "offset": 0}}
        rendered = self.c.store.put(source)
        self.c.acquisitions.append(rendered)
        result = self.c.score([self.c.mine([rendered])])
        self.assertTrue(result["ok"])
        self.assertTrue(result["coverage_complete"])
        row = result["requested_coverage"]["requests"][0]
        self.assertEqual([x["ok"] for x in row["acquisitions"]], [False, True])
        self.assertEqual(row["fulfillment"]["acquisition_artifact_id"], rendered)

    def test_failed_mining_and_failed_search_recovery_keep_original_audit_and_selected_fulfillment(self):
        source = self.ready()[0]
        bad = self.c.mine([source], failed=True)
        failed_search = self.c.search([], ok=False)
        self.c.search(["https://example.org/page-0"])
        good = self.c.mine([source])
        result = self.c.score([bad, good])
        self.assertTrue(result["coverage_complete"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["supplied_mining_status"], "partial_coverage")
        self.assertIn(failed_search, [x["artifact_id"] for x in result["requested_coverage"]["search_outcomes"]])
        self.assertFalse(self.c.score([bad, good], fulfillments=[{"request_id": "page0", "acquisition_artifact_id": source,
                                                                  "mining_artifact_id": bad}])["ok"])

    def test_unique_fulfillment_needs_no_duplicate_id_array_but_ambiguity_requires_override(self):
        source = self.ready()[0]
        first = self.c.mine([source])
        automatic = self.c.score([first], fulfillments=[], search_fulfillments=[])
        self.assertTrue(automatic["ok"])
        self.assertEqual(automatic["requested_coverage"]["requests"][0]["selection"], "unique_eligible")
        changed = self.c.store.get(source)
        changed["payload"]["text"] += " A different complete capture."
        second_source = self.c.store.put(changed)
        self.c.acquisitions.append(second_source)
        second = self.c.mine([second_source])
        held = self.c.score([first, second], fulfillments=[])
        self.assertFalse(held["ok"])
        self.assertEqual(held["requested_coverage"]["requests"][0]["status"], "ambiguous_fulfillment")
        explicit = self.c.score([first, second], fulfillments=[{"request_id": "page0", "acquisition_artifact_id": second_source,
                                                              "mining_artifact_id": second}])
        self.assertTrue(explicit["ok"])
        self.assertEqual(len(explicit["requested_coverage"]["requests"][0]["acquisitions"]), 2)

    def test_complete_accounting_keeps_prefix_analysis_window_explicit(self):
        source = self.ready()[0]
        record = self.c.store.get(source)
        record["payload"]["text"] += " More public source text." * 1200
        larger = self.c.store.put(record)
        self.c.acquisitions = [self.c.acquisitions[0], larger]
        result = self.c.score([self.c.mine([larger])])
        self.assertTrue(result["coverage_complete"])
        scope = result["requested_coverage"]["requests"][0]["analysis_scope"]
        self.assertTrue(scope["input_truncated"])
        self.assertEqual(scope["input_chars"], mining.PAGE_CHARS)
        self.assertGreater(scope["source_chars"], scope["input_chars"])
        self.assertIn("not every ever-issued attempt, whole-page/web analysis or semantic truth", result["requested_coverage"]["scope"])

    def test_eighty_eight_requested_sources_combine_twenty_two_existing_mining_batches(self):
        sources = self.ready(88)
        ids = [self.c.mine(sources[n:n + 4]) for n in range(0, len(sources), 4)]
        result = self.c.score(ids, fulfillments=[], search_fulfillments=[])
        self.assertTrue(result["coverage_complete"])
        self.assertEqual(len(result["requested_coverage"]["requests"]), 88)
        self.assertEqual(result["input_claims"], 88)

    def test_deadline_refuses_before_publication_without_marking_seen(self):
        self.ready()
        before = set(self.c.store.directory.iterdir())
        with self.assertRaisesRegex(ValueError, "deadline"):
            plan.requested_score(self.c.store, {"research_plan_id": self.c.plan}, self.c.identity, time.monotonic() - 1)
        self.assertEqual(set(self.c.store.directory.iterdir()), before)


class PlanningRuntimeTests(unittest.TestCase):
    def test_existing_dispatcher_plans_and_reads_with_real_native_project_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder).resolve()
            project = home / "project"
            project.mkdir()
            source = Path(__file__).resolve().parents[1] / "adapters/pi/project-workflow/project_identity.py"
            spec = importlib.util.spec_from_file_location("planning_identity", source)
            identity = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(identity)
            state = home / "state/projects"
            with patch.dict(os.environ, {"PI_PROJECT_STATE_BASE": str(state)}):
                native, _ = identity.initialize_identity(project)
            bound = runtime.ResearchRuntime.__new__(runtime.ResearchRuntime)
            bound.home, bound.identity, bound.env = home, identity, {"PI_PROJECT_STATE_BASE": str(state)}
            selection = {"project": {"root": str(project), "projectId": native["project_id"], "boardId": native["board_id"]}, "task": None}
            request = {"action": "plan", "selection": selection, "query": "Which public method?", "extraction_schema": ["method"],
                       "angles": [{"id": "mechanism", "query": "public method mechanism"}]}
            result = bound.execute(request)
            self.assertTrue(result["ok"])
            self.assertTrue(result["plan_data_only"])
            read = bound.execute({"action": "read", "selection": selection, "artifact_id": result["artifact_id"]})
            self.assertEqual(read["artifact_id"], result["artifact_id"])
            before = set((Path(native["state_root"]) / "research/artifacts").iterdir())
            with self.assertRaisesRegex(ValueError, "Unexpected planning"):
                bound.execute({**request, "api_key": "NOT_A_REAL_KEY"})
            with patch.object(runtime.time, "monotonic", side_effect=[0, 3]):
                with self.assertRaisesRegex(ValueError, "deadline"):
                    bound.execute({**request, "timeout": 2})
            self.assertEqual(set((Path(native["state_root"]) / "research/artifacts").iterdir()), before)
