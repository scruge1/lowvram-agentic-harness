import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness.source_snapshot import pinned_snapshot, stable_snapshot


class SourceSnapshotTests(unittest.TestCase):
    def setUp(self):
        parent = Path(__file__).resolve().parent
        self.temporary = tempfile.TemporaryDirectory(prefix="snapshot-", dir=parent)
        self.directory = Path(self.temporary.name).resolve()
        # Verify the exact target before registering recursive temporary cleanup.
        self.assertEqual(self.directory.parent, parent)
        self.addCleanup(self.temporary.cleanup)
        self.path = self.directory / "source.md"
        self.path.write_bytes(b"# Project\n\n## Current\nReady.\n")

    def test_real_snapshot_after_atomic_publication(self):
        staged = self.directory / "staged.md"
        source = b"# Project\n\n## Current\nPublished.\n"
        staged.write_bytes(source)
        os.replace(staged, self.path)
        result = stable_snapshot(self.path, len(source))
        self.assertEqual(result["source"], source)
        self.assertEqual(result["source_bytes"], len(source))
        self.assertEqual(result["source_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual(len(result["source_stamp"]), 7)

    def test_byte_limits_and_empty_source(self):
        with self.assertRaises(ValueError):
            stable_snapshot(self.path, self.path.stat().st_size - 1)
        self.path.write_bytes(b"")
        with self.assertRaises(ValueError):
            stable_snapshot(self.path)
        for limit in (0, -1, True, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                stable_snapshot(self.path, limit)

    def test_replacement_file_on_second_open_is_refused(self):
        replacement = self.directory / "replacement.md"
        replacement.write_bytes(self.path.read_bytes())
        opening = os.open
        calls = []

        def changed_open(path, flags):
            calls.append(path)
            if len(calls) == 2:
                # Model the name resolving to another real file. Windows may
                # deny renaming an open file before the metadata check runs.
                return opening(replacement, flags)
            return opening(path, flags)

        with patch("harness.source_snapshot.os.open", side_effect=changed_open):
            with self.assertRaises(ValueError):
                stable_snapshot(self.path)

    def test_in_place_metadata_drift_is_refused(self):
        reading = os.read
        changed = []

        def changed_read(descriptor, count):
            result = reading(descriptor, count)
            if not changed:
                previous = self.path.stat()
                os.utime(self.path, ns=(previous.st_atime_ns,
                                       previous.st_mtime_ns + 10000000000))
                changed.append(True)
            return result

        with patch("harness.source_snapshot.os.read", side_effect=changed_read):
            with self.assertRaises(ValueError):
                stable_snapshot(self.path)

    def test_failed_named_fstat_closes_both_descriptors(self):
        opening, fstat, closing = os.open, os.fstat, os.close
        opened, closed, stats = [], [], []

        def tracked_open(path, flags):
            descriptor = opening(path, flags)
            opened.append(descriptor)
            return descriptor

        def failed_stat(descriptor):
            stats.append(descriptor)
            if len(stats) == 3:
                raise OSError("Injected named-handle failure")
            return fstat(descriptor)

        def tracked_close(descriptor):
            closed.append(descriptor)
            closing(descriptor)

        with patch("harness.source_snapshot.os.open", side_effect=tracked_open), \
                patch("harness.source_snapshot.os.fstat", side_effect=failed_stat), \
                patch("harness.source_snapshot.os.close", side_effect=tracked_close):
            with self.assertRaises(OSError):
                stable_snapshot(self.path)
        self.assertEqual(closed, list(reversed(opened)))
        for descriptor in opened:
            with self.assertRaises(OSError):
                os.fstat(descriptor)

    def test_hardlinked_source_is_refused(self):
        alias = self.directory / "hardlink.md"
        try:
            os.link(self.path, alias)
        except OSError as error:
            self.skipTest("Hard links unavailable: " + type(error).__name__)
        with self.assertRaises(ValueError):
            stable_snapshot(self.path)

    def test_relative_source_is_refused(self):
        with self.assertRaises(ValueError):
            stable_snapshot(Path("source.md"))

    def test_real_large_pin_requires_an_explicit_sufficient_budget(self):
        source = b"public test bytes\n" * 40000
        self.path.write_bytes(source)
        digest = hashlib.sha256(source).hexdigest()
        with self.assertRaises(ValueError):
            stable_snapshot(self.path)
        result = pinned_snapshot(self.path, len(source), digest,
                                 max_bytes=len(source))
        self.assertEqual(result["source"], source)
        self.assertEqual(result["source_sha256"], digest)

    def test_declared_pin_over_budget_refuses_before_open(self):
        with patch("harness.source_snapshot.os.open") as opening:
            with self.assertRaises(ValueError):
                pinned_snapshot(self.path, 1025, "a" * 64, max_bytes=1024)
        opening.assert_not_called()

    def test_wrong_size_or_hash_pin_is_refused(self):
        source = self.path.read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        for size, expected in ((len(source) + 1, digest),
                               (len(source), "0" * 64)):
            with self.subTest(size=size, digest=expected), self.assertRaises(ValueError):
                pinned_snapshot(self.path, size, expected,
                                max_bytes=len(source) + 1)

    def test_invalid_pin_or_budget_refuses_before_open(self):
        cases = ((True, "a" * 64, 10), (1, "A" * 64, 10),
                 (1, "g" * 64, 10), (1, "a" * 63, 10),
                 (1, None, 10), (1, "a" * 64, True),
                 (0, "a" * 64, 10), (1, "a" * 64, 0))
        with patch("harness.source_snapshot.os.open") as opening:
            for size, digest, budget in cases:
                with self.subTest(size=size, digest=digest, budget=budget), \
                        self.assertRaises(ValueError):
                    pinned_snapshot(self.path, size, digest, max_bytes=budget)
        opening.assert_not_called()


if __name__ == "__main__":
    unittest.main()
