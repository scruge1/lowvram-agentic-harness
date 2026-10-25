"""Exercise the actual fresh-home CLI and its overwrite/privacy boundaries."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from harness import home


class AgentHomeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="agent-home-test-")
        self.addCleanup(self.temporary.cleanup)
        # Windows runners can expose TEMP through an 8.3 path alias. Compare
        # the same canonical identity that the installed home records.
        self.root = Path(self.temporary.name).resolve() / "Agent home with spaces"

    def create(self):
        return home.scaffold(self.root, profile="core", base_url="http://127.0.0.1:8080/v1", model="local-test", name="Test Owner", offline=True)

    def test_cli_home_and_launcher_preserve_paths_and_private_files(self):
        result = subprocess.run([sys.executable, "-m", "harness.home", "--home", str(self.root), "install", "--profile", "core", "--offline", "--base-url", "http://127.0.0.1:8080/v1", "--model", "local-test"], cwd=home.ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "scaffolded")
        report = subprocess.run([sys.executable, str(self.root / "agent-home.py"), "doctor"], cwd=self.temporary.name, capture_output=True, text=True)
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertEqual(json.loads(report.stdout)["home"], str(self.root))
        settings = json.loads((self.root / "agent/settings.json").read_text())
        self.assertEqual(settings["enabledModels"], ["local/*"])
        self.assertNotIn("bash", settings["defaultTools"])
        for relative in ("home.json", "context/profile.md", "agent/models.json", "memory/imports/private.jsonl", "agent/sessions/raw.jsonl", "agent/settings.json"):
            checked = subprocess.run(["git", "check-ignore", relative], cwd=self.root, capture_output=True)
            self.assertEqual(checked.returncode, 0, relative)
        self.assertTrue((self.root / "agent/prompts/personalize.md").is_file())
        skill = (self.root / "agent/skills/source-control/SKILL.md").read_text()
        self.assertIn(self.root.as_posix(), skill)
        self.assertNotIn("{{HOME}}", skill)
        self.assertTrue((self.root / "runtime/harness/source_checkpoint.py").is_file())
        self.assertTrue((self.root / "runtime/harness/managed_launch.py").is_file())
        self.assertTrue(home.managed_launch.command_file(self.root / "bin", "harness-agent").is_file())
        projector = self.root / "runtime/adapters/pi/project-workflow/kanban-reply-projector.mjs"
        self.assertEqual(projector.read_bytes(), (home.ROOT / "adapters/pi/project-workflow/kanban-reply-projector.mjs").read_bytes())
        manifest = json.loads((self.root / "runtime/runtime-manifest.json").read_text())
        self.assertTrue(any(item["path"] == "adapters/pi/project-workflow/kanban-reply-projector.mjs" for item in manifest["files"]))
        self.assertEqual(subprocess.check_output(["git", "diff", "--cached", "--name-only"], cwd=self.root), b"")

    def test_existing_target_is_never_overwritten(self):
        self.root.mkdir()
        marker = self.root / "AGENTS.md"
        marker.write_text("Keep original identity")
        with self.assertRaises(home.HomeError):
            self.create()
        self.assertEqual(marker.read_text(), "Keep original identity")
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_incomplete_template_bundle_refuses_before_home_creation(self):
        source = Path(self.temporary.name) / "incomplete checkout"
        adapter = source / "adapters/pi/project-workflow/pi_kanban.py"
        adapter.parent.mkdir(parents=True)
        adapter.write_text("# Source presence alone does not prove a complete template bundle\n")
        template = source / "harness/templates/agent-home/AGENTS.md"
        template.parent.mkdir(parents=True)
        template.write_text("# Root routing without its context targets\n")
        with self.assertRaisesRegex(home.HomeError, "templates are missing"):
            home.scaffold(self.root, source=source, profile="core", base_url="http://127.0.0.1:8080/v1", model="test", offline=True)
        self.assertFalse(self.root.exists())

    def test_owner_name_survives_runtime_guard_copy(self):
        config = self.create()
        self.assertEqual(config["name"], "Test Owner")
        self.assertIn("Owner: Test Owner.", (self.root / "context/profile.md").read_text())
        self.assertNotIn("pi_native_events.py", (self.root / "AGENTS.md").read_text())

    def test_endpoint_credentials_rejected_before_home_creation(self):
        with self.assertRaises(home.HomeError):
            home.scaffold(self.root, base_url="https://user:secret@example.org/v1", model="test", offline=True)
        self.assertFalse(self.root.exists())

    def test_runtime_drift_refuses_launch(self):
        self.create()
        file = self.root / "runtime/harness/enforcement.py"
        file.write_text(file.read_text() + "\n# changed\n")
        report = home.doctor(self.root)
        self.assertEqual(report["status"], "failed")
        self.assertIn("runtime source changed: harness/enforcement.py", report["failures"])
        with self.assertRaises(home.HomeError):
            home.launch(self.root, [])

    def test_missing_packages_are_not_reported_installed(self):
        home.scaffold(self.root, profile="full", base_url="http://localhost:8080/v1", model="test", offline=True)
        report = home.doctor(self.root)
        self.assertIn("package not installed: claude-mem", report["failures"])
        self.assertEqual(report["authority"], "none")
        settings = json.loads((self.root / "agent/settings.json").read_text())
        self.assertTrue(any(path.endswith("pi-kanban.ts") for path in settings["extensions"]))
        mcp = json.loads((self.root / "agent/mcp.json").read_text())["mcpServers"]["mempalace"]
        self.assertEqual(mcp["exposure"], "deferred")
        self.assertEqual(mcp["env"]["MEMPALACE_CONFIG_DIR"], str(self.root / "state/mempalace-config"))
        self.assertEqual(mcp["args"][-3:], ["--home", str(self.root), "mcp"])

    def test_installed_label_does_not_hide_missing_package(self):
        home.scaffold(self.root, profile="pi", base_url="http://localhost:8080/v1", model="test", offline=True)
        _, config = home.load(self.root)
        config["installed"]["pi"] = {"requested": home.PINS["pi"], "artifacts": [{"path": str(self.root / "packages/pi/missing.json"), "sha256": "0" * 64}]}
        home.save_status(self.root, config)
        self.assertIn("installed package missing or changed: pi", home.doctor(self.root)["failures"])

    def test_moved_home_identity_requires_explicit_migration(self):
        self.create()
        moved = self.root.with_name("moved")
        self.root.rename(moved)
        with self.assertRaises(home.HomeError):
            home.doctor(moved)

    def test_output_timeout_retains_failure_log_without_replay(self):
        self.root.mkdir()
        with self.assertRaisesRegex(home.HomeError, "Timed out"):
            home.run([sys.executable, "-c", "import time;print('before',flush=True);time.sleep(20)"], cwd=self.root, timeout=0.2)
        logs = [path for path in (self.root / "logs").glob("command-*.log") if not path.name.endswith(".stderr.log")]
        self.assertEqual(len(logs), 1)
        self.assertIn("before", logs[0].read_text())

    def test_backend_warning_does_not_corrupt_structured_stdout(self):
        self.root.mkdir()
        output = home.run([sys.executable, "-c", "import json,sys;print('backend warning',file=sys.stderr);print(json.dumps({'ok':True}))"], cwd=self.root)
        self.assertEqual(json.loads(output), {"ok": True})
        self.assertTrue(any("backend warning" in path.read_text() for path in (self.root / "logs").glob("*.stderr.log")))


if __name__ == "__main__":
    unittest.main()
