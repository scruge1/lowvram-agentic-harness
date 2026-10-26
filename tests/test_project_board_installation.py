"""Synthetic package-record boundaries; no npm, native UI or factory acceptance."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from harness import home, project_board_assets as assets


class BoardAssetRecordTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="board-asset-record-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve() / "home"
        self.config = home.scaffold(self.root, profile="core", base_url="http://127.0.0.1:1/v1",
                                    model="synthetic-no-model", offline=True)

    def synthetic_record(self):
        output = self.root / assets.DIRECTORY
        output.mkdir()
        (output / "index.html").write_text("<p>Synthetic record-boundary asset only</p>", encoding="utf-8")
        policy = json.loads((self.root / "runtime/harness/project-board-native.json").read_text(encoding="utf-8"))
        manifest = {"schema": "project-board-assets/v1", "hermes_commit": policy["commit"],
                    "native_source_files": policy["files"], "host_source_files": assets.source_inputs(self.root),
                    "builder_sha256": assets.digest(self.root / "runtime/scripts/build_project_board_assets.py"),
                    "upstream_source": {"commit": policy["commit"], "tree": "1" * 40, "tracked_source": "clean",
                                        "license_sha256": "3" * 64,
                                        "untracked_exclusions": ["/node_modules/", "/web/node_modules/", "/hermes_agent.egg-info/"]},
                    "node_version": "v22.23.2", "node_sha256": "2" * 64,
                    "files": {"index.html": assets.digest(output / "index.html")}}
        (output / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        record = assets.proposed_record(self.root)
        self.config["installed"]["hermes"] = {"board_ui": record}
        return output, record

    def test_record_path_asset_and_runtime_source_drift_refuse(self):
        output, record = self.synthetic_record()
        self.assertEqual(assets.resolve(self.root, self.config), (output, record["sha256"]))
        foreign = copy.deepcopy(record)
        foreign["manifest"] = "../foreign/manifest.json"
        with self.assertRaisesRegex(ValueError, "another path"):
            assets.verify(self.root, foreign)
        asset = output / "index.html"
        original = asset.read_bytes()
        asset.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            assets.verify(self.root, record)
        asset.write_bytes(original)
        source = self.root / "runtime/adapters/project-board/index.html"
        source.write_bytes(b"changed host source")
        with self.assertRaisesRegex(ValueError, "build inputs"):
            assets.verify(self.root, record)

    def test_legacy_record_and_partial_output_are_retained_before_installation(self):
        self.config["installed"]["hermes"] = {"artifacts": [], "acceptance": "synthetic legacy record"}
        with self.assertRaisesRegex(ValueError, "older package records"):
            assets.preflight(self.root, self.config)
        self.config["installed"].clear()
        output = self.root / assets.DIRECTORY
        output.mkdir()
        marker = output / "partial.txt"
        marker.write_text("retained partial fixture", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            assets.preflight(self.root, self.config)
        self.assertEqual(marker.read_text(encoding="utf-8"), "retained partial fixture")

    def test_shared_or_foreign_lease_cannot_start_package_effects(self):
        execute = Mock()
        for mode, selected in (("shared", self.root), ("exclusive", self.root.parent)):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "exclusive phase"):
                assets.install(self.root, node="not-called", npm_cli="not-called", environment={}, run=execute,
                               lease=SimpleNamespace(mode=mode, home=selected, pass_fds=()))
        execute.assert_not_called()

    def test_ui_build_failure_cannot_publish_an_installed_package(self):
        # Package commands are inert stubs. This checks the actual installer
        # transaction, not successful package installation or kernel admission.
        target = self.root.parent / "install fault"
        config = home.scaffold(target, profile="agent", base_url="http://127.0.0.1:1/v1",
                               model="synthetic-no-model", offline=True)
        before = (target / "home.json").read_bytes()
        python = home.executable(target / "envs/hermes")
        python.parent.mkdir(parents=True)
        python.write_text("Synthetic unused executable", encoding="utf-8")
        node, npm = target / "fixture-node", target / "fixture-npm"
        node.write_text("Synthetic unused Node", encoding="utf-8")
        npm.write_text("Synthetic unused npm", encoding="utf-8")
        def execute(command, **_kwargs):
            values = list(map(str, command))
            if "--version" in values:
                return "v22.23.2"
            if "-c" in values:
                return "3.12.13"
            if "rev-parse" in values:
                return home.GIT_SOURCES["hermes"][1]
            return "Synthetic package output"
        lease = SimpleNamespace(mode="exclusive", home=target, pass_fds=(999,))
        with patch.object(home.platform, "system", return_value="Linux"), \
                patch.object(home.shutil, "which", side_effect=lambda name: str(node if name == "node" else npm)), \
                patch.object(home, "run", side_effect=execute), \
                patch.object(assets, "install", side_effect=ValueError("synthetic UI build failed")), \
                patch.object(home, "package_artifacts") as fingerprint, patch.object(home, "save_status") as save:
            with self.assertRaisesRegex(ValueError, "UI build failed"):
                home._install_packages(target, config, only=("hermes",), finalize=False,
                                       lifecycle_fds=lease.pass_fds, lifecycle_lease=lease)
        fingerprint.assert_not_called()
        save.assert_not_called()
        self.assertNotIn("hermes", config["installed"])
        self.assertEqual((target / "home.json").read_bytes(), before)

    def test_npm_and_compiler_receive_the_same_bounded_child_environment(self):
        lease = SimpleNamespace(mode="exclusive", home=self.root, pass_fds=(999,))
        environment = {"HOME": "synthetic selected home", "NODE_OPTIONS": "--require unreviewed-preload",
                       "NODE_PATH": "unreviewed-module-path", "NODE_ENV": "production"}
        execute = Mock(return_value="Synthetic npm output")
        with patch.object(assets.home_entry, "inherited_pass_fds", return_value=(999,)), \
                patch.object(assets.compiler, "native_source_identity", return_value={}), \
                patch.object(assets.compiler, "build", side_effect=ValueError("synthetic compiler stop")) as build:
            with self.assertRaisesRegex(ValueError, "compiler stop"):
                assets.install(self.root, node="not-executed", npm_cli="not-executed", environment=environment,
                               run=execute, lease=lease)
        npm_environment = execute.call_args.kwargs["env"]
        self.assertIn("--include=dev", execute.call_args.args[0])
        self.assertEqual(npm_environment, build.call_args.kwargs["environment"])
        self.assertEqual(npm_environment["HOME"], environment["HOME"])
        self.assertEqual(npm_environment[assets.home_entry.FD_ENV], "999")
        self.assertNotIn("NODE_OPTIONS", npm_environment)
        self.assertNotIn("NODE_PATH", npm_environment)
        self.assertEqual(environment["NODE_OPTIONS"], "--require unreviewed-preload")


if __name__ == "__main__":
    unittest.main()
