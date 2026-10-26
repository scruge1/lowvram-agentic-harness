"""Deterministic cached-corpus controls; synthetic producer responses, no model."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from harness import research_consensus as c
from harness import research_mining as m
from harness import research_runtime as r


class Corpus:
    def __init__(self, root, project=None, identity_sha256="1" * 64):
        self.project = project or {"project_id": "synthetic", "board_id": "project:synthetic", "canonical_root": str(root)}
        self.identity_sha256 = identity_sha256
        self.store = r.ArtifactStore(root, self.project)

    def mine(self, url="https://github.com/example/method", *, query="How does the method work?", field="method",
             claim="A sustained hypothesis experiment execution revision loop.", quote="sustained hypothesis experiment execution revision loop",
             body=None, requested_url=None, status="ok", relevance=3, confidence=1.0, partial=False, page_count=1, recall_bias=None):
        sources = []
        for n in range(page_count):
            page = url if page_count == 1 else url.rstrip("/") + f"/page-{n}"
            text = body if body is not None else quote + "\nSource marker: " + page
            sources.append(self.store.put({"schema": "project-research-artifact/v1", "project": self.project, "action": "fetch",
                                           "payload": {"ok": True, "status": "ok", "requested_url": requested_url or page,
                                                       "response": {"final_url": page, "cleaned_text_full": text}}}))
        fields = [field] + ([f"other{i}" for i in range(8)] if partial else [])
        plan = m.prepare({"query": query, "extraction_schema": fields, "artifact_ids": sources,
                          "recall_bias": recall_bias or ("HIGH" if relevance == 1 else "MEDIUM")}, self.store,
                         {"provider": "local", "id": "synthetic-no-inference"}, r.text_view, r.wire, r.digest)
        plan_id = self.store.put({"schema": "project-research-artifact/v1", "project": self.project,
                                  "identity_sha256": self.identity_sha256, "action": "mine_plan",
                                  "payload": {"ok": True, "status": "prepared", **plan}})
        values = [{"field": field, "claim": claim, "relevance": relevance, "confidence": confidence, "evidence_span": quote}] if claim else []
        responses = [{"source": n, "shard": 0, "status": status, "text": json.dumps({"claims": values}) if status == "ok" else ""}
                     for n in range(page_count)]
        payload = m.finish(plan, responses)
        payload["plan_artifact_id"] = plan_id
        return self.store.put({"schema": "project-research-artifact/v1", "project": self.project,
                               "identity_sha256": self.identity_sha256, "action": "mine", "payload": payload})

    def score(self, ids, **values):
        return c.score(self.store, ids, self.identity_sha256, **values)

    def altered(self, key, change):
        value = copy.deepcopy(self.store.get(key))
        change(value)
        return self.store.put(value)


class ConsensusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.corpus = Corpus(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_math_primary_singleton_and_low_authority_controls(self):
        key = self.corpus.mine("https://arxiv.org/html/1234")
        result = self.corpus.score([key])
        self.assertTrue(result["ok"])
        self.assertFalse(result["consensus_established"])
        self.assertEqual(result["clusters"][0]["cluster_score"], 86.11)
        self.assertEqual(result["clusters"][0]["tier"], "CANONICAL")
        seo = [self.corpus.mine(f"https://example{i}.org/page") for i in range(3)]
        other = self.corpus.score(seo)
        self.assertNotEqual(other["clusters"][0]["tier"], "CANONICAL")
        self.assertGreater(result["clusters"][0]["cluster_score"], other["clusters"][0]["cluster_score"])
        claim = {"source_url": "https://arxiv.org/a", "relevance": 3, "confidence": 0.9}
        self.assertLess(c.claim_weight(claim), c.claim_weight({**claim, "evidence_span": "quoted"}))

    def test_two_source_lexical_grouping_records_method_and_no_truth_claim(self):
        ids = [self.corpus.mine("https://github.com/example/method"), self.corpus.mine("https://example.readthedocs.io/method")]
        result = self.corpus.score(ids)
        cluster = result["clusters"][0]
        self.assertEqual(len(result["clusters"]), 1)
        self.assertEqual(cluster["tier"], "CORROBORATED")
        self.assertEqual(cluster["cluster_score"], 71.65)
        self.assertEqual(cluster["domain_coverage_proxy"], 2)
        self.assertIn("lexical", result["cluster_method"])
        self.assertEqual(result["embedding_route"], "not_used_no_qualified_route")
        self.assertFalse(result["consensus_established"])
        self.assertEqual(result["input_claims"], 2)

    def test_duplicate_url_snapshot_and_subdomain_cannot_inflate_scoring(self):
        same_domain = [self.corpus.mine(f"https://part{i}.example.org/page{i}") for i in range(3)]
        result = self.corpus.score(same_domain)
        self.assertEqual(result["clusters"][0]["independent_sources"], 1)
        self.assertNotEqual(result["clusters"][0]["tier"], "CORROBORATED")
        body = "sustained hypothesis experiment execution revision loop"
        copies = [self.corpus.mine(url, body=body) for url in ("https://github.com/a", "https://example.readthedocs.io/b")]
        copied = self.corpus.score(copies)["clusters"][0]
        self.assertEqual(len(copied["claim_indices"]), 2)
        self.assertEqual(copied["scored_claims"], 1)
        self.assertEqual(copied["duplicate_references"], 1)
        with self.assertRaisesRegex(ValueError, "distinct mining"):
            self.corpus.score([copies[0], copies[0]])
        same_url = [self.corpus.mine("https://github.com/a", body=body + suffix) for suffix in (" first", " second")]
        self.assertEqual(self.corpus.score(same_url)["clusters"][0]["scored_claims"], 1)

    def test_original_requested_source_prevents_representation_count_inflation(self):
        ids = [self.corpus.mine(url, requested_url="https://arxiv.org/abs/1234")
               for url in ("https://arxiv.org/html/1234", "https://ar5iv.org/html/1234")]
        result = self.corpus.score(ids)
        self.assertEqual(result["clusters"][0]["scored_claims"], 1)
        self.assertEqual(len(result["clusters"][0]["claim_indices"]), 2)

    def test_anchored_legacy_priors_do_not_trust_unrelated_host_substrings(self):
        for url in ("https://pubmed.evil.example/a", "https://readthedocs.evil.example/a", "https://arxiv.org.evil.example/a"):
            self.assertEqual(c.authority_of(url)[0], 0.1)
        self.assertEqual(c.authority_of("https://pubmed.ncbi.nlm.nih.gov/123")[0], 1)
        self.assertEqual(c.authority_of("https://example.readthedocs.io/a")[0], 0.7)

    def test_numeric_variants_keep_quotes_and_do_not_merge_or_average(self):
        ids = [self.corpus.mine(url, field="memory", claim=f"Memory capacity is {value}.", quote=f"Memory capacity is {value}.")
               for url, value in (("https://arxiv.org/a", "32 GiB"), ("https://openreview.net/b", "64 GiB"))]
        result = self.corpus.score(ids)
        self.assertEqual(len(result["clusters"]), 2)
        values = result["numeric_evidence"][0]
        self.assertEqual(values["status"], "CONTESTED_LITERALS")
        self.assertEqual([v["literal"] for v in values["values"]], ["32 GiB", "64 GiB"])
        self.assertTrue(all(result["claim_rows"][v["claim_indices"][0]]["evidence_span"] for v in values["values"]))
        self.assertIn("no unit conversion", values["comparison"])
        self.assertNotIn("average", values)

    def test_numeric_identifier_suffixes_and_fractional_literals_remain_distinct(self):
        self.assertEqual(c.numeric_literals("HTTP403"), ("403",))
        self.assertEqual(c.numeric_literals(".5 GiB"), (".5 GiB",))
        self.assertNotEqual(c.numeric_literals(".5 GiB"), c.numeric_literals("5 GiB"))
        ids = [self.corpus.mine(url, field="status", claim=f"Service reports HTTP{code} for this request.",
                               quote=f"Service reports HTTP{code} for this request.")
               for url, code in (("https://example.org/a", 403), ("https://example.net/b", 404))]
        self.assertEqual(len(self.corpus.score(ids)["clusters"]), 2)

    def test_empty_allfailed_partial_and_background_are_explicit_not_consensus(self):
        failed = self.corpus.mine(status="model_error")
        result = self.corpus.score([failed])
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "all_failed")
        self.assertEqual(result["inputs"][0]["failure_ledger"], self.corpus.store.get(failed)["payload"]["failure_ledger"])
        empty = self.corpus.mine(claim="")
        self.assertEqual(self.corpus.score([empty])["status"], "no_relevant_claims")
        self.assertTrue(self.corpus.score([empty])["coverage_complete"])
        good = self.corpus.mine()
        mixed = self.corpus.score([good, failed])
        self.assertEqual(mixed["status"], "partial_coverage")
        self.assertEqual(len(mixed["inputs"]), 2)
        self.assertEqual(len(mixed["clusters"]), 1)
        partial = self.corpus.mine(partial=True)
        self.assertEqual(self.corpus.score([partial])["status"], "partial_coverage")
        background = self.corpus.score([self.corpus.mine(relevance=1)])
        self.assertEqual(background["status"], "background_only")
        self.assertEqual(background["background_claims"], 1)
        self.assertEqual(background["claim_rows"][background["background_claim_indices"][0]]["relevance"], 1)
        self.assertEqual(background["clusters"], [])
        with self.assertRaisesRegex(ValueError, "distinct mining"):
            self.corpus.score([])

    def test_healthy_no_relevance_is_not_a_dead_batch_or_a_successful_seen_receipt(self):
        empty, useful = self.corpus.mine(relevance=1, recall_bias="MEDIUM"), self.corpus.mine()
        combined = self.corpus.score([empty, useful])
        self.assertTrue(combined["ok"])
        self.assertTrue(combined["coverage_complete"])
        entry = combined["inputs"][0]
        self.assertTrue(entry["operationally_healthy"])
        self.assertTrue(entry["no_relevant_claims"])
        self.assertFalse(entry["complete"])
        self.assertEqual(entry["dropped_background_claims"], 1)
        self.assertEqual(self.corpus.store.get(empty)["payload"]["seen_source_artifacts"], [])
        failed = self.corpus.mine(status="model_error")
        self.assertEqual(self.corpus.score([empty, failed])["status"], "partial_coverage")

    def test_thirty_two_batches_cover_ninety_six_pages_without_silent_truncation(self):
        batches = [self.corpus.mine(f"https://batch{i}.example.org/source", page_count=3) for i in range(32)]
        result = self.corpus.score(batches)
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["inputs"]), 32)
        self.assertEqual(result["input_claims"], 96)
        self.assertEqual(len(result["claim_rows"]), 96)
        self.assertEqual(sorted(i for cl in result["clusters"] for i in cl["claim_indices"]), list(range(96)))
        self.assertLess(len(r.wire(result)), r.ARTIFACT_BYTES)
        other = self.corpus.mine(query="Other batch topic")
        with self.assertRaisesRegex(ValueError, "topics or extraction schemas differ"):
            self.corpus.score(batches[:-1] + [other])
        with self.assertRaisesRegex(ValueError, "1 through 32"):
            self.corpus.score(batches + [other])

    def test_existing_artifact_byte_budget_refuses_instead_of_dropping_inputs(self):
        ids = [self.corpus.mine(url) for url in ("https://github.com/a", "https://example.readthedocs.io/b")]
        self.corpus.store.maximum = max(p.stat().st_size for p in self.corpus.store.directory.iterdir()) + 1
        with self.assertRaisesRegex(ValueError, "byte budget"):
            self.corpus.score(ids)

    def test_mixed_question_schema_or_expected_intent_refuses_whole_operation(self):
        first = self.corpus.mine()
        for second in (self.corpus.mine(query="A different topic"), self.corpus.mine(field="another_field")):
            with self.assertRaisesRegex(ValueError, "topics or extraction schemas differ"):
                self.corpus.score([first, second])
        with self.assertRaisesRegex(ValueError, "intent differs"):
            self.corpus.score([first], query="Another question")

    def test_stored_span_source_model_and_health_tampering_refuse(self):
        key = self.corpus.mine()
        changes = [lambda d: d["payload"]["claims"][0].update(evidence_start=99),
                   lambda d: d["payload"]["claims"][0].update(source_text_sha256="0" * 64),
                   lambda d: d["payload"]["claims"][0].update(evidence_span="outside supplied source"),
                   lambda d: d["payload"].update(model={"id": "different"}),
                   lambda d: d["payload"].update(expected_shards=True),
                   lambda d: d["payload"].update(analysed_shards=0),
                   lambda d: d["payload"].update(response_hashes=[]),
                   lambda d: d.update(identity_sha256="0" * 64)]
        for change in changes:
            with self.subTest(change=change):
                altered = self.corpus.altered(key, change)
                with self.assertRaises((ValueError, KeyError)):
                    self.corpus.score([altered])

    def test_a_failed_corpus_cannot_be_relabelled_as_complete(self):
        failed = self.corpus.mine(status="model_error")
        def false_completion(record):
            payload = record["payload"]
            source = payload["failure_ledger"][0]["source_artifact_id"]
            payload.update(status="ok", ok=True, complete=True, seen_source_artifacts=[source])
            payload["failure_ledger"] = payload["failure_ledger"][:1]
        altered = self.corpus.altered(failed, false_completion)
        with self.assertRaisesRegex(ValueError, "status contradicts full-set"):
            self.corpus.score([altered])


class ConsensusRuntimeTests(unittest.TestCase):
    def test_declared_productive_deadline_rejects_a_late_scoring_result_before_publish(self):
        with tempfile.TemporaryDirectory() as name:
            home = Path(name).resolve()
            project = home / "project"
            project.mkdir()
            source = Path(__file__).resolve().parents[1] / "adapters/pi/project-workflow/project_identity.py"
            spec = importlib.util.spec_from_file_location("consensus_deadline_identity", source)
            identity = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(identity)
            state = home / "state/projects"
            with patch.dict(os.environ, {"PI_PROJECT_STATE_BASE": str(state)}):
                native, _ = identity.initialize_identity(project)
            binding = {"project_id": native["project_id"], "board_id": native["board_id"], "canonical_root": str(project)}
            corpus = Corpus(Path(native["state_root"]), binding, r.digest((project / ".icm/project.json").read_bytes()))
            key = corpus.mine()
            runtime = r.ResearchRuntime.__new__(r.ResearchRuntime)
            runtime.home, runtime.identity, runtime.env = home, identity, {"PI_PROJECT_STATE_BASE": str(state)}
            selection = {"project": {"root": str(project), "projectId": native["project_id"], "boardId": native["board_id"]}, "task": None}
            original = c.score
            def delayed(*args, **kwargs):
                value = original(*args, **kwargs)
                time.sleep(2.1)
                return value
            before = set(corpus.store.directory.iterdir())
            started = time.monotonic()
            with patch.object(c, "score", side_effect=delayed), self.assertRaisesRegex(ValueError, "deadline"):
                runtime.execute({"action": "consensus", "artifact_ids": [key], "selection": selection, "timeout": 2})
            self.assertGreaterEqual(time.monotonic() - started, 2)
            self.assertEqual(set(corpus.store.directory.iterdir()), before)

    def test_existing_dispatcher_stores_full_result_and_cached_read_never_infers(self):
        with tempfile.TemporaryDirectory() as name:
            home = Path(name).resolve()
            project = home / "project"
            project.mkdir()
            source = Path(__file__).resolve().parents[1] / "adapters/pi/project-workflow/project_identity.py"
            spec = importlib.util.spec_from_file_location("consensus_fixture_identity", source)
            identity = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(identity)
            state = home / "state/projects"
            with patch.dict(os.environ, {"PI_PROJECT_STATE_BASE": str(state)}):
                native, _ = identity.initialize_identity(project)
            binding = {"project_id": native["project_id"], "board_id": native["board_id"], "canonical_root": str(project)}
            corpus = Corpus(Path(native["state_root"]), binding, r.digest((project / ".icm/project.json").read_bytes()))
            key = corpus.mine()
            runtime = r.ResearchRuntime.__new__(r.ResearchRuntime)
            runtime.home, runtime.identity, runtime.env = home, identity, {"PI_PROJECT_STATE_BASE": str(state)}
            selection = {"project": {"root": str(project), "projectId": native["project_id"], "boardId": native["board_id"]}, "task": None}
            with patch.object(runtime, "mining_model", side_effect=AssertionError("No model access")), \
                    patch("harness.web_research.fetch", side_effect=AssertionError("No fetch")), \
                    patch("harness.web_research.search", side_effect=AssertionError("No search")):
                result = runtime.execute({"action": "consensus", "artifact_ids": [key], "selection": selection})
                self.assertTrue(result["ok"])
                self.assertFalse(result["consensus_established"])
                self.assertLessEqual(len(r.wire(result)), r.MODEL_BYTES)
                cached = runtime.execute({"action": "read", "artifact_id": result["artifact_id"], "selection": selection})
                self.assertIn("domain_coverage_proxy", cached["text"])
                saved = corpus.store.get(result["artifact_id"])
                self.assertEqual(saved["payload"]["input_claims"], 1)
                for fields in ({"embedding_url": "http://127.0.0.1:1"}, {"authority_candidates": {"example.org": 1}}):
                    with self.assertRaisesRegex(ValueError, "Unexpected consensus"):
                        runtime.execute({"action": "consensus", "artifact_ids": [key], "selection": selection, **fields})


if __name__ == "__main__":
    unittest.main()
