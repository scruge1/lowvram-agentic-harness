import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import memory_claim_candidate


class MemoryClaimCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        self.closeout = self.root / ".icm/workspace/wiki/task-closeouts/task-001.json"
        self.closeout.parent.mkdir(parents=True)
        value = {
            "schema": "pi-project-closeout/v1",
            "project_id": "project-001",
            "board_id": "board-001",
            "task_id": "task-001",
            "card_id": "card-001",
            "summary": "Verified browser download handling.",
            "lessons": ["Use download.save_as before closing the context."],
            "receipt": {"sha256": "a" * 64},
            "authority": "verified_lesson_guidance_only",
        }
        self.closeout.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        payload = {
            "schema": "pi-project-closeout-memory/v1",
            "project_id": "project-001",
            "task_id": "task-001",
            "summary": value["summary"],
            "lessons": value["lessons"],
            "closeout_path": ".icm/workspace/wiki/task-closeouts/task-001.json",
            "closeout_sha256": hashlib.sha256(self.closeout.read_bytes()).hexdigest(),
            "receipt_sha256": "a" * 64,
            "authority": "guidance_only",
        }
        self.snapshot = self.root / "drawer.json"
        self.snapshot.write_text(json.dumps({
            "drawer_id": "drawer_001",
            "content": json.dumps(payload, sort_keys=True, separators=(",", ":")),
            "metadata": {"filed_at": "2026-09-20T12:00:00Z"},
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def test_compiles_immutable_source_bound_candidate(self):
        result = memory_claim_candidate.compile_candidate(self.root, self.closeout, self.snapshot)
        repeated = memory_claim_candidate.compile_candidate(self.root, self.closeout, self.snapshot)
        self.assertEqual(result["candidate_sha256"], repeated["candidate_sha256"])
        candidate = json.loads(Path(result["candidate_path"]).read_text())
        self.assertIn("/.icm/workspace/wiki/memory-candidates/", result["candidate_path"].replace("\\", "/"))
        self.assertEqual("mempalace://drawer/drawer_001", candidate["claim"]["source_path"])
        self.assertNotIn("@", candidate["claim"]["safe_text"])
        self.assertEqual("project_local_candidate", candidate["promotion_state"])

    def test_rejects_drawer_content_drift(self):
        value = json.loads(self.snapshot.read_text())
        value["content"] += "changed"
        self.snapshot.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(memory_claim_candidate.MemoryClaimError, "drawer content differs"):
            memory_claim_candidate.compile_candidate(self.root, self.closeout, self.snapshot)

    def test_rejects_sensitive_summary(self):
        value = json.loads(self.closeout.read_text())
        value["summary"] = "Account email is person@example.com"
        self.closeout.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaises(memory_claim_candidate.MemoryClaimError):
            memory_claim_candidate.compile_candidate(self.root, self.closeout, self.snapshot)

    def test_rejects_cross_project_paths(self):
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(memory_claim_candidate.MemoryClaimError, "outside project"):
            memory_claim_candidate.compile_candidate(self.root, self.closeout, outside)


if __name__ == "__main__":
    unittest.main()
