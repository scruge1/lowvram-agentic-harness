"""Offline identity and independent-answer controls; native demo is separate."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from harness import home as factory


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("harness_lab_fixture", ROOT / "adapters/pi/lab/harness_lab.py")
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


class AnswersTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=os.environ.get("HARNESS_LAB_TEST_ROOT"))
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / "demo.json").write_text(json.dumps({"done": 2, "failed": 0}), encoding="utf-8")
        for task, amounts, total in (("ledger-1", ["100.25", "-20.10", "5.00"], "85.15"),
                                     ("ledger-2", ["35.50", "-10.25", "-5.00"], "20.25")):
            source = self.root / "sources" / task
            source.mkdir(parents=True)
            (source / "ledger.csv").write_text("amount\n" + "\n".join(amounts) + "\n", encoding="utf-8")
            selections = {}
            for mode in ("agg", "seq"):
                run = self.root / "executions" / task / mode
                run.mkdir(parents=True)
                (run / "answer.txt").write_text("Total: " + total + "\n", encoding="utf-8")
                selections[mode] = {"chosen_run_dir": str(run)}
            run = self.root / "runs" / task
            run.mkdir(parents=True)
            (run / "summary.json").write_text(json.dumps({"task_id": task, "status": "ok", "selections": selections}), encoding="utf-8")

    def test_independent_signed_answers_both_native_modes(self):
        value = lab.check_answers(self.root)
        self.assertEqual(set(value), {"ledger-1", "ledger-2"})
        self.assertEqual(value["ledger-1"]["agg"]["expected"], "Total: 85.15")

    def test_upstream_done_alone_does_not_accept_wrong_signed_answer(self):
        (self.root / "executions/ledger-1/agg/answer.txt").write_text("Total: 105.25\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "signed amount"):
            lab.check_answers(self.root)

    def test_changed_input_cannot_make_wrong_answer_pass(self):
        (self.root / "sources/ledger-1/ledger.csv").write_text("amount\n100.25\n0\n5.00\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "input changed"):
            lab.check_answers(self.root)

    def test_missing_mode_and_escaped_selection_refuse(self):
        path = self.root / "runs/ledger-1/summary.json"
        original = path.read_bytes()
        value = json.loads(original)
        del value["selections"]["seq"]
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Both native"):
            lab.check_answers(self.root)
        value = json.loads(original)
        value["selections"]["agg"]["chosen_run_dir"] = str(self.root.parent)
        path.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "outside"):
            lab.check_answers(self.root)

    def test_child_environment_does_not_copy_auth_proxy_or_python_overrides(self):
        with mock.patch.dict(os.environ, {"EXA_API_KEY": "synthetic", "HTTP_PROXY": "synthetic", "PYTHONPATH": "synthetic",
                                          "NODE_OPTIONS": "synthetic", "GIT_CONFIG_GLOBAL": "synthetic"}):
            result = lab.environment(self.root)
        self.assertFalse({"EXA_API_KEY", "HTTP_PROXY", "PYTHONPATH", "NODE_OPTIONS"} & result.keys())
        self.assertEqual(result["GIT_CONFIG_GLOBAL"], os.devnull)
        self.assertEqual(result["CUDA_VISIBLE_DEVICES"], "")

    def test_missing_package_refuses_before_demo_child_or_run_creation(self):
        with mock.patch.object(lab, "status", side_effect=ValueError("missing package")), \
                mock.patch.object(lab.subprocess, "run") as launch:
            with self.assertRaisesRegex(ValueError, "missing package"):
                lab.demo(self.root)
        launch.assert_not_called()
        self.assertFalse((self.root / "state").exists())


@unittest.skipUnless(shutil.which("git"), "Git is a documented installer prerequisite")
class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(dir=os.environ.get("HARNESS_LAB_TEST_ROOT"))
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name).resolve() / "agent home"
        factory.scaffold(self.home, source=ROOT, profile="full", base_url="http://127.0.0.1:9/v1",
                         model="inert-source-fixture", offline=True)
        checkout = self.home / "packages/harness2-source"
        (checkout / "harness2/cli").mkdir(parents=True)
        for relative in ("demo.py", "cli/demo.py"):
            path = checkout / "harness2" / relative
            path.write_text("# synthetic source-only identity fixture\n", encoding="utf-8")
        env = lab.environment(self.home)
        subprocess.run(["git", "init", "--quiet", str(checkout)], check=True, env=env)
        subprocess.run(["git", "-C", str(checkout), "add", "."], check=True, env=env)
        subprocess.run(["git", "-C", str(checkout), "-c", "user.name=Source fixture", "-c", "user.email=fixture@example.invalid",
                        "commit", "--quiet", "-m", "Synthetic source identity"], check=True, env=env)
        commit = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], check=True, env=env,
                                capture_output=True, text=True).stdout.strip()
        patch = mock.patch.dict(factory.GIT_SOURCES, {"harness2": ("https://example.invalid/synthetic", commit)})
        patch.start()
        self.addCleanup(patch.stop)
        site = self.home / "envs/harness2/lib/site-packages"
        shutil.copytree(checkout / "harness2", site / "harness2")
        self.metadata = site / "harness2-0.1.dist-info"
        self.metadata.mkdir()
        (self.metadata / "METADATA").write_text("Synthetic fixture", encoding="utf-8")
        (self.metadata / "direct_url.json").write_text(json.dumps({"url": checkout.as_uri(), "dir_info": {}}), encoding="utf-8")
        package = self.home / "packages/deepseek/node_modules/@deepseek-ai/dsh/package.json"
        package.parent.mkdir(parents=True)
        package.write_text(json.dumps({"version": "0.2.1-rc.2"}), encoding="utf-8")
        self.config = json.loads((self.home / "home.json").read_text(encoding="utf-8"))
        for key, files in (("harness2", [self.metadata / "METADATA", self.metadata / "direct_url.json"]),
                           ("deepseek", [package])):
            self.config["installed"][key] = {"requested": factory.PINS[key], "artifacts":
                                              [{"path": str(path), "sha256": lab.sha(path)} for path in files]}
        self.save()

    def save(self):
        (self.home / "home.json").write_text(json.dumps(self.config), encoding="utf-8")

    def test_exact_local_checkout_recorded_artifacts_and_native_source(self):
        result = lab.status(self.home)
        self.assertTrue(result["ok"])
        self.assertEqual(result["components"]["harness2"]["verified_code_files"], 2)
        self.assertEqual(result["model_calls"], 0)

    def test_full_profile_wiring_and_agent_profile_exclusion(self):
        settings = json.loads((self.home / "agent/settings.json").read_text(encoding="utf-8"))
        self.assertIn(str(self.home / "runtime/adapters/pi/lab/harness-lab.ts"), settings["extensions"])
        with mock.patch.dict(os.environ, {}, clear=True):
            value = factory.environment(self.home)
            self.assertEqual(value["PI_HARNESS_LAB_HELPER_SHA256"], lab.sha(self.home / "runtime" / lab.RELATIVE))
            self.assertNotIn("PI_HARNESS_LAB_COMMAND", value, "Missing owned Python must not gain an ambient fallback")
            self.config["profile"] = "agent"
            self.save()
            value = factory.environment(self.home)
            self.assertFalse(any(key.startswith("PI_HARNESS_LAB_") for key in value))

    def test_optional_profile_and_wrong_pin_refuse_before_git(self):
        with mock.patch.object(lab.subprocess, "run") as child:
            for mutate in (lambda: self.config.update(profile="agent"),
                           lambda: self.config["selected_packages"].update(harness2="different")):
                original = json.dumps(self.config)
                mutate()
                self.save()
                with self.assertRaisesRegex(ValueError, "full package"):
                    lab.status(self.home)
                self.config = json.loads(original)
            child.assert_not_called()

    def test_missing_and_drifted_recorded_artifacts_refuse(self):
        original = self.metadata.joinpath("METADATA").read_bytes()
        for value in (None, b"changed"):
            path = self.metadata / "METADATA"
            if value is None:
                path.unlink()
            else:
                path.write_bytes(value)
            with self.assertRaisesRegex(ValueError, "artifacts changed"):
                lab.status(self.home)
            path.write_bytes(original)

    def test_changed_installed_demo_refuses(self):
        (self.metadata.parent / "harness2/demo.py").write_text("# changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "differs from its pinned source"):
            lab.status(self.home)

    def test_foreign_direct_url_and_checkout_commit_refuse(self):
        direct = self.metadata / "direct_url.json"
        direct.write_text(json.dumps({"url": "https://example.invalid/not-owned"}), encoding="utf-8")
        record = self.config["installed"]["harness2"]["artifacts"][1]
        record["sha256"] = lab.sha(direct)
        self.save()
        with self.assertRaisesRegex(ValueError, "pinned source checkout"):
            lab.status(self.home)


if __name__ == "__main__":
    unittest.main()
