import hashlib
import unittest

from harness.source_read import complete_section


class CompleteSectionTests(unittest.TestCase):
    def test_complete_section_excludes_other_sections_and_binds_source(self):
        body = b"## Current\nMeasured state.\n### Next action\nRead the owner record.\n\n"
        source = b"# Project\n\n" + body + b"## History\nOlder private notes.\n"
        result = complete_section(source, "Current")
        self.assertEqual(result["body"], body)
        self.assertEqual(result["body_sha256"], hashlib.sha256(body).hexdigest())
        self.assertEqual(result["source_sha256"], hashlib.sha256(source).hexdigest())
        self.assertEqual((result["start_line"], result["end_line"]), (3, 7))
        self.assertTrue(result["section_complete"])
        self.assertFalse(result["full_source_in_body"])

    def test_one_byte_over_budget_refuses_instead_of_returning_a_prefix(self):
        source = b"## Current\nExact bytes.\n"
        self.assertEqual(complete_section(source, "Current", len(source))["body"], source)
        with self.assertRaises(ValueError):
            complete_section(source, "Current", len(source) - 1)

    def test_utf8_budget_counts_bytes(self):
        source = "## Current\n\u00e9\n".encode("utf-8")
        with self.assertRaises(ValueError):
            complete_section(source, "Current", len(source.decode("utf-8")))
        self.assertEqual(complete_section(source, "Current", len(source))["body_bytes"], len(source))

    def test_crlf_and_unterminated_final_line_are_preserved(self):
        source = b"# Project\r\n## Current\r\nExact text"
        result = complete_section(source, "Current")
        self.assertEqual(result["body"], b"## Current\r\nExact text")
        self.assertEqual((result["start_line"], result["end_line"]), (2, 3))

    def test_missing_duplicate_or_nonmatching_level_refuses(self):
        for source in (b"## Other\n", b"### Current\n", b"## Current\n## Current\n"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                complete_section(source, "Current")

    def test_source_limits_and_invalid_inputs_refuse(self):
        source = b"## Current\n"
        for limit in (True, 0, -1, 1.5):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                complete_section(source, "Current", max_body_bytes=limit)
        with self.assertRaises(ValueError):
            complete_section(source, "Current", max_source_bytes=len(source) - 1)
        for name in ("", " Current", "Current\n## History"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                complete_section(source, name)
        with self.assertRaises(TypeError):
            complete_section(source.decode(), "Current")
        with self.assertRaises(UnicodeDecodeError):
            complete_section(b"## Current\n\xff", "Current")

    def test_entire_source_is_distinguished_from_a_section_only_view(self):
        source = b"## Current\n"
        result = complete_section(source, "Current")
        self.assertTrue(result["full_source_in_body"])
        self.assertEqual(result["body_sha256"], result["source_sha256"])


if __name__ == "__main__":
    unittest.main()
