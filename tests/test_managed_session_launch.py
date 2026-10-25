"""Launch integration for the existing session/home leases; no model or service."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

from harness import home, home_entry, managed_launch, session_resume


@unittest.skipUnless(sys.platform == "linux", "Managed session leases require Linux")
class ManagedSessionLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="managed-session-", dir=os.environ.get("PI_SESSION_TEST_ROOT"))
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.agent = self.base / "owned home"
        home.scaffold(self.agent, profile="core", base_url="http://127.0.0.1:9/v1", model="fixture-model", offline=True)
        self.package = self.agent / "packages/pi/node_modules/@earendil-works/pi-coding-agent"
        (self.package / "dist").mkdir(parents=True)
        (self.package / "package.json").write_text(json.dumps({"name": "@earendil-works/pi-coding-agent", "version": "1.4.0"}))
        (self.package / "dist/cli.js").write_text("// Explicit unit fixture; subprocess execution is inspected, not run.\n")
        self.project = self.base / "project"
        self.project.mkdir()
        self.identities = {}
        for index, directory in enumerate((self.agent, self.project)):
            project_id = "fixture-project-" + str(index)
            identity = {"project_id": project_id, "board_id": "project:" + project_id,
                        "canonical_root": str(directory), "state_root": str(self.agent / "state/projects" / project_id)}
            (directory / ".icm").mkdir(exist_ok=True)
            (directory / ".icm/project.json").write_text(json.dumps(identity))
            self.identities[str(directory)] = identity
        self.node = Path(sys.executable).resolve()

    def admit(self, _agent, request):
        self.assertEqual(request["action"], "project_admit")
        self.assertNotIn("initialize", request)
        return {"ok": True, "result": {"identity": self.identities[request["project_root"]]}}

    def launch(self, arguments=(), project=None, continued=False, child=None):
        with mock.patch.object(home, "doctor", return_value={"failures": []}), \
             mock.patch.object(home, "board", side_effect=self.admit), \
             mock.patch.object(home, "palace") as palace, \
             mock.patch.object(home.shutil, "which", return_value=str(self.node)), \
             mock.patch.object(home.subprocess, "call", side_effect=child or (lambda *_args, **_kwargs: 0)) as call, \
             contextlib.redirect_stderr(io.StringIO()):
            self.last_palace, self.last_child = palace, call
            value = home.launch(self.agent, list(arguments), project, continue_recent=continued)
        return value, call, palace

    def acquire(self, directory=None, **kwargs):
        directory = directory or self.agent
        return session_resume.acquire(self.agent, directory, node=self.node, pi_package=self.package,
                                      project_identity=self.identities[str(directory)], **kwargs)

    def test_every_fresh_launch_holds_both_kernel_leases_through_child_exit(self):
        def child(argv, *, cwd, env, pass_fds):
            self.assertEqual(cwd, self.agent)
            self.assertEqual(len(pass_fds), 2)
            self.assertEqual(int(env[home_entry.FD_ENV]), pass_fds[0])
            for descriptor in pass_fds:
                os.fstat(descriptor)
            with self.assertRaises(session_resume.SessionBusyError):
                self.acquire()
            config = json.loads((self.agent / "home.json").read_text())
            guard = home_entry._load_guard(self.agent, config["lifecycle_guard_sha256"])
            with self.assertRaises(guard.LeaseBusy):
                with guard.lease(self.agent, expected_sha256=config["lifecycle_guard_sha256"], mode="exclusive"):
                    self.fail("Update acquired a live home")
            self.assertNotIn("--session", argv)
            self.assertEqual(env.get("HOME"), os.environ.get("HOME"))
            return 0
        value, _, palace = self.launch(child=child)
        self.assertEqual(value, 0)
        palace.assert_called_once_with(self.agent, "start")
        with self.acquire():
            pass

    def test_parent_close_never_unlocks_a_surviving_inherited_bucket_description(self):
        retained = []
        def child(_argv, **options):
            retained.append(os.dup(options["pass_fds"][1]))
            return 0
        try:
            self.launch(child=child)
            with self.assertRaises(session_resume.SessionBusyError):
                self.acquire()
        finally:
            for descriptor in retained:
                os.close(descriptor)
        with self.acquire():
            pass

    def test_empty_continue_and_live_owner_refuse_before_hub_or_child(self):
        with self.assertRaises(session_resume.NoPreviousSession):
            self.launch(continued=True)
        self.last_palace.assert_not_called()
        self.last_child.assert_not_called()
        with self.acquire():
            with self.assertRaises(session_resume.SessionBusyError):
                self.launch()
            with self.assertRaises(session_resume.SessionBusyError):
                self.launch(continued=True)
            self.last_palace.assert_not_called()
            self.last_child.assert_not_called()

    def test_internal_session_path_precedes_literal_end_and_prompt(self):
        path = managed_launch.session_directory(self.agent, self.project) / "selected.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("explicit synthetic fixture; native selector is isolated in this unit\n")
        before = path.read_bytes()
        selection = {"path": str(path), "id": "fixture-session"}
        with mock.patch.object(session_resume, "_select", return_value=selection):
            _, call, _ = self.launch(["--", "--model", "literal prompt value"], self.project, continued=True)
        argv = call.call_args.args[0]
        self.assertEqual(argv[6:], ["--session", str(path), "--", "--model", "literal prompt value"])
        self.assertEqual(path.read_bytes(), before)

    def test_raw_session_overrides_remain_refused_before_board_or_hub(self):
        for arguments in (["--session", "arbitrary"], ["--continue"], ["--resume"], ["-c"]):
            with mock.patch.object(home, "board") as board, mock.patch.object(home, "palace") as palace:
                with self.assertRaises(managed_launch.LaunchError):
                    home.launch(self.agent, arguments)
                board.assert_not_called()
                palace.assert_not_called()

    def test_malformed_saved_header_and_other_home_pointer_are_preserved(self):
        bucket = managed_launch.session_directory(self.agent, self.project)
        bucket.mkdir(parents=True)
        saved = bucket / "malformed.jsonl"
        saved.write_bytes(b"not JSON\n")
        before = saved.read_bytes()
        with self.assertRaises(session_resume.SessionScopeError):
            self.launch(project=self.project, continued=True)
        self.assertEqual(saved.read_bytes(), before)
        identity_file = self.project / ".icm/project.json"
        wrong = {**self.identities[str(self.project)], "state_root": str(self.base / "other-home/state")}
        identity_file.write_text(json.dumps(wrong))
        pointer = identity_file.read_bytes()
        with self.assertRaises(session_resume.SessionScopeError):
            self.launch(project=self.project)
        self.assertEqual(identity_file.read_bytes(), pointer)

    def test_continue_cli_has_typed_no_previous_refusal(self):
        from harness import session_resume
        for values in (["--home", str(self.agent), "start", "--continue"],
                       ["--home", str(self.agent), "managed", "--", "--continue"]):
            with mock.patch.object(home, "launch", side_effect=session_resume.NoPreviousSession("No previous session")) as launch, \
                 contextlib.redirect_stderr(io.StringIO()) as errors:
                self.assertEqual(home.main(values), 1)
            self.assertEqual(json.loads(errors.getvalue())["code"], "no_previous_session")
            self.assertTrue(launch.call_args.kwargs["continue_recent"])

    def test_status_reports_supported_scope_without_selecting_history(self):
        with mock.patch.object(home, "doctor", return_value={"failures": [], "pending_acceptance": []}), \
             mock.patch.object(session_resume, "acquire") as acquire:
            value = home.launch_status(self.agent)
        acquire.assert_not_called()
        self.assertIn("--continue", value["resume"])
        self.assertIn("exclusive bucket", value["session_ownership"])


if __name__ == "__main__":
    unittest.main()
