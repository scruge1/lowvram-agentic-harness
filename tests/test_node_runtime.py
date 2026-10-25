"""Managed Node binding validation with explicit synthetic runtime receipts."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import bootstrap
from harness import node_runtime as runtime


class NodeRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name).resolve()
        self.home = self.directory / "owned-home"
        self.home.mkdir()
        self.root = Path(str(self.home) + "-runtimes")
        self.prefix = self.root / bootstrap.NODE_NAME
        self.node = self.prefix / "bin/node"
        self.npm = self.prefix / "lib/node_modules/npm/bin/npm-cli.js"
        self.library = self.prefix / "lib/node_modules/npm/package.json"
        self.python = self.root / "python" / bootstrap.PYTHON_KEY / "bin/python3.12"
        for file, body in ((self.node, b"synthetic Node binary"), (self.npm, b"synthetic npm CLI"),
                           (self.library, b'{"name":"synthetic-npm"}'), (self.python, b"synthetic base Python")):
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(body)
        self.marker = self.root / "bootstrap-owner"
        self.marker.write_text("agent-home-bootstrap/v1:" + str(self.home) + "\n")
        self.source = self.root / "runtime-receipt.json"
        self.value = {"schema": "agent-home-bootstrap/v1", "status": "runtimes_installed",
                      "home": str(self.home), "runtime_root": str(self.root),
                      "python": {"path": str(self.python), "sha256": bootstrap.sha256(self.python)},
                      "node": {"path": str(self.node), "version": bootstrap.NODE_VERSION,
                               "runtime_root": str(self.prefix), "sha256": bootstrap.sha256(self.node),
                               "files": bootstrap.inventory(self.prefix)}}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        self.source.write_text(json.dumps(self.value), encoding="utf-8")

    def binding(self):
        # These files are synthetic; no synthetic executable is ever started.
        with patch.object(runtime.sys, "executable", str(self.python)), patch.object(runtime.platform, "python_version", return_value="3.12.13"):
            return runtime.bind(self.home, self.node)

    def test_exact_owned_binding_and_receipt_are_retained(self):
        record = self.binding()
        self.assertIsNone(runtime.check(self.home, record))
        self.assertEqual(record["path"], str(self.node))
        self.assertEqual(record["runtime_root"], str(self.prefix))
        self.assertEqual(record["npm_cli"], str(self.npm))
        self.assertEqual(record["npm_cli_sha256"], bootstrap.sha256(self.npm))
        self.assertEqual(record["bootstrap_receipt_sha256"], bootstrap.sha256(self.source))

    def test_wrong_home_and_owner_marker_are_refused(self):
        record = self.binding()
        other = self.directory / "different-home"
        other.mkdir()
        self.assertIn("permanent bootstrap prefix", runtime.check(other, record))
        self.marker.write_text("agent-home-bootstrap/v1:" + str(other))
        self.assertIn("owner differs", runtime.check(self.home, record))

    def test_wrong_bootstrap_receipt_identity_is_refused(self):
        record = self.binding()
        original = copy.deepcopy(self.value)
        for field, value in (("home", str(self.directory)), ("runtime_root", str(self.directory)),
                             ("schema", "unrelated/v1"), ("status", "partial")):
            self.value = {**copy.deepcopy(original), field: value}
            self.save()
            self.assertIn("receipt identity differs", runtime.check(self.home, record))

    def test_receipt_byte_drift_refused_even_if_runtime_fields_match(self):
        record = self.binding()
        self.source.write_text(json.dumps(self.value, indent=2), encoding="utf-8")
        self.assertIn("receipt changed", runtime.check(self.home, record))

    def test_node_binary_drift_never_selects_ambient_node(self):
        record = self.binding()
        self.node.write_bytes(b"changed binary")
        with patch.dict(os.environ, {"PATH": str(self.directory / "ambient-node")}), patch.object(bootstrap, "command", side_effect=AssertionError("No fallback or probe is allowed")):
            self.assertIn("Node identity differs", runtime.check(self.home, record))

    def test_npm_cli_and_other_inventory_drift_are_refused(self):
        record = self.binding()
        for target in (self.npm, self.library):
            original = target.read_bytes()
            target.write_bytes(original + b" drift")
            self.assertIn("inventory changed", runtime.check(self.home, record))
            target.write_bytes(original)
        added = self.prefix / "extra.js"
        added.write_text("unexpected extra file")
        self.assertIn("inventory changed", runtime.check(self.home, record))
        added.unlink()
        self.library.unlink()
        self.assertIn("inventory changed", runtime.check(self.home, record))

    def test_missing_npm_is_refused_even_with_rewritten_inventory(self):
        record = self.binding()
        self.npm.unlink()
        self.value["node"]["files"] = bootstrap.inventory(self.prefix)
        self.save()
        self.assertIn("npm CLI is unavailable", runtime.check(self.home, record))

    def test_managed_base_python_hash_and_installer_interpreter_are_bound(self):
        record = self.binding()
        self.python.write_bytes(b"changed Python")
        self.assertIn("base Python drift", runtime.check(self.home, record))
        self.python.write_bytes(b"synthetic base Python")
        with patch.object(runtime.sys, "executable", str(self.directory / "other-python")), patch.object(runtime.platform, "python_version", return_value="3.12.13"):
            with self.assertRaisesRegex(runtime.NodeRuntimeError, "exact managed Python"):
                runtime.bind(self.home, self.node)
        with patch.object(runtime.sys, "executable", str(self.python)), patch.object(runtime.platform, "python_version", return_value="3.12.3"):
            with self.assertRaisesRegex(runtime.NodeRuntimeError, "exact managed Python"):
                runtime.bind(self.home, self.node)

    def test_mutated_binding_or_extra_fields_have_no_ambient_fallback(self):
        record = self.binding()
        for field, value in (("path", str(self.directory / "ambient-node")), ("sha256", "0" * 64),
                             ("version", "24.0.0"), ("npm_cli", "/ambient/npm"), ("unexpected", "ignored?")):
            self.assertIsNotNone(runtime.check(self.home, {**record, field: value}))
        for invalid in (None, [], {}, "node"):
            self.assertIsNotNone(runtime.check(self.home, invalid))

    def test_invalid_missing_and_oversized_receipts_fail_closed(self):
        record = self.binding()
        self.source.write_text("not JSON")
        self.assertIsNotNone(runtime.check(self.home, record))
        self.source.write_bytes(b" " * (8 * 1024 * 1024 + 1))
        self.assertIn("bounded native bootstrap", runtime.check(self.home, record))
        self.source.unlink()
        self.assertIn("bounded native bootstrap", runtime.check(self.home, record))

    def test_valid_json_with_wrong_object_shapes_returns_doctor_failure(self):
        record = self.binding()
        for label, malformed in (("list-root", []), ("null-root", None), ("string-root", "receipt"),
                                 ("null-node", {**self.value, "node": None}), ("list-node", {**self.value, "node": []}),
                                 ("null-python", {**self.value, "python": None})):
            with self.subTest(shape=label):
                self.source.write_text(json.dumps(malformed), encoding="utf-8")
                self.assertIsNotNone(runtime.check(self.home, record))

    @unittest.skipIf(os.name == "nt", "Symlink controls need no elevated Windows privilege on Linux")
    def test_symlinked_binary_and_receipt_are_refused(self):
        record = self.binding()
        actual = self.prefix / "bin/real-node"
        self.node.rename(actual)
        self.node.symlink_to(actual)
        self.assertIn("canonical owned Node", runtime.check(self.home, record))
        self.node.unlink()
        actual.rename(self.node)
        alternate = self.root / "alternate-receipt.json"
        self.source.rename(alternate)
        self.source.symlink_to(alternate)
        self.assertIn("bounded native bootstrap", runtime.check(self.home, record))


if __name__ == "__main__":
    unittest.main()
