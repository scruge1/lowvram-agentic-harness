"""Inspect and stage an exact runtime source update without activating it.

Existing home/runtime paths and memory/Framework bindings need a coordinated
activation operation. This module never replaces that active tree, runs a
package installer, changes agent context or restarts a service.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

try:
    from . import home as bootstrap
except ImportError:
    import home as bootstrap


SCHEMA = "agent-home-runtime-stage/v1"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,127}\Z")
PRESERVED = ["agent", "context", "memory", "projects", "envs", "packages", "cache",
             "state/validated-memory.jsonl", "state/projects", "state/hermes"]


class MaintenanceError(ValueError):
    """An update precondition or retained source binding failed."""


def require(value, message):
    if not value:
        raise MaintenanceError(message)


def digest(file):
    result = hashlib.sha256()
    with Path(file).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def canonical_hash(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stamp():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def read_json(path):
    require(path.is_file() and not path.is_symlink(), "Expected a regular JSON file: " + str(path))
    return json.loads(path.read_text(encoding="utf-8"))


def relative_path(value):
    require(isinstance(value, str) and value and "\\" not in value, "Use a nonempty POSIX relative path")
    path = Path(value)
    require(not path.is_absolute() and ".." not in path.parts and "." not in path.parts,
            "Artifact path escaped its selected tree")
    return path


def inside(root, relative, *, exists=False):
    require(not root.is_symlink(), "Selected source/state tree symlink is unsupported: " + str(root))
    path = root / relative_path(relative)
    require(path.resolve(strict=exists).is_relative_to(root.resolve(strict=True)), "Artifact escaped its selected tree")
    for parent in (path, *path.parents):
        if parent == root:
            break
        require(not parent.is_symlink(), "Source/state symlinks are not supported: " + str(parent))
    return path


def pin_literals(file):
    tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
    values = [node.value for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(target, ast.Name) and target.id == "PINS" for target in node.targets)]
    require(len(values) == 1, "Candidate needs one literal PINS declaration")
    try:
        result = ast.literal_eval(values[0])
    except (ValueError, TypeError) as error:
        raise MaintenanceError("PINS must be data; candidate source was not executed") from error
    require(isinstance(result, dict) and result and all(isinstance(k, str) and isinstance(v, str)
                                                      for k, v in result.items()), "Invalid PINS declaration")
    return result


def descriptor_artifacts(home, config, records, artifacts):
    """Check existing descriptor identities without importing their packages."""
    bound = {}

    def check(path, expected, label):
        path = Path(path)
        require(path.is_absolute() and path.is_file() and digest(path) == expected,
                label + " binding artifact drift")
        bound[str(path)] = expected

    if config.get("framework_binding_sha256"):
        file = inside(home, "state/framework-binding.json", exists=True)
        require(digest(file) == config["framework_binding_sha256"], "Framework descriptor drift")
        value = read_json(file)
        require(value.get("schema") == "pi-framework-binding/v1"
                and value.get("framework_version") == "1.21.0", "Framework descriptor schema/version differs")
        helper = home / "runtime/adapters/pi/intake/decision-138.py"
        require(Path(value["helper"]).resolve() == helper.resolve()
                and value["helper_sha256"] == records.get("adapters/pi/intake/decision-138.py"),
                "Framework helper binding differs")
        check(value["python"], value["python_sha256"], "Framework Python")
        check(value["helper"], value["helper_sha256"], "Framework helper")
        files = value["files"]
        require(isinstance(files, list) and 0 < len(files) <= 500, "Framework source closure is unavailable")
        seen = set()
        for item in files:
            require(item["path"] not in seen, "Duplicate Framework source binding")
            seen.add(item["path"])
            check(item["path"], item["sha256"], "Framework source")
    memory = config.get("memory_runtime")
    if memory:
        require(memory.get("schema") == "memory-runtime/v1"
                and memory.get("mempalace_version") == "3.11.0", "Memory descriptor schema/version differs")
        require(Path(memory["cache_directory"]).resolve()
                == (home / "cache/chroma/onnx_models/all-MiniLM-L6-v2").resolve(),
                "Memory cache binding differs")
        check(memory["python"], memory["python_sha256"], "Memory Python")
        check(memory["onnx_source"]["path"], memory["onnx_source"]["sha256"], "Memory ONNX source")
        shim = inside(home, "bin/mempalace", exists=True)
        check(shim, config.get("memory_cli_sha256"), "Memory CLI")
        artifacts["bin/mempalace"] = digest(shim)
    return bound


def active_snapshot(home):
    require(not Path(home).is_symlink(), "Select the actual home directory")
    require(not (Path(home) / "home.json").is_symlink(), "Active home configuration symlink is unsupported")
    home, config = bootstrap.load(Path(home))
    runtime = home / "runtime"
    manifest_path = inside(home, "runtime/runtime-manifest.json", exists=True)
    require(digest(manifest_path) == config["runtime_manifest_sha256"], "Active runtime manifest drift")
    manifest = read_json(manifest_path)
    records = {}
    for item in manifest["files"]:
        name = item["path"]
        require(name not in records, "Duplicate active runtime artifact")
        path = inside(runtime, name, exists=True)
        require(path.is_file() and digest(path) == item["sha256"], "Active runtime source drift: " + name)
        records[name] = item["sha256"]
    artifacts = {"home.json": digest(home / "home.json"),
                 "runtime/runtime-manifest.json": digest(manifest_path)}
    artifacts.update({"runtime/" + name: value for name, value in records.items()})
    for name in ("agent-home.py", "runtime/adapters/pi/project-workflow/everyday-runtime.json",
                 "state/framework-binding.json"):
        path = inside(home, name)
        if path.exists():
            artifacts[name] = digest(path)
    bindings = read_json(home / "runtime/adapters/pi/project-workflow/everyday-runtime.json")
    require(Path(bindings["runtime"]).resolve() == runtime.resolve(), "Active workflow runtime binding differs")
    require(bindings["runtime_manifest_sha256"] == config["runtime_manifest_sha256"], "Active workflow manifest binding differs")
    require(bindings["engine_sha256"] == records.get("harness/enforcement.py"), "Active engine binding differs")
    require(bindings["helper_sha256"] == records.get("adapters/pi/project-workflow/everyday_workflow.py"), "Active workflow helper binding differs")
    bound_artifacts = descriptor_artifacts(home, config, records, artifacts)
    known = set(records) | {"runtime-manifest.json", "adapters/pi/project-workflow/everyday-runtime.json"}
    for path in runtime.rglob("*"):
        if "__pycache__" in path.parts:
            continue
        require(not path.is_symlink(), "Unexpected active runtime symlink")
        if path.is_file():
            require(path.relative_to(runtime).as_posix() in known, "Unlisted active runtime artifact: " + str(path))
    package_artifacts = []
    for key, record in sorted(config.get("installed", {}).items()):
        require(all(".." not in Path(item["path"]).parts for item in record.get("artifacts", [])), "Package artifact path escaped its home")
        require(bootstrap.check_package(home, key, record) is None, "Active package artifact drift: " + key)
        package_artifacts.append({"package": key, "requested": record.get("requested"),
                                  "artifacts": record["artifacts"]})
    pins = pin_literals(runtime / "harness/home.py")
    require(all(pins.get(k) == v for k, v in config["selected_packages"].items()), "Active package declarations differ from active source")
    interpreter = Path(bindings["python"])
    require(interpreter.is_absolute() and interpreter.is_file(), "Active workflow interpreter is unavailable")
    result = {"home": str(home), "runtime_files": records, "artifacts": artifacts,
              "pins": pins, "packages": package_artifacts, "bound_artifacts": bound_artifacts,
              "python": bindings["python"], "python_sha256": digest(interpreter)}
    result["sha256"] = canonical_hash(result)
    return home, config, result


def source_inventory(source):
    require(not Path(source).is_symlink(), "Select the actual source directory")
    source = Path(source).expanduser().resolve(strict=True)
    paths = set(bootstrap.source_files(source))
    # The runtime inventory and the installation template closure differ:
    # include non-code templates such as gitignore.template as exact data too.
    templates = source / "harness/templates/agent-home"
    for name in bootstrap.REQUIRED_TEMPLATES:
        require((templates / name).is_file(), "Missing required candidate template: " + name)
    paths.update(path for path in templates.rglob("*") if path.is_file())
    records = {}
    for path in sorted(paths):
        require(not path.is_symlink() and path.resolve().is_relative_to(source), "Candidate source symlink/escape")
        name = path.relative_to(source).as_posix()
        inside(source, name, exists=True)
        records[name] = digest(path)
    for name in ("pi-task-worker.py", "pi_native_events.py"):
        original = "adapters/pi/project-workflow/" + name
        require(original in records, "Missing process-owner source: " + name)
        records[name] = records[original]
    return source, records, pin_literals(source / "harness/home.py")


def local_closure(root, records):
    """Check static local references, without importing candidate code."""
    references, errors = [], []
    for name in records:
        path = root / name
        if path.suffix == ".py":
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
            except (SyntaxError, UnicodeError) as error:
                errors.append(str(error))
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.ImportFrom):
                    continue
                if node.level:
                    parent = path.parent
                    for _ in range(node.level - 1):
                        parent = parent.parent
                    modules = [node.module] if node.module else [alias.name for alias in node.names]
                elif node.module and node.module.split(".")[0] in {"harness", "ssot"}:
                    parent, modules = root, [node.module]
                else:
                    continue
                for module in modules:
                    base = parent.joinpath(*module.split("."))
                    candidates = [base.with_suffix(".py"), base / "__init__.py"]
                    found = next((p for p in candidates if p.is_file() and p.resolve().is_relative_to(root.resolve())), None)
                    if found is None:
                        errors.append(name + ": unresolved local Python import " + module)
                    elif found.relative_to(root).as_posix() not in records:
                        errors.append(name + ": local Python import outside selected source inventory " + module)
                    else:
                        references.append({"from": name, "to": found.relative_to(root).as_posix()})
        elif path.suffix in {".ts", ".mjs", ".js"}:
            text = path.read_text(encoding="utf-8")
            for target in re.findall(r"(?:from\s*|import\s*\(?)['\"](\.[^'\"]+)['\"]", text):
                resolved = (path.parent / target).resolve()
                if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
                    errors.append(name + ": unresolved local JS import " + target)
                elif resolved.relative_to(root).as_posix() not in records:
                    errors.append(name + ": local JS import outside selected source inventory " + target)
                else:
                    references.append({"from": name, "to": resolved.relative_to(root).as_posix()})
    return {"references": references, "errors": errors, "scope": "Static Python syntax/local from-imports and literal relative JS imports only; dynamic and package APIs remain unqualified"}


def external_imports(root, records):
    """Detect new literal dependency requests; do not resolve or import them."""
    result = set()
    for name in records:
        path = root / name
        if path.suffix == ".py":
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=name)
            except (SyntaxError, UnicodeError):
                continue  # local_closure reports syntax failures separately.
            for node in ast.walk(tree):
                modules = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                           else [node.module] if isinstance(node, ast.ImportFrom) and not node.level and node.module else [])
                for module in modules:
                    top = module.split(".")[0]
                    if top in sys.stdlib_module_names or top in {"harness", "ssot"}:
                        continue
                    if (top + ".py") in records or (path.parent / (top + ".py")).is_file():
                        continue
                    result.add("python:" + module)
        elif path.suffix in {".ts", ".mjs", ".js"}:
            for module in re.findall(r"(?:from\s*|import\s*\(?)['\"]([^'\"]+)['\"]", path.read_text(encoding="utf-8")):
                if not module.startswith((".", "node:")):
                    result.add("javascript:" + module)
    return sorted(result)


def updates_directory(home, *, create=False):
    path = inside(home, "state/updates")
    if create:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def pending_operations(home):
    directory = updates_directory(home)
    if not directory.exists():
        return []
    result = []
    for path in sorted(directory.iterdir()):
        if path.name == ".maintenance.lock":
            result.append("operation lock requires inspection")
        elif path.name == "pending-activation.json":
            result.append("pending activation requires recovery")
        elif path.is_symlink():
            raise MaintenanceError("Unexpected update-state symlink")
        elif path.is_dir():
            receipt = path / "admission.json"
            status = read_json(receipt).get("status") if receipt.exists() else "incomplete"
            completed_update = False
            update = path / "runtime-update.json"
            if receipt.is_file() and update.exists():
                try:
                    record = read_json(update)
                    completed_update = (isinstance(record, dict) and record.get("schema") == "agent-home-runtime-update/v1"
                                        and record.get("home") == str(home)
                                        and record.get("operation") == path.name
                                        and record.get("stage_receipt_sha256") == digest(receipt)
                                        and record.get("status") in {"accepted", "rolled_back", "recovered_predecessor"})
                except (OSError, ValueError, TypeError):
                    pass  # Unknown or damaged journals stay pending.
            if status != "withdrawn_not_active" and not completed_update:
                result.append(path.name + ": " + str(status))
    return result


def plan(home, source):
    home, _config, active = active_snapshot(home)
    source, records, pins = source_inventory(source)
    # Root process-owner copies are materialized during stage, not source files.
    closure = local_closure(source, {k: v for k, v in records.items() if "/" in k})
    package_changes = [{"package": key, "old": active["pins"].get(key), "new": pins.get(key)}
                       for key in sorted(set(active["pins"]) | set(pins)) if active["pins"].get(key) != pins.get(key)]
    old = active["runtime_files"]
    introduced_imports = sorted(set(external_imports(source, {k: v for k, v in records.items() if "/" in k}))
                                - set(external_imports(home / "runtime", old)))
    result = {"schema": SCHEMA, "home": str(home), "source": str(source), "active": active,
              "source_files": records, "source_sha256": canonical_hash(records), "pins": pins,
              "diff": {"added": sorted(set(records) - set(old)), "removed": sorted(set(old) - set(records)),
                       "changed": sorted(k for k in set(records) & set(old) if records[k] != old[k])},
              "package_changes": package_changes, "introduced_dependency_imports": introduced_imports, "local_closure": closure,
              "preserved_unmodified": PRESERVED, "pending_operations": pending_operations(home),
              "candidate_runtime_acceptance": "not_run", "activation": "unsupported; launcher/environment, memory and Framework bindings still target home/runtime",
              "package_qualification": "Existing declared artifact identities only; full transitive package/API qualification is pending and no package is installed"}
    result["estimated_stage_bytes"] = sum((source / ("adapters/pi/project-workflow/" + k if "/" not in k else k)).stat().st_size
                                          for k in records) + sum((home / name).stat().st_size for name in active["artifacts"])
    result["plan_sha256"] = canonical_hash(result)
    return result


@contextmanager
def operation_lock(home, operation):
    directory = updates_directory(home, create=True)
    lock = directory / ".maintenance.lock"
    data = json.dumps({"operation": operation, "pid": os.getpid(), "nonce": os.urandom(16).hex()}).encode()
    try:
        with lock.open("xb") as stream:
            stream.write(data)
    except FileExistsError as error:
        raise MaintenanceError("An update operation is pending; inspect its exact lock") from error
    try:
        yield directory
    finally:
        if lock.is_file() and not lock.is_symlink() and lock.read_bytes() == data:
            lock.unlink()


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def copy_exact(source, target, expected):
    require(digest(source) == expected, "Source changed before copy: " + str(source))
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with source.open("rb") as old, target.open("xb") as new:
        shutil.copyfileobj(old, new, 1024 * 1024)
    require(digest(target) == expected and digest(source) == expected, "Source changed during copy")


def stage(home, source, operation, expected_plan):
    require(IDENTIFIER.fullmatch(operation), "Use an explicit operation identifier")
    selected = plan(home, source)
    require(selected["plan_sha256"] == expected_plan, "Plan/source/active state drift; inspect a fresh plan")
    require(not selected["package_changes"], "Package pins changed; a separate dependency qualification is required")
    require(not selected["introduced_dependency_imports"], "New dependency imports need separate dependency qualification")
    require(not selected["local_closure"]["errors"], "Candidate has unresolved static source references")
    require(not selected["pending_operations"], "Inspect/withdraw the pending update operation first")
    home, source = Path(selected["home"]), Path(selected["source"])
    require(shutil.disk_usage(home).free >= selected["estimated_stage_bytes"] * 2 + 8 * 1024 * 1024,
            "Insufficient staging space; preserve active data and use the selected home storage owner")
    with operation_lock(home, operation) as directory:
        require(not [item for item in pending_operations(home) if item != "operation lock requires inspection"],
                "Another operation became pending before staging")
        require(active_snapshot(home)[2]["sha256"] == selected["active"]["sha256"], "Active state changed before staging")
        require(source_inventory(source)[1] == selected["source_files"], "Candidate source changed before staging")
        target = directory / operation
        require(not target.exists(), "Operation replay is not permitted")
        target.mkdir(mode=0o700)
        write_new(target / "request.json", selected)
        try:
            for name, expected in selected["active"]["artifacts"].items():
                copy_exact(inside(home, name, exists=True), target / "predecessor" / name, expected)
            runtime = target / "candidate/runtime"
            for name, expected in selected["source_files"].items():
                original = source / ("adapters/pi/project-workflow/" + name if "/" not in name else name)
                copy_exact(original, runtime / name, expected)
            manifest = {"files": [{"path": name, "sha256": value} for name, value in sorted(selected["source_files"].items())]}
            write_new(runtime / "runtime-manifest.json", manifest)
            workflow = runtime / "adapters/pi/project-workflow"
            write_new(workflow / "everyday-runtime.json", {"python": selected["active"]["python"], "runtime": str(runtime),
                      "runtime_manifest_sha256": digest(runtime / "runtime-manifest.json"),
                      "engine_sha256": selected["source_files"]["harness/enforcement.py"],
                      "helper_sha256": selected["source_files"]["adapters/pi/project-workflow/everyday_workflow.py"]})
            require(active_snapshot(home)[2]["sha256"] == selected["active"]["sha256"], "Active state changed during staging")
            candidate_files = {p.relative_to(runtime).as_posix(): digest(p) for p in sorted(runtime.rglob("*")) if p.is_file()}
            receipt = {"schema": SCHEMA, "operation": operation, "status": "staged_not_active", "created": stamp(),
                       "home": str(home), "plan_sha256": expected_plan, "active_sha256": selected["active"]["sha256"],
                       "request_sha256": digest(target / "request.json"),
                       "candidate_files": candidate_files, "candidate_sha256": canonical_hash(candidate_files),
                       "candidate_runtime_acceptance": "not_run", "activation": "unsupported", "rollback": "withdraw candidate only; active generation was not replaced"}
            write_new(target / "admission.json", receipt)
        except Exception as error:
            write_new(target / "admission.json", {"schema": SCHEMA, "operation": operation, "home": str(home),
                      "status": "failed_staging_not_active", "error": str(error), "active_sha256": selected["active"]["sha256"]})
            raise
    return {**receipt, "receipt": str(target / "admission.json"), "receipt_sha256": digest(target / "admission.json")}


def selected_operation(home, operation):
    require(IDENTIFIER.fullmatch(operation), "Invalid operation identifier")
    home, _config = bootstrap.load(Path(home))
    target = inside(home, "state/updates/" + operation, exists=True)
    receipt = read_json(target / "admission.json")
    require(receipt.get("schema") == SCHEMA and receipt.get("home") == str(home)
            and receipt.get("operation") == operation, "Operation identity differs")
    return home, target, receipt


def verify_stage(home, operation):
    home, target, receipt = selected_operation(home, operation)
    errors = []
    if receipt.get("status") != "staged_not_active":
        errors.append("Candidate is not in staged_not_active state")
    runtime = target / "candidate/runtime"
    files = {}
    if runtime.is_dir() and not runtime.is_symlink():
        for file in sorted(runtime.rglob("*")):
            if file.is_symlink():
                errors.append("Candidate symlink: " + str(file))
            elif file.is_file():
                files[file.relative_to(runtime).as_posix()] = digest(file)
    if files != receipt.get("candidate_files") or canonical_hash(files) != receipt.get("candidate_sha256"):
        errors.append("Candidate file inventory changed")
    request = read_json(target / "request.json")
    if digest(target / "request.json") != receipt.get("request_sha256"):
        errors.append("Retained request changed")
    requested_plan = {k: v for k, v in request.items() if k != "plan_sha256"}
    if request.get("plan_sha256") != receipt.get("plan_sha256") or canonical_hash(requested_plan) != request.get("plan_sha256"):
        errors.append("Retained plan binding differs")
    if runtime.is_dir():
        for name, expected in request["source_files"].items():
            if files.get(name) != expected:
                errors.append("Candidate source differs from retained plan: " + name)
        closure = local_closure(runtime, request["source_files"])
        errors.extend(closure["errors"])
    for name, expected in request["active"]["artifacts"].items():
        file = inside(target / "predecessor", name)
        if not file.is_file() or digest(file) != expected:
            errors.append("Predecessor backup changed: " + name)
    try:
        if active_snapshot(home)[2]["sha256"] != receipt.get("active_sha256"):
            errors.append("Active state changed after staging")
    except (OSError, ValueError) as error:
        errors.append("Active state cannot be verified: " + str(error))
    return {"schema": SCHEMA, "operation": operation, "valid_staged_source": not errors, "errors": errors,
            "active_generation_replaced": False, "candidate_runtime_acceptance": "not_run", "activation": "unsupported"}


def withdraw(home, operation, expected_receipt):
    home, target, receipt = selected_operation(home, operation)
    update = target / "runtime-update.json"
    require(not update.exists() and not update.is_symlink(),
            "Runtime update history exists; use its recovery or rollback route without changing stage admission")
    path = target / "admission.json"
    require(receipt["status"] in {"staged_not_active", "failed_staging_not_active"}, "Operation is already terminal")
    require(digest(path) == expected_receipt, "Receipt drift; inspect the exact operation")
    with operation_lock(home, operation):
        require(not update.exists() and not update.is_symlink(), "Runtime update appeared before withdrawal")
        original = path.read_bytes()
        require(hashlib.sha256(original).hexdigest() == expected_receipt, "Receipt changed before withdrawal")
        backup = path.with_name(path.name + ".previous-" + stamp())
        with backup.open("xb") as stream:
            stream.write(original)
        replacement = {**receipt, "status": "withdrawn_not_active", "withdrawn": stamp(),
                       "withdrawal": "Candidate retired without changing active runtime or user state; all retained bytes preserved"}
        descriptor, name = tempfile.mkstemp(prefix="admission-", suffix=".tmp", dir=target)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(replacement, stream, indent=2, ensure_ascii=False)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            require(digest(path) == expected_receipt, "Concurrent receipt drift")
            os.replace(name, path)
        finally:
            temporary = Path(name)
            if temporary.exists():
                temporary.unlink()
    return {**replacement, "receipt_sha256": digest(path), "previous_receipt": str(backup)}


def inspect(home):
    home, config = bootstrap.load(Path(home))
    return {"schema": SCHEMA, "home": str(home), "active_doctor": bootstrap.doctor(home),
            "doctor_scope": "Current active generation only; not candidate qualification", "pending_operations": pending_operations(home),
            "selected_packages": config["selected_packages"], "running_generation": "not_observed",
            "activation": "unsupported", "preserved_unmodified": PRESERVED}


def repair_plan(home):
    result = inspect(home)
    binding = read_json(Path(result["home"]) / "runtime/adapters/pi/project-workflow/everyday-runtime.json")
    result["repair"] = {"automatic_changes": False,
                        "package_route": [binding["python"], "-B", str(Path(result["home"]) / "agent-home.py"), "resume-install"],
                        "limits": "Review exact active doctor failures before explicit package repair. Runtime drift needs a reviewed predecessor and coordinated binding recovery; this module does not replace active source or reinstall packages."}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--home", required=True, type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("inspect")
    commands.add_parser("repair-plan")
    for name in ("plan", "stage"):
        command = commands.add_parser(name)
        command.add_argument("--source", required=True, type=Path)
        if name == "stage":
            command.add_argument("--operation", required=True)
            command.add_argument("--expected-plan", required=True)
    for name in ("verify-stage", "withdraw"):
        command = commands.add_parser(name)
        command.add_argument("--operation", required=True)
        if name == "withdraw":
            command.add_argument("--expected-receipt", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = inspect(args.home)
        elif args.command == "repair-plan":
            result = repair_plan(args.home)
        elif args.command == "plan":
            result = plan(args.home, args.source)
        elif args.command == "stage":
            result = stage(args.home, args.source, args.operation, args.expected_plan)
        elif args.command == "verify-stage":
            result = verify_stage(args.home, args.operation)
        else:
            result = withdraw(args.home, args.operation, args.expected_receipt)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if result.get("valid_staged_source") is False else 0
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"schema": SCHEMA, "status": "refused", "error": str(error), "active_runtime_changed_by_this_operation": False}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
