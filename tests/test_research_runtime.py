"""Offline evidence-store and routing checks; no search provider or browser."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import research_runtime as rr


def record(text="public evidence", action="fetch", project=None):
    return {"schema": "project-research-artifact/v1", "project": project or {"project_id": "fixture", "board_id": "project:fixture", "canonical_root": "/fixture"},
            "action": action, "authority": rr.AUTHORITY,
            "payload": {"ok": True, "status": "ok", "response": {"cleaned_text_full": text,
                        "cleaned_text": text[:10], "raw_content_base64": "PRIVATE_BINARY"}}}


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # Hosted Windows TEMP can use an 8.3 alias. The production store expects
        # the same canonical state path that native project admission records.
        self.root = Path(self.temp.name).resolve()
        self.project = record()["project"]
        self.store = rr.ArtifactStore(self.root, self.project)

    def tearDown(self):
        self.temp.cleanup()

    def test_immutable_content_address_and_deduplication(self):
        source = record()
        key = self.store.put(source)
        self.assertEqual(key, "sha256:" + hashlib.sha256(rr.wire(source)).hexdigest())
        self.assertEqual(self.store.put(source), key)
        self.assertEqual(self.store.get(key), source)
        self.assertEqual(len(list(self.store.directory.iterdir())), 1)

    def test_hash_drift_and_foreign_project_are_refused(self):
        key = self.store.put(record())
        target = self.store.directory / (key[7:] + ".json")
        target.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(rr.ResearchError, "hash differs"):
            self.store.get(key)
        foreign = record(project={**self.project, "project_id": "different"})
        with self.assertRaisesRegex(rr.ResearchError, "binding differs"):
            self.store.put(foreign)
        raw = rr.wire(foreign)
        foreign_key = "sha256:" + rr.digest(raw)
        (self.store.directory / (foreign_key[7:] + ".json")).write_bytes(raw)
        with self.assertRaisesRegex(rr.ResearchError, "selected project"):
            self.store.get(foreign_key)

    def test_id_paths_and_symlink_artifacts_are_refused(self):
        for key in ("../other", "sha256:" + "A" * 64, None, "sha256:" + "0" * 64 + "/x"):
            with self.assertRaises(rr.ResearchError):
                self.store.get(key)
        if os.name != "nt":
            key = "sha256:" + "0" * 64
            target = self.root / "other.json"
            target.write_text("{}")
            (self.store.directory / (key[7:] + ".json")).symlink_to(target)
            with self.assertRaisesRegex(rr.ResearchError, "redirected"):
                self.store.get(key)

    def test_quota_failure_publishes_nothing(self):
        store = rr.ArtifactStore(self.root, self.project, quota_bytes=100)
        with self.assertRaisesRegex(rr.ResearchError, "quota"):
            store.put(record("x" * 101))
        self.assertEqual(list(store.directory.iterdir()), [])

    @unittest.skipIf(os.name == "nt", "Native symlink fixture requires no elevated Windows privilege")
    def test_redirected_storage_ancestor_is_refused_before_creation(self):
        outside = self.root / "outside"
        outside.mkdir()
        alias = self.root / "alias"
        alias.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(rr.ResearchError, "ancestors"):
            rr.ArtifactStore(alias / "project", self.project)
        self.assertEqual(list(outside.iterdir()), [])

    def test_metadata_never_includes_full_body_or_binary(self):
        source = record("SOURCE_SECRET")
        view = rr.projection(source, "sha256:" + "0" * 64, view="metadata")
        self.assertNotIn("SOURCE_SECRET", view["text"])
        self.assertNotIn("PRIVATE_BINARY", view["text"])

    def test_unicode_and_json_escaping_windows_recover_exact_full_extraction(self):
        text = ('漢字🙂\n\t"\\\x01' * 10000)
        source = record(text)
        offset, recovered = 0, []
        while True:
            view = rr.projection(source, "sha256:" + "0" * 64, offset=offset, limit=8192, cached=True)
            self.assertLessEqual(len(rr.wire(view)), rr.MODEL_BYTES)
            self.assertEqual(view["window_sha256"], rr.digest(view["text"].encode()))
            self.assertEqual(view["text_sha256"], rr.digest(text.encode()))
            recovered.append(view["text"])
            if view["next_offset"] is None:
                break
            self.assertGreater(view["next_offset"], offset)
            offset = view["next_offset"]
        self.assertEqual("".join(recovered), text)

    def test_render_is_only_captured_window_and_failure_status_is_retained(self):
        source = record(action="render")
        source["payload"] = {"ok": False, "status": "timeout", "reason": "deadline", "document": {"text": "captured", "offset": 99, "truncated": True}}
        initial = rr.projection(source, "sha256:" + "0" * 64)
        self.assertFalse(initial["ok"])
        self.assertEqual(initial["content_scope"], "captured_browser_window")
        self.assertEqual(initial["capture_offset"], 99)
        cached = rr.projection(source, "sha256:" + "0" * 64, cached=True)
        self.assertTrue(cached["ok"])
        self.assertEqual(cached["source_status"], "timeout")


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name).resolve()
        self.project = self.home / "project"
        self.project.mkdir()
        self.state_base = self.home / "state/projects"
        source = Path(__file__).resolve().parents[1] / "adapters/pi/project-workflow/project_identity.py"
        spec = importlib.util.spec_from_file_location("research_test_native_identity", source)
        self.identity = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.identity)
        with patch.dict(os.environ, {"PI_PROJECT_STATE_BASE": str(self.state_base)}):
            identity, _ = self.identity.initialize_identity(self.project)
        self.selection = {"project": {"root": str(self.project), "projectId": identity["project_id"], "boardId": identity["board_id"]}, "task": None}
        # Exercise the real dispatcher/identity/store without installing packages.
        self.runtime = rr.ResearchRuntime.__new__(rr.ResearchRuntime)
        self.runtime.home = self.home
        self.runtime.identity = self.identity
        self.runtime.env = {"PI_PROJECT_STATE_BASE": str(self.state_base)}

    def tearDown(self):
        self.temp.cleanup()

    def test_fetch_publishes_full_body_but_cached_read_never_calls_network(self):
        payload = record("COMPLETE " * 10000)["payload"]
        with patch("harness.web_research.fetch", return_value=payload) as fetch, patch.dict(os.environ, clear=False):
            initial = self.runtime.execute({"action": "fetch", "url": "https://example.org/", "selection": self.selection})
        fetch.assert_called_once()
        self.assertLessEqual(len(rr.wire(initial)), rr.MODEL_BYTES)
        with patch("harness.research_runtime.importlib.import_module", side_effect=AssertionError("cached read must not load network clients")):
            cached = self.runtime.execute({"action": "read", "artifact_id": initial["artifact_id"], "offset": initial["next_offset"], "selection": self.selection})
        self.assertTrue(cached["cached"])
        binding, identity, _ = self.runtime.selection({"selection": self.selection})
        saved = rr.ArtifactStore(identity["state_root"], binding).get(initial["artifact_id"])
        self.assertEqual(saved["payload"]["selected_native"], payload)
        self.assertEqual(saved["payload"]["attempts"][0]["native"], payload)

    def test_automatic_browser_fallback_retains_partial_source_scope_in_cached_read(self):
        empty = {"ok": False, "status": "empty_extraction", "response": {
            "content_type": "text/html", "status_code": 200, "raw_truncated": False,
            "cleaned_text_full": "", "final_url": "https://example.org/dynamic"}}
        rendered = {"ok": True, "status": "partial", "page_url": "https://example.org/dynamic",
                    "document": {"text": "synthetic rendered evidence", "truncated": True, "offset": 0}}
        with patch("harness.web_research.fetch", return_value=empty), \
                patch("harness.web_browser.render", return_value=rendered) as browser:
            initial = self.runtime.execute({"action": "fetch", "url": "https://example.org/dynamic",
                                            "selection": self.selection})
        self.assertEqual(browser.call_count, 1)
        self.assertEqual(initial["content_scope"], "captured_browser_window")
        self.assertEqual(initial["selected_url"], rendered["page_url"])
        self.assertFalse(initial["requested_source_complete"])
        self.assertTrue(initial["capture_truncated"])
        cached = self.runtime.execute({"action": "read", "artifact_id": initial["artifact_id"],
                                       "selection": self.selection})
        self.assertEqual(cached["text"], rendered["document"]["text"])
        self.assertEqual(cached["content_scope"], "captured_browser_window")
        self.assertEqual(cached["source_status"], "partial")
        self.assertFalse(cached["requested_source_complete"])

    def test_search_uses_host_home_and_cannot_select_credentials_from_request(self):
        payload = {"ok": True, "status": "ok", "provider": "duckduckgo", "results": []}
        with patch("harness.web_research.search", return_value=payload) as search:
            result = self.runtime.execute({"action": "search", "query": "portable example",
                                           "selection": self.selection})
            search.assert_called_once_with("portable example", limit=5, timeout=30, home=self.home)
            binding, identity, _ = self.runtime.selection({"selection": self.selection})
            saved = rr.ArtifactStore(identity["state_root"], binding).get(result["artifact_id"])
            self.assertEqual(saved["payload"], payload)
            for override in ({"home": "/other/home"}, {"provider": "brave"},
                             {"api_key": "synthetic-secret"}, {"retention": "rights_confirmed"}):
                with self.assertRaisesRegex(rr.ResearchError, "Unexpected research request"):
                    self.runtime.execute({"action": "search", "query": "portable example",
                                          "selection": self.selection, **override})
            self.assertEqual(search.call_count, 1)

    def test_selected_identity_drift_and_unadmitted_selection_refused(self):
        for selection in (None, {**self.selection, "boardAdmissionFailed": True},
                          {**self.selection, "project": {**self.selection["project"], "projectId": "wrong"}}):
            with self.assertRaises((rr.ResearchError, ValueError)):
                self.runtime.execute({"action": "read", "artifact_id": "sha256:" + "0" * 64, "selection": selection})

    def test_mid_fetch_identity_drift_is_not_published(self):
        def changed(*_args, **_kwargs):
            target = self.project / ".icm/project.json"
            document = json.loads(target.read_text())
            document["last_verified_at"] = "changed-during-fetch"
            target.write_text(json.dumps(document))
            return record()["payload"]
        with patch("harness.web_research.fetch", side_effect=changed), patch.dict(os.environ, clear=False):
            with self.assertRaisesRegex(rr.ResearchError, "changed during"):
                self.runtime.execute({"action": "fetch", "url": "https://example.org/", "selection": self.selection})
        self.assertEqual(list(self.state_base.glob("*/research/artifacts/*.json")), [])

    def test_foreign_model_fields_do_not_expand_network_or_project_authority(self):
        for field in ("project_root", "private_hosts", "headers", "provider", "python"):
            with self.assertRaisesRegex(rr.ResearchError, "Unexpected"):
                self.runtime.execute({"action": "search", "query": "test", "selection": self.selection, field: "untrusted"})


if __name__ == "__main__":
    unittest.main()
