"""Source/health/storage controls; no model, provider, browser or private data."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import research_mining as m
from harness import research_runtime as r


class MiningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.project = {"project_id": "synthetic", "board_id": "project:synthetic", "canonical_root": str(self.root)}
        self.store = r.ArtifactStore(self.root / "state", self.project)
        self.text = "Synthetic source. The orchard has seven trees. Unicode 漢字🙂."
        self.key = self.source(self.text)
        self.request = {"query": "How many trees?", "artifact_ids": [self.key], "extraction_schema": ["count"]}
        self.model = {"provider": "local", "id": "synthetic", "transport_sha256": "0" * 64}

    def tearDown(self):
        self.temp.cleanup()

    def source(self, text, ok=True):
        return self.store.put({"schema": "project-research-artifact/v1", "project": self.project,
                               "action": "fetch", "payload": {"ok": ok, "status": "ok" if ok else "timeout",
                               "response": {"final_url": "https://example.org/orchard", "cleaned_text_full": text}}})

    def plan(self, **values):
        return m.prepare({**self.request, **values}, self.store, self.model, r.text_view, r.wire, r.digest)

    def response(self, **values):
        claim = {"field": "count", "claim": "The orchard has seven trees.", "relevance": 3,
                 "confidence": 0.9, "evidence_span": "The orchard has seven trees."}
        claim.update(values)
        return {"source": 0, "shard": 0, "status": "ok", "text": json.dumps({"claims": [claim]})}

    def test_exact_span_offsets_and_source_hashes(self):
        plan = self.plan()
        result = m.finish(plan, [self.response()])
        self.assertTrue(result["complete"])
        self.assertEqual(result["seen_source_artifacts"], [self.key])
        claim = result["claims"][0]
        self.assertEqual(self.text[claim["evidence_start"]:claim["evidence_end"]], claim["evidence_span"])
        self.assertEqual(claim["source_text_sha256"], r.digest(self.text.encode()))
        self.assertEqual(claim["artifact_id"], self.key)

    def test_bad_schema_numeric_and_off_source_quotes_are_failed_shards(self):
        for response in (self.response(field="invented"), self.response(relevance=True),
                         self.response(confidence=float("nan")), self.response(confidence=2),
                         self.response(evidence_span="Not in the source"), self.response(claim=[]),
                         {"source": 0, "shard": 0, "status": "ok", "text": "{}"},
                         {"source": 0, "shard": 0, "status": "ok", "text": "not JSON"}):
            with self.subTest(response=response):
                result = m.finish(self.plan(), [response])
                self.assertEqual(result["status"], "all_failed")
                self.assertEqual(result["failure_ledger"][0]["status"], "malformed")
                self.assertEqual(result["seen_source_artifacts"], [])

    def test_background_and_valid_empty_are_distinct_from_failed_analysis(self):
        for response in (self.response(relevance=1), {"source": 0, "shard": 0, "status": "ok", "text": '{"claims":[]}'}):
            result = m.finish(self.plan(), [response])
            self.assertEqual(result["status"], "zero_claims")
            self.assertEqual(result["analysed_rate"], 1)
            self.assertFalse(result["ok"])
            self.assertEqual(result["seen_source_artifacts"], [])
        high = m.finish(self.plan(recall_bias="HIGH"), [self.response(relevance=1)])
        self.assertTrue(high["ok"])

    def test_shards_and_low_yield_are_not_success_or_seen(self):
        fields = ["count"] + [f"field{i}" for i in range(24)]
        plan = self.plan(extraction_schema=fields)
        self.assertEqual(list(map(len, plan["shards"])), [8, 8, 8, 1])
        result = m.finish(plan, [self.response()])
        self.assertEqual(result["status"], "low_yield")
        self.assertEqual(result["analysed_rate"], 0.25)
        self.assertEqual(sum(row["status"] == "not_attempted" for row in result["failure_ledger"]), 3)
        self.assertEqual(result["failure_ledger"][-1]["status"], "low_yield")
        self.assertEqual(result["seen_source_artifacts"], [])
        partial = m.finish(self.plan(extraction_schema=fields[:9]), [self.response()])
        self.assertEqual(partial["status"], "partial_failure")
        self.assertEqual(partial["seen_source_artifacts"], [])

    def test_failed_cancelled_deadline_and_length_never_seen(self):
        for status in ("model_error", "cancelled", "deadline", "length", "model_changed"):
            result = m.finish(self.plan(), [{"source": 0, "shard": 0, "status": status, "text": ""}])
            self.assertEqual(result["status"], "all_failed")
            self.assertEqual(result["failure_ledger"][0]["status"], status)
            self.assertEqual(result["seen_source_artifacts"], [])
        for flags, expected in (({"cancelled": True}, "cancelled"), ({"timed_out": True}, "deadline")):
            result = m.finish(self.plan(), [self.response()], **flags)
            self.assertEqual(result["status"], expected)
            self.assertFalse(result["complete"])
            self.assertEqual(result["seen_source_artifacts"], [])

    def test_model_question_schema_scope_and_source_change_identity(self):
        baseline = self.plan()["run_identity_sha256"]
        for values in ({"query": "Different topic"}, {"recall_bias": "HIGH"}, {"extraction_schema": ["count", "method"]},
                       {"mine_timeout_seconds": 900}, {"artifact_ids": [self.source(self.text + " New evidence.")]}):
            self.assertNotEqual(self.plan(**values)["run_identity_sha256"], baseline)
        self.model["id"] = "other-model"
        self.assertNotEqual(self.plan()["run_identity_sha256"], baseline)

    def test_only_actual_input_window_can_support_quote_and_partial_is_explicit(self):
        text = "x" * m.PAGE_CHARS + self.text
        plan = self.plan(artifact_ids=[self.source(text)])
        self.assertTrue(plan["sources"][0]["input_truncated"])
        result = m.finish(plan, [self.response()])
        self.assertEqual(result["status"], "all_failed")
        self.assertEqual(plan["sources"][0]["source_text_sha256"], r.digest(text.encode()))

    def test_invalid_inputs_duplicate_responses_and_failed_source_refuse(self):
        for values in ({"query": ""}, {"artifact_ids": []}, {"artifact_ids": [self.key, self.key]},
                       {"artifact_ids": [self.source(self.text, False)]}, {"extraction_schema": []},
                       {"extraction_schema": ["count", "count"]}, {"recall_bias": "UNKNOWN"}):
            with self.assertRaises((ValueError, TypeError)):
                self.plan(**values)
        with self.assertRaisesRegex(ValueError, "response count"):
            m.finish(self.plan(), [self.response(), self.response()])


class MiningRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.project = self.home / "project"
        self.project.mkdir()
        source = Path(__file__).resolve().parents[1] / "adapters/pi/project-workflow/project_identity.py"
        spec = importlib.util.spec_from_file_location("mining_fixture_identity", source)
        identity = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(identity)
        state = self.home / "state/projects"
        with patch.dict(os.environ, {"PI_PROJECT_STATE_BASE": str(state)}):
            self.identity, _ = identity.initialize_identity(self.project)
        self.selection = {"project": {"root": str(self.project), "projectId": self.identity["project_id"], "boardId": self.identity["board_id"]}, "task": None}
        self.runtime = r.ResearchRuntime.__new__(r.ResearchRuntime)
        self.runtime.home, self.runtime.identity, self.runtime.env = self.home, identity, {"PI_PROJECT_STATE_BASE": str(state)}
        self.runtime.config = {"model": "synthetic", "base_url": "http://127.0.0.1:1/v1"}
        model = {"id": "synthetic", "contextWindow": 32768, "maxTokens": 4096, "reasoning": False}
        (self.home / "agent").mkdir()
        self.models = self.home / "agent/models.json"
        self.models.write_bytes(r.wire({"providers": {"local": {"baseUrl": self.runtime.config["base_url"], "api": "openai-completions", "models": [model]}}}))
        self.model = {"provider": "local", "id": "synthetic", "api": "openai-completions", "base_url": self.runtime.config["base_url"],
                      "context_window": 32768, "max_tokens": 4096, "reasoning": False, "compat_sha256": r.digest(r.wire({})),
                      "headers_sha256": r.digest(r.wire({})),
                      "models_sha256": r.digest(self.models.read_bytes()), "output_tokens": 1000}
        binding = {"project_id": self.identity["project_id"], "board_id": self.identity["board_id"], "canonical_root": str(self.project)}
        self.store = r.ArtifactStore(self.identity["state_root"], binding)
        self.key = self.store.put({"schema": "project-research-artifact/v1", "project": binding, "action": "fetch",
                                   "payload": {"ok": True, "status": "ok", "response": {"final_url": "https://example.org/", "cleaned_text_full": "The orchard has seven trees."}}})
        self.common = {"selection": self.selection, "session_id": "synthetic", "model_binding": self.model}
        self.request = {"action": "mine_prepare", **self.common, "query": "Trees?", "extraction_schema": ["count"], "artifact_ids": [self.key]}

    def tearDown(self):
        self.temp.cleanup()

    def finish(self, plan, **values):
        row = {"source": 0, "shard": 0, "status": "ok", "text": json.dumps({"claims": [{"field": "count", "claim": "Seven trees.", "relevance": 3, "confidence": 0.9, "evidence_span": "seven trees"}]})}
        return self.runtime.execute({"action": "mine_finish", **self.common, "plan_artifact_id": plan["plan_artifact_id"], "responses": [row], **values})

    def test_dispatch_publication_cached_read_and_explicit_successful_resume(self):
        plan = self.runtime.execute(self.request)
        result = self.finish(plan)
        self.assertTrue(result["complete"])
        self.assertLessEqual(len(r.wire(result)), r.MODEL_BYTES)
        artifact = self.store.get(result["artifact_id"])
        self.assertEqual(artifact["payload"]["seen_source_artifacts"], [self.key])
        cached = self.runtime.execute({"action": "read", "selection": self.selection, "artifact_id": result["artifact_id"]})
        self.assertIn("Seven trees", cached["text"])
        resume = self.runtime.execute({**self.request, "resume_artifact_id": result["artifact_id"]})
        self.assertEqual(resume["cached_result"]["artifact_id"], result["artifact_id"])
        with self.assertRaisesRegex(r.ResearchError, "unchanged mining"):
            self.runtime.execute({**self.request, "query": "Other topic", "resume_artifact_id": result["artifact_id"]})
        metadata = r.projection(self.store.get(plan["plan_artifact_id"]), plan["plan_artifact_id"], view="metadata")
        self.assertNotIn("The orchard has seven trees.", metadata["text"])
        self.assertNotIn("user_prompt", json.loads(metadata["text"])["payload"]["sources"][0])

    def test_cancelled_failure_receipt_is_not_resume_authority(self):
        result = self.finish(self.runtime.execute(self.request), cancelled=True)
        self.assertFalse(result["complete"])
        self.assertEqual(result["status"], "cancelled")
        with self.assertRaisesRegex(r.ResearchError, "successful unchanged"):
            self.runtime.execute({**self.request, "resume_artifact_id": result["artifact_id"]})

    def test_model_and_identity_drift_refuse_before_publication(self):
        plan = self.runtime.execute(self.request)
        count = len(list(self.store.directory.iterdir()))
        self.models.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(r.ResearchError, "model bytes changed"):
            self.finish(plan)
        self.assertEqual(len(list(self.store.directory.iterdir())), count)
        with self.assertRaisesRegex(r.ResearchError, "actual configured local"):
            self.runtime.execute({**self.request, "model_binding": {**self.model, "provider": "foreign"}})

    def test_in_memory_routing_headers_are_not_accepted_as_pinned_home_config(self):
        with self.assertRaisesRegex(r.ResearchError, "transport changed"):
            self.runtime.execute({**self.request, "model_binding": {**self.model, "headers_sha256": r.digest(r.wire({"x-route": "synthetic"}))}})

    def test_foreign_home_model_endpoint_cannot_enable_cloud_mining(self):
        self.runtime.config["base_url"] = "https://203.0.113.1/v1"
        with self.assertRaisesRegex(ValueError, "owner-selected local hardware"):
            self.runtime.execute({**self.request, "model_binding": {**self.model, "base_url": self.runtime.config["base_url"]}})


if __name__ == "__main__":
    unittest.main()
