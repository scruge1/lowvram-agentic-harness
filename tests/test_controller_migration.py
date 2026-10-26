"""Narrow controller migration fixtures; no installed target or model calls."""
import copy
import hashlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

from harness import runtime_update as update, maintenance as state
from tests.test_runtime_update import UpdateFixture, digest

# Retained actual verifier from 724818a, independently executed below. Its
# imports/helpers are unchanged by this migration; this is not a mock verifier.
OLD_HELPERS = {'require': '8c195cc2f79b17698e1a0015ded4c17552d4d8f2dab9d900e33d9f04cd347245', 'operation': 'b7673dddf4cd055d7c0c3c52ff9a6a30ce5f0adf404d4614b11d05240d178683', 'load_update': '2ebb0ed7b07ceb45e06433eebbac77cf38f644b74fb439a2fec4af91fd8153ea'}
OLD_FIXED_MODULES = {'harness/maintenance.py': 'adf106162d739f4fef156873fdd9f63b7448a0959c9c04975c6280886911ee2b', 'harness/home_entry.py': 'cd1d42117f6e8dcec8da8f31e5cde4416bc3b5e48fe7693f63be2db91bc609df'}
OLD_VERIFY_SHA256 = "e3ea62ccd851d1034421cbb50ab918742559288adafab500152234759cb6a69d"
OLD_VERIFY = r'''
def verify(home, identifier, expected_journal):
    home, target, _stage, journal, value = load_update(home, identifier, expected_journal)
    with home_entry.consumer(home), state.operation_lock(home, identifier):
        require(state.digest(journal) == expected_journal, "Journal changed before verification admission")
        require(value["status"] in {"activated_pending_consumer_acceptance", "consumer_verification_failed"},
                "Only a coherent activated generation can enter consumer verification")
        require(state.active_snapshot(home)[2]["sha256"] == value["after_active_sha256"], "Activated generation drift")
        try:
            value["doctor"] = managed_doctor(home, target)
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
            value["status"] = "consumer_verification_failed"
            value["consumer_error"] = str(error)
            save_journal(journal, value, "normal-consumer-verification-failed")
            raise
    return {**value, "journal_sha256": state.digest(journal), "accepted": True}

'''


def legacy_controller_source():
    """Exact public pre-board home.py; no Git history or new-scope assumption."""
    # Commit3808ec7610d3e2d083cd68124c75d381e956a74d, harness/home.py;
    # Git blob6c4f6da54eff24ae49caf79a5b3a445fcd8168ed. Accept only raw
    # Git LF or its complete Windows LF-to-CRLF checkout transformation.
    path = Path(__file__).parent / "fixtures/agent-home-controller-source60.py.txt"
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() not in {
        "999eedb6636a5eb8b84d84890dd75624e99c5a7ff6c0ec1f88cf091734ddff50",
        "b7db7c1aecee13264a727ad759ace588b818d48c0cc934887cc520e62a60c1b3",
    }:
        raise AssertionError("Frozen public legacy controller fixture changed")
    return raw.decode("utf-8").replace("\r\n", "\n")


def research_cli(path, *, previous=False):
    text = legacy_controller_source()
    parser = '''class CommandParser(argparse.ArgumentParser):
    def error(self, message):
        # A mistaken --api-key argument must not be copied to terminal logs.
        self.print_usage(sys.stderr)
        self.exit(2, "Invalid command arguments. Use --help for accepted commands and options.\\n")


'''
    options = '''    research = commands.add_parser("research", help="Set up optional web retrieval in your terminal or inspect redacted status")
    research.add_argument("operation", choices=("setup", "status", "skip", "revisit", "remove"))
    research.add_argument("--provider", help="Optional provider name from the research setup catalog")
'''
    dispatch = '''        if args.command == "research":
            from harness import home_entry, research_setup
            home, _config = load(args.home)
            arguments = ["--home", str(home), args.operation]
            if args.provider:
                arguments.extend(["--provider", args.provider])
            with home_entry.consumer(home):
                return research_setup.main(arguments)
'''
    if previous:
        text = text.replace(parser, "", 1).replace(options, "", 1).replace(dispatch, "", 1)
        text = text.replace('parser = CommandParser(description=__doc__, allow_abbrev=False)',
                            'parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)', 1)
    elif 'class CommandParser(' not in text:
        text = text.replace('def digest(file):', parser + 'def digest(file):', 1)
        text = text.replace('parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)',
                            'parser = CommandParser(description=__doc__, allow_abbrev=False)', 1)
        text = text.replace('    args = parser.parse_args(argv)', options + '    args = parser.parse_args(argv)', 1)
        text = text.replace('        if args.command == "palace":', dispatch + '        if args.command == "palace":', 1)
    path.write_text(text, encoding="utf-8")


def redacted_status():
    return {"schema": "agent-home-research-status/v1", "guidance_checked": "2026-10-25",
            "limits": "Local configuration only. No provider request, quota check or managed environment forwarding was tested.",
            "providers": {name: {"configured_state": "unconfigured", "state": "unconfigured", "credential_present": False,
                                 "credential_source": "none", "tested": False}
                          for name in ("searxng", "exa", "brave", "tavily", "ddg")}}


class ResearchStatusContractTests(unittest.TestCase):
    def test_complete_redacted_status_and_known_enum_values(self):
        value = redacted_status()
        update.validate_research_status(value)
        from harness import research_config
        self.assertEqual(set(value["providers"]), set(research_config.LEGACY_ORDER))
        expanded = copy.deepcopy(value)
        expanded["providers"] = {name: copy.deepcopy(value["providers"]["exa"]) for name in research_config.ORDER}
        update.validate_research_status(expanded)
        for name in ("serper", "jina", "serpapi"):
            candidate = copy.deepcopy(expanded)
            candidate["providers"][name]["api_key"] = "synthetic-private-value"
            with self.subTest(provider=name), self.assertRaises(ValueError):
                update.validate_research_status(candidate)
        for guidance in (research_config.GUIDANCE_CHECKED, "2026-10-26", "2028-02-29"):
            candidate = copy.deepcopy(value)
            candidate["guidance_checked"] = guidance
            update.validate_research_status(candidate)
        for field, choices in {"configured_state": ("enabled", "skipped", "unconfigured"),
                               "state": ("skipped", "unconfigured", "retention_hold", "endpoint_missing", "credential_missing", "ready"),
                               "credential_source": ("none", "environment", "home"), "credential_present": (True, False)}.items():
            for choice in choices:
                candidate = copy.deepcopy(value)
                candidate["providers"]["exa"][field] = choice
                update.validate_research_status(candidate)

    def test_malformed_unknown_and_secret_fields_are_refused(self):
        good = redacted_status()
        values = [None, [], {}, {**good, "providers": {}}, {**good, "guidance_checked": "tomorrow"},
                  {**good, "limits": "tested"}, {**good, "api_key": "synthetic-private-value"},
                  {key: value for key, value in good.items() if key != "limits"}]
        for guidance in ("2026-02-30", "2026-13-01", "20261025", "2026-1-01", "0000-01-01", None, 0):
            values.append({**good, "guidance_checked": guidance})
        for field, invalid in (("api_key", "synthetic-private-value"), ("endpoint", "http://synthetic.invalid"),
                               ("configured_state", "ready"), ("state", "successful"), ("state", "enabled"), ("state", {}),
                               ("credential_source", "synthetic-private-value"), ("credential_present", 1), ("tested", True), ("tested", 0)):
            candidate = copy.deepcopy(good)
            candidate["providers"]["exa"][field] = invalid
            values.append(candidate)
        for change in ("missing", "unknown", "malformed"):
            candidate = copy.deepcopy(good)
            if change == "missing":
                del candidate["providers"]["ddg"]
            elif change == "unknown":
                candidate["providers"]["unknown"] = candidate["providers"]["ddg"]
            else:
                candidate["providers"]["ddg"] = []
            values.append(candidate)
        for index, value in enumerate(values):
            with self.subTest(case=index), self.assertRaises(ValueError):
                update.validate_research_status(value)


class ControllerMigrationTests(UpdateFixture):
    def prepare_controller(self):
        case = self.case
        research_cli(case["source"] / "harness/home.py")
        # Fixture handler only. Native adoption must separately use the actual
        # complete research feature and unchanged normal managed Pi handler.
        (case["source"] / "harness/research_setup.py").write_text(
            'import json\ndef main(argv):\n print(' + repr(json.dumps(redacted_status())) + ')\n return 0\n')
        # Give the predecessor a distinct updater identity. Retained real old
        # verification semantics are exercised independently below.
        old_home = case["home"] / "runtime/harness/home.py"
        research_cli(old_home, previous=True)
        old = case["home"] / "runtime/harness/runtime_update.py"
        raw = old.read_text()
        raw = raw.replace('CONTROLLER_SCOPE = "controller-cli-v1"', 'CONTROLLER_SCOPE = "unavailable-predecessor"')
        old.write_text(raw)
        manifest = case["home"] / "runtime/runtime-manifest.json"
        value = state.read_json(manifest)
        for item in value["files"]:
            if item["path"] in {"harness/runtime_update.py", "harness/home.py"}:
                item["sha256"] = digest(case["home"] / "runtime" / item["path"])
        manifest.write_text(json.dumps(value))
        config = case["home"] / "home.json"
        value = state.read_json(config)
        value["runtime_manifest_sha256"] = digest(manifest)
        config.write_text(json.dumps(value))
        # Everyday's manifest reference also needs the exact changed manifest.
        workflow = case["home"] / "runtime" / update.WORKFLOW
        value = state.read_json(workflow)
        value["runtime_manifest_sha256"] = digest(manifest)
        workflow.write_text(json.dumps(value))
        case["before"] = state.active_snapshot(case["home"])[2]
        selected = state.plan(case["home"], case["source"])
        case["stage"] = state.stage(case["home"], case["source"], case["operation"], selected["plan_sha256"])
        case["target"] = Path(case["stage"]["receipt"]).parent
        plan = self.cli("controller-plan")
        case["plan"] = plan
        evidence = case["target"] / "review.txt"
        evidence.write_text("Reviewed isolated synthetic source fixture, not deployment acceptance")
        qualification = {"schema": update.QUALIFICATION, "scope": update.CONTROLLER_SCOPE,
                         "qualified": True, "execution_authorized": True,
                         "evidence": [{"path": str(evidence), "sha256": digest(evidence)}],
                         **{key: plan[key] for key in ("home", "operation", "stage_receipt_sha256", "candidate_sha256",
                                                      "controller", "active_sha256")}}
        case["qualification"] = case["target"] / "qualification.json"
        case["qualification"].write_text(json.dumps(qualification))
        return case

    def cli(self, command, *extra, expected=0, controller=None):
        case = self.case
        file = controller or case["source"] / "harness/runtime_update.py"
        result = subprocess.run([sys.executable, "-B", str(file), "--home", str(case["home"]), command,
                                 "--operation", case["operation"], *map(str, extra)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, expected, result.stderr)
        return json.loads(result.stdout if expected == 0 else result.stderr)

    def activate(self):
        case = self.case
        return self.cli("controller-apply", "--expected-plan", case["plan"]["plan_sha256"],
                        "--qualification", case["qualification"], "--qualification-sha256", digest(case["qualification"]),
                        "--execute-qualified-runtime")

    def test_scope_closure_and_ordinary_refusal(self):
        case = self.prepare_controller()
        self.assertEqual(case["plan"]["holds"], [])
        self.assertTrue(update.plan(case["home"], case["operation"])["holds"])
        self.assertNotEqual(case["plan"]["controller"]["old"], case["plan"]["controller"]["new"])
        refused = update.qualified
        with self.assertRaisesRegex(ValueError, "qualification contract"):
            refused(case["qualification"], digest(case["qualification"]), update.plan(case["home"], case["operation"]), True)
        # After the research merge the normal checkout can be the candidate.
        # Bind an actual distinct predecessor updater to prove closure refusal.
        with mock.patch.object(update, "__file__", str(case["home"] / "runtime/harness/runtime_update.py")):
            with self.assertRaisesRegex(ValueError, "closure"):
                update.controller_plan(case["home"], case["operation"])
        self.assertFalse(self.journal().exists())

    def test_exact_controller_qualification_bindings_are_required(self):
        case = self.prepare_controller()
        file = case["qualification"]
        original = json.loads(file.read_text())
        for field in ("active_sha256", "controller"):
            value = dict(original)
            value[field] = "unreviewed"
            file.write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, "bindings differ"):
                update.qualified(file, digest(file), case["plan"], True)
        file.write_text(json.dumps(original))
        self.assertFalse(self.journal().exists())

    @unittest.skipIf(sys.platform == "linux", "Unsupported platform only")
    def test_controller_apply_on_windows_refuses_before_activation(self):
        self.prepare_controller()
        result = self.cli("controller-apply", "--expected-plan", self.case["plan"]["plan_sha256"],
                          "--qualification", self.case["qualification"], "--qualification-sha256", digest(self.case["qualification"]),
                          "--execute-qualified-runtime", expected=1)
        self.assertIn("require Linux", result["error"])
        self.assertFalse(self.journal().exists())

    def test_exact_reviewed_ast_refuses_core_and_main_changes(self):
        case = self.prepare_controller()
        file = case["source"] / "harness/home.py"
        original = file.read_text()
        for changed, error in [(original.replace('SCHEMA = "agent-home/v1"', 'SCHEMA = "other"'), "constants"),
                               (original.replace('def load(home):', 'def load(home, escape=True):'), "constants"),
                               (original.replace('"research", help=', '"escape", help='), "definitions")]:
            file.write_text(changed)
            with mock.patch.object(update.state.bootstrap, "__file__", str(file)):
                with self.assertRaisesRegex(ValueError, error):
                    update.controller_bindings(case["home"], case["source"])
        file.write_text(original)

    def test_current_board_controller_is_outside_legacy_cli_scope(self):
        case = self.prepare_controller()
        file = case["source"] / "harness/home.py"
        original = file.read_bytes()
        try:
            file.write_bytes((Path(__file__).resolve().parents[1] / "harness/home.py").read_bytes())
            with self.assertRaisesRegex(ValueError, "Controller CLI definitions"):
                update.controller_bindings(case["home"], case["source"])
        finally:
            file.write_bytes(original)

    @unittest.skipUnless(sys.platform == "linux", "Existing Linux EX/runtime exchange")
    def test_actual_migration_old_verify_refusal_new_verify_and_exact_rollback(self):
        case = self.prepare_controller()
        activated = self.activate()
        self.assertEqual(activated["status"], "controller_pending_consumer_acceptance")
        self.assertEqual(hashlib.sha256(OLD_VERIFY.encode()).hexdigest(), OLD_VERIFY_SHA256)
        # Prove that no new helper can supply the old verifier's rejection.
        for name, expected in OLD_HELPERS.items():
            raw = inspect.getsource(getattr(update, name)).rstrip() + "\n"
            self.assertEqual(hashlib.sha256(raw.encode()).hexdigest(), expected)
        for name, expected in OLD_FIXED_MODULES.items():
            # Git checkout CRLF is not a code change. Stage separately requires
            # exact before/candidate byte identity for these fixed modules.
            raw = (Path(__file__).resolve().parents[1] / name).read_text().encode()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)
        namespace = dict(vars(update))
        exec(compile(OLD_VERIFY, "retained-724818a-verify.py", "exec"), namespace)
        before = self.journal().read_bytes()
        for status in ("controller_pending_consumer_acceptance", "controller_verification_failed"):
            value = json.loads(before)
            value["status"] = status
            self.journal().write_text(json.dumps(value))
            retained = self.journal().read_bytes()
            try:
                namespace["verify"](case["home"], case["operation"], digest(self.journal()))
            except ValueError as error:
                self.assertEqual(str(error), "Only a coherent activated generation can enter consumer verification")
                trace = error.__traceback__
                frames = []
                while trace:
                    frames.append((trace.tb_frame.f_code.co_filename, trace.tb_lineno))
                    trace = trace.tb_next
                self.assertIn(("retained-724818a-verify.py", OLD_VERIFY[:OLD_VERIFY.index(
                    '        require(value["status"]')].count("\n") + 1), frames)
            else:
                self.fail("Retained old verifier accepted a controller migration")
            self.assertEqual(self.journal().read_bytes(), retained)
        self.journal().write_bytes(before)
        self.cli("verify", "--expected-journal", digest(self.journal()), expected=1)
        retained = case["target"] / "candidate/runtime/harness/runtime_update.py"
        accepted = self.cli("controller-verify", "--expected-journal", digest(self.journal()), controller=retained)
        self.assertEqual(accepted["status"], "accepted")
        self.assertIn("controller_consumer", accepted)
        rolled = self.cli("rollback", "--expected-journal", digest(self.journal()), controller=retained)
        self.assertEqual(rolled["status"], "rolled_back")
        self.assertEqual(state.active_snapshot(case["home"])[2], case["before"])

    @unittest.skipUnless(sys.platform == "linux", "Existing Linux EX/runtime exchange")
    def test_controller_faults_recover_with_retained_source_and_preserve_data(self):
        for fault in ("pending-published", "old-runtime-moved", "new-runtime-installed", "binding:home.json", "coherent-activation-committed"):
            with self.subTest(fault=fault):
                if self.case.get("stage"):
                    self.case = self.new_case("fault-" + fault.replace(":", "-"))
                case = self.prepare_controller()
                source = case["source"]
                script = ("import sys;sys.path.insert(0," + repr(str(source)) + ");from harness import runtime_update as u;"
                          "u._fault=lambda step: (_ for _ in ()).throw(ValueError('injected')) if step==" + repr(fault) + " else None;"
                          "raise SystemExit(u.main(" + repr(["--home", str(case["home"]), "controller-apply", "--operation", case["operation"],
                          "--expected-plan", case["plan"]["plan_sha256"], "--qualification", str(case["qualification"]),
                          "--qualification-sha256", digest(case["qualification"]), "--execute-qualified-runtime"]) + "))")
                result = subprocess.run([sys.executable, "-B", "-c", script], capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertTrue((case["home"] / update.PENDING).exists())
                retained = case["target"] / "candidate/runtime/harness/runtime_update.py"
                recovered = self.cli("recover", "--expected-journal", digest(self.journal()), controller=retained)
                self.assertEqual(recovered["status"], "recovered_predecessor")
                self.assertEqual(state.active_snapshot(case["home"])[2], case["before"])


if __name__ == "__main__":
    unittest.main()

