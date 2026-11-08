"""Read-only source parity comparison; refuses unsafe and partial inventories."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from scripts import pi_source_parity as parity


class ParityAuditTests(unittest.TestCase):
    @staticmethod
    def _mapping(root, records):
        file = root / "parity-map.json"
        file.write_text(json.dumps({"schema": parity.MAP_SCHEMA, "components": records}))
        return file

    @staticmethod
    def _fixture(a, b, content_a="same", content_b="same"):
        a.mkdir()
        b.mkdir()
        (a / "adapter.ts").write_text(content_a)
        (b / "installed.ts").write_text(content_b)
        return [{"id": "intake", "public": "adapter.ts", "installed": "installed.ts"}]

    def test_byte_identity_only_and_no_paths_or_source_content(self):
        with TemporaryDirectory() as base:
            root = Path(base)
            a, b = root / "public", root / "installed"
            records = self._fixture(a, b, "DO_NOT_EXPOSE_PRIVATE_CONTENT", "DO_NOT_EXPOSE_PRIVATE_CONTENT")
            before = (a / "adapter.ts").stat().st_mtime_ns
            result = parity.audit(a, b, self._mapping(root, records))
            self.assertEqual(result["status"], "byte_identical")
            self.assertEqual(result["counts"]["byte_identical"], 1)
            self.assertEqual(result["component_count"], 1)
            self.assertFalse(result["components"][0]["automatic_sync_allowed"])
            self.assertFalse(result["components"][0]["semantic_equivalence_verified"])
            self.assertEqual(result["components"][0]["installed"]["sha256"],
                             hashlib.sha256(b"DO_NOT_EXPOSE_PRIVATE_CONTENT").hexdigest())
            display = json.dumps(result)
            self.assertNotIn(str(b), display)
            self.assertNotIn("DO_NOT_EXPOSE_PRIVATE_CONTENT", display)
            self.assertNotIn("installed.ts", display)
            self.assertEqual((a / "adapter.ts").stat().st_mtime_ns, before)

    def test_source_change_requires_review_and_strict_exit_two(self):
        with TemporaryDirectory() as base:
            root = Path(base)
            a, b = root / "public", root / "installed"
            records = self._fixture(a, b, "public source", "private candidate")
            mapping = self._mapping(root, records)
            value = parity.audit(a, b, mapping)
            self.assertEqual(value["status"], "review_required")
            self.assertEqual(value["components"][0]["state"], "needs_review")
            stream = StringIO()
            with redirect_stdout(stream):
                code = parity.main(["--public-root", str(a), "--installed-root", str(b),
                                    "--mapping", str(mapping), "--strict-drift"])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(stream.getvalue())["status"], "review_required")

    def test_missing_sources_are_not_treated_as_identical(self):
        with TemporaryDirectory() as base:
            root = Path(base)
            a, b = root / "public", root / "installed"
            self._fixture(a, b)
            records = [
                {"id": "missing-left", "public": "absent.ts", "installed": "installed.ts"},
                {"id": "missing-right", "public": "adapter.ts", "installed": "absent.ts"},
                {"id": "missing-both", "public": "nowhere.ts", "installed": "no-file.ts"},
            ]
            value = parity.audit(a, b, self._mapping(root, records))
            self.assertEqual(value["status"], "review_required")
            self.assertEqual({x["state"] for x in value["components"]},
                             {"missing_public", "missing_installed", "missing_both"})
            self.assertEqual(value["counts"]["byte_identical"], 0)

    def test_rejects_unsafe_paths_and_duplicate_mapping(self):
        with TemporaryDirectory() as base:
            root = Path(base)
            a, b = root / "public", root / "installed"
            self._fixture(a, b)
            records = [{"id": "one", "public": "adapter.ts", "installed": "installed.ts"}]
            for bad in ("../outside.ts", "/etc/shadow", r"C:\Windows\file", "x//file.ts",
                        "x/./file.ts", "x/../file.ts", "x\nfile.ts", ""):
                with self.subTest(bad=bad):
                    changed = [dict(records[0], public=bad)]
                    with self.assertRaises(parity.ParityError):
                        parity.audit(a, b, self._mapping(root, changed))
            for entry in (
                [dict(records[0]), dict(records[0])],
                [dict(records[0]), {"id": "other", "public": "adapter.ts", "installed": "else.ts"}],
                [dict(records[0]), {"id": "other", "public": "different.ts", "installed": "installed.ts"}],
                [{"id": "Bad ID", "public": "adapter.ts", "installed": "installed.ts"}],
                [],
            ):
                with self.subTest(entry=entry), self.assertRaises(parity.ParityError):
                    parity.audit(a, b, self._mapping(root, entry))

    def test_rejects_oversized_map_invalid_schema_and_fields(self):
        with TemporaryDirectory() as base:
            root = Path(base)
            a, b = root / "public", root / "installed"
            records = self._fixture(a, b)
            mapping = self._mapping(root, records)
            for object_ in (
                {"schema": "unknown", "components": records},
                {"schema": parity.MAP_SCHEMA, "components": records, "extra": 123},
                {"schema": parity.MAP_SCHEMA, "components": [{"id": "one"}]},
            ):
                mapping.write_text(json.dumps(object_))
                with self.assertRaises(parity.ParityError):
                    parity.audit(a, b, mapping)
            mapping.write_text("x" * (parity.MAX_MAP_BYTES + 1))
            with self.assertRaises(parity.ParityError):
                parity.audit(a, b, mapping)

    def test_oversized_mapped_file_refuses_without_content_disclosure(self):
        with TemporaryDirectory() as base:
            root = Path(base)
            a, b = root / "public", root / "installed"
            records = self._fixture(a, b)
            with (b / "installed.ts").open("wb") as stream:
                stream.truncate(parity.MAX_SOURCE_BYTES + 1)
            with self.assertRaises(parity.ParityError):
                parity.audit(a, b, self._mapping(root, records))

    def test_symlink_escape_denied_without_traversal(self):
        with TemporaryDirectory() as base:
            root = Path(base)
            a, b, foreign = root / "public", root / "installed", root / "foreign"
            self._fixture(a, b)
            foreign.mkdir()
            (foreign / "secret.ts").write_text("Never read this file")
            link = b / "foreign"
            try:
                link.symlink_to(foreign, target_is_directory=True)
            except (NotImplementedError, OSError):
                self.skipTest("Symlink privileges unavailable on this host")
            mapping = self._mapping(root, [
                {"id": "foreign", "public": "adapter.ts", "installed": "foreign/secret.ts"}])
            with self.assertRaises(parity.ParityError):
                parity.audit(a, b, mapping)
            with self.assertRaises(parity.ParityError):
                parity.audit(a, link, self._mapping(root, [
                    {"id": "foreign", "public": "adapter.ts", "installed": "secret.ts"}]))

    def test_matching_roots_cannot_create_false_parity(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "same.ts").write_text("same")
            mapping = self._mapping(root, [
                {"id": "same", "public": "same.ts", "installed": "same.ts"}])
            with self.assertRaises(parity.ParityError):
                parity.audit(root, root, mapping)

    def test_cli_invalid_source_is_nonzero_and_redacted(self):
        with TemporaryDirectory() as base:
            root = Path(base)
            a = root / "public"
            a.mkdir()
            mapping = root / "bad-map.json"
            mapping.write_text("not json")
            out = StringIO()
            with redirect_stdout(out):
                code = parity.main(["--public-root", str(a), "--installed-root", str(root),
                                    "--mapping", str(mapping)])
            self.assertEqual(code, 1)
            result = json.loads(out.getvalue())
            self.assertEqual(result["status"], "invalid")
            self.assertEqual(result["authority"], "none")
            self.assertNotIn(str(root), out.getvalue())


if __name__ == "__main__":
    unittest.main()
