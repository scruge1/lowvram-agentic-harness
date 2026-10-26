"""Real saved evidence validation; no provider, browser or model calls."""
import copy
import json
from unittest import TestCase
from unittest.mock import patch

from harness import research_runtime as rr
from tests import test_research_runtime as runtime_fixtures


class ResearchProgressTests(TestCase):
    def setUp(self):
        fixture = runtime_fixtures.RoutingTests()
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        self.runtime, self.selection, self.project = fixture.runtime, fixture.selection, fixture.project
        self.binding, self.identity, self.source_hash = self.runtime.selection({"selection": self.selection})
        self.store = rr.ArtifactStore(self.identity["state_root"], self.binding)

    def saved(self, action="fetch", payload=None, **changes):
        payload = payload or {"ok": True, "status": "ok", "text": "Seven rows,42 litres/hour.", "content_scope": "full_extraction"}
        record = {"schema": "project-research-artifact/v1", "project": self.binding, "session_id": "native-session",
                  "identity_sha256": self.source_hash, "authority": rr.AUTHORITY, "action": action, "payload": payload, **changes}
        key = self.store.put(record)
        return rr.projection(record, key), record

    def validate(self, delivery, **changes):
        return self.runtime.execute({"action": "_progress_validate", "selection": self.selection,
                                     "session_id": "native-session", "delivery": delivery, **changes})

    def test_saved_nonempty_source_gets_content_credit_without_body_output(self):
        delivered, _ = self.saved()
        result = self.validate(delivered)
        self.assertTrue(result["credit"])
        self.assertEqual(result["artifact_id"], delivered["artifact_id"])
        self.assertNotIn("Seven rows", json.dumps(result))
        self.assertEqual(result["authority"], "untrusted_source_evidence")

    def test_timestamp_new_id_and_whitespace_do_not_make_content_new(self):
        first, _ = self.saved(observed_at="first")
        second, _ = self.saved(observed_at="second")
        third, _ = self.saved(payload={"ok": True, "status": "ok", "text": " Seven\nrows,42   litres/hour. ", "content_scope": "full_extraction"})
        self.assertNotEqual(first["artifact_id"], second["artifact_id"])
        self.assertEqual(len({self.validate(value)["fingerprint"] for value in (first, second, third)}), 1)

    def test_order_rank_provider_duplicates_do_not_make_search_new(self):
        hits = [{"url": "https://example.org/a", "canonical_url": "https://example.org/a", "title": "One source", "snippet": "Seven rows", "rank": 1},
                {"url": "https://example.org/b", "title": "Another source", "snippet": "42 litres/hour", "rank": 2}]
        first, _ = self.saved("search", {"ok": True, "status": "ok", "hits": hits})
        changed = [{**row, "rank": 19, "provider": "changed", "observations": [{"at": "new"}]} for row in reversed(hits)]
        second, _ = self.saved("search", {"ok": True, "status": "ok", "hits": changed + changed})
        self.assertEqual(self.validate(first)["fingerprint"], self.validate(second)["fingerprint"])

    def test_failed_partial_failure_empty_and_metadata_only_abstain(self):
        cases = [("fetch", {"ok": False, "status": "partial", "text": "uncertain prior body", "content_scope": "full_extraction"}),
                 ("fetch", {"ok": True, "status": "deadline", "text": "uncertain body", "content_scope": "full_extraction"}),
                 ("fetch", {"ok": True, "status": "ok", "text": "  ", "content_scope": "full_extraction"}),
                 ("render", {"ok": True, "status": "ok", "document": {"text": ""}}),
                 ("search", {"ok": True, "status": "ok", "hits": []}),
                 ("search", {"ok": True, "status": "ok", "hits": [{"url": "https://example.org/", "title": " ", "snippet": ""}]})]
        for action, payload in cases:
            with self.subTest(action=action, payload=payload):
                delivered, _ = self.saved(action, payload)
                self.assertFalse(self.validate(delivered)["credit"])

    def test_successful_browser_window_is_partial_evidence_not_full_coverage(self):
        delivered, _ = self.saved("render", {"ok": True, "status": "partial", "document": {"text": "Seven new rows", "truncated": True}})
        result = self.validate(delivered)
        self.assertTrue(result["credit"])
        self.assertEqual(result["coverage"], "captured_partial_evidence")
        self.assertEqual(result["content_scope"], "captured_browser_window")

    def test_cached_read_and_unsuccessful_delivered_result_abstain(self):
        delivered, record = self.saved()
        cached = rr.projection(record, delivered["artifact_id"], cached=True)
        self.assertFalse(self.validate(cached)["credit"])
        self.assertFalse(self.validate({**delivered, "ok": False})["credit"])

    def test_missing_damaged_foreign_or_wrong_session_source_refuse(self):
        delivered, _ = self.saved()
        with self.assertRaises((ValueError, OSError)):
            self.validate({**delivered, "artifact_id": "sha256:" + "0" * 64})
        with self.assertRaisesRegex(ValueError, "another native session"):
            self.validate(delivered, session_id="different-session")
        for changes, reason in [({"identity_sha256": "0" * 64}, "source changed"),
                                ({"project": {**self.binding, "project_id": "foreign"}}, "binding")]:
            record = {"schema": "project-research-artifact/v1", "project": self.binding, "session_id": "native-session",
                      "identity_sha256": self.source_hash, "authority": rr.AUTHORITY, "action": "fetch", "payload": {"ok": True, "status": "ok", "text": "new body", "content_scope": "full_extraction"}, **changes}
            # A malformed saved fixture is not authority; the real getter must refuse it.
            writer = rr.ArtifactStore(self.identity["state_root"], record["project"])
            key = writer.put(record)
            with self.assertRaises(ValueError):
                self.validate({**delivered, "artifact_id": key})
        file = self.store.directory / (delivered["artifact_id"][7:] + ".json")
        file.write_bytes(file.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "hash"):
            self.validate(delivered)

    def test_forged_delivery_body_hash_project_window_refuse(self):
        delivered, _ = self.saved()
        for change in ({"text_sha256": "0" * 64}, {"text": "invented"}, {"project_id": "foreign"},
                       {"window_sha256": "0" * 64}, {"offset": 1}, {"status": "failed"},
                       {"schema": "untrusted-shape"}, {"content_scope": "full_dom"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.validate({**delivered, **change})

    def test_source_change_during_validation_refuses(self):
        delivered, _ = self.saved()
        file = self.project / ".icm/project.json"
        original = file.read_bytes()
        native = rr.text_view
        def changed(*args):
            value = native(*args)
            file.write_bytes(original + b" ")
            return value
        try:
            with patch.object(rr, "text_view", side_effect=changed), self.assertRaisesRegex(ValueError, "during validation"):
                self.validate(delivered)
        finally:
            file.write_bytes(original)

    def test_out_of_range_count_mismatch_and_whitespace_window_refuse(self):
        delivered, _ = self.saved()
        for changed in ({"offset": 100000, "returned_chars": 1, "text": "", "window_sha256": rr.digest(b"")},
                        {"returned_chars": delivered["returned_chars"] + 1}):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "source window"):
                self.validate({**delivered, **changed})
        spaced, _ = self.saved(payload={"ok": True, "status": "ok", "text": " " * 100 + "Real source facts", "content_scope": "full_extraction"})
        with self.assertRaisesRegex(ValueError, "source window"):
            self.validate({**spaced, "returned_chars": 80, "text": " " * 80, "window_sha256": rr.digest(b" " * 80)})

    def test_request_is_read_only_and_has_no_credential_or_model_fields(self):
        delivered, _ = self.saved()
        before = sorted((file.name, file.read_bytes()) for file in self.store.directory.iterdir())
        self.validate(delivered)
        self.assertEqual(before, sorted((file.name, file.read_bytes()) for file in self.store.directory.iterdir()))
        with self.assertRaisesRegex(ValueError, "Unexpected progress"):
            self.validate(copy.deepcopy(delivered), provider="untrusted")
