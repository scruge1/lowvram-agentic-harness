"""Contract disclosure checks use mocked transport; no model or network."""
import io
import json
import unittest
from unittest.mock import patch

from harness.llm import DEFAULTS, LocalLLM


def response():
    return io.BytesIO(b'{"choices":[{"message":{"content":"hold"}}]}')


class PromptDisclosureTests(unittest.TestCase):
    def setUp(self):
        self.model = LocalLLM(dict(DEFAULTS, model="fixture-model"))

    def test_missing_contract_refuses_before_transport(self):
        with patch("harness.llm.urllib.request.urlopen") as transport:
            with self.assertRaisesRegex(ValueError, "omit required contract text"):
                self.model.ask("Include both mandatory labels.",
                               required_prompt_literals=("scope_unknown", "runtime_unknown"))
            transport.assert_not_called()

    def test_sidecar_metadata_does_not_disclose_contract(self):
        messages = [{"role": "user", "content": "Review the supplied report.",
                     "metadata": {"required_labels": ["scope_unknown"]}}]
        with patch("harness.llm.urllib.request.urlopen") as transport:
            with self.assertRaises(ValueError):
                self.model.chat(messages, required_prompt_literals=["scope_unknown"])
            transport.assert_not_called()

    def test_actual_wire_messages_contain_required_literals(self):
        system = 'Required gap labels: ["scope_unknown", "runtime_unknown"].'
        with patch("harness.llm.urllib.request.urlopen", return_value=response()) as transport:
            self.assertEqual(self.model.ask("Review the report.", system=system,
                                           required_prompt_literals=("scope_unknown", "runtime_unknown")),
                             "hold")
            request = transport.call_args[0][0]
            body = json.loads(request.data)
            self.assertEqual(body["messages"], [{"role": "system", "content": system},
                                                {"role": "user", "content": "Review the report."}])
            self.assertNotIn("required_prompt_literals", body)
            self.assertEqual(body["model"], "fixture-model")

    def test_default_call_keeps_existing_payload(self):
        with patch("harness.llm.urllib.request.urlopen", return_value=response()) as transport:
            self.assertEqual(self.model.ask("Hello"), "hold")
            body = json.loads(transport.call_args[0][0].data)
            self.assertEqual(body, {"model": "fixture-model",
                                    "messages": [{"role": "user", "content": "Hello"}],
                                    "temperature": DEFAULTS["temperature"],
                                    "max_tokens": DEFAULTS["max_tokens"], "stream": False})

    def test_invalid_requirements_refuse_before_transport(self):
        with patch("harness.llm.urllib.request.urlopen") as transport:
            for invalid in (None, "scope_unknown", [""], [" "], [1]):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    self.model.ask("Hello", required_prompt_literals=invalid)
            transport.assert_not_called()

    def test_non_text_content_is_not_stringified_as_disclosure(self):
        with patch("harness.llm.urllib.request.urlopen") as transport:
            with self.assertRaises(ValueError):
                self.model.chat([{"role": "user", "content": {"scope_unknown": True}}],
                                required_prompt_literals=("scope_unknown",))
            transport.assert_not_called()

    def test_unicode_text_is_checked_after_json_serialization(self):
        with patch("harness.llm.urllib.request.urlopen", return_value=response()) as transport:
            self.assertEqual(self.model.ask("Required label: \u03b1_scope",
                                           required_prompt_literals=("\u03b1_scope",)), "hold")
            self.assertIn("\u03b1_scope", json.loads(transport.call_args[0][0].data)["messages"][0]["content"])

    def test_literal_cannot_be_assembled_across_messages(self):
        with patch("harness.llm.urllib.request.urlopen") as transport:
            with self.assertRaises(ValueError):
                self.model.chat([{"role": "system", "content": "scope_"},
                                 {"role": "user", "content": "unknown"}],
                                required_prompt_literals=("scope_\nunknown",))
            transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
