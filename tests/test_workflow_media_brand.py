"""Portable asset and truth-boundary checks for the STUAIM-branded example."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs/media/stuaim"
MANIFEST = ASSETS / "SOURCE-MANIFEST.json"


class BrandedMediaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.record = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_assets_are_pinned_and_no_font_files_are_published(self):
        record = self.record
        self.assertEqual(record["schema"], "stuaim-public-visual-review/v1")
        self.assertEqual(record["status"], "design_review_not_desktop_release")
        self.assertFalse(record["live_model_used"])
        self.assertFalse(record["desktop_ui_captured"])
        self.assertTrue(record["no_font_binaries_distributed"])
        self.assertEqual(len(record["assets"]), 13)
        self.assertFalse(list(ASSETS.rglob("*.ttf")))
        self.assertFalse(list(ASSETS.rglob("*.otf")))
        for path, pinned in record["assets"].items():
            with self.subTest(path=path):
                self.assertFalse(Path(path).is_absolute())
                raw = (ROOT / path).read_bytes()
                self.assertEqual(pinned["sha256"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(pinned["size_bytes"], len(raw))

    def test_animated_readme_preview_and_mp4_are_actual_media(self):
        gif = (ROOT / "docs/media/stuaim-workflow-preview.gif").read_bytes()
        video = (ROOT / "docs/media/source-backed-workflow.mp4").read_bytes()
        self.assertEqual(gif[:6], b"GIF89a")
        self.assertEqual(struct.unpack("<HH", gif[6:10]), (800, 450))
        self.assertLess(len(gif), 2_000_000)
        self.assertGreaterEqual(gif.count(b"\x21\xf9\x04"), 90)
        self.assertEqual(video[4:8], b"ftyp")
        self.assertLess(len(video), 4_000_000)
        self.assertEqual(self.record["video"]["frames"], 528)
        self.assertEqual(self.record["video"]["duration_seconds"], 22.0)
        self.assertEqual(self.record["inline_gif"]["frames"], 102)

    def test_brand_geometry_and_readme_copy(self):
        self.assertEqual(
            self.record["flat_banner_geometry"],
            {
                "columns": 40,
                "rows": 12,
                "left_knots": 240,
                "right_knots": 240,
                "projection": "orthographic_2d",
            },
        )
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("stuaim-horizontal-dark.png", readme)
        self.assertIn("stuaim-horizontal-light.png", readme)
        self.assertIn("stuaim-workflow-preview.gif", readme)
        self.assertIn("STUAIM desktop interface is still being developed", readme)
        self.assertIn("scripted worker", readme)
        self.assertIn(
            "controller then set the local project status to `tested`", readme
        )
        for slogan in (
            "Only evidence can complete it",
            "A passing command is not proof",
            "The check found the truth",
            "The agent said it was done",
            "Not just chat",
            "actual work",
        ):
            self.assertNotIn(slogan, readme)

    def test_renderer_draws_illustration_not_fake_desktop(self):
        render = (ROOT / "examples/media/source-backed-workflow/render.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("stuaim-horizontal-dark.png", render)
        self.assertIn('"ILLUSTRATED REPLAY"', render)
        self.assertIn("Scripted fixture. No local LLM used.", render)
        for original in (
            "The verification problem",
            "A passing command is not proof",
            "Only evidence can",
            "The check found the truth",
        ):
            self.assertNotIn(original, render)
        self.assertNotIn("E:\\AgentData", render)
        self.assertNotIn("/home/adam", render)


if __name__ == "__main__":
    unittest.main()
