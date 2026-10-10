"""Run the dependency-free release gate for the portable SSOT package."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SELFTESTS = (
    "harness/verify.py",
    "harness/paired_gate.py",
    "harness/dispatch_retry.py",
    "harness/research_ground.py",
    "harness/model_catalog.py",
    "harness/hardware_probe.py",
    "scripts/autotune_offload.py",
)

TAIL_BYTES = 80000
SETTLEMENT_SECONDS = 3
# Preserve ownership when an exact child does not settle. Never infer that its
# descendants stopped, and do not let a Popen context manager wait indefinitely.
UNSETTLED_CHILDREN = []


def output_snapshot(stream) -> dict:
    before = os.fstat(stream.fileno())
    offset = max(0, before.st_size - TAIL_BYTES)
    count = before.st_size - offset
    # Never move the writer's shared file offset. Descendants can still write.
    if hasattr(os, "pread"):
        data = os.pread(stream.fileno(), count, offset)
    else:
        reader = os.open(stream.name, os.O_RDONLY | os.O_BINARY | os.O_TEMPORARY)
        try:
            os.lseek(reader, offset, os.SEEK_SET)
            data = os.read(reader, count)
        finally:
            os.close(reader)
    after = os.fstat(stream.fileno())
    decoded = data.decode("utf-8", errors="replace")
    return {
        "tail": decoded[-20000:],
        "observed_bytes": before.st_size,
        "sampled_bytes": len(data),
        "sampled_sha256": hashlib.sha256(data).hexdigest(),
        "truncated": offset > 0 or len(decoded) > 20000,
        "stable": (before.st_size, before.st_mtime_ns)
        == (after.st_size, after.st_mtime_ns)
        and len(data) == before.st_size - offset,
    }


def run(argv: list[str], *, cwd: Path = ROOT, env=None, timeout: int = 120) -> dict:
    with tempfile.TemporaryFile(mode="w+b") as stdout, tempfile.TemporaryFile(mode="w+b") as stderr:
        child = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            shell=False,
        )
        timed_out = False
        settled = True
        kill_error = None
        try:
            child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            try:
                child.kill()
            except OSError as exc:
                kill_error = type(exc).__name__
            try:
                child.wait(timeout=SETTLEMENT_SECONDS)
            except subprocess.TimeoutExpired:
                settled = False
                UNSETTLED_CHILDREN.append(child)
        captures = {"stdout": output_snapshot(stdout), "stderr": output_snapshot(stderr)}
        result = {
            "argv": argv,
            "exit_code": 124 if timed_out else child.returncode,
            "child_exit_code": child.returncode,
            "child_settled": settled,
            "stdout_tail": captures["stdout"].pop("tail"),
            "stderr_tail": captures["stderr"].pop("tail"),
            "output_snapshots": captures,
        }
        if kill_error is not None:
            result["kill_error"] = kill_error
        if not timed_out and not all(capture["stable"] for capture in captures.values()):
            result["exit_code"] = 125
    if timed_out:
        result.update(timed_out=True, timeout_seconds=timeout, settlement_seconds=SETTLEMENT_SECONDS)
        print("Release command timed out: " + json.dumps(result), file=sys.stderr, flush=True)
    elif result["exit_code"] != 0:
        print("Release command returned nonzero: " + json.dumps(result), file=sys.stderr, flush=True)
    return result


def main() -> int:
    results = []
    results.append(
        run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            timeout=240,
        )
    )
    for path in SELFTESTS:
        results.append(run([sys.executable, path, "--selftest"]))

    forbidden = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT).as_posix()
        if (
            "/.ssot/" in f"/{relative}"
            or "/.enforcement/" in f"/{relative}"
            or "/.trusted-project/" in f"/{relative}"
            or relative.startswith("examples/ssot-starter/artifacts/")
            or relative.startswith("examples/enforced-task/artifacts/")
        ):
            forbidden.append(relative)

    with tempfile.TemporaryDirectory(prefix="ssot-release-") as temporary:
        demo_root = Path(temporary) / "ssot-starter"
        shutil.copytree(ROOT / "examples" / "ssot-starter", demo_root)
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT)
        demo = run([sys.executable, "demo.py"], cwd=demo_root, env=environment)
        results.append(demo)
        try:
            demo_status = json.loads(demo["stdout_tail"])
        except json.JSONDecodeError:
            demo_status = {}

        enforced_root = Path(temporary) / "enforced-task"
        shutil.copytree(ROOT / "examples" / "enforced-task", enforced_root)
        enforced_demo = run(
            [sys.executable, "demo.py"], cwd=enforced_root, env=environment
        )
        results.append(enforced_demo)
        try:
            enforced_status = json.loads(enforced_demo["stdout_tail"])
        except json.JSONDecodeError:
            enforced_status = {}

        integration_root = Path(temporary) / "integration-target"
        integration_root.mkdir()
        (integration_root / "AGENTS.md").write_text(
            "# Target instructions\n", encoding="utf-8"
        )
        integration_bootstrap = run(
            [
                sys.executable,
                "-m",
                "harness.integration",
                "--root",
                str(integration_root),
                "--host",
                "generic",
                "--surface",
                "AGENTS.md",
            ],
            env=environment,
        )
        results.append(integration_bootstrap)
        integration_doctor = run(
            [
                sys.executable,
                "-m",
                "ssot.cli",
                "--root",
                str(integration_root),
                "doctor",
            ],
            env=environment,
        )
        results.append(integration_doctor)
        try:
            integration_bootstrap_status = json.loads(
                integration_bootstrap["stdout_tail"]
            )
            integration_doctor_status = json.loads(integration_doctor["stdout_tail"])
        except json.JSONDecodeError:
            integration_bootstrap_status = {}
            integration_doctor_status = {}

        activation_root = Path(temporary) / "activation-target"
        activation_root.mkdir()
        (activation_root / "AGENTS.md").write_text(
            "# Activation target\n", encoding="utf-8"
        )
        activation_budget = activation_root / "budget.json"
        activation_budget.write_text(
            json.dumps(
                {
                    "model_tokens": 0,
                    "cost_usd": 0,
                    "wall_seconds": 60,
                    "outer_attempts": 2,
                    "research_sources": 0,
                    "storage_bytes": 100000,
                    "external_side_effects": 0,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        activation_plan = run(
            [
                sys.executable,
                "-m",
                "harness.project",
                "execute",
                "Build the copied release fixture",
                "--root",
                str(activation_root),
                "--budget-file",
                str(activation_budget),
            ],
            env=environment,
        )
        results.append(activation_plan)
        try:
            activation_plan_status = json.loads(activation_plan["stdout_tail"])
        except json.JSONDecodeError:
            activation_plan_status = {}
        activation_status = run(
            [
                sys.executable,
                "-m",
                "harness.project",
                "status",
                activation_plan_status.get("project_id", "invalid"),
                "--root",
                str(activation_root),
            ],
            env=environment,
        )
        results.append(activation_status)
        try:
            activation_derived_status = json.loads(activation_status["stdout_tail"])
        except json.JSONDecodeError:
            activation_derived_status = {}

        project_id = activation_plan_status.get("project_id", "invalid")
        project_dir = (
            activation_root / ".trusted-project" / "projects" / project_id
        )
        intent_path = project_dir / "intent.json"
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        candidate = activation_root / "candidate"
        candidate.mkdir()
        prd_path = candidate / "PRD.md"
        prd_path.write_text(
            "# Copied release fixture\n\nBuild the copied release fixture.\n",
            encoding="utf-8",
        )
        prd_lines = prd_path.read_bytes().splitlines(keepends=True)
        manifest = {
            "schema_version": 1,
            "project_id": project_id,
            "intent_sha256": hashlib.sha256(intent_path.read_bytes()).hexdigest(),
            "prd_sha256": hashlib.sha256(prd_path.read_bytes()).hexdigest(),
            "requirements": [
                {
                    "id": "REQ-001",
                    "text": "Build the copied release fixture.",
                    "acceptance": ["The fixture build is independently accepted."],
                    "sources": [
                        {
                            "class": "user",
                            "locator": "intent.request",
                            "sha256": intent["request"]["sha256"],
                        }
                    ],
                    "prd_locator": {
                        "line_start": 3,
                        "line_end": 3,
                        "text_sha256": hashlib.sha256(prd_lines[2]).hexdigest(),
                    },
                }
            ],
            "non_goals": [],
            "constraints": [],
            "risks": [{"risk": "fixture drift", "mitigation": "bind exact bytes"}],
            "dependencies": [],
            "deliverables": ["copied fixture"],
            "open_decisions": [],
        }
        manifest_path = candidate / "prd-manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        check_names = (
            "coverage",
            "contradictions",
            "provenance",
            "feasibility",
            "risk",
            "failure_recovery",
            "measurable_acceptance",
        )
        reinforcement = {
            "schema_version": 1,
            "project_id": project_id,
            "critic_identity": "release-critic",
            "prd_sha256": manifest["prd_sha256"],
            "manifest_sha256": hashlib.sha256(
                manifest_path.read_bytes()
            ).hexdigest(),
            "checks": {
                name: {"passed": True, "evidence": [f"{name} checked"]}
                for name in check_names
            },
            "issues": [],
            "open_decisions": [],
        }
        reinforcement_path = candidate / "prd-reinforcement.json"
        reinforcement_path.write_text(
            json.dumps(reinforcement, indent=2) + "\n", encoding="utf-8"
        )
        reviewer_path = activation_root / "review_prd.py"
        reviewer_path.write_text(
            """import json, os, sys
from pathlib import Path
if '--negative-control' in sys.argv:
    print(json.dumps({'verdict': 'negative_control_pass', 'reviewer_identity': 'release-reviewer'}))
else:
    manifest = json.loads(Path(os.environ['TRUSTED_PROJECT_MANIFEST']).read_text())
    print(json.dumps({
        'verdict': 'approved',
        'reviewer_identity': 'release-reviewer',
        'project_id': os.environ['TRUSTED_PROJECT_PROJECT_ID'],
        'intent_sha256': os.environ['TRUSTED_PROJECT_INTENT_SHA256'],
        'prd_sha256': os.environ['TRUSTED_PROJECT_PRD_SHA256'],
        'manifest_sha256': os.environ['TRUSTED_PROJECT_MANIFEST_SHA256'],
        'reinforcement_sha256': os.environ['TRUSTED_PROJECT_REINFORCEMENT_SHA256'],
        'requirement_ids': [row['id'] for row in manifest['requirements']],
        'open_decisions': [],
    }))
""",
            encoding="utf-8",
        )
        contract = {
            "schema_version": 1,
            "project_id": project_id,
            "drafter_identity": "release-drafter",
            "prd_path": "candidate/PRD.md",
            "manifest_path": "candidate/prd-manifest.json",
            "reinforcement_path": "candidate/prd-reinforcement.json",
            "reviewer": {
                "owner": "release-reviewer",
                "argv": ["{python}", "review_prd.py"],
                "files": ["review_prd.py"],
                "timeout_seconds": 30,
                "negative_control": {
                    "argv": ["{python}", "review_prd.py", "--negative-control"],
                    "files": ["review_prd.py"],
                    "timeout_seconds": 30,
                },
            },
        }
        contract_path = activation_root / "admit-prd.json"
        contract_path.write_text(
            json.dumps(contract, indent=2) + "\n", encoding="utf-8"
        )
        activation_admit = run(
            [
                sys.executable,
                "-m",
                "harness.project",
                "admit-prd",
                project_id,
                "--root",
                str(activation_root),
                "--contract",
                str(contract_path),
            ],
            env=environment,
        )
        results.append(activation_admit)
        try:
            activation_reviewed_status = json.loads(activation_admit["stdout_tail"])
        except json.JSONDecodeError:
            activation_reviewed_status = {}
        reviewed_prd = project_dir / "prd" / "PRD.md"
        reviewed_prd_relative = reviewed_prd.relative_to(activation_root).as_posix()
        reviewed_manifest = json.loads(
            (project_dir / "prd" / "prd-manifest.json").read_text(encoding="utf-8")
        )
        reviewed_requirement = reviewed_manifest["requirements"][0]
        reviewed_locator = reviewed_requirement["prd_locator"]
        stage_verifier = activation_root / "verify_stage.py"
        stage_verifier.write_text("raise SystemExit(0)\n", encoding="utf-8")
        task_worker = activation_root / "worker.py"
        task_worker.write_text(
            "from pathlib import Path\nPath('result.json').write_text('{}\\n')\n",
            encoding="utf-8",
        )
        task_verifier = activation_root / "verify_task.py"
        task_verifier.write_text("raise SystemExit(0)\n", encoding="utf-8")
        project_acceptor = activation_root / "accept_project.py"
        project_acceptor.write_text("raise SystemExit(0)\n", encoding="utf-8")
        task_contract = {
            "schema_version": 1,
            "task_id": "release-build",
            "objective": "Build the copied release fixture.",
            "worker": {
                "argv": ["{python}", "worker.py"],
                "files": ["worker.py"],
                "timeout_seconds": 30,
            },
            "outputs": ["result.json"],
            "receipt_output": "enforcement-receipt.json",
            "retry": {
                "max_attempts": 2,
                "retry_on": ["process_failure", "verification_failure"],
                "backoff_seconds": [0],
                "inner_tool_max_attempts": 1,
            },
            "research": {"required": False},
            "verifier": {
                "argv": ["{python}", "verify_task.py"],
                "files": ["verify_task.py"],
                "timeout_seconds": 30,
                "negative_control": {
                    "argv": ["{python}", "verify_task.py", "--negative-control"],
                    "files": ["verify_task.py"],
                    "timeout_seconds": 30,
                },
            },
        }
        task_contract_path = candidate / "build-task.json"
        task_contract_path.write_text(
            json.dumps(task_contract, indent=2) + "\n", encoding="utf-8"
        )
        ssot_candidate = {
            "schema_version": 1,
            "project_id": project_id,
            "authority_cap": "tested",
            "target": {"files": [reviewed_prd_relative]},
            "requirements": [
                {
                    "id": reviewed_requirement["id"],
                    "text": reviewed_requirement["text"],
                    "scope_class": "project_specific",
                    "source": {
                        "path": reviewed_prd_relative,
                        "locator": (
                            f"line:{reviewed_locator['line_start']}-"
                            f"{reviewed_locator['line_end']}"
                        ),
                        "sha256": hashlib.sha256(
                            reviewed_prd.read_bytes()
                        ).hexdigest(),
                    },
                    "disposition": "applicable",
                    "owner_stage": "build",
                    "acceptance_evidence": reviewed_requirement["acceptance"],
                }
            ],
            "stages": [
                {
                    "id": "build",
                    "objective": "Build the copied release fixture.",
                    "acceptance": "The reviewed property passes.",
                    "depends_on": [],
                    "requirements": [reviewed_requirement["id"]],
                    "materials": [
                        reviewed_prd_relative,
                        "candidate/build-task.json",
                        "worker.py",
                        "verify_task.py",
                    ],
                    "trace_output": "ssot-execution-trace.json",
                    "outputs": [
                        "result.json",
                        "enforcement-receipt.json",
                        "ssot-execution-trace.json",
                    ],
                    "properties": reviewed_requirement["acceptance"],
                    "action": {
                        "kind": "harness.enforcement",
                        "producer": "release-worker",
                        "verifier_owner": "release-task-verifier",
                        "contract": "candidate/build-task.json",
                        "contract_sha256": hashlib.sha256(
                            task_contract_path.read_bytes()
                        ).hexdigest(),
                        "receipt_output": "enforcement-receipt.json",
                        "usage_mode": "script_no_model",
                        "effects": [],
                        "runtime_profile": None,
                        "runtime_profile_sha256": None,
                    },
                    "verifier": {
                        "owner": "release-stage-verifier",
                        "type": "deterministic_property",
                        "argv": ["{python}", "verify_stage.py"],
                        "negative_control": {
                            "argv": [
                                "{python}",
                                "verify_stage.py",
                                "--negative-control",
                            ]
                        },
                        "files": ["verify_stage.py"],
                        "timeout_seconds": 30,
                    },
                }
            ],
            "acceptance": {
                "owner": "release-project-acceptor",
                "type": "deterministic_property",
                "argv": ["{python}", "accept_project.py"],
                "negative_control": {
                    "argv": [
                        "{python}",
                        "accept_project.py",
                        "--negative-control",
                    ]
                },
                "files": ["accept_project.py"],
                "timeout_seconds": 30,
            },
        }
        ssot_candidate_path = candidate / "ssot-project.json"
        ssot_candidate_path.write_text(
            json.dumps(ssot_candidate, indent=2) + "\n", encoding="utf-8"
        )

        def release_file_record(path):
            return {
                "path": path.relative_to(activation_root).as_posix(),
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }

        verifier_candidates = {
            "schema_version": 1,
            "project_id": project_id,
            "status": "untrusted_drafts",
            "generated_by": "release-compiler",
            "candidate_manifest_sha256": hashlib.sha256(
                ssot_candidate_path.read_bytes()
            ).hexdigest(),
            "verifiers": [
                {
                    "scope": "stage:build",
                    "owner": "release-stage-verifier",
                    "argv": ["{python}", "verify_stage.py"],
                    "negative_control_argv": [
                        "{python}",
                        "verify_stage.py",
                        "--negative-control",
                    ],
                    "files": [release_file_record(stage_verifier)],
                },
                {
                    "scope": "action:build",
                    "owner": "release-task-verifier",
                    "argv": ["{python}", "verify_task.py"],
                    "negative_control_argv": [
                        "{python}",
                        "verify_task.py",
                        "--negative-control",
                    ],
                    "files": [release_file_record(task_verifier)],
                },
                {
                    "scope": "acceptance",
                    "owner": "release-project-acceptor",
                    "argv": ["{python}", "accept_project.py"],
                    "negative_control_argv": [
                        "{python}",
                        "accept_project.py",
                        "--negative-control",
                    ],
                    "files": [release_file_record(project_acceptor)],
                },
            ],
        }
        verifier_candidates_path = candidate / "verifier-candidates.json"
        verifier_candidates_path.write_text(
            json.dumps(verifier_candidates, indent=2) + "\n", encoding="utf-8"
        )
        ssot_reviewer = activation_root / "review_ssot.py"
        ssot_reviewer.write_text(
            """import json, os, sys
from pathlib import Path
owner = 'release-ssot-reviewer'
if '--negative-control' in sys.argv:
    print(json.dumps({'verdict': 'negative_control_pass', 'reviewer_identity': owner}))
else:
    manifest = json.loads(Path(os.environ['TRUSTED_PROJECT_MANIFEST']).read_text())
    verifiers = json.loads(Path(os.environ['TRUSTED_PROJECT_VERIFIER_CANDIDATES']).read_text())
    print(json.dumps({
        'verdict': 'approved',
        'reviewer_identity': owner,
        'project_id': os.environ['TRUSTED_PROJECT_PROJECT_ID'],
        'intent_sha256': os.environ['TRUSTED_PROJECT_INTENT_SHA256'],
        'review_receipt_sha256': os.environ['TRUSTED_PROJECT_REVIEW_RECEIPT_SHA256'],
        'manifest_sha256': os.environ['TRUSTED_PROJECT_MANIFEST_SHA256'],
        'verifier_candidates_sha256': os.environ['TRUSTED_PROJECT_VERIFIER_CANDIDATES_SHA256'],
        'requirement_ids': [row['id'] for row in manifest['requirements']],
        'verifier_scopes': [row['scope'] for row in verifiers['verifiers']],
    }))
""",
            encoding="utf-8",
        )
        compile_contract = {
            "schema_version": 1,
            "project_id": project_id,
            "compiler_identity": "release-compiler",
            "manifest_path": ssot_candidate_path.relative_to(
                activation_root
            ).as_posix(),
            "verifier_candidates_path": verifier_candidates_path.relative_to(
                activation_root
            ).as_posix(),
            "reviewer": {
                "owner": "release-ssot-reviewer",
                "argv": ["{python}", "review_ssot.py"],
                "files": ["review_ssot.py"],
                "timeout_seconds": 30,
                "negative_control": {
                    "argv": ["{python}", "review_ssot.py", "--negative-control"],
                    "files": ["review_ssot.py"],
                    "timeout_seconds": 30,
                },
            },
        }
        compile_contract_path = activation_root / "compile-ssot.json"
        compile_contract_path.write_text(
            json.dumps(compile_contract, indent=2) + "\n", encoding="utf-8"
        )
        activation_compile = run(
            [
                sys.executable,
                "-m",
                "harness.project",
                "compile-ssot",
                project_id,
                "--root",
                str(activation_root),
                "--contract",
                str(compile_contract_path),
            ],
            env=environment,
        )
        results.append(activation_compile)
        try:
            activation_compiled_status = json.loads(activation_compile["stdout_tail"])
        except json.JSONDecodeError:
            activation_compiled_status = {}
        activation_execute = run(
            [
                sys.executable,
                "-m",
                "harness.project",
                "execute",
                project_id,
                "--root",
                str(activation_root),
            ],
            env=environment,
        )
        results.append(activation_execute)
        try:
            activation_execute_status = json.loads(
                activation_execute["stdout_tail"]
            )
        except json.JSONDecodeError:
            activation_execute_status = {}

    failures = [row for row in results if row["exit_code"] != 0]
    if forbidden:
        failures.append({"forbidden_generated_files": forbidden})
    if not (
        demo_status.get("complete") is True
        and demo_status.get("authority_state") == "tested"
        and demo_status.get("requirements", {}).get("conserved") is True
    ):
        failures.append({"invalid_demo_status": demo_status})
    if not (
        enforced_status.get("complete") is True
        and enforced_status.get("authority_state") == "tested"
        and enforced_status.get("requirements", {}).get("conserved") is True
    ):
        failures.append({"invalid_enforced_demo_status": enforced_status})
    if not (
        integration_bootstrap_status.get("status") == "scaffolded"
        and integration_bootstrap_status.get("ready") is False
        and integration_doctor_status.get("ready") is False
        and integration_doctor_status.get("unresolved_requirements")
        == ["REQ-UNRESOLVED-001"]
    ):
        failures.append(
            {
                "invalid_integration_bootstrap": integration_bootstrap_status,
                "invalid_integration_doctor": integration_doctor_status,
            }
        )
    if not (
        activation_reviewed_status.get("state") == "prd_reviewed"
        and activation_reviewed_status.get("authority")
        == "reviewed_prd_only_no_execution"
        and activation_reviewed_status.get("ready_for_execution") is False
        and activation_compiled_status.get("state") == "configured"
        and activation_compiled_status.get("authority")
        == "no_project_completion_authority"
        and activation_compiled_status.get("ready_for_execution") is True
        and activation_execute_status.get("state") == "tested"
        and activation_execute_status.get("authority") == "tested"
        and activation_execute_status.get("execution_receipts") == 1
        and activation_execute_status.get("ssot", {}).get("accepted") is True
    ):
        failures.append(
            {
                "invalid_prd_admission": activation_reviewed_status,
                "invalid_ssot_compilation": activation_compiled_status,
                "invalid_compiled_execute_hold": activation_execute_status,
            }
        )
    if not (
        activation_plan_status.get("state") == "held_prd_not_reviewed"
        and activation_plan_status.get("authority") == "no_execution_authority"
        and activation_plan_status.get("ready_for_execution") is False
        and activation_derived_status.get("project_id")
        == activation_plan_status.get("project_id")
        and activation_derived_status.get("event_head_sha256")
        == activation_plan_status.get("event_head_sha256")
    ):
        failures.append(
            {
                "invalid_activation_plan": activation_plan_status,
                "invalid_activation_status": activation_derived_status,
            }
        )

    report = {
        "status": "tested" if not failures else "failed",
        "checks": len(results) + 4,
        "failed": failures,
        "unit_test_command": results[0]["argv"],
        "selftest_count": len(SELFTESTS),
        "copied_demo": demo_status,
        "copied_enforced_demo": enforced_status,
        "copied_integration_bootstrap": integration_bootstrap_status,
        "copied_integration_doctor": integration_doctor_status,
        "copied_activation_plan": activation_plan_status,
        "copied_activation_status": activation_derived_status,
        "copied_prd_admission": activation_reviewed_status,
        "copied_ssot_compilation": activation_compiled_status,
        "copied_compiled_execute_hold": activation_execute_status,
        "source_tree_generated_state": forbidden,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
