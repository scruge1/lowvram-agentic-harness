import hashlib
import unittest

from harness.source_compare import compare_named_functions


class SourceCompareTests(unittest.TestCase):
    def test_formatting_and_comments_preserve_selected_ast(self):
        left = b"def f():\n    return 1\n"
        right = b"# moved\n\ndef f():\n    return 1  # same value\n"
        result = compare_named_functions(left, right, ["f"])
        self.assertTrue(result["all_selected_functions_equal"])
        self.assertFalse(result["source_bytes_equal"])
        self.assertEqual(result["left"]["source_sha256"], hashlib.sha256(left).hexdigest())
        self.assertEqual(result["right"]["source_bytes"], len(right))
        self.assertTrue(result["parser_version"])

    def test_body_change_is_localized_to_named_function(self):
        left = b"def f(): return 1\ndef g(): return 2\n"
        right = b"def f(): return 3\ndef g(): return 2\n"
        result = compare_named_functions(left, right, ["f", "g"])
        self.assertEqual(result["functions_equal"], {"f": False, "g": True})
        self.assertFalse(result["all_selected_functions_equal"])

    def test_global_changes_do_not_establish_behavioural_equivalence(self):
        left = b"VALUE=1\ndef f(): return VALUE\n"
        right = b"VALUE=2\ndef f(): return VALUE\n"
        result = compare_named_functions(left, right, ["f"])
        self.assertTrue(result["all_selected_functions_equal"])
        self.assertFalse(result["source_bytes_equal"])
        self.assertNotIn("behaviour_equal", result)

    def test_source_is_not_executed(self):
        source = b"raise AssertionError('must not run')\ndef f(): return 1\n"
        self.assertTrue(compare_named_functions(source, source, ["f"])["source_bytes_equal"])

    def test_missing_nested_and_duplicate_names_refuse(self):
        for source in (b"def g(): pass\n",
                       b"def g():\n    def f(): pass\n",
                       b"def f(): pass\ndef f(): pass\n",
                       b"def f(): pass\nasync def f(): pass\n"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                compare_named_functions(source, source, ["f"])

    def test_async_function_and_unicode_bytes(self):
        source = 'async def f(): return "é"\n'.encode()
        result = compare_named_functions(source, source, ("f",), len(source))
        self.assertTrue(result["all_selected_functions_equal"])
        with self.assertRaises(ValueError):
            compare_named_functions(source, source, ["f"], len(source) - 1)

    def test_invalid_sources_refuse_without_echoing_source(self):
        for source in (b"", "def f(): pass", b"def f(): SECRET("):
            with self.subTest(source=source), self.assertRaises(ValueError) as caught:
                compare_named_functions(source, b"def f(): pass\n", ["f"])
            self.assertNotIn("SECRET", str(caught.exception))

    def test_invalid_names_and_limits_refuse(self):
        source = b"def f(): pass\n"
        for names in ([], "f", ["f", "f"], ["not a name"], [None], ["f"] * 33):
            with self.subTest(names=names), self.assertRaises(ValueError):
                compare_named_functions(source, source, names)
        for limit in (True, 0, -1, "100"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                compare_named_functions(source, source, ["f"], limit)


if __name__ == "__main__":
    unittest.main()
