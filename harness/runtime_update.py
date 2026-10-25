"""Explicit compatible runtime exchange, recovery and generation rollback.

Apply requires an exact staged-source qualification contract and explicit
permission to execute that candidate. It ends coherently activated but pending
normal consumer acceptance. An incomplete transaction retains the existing
pending sentinel and blocks normal entry. Personal files and packages are never
re-scaffolded. This module uses HOME/runtime and the existing operation history.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

try:
    from . import maintenance as state, home_entry
except ImportError:
    import maintenance as state
    import home_entry


SCHEMA = "agent-home-runtime-update/v1"
QUALIFICATION = "agent-home-runtime-qualification/v1"
CONTROLLER_SCOPE = "controller-cli-v1"
# Reviewed research CLI definitions, from source commit 98076e3. Other AST
# nodes must match the installed controller, including imports and constants.
CONTROLLER_MAIN = "5e33d2aa155aa9e5a5a0a763429e0da1958d2c3dee2dffc39af108ca77001c90"
PREVIOUS_MAIN = "5cf355a5d36ee806ffb5e4b6f2ba2d815a422d5e7eb3819c07ab774380abcfc0"
CONTROLLER_PARSER = "b546b0054638ce3251bd18c558b59220df987e13a5f8858705287f73fc6f5175"
PENDING = "state/updates/pending-activation.json"
WORKFLOW = "adapters/pi/project-workflow/everyday-runtime.json"
COMMAND_TIMEOUT = 90
# These entry/configuration protocols are intentionally outside the first
# compatible migration slice. Ordinary adapters and execution code may change.
FIXED_SOURCE = ("harness/home.py", "harness/home_entry.py", "harness/home_lifecycle.py",
                "harness/maintenance.py", "harness/runtime_update.py",
                "adapters/pi/intake/framework_binding.py")
CONTROLS = ("home-lifecycle.py", "agent-home.py", "agent/settings.json", "agent/mcp.json",
            "agent/models.json", "bin/mempalace", "bin/harness-agent", "bin/harness-agent.cmd")


class UpdateError(ValueError):
    pass


def require(value, message):
    if not value:
        raise UpdateError(message)


def _fault(_step):
    """Tests inject interruption here; no product CLI fault switch exists."""


def fsync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def raw_json(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_new(path, value):
    with path.open("xb") as stream:
        stream.write(raw_json(value))
        stream.flush()
        os.fsync(stream.fileno())
    fsync_directory(path.parent)


def replace_bytes(path, raw, expected, *, backup_dir=None):
    """Expected-old-hash replacement with an immutable timestamp predecessor."""
    require(path.is_file() and not path.is_symlink() and state.digest(path) == expected,
            "Concurrent binding drift: " + str(path))
    old = path.read_bytes()
    if backup_dir is not None:
        backup_dir.mkdir(parents=True, exist_ok=True)
    previous = (backup_dir or path.parent) / (path.name + ".previous-" + state.stamp())
    with previous.open("xb") as stream:
        stream.write(old)
        stream.flush()
        os.fsync(stream.fileno())
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".candidate", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        require(state.digest(path) == expected, "Concurrent binding drift before replacement")
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        candidate = Path(temporary)
        if candidate.exists():
            candidate.unlink()
    return hashlib.sha256(raw).hexdigest()


def inventory(root):
    require(root.is_dir() and not root.is_symlink(), "Expected an actual runtime directory")
    result = {}
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.relative_to(root).parts:
            continue
        require(not path.is_symlink(), "Runtime tree symlink is unsupported")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = state.digest(path)
    return result


def controls(home):
    result = {}
    for relative in CONTROLS:
        file = state.inside(home, relative)
        if file.exists():
            require(file.is_file(), "Control path is not a file")
            result[relative] = state.digest(file)
    return result


def integrated(home):
    home, config = home_entry.selected_home(home)
    pin = config.get("lifecycle_guard_sha256")
    require(pin and config.get("lifecycle_launcher_sha256"), "Explicit stable lifecycle baseline integration is required")
    require(state.digest(state.inside(home, "home-lifecycle.py", exists=True)) == pin
            and state.digest(state.inside(home, "agent-home.py", exists=True)) == config["lifecycle_launcher_sha256"],
            "Stable entry baseline drift")
    return home, config


@contextmanager
def exclusive(home, *, recover=False):
    require(sys.platform == "linux", "Runtime activation and rollback require Linux")
    home, config = integrated(home)
    guard = home_entry._load_guard(home, config["lifecycle_guard_sha256"])
    with guard.lease(home, expected_sha256=config["lifecycle_guard_sha256"], mode="exclusive", recover=recover):
        yield home


def stopped(home):
    # A normal stopped hub removes its exact owner receipt. Stale/unknown
    # ownership must be resolved by the existing explicit stop route first.
    owner = state.inside(home, "state/mempalace-hub/owner.json")
    require(not owner.exists(), "Run the existing explicit owned palace stop before runtime maintenance")


def operation(home, identifier):
    home, target, receipt = state.selected_operation(home, identifier)
    return home, target, receipt, target / "runtime-update.json"


def executing_controller(candidate):
    closure = {"harness/runtime_update.py": Path(__file__), "harness/maintenance.py": Path(state.__file__),
               "harness/home_entry.py": Path(home_entry.__file__), "harness/home.py": Path(state.bootstrap.__file__)}
    for relative, loaded in closure.items():
        require(not loaded.is_symlink() and state.digest(loaded) == state.digest(candidate / relative),
                "Execute the exact staged controller closure: " + relative)
    return {name: state.digest(path) for name, path in closure.items()}


def controller_bindings(home, candidate):
    """Narrow reviewed CLI migration, with exact executing recovery closure."""
    def nodes(path):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        # Python 3.12 adds empty type_params to function/class AST nodes.
        # Remove only that empty field to retain the reviewed 3.9+ encoding.
        for node in ast.walk(tree):
            if hasattr(node, "type_params"):
                require(not node.type_params, "Generic controller definitions are outside controller-cli-v1")
                del node.type_params
        return tree.body

    def node_dump(node):
        # Python 3.13 otherwise omits empty fields that older dumps include.
        options = {"show_empty": True} if sys.version_info >= (3, 13) else {}
        return ast.dump(node, include_attributes=False, **options)

    def node_hash(node):
        return hashlib.sha256(node_dump(node).encode()).hexdigest()

    before = nodes(home / "runtime/harness/home.py")
    after = nodes(candidate / "harness/home.py")
    old_main = [n for n in before if isinstance(n, ast.FunctionDef) and n.name == "main"]
    new_main = [n for n in after if isinstance(n, ast.FunctionDef) and n.name == "main"]
    parser = [n for n in after if isinstance(n, ast.ClassDef) and n.name == "CommandParser"]
    require(len(old_main) == len(new_main) == len(parser) == 1
            and node_hash(old_main[0]) == PREVIOUS_MAIN and node_hash(new_main[0]) == CONTROLLER_MAIN
            and node_hash(parser[0]) == CONTROLLER_PARSER, "Controller CLI definitions are outside controller-cli-v1")
    old_rest = [node_dump(n) for n in before if n is not old_main[0]]
    new_rest = [node_dump(n) for n in after if n is not new_main[0] and n is not parser[0]]
    require(old_rest == new_rest, "Controller core definitions/constants/imports changed")
    closure = executing_controller(candidate)
    return {"scope": CONTROLLER_SCOPE,
            "old": {name: state.digest(home / "runtime" / name) for name in FIXED_SOURCE},
            "new": {name: state.digest(candidate / name) for name in FIXED_SOURCE},
            "executing_closure": closure,
            "python": str(Path(sys.executable).resolve()), "python_sha256": state.digest(Path(sys.executable).resolve()),
            "recovery_controller": str(candidate / "harness/runtime_update.py")}


def plan(home, identifier):
    return _plan(home, identifier)


def controller_plan(home, identifier):
    return _plan(home, identifier, controller=True)


def _plan(home, identifier, *, controller=False):
    home, target, stage, journal = operation(home, identifier)
    home, config = integrated(home)
    require(target.stat().st_dev == home.stat().st_dev, "Runtime exchange requires the operation and home on one filesystem")
    require(not journal.exists() and not journal.is_symlink(), "Update operation replay is not permitted")
    checked = state.verify_stage(home, identifier)
    require(checked["valid_staged_source"], "Staged source is invalid: " + "; ".join(checked["errors"]))
    request = state.read_json(target / "request.json")
    active = request["active"]
    require(not request["package_changes"] and not request.get("introduced_dependency_imports"),
            "Package/dependency changes require separate qualification")
    candidate = target / "candidate/runtime"
    holds = []
    for relative in FIXED_SOURCE:
        if controller and relative in {"harness/home.py", "harness/runtime_update.py"}:
            continue
        if stage["candidate_files"].get(relative) != active["runtime_files"].get(relative):
            holds.append("Entry/configuration protocol migration is unsupported: " + relative)
    templates = "harness/templates/agent-home/"
    for relative, previous in active["runtime_files"].items():
        if relative.startswith(templates) and stage["candidate_files"].get(relative) != previous:
            holds.append("Personal template migration needs separate review: " + relative)
    # Source packaging may retain gitignore.template as data. It is never
    # rendered into or adopted over the selected home's personal files here.
    for relative in stage["candidate_files"]:
        if relative.startswith(templates) and relative not in active["runtime_files"] \
                and relative != templates + "gitignore.template":
            holds.append("New template adoption is outside this compatible update: " + relative)
    result = {"schema": SCHEMA, "home": str(home), "operation": identifier,
              "stage_receipt_sha256": state.digest(target / "admission.json"),
              "candidate_sha256": stage["candidate_sha256"], "active_sha256": active["sha256"],
              "candidate_files": inventory(candidate), "controls": controls(home),
              "profile": config["profile"], "holds": holds, "personal_template_adoption": "none",
              "candidate_execution": "Requires exact explicit qualification contract and execution acknowledgement",
              "apply_result": "activated_pending_consumer_acceptance; not accepted",
              "source": request["source"], "package_changes": [], "introduced_dependency_imports": []}
    if controller:
        result["controller"] = controller_bindings(home, candidate)
        result["apply_result"] = "controller_pending_consumer_acceptance; not accepted"
    result["plan_sha256"] = state.canonical_hash(result)
    return result


def qualified(file, expected, selected, execute):
    require(execute is True, "Explicit execute-qualified-runtime acknowledgement is required")
    file = Path(file)
    require(file.is_absolute() and file.is_file() and not file.is_symlink() and state.digest(file) == expected,
            "Qualification contract drift or invalid path")
    value = state.read_json(file)
    require(value.get("schema") == QUALIFICATION and value.get("scope") == (CONTROLLER_SCOPE if "controller" in selected else "compatible-runtime-only")
            and value.get("execution_authorized") is True and value.get("qualified") is True,
            "A reviewed explicit runtime qualification contract is required")
    for key in ("home", "operation", "stage_receipt_sha256", "candidate_sha256"):
        require(value.get(key) == selected[key], "Qualification source/target binding differs: " + key)
    if "controller" in selected:
        require(value.get("controller") == selected["controller"] and value.get("active_sha256") == selected["active_sha256"],
                "Controller qualification old/new/executing bindings differ")
    evidence = value.get("evidence")
    require(isinstance(evidence, list) and evidence, "Qualification needs retained reviewed evidence")
    for item in evidence:
        path = Path(item["path"])
        require(path.is_absolute() and path.is_file() and not path.is_symlink()
                and state.digest(path) == item["sha256"], "Qualification evidence drift")
    return {"path": str(file), "sha256": expected, "contract": value,
            "authority": "Explicit caller-reviewed source qualification; not automatic all-session authority"}


def save_journal(path, value, event):
    value["events"].append({"event": event, "time": state.stamp()})
    if path.exists():
        replace_bytes(path, raw_json(value), state.digest(path))
    else:
        write_new(path, value)


def pending_new(home, identifier, journal):
    path = state.inside(home, PENDING)
    value = {"schema": SCHEMA, "home": str(home), "operation": identifier,
             "journal": str(journal), "created": state.stamp()}
    write_new(path, value)
    return state.digest(path)


def pending_check(home, identifier, journal):
    path = state.inside(home, PENDING, exists=True)
    value = state.read_json(path)
    require(value.get("schema") == SCHEMA and value.get("home") == str(home)
            and value.get("operation") == identifier and value.get("journal") == str(journal),
            "Pending transaction belongs to a different operation")
    return path


def pending_retire(home, identifier, journal, target):
    pending = pending_check(home, identifier, journal)
    archive = target / ("pending-retired-" + state.stamp() + ".json")
    # Move the exact sentinel into this operation's retained history. A
    # completed coherent transaction is not an incomplete activation window.
    os.replace(pending, archive)
    fsync_directory(pending.parent)
    fsync_directory(target)


def run_bound(argv, *, home, target, label):
    """Run explicit qualified helper/normal consumer, retaining complete output."""
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "CUDA_VISIBLE_DEVICES": ""}
    timed_out = False
    try:
        # Every command here is explicit and noninteractive. An inherited
        # control pipe makes native Pi print mode wait for EOF before dispatch.
        result = subprocess.run([str(arg) for arg in argv], cwd=home, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=COMMAND_TIMEOUT, check=False)
        stdout, stderr, code = result.stdout, result.stderr, result.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr, code = error.stdout or b"", error.stderr or b"", None
        timed_out = True
    record = {"argv": [str(arg) for arg in argv], "cwd": str(home), "code": code,
              "stdin": "DEVNULL", "timed_out": timed_out, "timeout_seconds": COMMAND_TIMEOUT,
              "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
              "stderr_sha256": hashlib.sha256(stderr).hexdigest()}
    prefix = target / (label + "-" + state.stamp())
    Path(str(prefix) + ".stdout").write_bytes(stdout)
    Path(str(prefix) + ".stderr").write_bytes(stderr)
    write_new(Path(str(prefix) + ".json"), record)
    require(not timed_out, "Qualified command timed out: " + label + "; partial stdout/stderr retained " + str(prefix)
            + "; descendant settlement is not established")
    require(code == 0, "Qualified command failed: " + label + "; retained " + str(prefix))
    return stdout.decode("utf-8"), record


def publish(home, target, journal, value, relative, raw):
    path = state.inside(home, relative, exists=True)
    expected = state.digest(path)
    after = hashlib.sha256(raw).hexdigest()
    allowed = value["allowed_binding_hashes"].setdefault(relative, [])
    for item in (expected, after):
        if item not in allowed:
            allowed.append(item)
    save_journal(journal, value, "before-binding:" + relative)
    replace_bytes(path, raw, expected, backup_dir=target / "activation/binding-history")
    save_journal(journal, value, "after-binding:" + relative)
    _fault("binding:" + relative)


def apply(home, identifier, expected_plan, qualification, qualification_sha256, *, execute_qualified_runtime=False):
    return _apply(home, identifier, expected_plan, qualification, qualification_sha256,
                  execute_qualified_runtime=execute_qualified_runtime)


def controller_apply(home, identifier, expected_plan, qualification, qualification_sha256, *, execute_qualified_runtime=False):
    return _apply(home, identifier, expected_plan, qualification, qualification_sha256,
                  execute_qualified_runtime=execute_qualified_runtime, controller=True)


def _apply(home, identifier, expected_plan, qualification, qualification_sha256, *, execute_qualified_runtime=False, controller=False):
    selected = _plan(home, identifier, controller=controller)
    require(selected["plan_sha256"] == expected_plan, "Reviewed update plan drift")
    require(not selected["holds"], "; ".join(selected["holds"]))
    contract = qualified(qualification, qualification_sha256, selected, execute_qualified_runtime)
    home, target, stage, journal = operation(home, identifier)
    with exclusive(home), state.operation_lock(home, identifier):
        stopped(home)
        require(_plan(home, identifier, controller=controller)["plan_sha256"] == expected_plan, "Active/staged state changed before activation")
        qualified(qualification, qualification_sha256, selected, execute_qualified_runtime)
        require(shutil.disk_usage(home).free >= sum(p.stat().st_size for p in (target / "candidate/runtime").rglob("*")
                                                   if p.is_file()) * 2 + 8 * 1024 * 1024,
                "Insufficient selected-home activation space")
        activation = target / "activation"
        require(not activation.exists(), "Activation directory replay is not permitted")
        activation.mkdir(mode=0o700)
        original = activation / "original"
        original.mkdir()
        _home, config, active = state.active_snapshot(home)
        before_runtime = inventory(home / "runtime")
        originals = {}
        for relative in ("home.json", "state/framework-binding.json", "bin/mempalace", "home-lifecycle.py", "agent-home.py"):
            file = state.inside(home, relative)
            if file.exists():
                expected = state.digest(file)
                state.copy_exact(file, original / relative, expected)
                originals[relative] = expected
        prepared = activation / "prepared-runtime"
        shutil.copytree(target / "candidate/runtime", prepared)
        require(inventory(prepared) == selected["candidate_files"]
                and inventory(target / "candidate/runtime") == selected["candidate_files"], "Candidate drift during preparation")
        workflow = prepared / WORKFLOW
        binding = state.read_json(workflow)
        binding["runtime"] = str(home / "runtime")
        with workflow.open("wb") as stream:
            stream.write(raw_json(binding))
            stream.flush()
            os.fsync(stream.fileno())
        after_runtime = inventory(prepared)
        value = {"schema": SCHEMA, "home": str(home), "operation": identifier, "status": "activation_incomplete",
                 "stage_receipt_sha256": selected["stage_receipt_sha256"], "plan_sha256": expected_plan,
                 "qualification": contract, "before_active_sha256": active["sha256"], "profile": config["profile"],
                 "before_runtime": before_runtime, "after_runtime": after_runtime, "originals": originals,
                 "controls": selected["controls"], "allowed_binding_hashes": {key: [item] for key, item in originals.items()},
                 "events": [], "candidate_runtime_acceptance": "not_run", "personal_template_adoption": "none"}
        if controller:
            value["controller"] = selected["controller"]
        save_journal(journal, value, "prepared")
        pending_new(home, identifier, journal)
        save_journal(journal, value, "pending-published")
        _fault("pending-published")
        # Both directories are exact checked paths within this selected home.
        # The original staged candidate remains intact and is never exchanged.
        old_runtime = activation / "predecessor-runtime"
        require(not old_runtime.exists(), "Predecessor destination is occupied")
        os.replace(home / "runtime", old_runtime)
        fsync_directory(home)
        fsync_directory(activation)
        save_journal(journal, value, "old-runtime-moved")
        _fault("old-runtime-moved")
        os.replace(prepared, home / "runtime")
        fsync_directory(home)
        fsync_directory(activation)
        save_journal(journal, value, "new-runtime-installed")
        _fault("new-runtime-installed")
        new_config = dict(config)
        new_config["runtime_manifest_sha256"] = state.digest(home / "runtime/runtime-manifest.json")
        new_config["native_acceptance"] = "not_run"
        publish(home, target, journal, value, "home.json", raw_json(new_config))
        if config.get("framework_binding_sha256"):
            old_framework = state.read_json(original / "state/framework-binding.json")
            output = activation / "framework-binding-generated.json"
            helper = home / "runtime/adapters/pi/intake/framework_binding.py"
            text, record = run_bound([old_framework["python"], "-B", helper, "--output", output],
                                     home=home, target=activation, label="new-framework-binding")
            observed = json.loads(text)
            require(observed.get("ok") is True and observed.get("sha256") == state.digest(output), "New Framework binding failed")
            bound = state.read_json(output)
            expected_helper = home / "runtime/adapters/pi/intake/decision-138.py"
            require(bound.get("helper") == str(expected_helper) and bound.get("helper_sha256") == state.digest(expected_helper),
                    "Framework descriptor did not observe the actual new active helper")
            for key in ("schema", "framework_version", "python", "python_sha256", "files"):
                require(bound.get(key) == old_framework.get(key), "Framework package/environment migration is unsupported")
            publish(home, target, journal, value, "state/framework-binding.json", output.read_bytes())
            new_config["framework_binding_sha256"] = state.digest(output)
            value["framework_command"] = record
        if config.get("memory_runtime"):
            memory = config["memory_runtime"]
            text, record = run_bound([memory["python"], "-B", home / "runtime/harness/memory_runtime.py", "--home", home, "--bind"],
                                     home=home, target=activation, label="new-memory-binding")
            observed = json.loads(text)
            require(observed == memory, "Memory environment/cache migration is unsupported")
            new_config["memory_runtime"] = observed
            value["memory_command"] = record
        publish(home, target, journal, value, "home.json", raw_json(new_config))
        require(inventory(home / "runtime") == after_runtime and controls(home) == value["controls"], "Final active source/control drift")
        value["after_active_sha256"] = state.active_snapshot(home)[2]["sha256"]
        value["status"] = "controller_pending_consumer_acceptance" if controller else "activated_pending_consumer_acceptance"
        save_journal(journal, value, "coherent-activation-committed")
        _fault("coherent-activation-committed")
        pending_retire(home, identifier, journal, target)
    return {**value, "journal": str(journal), "journal_sha256": state.digest(journal),
            "accepted": False, "next": "Run verify through the actual stable managed entry"}


def load_update(home, identifier, expected=None):
    home, target, stage, journal = operation(home, identifier)
    value = state.read_json(journal)
    require(value.get("schema") == SCHEMA and value.get("home") == str(home)
            and value.get("operation") == identifier and value.get("stage_receipt_sha256") == state.digest(target / "admission.json"),
            "Update/stage identity differs")
    if expected is not None:
        require(state.digest(journal) == expected, "Reviewed transaction journal drift")
    return home, target, stage, journal, value


def check_predecessors(target, value):
    activation = state.inside(target, "activation", exists=True)
    previous = state.inside(activation, "predecessor-runtime", exists=True)
    require(inventory(previous) == value["before_runtime"], "Predecessor runtime drift")
    original = state.inside(activation, "original", exists=True)
    for relative, expected in value["originals"].items():
        require(state.digest(state.inside(original, relative, exists=True)) == expected, "Retained binding predecessor drift")


def restore_predecessor(home, target, journal, value):
    """Idempotent exact predecessor restoration while pending and EX remain held."""
    require(controls(home) == value["controls"], "Personal/control changes need review; no files overwritten")
    activation = state.inside(target, "activation", exists=True)
    previous, current = activation / "predecessor-runtime", home / "runtime"
    if previous.exists():
        require(inventory(previous) == value["before_runtime"], "Predecessor runtime drift")
        if current.exists():
            observed = inventory(current)
            require(observed in (value["before_runtime"], value["after_runtime"]), "Unknown active runtime drift; preserve for review")
            saved = activation / ("retired-runtime-" + state.stamp())
            os.replace(current, saved)
            fsync_directory(home)
            fsync_directory(activation)
            save_journal(journal, value, "restore-current-retired")
            _fault("restore-current-retired")
        os.replace(previous, current)
        fsync_directory(home)
        fsync_directory(activation)
        save_journal(journal, value, "restore-runtime-installed")
        _fault("restore-runtime-installed")
    else:
        require(current.exists() and inventory(current) == value["before_runtime"],
                "Exact predecessor is unavailable; no unknown directory moved")
    original = state.inside(activation, "original", exists=True)
    for relative in ("home.json", "state/framework-binding.json"):
        if relative not in value["originals"]:
            continue
        saved = state.inside(original, relative, exists=True)
        require(state.digest(saved) == value["originals"][relative], "Retained binding predecessor drift")
        actual = state.inside(home, relative, exists=True)
        expected = state.digest(actual)
        require(expected in value["allowed_binding_hashes"][relative], "Unknown current binding drift; no overwrite")
        replace_bytes(actual, saved.read_bytes(), expected, backup_dir=activation / "binding-history")
        save_journal(journal, value, "restore-binding:" + relative)
        _fault("restore-binding:" + relative)
    require(inventory(current) == value["before_runtime"]
            and state.active_snapshot(home)[2]["sha256"] == value["before_active_sha256"],
            "Restored predecessor does not match its complete retained active identity")


def managed_doctor(home, target):
    # Launch a fresh interpreter through the actual stable entry. Do not call
    # the controller's imported bootstrap module and label that new-runtime QA.
    config = state.read_json(home / "home.json")
    workflow = state.read_json(home / "runtime" / WORKFLOW)
    text, record = run_bound([workflow["python"], "-B", home / "agent-home.py", "doctor"],
                            home=home, target=target, label="managed-doctor")
    result = json.loads(text)
    require(result.get("failures") == [], "Actual managed doctor rejected the current runtime")
    require(state.digest(home / "runtime/runtime-manifest.json") == config["runtime_manifest_sha256"], "Doctor target manifest drift")
    return {"command": record, "result": result, "runtime_manifest_sha256": config["runtime_manifest_sha256"]}


def recover(home, identifier, expected_journal):
    home, target, _stage, journal, value = load_update(home, identifier, expected_journal)
    with exclusive(home, recover=True), state.operation_lock(home, identifier):
        require(state.digest(journal) == expected_journal, "Journal changed before recovery admission")
        pending_check(home, identifier, journal)
        stopped(home)
        require(value["status"] in {"activation_incomplete", "rollback_incomplete", "activated_pending_consumer_acceptance",
                                    "recovered_pending_consumer_acceptance", "rolled_back_pending_consumer_acceptance",
                                    "controller_pending_consumer_acceptance", "controller_verification_failed"},
                "Operation is not an incomplete recoverable transaction")
        restore_predecessor(home, target, journal, value)
        value["status"] = "recovered_pending_consumer_acceptance"
        save_journal(journal, value, "predecessor-restored-coherently")
        _fault("predecessor-restored-coherently")
        pending_retire(home, identifier, journal, target)
    # This is an actual old generation consumer check, not candidate acceptance.
    with home_entry.consumer(home), state.operation_lock(home, identifier):
        value["recovered_doctor"] = managed_doctor(home, target)
        value["status"] = "recovered_predecessor"
        value["restored_generation_acceptance"] = "actual managed doctor; Pi acceptance remains its prior retained qualification"
        save_journal(journal, value, "recovered-managed-doctor-passed")
    return {**value, "journal_sha256": state.digest(journal), "predecessor_restored": True}


def rollback(home, identifier, expected_journal):
    home, target, _stage, journal, value = load_update(home, identifier, expected_journal)
    with exclusive(home), state.operation_lock(home, identifier):
        require(state.digest(journal) == expected_journal, "Journal changed before rollback admission")
        stopped(home)
        require(value["status"] in {"activated_pending_consumer_acceptance", "consumer_verification_failed", "accepted",
                                    "controller_pending_consumer_acceptance", "controller_verification_failed"},
                "Operation is not an active generation eligible for rollback")
        require(state.active_snapshot(home)[2]["sha256"] == value["after_active_sha256"], "Active generation drift; rollback refused")
        require(controls(home) == value["controls"], "Control drift; rollback refused without changing user files")
        check_predecessors(target, value)
        value["status"] = "rollback_incomplete"
        save_journal(journal, value, "rollback-prepared")
        pending_new(home, identifier, journal)
        save_journal(journal, value, "rollback-pending-published")
        _fault("rollback-pending-published")
        restore_predecessor(home, target, journal, value)
        value["status"] = "rolled_back_pending_consumer_acceptance"
        save_journal(journal, value, "rollback-restored-coherently")
        _fault("rollback-restored-coherently")
        pending_retire(home, identifier, journal, target)
    with home_entry.consumer(home), state.operation_lock(home, identifier):
        value["rollback_doctor"] = managed_doctor(home, target)
        value["status"] = "rolled_back"
        value["rollback_acceptance"] = "exact predecessor identity and actual managed doctor; prior Pi qualification retained"
        save_journal(journal, value, "rollback-managed-doctor-passed")
    return {**value, "journal_sha256": state.digest(journal), "new_user_data_preserved": True}


def verify(home, identifier, expected_journal):
    return _verify(home, identifier, expected_journal)


def controller_verify(home, identifier, expected_journal):
    return _verify(home, identifier, expected_journal, controller=True)


def _verify(home, identifier, expected_journal, *, controller=False):
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
                require(observed.get("schema") == "agent-home-research-status/v1"
                        and isinstance(observed.get("providers"), dict), "Actual research status response is invalid")
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
    return {**value, "journal_sha256": state.digest(journal), "accepted": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--home", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "apply", "verify", "recover", "rollback", "controller-plan", "controller-apply", "controller-verify"):
        command = commands.add_parser(name, allow_abbrev=False)
        command.add_argument("--operation", required=True)
        if name in {"apply", "controller-apply"}:
            command.add_argument("--expected-plan", required=True)
            command.add_argument("--qualification", required=True, type=Path)
            command.add_argument("--qualification-sha256", required=True)
            command.add_argument("--execute-qualified-runtime", action="store_true")
        elif name not in {"plan", "controller-plan"}:
            command.add_argument("--expected-journal", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command in {"plan", "controller-plan"}:
            result = globals()[args.command.replace("-", "_")](args.home, args.operation)
        elif args.command in {"apply", "controller-apply"}:
            result = globals()[args.command.replace("-", "_")](args.home, args.operation, args.expected_plan, args.qualification, args.qualification_sha256,
                           execute_qualified_runtime=args.execute_qualified_runtime)
        else:
            result = globals()[args.command.replace("-", "_")](args.home, args.operation, args.expected_journal)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        result = {"schema": SCHEMA, "status": "refused_or_incomplete", "error": str(error),
                  "instruction": "An existing pending journal blocks normal entry; inspect and explicitly recover before reuse"}
        print(json.dumps(result), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
