import copy
import hashlib
import unittest

from harness.quote_evidence import attribute_quote


class QuoteEvidenceTests(unittest.TestCase):
    def test_unique_quote_binds_exact_bytes_without_mutation(self):
        quote = "an exact observation"
        fields = {"unrelated": "other words", "answer": "Prefix: " + quote + "."}
        before = copy.deepcopy(fields)
        result = attribute_quote(quote, fields)
        self.assertEqual(result, {
            "field": "answer",
            "field_sha256": hashlib.sha256(fields["answer"].encode()).hexdigest(),
            "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
            "utf8_spans": [{"start": 8, "end": 28}],
        })
        self.assertEqual(fields, before)
        self.assertEqual(result, attribute_quote(quote, dict(reversed(list(fields.items())))))

    def test_absent_and_multiple_field_matches_refuse(self):
        for fields in ({}, {"a": "no observation"},
                       {"a": "same exact quote", "b": "prefix same exact quote"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                attribute_quote("same exact quote", fields)

    def test_unicode_spans_are_bytes_and_keep_all_occurrences(self):
        quote = "évidence"
        value = "🙂" + quote + " / " + quote
        result = attribute_quote(quote, {"a": value})
        self.assertEqual(result["utf8_spans"], [{"start": 4, "end": 13}, {"start": 16, "end": 25}])
        for span in result["utf8_spans"]:
            self.assertEqual(value.encode()[span["start"]:span["end"]], quote.encode())

    def test_overlapping_occurrences_are_preserved(self):
        self.assertEqual(attribute_quote("aaaaaaaa", {"a": "aaaaaaaaaa"})["utf8_spans"],
                         [{"start": 0, "end": 8}, {"start": 1, "end": 9}, {"start": 2, "end": 10}])

    def test_no_normalization_or_case_repair(self):
        for text in ("EVIDENCE", "e\u0301vidence", "évid ence"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                attribute_quote("évidence", {"a": text})

    def test_character_limits_and_invalid_inputs(self):
        for size in (8, 120):
            quote = "é" * size
            self.assertEqual(attribute_quote(quote, {"a": quote})["utf8_spans"],
                             [{"start": 0, "end": size * 2}])
        for quote in (None, b"evidence", "x" * 7, "x" * 121, "evidence\n", "evidence\r"):
            with self.subTest(quote=quote), self.assertRaises(ValueError):
                attribute_quote(quote, {"a": "evidence"})
        for fields in (None, [], {1: "evidence"}, {"a": 1}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                attribute_quote("evidence", fields)

    def test_invalid_utf8_refuses(self):
        with self.assertRaises(ValueError):
            attribute_quote("evidence", {"a": "\ud800evidence"})

    def test_exact_membership_does_not_claim_semantic_support(self):
        result = attribute_quote("unrelated statement", {"wrong_answer": "unrelated statement"})
        self.assertEqual(result["field"], "wrong_answer")
        self.assertEqual(set(result), {"field", "field_sha256", "quote_sha256", "utf8_spans"})


if __name__ == "__main__":
    unittest.main()
