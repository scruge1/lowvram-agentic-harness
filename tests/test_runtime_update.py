"""Owned runtime exchanges and interruption recovery; no package/model/service."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from harness import home as bootstrap, maintenance as state, runtime_update as update


REPO = Path(__file__).resolve().parents[1]


def digest(file):
    return hashlib.sha256(file.read_bytes()).hexdigest()


@unittest.skipUnless(shutil.which("git"), "Existing core scaffold requires Git")
class UpdateFixture(unittest.TestCase):
    def setUp(self):
        selected = os.environ.get("RUNTIME_UPDATE_TEST_ROOT")
        if not selected and os.name == "nt" and Path("E:/").is_dir():
            selected = "E:/"
        self.temporary = tempfile.TemporaryDirectory(prefix="harness-runtime-update-", dir=selected)
        self.base = Path(self.temporary.name).resolve()
        self.parent = self.base.parent
        self.baseline = self.base / "baseline-source"
        for name in ("harness", "ssot", "adapters/pi"):
            for path in (REPO / name).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and (path.suffix in {".py", ".ts", ".mjs", ".md"}
                                                                         or "templates" in path.parts
                                                                         or path.relative_to(REPO).as_posix() in {
                                                                             "harness/model-service-pins.json", "harness/claude-memory-patch.json"}):
                    target = self.baseline / path.relative_to(REPO)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, target)
        for relative in ("harness/project-board-native.json", "scripts/build_project_board_assets.py",
                         "adapters/project-board/entry.js", "adapters/project-board/style.css",
                         "adapters/project-board/index.html", "adapters/project-board/native-utils.ts",
                         "adapters/project-board/NOTICE.md", "adapters/project-board/HERMES-LICENSE.txt"):
            target = self.baseline / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / relative, target)
        self.addCleanup(self.clean_fixture)
        self.cases = []
        self.case = self.new_case("main")

    def clean_fixture(self):
        for case in self.cases:
            self.assertEqual({str(path): path.read_bytes() for path in case["protected"]}, case["protected_bytes"])
        self.assertEqual(self.base.parent, self.parent)
        self.assertEqual(self.base.resolve(), self.base)
        self.assertTrue(self.base.name.startswith("harness-runtime-update-"))
        self.temporary.cleanup()

    def new_case(self, name):
        source = self.base / (name + "-candidate")
        shutil.copytree(self.baseline, source)
        home = self.base / (name + " agent home ü")
        bootstrap.scaffold(home, source=self.baseline, profile="core", base_url="http://127.0.0.1:9/v1",
                           model="no-model-fixture", offline=True)
        protected = []
        for relative in ("agent/auth.json", "agent/sessions/original.jsonl", "context/owner.md", "memory/palace/keep.bin",
                         "state/projects/board.bin", "packages/cache.bin", "cache/keep.bin", "envs/keep.bin"):
            file = home / relative
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("synthetic preserved data: " + relative)
            protected.append(file)
        before = state.active_snapshot(home)[2]
        patch = source / "harness/enforcement.py"
        patch.write_bytes(patch.read_bytes() + b"\nRUNTIME_UPDATE_FIXTURE = 'qualified-compatible-patch'\n")
        case = {"home": home, "source": source, "protected": protected,
                "protected_bytes": {str(path): path.read_bytes() for path in protected}, "before": before,
                "operation": "runtime-source-a"}
        self.cases.append(case)
        return case

    def prepare(self, case=None):
        case = case or self.case
        home, source, identifier = case["home"], case["source"], case["operation"]
        selected = state.plan(home, source)
        stage = state.stage(home, source, identifier, selected["plan_sha256"])
        case["stage"] = stage
        case["target"] = Path(stage["receipt"]).parent
        plan = update.plan(home, identifier)
        case["plan"] = plan
        evidence = case["target"] / "fixture-source-review.json"
        evidence.write_text(json.dumps({"scope": "Explicit owned fixture source review only", "candidate_sha256": stage["candidate_sha256"]}))
        contract = {"schema": update.QUALIFICATION, "scope": "compatible-runtime-only", "qualified": True,
                    "execution_authorized": True, "evidence": [{"path": str(evidence), "sha256": digest(evidence)}],
                    **{key: plan[key] for key in ("home", "operation", "stage_receipt_sha256", "candidate_sha256")}}
        qualification = case["target"] / "qualification.json"
        qualification.write_text(json.dumps(contract))
        case["qualification"] = qualification
        return case

    def apply(self, case=None):
        case = case or self.case
        return update.apply(case["home"], case["operation"], case["plan"]["plan_sha256"],
                            case["qualification"], digest(case["qualification"]), execute_qualified_runtime=True)

    def journal(self, case=None):
        case = case or self.case
        return case["target"] / "runtime-update.json"

    def doctor(self, case=None, expected=0):
        case = case or self.case
        result = subprocess.run([sys.executable, "-B", str(case["home"] / "agent-home.py"), "doctor"],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, expected, result.stderr)
        return result


class ReadOnlyUpdateTests(UpdateFixture):
    def test_plan_binds_exact_stage_and_keeps_candidate_unaccepted(self):
        case = self.prepare()
        self.assertEqual(case["plan"]["holds"], [])
        self.assertEqual(case["plan"]["apply_result"], "activated_pending_consumer_acceptance; not accepted")
        self.assertEqual(case["plan"]["personal_template_adoption"], "none")
        self.assertFalse(self.journal().exists())
        self.assertEqual(state.active_snapshot(case["home"])[2], case["before"])

    def test_entry_and_template_migrations_are_held(self):
        case = self.case
        for relative in ("harness/home.py", "harness/templates/agent-home/agent/APPEND_SYSTEM.md"):
            file = case["source"] / relative
            file.write_bytes(file.read_bytes() + b"\n# incompatible fixture migration\n")
        self.prepare()
        self.assertTrue(any("protocol migration" in item for item in case["plan"]["holds"]))
        self.assertTrue(any("template migration" in item for item in case["plan"]["holds"]))
        with self.assertRaisesRegex(ValueError, "migration"):
            self.apply()
        self.assertFalse((case["home"] / update.PENDING).exists())

    def test_qualification_acknowledgement_and_retained_evidence_are_required(self):
        case = self.prepare()
        with self.assertRaisesRegex(ValueError, "acknowledgement"):
            update.apply(case["home"], case["operation"], case["plan"]["plan_sha256"],
                         case["qualification"], digest(case["qualification"]))
        (case["target"] / "fixture-source-review.json").write_text("changed after review")
        with self.assertRaisesRegex(ValueError, "evidence drift"):
            self.apply()
        self.assertFalse(self.journal().exists())

    @unittest.skipIf(sys.platform == "linux", "Actual unsupported-platform activation refusal")
    def test_actual_windows_refuses_activation_without_mutating_the_working_generation(self):
        case = self.prepare()
        with self.assertRaisesRegex(ValueError, "require Linux"):
            self.apply()
        self.assertFalse(self.journal().exists())
        self.assertFalse((case["home"] / update.PENDING).exists())
        self.assertEqual(state.active_snapshot(case["home"])[2], case["before"])


@unittest.skipUnless(sys.platform == "linux", "Actual Linux generation exchange")
class LinuxRuntimeUpdateTests(UpdateFixture):
    def test_noninteractive_helper_gets_eof_and_timeout_keeps_partial_diagnostics(self):
        case = self.prepare()
        program = "import sys,time;data=sys.stdin.buffer.read();print('EOF='+str(len(data)),flush=True);print('retained-stderr',file=sys.stderr,flush=True);time.sleep(3)"
        driver = (
            "import json,sys\nfrom pathlib import Path\nsys.path.insert(0," + repr(str(REPO)) + ")\n"
            "from harness import runtime_update as u\nu.COMMAND_TIMEOUT=.5\ntry:\n"
            " u.run_bound(" + repr([sys.executable, "-B", "-u", "-c", program])
            + ",home=Path(" + repr(str(case["home"])) + "),target=Path(" + repr(str(case["target"])) + "),label='cpu-timeout')\n"
            "except u.UpdateError as error:print(json.dumps({'error':str(error)}),flush=True)\n"
        )
        child = subprocess.Popen([sys.executable, "-B", "-u", "-c", driver], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            import select
            self.assertTrue(select.select([child.stdout], [], [], 5)[0], "Driver waited on inherited control input")
            result = json.loads(child.stdout.readline())
            self.assertIn("timed out", result["error"])
            self.assertEqual(child.wait(timeout=5), 0)
            # The caller control pipe remained open throughout. Only DEVNULL
            # could have supplied the EOF that the actual CPU child observed.
            self.assertFalse(child.stdin.closed)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=3)
            for stream in (child.stdin, child.stdout, child.stderr):
                stream.close()
        record_file = next(case["target"].glob("cpu-timeout-*.json"))
        record = state.read_json(record_file)
        self.assertTrue(record["timed_out"])
        self.assertEqual(record["stdin"], "DEVNULL")
        self.assertIsNone(record["code"])
        self.assertIn(b"EOF=0", record_file.with_suffix(".stdout").read_bytes())
        self.assertIn(b"retained-stderr", record_file.with_suffix(".stderr").read_bytes())

    def test_apply_changes_final_path_bindings_but_accepts_only_after_actual_managed_doctor(self):
        case = self.prepare()
        staged = case["target"] / "candidate/runtime"
        staged_before = update.inventory(staged)
        result = self.apply()
        self.assertEqual(result["status"], "activated_pending_consumer_acceptance")
        self.assertFalse(result["accepted"])
        self.assertFalse((case["home"] / update.PENDING).exists())
        self.assertEqual(update.inventory(staged), staged_before)
        binding = state.read_json(case["home"] / "runtime" / update.WORKFLOW)
        self.assertEqual(binding["runtime"], str(case["home"] / "runtime"))
        self.assertNotEqual(state.active_snapshot(case["home"])[2]["sha256"], case["before"]["sha256"])
        with mock.patch.object(state.bootstrap, "doctor", side_effect=AssertionError("Old imported doctor must not qualify the new runtime")):
            accepted = update.verify(case["home"], case["operation"], digest(self.journal()))
        self.assertEqual(accepted["status"], "accepted")
        self.assertIn("Core inspection only", accepted["acceptance_scope"])
        self.assertEqual(accepted["doctor"]["command"]["argv"][2], str(case["home"] / "agent-home.py"))
        self.assertEqual(accepted["doctor"]["result"]["failures"], [])

    def test_rollback_restores_exact_accepted_generation_and_preserves_new_user_data(self):
        case = self.prepare()
        self.apply()
        update.verify(case["home"], case["operation"], digest(self.journal()))
        new_data = case["home"] / "context/new-after-activation.md"
        new_data.write_text("new owner data must survive generation rollback")
        auth = case["home"] / "agent/auth.json"
        auth.write_text("synthetic owner auth changed after activation")
        case["protected_bytes"][str(auth)] = auth.read_bytes()
        result = update.rollback(case["home"], case["operation"], digest(self.journal()))
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(state.active_snapshot(case["home"])[2], case["before"])
        self.assertEqual(new_data.read_text(), "new owner data must survive generation rollback")
        self.assertEqual(auth.read_text(), "synthetic owner auth changed after activation")
        self.assertEqual(result["rollback_doctor"]["result"]["failures"], [])
        self.assertFalse((case["home"] / update.PENDING).exists())
        self.assertTrue(any((case["target"] / "activation").glob("retired-runtime-*")))
        self.assertTrue((case["target"] / "candidate/runtime").is_dir())
        with self.assertRaises(ValueError):
            update.rollback(case["home"], case["operation"], digest(self.journal()))

    def test_unaccepted_coherent_generation_can_be_explicitly_rolled_back(self):
        case = self.prepare()
        self.apply()
        result = update.rollback(case["home"], case["operation"], digest(self.journal()))
        self.assertEqual(result["status"], "rolled_back")
        self.assertEqual(state.active_snapshot(case["home"])[2], case["before"])

    def test_each_exchange_and_config_fault_keeps_pending_until_exact_recovery(self):
        points = (("pending-published", 1), ("old-runtime-moved", 1), ("new-runtime-installed", 1),
                  ("binding:home.json", 1), ("binding:home.json", 2), ("coherent-activation-committed", 1))
        for index, (point, occurrence) in enumerate(points):
            with self.subTest(point=point, occurrence=occurrence):
                case = self.prepare(self.new_case("fault-" + str(index)))
                seen = 0

                def interrupt(step):
                    nonlocal seen
                    if step == point:
                        seen += 1
                        if seen == occurrence:
                            raise OSError("Injected interruption: " + point)

                with mock.patch.object(update, "_fault", side_effect=interrupt):
                    with self.assertRaisesRegex(OSError, "Injected interruption"):
                        self.apply(case)
                self.assertTrue((case["home"] / update.PENDING).exists())
                self.assertIn("Pending activation", self.doctor(case, expected=1).stderr)
                restored = update.recover(case["home"], case["operation"], digest(self.journal(case)))
                self.assertEqual(restored["status"], "recovered_predecessor")
                self.assertEqual(state.active_snapshot(case["home"])[2], case["before"])
                self.assertFalse((case["home"] / update.PENDING).exists())

    def test_rollback_interruption_can_recover_without_losing_either_source_tree(self):
        case = self.prepare()
        self.apply()

        def interrupt(step):
            if step == "restore-runtime-installed":
                raise OSError("Injected rollback interruption")

        with mock.patch.object(update, "_fault", side_effect=interrupt):
            with self.assertRaisesRegex(OSError, "rollback interruption"):
                update.rollback(case["home"], case["operation"], digest(self.journal()))
        self.assertTrue((case["home"] / update.PENDING).exists())
        update.recover(case["home"], case["operation"], digest(self.journal()))
        self.assertEqual(state.active_snapshot(case["home"])[2], case["before"])
        self.assertTrue(any((case["target"] / "activation").glob("retired-runtime-*")))

    def test_active_or_predecessor_drift_is_refused_without_overwriting_unknown_bytes(self):
        case = self.prepare()
        self.apply()
        active = case["home"] / "runtime/harness/enforcement.py"
        active.write_bytes(active.read_bytes() + b"\n# independent source drift\n")
        before = active.read_bytes()
        with self.assertRaisesRegex(ValueError, "drift"):
            update.rollback(case["home"], case["operation"], digest(self.journal()))
        self.assertEqual(active.read_bytes(), before)
        self.assertFalse((case["home"] / update.PENDING).exists())

    def test_predecessor_drift_refuses_before_publishing_a_rollback_pending_marker(self):
        case = self.prepare()
        self.apply()
        previous = case["target"] / "activation/predecessor-runtime/harness/enforcement.py"
        raw = previous.read_bytes()
        previous.write_bytes(raw + b"\n# predecessor drift\n")
        with self.assertRaisesRegex(ValueError, "Predecessor runtime drift"):
            update.rollback(case["home"], case["operation"], digest(self.journal()))
        self.assertFalse((case["home"] / update.PENDING).exists())
        previous.write_bytes(raw)
        backup = case["target"] / "activation/original/home.json"
        backup.write_bytes(backup.read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "binding predecessor drift"):
            update.rollback(case["home"], case["operation"], digest(self.journal()))
        self.assertFalse((case["home"] / update.PENDING).exists())
        self.assertEqual(json.loads(self.doctor().stdout)["failures"], [])

    def test_pending_foreign_operation_and_journal_replay_are_not_cleared(self):
        case = self.prepare()
        result = self.apply()
        with self.assertRaisesRegex(ValueError, "replay"):
            self.apply()
        pending = case["home"] / update.PENDING
        pending.write_text(json.dumps({"schema": update.SCHEMA, "home": str(case["home"]), "operation": "foreign"}))
        before = pending.read_bytes()
        with self.assertRaisesRegex(ValueError, "different operation"):
            update.recover(case["home"], case["operation"], result["journal_sha256"])
        self.assertEqual(pending.read_bytes(), before)

    def test_owned_hub_requires_explicit_stop_and_shared_consumer_refuses_exchange(self):
        case = self.prepare()
        with home_entry_for_test(case["home"]) as held:
            self.assertTrue(held)
            with self.assertRaisesRegex(ValueError, "busy"):
                self.apply()
        owner = case["home"] / "state/mempalace-hub/owner.json"
        owner.parent.mkdir()
        owner.write_text("stale fixture ownership; operator must explicitly stop")
        with self.assertRaisesRegex(ValueError, "explicit owned palace stop"):
            self.apply()
        self.assertFalse(self.journal().exists())
        self.assertFalse((case["home"] / update.PENDING).exists())

    def test_real_cli_plan_apply_verify_and_rollback(self):
        case = self.prepare()
        command = [sys.executable, "-B", "-m", "harness.runtime_update", "--home", str(case["home"])]

        def run(arguments):
            result = subprocess.run([*command, *arguments], cwd=REPO, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

        selected = run(["plan", "--operation", case["operation"]])
        activated = run(["apply", "--operation", case["operation"], "--expected-plan", selected["plan_sha256"],
                         "--qualification", str(case["qualification"]), "--qualification-sha256", digest(case["qualification"]),
                         "--execute-qualified-runtime"])
        self.assertFalse(activated["accepted"])
        accepted = run(["verify", "--operation", case["operation"], "--expected-journal", digest(self.journal())])
        self.assertTrue(accepted["accepted"])
        restored = run(["rollback", "--operation", case["operation"], "--expected-journal", digest(self.journal())])
        self.assertEqual(restored["status"], "rolled_back")


def home_entry_for_test(home):
    # Existing real guard API, not a mocked service/lease.
    from harness import home_entry
    return home_entry.consumer(home)


if __name__ == "__main__":
    unittest.main()
