"""Real validated-retrieval → Dream evidence boundary, without memory service I/O."""

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

from harness import memory_dream as dream

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "adapters/pi/memory"
sys.path.insert(0, str(NATIVE))
spec = importlib.util.spec_from_file_location(
    "validated_mem_for_dream", NATIVE / "validated_memory_query.py"
)
validated = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validated)


class MemPalaceDreamBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(prefix="mempalace-dream-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name).resolve(strict=True)
        self.home = root / "home"
        self.project = root / "project"
        self.home.mkdir()
        self.project.mkdir()
        (self.project / ".icm").mkdir()
        self.pid = "p_mempalace_dream_fixture"
        self.identity = {
            "project_id": self.pid,
            "board_id": "project:" + self.pid,
            "canonical_root": str(self.project),
            "state_root": str(self.home / "state/projects" / self.pid),
        }
        (self.project / ".icm/project.json").write_text(json.dumps(self.identity))
        self.original = self.project / "owner-proof.md"
        self.raw = "The accepted owner design requires an independent native verifier."
        self.original.write_text(
            "# Current policy\n" + self.raw + "\n", encoding="utf-8"
        )
        self.reviewed = (
            "Source-qualified completion still needs a separate host verifier."
        )
        self.registry = {
            "claim_id": "claim-verified-1",
            "claim_sha256": validated.claim_sha256(self.raw),
            "source_path": str(self.original),
            "source_sha256": validated.sha256_bytes(self.original.read_bytes()),
            "safe_text": self.reviewed,
            "safe_text_sha256": validated.sha256_bytes(self.reviewed.encode()),
            "state": "current",
            "evidence_class": "verified_closeout",
            "observed_at": "2026-11-08T19:00:00Z",
        }
        self.search = {
            "results": [
                {
                    "text": self.raw,
                    "source_path": str(self.original),
                    "source_sha256": self.registry["source_sha256"],
                    "similarity": 0.92,
                }
            ]
        }

    def validated_reply(self):
        records = {
            (self.registry["source_path"], self.registry["claim_sha256"]): self.registry
        }
        return validated.validated_query("owner project evidence", self.search, records)

    def converted(self, reply=None, **kwargs):
        return dream.from_validated_mempalace_result(
            self.validated_reply() if reply is None else reply,
            project_id=self.pid,
            claim_key="owner.verification",
            **kwargs,
        )

    def view(self, *records):
        return dream.preview(
            self.home,
            self.project,
            {"schema": dream.SCHEMA, "project_id": self.pid, "evidence": list(records)},
        )

    def test_real_validated_retrieval_never_promotes_source_without_original(self):
        accepted = self.validated_reply()
        self.assertFalse(accepted["abstained"])
        self.assertEqual(accepted["authority"], "verified_retrieval_only")
        record = self.converted(accepted)
        self.assertEqual(record["source_kind"], "mempalace")
        self.assertEqual(record["verification"], "retrieval_only")
        self.assertEqual(record["source_sha256"], self.registry["source_sha256"])
        self.assertEqual(record["claim_text"], self.reviewed)
        self.assertTrue(record["source_id"].startswith("mp-"))
        self.assertNotIn("source_path", record)
        self.assertNotIn("source_quote", record)
        report = self.view(record)
        self.assertEqual(report["status"], "CANDIDATES_NOT_PROMOTED")
        self.assertEqual(
            report["forward_backward"][0]["status"], "SOURCE_REVIEW_REQUIRED"
        )
        self.assertEqual(report["exact_source_count"], 0)
        self.assertNotIn(str(self.original), json.dumps(report))
        self.assertNotIn(self.reviewed, json.dumps(report))

    def test_original_source_changed_upstream_refuses_dream_conversion(self):
        self.original.write_text("Original source materially changed.\n")
        abstained = self.validated_reply()
        self.assertTrue(abstained["abstained"])
        with self.assertRaises(dream.DreamInputError):
            self.converted(abstained)

    def test_conflicting_claude_and_mempalace_memory_is_not_blessed(self):
        old_text = "Owner previously preferred an unverified summary."
        pin = sha256(old_text.encode()).hexdigest()
        stored = {
            "schema": "claude-memory-tool-history/v1",
            "authority": "retrieval_only",
            "source_scope": "native_stored_tool_field",
            "status": "ok",
            "field_present": True,
            "platform_source": "raw",
            "project": "project-owner",
            "id": 42,
            "content_session_id": "session-A",
            "field": "tool_response",
            "text": old_text,
            "stored_eof": True,
            "offset": 0,
            "stored_bytes": len(old_text.encode()),
            "window_bytes": len(old_text.encode()),
            "stored_sha256": pin,
            "window_sha256": pin,
        }
        older = dream.from_claude_mem_tool_window(
            stored,
            project_id=self.pid,
            observer_project="project-owner",
            claim_key="owner.verification",
            claim_text=old_text,
            observed_at="2026-10-12T12:00:00Z",
        )
        newer = self.converted()
        view = self.view(newer, older)
        subject = view["forward_backward"][0]
        self.assertEqual(subject["status"], "CONTRADICTION_REVIEW_REQUIRED")
        self.assertEqual(
            subject["forward_source_ids"], [older["source_id"], newer["source_id"]]
        )
        self.assertEqual(
            subject["backward_source_ids"], [newer["source_id"], older["source_id"]]
        )
        self.assertEqual(view["exact_source_count"], 0)
        self.assertEqual(view["last_known_best"], "UNASSESSED_NOT_INFERRED")

    def test_untrusted_project_claim_cannot_cross_owner_boundary(self):
        item = self.converted()
        item["project_id"] = "p_another_home"
        with self.assertRaisesRegex(dream.DreamInputError, "Cross-project"):
            self.view(item)

    def test_unreviewed_or_revoked_candidates_refuse(self):
        valid = self.validated_reply()
        for alteration in (
            {"authority": "blessed"},
            {"abstained": True},
            {"reason": "no_current_provenanced_result"},
            {"bound_result_count": 0},
            {"raw_result_count": 0},
        ):
            reply = {**valid, **alteration}
            with (
                self.subTest(alteration=alteration),
                self.assertRaises(dream.DreamInputError),
            ):
                self.converted(reply)
        for change in (
            {"identity": "unbound:1:fake"},
            {"state": "superseded"},
            {"valid_to": "2026-11-01"},
            {"source_sha256": "unverified"},
            {"claim_sha256": "unverified"},
            {"source_path": "https://outside.example/secret"},
            {"text": "api_key=shouldneverbeincludedinmemory"},
            {"execution_authority": "blessed"},
            {"observed_at": "not-a-date"},
        ):
            row = {**valid["results"][0], **change}
            with self.subTest(change=change), self.assertRaises(dream.DreamInputError):
                self.converted({**valid, "results": [row]})
        with self.assertRaises(dream.DreamInputError):
            self.converted(valid, result_index=True)
        with self.assertRaises(dream.DreamInputError):
            self.converted(valid, result_index=2)

    def test_deterministic_pseudonymous_ids_and_no_original_source_paths(self):
        row = self.converted()
        second = self.converted()
        self.assertEqual(row, second)
        self.assertNotIn(str(self.original), json.dumps(row))
        self.assertNotIn("owner-proof.md", json.dumps(row))
        self.assertNotIn(self.raw, json.dumps(row))
        self.assertTrue(len(row["source_id"]) < 128)


if __name__ == "__main__":
    unittest.main()
