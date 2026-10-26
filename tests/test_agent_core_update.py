"""Reviewed home-node frontier and real source exchange, with synthetic packages.

Package/consumer jobs below are explicit unit fixtures. They do not qualify an
installed Pi profile, observer package, memory worker or model request.
"""
import ast
import copy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import unittest
from unittest import mock

from harness import home as bootstrap, maintenance as state, runtime_update as update
from harness.research_install import REQUIREMENTS
from tests.test_controller_migration import redacted_status, legacy_controller_source
from tests.test_runtime_update import UpdateFixture, digest


def source40_home():
    """Reverse only the published source41 diff; require real old node hashes."""
    text = legacy_controller_source()
    def replace(old, new=""):
        nonlocal text
        if text.count(old) != 1:
            raise AssertionError("Frozen home fixture frontier changed: " + old[:70])
        text = text.replace(old, new, 1)

    def definition(name, replacement=""):
        nonlocal text
        node = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == name)
        start = min([node.lineno, *(d.lineno for d in node.decorator_list)]) - 1
        lines = text.splitlines(keepends=True)
        text = "".join(lines[:start]) + replacement + "".join(lines[node.end_lineno:])

    replace("timeout=900, pass_fds=()):", "timeout=900):")
    replace("shell=False, pass_fds=pass_fds)", "shell=False)")
    replace('    observer_policy = source / "harness/claude-memory-patch.json"\n'
            '    if (source / "harness/claude_memory_patch.py").exists():\n'
            '        if not observer_policy.is_file() or observer_policy.is_symlink() or observer_policy.resolve() != observer_policy.absolute():\n'
            '            raise HomeError("The observer requires its canonical downstream patch manifest.")\n'
            '        paths.append(observer_policy)\n')
    replace('            from harness import claude_memory_patch\n'
            '            claude_memory_patch.verify(home)\n'
            '            paths.extend(claude_memory_patch.artifacts(home)[1:])\n')
    replace('    if key == "claude-mem":\n'
            '        from harness import claude_memory_patch\n'
            '        try:\n'
            '            claude_memory_patch.verify(home)\n'
            '        except (OSError, ValueError, KeyError, TypeError) as error:\n'
            '            return "Claude-mem downstream patch verification failed: " + str(error)\n')
    definition("install_packages", 'def install_packages(home, config, python312=None):\n'
               '    package_plan(config)\n    from harness import home_entry\n'
               '    with home_entry.consumer(home):\n        return _install_packages(home, config, python312)\n')
    definition("_observer_install_exclusive")
    replace("def _install_packages(home, config, python312=None, *, only=None, finalize=True, lifecycle_fds=()):",
            "def _install_packages(home, config, python312=None):")
    replace('    if only is not None:\n'
            '        if not isinstance(only, tuple) or not set(only).issubset(selected):\n'
            '            raise HomeError("Internal package selection differs from the pinned plan.")\n'
            '        selected = tuple(key for key in selected if key in only)\n')
    replace('            install_options = {"pass_fds": lifecycle_fds} if lifecycle_fds else {}\n')
    replace(", env=env, **install_options)", ", env=env)")
    replace('        if key == "claude-mem":\n'
            '            from harness import claude_memory_patch\n'
            '            claude_memory_patch.stage(home)\n')
    replace("    if not finalize:\n        return\n")
    nodes = ast.parse(text).body
    # node_hash uses the same C7 normalization as the production plan.
    for node in nodes:
        for child in ast.walk(node):
            if hasattr(child, "type_params"):
                del child.type_params
    observed = {n.name: update.node_hash(n) for n in nodes if isinstance(n, ast.FunctionDef) and n.name in update.CORE_OLD_NODES}
    if observed != update.CORE_OLD_NODES:
        raise AssertionError("Reconstructed public source40 nodes do not match reviewed AST hashes")
    return text


# Actual public source40 verifier body and unchanged helper identities.
# This avoids a dependency on Git history in installed/source-release tests.
OLD40_VERIFY_SHA256 = 'aed49558e940f2c6fbbec02c147c030939342384016cc7fd96055e19b07c7e97'
OLD40_HELPERS = {'require': '6aeb536b362738532cea8f44f98d50cab3736a4200891dd62a80e09767d3971c', 'operation': '1e7759db668c85bb87344e3bf61751e79465a6cff4b4d26f936251e113a1319d', 'load_update': 'c04e21c923c6f8b2106b4e7eb18344e51dbb370cb7a86bfe94fca1ec4345a4fd', 'managed_doctor': '27323f1e7f13f386b2797c6fde9875f996724f78f09f87d5327b3a09d2efc554', 'executing_controller': '9f4e9d22f7781945ebbcd40f52b7981cac146d8de28e9e1793f9c87089884689', 'validate_research_status': 'deb78cebf2e66b5a57a32ce9a3f4b5e5153e08c422eab423d3cb190110543496', 'run_bound': 'df01cc6ad4762fb2216ddffa4c598b9aa660a9eec99bfddfc0fb4fe74381582c'}
OLD40_VERIFY = r'''def _verify(home, identifier, expected_journal, *, controller=False):
    home, target, _stage, journal, value = load_update(home, identifier, expected_journal)
    with home_entry.consumer(home), state.operation_lock(home, identifier):
        require(state.digest(journal) == expected_journal, "Journal changed before verification admission")
        require(bool(value.get("controller")) == controller, "Use the explicit controller verification scope")
        statuses = {"controller_pending_consumer_acceptance", "controller_verification_failed"} if controller else {
            "activated_pending_consumer_acceptance", "consumer_verification_failed"}
        require(value["status"] in statuses,
                "Only a coherent activated generation can enter consumer verification")
        require(state.active_snapshot(home)[2]["sha256"] == value["after_active_sha256"], "Activated generation drift")
        try:
            value["doctor"] = managed_doctor(home, target)
            if controller:
                retained = target / "candidate/runtime"
                # Recovery must use the reviewed controller even after the source checkout moves.
                require(inventory(home / "runtime") == value["after_runtime"], "Controller runtime drift")
                binding = value["controller"]
                require(value["qualification"]["contract"].get("controller") == binding,
                        "Controller journal/qualification binding differs")
                require(executing_controller(retained) == binding["executing_closure"], "Retained controller closure drift")
                require(str(Path(sys.executable).resolve()) == binding["python"]
                        and state.digest(Path(binding["python"])) == binding["python_sha256"], "Controller interpreter drift")
                text, record = run_bound([Path(value["controller"]["python"]), "-B", home / "agent-home.py", "research", "status"],
                                         home=home, target=target, label="managed-research-status")
                observed = json.loads(text)
                validate_research_status(observed)
                value["controller_consumer"] = {"command": record, "schema": observed["schema"]}
            if value["profile"] == "core":
                value["acceptance_scope"] = "Core inspection only; no Pi/model/runtime enforcement claim"
            else:
                capability_relative = "adapters/pi/project-workflow/agent-capabilities.ts"
                capability = state.inside(home / "runtime", capability_relative, exists=True)
                manifest = state.read_json(home / "runtime/runtime-manifest.json")
                declared = {item["path"]: item["sha256"] for item in manifest["files"]}
                configured = state.read_json(home / "agent/settings.json")
                require(state.digest(capability) == declared.get(capability_relative)
                        and str(capability) in configured.get("extensions", [])
                        and re.search(r"\bpi\.registerCommand\(\s*(['\"])agent-health\1", capability.read_text(encoding="utf-8")),
                        "Known source-bound configured agent-health registration is required before any Pi invocation")
                text, record = run_bound([home / "bin/harness-agent", "--offline", "--print", "/agent-health"],
                                         home=home, target=target, label="managed-pi-health")
                health = []
                for line in text.splitlines():
                    try:
                        item = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(item, dict) and item.get("schema") == "pi-agent-health/v1":
                        health.append(item)
                require(len(health) == 1, "Expected one actual native pi-agent-health/v1 response")
                health = health[0]
                require(health.get("home") == str(home)
                        and health.get("runtime_manifest_sha256") == value["doctor"]["runtime_manifest_sha256"],
                        "Native health target/source binding differs")
                current_config = state.read_json(home / "home.json")
                require(health.get("cwd") == str(home) and health.get("model", {}).get("provider") == "local"
                        and health.get("model", {}).get("id") == current_config["model"], "Native health cwd/model binding differs")
                require(all(isinstance(health.get(key), list) and all(isinstance(name, str) for name in health[key])
                            for key in ("active_tools", "configured_tools")), "Invalid native tool inventory shape")
                require(health.get("readiness", {}).get("ok") is True, "Native configured resources are not ready")
                require(health.get("readiness", {}).get("missing_tools") == [], "Native configured tools are missing")
                require(health.get("authority") == "none" and type(health.get("generative_requests")) is int
                        and health["generative_requests"] == 0,
                        "Native health response is outside its read-only non-generative contract")
                required = {"workflow_step", "project_context", "kanban_intake_route", "validated_memory_query"}
                require(required.issubset(set(health.get("active_tools", []))), "Required native execution/intake/memory gates are missing")
                mcp = state.read_json(home / "agent/mcp.json").get("mcpServers", {}).get("mempalace", {})
                if mcp and mcp.get("enabled", True):
                    readiness = health["readiness"]
                    require(readiness.get("mcp_configured") is True and readiness.get("mcp_observed") is True
                            and "mcp__mempalace__mempalace_search" in health.get("configured_tools", []),
                            "Configured MemPalace discovery was not observed by the actual native handler")
                value["native_health"] = {"command": record, "result": health}
                value["acceptance_scope"] = "Actual stable doctor and normal managed Pi agent-health; no model inference"
            require(state.active_snapshot(home)[2]["sha256"] == value["after_active_sha256"], "Source changed during normal consumer verification")
            value["status"] = "accepted"
            value["candidate_runtime_acceptance"] = value["acceptance_scope"]
            save_journal(journal, value, "normal-consumers-accepted")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            value["status"] = "controller_verification_failed" if controller else "consumer_verification_failed"
            value["consumer_error"] = str(error)
            save_journal(journal, value, "normal-consumer-verification-failed")
            raise
    return {**value, "journal_sha256": state.digest(journal), "accepted": True}'''


def old40_verify():
    # Provider expansion changes the current redacted contract. Execute the
    # exact historical helper, rather than weakening its retained source pin.
    historical_status = (Path(__file__).parent / "fixtures/runtime-update-source40-research-status.txt").read_text(encoding="utf-8").strip()
    for name, pin in OLD40_HELPERS.items():
        source = historical_status if name == "validate_research_status" else inspect.getsource(getattr(update, name)).strip()
        if hashlib.sha256(source.encode()).hexdigest() != pin:
            raise AssertionError("Retained old verifier helper drift: " + name)
    if hashlib.sha256(OLD40_VERIFY.encode()).hexdigest() != OLD40_VERIFY_SHA256:
        raise AssertionError("Retained old verifier source drift")
    namespace = dict(vars(update))
    exec(compile(historical_status, "<public-source40-research-status>", "exec"), namespace)
    exec(compile(OLD40_VERIFY, "<public-source40-verifier>", "exec"), namespace)
    return namespace["_verify"]


class AgentCoreUpdateTests(UpdateFixture):
    def setUp(self):
        super().setUp()
        case = self.case
        candidate = case["source"] / "harness/home.py"
        candidate.write_text(legacy_controller_source(), encoding="utf-8")
        # Execute the real reconstructed home module. Changing only __file__
        # would misrepresent the exact executing controller closure.
        spec = importlib.util.spec_from_file_location("harness.source41_unit_fixture", candidate)
        historical_home = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(historical_home)
        binding = mock.patch.object(state, "bootstrap", historical_home)
        binding.start()
        self.addCleanup(binding.stop)
        # Synthetic artifacts avoid installing or importing external packages.
        self.package_check = mock.patch.object(historical_home, "check_package", return_value=None)
        self.package_check.start()
        self.addCleanup(self.package_check.stop)
        old = case["home"] / "runtime/harness/home.py"
        old.write_text(source40_home(), encoding="utf-8")
        config = state.read_json(case["home"] / "home.json")
        config["profile"] = "agent"
        config["selected_packages"] = {name: bootstrap.PINS[name] for name in update.CORE_PACKAGES}
        config["research_requirements"] = list(REQUIREMENTS)
        config["installed"] = {}
        for name in update.CORE_PACKAGES:
            file = case["home"] / "packages" / (name + ".fixture")
            file.write_text("Synthetic selected package; not an installed runtime")
            config["installed"][name] = {"requested": bootstrap.PINS[name], "observed": "synthetic-unit-fixture",
                                         "artifacts": [{"path": str(file), "sha256": digest(file)}]}
        (case["home"] / "home.json").write_text(json.dumps(config))
        configured = state.read_json(case["home"] / "agent/settings.json")
        configured["extensions"] = [str(case["home"] / "runtime/adapters/pi/project-workflow/agent-capabilities.ts")]
        (case["home"] / "agent/settings.json").write_text(json.dumps(configured))
        (case["home"] / "agent/mcp.json").write_text(json.dumps({"mcpServers": {}}))
        self.refresh_manifest()
        case["before"] = state.active_snapshot(case["home"])[2]

    def refresh_manifest(self):
        home = self.case["home"]
        manifest = home / "runtime/runtime-manifest.json"
        value = state.read_json(manifest)
        for item in value["files"]:
            item["sha256"] = digest(home / "runtime" / item["path"])
        manifest.write_text(json.dumps(value))
        config = state.read_json(home / "home.json")
        config["runtime_manifest_sha256"] = digest(manifest)
        (home / "home.json").write_text(json.dumps(config))
        workflow = home / "runtime" / update.WORKFLOW
        value = state.read_json(workflow)
        value["runtime_manifest_sha256"] = digest(manifest)
        workflow.write_text(json.dumps(value))

    def prepare_core(self):
        case = self.case
        plan = state.plan(case["home"], case["source"])
        case["stage"] = state.stage(case["home"], case["source"], case["operation"], plan["plan_sha256"])
        case["target"] = Path(case["stage"]["receipt"]).parent
        selected = update.core_source_plan(case["home"], case["operation"])
        case["plan"] = selected
        evidence = case["target"] / "core-source-review.json"
        evidence.write_text('{"scope":"Explicit synthetic source qualification only"}')
        contract = {"schema": update.QUALIFICATION, "scope": update.CORE_SOURCE_SCOPE,
                    "qualified": True, "execution_authorized": True,
                    "evidence": [{"path": str(evidence), "sha256": digest(evidence)}],
                    **{key: selected[key] for key in ("home", "operation", "stage_receipt_sha256", "candidate_sha256",
                                                     "active_sha256", "core_source")}}
        case["qualification"] = case["target"] / "core-source-qualification.json"
        case["qualification"].write_text(json.dumps(contract))
        return case

    def apply_core(self):
        case = self.prepare_core()
        result = update.core_source_apply(case["home"], case["operation"], case["plan"]["plan_sha256"],
                                          case["qualification"], digest(case["qualification"]), execute_qualified_runtime=True)
        self.assertEqual(result["status"], "core_source_pending_consumer_acceptance")
        return result

    def fixture_consumers(self, argv, **kwargs):
        home = self.case["home"]
        if list(map(str, argv))[-2:] == ["research", "status"]:
            return json.dumps(redacted_status()), {"fixture": "redacted status only"}
        self.assertEqual(str(argv[0]), str(home / "bin/harness-agent"))
        return json.dumps({"schema": "pi-agent-health/v1", "home": str(home), "cwd": str(home),
                           "runtime_manifest_sha256": state.read_json(home / "home.json")["runtime_manifest_sha256"],
                           "model": {"provider": "local", "id": "no-model-fixture"},
                           "active_tools": ["workflow_step", "project_context", "kanban_intake_route", "validated_memory_query"],
                           "configured_tools": [], "readiness": {"ok": True, "missing_tools": []},
                           "authority": "none", "generative_requests": 0}), {"fixture": "native shape only; no Pi invocation"}

    def test_frontier_is_explicit_and_legacy_scopes_still_refuse(self):
        # These metadata controls share one unchanged scaffold/stage. Repeating
        # full source copies for each negative dominated the source-only suite.
        self.check_function_frontier()
        self.check_extra_packages()
        self.check_settings_only_state()
        case = self.prepare_core()
        self.assertEqual(case["plan"]["holds"], [])
        self.assertEqual(case["plan"]["core_source"]["packages"]["profile"], "agent")
        self.assertTrue(update.plan(case["home"], case["operation"])["holds"])
        with self.assertRaisesRegex(ValueError, "Controller CLI definitions"):
            update.controller_plan(case["home"], case["operation"])
        self.check_qualification()
        self.check_package_bytes_and_closure()

    def check_function_frontier(self):
        candidate = self.case["source"] / "harness/home.py"
        original_bytes = candidate.read_bytes()
        original = candidate.read_text(encoding="utf-8")
        try:
            candidate.write_bytes(Path(bootstrap.__file__).read_bytes())
            # A later frontier may recognize its named nodes, then refuse the
            # remaining current controller definitions. Both paths stay closed.
            with self.assertRaisesRegex(ValueError, "outside agent-core-source|Unreviewed home definitions/constants/imports changed"):
                update.core_source_bindings(self.case["home"], self.case["source"])
        finally:
            candidate.write_bytes(original_bytes)
        for name in update.CORE_NEW_NODES:
            tree = ast.parse(original)
            node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
            node.body.insert(0, ast.Expr(ast.Constant("Unreviewed semantic node")))
            ast.fix_missing_locations(tree)
            try:
                candidate.write_text(ast.unparse(tree), encoding="utf-8")
                with self.subTest(node=name), self.assertRaisesRegex(ValueError, "outside agent-core-source"):
                    update.core_source_bindings(self.case["home"], self.case["source"])
            finally:
                candidate.write_bytes(original_bytes)
        for text in (original + "\nUNREVIEWED = True\n", "import fractions\n" + original,
                     original.replace('parser = CommandParser(', 'parser = argparse.ArgumentParser(', 1)):
            try:
                candidate.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "Unreviewed home"):
                    update.core_source_bindings(self.case["home"], self.case["source"])
            finally:
                candidate.write_bytes(original_bytes)
        data = self.case["source"] / "harness/templates/agent-home/gitignore.template"
        previous = data.read_bytes()
        try:
            data.write_bytes(previous + b"\n# Not the reviewed packaging data\n")
            with self.assertRaisesRegex(ValueError, "Unreviewed gitignore source data"):
                update.core_source_bindings(self.case["home"], self.case["source"])
        finally:
            data.write_bytes(previous)

    def check_settings_only_state(self):
        home = self.case["home"]
        self.assertTrue((home / "memory/claude-mem/settings.json").is_file())
        created = []
        try:
            for name in ("bun", "claude-mem"):
                prefix = home / "packages" / name
                prefix.mkdir()
                created.append(prefix)
                (prefix / "settings.json").write_text('{}')
            update.core_package_bindings(home)
            for prefix in created:
                marker = prefix / "node_modules"
                try:
                    marker.mkdir()
                    with self.assertRaisesRegex(ValueError, "partial package state"):
                        update.core_package_bindings(home)
                finally:
                    marker.rmdir()
        finally:
            for prefix in reversed(created):
                (prefix / "settings.json").unlink()
                prefix.rmdir()

    def check_extra_packages(self):
        home = self.case["home"]
        file = home / "home.json"
        raw = file.read_bytes()
        original = json.loads(raw)
        for key in ("bun", "claude-mem", "deepseek"):
            changed = copy.deepcopy(original)
            changed["installed"][key] = {"requested": "unqualified"}
            try:
                file.write_text(json.dumps(changed))
                with self.subTest(package=key), self.assertRaisesRegex(ValueError, "exactly the unchanged five"):
                    update.core_package_bindings(home)
            finally:
                file.write_bytes(raw)
        changed = copy.deepcopy(original)
        changed["profile"] = "full"
        try:
            file.write_text(json.dumps(changed))
            with self.assertRaisesRegex(ValueError, "exactly the unchanged five"):
                update.core_package_bindings(home)
        finally:
            file.write_bytes(raw)

    def check_qualification(self):
        case = self.case
        file = case["qualification"]
        raw = file.read_bytes()
        original = json.loads(raw)
        values = []
        for key in ("active_sha256", "scope"):
            value = copy.deepcopy(original)
            value[key] = "wrong"
            values.append(value)
        for key in ("python", "packages", "executing_closure"):
            value = copy.deepcopy(original)
            value["core_source"][key] = "wrong"
            values.append(value)
        for value in values:
            try:
                file.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    update.qualified(file, digest(file), case["plan"], True)
            finally:
                file.write_bytes(raw)

    def check_package_bytes_and_closure(self):
        case = self.case
        artifact = case["home"] / "packages/pi.fixture"
        original = artifact.read_bytes()
        try:
            artifact.write_bytes(original + b"unqualified change")
            with self.assertRaisesRegex(ValueError, "Reviewed update plan drift"):
                update.core_source_apply(case["home"], case["operation"], case["plan"]["plan_sha256"],
                                         case["qualification"], digest(case["qualification"]), execute_qualified_runtime=True)
        finally:
            artifact.write_bytes(original)
        with mock.patch.object(state.bootstrap, "__file__", str(case["home"] / "runtime/harness/home.py")), \
                self.assertRaisesRegex(ValueError, "exact staged controller closure"):
            update.core_source_plan(case["home"], case["operation"])
        self.assertFalse(self.journal().exists())

    def test_core_scope_does_not_authorize_template_or_stable_binder_changes(self):
        source = self.case["source"]
        for name in ("harness/templates/agent-home/agent/APPEND_SYSTEM.md", "adapters/pi/intake/framework_binding.py"):
            file = source / name
            file.write_bytes(file.read_bytes() + b"\n# Synthetic unreviewed template/control change\n")
        case = self.prepare_core()
        self.assertTrue(any("template" in value for value in case["plan"]["holds"]))
        self.assertTrue(any("framework_binding" in value for value in case["plan"]["holds"]))
        with self.assertRaises(ValueError):
            update.core_source_apply(case["home"], case["operation"], case["plan"]["plan_sha256"],
                                     case["qualification"], digest(case["qualification"]), execute_qualified_runtime=True)
        self.assertFalse(self.journal().exists())

    @unittest.skipUnless(os.name == "posix", "Real source exchange requires Linux ownership")
    def test_source_exchange_consumer_contract_and_rollback_preserve_packages_and_data(self):
        personal = self.case["home"] / ".gitignore"
        personal.write_bytes(personal.read_bytes() + b"\n# Synthetic personal additions\nprivate-outputs/\n")
        personal_bytes = personal.read_bytes()
        result = self.apply_core()
        case = self.case
        self.assertEqual(personal.read_bytes(), personal_bytes)
        before_packages = result["core_source"]["packages"]
        legacy = old40_verify()
        with self.assertRaisesRegex(ValueError, "Only a coherent activated generation"):
            legacy(case["home"], case["operation"], digest(self.journal()))
        with self.assertRaisesRegex(ValueError, "core source verification scope"):
            update.verify(case["home"], case["operation"], digest(self.journal()))
        with mock.patch.object(update, "managed_doctor", return_value={"fixture": "doctor shape only"}), \
                mock.patch.object(update, "run_bound", return_value=('{}', {})), \
                self.assertRaisesRegex(ValueError, "research"):
            update.core_source_verify(case["home"], case["operation"], digest(self.journal()))
        self.assertEqual(state.read_json(self.journal())["status"], "core_source_verification_failed")
        with self.assertRaisesRegex(ValueError, "Only a coherent activated generation"):
            legacy(case["home"], case["operation"], digest(self.journal()))
        # Fixture consumer jobs are mocked, never labelled native acceptance.
        with mock.patch.object(update, "managed_doctor", return_value={"runtime_manifest_sha256": digest(case["home"] / "runtime/runtime-manifest.json")}), \
                mock.patch.object(update, "run_bound", side_effect=self.fixture_consumers):
            # The consumer fixture uses a disabled MCP server from the outset.
            value = update.core_source_verify(case["home"], case["operation"], digest(self.journal()))
        self.assertTrue(value["accepted"])
        self.assertEqual(update.core_package_bindings(case["home"]), before_packages)
        added = case["home"] / "context/new-user-file.txt"
        added.write_text("Preserve after activation")
        with mock.patch.object(update, "managed_doctor", return_value={"fixture": "predecessor consumer only"}):
            rolled = update.rollback(case["home"], case["operation"], digest(self.journal()))
        self.assertEqual(rolled["status"], "rolled_back")
        self.assertEqual(added.read_text(), "Preserve after activation")
        self.assertEqual(personal.read_bytes(), personal_bytes)
        self.assertEqual(update.core_package_bindings(case["home"]), before_packages)

    @unittest.skipUnless(os.name == "posix", "Real source exchange requires Linux ownership")
    def test_interrupted_core_exchange_uses_retained_recovery_and_preserves_pending_on_drift(self):
        case = self.prepare_core()
        def fail(step):
            if step == "new-runtime-installed":
                raise OSError("Synthetic exchange interruption")
        with mock.patch.object(update, "_fault", side_effect=fail), self.assertRaisesRegex(OSError, "Synthetic exchange"):
            update.core_source_apply(case["home"], case["operation"], case["plan"]["plan_sha256"],
                                     case["qualification"], digest(case["qualification"]), execute_qualified_runtime=True)
        original = self.journal().read_bytes()
        value = state.read_json(self.journal())
        value["core_source"]["python_sha256"] = "0" * 64
        value["qualification"]["contract"]["core_source"] = copy.deepcopy(value["core_source"])
        self.journal().write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "interpreter drift"):
            update.recover(case["home"], case["operation"], digest(self.journal()))
        self.assertTrue((case["home"] / update.PENDING).exists())
        self.journal().write_bytes(original)
        with mock.patch.object(update, "managed_doctor", return_value={"fixture": "old doctor job only"}):
            result = update.recover(case["home"], case["operation"], digest(self.journal()))
        self.assertTrue(result["predecessor_restored"])
        self.assertFalse((case["home"] / update.PENDING).exists())
        self.assertEqual(state.active_snapshot(case["home"])[2]["sha256"], case["before"]["sha256"])


if __name__ == "__main__":
    unittest.main()
