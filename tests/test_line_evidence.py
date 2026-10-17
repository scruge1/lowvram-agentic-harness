import hashlib
import unittest

from harness.line_evidence import resolve_numbered_line


def resolve(contents, number=19, start=19, **overrides):
    excerpt = "\n".join(str(start + i) + ": " + text
                        for i, text in enumerate(contents))
    args = {"excerpt": excerpt, "span": [start, start + len(contents) - 1],
            "line_number": number,
            "excerpt_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
            "content_sha256": hashlib.sha256("\n".join(contents).encode()).hexdigest()}
    args.update(overrides)
    return resolve_numbered_line(**args)


class LineEvidenceTests(unittest.TestCase):
    def test_complete_line_and_hashes_preserve_late_clause(self):
        content = "lookup failure; " + "detail " * 25 + "process absence is unproved."
        result = resolve([content, "handoff status=ready"], number=19)
        self.assertEqual(result["content"], content)
        self.assertGreater(len(result["numbered_line"]), 120)
        self.assertEqual(result["selected_content_sha256"],
                         hashlib.sha256(content.encode()).hexdigest())
        self.assertEqual(result["numbered_line_sha256"],
                         hashlib.sha256(("19: " + content).encode()).hexdigest())
        self.assertTrue(result["location_is_not_entailment"])

    def test_unicode_bytes_are_not_normalized(self):
        content = "café e\u0301 🙂"
        result = resolve([content])
        self.assertEqual(result["content"].encode(), content.encode())
        self.assertNotEqual(result["selected_content_sha256"],
                            hashlib.sha256("café é 🙂".encode()).hexdigest())

    def test_exact_contiguous_numbers_and_span(self):
        for excerpt in ("019: value", "20: value", "19: value\n19: duplicate",
                        "19: value\r\n20: next"):
            with self.subTest(excerpt=excerpt), self.assertRaises(ValueError):
                resolve(["value", "next"], excerpt=excerpt,
                        excerpt_sha256=hashlib.sha256(excerpt.encode()).hexdigest())
        with self.assertRaises(ValueError):
            resolve(["value"], span=[19, 20])

    def test_both_hashes_are_checked(self):
        for key in ("excerpt_sha256", "content_sha256"):
            for invalid in ("0" * 64, "A" * 64, "bad", True, None):
                with self.subTest(key=key, invalid=invalid), self.assertRaises(ValueError):
                    resolve(["value"], **{key: invalid})

    def test_line_selection_and_span_refuse_coercion(self):
        for number in (True, False, 19.0, "19", 18, 20, None):
            with self.subTest(number=number), self.assertRaises(ValueError):
                resolve(["value"], number=number)
        for span in ([True, 19], [19, False], [20, 19], [19], "19:19", [0, 0]):
            with self.subTest(span=span), self.assertRaises(ValueError):
                resolve(["value"], span=span)

    def test_blank_and_markdown_headings_refuse_literal_text_survives(self):
        for content in ("", "  ", "# Heading", "   ### Heading", "---", "==="):
            with self.subTest(content=content), self.assertRaises(ValueError):
                resolve([content])
        with self.assertRaises(ValueError):
            resolve(["Setext heading", "---"])
        for content in ("> # quoted text", "    # code text", "#literal"):
            self.assertEqual(resolve([content])["content"], content)

    def test_inclusive_utf8_and_line_count_limits(self):
        content = "é" * 3998  # Four prefix bytes + 7,996 content bytes.
        self.assertEqual(len(resolve([content])["numbered_line"].encode()), 8000)
        with self.assertRaises(ValueError):
            resolve([content + "x"])
        self.assertEqual(resolve(["value"] * 64, number=82)["line_number"], 82)
        with self.assertRaises(ValueError):
            resolve(["value"] * 65)

    def test_invalid_text_and_errors_do_not_echo_source(self):
        for invalid in (None, b"19: value", 12, "\ud800"):
            with self.subTest(invalid=repr(invalid)), self.assertRaises(ValueError):
                resolve(["value"], excerpt=invalid)
        with self.assertRaises(ValueError) as error:
            resolve(["DO_NOT_ECHO_SECRET"], content_sha256="0" * 64)
        self.assertNotIn("DO_NOT_ECHO_SECRET", str(error.exception))


if __name__ == "__main__":
    unittest.main()
