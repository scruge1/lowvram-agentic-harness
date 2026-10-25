"""Factory/provider sequencing with real scaffold and real admission flocks.

Package/doctor and model lifecycle calls are isolated test doubles. These tests
start no server or model; native service and handoff ownership have separate
qualification. They verify that the real factory persists the selected route
before costly installation and that only the final Pi child receives a nonce.
"""
import contextlib
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from harness import bootstrap, home, home_entry, model_service, model_service_handoff
from harness import model_service_setup as setup


class OwnedFactoryTests(unittest.TestCase):
    def setUp(self):
        root = os.environ.get("MODEL_SERVICE_TEST_ROOT")
        temporary = tempfile.TemporaryDirectory(prefix="owned-factory-", dir=root)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.target = self.base / "Hôme Ω agent"
        self.binding = {"schema": model_service_handoff.SCHEMA, "home": str(self.target),
                        "storage_root": str(self.target) + "-runtimes", "specification_sha256": "1" * 64,
                        "base_url": "http://127.0.0.1:49991/v1", "model_id": "explicit-owned-model",
                        "context": 32768, "max_output": 4096, "transport_profile": "generic-local",
                        "environment_variable": model_service_handoff._variable(str(self.target))}
        self.provider = home.owned_service_provider(self.target, self.binding, profile="pi", base_url=self.binding["base_url"],
                                                    model=self.binding["model_id"], context_window=32768, max_output=4096,
                                                    model_profile="generic-local")

    def scaffold(self, **overrides):
        options = dict(profile="pi", base_url=self.binding["base_url"], model=self.binding["model_id"], offline=True,
                       owned_model_service=self.binding, local_provider=self.provider)
        options.update(overrides)
        return home.scaffold(self.target, **options)

    def test_real_scaffold_writes_nonsecret_binding_and_native_env_provider(self):
        config = self.scaffold()
        self.assertEqual(config["owned_model_service"], self.binding)
        written = json.loads((self.target / "agent/models.json").read_text())["providers"]["local"]
        self.assertEqual(written, self.provider)
        self.assertEqual(written["apiKey"], "$" + self.binding["environment_variable"])
        self.assertNotIn(self.binding["environment_variable"], home.environment(self.target))
        self.assertEqual(config["model_capability_acceptance"], "not_probed")

    def test_contradictory_provider_or_route_and_full_profile_refuse_before_creation(self):
        for changes in ({"model": "different"}, {"base_url": "http://127.0.0.1:49992/v1"}, {"context_window": 65536},
                        {"local_provider": dict(self.provider, apiKey="literal-secret")}, {"profile": "full"}):
            with self.subTest(changes=list(changes)), self.assertRaises(home.HomeError):
                self.scaffold(**changes)
            self.assertFalse(self.target.exists())

    def test_protocol_budget_refuses_before_factory_writes(self):
        binding = dict(self.binding, context=4096, max_output=128)
        with self.assertRaisesRegex(home.HomeError, "protocol-only"):
            self.scaffold(owned_model_service=binding, context_window=4096, max_output=128)
        self.assertFalse(self.target.exists())

    def test_provider_override_without_binding_refuses(self):
        with self.assertRaisesRegex(home.HomeError, "explicit owned"):
            self.scaffold(owned_model_service=None)
        self.assertFalse(self.target.exists())

    def test_managed_launch_only_child_environment_gets_nonce_and_continue_is_preserved(self):
        self.scaffold()
        cli = self.target / "packages/pi/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("// not executed by this isolated launch test\n")
        secret = "f" * 64
        lease = mock.MagicMock()
        lease.pi_args = ("--session", str(self.target / "agent/sessions/owned.jsonl"))
        lease.pass_fds = (211,)
        lease.selection = {"id": "owned-session-id"}
        context = contextlib.nullcontext(lease)
        from harness import session_resume
        with mock.patch.object(home, "doctor", return_value={"failures": []}), \
                mock.patch.object(home.shutil, "which", return_value=sys.executable), \
                mock.patch.object(home, "board", return_value={"result": {"identity": {"project_id": "unit"}}}), \
                mock.patch.object(home, "palace", return_value={"status": "running"}), \
                mock.patch.object(session_resume, "acquire", return_value=context) as acquire, \
                mock.patch.object(home.sys, "platform", "linux"), \
                mock.patch.object(model_service_handoff, "launch_environment", return_value=model_service_handoff.LaunchEnvironment(
                    {self.binding["environment_variable"]: secret}, {"lease_scope": "home_shared"})) as inject, \
                mock.patch.object(home.subprocess, "call", return_value=0) as call:
            result = home._launch(self.target, ["--offline", "--", "--model", "literal-prompt"], inherited=(210,), continue_recent=True)
        self.assertEqual(result, 0)
        self.assertTrue(acquire.call_args.kwargs["continue_recent"])
        self.assertEqual(call.call_args.args[0][-6:], ["--session", str(self.target / "agent/sessions/owned.jsonl"),
                                                      "--offline", "--", "--model", "literal-prompt"])
        self.assertEqual(call.call_args.kwargs["env"][self.binding["environment_variable"]], secret)
        if os.name != "nt":
            self.assertEqual(call.call_args.kwargs["pass_fds"], (210, 211))
        self.assertNotIn(self.binding["environment_variable"], home.environment(self.target))
        self.assertEqual(inject.call_count, 1)
        self.assertNotIn(secret, (self.target / "home.json").read_text() + (self.target / "agent/models.json").read_text())

    def test_managed_launch_refuses_missing_or_stale_provider_before_nonce_injection(self):
        self.scaffold()
        cli = self.target / "packages/pi/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("// not executed\n")
        lease = mock.MagicMock()
        lease.pi_args, lease.pass_fds, lease.selection = (), (), None
        from harness import session_resume
        for providers in ({}, {"local": dict(self.provider, apiKey="stale-literal")}):
            (self.target / "agent/models.json").write_text(json.dumps({"providers": providers}))
            with mock.patch.object(home, "doctor", return_value={"failures": []}), \
                    mock.patch.object(home.shutil, "which", return_value=sys.executable), \
                    mock.patch.object(home, "board", return_value={"result": {"identity": {}}}), \
                    mock.patch.object(home, "palace"), mock.patch.object(home.sys, "platform", "linux"), \
                    mock.patch.object(session_resume, "acquire", return_value=contextlib.nullcontext(lease)), \
                    mock.patch.object(model_service_handoff, "launch_environment") as inject, \
                    mock.patch.object(home.subprocess, "call") as call:
                with self.assertRaises(home.HomeError):
                    home._launch(self.target, ["--offline"])
            inject.assert_not_called()
            call.assert_not_called()


@unittest.skipUnless(sys.platform == "linux", "Owned setup uses Linux native admission flocks")
class SetupTests(OwnedFactoryTests):
    def setUp(self):
        super().setUp()
        self.runtime = Path(str(self.target) + "-runtimes")
        self.runtime.mkdir()
        (self.runtime / "bootstrap-owner").write_text("agent-home-bootstrap/v1:" + str(self.target) + "\n")
        self.state_path = self.runtime / "state/model-service/service.json"
        self.state_path.parent.mkdir(parents=True)
        self.state = {"schema": model_service.SCHEMA, "home": str(self.target), "storage_root": str(self.runtime),
                      "pid": 12345, "start_ticks": "67890", "nonce_sha256": "2" * 64, "phase": "running"}
        self.save_state()
        self.pre = {"binding": self.binding, "provider": self.provider,
                    "receipt": {"lease_scope": "pre_home", "service_pid": 12345, "service_start_ticks": "67890",
                                "nonce_sha256": "2" * 64, "service_state_sha256": hashlib.sha256(self.state_path.read_bytes()).hexdigest()}}
        self.post = copy.deepcopy(self.pre)
        self.post["receipt"].update(lease_scope="home_shared", service_pid=12346, service_start_ticks="67891", nonce_sha256="3" * 64)
        self.events = []

    def save_state(self):
        bootstrap.publish_json(self.state_path, self.state)

    def assert_admission(self, blocked):
        import fcntl
        descriptor = os.open(self.state_path.parent / "service.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                self.assertTrue(blocked)
            else:
                self.assertFalse(blocked)
        finally:
            os.close(descriptor)

    @contextlib.contextmanager
    def pipeline(self, *, install=None, capture=None):
        def stop(_root, state):
            self.events.append("stop")
            self.assertFalse(self.target.exists())
            self.assertEqual(state["pid"], self.pre["receipt"]["service_pid"])
            self.state["phase"] = "stopped"
            self.save_state()
            return {"status": "stopped"}
        def packages(target, config, python312=None):
            self.events.append("install")
            self.assert_admission(True)
            self.assertEqual(config["owned_model_service"], self.binding)
            self.assertEqual(json.loads((target / "agent/models.json").read_text())["providers"]["local"], self.provider)
            self.assertNotIn(self.binding["environment_variable"], home.environment(target))
            if install:
                install(target, config)
        def start(target, *, port):
            self.events.append("start")
            self.assert_admission(False)
            self.assertEqual(port, 49991)
            selected, config = home_entry.selected_home(target)
            guard = home_entry._load_guard(selected, config["lifecycle_guard_sha256"])
            guard.checked_home(selected, expected_sha256=config["lifecycle_guard_sha256"])
            return {"status": "running"}
        with mock.patch.object(model_service, "_load", return_value=({"specification": {"runtime": {"backend": "cpu"}}}, self.runtime, self.runtime / "unused")), \
                mock.patch.object(model_service_handoff, "capture", side_effect=capture or [self.pre, self.post]), \
                mock.patch.object(model_service, "_stop", side_effect=stop) as stopped, \
                mock.patch.object(model_service, "stop", side_effect=AssertionError("Public stop would reenter its mutation lock")), \
                mock.patch.object(home, "install_packages", side_effect=packages), \
                mock.patch.object(home, "doctor", return_value={"failures": [], "pending_acceptance": ["native task acceptance"]}), \
                mock.patch.object(model_service, "start", side_effect=start) as started:
            yield stopped, started

    def create(self, **kwargs):
        return setup.create(self.target, selection={"binding": self.binding, "provider": self.provider}, profile="pi", **kwargs)

    def test_real_factory_sequence_binding_before_installer_same_port_guarded_restart(self):
        with self.pipeline():
            result = self.create()
        self.assertEqual(self.events, ["stop", "install", "start"])
        self.assertEqual(result["status"], "installed_owned_service")
        operation = json.loads((self.state_path.parent / "setup.json").read_text())
        self.assertEqual(operation["phase"], "complete")
        self.assertFalse(operation["automatic_replay"])
        self.assertEqual(operation["installed_service"]["lease_scope"], "home_shared")

    def test_under_capacity_and_full_profile_do_not_stop_or_create(self):
        for changes in ({"context": 4096, "max_output": 32}, {"max_output": 32}, {"max_output": 20000}):
            selected = dict(self.binding, **changes)
            with self.pipeline() as (stopped, started), self.assertRaises(home.HomeError):
                setup.create(self.target, selection={"binding": selected, "provider": self.provider}, profile="pi")
            stopped.assert_not_called()
            started.assert_not_called()
            self.assertFalse(self.target.exists())
        with self.pipeline() as (stopped, _), self.assertRaisesRegex(home.HomeError, "full/observer"):
            setup.create(self.target, selection={"binding": self.binding, "provider": self.provider}, profile="full")
        stopped.assert_not_called()

    def test_captured_pid_nonce_state_race_refuses_exact_stop(self):
        self.state["pid"] = 12346
        self.save_state()
        with self.pipeline() as (stopped, started), self.assertRaisesRegex(setup.SetupError, "stopping_pre_home"):
            self.create()
        stopped.assert_not_called()
        started.assert_not_called()
        self.assertFalse(self.target.exists())
        operation = json.loads((self.state_path.parent / "setup.json").read_text())
        self.assertIn("lifetime changed", operation["error"])

    def test_service_admission_blocks_public_start_during_package_installation(self):
        def competing(_target, _config):
            # Call the real public entry until the genuine kernel service lock
            # refuses. Artifact/resources/metadata are fixtures, no process starts.
            real_start = self._public_start
            with mock.patch.object(model_service, "status", return_value={"status": "stopped"}), \
                    mock.patch.object(model_service, "_resources"), mock.patch.object(model_service, "_pidfd") as native, \
                    mock.patch.object(subprocess, "Popen", side_effect=AssertionError("Admission must refuse before spawn")):
                native.return_value.require_support.return_value = {"pidfd_open": "fixture", "pidfd_send_signal": "fixture"}
                with self.assertRaisesRegex(model_service.ModelServiceError, "retains the service lease"):
                    real_start(self.target)
        self._public_start = model_service.start
        with self.pipeline(install=competing):
            self.create()

    def test_installer_failure_preserves_partial_home_releases_admission_and_never_replays(self):
        def fail(*_):
            raise RuntimeError("bounded synthetic package failure")
        with self.pipeline(install=fail) as (_, started), self.assertRaisesRegex(setup.SetupError, "installing_packages"):
            self.create()
        started.assert_not_called()
        self.assertTrue(self.target.exists())
        self.assert_admission(False)
        operation = json.loads((self.state_path.parent / "setup.json").read_text())
        self.assertEqual(operation["failed_stage"], "installing_packages")
        self.assertIn("bounded synthetic", operation["error"])
        with self.assertRaisesRegex(setup.SetupError, "Target already exists"):
            self.create()

    def test_prior_uncertain_receipt_and_busy_setup_lock_refuse(self):
        import fcntl
        receipt = self.state_path.parent / "setup.json"
        receipt.write_text('{"phase":"stopping_pre_home"}\n')
        with self.pipeline() as (stopped, _), self.assertRaisesRegex(setup.SetupError, "Prior setup evidence"):
            self.create()
        stopped.assert_not_called()
        receipt.unlink()
        descriptor = os.open(self.state_path.parent / "setup.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.pipeline() as (stopped, _), self.assertRaisesRegex(setup.SetupError, "Another factory"):
                self.create()
            stopped.assert_not_called()
        finally:
            os.close(descriptor)

    def test_competing_posthome_wrong_port_refuses_without_stopping_new_owner(self):
        changed = copy.deepcopy(self.post)
        changed["binding"]["base_url"] = "http://127.0.0.1:49992/v1"
        with self.pipeline(capture=[self.pre, changed]) as (stopped, _), self.assertRaisesRegex(setup.SetupError, "starting_after_home"):
            self.create()
        self.assertEqual(stopped.call_count, 1)
        operation = json.loads((self.state_path.parent / "setup.json").read_text())
        self.assertIn("selected port/source", operation["error"])


if __name__ == "__main__":
    unittest.main()
