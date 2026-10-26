"""Finite CPU installer composition; no downloads, service starts or inference."""
import contextlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from harness import bootstrap as b, hardware_probe, model_service, model_service_handoff, model_service_setup


class LocalCpuBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "new agent"
        self.root = Path(str(self.home) + "-runtimes")
        self.receipt = {"home": str(self.home), "runtime_root": str(self.root),
                        "python": {"path": str(self.root / "python/bin/python3.12")},
                        "node": {"path": str(self.root / "node/bin/node")}}

    def tearDown(self):
        self.temp.cleanup()

    @contextlib.contextmanager
    def capacity(self, *, memory=30, free=30 * 1024 ** 3, cpus=8):
        with patch.object(model_service.sys, "platform", "linux"), \
                patch.object(model_service.platform, "machine", return_value="x86_64"), \
                patch.object(hardware_probe, "ram_info", return_value={"available_gb": memory}), \
                patch.object(b.os, "sched_getaffinity", return_value=set(range(cpus)), create=True), \
                patch.object(model_service.shutil, "disk_usage", return_value=shutil._ntuple_diskusage(free, 0, free)):
            yield

    def runtime_marker(self):
        self.root.mkdir()
        (self.root / "bootstrap-owner").write_text("agent-home-bootstrap/v1:" + str(self.home))

    def test_authoritative_plan_is_no_effects_and_uses_real_canonical_pins(self):
        with self.capacity():
            result = b.local_cpu_plan(self.home)
        pins = json.loads(model_service.PINS.read_text())
        spec = result["specification"]
        self.assertEqual(spec["model"], pins["model"])
        self.assertEqual(spec["runtime"]["archives"], pins["runtime"]["cpu"])
        self.assertEqual(spec["resources"], {"context": 32768, "max_output": 4096,
                         "threads": 8, "batch_threads": 8, "ram_required_bytes": 20 * 1024 ** 3,
                         "gpu_uuid": None, "min_gpu_free_mb": 0, "gpu_layers": 0, "n_cpu_moe": 0})
        self.assertTrue(result["memory"]["sufficient"])
        self.assertEqual(result["cpu"], {"available_logical_cpus": 8, "source": "process_affinity", "required": 8,
                                       "sufficient": True, "exclusive_reservation": False})
        self.assertEqual(result["storage"]["required_free_bytes"], 20 * 1024 ** 3)
        self.assertEqual(result["default_manifest"]["sha256"], b.sha256(model_service.PINS))
        self.assertEqual(list(self.base.iterdir()), [])

    def test_display_only_shell_constants_match_every_canonical_artifact_field(self):
        source = (b.SOURCE / "install.sh").read_text()
        pins = json.loads(model_service.PINS.read_text())
        model, runtime = pins["model"], pins["runtime"]
        expected = {"CPU_MODEL_ID": model["id"], "CPU_MODEL_NAME": model["name"], "CPU_MODEL_REVISION": model["revision"],
                    "CPU_MODEL_SHA": model["sha256"], "CPU_MODEL_BYTES": model["bytes"],
                    "CPU_RUNTIME_RELEASE": runtime["release"], "CPU_RUNTIME_REVISION": runtime["revision"],
                    "CPU_RUNTIME_NAME": runtime["cpu"][0]["name"], "CPU_RUNTIME_SHA": runtime["cpu"][0]["sha256"],
                    "CPU_RUNTIME_BYTES": runtime["cpu"][0]["bytes"]}
        for key, value in expected.items():
            self.assertEqual(re.search(r"^" + key + r"=(.+)$", source, re.MULTILINE)[1], str(value))
        self.assertIn(model["license"], source)
        self.assertIn(runtime["license"], source)
        self.assertIn(f'{sum(item["bytes"] for item in [model, *runtime["cpu"]]):,}', source)
        self.assertEqual(model["url"], "https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/"
                         + model["revision"] + "/" + model["name"])
        self.assertEqual(runtime["cpu"][0]["url"], "https://github.com/ggml-org/llama.cpp/releases/download/"
                         + runtime["release"] + "/" + runtime["cpu"][0]["name"])
        self.assertIn("https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct-GGUF/resolve/$CPU_MODEL_REVISION/$CPU_MODEL_NAME", source)
        self.assertIn("https://github.com/ggml-org/llama.cpp/releases/download/$CPU_RUNTIME_RELEASE/$CPU_RUNTIME_NAME", source)

    def test_options_accept_owner_and_explicit_full_without_changing_default(self):
        result = b.local_cpu_options(["--profile=pi", "--name", "Example Owner"])
        self.assertEqual((result.profile, result.name), ("pi", "Example Owner"))
        self.assertEqual(b.local_cpu_options([]).profile, "agent")
        self.assertEqual(b.local_cpu_options(["--profile=full"]).profile, "full")
        for arguments in (["--profile", "core"], ["--offline"], ["--base-url", "http://localhost"],
                          ["--model=other"], ["--context-window=8192"], ["--max-output=32"],
                          ["--model-profile=llama-cpp-qwen"], ["--resume-install"], ["--source", "other"],
                          ["--profile=pi", "--profile=agent"], ["--name=one", "--name=two"],
                          ["--prof=pi"], ["--name", ""], ["--name", "two\nlines"], ["--profile"]):
            with self.subTest(arguments=arguments), self.assertRaises(b.BootstrapError):
                b.local_cpu_options(arguments)

    def test_main_invalid_combinations_refuse_before_runtime_provision(self):
        prefix = ["--home", str(self.home), "--runtime-root", str(self.root), "--local-cpu", "--confirmed"]
        for arguments in (["--resume-install"], ["--runtimes-only"], ["--", "--offline"], ["--", "--profile=core"]):
            with self.subTest(arguments=arguments), patch.object(b, "provision") as native, \
                    contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(b.main(prefix + arguments), 1)
                native.assert_not_called()
        self.assertEqual(list(self.base.iterdir()), [])

    def test_full_plan_discloses_nine_packages_capture_and_optional_labs_without_effects(self):
        from harness import home
        with self.capacity(), patch.object(model_service, "start") as start:
            report = b.local_cpu_plan(self.home, profile="full")
        self.assertEqual(report["full_bundle"]["selected_packages"], home.PINS)
        self.assertEqual(report["full_bundle"]["experimental_labs"], ["harness2", "deepseek"])
        self.assertIn("unqualified", report["full_bundle"]["acceptance"])
        self.assertIn("shared home lease", report["full_bundle"]["observer"])
        start.assert_not_called()
        self.assertEqual(list(self.base.iterdir()), [])

    def test_python_plan_needs_no_bootstrap_directory_or_consent(self):
        with self.capacity(), patch.object(b, "provision") as native, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(b.main(["--home", str(self.home), "--runtime-root", str(self.root), "--local-cpu", "--plan"]), 0)
        native.assert_not_called()
        self.assertEqual(list(self.base.iterdir()), [])

    def test_low_resources_or_missing_confirmation_precede_runtime_and_model_transfer(self):
        prefix = ["--home", str(self.home), "--runtime-root", str(self.root), "--local-cpu"]
        for memory, free, cpus, confirmed in ((10, 30 * 1024 ** 3, 8, True), (30, 10 * 1024 ** 3, 8, True),
                                              (30, 30 * 1024 ** 3, 4, True), (30, 30 * 1024 ** 3, 8, False)):
            with self.subTest(memory=memory, free=free, cpus=cpus, confirmed=confirmed), self.capacity(memory=memory, free=free, cpus=cpus), \
                    patch.object(b, "provision") as runtime, patch.object(model_service, "provision") as model, \
                    contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(b.main(prefix + (["--confirmed"] if confirmed else [])), 1)
                runtime.assert_not_called()
                model.assert_not_called()
        self.assertEqual(list(self.base.iterdir()), [])

    def test_cpu_count_fallback_refuses_unknown_capacity_and_prefers_affinity(self):
        with self.capacity(cpus=4), patch.object(b.os, "cpu_count", return_value=48):
            self.assertFalse(b.local_cpu_plan(self.home)["cpu"]["sufficient"])
        for count in (None, 4, 8):
            with self.capacity(), patch.object(b.os, "sched_getaffinity", None), patch.object(b.os, "cpu_count", return_value=count):
                report = b.local_cpu_plan(self.home)["cpu"]
                self.assertEqual(report["source"], "os_cpu_count")
                self.assertEqual(report["sufficient"], count == 8)

    def test_existing_home_or_missing_templates_refuses_before_model_transfer(self):
        self.home.mkdir()
        marker = self.home / "preserve"
        marker.write_text("unchanged")
        with self.capacity(), self.assertRaisesRegex(b.BootstrapError, "new canonical"):
            b.local_cpu_plan(self.home)
        self.assertEqual(marker.read_text(), "unchanged")
        marker.unlink()
        self.home.rmdir()
        with self.capacity(), patch.object(b, "SOURCE", self.base / "incomplete-source"), \
                self.assertRaisesRegex(b.BootstrapError, "templates"):
            b.local_cpu_plan(self.home)
        self.assertFalse(self.root.exists())

    def test_composition_keeps_exact_order_and_runtime_bindings_without_generic_installer(self):
        self.runtime_marker()
        calls = Mock()
        selection = {"binding": {"nonsecret": "binding"}, "provider": {"apiKey": "$OWNED_VARIABLE"}}
        calls.capture.return_value = selection
        calls.create.return_value = {"status": "installed_owned_service", "model_capability_acceptance": "not_probed"}
        with self.capacity(), patch.object(model_service, "provision", calls.provision), \
                patch.object(model_service, "start", calls.start), patch.object(model_service_handoff, "capture", calls.capture), \
                patch.object(model_service_setup, "create", calls.create), patch.object(b.subprocess, "run") as generic, \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(b.install_local_cpu(self.receipt, ["--profile=full", "--name=Public Owner"]), 0)
        self.assertEqual([item[0] for item in calls.mock_calls], ["provision", "start", "capture", "create"])
        self.assertTrue(calls.provision.call_args.kwargs["allow_download"])
        self.assertEqual(calls.provision.call_args.args[1]["resources"]["threads"], 8)
        self.assertEqual(calls.start.call_args.kwargs, {"startup_timeout": 120})
        self.assertEqual(calls.create.call_args.kwargs, {"selection": selection, "source": b.SOURCE, "profile": "full",
                         "name": "Public Owner", "python312": self.receipt["python"]["path"],
                         "managed_node": Path(self.receipt["node"]["path"])})
        generic.assert_not_called()
        handoff = json.loads((self.root / "installer-handoff.json").read_text())
        self.assertEqual((handoff["phase"], handoff["exit_code"]), ("complete", 0))
        self.assertFalse(self.home.exists())  # Factory is mocked in this composition test.

    def test_failure_retains_phase_and_prevents_uncertain_replay(self):
        self.runtime_marker()
        with self.capacity(), patch.object(model_service, "provision"), \
                patch.object(model_service, "start", side_effect=ValueError("owned startup failed")), \
                patch.object(model_service_setup, "create") as factory:
            with self.assertRaisesRegex(ValueError, "startup failed"):
                b.install_local_cpu(self.receipt, [])
            factory.assert_not_called()
        receipt = self.root / "installer-handoff.json"
        original = receipt.read_bytes()
        result = json.loads(original)
        self.assertEqual((result["phase"], result["failed_stage"]), ("failed", "starting_pre_home"))
        self.assertFalse(result["automatic_replay"])
        with self.capacity(), patch.object(model_service, "provision") as model:
            with self.assertRaisesRegex(b.BootstrapError, "Prior installer handoff"):
                b.install_local_cpu(self.receipt, [])
            model.assert_not_called()
        self.assertEqual(receipt.read_bytes(), original)

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("bash"), "Initial shell is Linux only")
    def test_shell_local_cpu_plan_and_early_refusals_have_no_effects(self):
        prefix = ["bash", str(b.SOURCE / "install.sh"), "--home", str(self.home), "--local-cpu"]
        result = subprocess.run(prefix + ["--plan"], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("5,050,222,955", result.stdout)
        self.assertIn("20 GiB", result.stdout)
        self.assertIn("no\naccepted agent task quality", result.stdout)
        self.assertIn("threads8/batch threads8", result.stdout)
        self.assertIn("total download bytes", result.stdout)
        full = subprocess.run(prefix + ["--plan", "--profile=full"], capture_output=True, text=True, timeout=20)
        self.assertEqual(full.returncode, 0, full.stderr)
        self.assertIn("FULL BUNDLE CANDIDATE", full.stdout)
        self.assertIn("shared home lease", full.stdout)
        self.assertIn("optional experimental labs", full.stdout)
        for arguments in (["--profile=core"], ["--offline"], ["--base-url=x"], ["--model=other"], ["--resume-install"],
                          ["--runtimes-only"], ["--context-window=8192"], ["--model-profile=generic-local"]):
            result = subprocess.run(prefix + ["--yes", *arguments], capture_output=True, text=True, timeout=20)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("--local-cpu", result.stderr)
        declined = subprocess.run(prefix, input="n\n", capture_output=True, text=True, timeout=20)
        self.assertEqual(declined.returncode, 0, declined.stderr)
        self.assertEqual(list(self.base.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
