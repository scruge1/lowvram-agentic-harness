import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "adapters" / "pi" / "project-workflow"


def load(name):
    spec = importlib.util.spec_from_file_location(name, WORKFLOW / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sys.path.insert(0, str(WORKFLOW))
project_identity = load("project_identity")
project_knowledge = load("project_knowledge")
project_skill_candidate = load("project_skill_candidate")


class PiProjectWorkflowTests(unittest.TestCase):
    def test_export_has_no_private_host_binding(self):
        forbidden = ("/home/adam", "a33_s", "100.84.")
        for path in WORKFLOW.iterdir():
            if path.is_file():
                text = path.read_text(encoding="utf-8")
                for value in forbidden:
                    self.assertNotIn(value, text, f"private binding in {path.name}")

    def test_workspace_initializer_is_source_pinned(self):
        initializer = WORKFLOW / "init_workspace.py"
        self.assertEqual(
            hashlib.sha256(initializer.read_bytes()).hexdigest(),
            "1cd480bd692001fa8d56775496d723c6ff937c1b306ddd66c1c6f343ec90c6b9",
        )

    def test_hyphenated_skill_candidate_is_immutable_and_searchable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            identity, created = project_identity.initialize_identity(
                root, native_authority="test fixture only"
            )
            self.assertTrue(created)
            closeout_path = root / ".icm" / "workspace" / "wiki" / "task-closeouts" / "task-1.json"
            closeout_path.parent.mkdir(parents=True)
            closeout = {
                "schema": "pi-project-closeout/v1",
                "project_id": identity["project_id"],
                "task_id": "task-1",
                "authority": "verified_lesson_guidance_only",
                "receipt": {
                    "status": "accepted",
                    "authority_cap": "tested",
                    "sha256": "a" * 64,
                },
            }
            closeout_bytes = (json.dumps(closeout, sort_keys=True) + "\n").encode()
            closeout_path.write_bytes(closeout_bytes)
            request = {
                "name": "verified-project-closeout",
                "description": "Reuse an accepted project closeout.",
                "closeout_path": str(closeout_path),
                "closeout_sha256": hashlib.sha256(closeout_bytes).hexdigest(),
                "triggers": ["A verified project task needs reusable guidance."],
                "steps": ["Read the source closeout and its receipt binding."],
                "verification": ["Confirm the closeout and skill hashes."],
                "stop_conditions": ["Stop when the source closeout differs."],
            }
            result = project_skill_candidate.compile_candidate(root, request)
            self.assertEqual(result["promotion_state"], "project_local_candidate")
            self.assertEqual(result["authority"], "guidance_only")
            query = project_knowledge.query(root, "verified-project-closeout", 10)
            paths = {item["path"] for item in query["results"]}
            self.assertIn(".icm/skills/verified-project-closeout/SKILL.md", paths)
            self.assertIn(".icm/skills/verified-project-closeout/candidate.json", paths)
            with self.assertRaises(project_skill_candidate.SkillCandidateError):
                project_skill_candidate.compile_candidate(
                    root, {**request, "description": "Changed content."}
                )

    def test_runtime_configuration_uses_explicit_hashes(self):
        extension = (WORKFLOW / "everyday-workflow.ts").read_text(encoding="utf-8")
        helper = (WORKFLOW / "everyday_workflow.py").read_text(encoding="utf-8")
        self.assertIn("configuration.runtime_manifest_sha256", extension)
        self.assertIn("configuration.engine_sha256", extension)
        self.assertNotIn("ENGINE_SHA =", helper)
        self.assertNotIn("RUNTIME_SHA =", helper)


if __name__ == "__main__":
    unittest.main()
