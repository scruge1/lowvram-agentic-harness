"""Select native protocol metadata without guessing a model's quality or fit."""
import json
from pathlib import Path
import tempfile
import unittest

from harness import home, model_profiles


class ModelProfileTests(unittest.TestCase):
    def test_qwen_format_is_explicit_and_returns_independent_metadata(self):
        generic = model_profiles.model_definition("any-name", 32768, 4096)
        qwen = model_profiles.model_definition("explicit-owner-model", 32768, 4096, "llama-cpp-qwen")
        self.assertNotIn("reasoning", generic)
        self.assertEqual(qwen["id"], "explicit-owner-model")
        self.assertTrue(qwen["reasoning"])
        self.assertEqual(qwen["compat"]["thinkingFormat"], "qwen-chat-template")
        qwen["compat"]["thinkingFormat"] = "changed"
        self.assertEqual(model_profiles.model_definition("x", 32768, 4096, "llama-cpp-qwen")["compat"]["thinkingFormat"],
                         "qwen-chat-template")

    def test_unknown_transport_profile_refuses_before_any_home_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "not-created"
            with self.assertRaisesRegex(home.HomeError, "Unknown model transport"):
                home.scaffold(target, profile="core", base_url="http://127.0.0.1:1/v1", model="qwen-but-no-guess",
                              model_profile="guessed-from-name", offline=True)
            self.assertFalse(target.exists())

    def test_selected_native_profile_is_in_normal_scaffold_and_keeps_off_default(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "Owned home"
            result = home.scaffold(target, profile="core", base_url="http://127.0.0.1:1/v1", model="owner-selected",
                                   model_profile="llama-cpp-qwen", context_window=32768, max_output=4096, offline=True)
            model = json.loads((target / "agent/models.json").read_text())["providers"]["local"]["models"][0]
            settings = json.loads((target / "agent/settings.json").read_text())
            self.assertEqual(model["compat"]["thinkingFormat"], "qwen-chat-template")
            self.assertEqual(model["contextWindow"], 32768)
            self.assertEqual(model["maxTokens"], 4096)
            self.assertEqual(settings["defaultThinkingLevel"], "off")
            self.assertEqual(result["model_profile"], "llama-cpp-qwen")
            self.assertEqual(result["model_capability_acceptance"], "not_probed")


if __name__ == "__main__":
    unittest.main()
