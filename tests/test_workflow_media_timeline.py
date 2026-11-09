"""Static moving-scene gate: prevent a regress to overlapping headings.

The first full video review exposed four overlapped text handoffs. This test
parses the optional renderer source without importing Pillow in core CI.
"""

from __future__ import annotations

import ast
from pathlib import Path
import unittest


SOURCE = (
    Path(__file__).resolve().parents[1]
    / "examples/media/source-backed-workflow/render.py"
)


def scene_windows():
    parsed = ast.parse(SOURCE.read_text(encoding="utf-8"))
    frame = next(
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef) and node.name == "frame"
    )
    scenes = next(
        node.value
        for node in ast.walk(frame)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "scenes" for t in node.targets)
    )
    if not isinstance(scenes, ast.List):
        raise ValueError("Scene windows must remain a literal reviewed list")
    return [
        (float(ast.literal_eval(row.elts[0])), float(ast.literal_eval(row.elts[1])))
        for row in scenes.elts
    ]


def no_text_overlap(windows):
    return all(a < b for a, b in windows) and all(
        first_end <= second_start
        for (_, first_end), (second_start, _) in zip(windows, windows[1:])
    )


class VideoTimelineGate(unittest.TestCase):
    def test_five_scenes_have_no_simultaneous_text_painting(self):
        windows = scene_windows()
        self.assertEqual(len(windows), 5)
        self.assertEqual(windows[0][0], 0)
        self.assertGreater(windows[-1][1], 22)
        self.assertLess(windows[-1][1], 22.25)
        self.assertTrue(no_text_overlap(windows))

    def test_negative_control_detects_original_headline_collision(self):
        windows = scene_windows()
        corrupted = list(windows)
        corrupted[1] = (windows[0][1] - 0.9, windows[1][1])
        self.assertFalse(no_text_overlap(corrupted))


if __name__ == "__main__":
    unittest.main()
