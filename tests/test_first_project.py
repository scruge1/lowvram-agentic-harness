"""Actual Git/file/CLI checks for the report slice; no model or service calls."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness import first_project, hardware_probe, home, onboarding


def fixture_board(_home, request):
    # Normal home.project admission creates this required surface. Board/package
    # ownership remains an explicit fixture in these source/file tests.
    workspace = Path(request["project_root"]) / ".icm/workspace"
    workspace.mkdir(parents=True)
    (workspace / "PROJECT-SSOT.md").write_text("# Synthetic existing workspace\n\nKeep this original route.\n", encoding="utf-8")
    return {"fixture_board_admission": True}


class FirstProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.home = self.root / "agent home"
        (self.home / "projects").mkdir(parents=True)
        (self.home / "agent").mkdir()
        (self.home / "home.json").write_text(json.dumps({
            "schema": "agent-home/v1", "home": str(self.home),
            "model": "public-test-model", "installed": {"hermes": {"fixture": True}},
        }))
        (self.home / "agent/models.json").write_text(json.dumps({"providers": {"local": {"models": [
            {"id": "public-test-model", "contextWindow": 32768, "maxTokens": 4096},
        ]}}}))
        self.observed = {
            "observed_at": "2026-01-02T03:04:05Z", "system": {"platform": "test fixture"},
            "hardware": {"gpu": {"available": True, "name": "Fixture GPU", "vram_total_mb": 24576},
                         "ram": {"total_gb": 32.5}},
            "storage": {"total_bytes": 1_000_000_000_000, "measured_existing_path": str(self.home)},
            "limits": ["Fixture observations only; no model-fit qualification."],
        }

    def prepare(self, name="hardware-report"):
        # This test exercises real home.project and Git. Package admission and
        # board transport are explicit fixtures, not actual Hermes acceptance.
        with mock.patch.object(onboarding, "inventory", return_value=self.observed) as inventory, \
             mock.patch.object(home, "check_package", return_value=None), \
             mock.patch.object(home, "board", side_effect=fixture_board) as board:
            result = first_project.prepare(self.home, name)
        inventory.assert_called_once_with(self.home / "projects")
        self.assertEqual(board.call_count, 1)
        self.assertEqual(board.call_args.args[1]["action"], "project_admit")
        self.assertIs(board.call_args.args[1]["initialize"], True)
        project = Path(result["project_root"])
        self.assertTrue((project / ".git").is_dir())
        self.assertTrue((project / "AGENTS.md").is_file())
        self.assertEqual(subprocess.run(["git", "-C", str(project), "rev-parse", "--is-inside-work-tree"],
                                        capture_output=True, text=True, check=True).stdout.strip(), "true")
        return project, result

    def write_report(self, project, words=300):
        facts = json.loads((project / "hardware-facts.json").read_text())
        rows = first_project._rows(facts)
        text = "# Hardware report\n\nSource: hardware-facts.json.\n\n| Measurement | Value | Unit |\n| --- | --- | --- |\n"
        for row in rows:
            value = "unknown" if row["value"] is None else str(row["value"])
            text += "| " + row["label"] + " | " + value + " | " + row["unit"] + " |\n"
        text += ("\nThis synthetic checker fixture is not real model evidence. "
                 "Configured metadata is not a running service or hardware-fit qualification. "
                 "Unknown facts remain unknown. Semantic review is separate.\n")
        text += " inventory" * (words - first_project.word_count(text))
        (project / "hardware-report.md").write_text(text, encoding="utf-8")
        return text

    def check(self, project, result):
        return first_project.check(project, result["manifest_sha256"])

    def test_prepare_reuses_real_git_project_and_records_actual_source_bytes(self):
        before_home = os.environ.get("HOME")
        project, result = self.prepare()
        facts = json.loads((project / "hardware-facts.json").read_text())
        self.assertEqual(facts["sources"]["hardware_probe"]["sha256"],
                         hashlib.sha256(Path(hardware_probe.__file__).read_bytes()).hexdigest())
        self.assertEqual(result["model_requests"], 0)
        self.assertEqual(result["semantic_review"], "required_after_real_report")
        self.assertEqual(result["check_argv"][-2:], ["--expected-sha256", result["manifest_sha256"]])
        self.assertEqual(os.environ.get("HOME"), before_home)
        self.assertFalse((project / "hardware-report.md").exists())

    def test_actual_onboarding_inventory_is_read_only_and_no_service_probe(self):
        with mock.patch.object(onboarding, "probe_service", side_effect=AssertionError("No model endpoint")):
            observation = onboarding.inventory(self.home / "projects")
        self.assertEqual(observation["changes"], [])
        self.assertGreater(observation["storage"]["total_bytes"], 0)
        self.assertIn("total_gb", observation["hardware"]["ram"])

    def test_generated_template_and_task_body_use_existing_context_routes(self):
        project, result = self.prepare()
        instructions = (project / "FIRST-PROJECT.md").read_text(encoding="utf-8")
        template = json.loads(instructions.split("Action argv TEMPLATE JSON:\n", 1)[1].split("\n", 1)[0])
        self.assertEqual(template, result["action_argv_template"])
        self.assertEqual(template[0], result["check_argv"][0])
        self.assertEqual(template[1:4], ["-I", "-B", "-c"])
        route = (project / ".icm/workspace/PROJECT-SSOT.md").read_text(encoding="utf-8")
        self.assertTrue(route.startswith("# Synthetic existing workspace\n\nKeep this original route.\n"))
        self.assertIn(instructions, route)
        self.assertLess(len((project / "AGENTS.md").read_bytes()), 1024)
        self.assertIn("it is NOT a report writer", instructions)
        self.assertEqual(set(first_project.INPUTS), {"hardware-facts.json", "FIRST-PROJECT.md"})

    def test_generated_writer_executes_literal_complete_argv_without_shell_and_refuses_overwrite(self):
        project, result = self.prepare()
        template = json.loads((project / "FIRST-PROJECT.md").read_text(encoding="utf-8")
                              .split("Action argv TEMPLATE JSON:\n", 1)[1].split("\n", 1)[0])
        body = ('# Synthetic writer fixture\n\n"double" and \'single\' quotes.\n'
                '$HOME $(touch shell-effect) `touch shell-effect`\n'
                "__import__('pathlib').Path('shell-effect').write_text('bad')\n"
                'Unicode: 漢字🙂 café. Backslash: \\ and literal dollars: $$.\r\nFinal line.\n')
        before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
        command = template[:-1] + [body]
        ran = subprocess.run(command, cwd=project, shell=False, capture_output=True, stdin=subprocess.DEVNULL, timeout=10)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        output = project / "hardware-report.md"
        self.assertEqual(output.read_bytes(), body.encode("utf-8"))
        self.assertFalse((project / "shell-effect").exists())
        for relative, raw in before.items():
            self.assertEqual((project / relative).read_bytes(), raw)
        occupied = subprocess.run(template[:-1] + ["Replacement must not overwrite."], cwd=project, shell=False,
                                  capture_output=True, stdin=subprocess.DEVNULL, timeout=10)
        self.assertNotEqual(occupied.returncode, 0)
        self.assertEqual(output.read_bytes(), body.encode("utf-8"))

    def test_writer_placeholder_or_missing_body_does_not_create_a_report(self):
        project, result = self.prepare()
        template = result["action_argv_template"]
        for command in (template, template[:-1]):
            ran = subprocess.run(command, cwd=project, shell=False, capture_output=True, stdin=subprocess.DEVNULL, timeout=10)
            self.assertNotEqual(ran.returncode, 0)
            self.assertFalse((project / "hardware-report.md").exists())

    def repair(self, project, result, expected, body, prefix=""):
        template = result["repair_action_argv_template"]
        return subprocess.run(template[:4] + [prefix + template[4], expected, body], cwd=project,
                              shell=False, capture_output=True, stdin=subprocess.DEVNULL, timeout=10)

    @unittest.skipUnless(sys.platform == "linux", "Qualified repair uses a Linux directory flock")
    def test_repair_retains_failed_bytes_and_original_checker_and_inputs(self):
        project, result = self.prepare()
        body = self.write_report(project)
        output = project / first_project.OUTPUT
        old = b"Short synthetic failed report.\n"
        output.write_bytes(old)
        before = {name: (project / name).read_bytes() for name in (*first_project.INPUTS, first_project.MANIFEST)}
        expected = hashlib.sha256(old).hexdigest()
        instructions = (project / "FIRST-PROJECT.md").read_text(encoding="utf-8")
        declared = json.loads(instructions.split("Recovery action argv TEMPLATE JSON:\n", 1)[1].split("\n", 1)[0])
        self.assertEqual(declared, result["repair_action_argv_template"])
        ran = self.repair(project, result, expected, body)
        self.assertEqual(ran.returncode, 0, ran.stderr)
        self.assertEqual(output.read_bytes(), body.encode("utf-8"))
        self.assertEqual((project / ("hardware-report.failed-" + expected + ".md")).read_bytes(), old)
        self.assertFalse((project / (".hardware-report.repair-" + expected + ".tmp")).exists())
        self.assertTrue(self.check(project, result)["passed"])
        self.assertFalse(first_project.check(self.root, result["manifest_sha256"])["passed"])
        for name, raw in before.items():
            self.assertEqual((project / name).read_bytes(), raw)

    @unittest.skipUnless(sys.platform == "linux", "Qualified repair uses a Linux directory flock")
    def test_repair_stale_preimage_and_occupied_backup_or_stage_preserve_files(self):
        project, result = self.prepare()
        output = project / first_project.OUTPUT
        output.write_bytes(b"Retained failure")
        expected = hashlib.sha256(output.read_bytes()).hexdigest()
        self.assertNotEqual(self.repair(project, result, "0" * 64, "corrected").returncode, 0)
        self.assertEqual(sorted(p.name for p in project.glob("*failed*")), [])
        for name in ("hardware-report.failed-" + expected + ".md", ".hardware-report.repair-" + expected + ".tmp"):
            with self.subTest(name=name):
                occupied = project / name
                occupied.write_bytes(b"Uncertain prior action; preserve")
                before = {p.name: p.read_bytes() for p in project.iterdir() if p.is_file()}
                self.assertNotEqual(self.repair(project, result, expected, "corrected").returncode, 0)
                self.assertEqual({p.name: p.read_bytes() for p in project.iterdir() if p.is_file()}, before)
                occupied.unlink()  # Owned fixture only, not a product recovery route.

    @unittest.skipUnless(sys.platform == "linux", "Qualified repair uses a Linux directory flock")
    def test_repair_symlink_hardlink_and_oversize_refuse_without_new_artifacts(self):
        project, result = self.prepare()
        output = project / first_project.OUTPUT
        outside = self.root / "synthetic-source.md"
        outside.write_bytes(b"Retain this source")
        expected = hashlib.sha256(outside.read_bytes()).hexdigest()
        for mode in ("symlink", "hardlink", "oversize"):
            with self.subTest(mode=mode):
                if mode == "symlink":
                    output.symlink_to(outside)
                elif mode == "hardlink":
                    os.link(outside, output)
                else:
                    output.write_bytes(b"x" * (first_project.MAX_BYTES + 1))
                self.assertNotEqual(self.repair(project, result, expected, "corrected").returncode, 0)
                self.assertEqual(outside.read_bytes(), b"Retain this source")
                self.assertFalse((project / ("hardware-report.failed-" + expected + ".md")).exists())
                output.unlink()

    @unittest.skipUnless(sys.platform == "linux", "Qualified repair uses a Linux directory flock")
    def test_repair_rechecks_preimage_and_retains_staging_after_observed_drift(self):
        project, result = self.prepare()
        output = project / first_project.OUTPUT
        output.write_bytes(b"original failure")
        expected = hashlib.sha256(output.read_bytes()).hexdigest()
        # Explicit unit-only fault: change the preimage after the stage fsync.
        prefix = ("import os\nfrom pathlib import Path\n_real_fsync=os.fsync\n_calls=0\n"
                  "def _fault(fd):\n    global _calls\n    _real_fsync(fd)\n    _calls+=1\n"
                  "    if _calls==2: Path('hardware-report.md').write_bytes(b'observed drift')\n"
                  "os.fsync=_fault\n")
        ran = self.repair(project, result, expected, "corrected body", prefix)
        self.assertNotEqual(ran.returncode, 0)
        self.assertIn(b"preimage changed", ran.stderr)
        self.assertEqual(output.read_bytes(), b"observed drift")
        self.assertEqual((project / ("hardware-report.failed-" + expected + ".md")).read_bytes(), b"original failure")
        self.assertEqual((project / (".hardware-report.repair-" + expected + ".tmp")).read_bytes(), b"corrected body")

    @unittest.skipUnless(sys.platform == "linux", "Qualified repair uses Linux file permissions")
    def test_repair_keeps_backup_stage_and_replacement_private_under_permissive_umask(self):
        for interrupted in (False, True):
            with self.subTest(interrupted=interrupted):
                project, result = self.prepare("private-interrupted" if interrupted else "private-success")
                output = project / first_project.OUTPUT
                output.write_bytes(b"private synthetic failed report")
                output.chmod(0o600)
                expected = hashlib.sha256(output.read_bytes()).hexdigest()
                prefix = "import os\nos.umask(0)\n"
                if interrupted:
                    prefix += ("_real_fsync=os.fsync\n_calls=0\n"
                               "def _fault(fd):\n    global _calls\n    _real_fsync(fd)\n    _calls+=1\n"
                               "    if _calls==2: raise OSError('controlled failure after stage fsync')\n"
                               "os.fsync=_fault\n")
                ran = self.repair(project, result, expected, "new private synthetic report", prefix)
                self.assertEqual(ran.returncode == 0, not interrupted, ran.stderr)
                backup = project / ("hardware-report.failed-" + expected + ".md")
                self.assertEqual(backup.read_bytes(), b"private synthetic failed report")
                for path in (output, backup):
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                stage = project / (".hardware-report.repair-" + expected + ".tmp")
                if interrupted:
                    self.assertEqual(output.read_bytes(), b"private synthetic failed report")
                    self.assertEqual(stage.read_bytes(), b"new private synthetic report")
                    self.assertEqual(stage.stat().st_mode & 0o777, 0o600)
                else:
                    self.assertEqual(output.read_bytes(), b"new private synthetic report")
                    self.assertFalse(stage.exists())

    @unittest.skipUnless(sys.platform == "linux", "Qualified repair uses a Linux directory flock")
    def test_directory_lease_blocks_generated_initial_and_repair_writers(self):
        import fcntl
        project, result = self.prepare()
        directory = os.open(project, os.O_RDONLY | os.O_DIRECTORY)
        try:
            fcntl.flock(directory, fcntl.LOCK_EX | fcntl.LOCK_NB)
            initial = subprocess.run(result["action_argv_template"][:-1] + ["body"], cwd=project,
                                     shell=False, capture_output=True, timeout=10)
            self.assertNotEqual(initial.returncode, 0)
            self.assertFalse((project / first_project.OUTPUT).exists())
            (project / first_project.OUTPUT).write_bytes(b"failed")
            self.assertNotEqual(self.repair(project, result, hashlib.sha256(b"failed").hexdigest(), "body").returncode, 0)
            self.assertEqual((project / first_project.OUTPUT).read_bytes(), b"failed")
        finally:
            os.close(directory)

    def test_repair_invalid_arguments_and_unsupported_platform_do_not_write(self):
        project, result = self.prepare()
        source = result["repair_action_argv_template"]
        prefix = "import sys\nsys.platform='unsupported-fixture'\n"
        commands = [source, source[:4] + [prefix + source[4], "0" * 64, "body"]]
        for command in commands:
            ran = subprocess.run(command, cwd=project, shell=False, capture_output=True, timeout=10)
            self.assertNotEqual(ran.returncode, 0)
        self.assertFalse((project / first_project.OUTPUT).exists())

    def test_generated_writer_refuses_a_dangling_symlink_without_touching_its_target(self):
        project, result = self.prepare()
        target = self.root / "uncreated-target.md"
        output = project / "hardware-report.md"
        try:
            output.symlink_to(target)
        except OSError:
            self.skipTest("This platform does not permit owned symlink creation")
        ran = subprocess.run(result["action_argv_template"][:-1] + ["Synthetic body"], cwd=project,
                             shell=False, capture_output=True, stdin=subprocess.DEVNULL, timeout=10)
        self.assertNotEqual(ran.returncode, 0)
        self.assertTrue(output.is_symlink())
        self.assertFalse(target.exists())

    def test_missing_normal_workspace_refuses_instead_of_inventing_a_route(self):
        with mock.patch.object(onboarding, "inventory", return_value=self.observed), \
             mock.patch.object(home, "check_package", return_value=None), \
             mock.patch.object(home, "board", return_value={"fixture_missing_workspace": True}):
            with self.assertRaisesRegex(ValueError, "existing normal instruction route"):
                first_project.prepare(self.home, "missing-workspace")
        project = self.home / "projects/missing-workspace"
        self.assertTrue((project / ".git").is_dir())
        self.assertFalse((project / "FIRST-PROJECT.md").exists())
        self.assertFalse((project / ".icm/workspace").exists())

    def test_prepare_refuses_occupied_project_before_observation_or_changes(self):
        project = self.home / "projects/existing"
        project.mkdir()
        (project / "keep").write_bytes(b"retained")
        with mock.patch.object(onboarding, "inventory") as inventory:
            with self.assertRaisesRegex(ValueError, "already exists"):
                first_project.prepare(self.home, "existing")
        inventory.assert_not_called()
        self.assertEqual((project / "keep").read_bytes(), b"retained")

    def test_unknown_observations_and_unmatched_caps_stay_unknown(self):
        self.observed["hardware"] = {"gpu": {"available": False, "name": None}, "ram": {"total_gb": None}}
        (self.home / "agent/models.json").write_text('{"providers":{"local":{"models":[]}}}')
        project, result = self.prepare()
        facts = json.loads((project / "hardware-facts.json").read_text())
        self.assertIsNone(facts["ram_total_gb"])
        self.assertIsNone(facts["gpu_vram_mib"])
        self.assertIsNone(facts["configured_model"]["context_tokens"])
        self.write_report(project)
        self.assertTrue(self.check(project, result)["passed"])
        output = project / "hardware-report.md"
        output.write_text(output.read_text().replace("| GPU VRAM | unknown |", "| GPU VRAM | 8192 |"))
        self.assertFalse(self.check(project, result)["passed"])

    def test_exact_word_bounds_and_markup_count(self):
        self.assertEqual(first_project.word_count("# Read-only report\n| GPU | 24,576 | MiB |\nExact source hardware-facts.json."), 8)
        project, result = self.prepare()
        for words, passed in [(249, False), (250, True), (400, True), (401, False)]:
            with self.subTest(words=words):
                self.write_report(project, words)
                checked = self.check(project, result)
                self.assertEqual(checked["word_count"], words)
                self.assertEqual(checked["passed"], passed)

    def test_wrong_numeric_values_units_duplicate_rows_and_missing_source_refuse(self):
        project, result = self.prepare()
        original = self.write_report(project)
        bad = [original.replace("| 24576 |", "| 8192 |"),
               original.replace("| 24576 | MiB |", "| 24576 | MB |"),
               original.replace("| 32.5 | GB (decimal) |", "| 32.5 | GiB |"),
               original.replace("| 32768 | tokens |", "| 32,76,8 | tokens |"),
               original + "\n| GPU VRAM | 24576 | MiB |\n",
               original.replace("hardware-facts.json", "unsupported-source")]
        for text in bad:
            with self.subTest(text=text[:60]):
                (project / "hardware-report.md").write_text(text)
                self.assertFalse(self.check(project, result)["passed"])
        (project / "hardware-report.md").write_text(original.replace("| 24576 |", "| 24,576 |"))
        self.assertTrue(self.check(project, result)["passed"])

    def test_input_and_contract_tamper_refuse(self):
        project, result = self.prepare()
        self.write_report(project)
        facts = project / "hardware-facts.json"
        original = facts.read_bytes()
        facts.write_bytes(original + b"\n")
        self.assertFalse(self.check(project, result)["passed"])
        facts.write_bytes(original)
        contract = project / "first-project.json"
        contract.write_bytes(contract.read_bytes() + b"\n")
        self.assertIn("manifest byte drift", self.check(project, result)["error"])

    def test_checker_does_not_infer_tuner_execution_from_english(self):
        project, result = self.prepare()
        original = self.write_report(project)
        for sentence in ["It was NOT run here.", "The tuner was run."]:
            (project / "hardware-report.md").write_text(original + "\n" + sentence)
            checked = self.check(project, result)
            self.assertTrue(checked["passed"])
            self.assertEqual(checked["semantic_review"], "required")
            self.assertEqual(checked["tuner_execution"], "not_observed_by_this_checker")

    def test_actual_readonly_cli_and_empty_cwd_negative_control(self):
        project, result = self.prepare()
        self.write_report(project)
        before = {str(path.relative_to(project)): path.read_bytes() for path in project.rglob("*") if path.is_file()}
        command = result["check_argv"]
        positive = subprocess.run(command, cwd=project, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=10)
        self.assertEqual(positive.returncode, 0, positive.stderr)
        self.assertTrue(json.loads(positive.stdout)["passed"])
        after = {str(path.relative_to(project)): path.read_bytes() for path in project.rglob("*") if path.is_file()}
        self.assertEqual(before, after)
        empty = self.root / "empty"
        empty.mkdir()
        negative = subprocess.run(command, cwd=empty, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=10)
        self.assertEqual(negative.returncode, 1, negative.stderr)
        self.assertFalse(json.loads(negative.stdout)["passed"])
        self.assertEqual(list(empty.iterdir()), [])

    def test_checker_reports_malformed_or_oversize_file_as_structured_failure(self):
        project, result = self.prepare()
        self.write_report(project)
        output = project / "hardware-report.md"
        output.write_bytes(b"x" * (first_project.MAX_BYTES + 1))
        self.assertIn("64 KiB", self.check(project, result)["error"])
        contract = project / "first-project.json"
        contract.write_text("[]")
        malformed = first_project.check(project, hashlib.sha256(contract.read_bytes()).hexdigest())
        self.assertFalse(malformed["passed"])
        self.assertIn("Unsupported", malformed["error"])

    def test_redirected_project_directory_and_report_are_refused(self):
        outside = self.root / "outside"
        outside.mkdir()
        projects = self.home / "projects"
        projects.rmdir()
        try:
            projects.symlink_to(outside, target_is_directory=True)
        except OSError:
            projects.mkdir()
            self.skipTest("This platform does not permit owned symlink creation")
        with self.assertRaisesRegex(ValueError, "without redirection"):
            first_project.prepare(self.home, "escaped")
        self.assertEqual(list(outside.iterdir()), [])
        projects.unlink()
        projects.mkdir()
        project, result = self.prepare()
        text = self.write_report(project)
        output = project / "hardware-report.md"
        output.unlink()
        target = outside / "report.md"
        target.write_text(text)
        output.symlink_to(target)
        self.assertIn("redirected", self.check(project, result)["error"])


if __name__ == "__main__":
    unittest.main()
