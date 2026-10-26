"""Installer-owned static board assets in the existing Hermes package record."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from harness import home_entry
from scripts import build_project_board_assets as compiler

DIRECTORY = "packages/project-board-ui"
SCHEMA = "agent-home-board-ui/v1"


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def paths(home):
    home = Path(home).resolve(strict=True)
    output = home / DIRECTORY
    require(all(not path.is_symlink() for path in (home / "packages", output)), "Board UI package path is redirected")
    return home, output, output / "manifest.json"


def source_inputs(home):
    runtime = home / "runtime"
    require(all((runtime / "adapters/project-board" / name).is_file()
                and not (runtime / "adapters/project-board" / name).is_symlink() for name in compiler.HOST_FILES),
            "Installed board host source is missing or redirected")
    return {name: digest(runtime / "adapters/project-board" / name) for name in compiler.HOST_FILES}


def matching_installer_source(home):
    require(all((home / "runtime" / name).is_file() and not (home / "runtime" / name).is_symlink()
                for name in ("harness/project_board_assets.py", "scripts/build_project_board_assets.py", "harness/project-board-native.json"))
            and digest(Path(__file__)) == digest(home / "runtime/harness/project_board_assets.py")
            and digest(Path(compiler.__file__)) == digest(home / "runtime/scripts/build_project_board_assets.py")
            and {name: digest(compiler.ROOT / "adapters/project-board" / name) for name in compiler.HOST_FILES} == source_inputs(home)
            and digest(compiler.ROOT / "harness/project-board-native.json") == digest(home / "runtime/harness/project-board-native.json"),
            "Installer board sources differ from the installed runtime; use reviewed source adoption")


def proposed_record(home):
    home, _output, manifest = paths(home)
    return {"schema": SCHEMA, "manifest": DIRECTORY + "/manifest.json", "sha256": digest(manifest),
            "builder_sha256": digest(home / "runtime/scripts/build_project_board_assets.py"),
            "policy_sha256": digest(home / "runtime/harness/project-board-native.json")}


def verify(home, record):
    """Verify existing recorded bytes only; never install, fetch or initialize."""
    home, output, manifest = paths(home)
    require(isinstance(record, dict) and set(record) == {"schema", "manifest", "sha256", "builder_sha256", "policy_sha256"},
            "Managed board UI record is missing or malformed")
    require(record.get("schema") == SCHEMA and record.get("manifest") == DIRECTORY + "/manifest.json",
            "Managed board UI record belongs to another path")
    require(all(isinstance(record.get(key), str) and re.fullmatch(r"[0-9a-f]{64}", record[key])
                for key in ("sha256", "builder_sha256", "policy_sha256")), "Managed board UI hashes are malformed")
    require(manifest.is_file() and not manifest.is_symlink() and manifest.stat().st_size <= 262144,
            "Managed board UI manifest is missing or incomplete; keep partial files for review")
    require(proposed_record(home) == record, "Managed board UI source or manifest changed; use reviewed maintenance")
    value = json.loads(manifest.read_text(encoding="utf-8"))
    policy = json.loads((home / "runtime/harness/project-board-native.json").read_text(encoding="utf-8"))
    require(isinstance(value, dict) and value.get("native_source_files") == policy["files"]
            and value.get("host_source_files") == source_inputs(home)
            and value.get("builder_sha256") == record["builder_sha256"],
            "Managed board UI does not match this runtime's build inputs")
    upstream = value.get("upstream_source", {})
    require(isinstance(upstream, dict) and upstream.get("commit") == policy["commit"]
            and upstream.get("tracked_source") == "clean"
            and isinstance(upstream.get("tree"), str) and re.fullmatch(r"[0-9a-f]{40}", upstream["tree"])
            and isinstance(upstream.get("license_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", upstream["license_sha256"])
            and upstream.get("untracked_exclusions") == ["/node_modules/", "/web/node_modules/", "/hermes_agent.egg-info/"],
            "Managed board UI lacks its pinned clean Git source generation")
    require(value.get("node_version") == "v22.23.2" and isinstance(value.get("node_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", value["node_sha256"]), "Managed board UI lacks its build runtime identity")
    from harness.project_board import asset_files
    asset_files(output, record["sha256"])
    return output, record["sha256"]


def resolve(home, config):
    record = config.get("installed", {}).get("hermes", {}).get("board_ui")
    require(record is not None, "Local board files are not installed. Finish this new home's installation with the reviewed source installer. "
            "An older installed package needs reviewed maintenance; it is not changed automatically.")
    return verify(home, record)


def preflight(home, config):
    """Refuse old records and unknown partial output before package effects."""
    home, output, manifest = paths(home)
    installed = config.get("installed", {}).get("hermes")
    if installed is not None:
        require(installed.get("board_ui") is not None,
                "Existing Hermes has no managed board UI record. Keep this home intact and use reviewed maintenance; "
                "this installer does not automatically migrate older package records.")
    matching_installer_source(home)
    if output.exists():
        require(output.is_dir() and manifest.is_file(), "Board UI build is incomplete; keep its partial files and inspect before repair")
        verify(home, installed["board_ui"] if installed else proposed_record(home))


def install(home, *, node, npm_cli, environment, run, lease):
    """Caller holds the existing home EX lease; children retain its actual fd."""
    home, output, _manifest = paths(home)
    require(getattr(lease, "mode", None) == "exclusive" and getattr(lease, "home", None) == home,
            "Board UI installation requires this home's exclusive phase")
    lifecycle_fds = lease.pass_fds
    require(lifecycle_fds, "Board UI installation requires a live child lease descriptor")
    inherited = home_entry.inherited_pass_fds(home, environ={home_entry.FD_ENV: str(lifecycle_fds[0])})
    require(tuple(lifecycle_fds) == inherited, "Board UI child lease differs from this home")
    matching_installer_source(home)
    policy = json.loads((home / "runtime/harness/project-board-native.json").read_text(encoding="utf-8"))
    upstream = home / "packages/hermes-source"
    identity = compiler.native_source_identity(upstream, policy["commit"])
    if output.exists():
        # A completed build can outlive an interrupted package-record save.
        # Partial or foreign output is retained and refused, never overwritten.
        require(output.is_dir() and (output / "manifest.json").is_file(),
                "Board UI build is incomplete; keep its partial files and inspect before repair")
        record = proposed_record(home)
        verify(home, record)
        manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
        require(manifest["upstream_source"] == identity, "Retained board build belongs to a different source generation")
        return record
    env = dict(environment, AGENT_HOME_LIFECYCLE_FD=str(lifecycle_fds[0]))
    env.pop("NODE_OPTIONS", None)
    env.pop("NODE_PATH", None)
    run([node, npm_cli, "--prefix", upstream, "ci", "--workspace", "web", "--include-workspace-root=false",
         "--include=dev", "--ignore-scripts", "--no-audit", "--no-fund", "--prefer-offline"],
        cwd=home, env=env, timeout=900, pass_fds=lifecycle_fds)
    compiler.build(upstream, node, output, pass_fds=lifecycle_fds, environment=env)
    record = proposed_record(home)
    verify(home, record)
    return record
