"""Verify local-only observer configuration before worker dispatch."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import claude_memory, home


class ClaudeMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "home"
        self.config = home.scaffold(self.root, profile="core", base_url="http://127.0.0.1:8080/v1", model="test", offline=True)

    def test_complete_provider_and_private_worker_root(self):
        root, config = claude_memory.settings(self.root, self.config)
        self.assertEqual(root, self.root / "memory/claude-mem")
        self.assertEqual(config["CLAUDE_MEM_PROVIDER"], "openai-compatible")
        self.assertEqual(config["CLAUDE_MEM_QUOTA_FALLBACK_PROVIDER"], "")
        self.assertEqual(config["CLAUDE_MEM_CHROMA_ENABLED"], "false")
        self.assertEqual(config["CLAUDE_MEM_TRANSCRIPTS_ENABLED"], "false")

    def test_incomplete_or_cloud_fallback_configuration_never_dispatches(self):
        file = self.root / "memory/claude-mem/settings.json"
        value = json.loads(file.read_text())
        value["CLAUDE_MEM_OPENAI_COMPAT_MODEL"] = ""
        value["CLAUDE_MEM_QUOTA_FALLBACK_PROVIDER"] = "claude"
        file.write_text(json.dumps(value))
        with patch.object(claude_memory.platform, "system", return_value="Linux"), patch.object(claude_memory, "worker_paths") as workers:
            with self.assertRaises(home.HomeError):
                claude_memory.invoke(self.root, "start")
            workers.assert_not_called()

    def test_sensitive_search_abstains_before_any_worker_or_store_read(self):
        with patch.object(claude_memory.platform, "system", return_value="Linux"), patch.object(claude_memory, "settings") as settings:
            result = claude_memory.invoke(self.root, "search", event="old API key")
            self.assertEqual(result["reason"], "sensitive_query")
            settings.assert_not_called()

    def test_responding_foreign_port_is_not_worker_ownership(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self, _): return b'{"pid":123,"version":"13.29.0"}'
        root, _ = claude_memory.settings(self.root, self.config)
        with patch.object(claude_memory, "urlopen", return_value=Response()):
            with self.assertRaisesRegex(home.HomeError, "owned worker identity"):
                claude_memory.health(self.root, root, self.config, self.root / "worker.cjs")


if __name__ == "__main__":
    unittest.main()
