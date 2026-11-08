"""Native Dream manager tests with disposable data and local HTTP model stub."""

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from harness import memory_dream as dream


def sha(value):
    return hashlib.sha256(value).hexdigest()


class DreamFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="dream-intelligence-fixture-")
        base = Path(self.tmp.name)
        self.home = base / "agent-home"
        self.home.mkdir()
        self.project = base / "project"
        self.project.mkdir()
        (self.project / ".icm").mkdir()
        self.pid = "p_dream_test_123456abcdef"
        self.identity = {
            "project_id": self.pid,
            "board_id": "project:" + self.pid,
            "canonical_root": str(self.project),
            "state_root": str(self.home / "state" / "projects" / self.pid),
        }
        (self.project / ".icm" / "project.json").write_text(json.dumps(self.identity))
        self.record = self.project / "CURRENT.md"
        self.statement = (
            "The current model setup requires a verified native host lease."
        )
        self.record.write_text("# Current\n" + self.statement + "\n")
        self.base = {
            "schema": dream.SCHEMA,
            "project_id": self.pid,
            "evidence": [
                self.item(
                    "src-a",
                    self.statement,
                    "model.supervision",
                    "2026-11-07T10:00:00+00:00",
                    kind="icm",
                    on_disk=True,
                )
            ],
        }

    def tearDown(self):
        self.tmp.cleanup()

    def item(self, sid, text, key, time, kind="claude_mem", on_disk=False):
        result = {
            "source_id": sid,
            "source_kind": kind,
            "claim_key": key,
            "claim_text": text,
            "source_sha256": sha(self.record.read_bytes()) if on_disk else "a" * 64,
            "observed_at": time,
            "project_id": self.pid,
            "verification": "retrieval_only",
        }
        if on_disk:
            result["source_path"] = str(self.record)
            result["source_quote"] = self.statement
        return result

    def run_dream(self, req=None):
        return dream.preview(self.home, self.project, req or self.base)

    def test_verified_current_source_is_still_not_blessed(self):
        data = self.run_dream()
        self.assertEqual(data["status"], "CANDIDATES_NOT_PROMOTED")
        self.assertEqual(data["exact_source_count"], 1)
        self.assertEqual(
            data["forward_backward"][0]["status"], "SOURCE_PINNED_CANDIDATE"
        )
        self.assertEqual(data["last_known_best"], "UNASSESSED_NOT_INFERRED")
        self.assertIn("bless_ssot", data["forbidden"])

    def test_no_duplicate_store_or_files_written(self):
        before = {
            p.relative_to(self.tmp.name).as_posix(): sha(p.read_bytes())
            for p in Path(self.tmp.name).rglob("*")
            if p.is_file()
        }
        self.run_dream()
        after = {
            p.relative_to(self.tmp.name).as_posix(): sha(p.read_bytes())
            for p in Path(self.tmp.name).rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)

    def test_bidirectional_competing_claims_need_review(self):
        first = self.item(
            "early",
            "This model was the preferred agent model.",
            "model.preference",
            "2026-10-01T00:00:00+00:00",
        )
        later = self.item(
            "late",
            "Another model is now the preferred agent model.",
            "model.preference",
            "2026-11-08T00:00:00+00:00",
            kind="mempalace",
        )
        req = dict(self.base, evidence=[later, first])
        data = self.run_dream(req)
        subject = data["forward_backward"][0]
        self.assertEqual(subject["status"], "CONTRADICTION_REVIEW_REQUIRED")
        self.assertEqual(subject["forward_source_ids"], ["early", "late"])
        self.assertEqual(subject["backward_source_ids"], ["late", "early"])
        self.assertTrue(subject["newest_not_necessarily_best"])

    def test_identical_claims_do_not_promote_unverified_observations(self):
        a = self.item(
            "claim-a",
            "Always verify the current source.",
            "rule.verify",
            "2026-10-01T00:00:00Z",
        )
        b = self.item(
            "claim-b",
            "Always verify the current source.",
            "rule.verify",
            "2026-11-01T00:00:00Z",
        )
        out = self.run_dream(dict(self.base, evidence=[a, b]))
        self.assertEqual(out["exact_source_count"], 0)
        self.assertEqual(out["forward_backward"][0]["variant_count"], 1)
        self.assertEqual(out["forward_backward"][0]["status"], "SOURCE_REVIEW_REQUIRED")

    def test_modified_current_source_refused(self):
        self.record.write_text(self.statement + "\nUnreviewed mutation\n")
        with self.assertRaisesRegex(dream.DreamInputError, "changed"):
            self.run_dream()

    def test_wrong_source_excerpt_refused(self):
        self.base["evidence"][0]["source_quote"] = (
            "Text missing from the current artifact."
        )
        with self.assertRaisesRegex(dream.DreamInputError, "excerpt"):
            self.run_dream()

    def test_foreign_project_identity_refused(self):
        self.base["evidence"][0]["project_id"] = "p_other"
        with self.assertRaisesRegex(dream.DreamInputError, "Cross-project"):
            self.run_dream()

    def test_wrong_root_identity_refused(self):
        self.identity["state_root"] = str(self.project / "other-home")
        (self.project / ".icm" / "project.json").write_text(json.dumps(self.identity))
        with self.assertRaisesRegex(dream.DreamInputError, "different home"):
            self.run_dream()

    def test_credential_like_input_refused(self):
        self.base["evidence"][0]["claim_text"] = (
            "My password=supersecretlongvalue is a secret."
        )
        with self.assertRaisesRegex(dream.DreamInputError, "invalid/unsafe"):
            self.run_dream()

    def test_duplicate_source_refused(self):
        self.base["evidence"] *= 2
        with self.assertRaisesRegex(dream.DreamInputError, "Duplicate"):
            self.run_dream()

    def test_excessive_source_count_refused(self):
        self.base["evidence"] = [
            self.item(
                "s" + str(i),
                "This verified statement is for the demo.",
                "model.consolidation",
                "2026-10-01T00:00:00Z",
            )
            for i in range(65)
        ]
        with self.assertRaisesRegex(dream.DreamInputError, "1-64"):
            self.run_dream()

    def test_bad_source_path_and_symlink_refused(self):
        self.base["evidence"][0]["source_path"] = str(self.home / "private.db")
        with self.assertRaisesRegex(dream.DreamInputError, "escapes"):
            self.run_dream()

    def test_redirect_or_public_destination_refused(self):
        for endpoint in (
            "https://example.com/v1",
            "http://8.8.8.8:8080/v1",
            "http://localhost:8000/v1",
            "http://user:password@127.0.0.1:8080/v1",
        ):
            with (
                self.subTest(endpoint=endpoint),
                self.assertRaises(dream.DreamInputError),
            ):
                dream.local_url(endpoint)
        for forbidden in ("0.0.0.0", "169.254.1.1", "224.0.0.1"):
            with self.assertRaises(dream.DreamInputError):
                dream.local_url("http://" + forbidden + ":8123/v1")
        self.assertEqual(
            dream.local_url("http://127.0.0.1:8123/v1"),
            "http://127.0.0.1:8123/v1/chat/completions",
        )

    def test_dream_json_input_schema_cannot_hold_hidden_actions(self):
        request = dict(self.base, owner_grant=True)
        with self.assertRaisesRegex(dream.DreamInputError, "envelope"):
            self.run_dream(request)

    def test_cli_preview_is_read_only_and_contains_no_raw_memory_claims(self):
        from contextlib import redirect_stdout
        import io
        from unittest import mock

        before = {
            p.relative_to(self.tmp.name).as_posix(): sha(p.read_bytes())
            for p in Path(self.tmp.name).rglob("*")
            if p.is_file()
        }
        envelope = io.TextIOWrapper(
            io.BytesIO(json.dumps(self.base).encode()), encoding="utf-8"
        )
        output = io.StringIO()
        with mock.patch("sys.stdin", envelope), redirect_stdout(output):
            exit_code = dream.main(
                ["--home", str(self.home), "--project", str(self.project)]
            )
        self.assertEqual(exit_code, 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["status"], "CANDIDATES_NOT_PROMOTED")
        self.assertEqual(result["last_known_best"], "UNASSESSED_NOT_INFERRED")
        self.assertNotIn(self.statement, output.getvalue())
        self.assertNotIn(str(self.project), output.getvalue())
        after = {
            p.relative_to(self.tmp.name).as_posix(): sha(p.read_bytes())
            for p in Path(self.tmp.name).rglob("*")
            if p.is_file()
        }
        self.assertEqual(before, after)

    def test_cli_invalid_input_refuses_without_path_or_secret_leak(self):
        from contextlib import redirect_stdout
        import io
        from unittest import mock

        input_text = "{not valid json password=secretvalue123}"
        output = io.StringIO()
        stream = io.TextIOWrapper(io.BytesIO(input_text.encode()), encoding="utf-8")
        with mock.patch("sys.stdin", stream), redirect_stdout(output):
            exit_code = dream.main(
                ["--home", str(self.home), "--project", str(self.project)]
            )
        self.assertEqual(exit_code, 1)
        reply = json.loads(output.getvalue())
        self.assertEqual(reply["status"], "unavailable")
        self.assertNotIn("secretvalue123", output.getvalue())
        self.assertNotIn(str(self.home), output.getvalue())


class NativeClaudeHistoryAdapterTests(unittest.TestCase):
    def setUp(self):
        self.source_text = "The actual native window proves that this task was accepted as source text."
        self.pin = sha(self.source_text.encode())
        self.row = {
            "schema": "claude-memory-tool-history/v1",
            "authority": "retrieval_only",
            "source_scope": "native_stored_tool_field",
            "status": "ok",
            "field_present": True,
            "platform_source": "raw",
            "project": "selected-project",
            "id": 42,
            "content_session_id": "session-one",
            "field": "tool_response",
            "text": self.source_text,
            "stored_sha256": self.pin,
            "window_sha256": self.pin,
            "stored_eof": True,
            "offset": 0,
            "window_bytes": len(self.source_text.encode()),
            "stored_bytes": len(self.source_text.encode()),
        }
        self.params = dict(
            project_id="p_project_123",
            observer_project="selected-project",
            claim_key="task.acceptance",
            claim_text=self.source_text,
            observed_at="2026-11-08T19:00:00Z",
        )

    def test_existing_native_field_converts_to_retrieval_only_evidence(self):
        item = dream.from_claude_mem_tool_window(self.row, **self.params)
        self.assertEqual(item["source_id"], "cmtool-42-tool_response")
        self.assertEqual(item["source_sha256"], self.pin)
        self.assertEqual(item["verification"], "retrieval_only")
        self.assertNotIn("source_path", item)

    def test_cross_project_window_refused(self):
        with self.assertRaisesRegex(dream.DreamInputError, "different"):
            dream.from_claude_mem_tool_window(
                {**self.row, "project": "another"}, **self.params
            )

    def test_truncated_or_partial_window_refused(self):
        for change in (
            {"stored_eof": False},
            {"offset": 1},
            {"stored_bytes": 2000},
            {"stored_sha256": "a" * 64},
            {"field_present": False},
        ):
            with self.subTest(change=change), self.assertRaises(dream.DreamInputError):
                dream.from_claude_mem_tool_window({**self.row, **change}, **self.params)

    def test_model_invented_claim_not_present_in_original_refused(self):
        with self.assertRaisesRegex(dream.DreamInputError, "not present"):
            dream.from_claude_mem_tool_window(
                self.row,
                **{**self.params, "claim_text": "Unrelated accepted task claim"},
            )

    def test_native_field_cannot_smuggle_execution_authority(self):
        with self.assertRaises(dream.DreamInputError):
            dream.from_claude_mem_tool_window(
                {**self.row, "authority": "blessed"}, **self.params
            )


class LocalModelTest(DreamFixture):
    def test_local_inference_with_cited_proposal_and_no_remote_access(self):

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers["Content-Length"])
                payload = json.loads(self.rfile.read(length))
                assert payload["messages"][0]["role"] == "user"
                assert "/home/" not in payload["messages"][0]["content"]
                assert payload["max_tokens"] <= 650
                response = {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "proposals": [
                                            {
                                                "claim_key": "model.supervision",
                                                "source_ids": ["src-a"],
                                                "reason": "Revalidate this rule using a separate native acceptance test.",
                                                "kind": "revalidation",
                                            }
                                        ]
                                    }
                                )
                            }
                        }
                    ]
                }
                body = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *unused):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            cfg = {
                "base_url": "http://127.0.0.1:" + str(server.server_port) + "/v1",
                "model": "test-local-model",
            }
            result = dream.analyze_local(
                self.home, self.project, self.base, cfg, timeout=4
            )
            self.assertEqual(
                result["model_review"]["status"], "UNVERIFIED_LOCAL_MODEL_SUGGESTIONS"
            )
            self.assertTrue(result["model_review"]["cannot_promote"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
