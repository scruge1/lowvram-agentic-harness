import unittest

from harness.source_edit import replace_exact_once


class SourceEditTests(unittest.TestCase):
    def test_missing_inherited_pin_is_refused(self):
        source = b"startup-new\npins = parent_pins\n"
        # A rename and inverse rename can pass while a missing pin edit is a no-op.
        self.assertEqual(source.replace(b"old-pin", b"new-pin"), source)
        with self.assertRaises(ValueError):
            replace_exact_once(source, b"old-pin", b"new-pin")

    def test_multiple_and_overlapping_matches_are_refused(self):
        for source, old in ((b"old old", b"old"), (b"ababa", b"aba")):
            with self.subTest(source=source), self.assertRaises(ValueError):
                replace_exact_once(source, old, b"new")

    def test_empty_and_unchanged_edits_are_refused(self):
        for old, new in ((b"", b"new"), (b"old", b"old")):
            with self.subTest(old=old), self.assertRaises(ValueError):
                replace_exact_once(b"old", old, new)

    def test_text_or_mutable_input_is_refused(self):
        for values in (("old", b"old", b"new"),
                       (b"old", "old", b"new"),
                       (b"old", b"old", bytearray(b"new"))):
            with self.subTest(values=values), self.assertRaises(TypeError):
                replace_exact_once(*values)

    def test_exact_binary_edit_preserves_other_bytes(self):
        source = b"\x00prefix\r\nold-pin\r\n\xffsuffix\n"
        self.assertEqual(replace_exact_once(source, b"old-pin", b"new-pin"),
                         b"\x00prefix\r\nnew-pin\r\n\xffsuffix\n")
        self.assertEqual(source, b"\x00prefix\r\nold-pin\r\n\xffsuffix\n")

    def test_explicit_deletion_supports_checked_inverse(self):
        self.assertEqual(replace_exact_once(b"prefix\nadded\nsuffix\n", b"added\n", b""),
                         b"prefix\nsuffix\n")


if __name__ == "__main__":
    unittest.main()
