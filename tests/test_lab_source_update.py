"""Released60-to61 frontier; package/consumer fixtures are not native proof."""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from harness import home as bootstrap, maintenance as state, runtime_update as update
from harness.research_install import REQUIREMENTS
from tests import test_agent_core_update as core_fixture
from tests.test_controller_migration import legacy_controller_source
from tests.test_runtime_update import UpdateFixture, digest


def checked_home(text, expected):
    tree = ast.parse(text)
    for child in ast.walk(tree):
        if hasattr(child, "type_params"):
            del child.type_params
    observed = {node.name: update.node_hash(node) for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name in expected}
    if observed != expected:
        raise AssertionError("Frozen released home definitions differ")
    return text


def source60_home():
    return checked_home(legacy_controller_source(), update.CORE_LAB_OLD_NODES)


def source61_home():
    # Exactly the two public additions in 1aceecd37220c630ef7f71766f90457f827c8af2.
    # Do not reverse changes from the current installer or alter admission hashes.
    text = source60_home()
    environment = next(node for node in ast.parse(text).body
                       if isinstance(node, ast.FunctionDef) and node.name == "environment")
    original = ast.get_source_segment(text, environment)
    marker = '    if config.get("framework_binding_sha256"):\n'
    addition = '''    if config.get("profile") == "full":
        helper = home / "runtime/adapters/pi/lab/harness_lab.py"
        lab_python = executable(home / "envs/harness2")
        value.update({"PI_HARNESS_LAB_PYTHON": str(lab_python), "PI_HARNESS_LAB_HELPER": str(helper),
                      "PI_HARNESS_LAB_HELPER_SHA256": digest(helper)})
        if lab_python.is_file():
            from harness import home_entry
            command = home_entry.guarded_command(home, [str(lab_python), "-s", "-B", str(home / "runtime/pi-task-worker.py"),
                                                       "--guard", str(lab_python), "-I", "-B", str(helper), "--home", str(home)],
                                                 python=str(lab_python))
            encoded = json.dumps(command, ensure_ascii=False, separators=(",", ":"))
            value["PI_HARNESS_LAB_COMMAND"] = encoded
            value["PI_HARNESS_LAB_COMMAND_SHA256"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
'''
    if original.count(marker) != 1 or text.count(original) != 1:
        raise AssertionError("Frozen environment insertion point changed")
    text = text.replace(original, original.replace(marker, addition + marker))
    marker = '            extensions.append(str(runtime / "adapters/pi/claude-memory.ts"))\n'
    if text.count(marker) != 1:
        raise AssertionError("Frozen extension insertion point changed")
    text = text.replace(marker, marker + '            extensions.append(str(runtime / "adapters/pi/lab/harness-lab.ts"))\n')
    return checked_home(text, update.CORE_LAB_NEW_NODES)


def source60_verify():
    # Exact public source60 _verify body, retained as text for offline archives.
    # Normalize only transport EOL; do not rewrite the verifier's source/logic.
    file = Path(__file__).with_name("fixtures") / "runtime-update-source60-verify.txt"
    text = file.read_text(encoding="utf-8")
    if hashlib.sha256(text.encode()).hexdigest() != "f542553f3c73b91b8bdf6f958d0eda0d0906a06beeaa9d3b51cc561c80de68b0":
        raise AssertionError("Frozen released60 verifier source changed")
    namespace = dict(vars(update))
    exec(compile(text, str(file), "exec"), namespace)
    return namespace["_verify"]


class LabSourceUpdateTests(UpdateFixture):
    refresh_manifest = core_fixture.AgentCoreUpdateTests.refresh_manifest
    prepare_core = core_fixture.AgentCoreUpdateTests.prepare_core
    fixture_consumers = core_fixture.AgentCoreUpdateTests.fixture_consumers

    def setUp(self):
        super().setUp()
        case = self.case
        candidate = case["source"] / "harness/home.py"
        candidate.write_text(source61_home(), encoding="utf-8")
        spec = importlib.util.spec_from_file_location("harness.lab_source61_unit_fixture", candidate)
        historical_home = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(historical_home)
        binding = mock.patch.object(state, "bootstrap", historical_home)
        binding.start()
        self.addCleanup(binding.stop)
        check = mock.patch.object(historical_home, "check_package", return_value=None)
        check.start()
        self.addCleanup(check.stop)
        file = case["home"] / "runtime/harness/home.py"
        file.write_text(source60_home(), encoding="utf-8")
        # Synthetic old payload identity only. The frozen old verifier is
        # executed below; actual old complete-controller proof is native QA.
        file = case["home"] / "runtime/harness/runtime_update.py"
        file.write_bytes(file.read_bytes() + b"\n# Synthetic predecessor payload identity\n")
        config = state.read_json(case["home"] / "home.json")
        config.update(profile="agent", selected_packages={key: bootstrap.PINS[key] for key in update.CORE_PACKAGES},
                      research_requirements=list(REQUIREMENTS), installed={})
        for key in update.CORE_PACKAGES:
            artifact = case["home"] / "packages" / (key + ".fixture")
            artifact.write_text("Synthetic package identity, never executed", encoding="utf-8")
            config["installed"][key] = {"requested": bootstrap.PINS[key], "observed": "synthetic-unit-fixture",
                                         "artifacts": [{"path": str(artifact), "sha256": digest(artifact)}]}
        (case["home"] / "home.json").write_text(json.dumps(config), encoding="utf-8")
        settings = state.read_json(case["home"] / "agent/settings.json")
        settings["extensions"] = [str(case["home"] / "runtime/adapters/pi/project-workflow/agent-capabilities.ts")]
        (case["home"] / "agent/settings.json").write_text(json.dumps(settings), encoding="utf-8")
        (case["home"] / "agent/mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")
        self.refresh_manifest()
        case["before"] = state.active_snapshot(case["home"])[2]

    def check_frontier_admission(self):
        case = self.prepare_core()
        self.assertEqual(case["plan"]["core_source"]["frontier"], "agent-lab-source-v1")
        self.assertEqual(case["plan"]["apply_result"], "core_lab_pending_consumer_acceptance; not accepted")
        self.assertTrue(any("protocol migration" in item for item in update.plan(case["home"], case["operation"])["holds"]))
        with self.assertRaisesRegex(ValueError, "controller-cli-v1"):
            update.controller_plan(case["home"], case["operation"])
        file = case["source"] / "harness/home.py"
        original = file.read_bytes()
        try:
            file.write_bytes(Path(bootstrap.__file__).read_bytes())
            with self.assertRaisesRegex(ValueError, "Unreviewed home|outside agent-core"):
                update.core_source_bindings(case["home"], case["source"])
        finally:
            file.write_bytes(original)
        for before, after in [('"agent": ("pi", "hermes", "mempalace", "framework", "research")',
                               '"agent": ("pi", "hermes")'),
                              ('"PI_HARNESS_LAB_COMMAND"', '"CHANGED_LAB_COMMAND"')]:
            try:
                text = original.decode("utf-8")
                self.assertEqual(text.count(before), 1)
                file.write_bytes(text.replace(before, after).encode("utf-8"))
                with self.assertRaisesRegex(ValueError, "Unreviewed home|outside agent-core"):
                    update.core_source_bindings(case["home"], case["source"])
            finally:
                file.write_bytes(original)
        config = case["home"] / "home.json"
        previous = config.read_bytes()
        try:
            value = json.loads(previous)
            value["profile"] = "full"
            config.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unchanged five"):
                update.core_package_bindings(case["home"])
        finally:
            config.write_bytes(previous)
        with self.assertRaisesRegex(ValueError, "Unreviewed core"):
            update.core_source_states({"frontier": "unknown"})
        qualification = case["qualification"]
        previous = qualification.read_bytes()
        try:
            value = json.loads(previous)
            del value["core_source"]["frontier"]
            qualification.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "qualification.*bindings"):
                update.qualified(qualification, digest(qualification), case["plan"], True)
        finally:
            qualification.write_bytes(previous)

    def check_old_verifier_exchange_and_rollback(self):
        case = self.case  # Admission above already staged this exact operation.
        settings = (case["home"] / "agent/settings.json").read_bytes()
        value = update.core_source_apply(case["home"], case["operation"], case["plan"]["plan_sha256"],
                                         case["qualification"], digest(case["qualification"]), execute_qualified_runtime=True)
        self.assertEqual(value["status"], update.CORE_LAB_PENDING)
        old = source60_verify()
        with self.assertRaisesRegex(ValueError, "Only a coherent activated generation"):
            old(case["home"], case["operation"], digest(self.journal()), core_source=True)
        with mock.patch.object(update, "managed_doctor", return_value={}), \
                mock.patch.object(update, "run_bound", return_value=('{}', {})), \
                self.assertRaisesRegex(ValueError, "research"):
            update.core_source_verify(case["home"], case["operation"], digest(self.journal()))
        self.assertEqual(state.read_json(self.journal())["status"], update.CORE_LAB_FAILED)
        with self.assertRaisesRegex(ValueError, "Only a coherent activated generation"):
            old(case["home"], case["operation"], digest(self.journal()), core_source=True)
        with mock.patch.object(update, "managed_doctor", return_value={"runtime_manifest_sha256": digest(case["home"] / "runtime/runtime-manifest.json")}), \
                mock.patch.object(update, "run_bound", side_effect=self.fixture_consumers):
            self.assertTrue(update.core_source_verify(case["home"], case["operation"], digest(self.journal()))["accepted"])
        added = case["home"] / "context/new-personal.txt"
        added.write_text("Preserve post-activation data", encoding="utf-8")
        with mock.patch.object(update, "managed_doctor", return_value={}):
            self.assertEqual(update.rollback(case["home"], case["operation"], digest(self.journal()))["status"], "rolled_back")
        self.assertEqual(added.read_text(encoding="utf-8"), "Preserve post-activation data")
        self.assertEqual((case["home"] / "agent/settings.json").read_bytes(), settings)
        self.assertEqual(state.active_snapshot(case["home"])[2]["sha256"], case["before"]["sha256"])

    def check_new_pending_interruption_and_recovery(self):
        case = self.prepare_core()
        def fault(step):
            if step == "coherent-activation-committed":
                raise OSError("Controlled new-frontier interruption")
        with mock.patch.object(update, "_fault", side_effect=fault), self.assertRaisesRegex(OSError, "new-frontier"):
            update.core_source_apply(case["home"], case["operation"], case["plan"]["plan_sha256"],
                                     case["qualification"], digest(case["qualification"]), execute_qualified_runtime=True)
        self.assertTrue((case["home"] / update.PENDING).exists())
        original = self.journal().read_bytes()
        try:
            value = json.loads(original)
            value["core_source"]["python_sha256"] = "0" * 64
            value["qualification"]["contract"]["core_source"] = copy.deepcopy(value["core_source"])
            self.journal().write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "interpreter drift"):
                update.recover(case["home"], case["operation"], digest(self.journal()))
            self.assertTrue((case["home"] / update.PENDING).exists())
        finally:
            self.journal().write_bytes(original)
        with mock.patch.object(update, "managed_doctor", return_value={}):
            self.assertTrue(update.recover(case["home"], case["operation"], digest(self.journal()))["predecessor_restored"])
        self.assertEqual(state.active_snapshot(case["home"])[2]["sha256"], case["before"]["sha256"])

    def check_rollback_interruption_and_user_data(self):
        case = self.prepare_core()
        update.core_source_apply(case["home"], case["operation"], case["plan"]["plan_sha256"],
                                 case["qualification"], digest(case["qualification"]), execute_qualified_runtime=True)
        added = case["home"] / "context/post-activation.txt"
        added.write_bytes(b"Owned data survives rollback/recovery")
        def fault(step):
            if step == "rollback-restored-coherently":
                raise OSError("Controlled rollback interruption")
        with mock.patch.object(update, "_fault", side_effect=fault), self.assertRaisesRegex(OSError, "rollback interruption"):
            update.rollback(case["home"], case["operation"], digest(self.journal()))
        with mock.patch.object(update, "managed_doctor", return_value={}):
            self.assertTrue(update.recover(case["home"], case["operation"], digest(self.journal()))["predecessor_restored"])
        self.assertEqual(added.read_bytes(), b"Owned data survives rollback/recovery")
        self.assertEqual(state.active_snapshot(case["home"])[2]["sha256"], case["before"]["sha256"])

    def test_released_frontier_admission_exchange_and_interrupted_recovery(self):
        # One scaffold instead of four. Every negative restores its bytes in
        # finally above; each subsequent transaction gets a new native operation.
        # Stop on a failed phase rather than letting uncertain state qualify the
        # next negative for an unrelated reason.
        self.check_frontier_admission()
        if os.name != "posix":
            return  # Metadata only; no Linux exchange/ownership claim.
        self.check_old_verifier_exchange_and_rollback()
        for identifier, check in (("lab-frontier-recovery", self.check_new_pending_interruption_and_recovery),
                                  ("lab-frontier-rollback", self.check_rollback_interruption_and_user_data)):
            self.assertFalse(state.pending_operations(self.case["home"]))
            self.assertEqual(state.active_snapshot(self.case["home"])[2]["sha256"], self.case["before"]["sha256"])
            self.case["operation"] = identifier
            check()
        self.assertEqual((self.case["home"] / "context/new-personal.txt").read_text(encoding="utf-8"),
                         "Preserve post-activation data")


if __name__ == "__main__":
    unittest.main()
