"""Disposable command registration and existing launch-route behavior.

The child probe is deliberately not Pi; native prompt/tool/session acceptance
is a separate SDK/installed-runtime qualification.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from harness import home, managed_launch, session_resume


@contextlib.contextmanager
def working_directory(path):
    before = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(before)


class ManagedLaunchTests(unittest.TestCase):
    def setUp(self):
        selected = os.environ.get("AGENT_HOME_LAUNCH_TEST_ROOT")
        if not selected and os.name == "nt" and Path("E:/AgentData/AgentHomeQualification").is_dir():
            selected = "E:/AgentData/AgentHomeQualification"
        temporary = tempfile.TemporaryDirectory(prefix="managed-launch-", dir=selected)
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.agent = self.base / "Hôme β with spaces"
        home.scaffold(self.agent, profile="core", base_url="http://127.0.0.1:8080/v1",
                      model="configured-model", offline=True)
        self.random = self.base / "unrelated cwd"
        self.random.mkdir()
        (self.random / "keep.txt").write_text("unrelated owner data\n")

    def create_other(self):
        other = self.base / "Other home"
        home.scaffold(other, profile="core", base_url="http://127.0.0.1:9090/v1", model="other-model", offline=True)
        return other

    def test_scaffold_command_runs_status_from_random_cwd_with_unicode_paths(self):
        command = managed_launch.command_file(self.agent / "bin", "harness-agent")
        self.assertTrue(command.is_file())
        result = subprocess.run([str(command), "--status"], cwd=self.random,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        status = json.loads(result.stdout)
        self.assertEqual(status["home"], str(self.agent))
        self.assertEqual(status["cwd"], str(self.agent))
        self.assertEqual(status["agent_dir"], str(self.agent / "agent"))
        self.assertEqual(status["model"], "local/configured-model")
        self.assertIsNone(status["project"])
        self.assertEqual(list(self.random.iterdir()), [self.random / "keep.txt"])

    def test_bound_launcher_refuses_other_home_and_managed_selector(self):
        other = self.create_other()
        for arguments in (["--home", str(other), "doctor"],
                          ["managed", "--", "--home", str(other), "--status"]):
            result = subprocess.run([sys.executable, str(self.agent / "agent-home.py"), *arguments],
                                    cwd=self.random, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1, result.stdout)
            self.assertIn("bound", result.stderr)
        selected, status, continued, arguments = managed_launch.managed_arguments(self.agent, ["--home", str(self.agent), "--status"])
        self.assertIsNone(selected)
        self.assertTrue(status)
        self.assertFalse(continued)
        self.assertEqual(arguments, [])

    def test_explicit_registration_collision_and_reversal_preserve_existing_pi(self):
        directory = self.base / "User bin ü"
        directory.mkdir()
        existing = managed_launch.command_file(directory, "pi")
        original = b"existing unrelated Pi command\n"
        existing.write_bytes(original)
        before_path = os.environ.get("PATH")
        result = managed_launch.register_command(self.agent, directory, default_pi=True)
        self.assertEqual(result["status"], "collision")
        self.assertEqual(existing.read_bytes(), original)
        unique = managed_launch.command_file(directory, "harness-agent")
        self.assertTrue(unique.is_file())
        self.assertFalse(result["commands"][1]["owned_unchanged"])
        self.assertIn("aliases/functions", result["shell_resolution"])
        self.assertEqual(os.environ.get("PATH"), before_path)
        managed_launch.remove_command(self.agent, directory)
        self.assertFalse(unique.exists())
        self.assertEqual(existing.read_bytes(), original)

    def test_two_homes_never_overwrite_each_others_command(self):
        directory = self.base / "bin"
        managed_launch.register_command(self.agent, directory, default_pi=True)
        command = managed_launch.command_file(directory, "harness-agent")
        before = command.read_bytes()
        other = self.create_other()
        result = managed_launch.register_command(other, directory)
        self.assertEqual(result["status"], "collision")
        self.assertEqual(command.read_bytes(), before)
        self.assertFalse(managed_launch.receipt_path(other, directory, "harness-agent").exists())
        managed_launch.register_command(other, directory, name="harness-other")
        managed_launch.remove_command(other, directory, name="harness-other")
        self.assertEqual(command.read_bytes(), before)
        managed_launch.remove_command(self.agent, directory)
        self.assertFalse(managed_launch.command_file(directory, "pi").exists())
        self.assertTrue(list((self.agent / "state/managed-commands").glob("*.removed")))

    def test_changed_command_blocks_reversal_before_any_owned_file_is_removed(self):
        directory = self.base / "bin"
        managed_launch.register_command(self.agent, directory, default_pi=True)
        unique = managed_launch.command_file(directory, "harness-agent")
        original = unique.read_bytes()
        default = managed_launch.command_file(directory, "pi")
        default.write_bytes(b"owner changed this command\n")
        with self.assertRaisesRegex(ValueError, "Command changed"):
            managed_launch.remove_command(self.agent, directory)
        self.assertEqual(unique.read_bytes(), original)
        self.assertEqual(default.read_bytes(), b"owner changed this command\n")

    def test_matching_overrides_are_normalized_and_session_profile_escapes_refuse(self):
        self.assertEqual(managed_launch.pi_arguments(["--provider=local", "--model", "configured-model", "--mode", "json"],
                                                    "configured-model"), ["--mode", "json"])
        for arguments in (["--provider", "cloud"], ["--model=other"], ["--models", "*"],
                          ["--agent-dir", "outside"], ["--home", "outside"], ["--no-extensions"],
                          ["-ne"], ["--no-mcp"], ["--system-prompt", "replacement"],
                          ["--session", "outside.jsonl"], ["--session-id", "other-project"],
                          ["--session-dir", "outside"], ["--resume"], ["-r"], ["--continue"],
                          ["-c"], ["--fork", "outside"], ["--no-session"], ["--mode", "rpc"], ["--mode=rpc"]):
            with self.subTest(arguments=arguments), mock.patch.object(home, "palace") as palace:
                with working_directory(self.random), self.assertRaises(ValueError):
                    home.launch(self.agent, arguments)
                palace.assert_not_called()
        self.assertEqual(managed_launch.pi_arguments(["--", "--provider", "cloud"], "configured-model"),
                         ["--", "--provider", "cloud"])
        self.assertEqual(managed_launch.pi_arguments(["--", "--", "--model", "other"], "configured-model"),
                         ["--", "--", "--model", "other"])

    def test_native_session_bucket_and_environment_keep_actual_os_home(self):
        before = {name: os.environ.get(name) for name in ("HOME", "USERPROFILE")}
        with mock.patch.dict(os.environ, {"PI_CODING_AGENT_DIR": "wrong-home", "PI_CODING_AGENT_SESSION_DIR": "outside"}):
            env = home.environment(self.agent)
        self.assertEqual(env["PI_CODING_AGENT_DIR"], str(self.agent / "agent"))
        self.assertEqual(env["PI_CODING_AGENT_SESSION_DIR"], str(managed_launch.session_directory(self.agent, self.agent)))
        self.assertEqual({name: env.get(name) for name in before}, before)
        self.assertTrue(Path(env["PI_CODING_AGENT_SESSION_DIR"]).is_relative_to(self.agent / "agent/sessions"))

    def test_continue_is_a_managed_selector_and_never_a_raw_pi_override(self):
        self.assertEqual(managed_launch.managed_arguments(self.agent, ["--continue", "--offline", "--print", "hello"]),
                         (None, False, True, ["--offline", "--print", "hello"]))
        for values in (["--continue", "--continue"], ["--continue=yes"], ["--status", "--continue"]):
            with self.assertRaises(managed_launch.LaunchError):
                managed_launch.managed_arguments(self.agent, values)
        _, _, continued, values = managed_launch.managed_arguments(self.agent, ["--offline", "--continue"])
        self.assertFalse(continued)
        with self.assertRaises(managed_launch.LaunchError):
            managed_launch.pi_arguments(values, "configured-model")

    def test_existing_project_selection_is_validated_without_adopting_random_cwd(self):
        project = self.base / "Admitted project"
        (project / ".icm").mkdir(parents=True)
        (project / ".icm/project.json").write_text("{}")
        with working_directory(self.random):
            self.assertIsNone(managed_launch.select_project(self.agent))
            with self.assertRaises(ValueError):
                managed_launch.select_project(self.agent, self.random)
        cli = self.agent / "packages/pi/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("// Fixture only; child execution is mocked in this case.\n")
        with working_directory(project), mock.patch.object(home, "board", side_effect=home.HomeError("other-home identity")) as board, \
             mock.patch.object(home, "palace") as palace, mock.patch.object(home.shutil, "which", return_value=sys.executable):
            with self.assertRaisesRegex(home.HomeError, "other-home identity"):
                home.launch(self.agent, [])
            board.assert_called_once_with(self.agent, {"action": "project_admit", "project_root": str(project)})
            palace.assert_not_called()

    @unittest.skipUnless(shutil.which("node"), "Node is needed for the child-environment probe")
    def test_existing_launch_runs_child_with_selected_project_and_home_binding(self):
        project = self.base / "Chosen project"
        (project / ".icm").mkdir(parents=True)
        (project / ".icm/project.json").write_text("{}")
        cli = self.agent / "packages/pi/node_modules/@earendil-works/pi-coding-agent/dist/cli.js"
        cli.parent.mkdir(parents=True)
        cli.write_text("require('fs').writeFileSync(process.env.MANAGED_LAUNCH_PROBE,JSON.stringify({cwd:process.cwd(),argv:process.argv.slice(2),agent:process.env.PI_CODING_AGENT_DIR,sessions:process.env.PI_CODING_AGENT_SESSION_DIR,HOME:process.env.HOME??null,USERPROFILE:process.env.USERPROFILE??null}));\n")
        probe = self.base / "child-probe.json"
        before = {name: os.environ.get(name) for name in ("HOME", "USERPROFILE")}
        with working_directory(self.random), mock.patch.object(home, "board") as board, \
             mock.patch.object(home, "palace") as palace, mock.patch.dict(os.environ, {"MANAGED_LAUNCH_PROBE": str(probe)}), \
             mock.patch.object(session_resume, "acquire", return_value=contextlib.nullcontext(SimpleNamespace(pi_args=(), pass_fds=(), selection=None))), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(home.launch(self.agent, ["--mode", "json"], project), 0)
        result = json.loads(probe.read_text(encoding="utf-8"))
        self.assertEqual(Path(result["cwd"]).resolve(), project)
        self.assertEqual(result["argv"], ["--provider", "local", "--model", "configured-model", "--mode", "json"])
        self.assertEqual(result["agent"], str(self.agent / "agent"))
        self.assertEqual(result["sessions"], str(managed_launch.session_directory(self.agent, project)))
        self.assertEqual({name: result[name] for name in before}, before)
        board.assert_called_once_with(self.agent, {"action": "project_admit", "project_root": str(project)})
        palace.assert_called_once_with(self.agent, "start")


if __name__ == "__main__":
    unittest.main()
