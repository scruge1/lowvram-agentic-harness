"""No-model, no-GPU portable inventory acceptance/negative controls."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock
import json
import unittest

from harness import model_inventory as inventory

UUID_A = "GPU-00000000-1111-2222-3333-000000000001"
UUID_B = "GPU-00000000-1111-2222-3333-000000000002"
GPU_DATA = (
    f"0, {UUID_A}, NVIDIA RTX Sample A, 24576, 12288, 12288\n"
    f"3, {UUID_B}, NVIDIA RTX Sample B, 24576, 8000, 16576\n"
)


def model(root: Path, name: str, n: int = 5):
    file = root / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(b"x" * n)
    return file


class ModelInventoryTests(unittest.TestCase):
    def test_directory_scan_groups_complete_shards_without_opening_model(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            model(root, "a-00001-of-00003.gguf", 12)
            model(root, "a-00002-of-00003.gguf", 13)
            model(root, "a-00003-of-00003.gguf", 14)
            model(root, "sub/B.GGUF", 40)
            model(root, "sub/mmproj-B.gguf", 70)
            model(root, "sub/ignored.txt", 120)
            result = inventory.discover_gguf([root])
            self.assertEqual(result["status"], "observed")
            self.assertEqual(result["model_roots_supplied"], 1)
            self.assertEqual(len(result["assets"]), 2)
            self.assertTrue(all(not a["runnable"] for a in result["assets"]))
            entries = {a["name"]: a for a in result["assets"]}
            self.assertEqual(entries["a"]["state"], "installed_unqualified")
            self.assertEqual(entries["a"]["size_bytes"], 39)
            self.assertEqual(entries["a"]["listed_shards"], 3)
            self.assertEqual(len(entries["a"]["paths"]), 3)
            self.assertEqual(entries["B"]["size_bytes"], 40)
            self.assertTrue(all(not p.startswith(str(root)) for a in result["assets"] for p in a["paths"]))
            self.assertTrue(all(len(a["source_stat_sha256"]) == 64 for a in result["assets"]))

    def test_missing_second_shard_is_not_presented_as_runnable(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            model(root, "partial-00001-of-00004.gguf", 5)
            model(root, "partial-00004-of-00004.gguf", 8)
            item = inventory.discover_gguf([root])["assets"][0]
            self.assertEqual(item["state"], "incomplete_shards")
            self.assertEqual(item["listed_shards"], 2)
            self.assertEqual(item["expected_shards"], 4)
            self.assertEqual(item["paths"], [])
            self.assertFalse(item["runnable"])

    def test_source_stat_change_changes_observation_identity(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            path = model(root, "change.gguf")
            before = inventory.discover_gguf([root])["assets"][0]
            path.write_bytes(b"changed fake fixture")
            after = inventory.discover_gguf([root])["assets"][0]
            self.assertNotEqual(before["id"], after["id"])
            self.assertNotEqual(before["source_stat_sha256"], after["source_stat_sha256"])
            self.assertEqual(after["execution_authority"], "none")

    def test_directory_depth_and_hidden_roots_are_bounded(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            model(root, ".hidden/inside.gguf")
            model(root, "one/two/three/deep.gguf")
            model(root, "one/top.gguf")
            result = inventory.discover_gguf([root], max_depth=1)
            self.assertEqual([a["name"] for a in result["assets"]], ["top"])

    def test_input_bounds_fail_closed_before_returning_partial_catalogues(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            for idx in range(5):
                model(root, f"weights-{idx}.gguf")
            for kwargs in ({"max_files": 3}, {"max_assets": 2}, {"max_depth": 8},
                           {"max_files": 0}, {"max_seconds": 0}):
                with self.subTest(kwargs=kwargs), self.assertRaises(inventory.InventoryError):
                    inventory.discover_gguf([root], **kwargs)
            with self.assertRaises(inventory.InventoryError):
                inventory.discover_gguf([])
            with self.assertRaises(inventory.InventoryError):
                inventory.discover_gguf([root, root])
            with self.assertRaises(inventory.InventoryError):
                inventory.discover_gguf([root / "missing"])

    def test_time_budget_cannot_claim_a_partial_success(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            model(root, "one.gguf")
            ticks = iter([0, 1.1, 1.2])
            with self.assertRaises(inventory.InventoryError):
                inventory.discover_gguf([root], max_seconds=1, clock=lambda: next(ticks))

    def test_file_symlinks_outside_root_do_not_get_inventoried(self):
        with TemporaryDirectory() as r1, TemporaryDirectory() as r2:
            root, outside = Path(r1), Path(r2)
            target = model(outside, "outside.gguf")
            try:
                (root / "shortcut.gguf").symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable without Windows privileges")
            result = inventory.discover_gguf([root])
            self.assertEqual(result["assets"], [])
            self.assertIn("symlink_asset_ignored", result["warnings"])

    def test_directory_symlinks_are_never_walked(self):
        with TemporaryDirectory() as r1, TemporaryDirectory() as r2:
            root, outside = Path(r1), Path(r2)
            model(outside, "foreign.gguf")
            try:
                (root / "foreign-dir").symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Symlinks unavailable without Windows privileges")
            result = inventory.discover_gguf([root])
            self.assertEqual(result["assets"], [])
            with self.assertRaises(inventory.InventoryError):
                inventory.discover_gguf([root / "foreign-dir"])

    def test_gpu_inventory_output_is_bounded(self):
        oversized = GPU_DATA * 70
        with self.assertRaises(inventory.InventoryError):
            inventory.parse_gpu_inventory(oversized)
        with self.assertRaises(inventory.InventoryError):
            inventory.parse_gpu_inventory("x" * 128001)

    def test_misleading_mismatched_shard_names_do_not_complete(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            model(root, "a-00001-of-00002.gguf")
            model(root, "a-00002-of-00003.gguf")
            states = [entry["state"] for entry in inventory.discover_gguf([root])["assets"]]
            self.assertEqual(states, ["incomplete_shards", "incomplete_shards"])

    def test_incomplete_bad_shard_ordinal_is_ignored(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            model(root, "broken-00000-of-00003.gguf")
            result = inventory.discover_gguf([root])
            self.assertEqual(result["assets"], [])
            self.assertIn("invalid_shard_number", result["warnings"])

    def test_gpu_inventory_observes_all_cards_without_claiming_ownership(self):
        cards = inventory.parse_gpu_inventory(GPU_DATA)
        self.assertEqual([d["index"] for d in cards], [0, 3])
        self.assertEqual(len(cards), 2)
        self.assertTrue(all(d["process_owner"] == "unknown" for d in cards))
        self.assertTrue(all(d["available_for_tasks"] == "not_established" for d in cards))

    def test_gpu_identity_or_measurement_ambiguity_fails_entire_view(self):
        cases = [
            "", "0, missing, Test, 24576, 1, 24575",
            GPU_DATA.replace(UUID_B, UUID_A),
            GPU_DATA.replace("3, " + UUID_B, "0, " + UUID_B),
            GPU_DATA.replace("8000, 16576", "8000, 17000"),
            GPU_DATA.replace("8000, 16576", "negative, 16576"),
            GPU_DATA.replace("3, " + UUID_B, "3, bogus"),
        ]
        for body in cases:
            with self.subTest(body=body[:50]), self.assertRaises(inventory.InventoryError):
                inventory.parse_gpu_inventory(body)

    def test_gpu_process_is_read_only_and_unknown_on_error(self):
        received = []
        def command(argv, **kwargs):
            received.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout=GPU_DATA)
        result = inventory.gpu_inventory(run=command)
        self.assertEqual(result["status"], "observed")
        self.assertFalse(result["safe_to_allocate"])
        self.assertEqual(len(result["devices"]), 2)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0][1], "--query-gpu=index,uuid,name,memory.total,memory.used,memory.free")
        self.assertTrue(received[0][1]["capture_output"])
        def bad(_argv, **_kwargs):
            raise OSError("NVIDIA runtime absent")
        self.assertEqual(inventory.gpu_inventory(run=bad)["status"], "unavailable")
        self.assertEqual(inventory.gpu_inventory(run=bad)["devices"], [])

    def test_cli_does_not_probe_gpu_when_opted_out(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            model(root, "synthetic.gguf")
            output = StringIO()
            with mock.patch.object(inventory, "gpu_inventory", side_effect=AssertionError("Must not probe")):
                with redirect_stdout(output):
                    code = inventory.main(["--root", str(root), "--no-gpu-probe"])
            self.assertEqual(code, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["gpu"]["status"], "not_requested")
            self.assertEqual(len(payload["assets"]), 1)
            self.assertEqual(payload["authority"], "none")


if __name__ == "__main__":
    unittest.main()
