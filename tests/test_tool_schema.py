import copy
import unittest

from harness.tool_schema import migrate_known_tool_schema, tool_function_sha256


class ToolSchemaTests(unittest.TestCase):
    def setUp(self):
        self.old = {"type": "function", "function": {
            "name": "read_context", "description": "Read current project notes.",
            "parameters": {"type": "object", "properties": {
                "layer": {"type": "string"},
                "scope": {"type": "string", "enum": ["named", "selected"]}},
                "required": ["layer"], "additionalProperties": False}}}
        self.fresh = copy.deepcopy(self.old)
        self.fresh["function"]["parameters"]["required"].append("scope")
        self.policy = {"scope": "session-a", "expected_scope": "session-a",
                       "tool_name": "read_context",
                       "old_function_sha256": tool_function_sha256(self.old),
                       "new_function_sha256": tool_function_sha256(self.fresh)}

    def migrate(self, pinned=None, fresh=None, **changes):
        return migrate_known_tool_schema(
            self.old if pinned is None else pinned,
            self.fresh if fresh is None else fresh, **{**self.policy, **changes})

    def test_known_same_version_contract_change_replaces_only_target(self):
        other = {"type": "function", "function": {"name": "other"}}
        before = [other, self.old]
        after = [self.migrate(pinned=item) for item in before]
        self.assertIs(after[0], other)
        self.assertEqual(after[1], self.fresh)
        self.assertEqual(before, [other, self.old])
        self.assertNotEqual(self.policy["old_function_sha256"],
                            self.policy["new_function_sha256"])

    def test_foreign_or_missing_scope_and_policy_do_not_migrate(self):
        for changes in ({"scope": "session-b"}, {"scope": ""},
                        {"scope": None}, {"expected_scope": None},
                        {"tool_name": "other"}, {"old_function_sha256": "unknown"}):
            with self.subTest(changes=changes):
                self.assertIs(self.migrate(**changes), self.old)

    def test_unknown_old_or_fresh_content_does_not_migrate(self):
        for target in ("pinned", "fresh"):
            changed = copy.deepcopy(self.old if target == "pinned" else self.fresh)
            changed["function"]["description"] += " drift"
            result = self.migrate(**{target: changed})
            self.assertIs(result, changed if target == "pinned" else self.old)

    def test_unavailable_or_foreign_fresh_tool_is_not_reintroduced(self):
        self.assertIs(migrate_known_tool_schema(self.old, None, **self.policy), self.old)
        changed = copy.deepcopy(self.fresh)
        changed["function"]["name"] = "foreign"
        self.assertIs(self.migrate(fresh=changed), self.old)

    def test_snapshot_preserves_inputs_and_is_independent_of_fresh_cache(self):
        original = copy.deepcopy(self.fresh)
        result = self.migrate()
        self.assertEqual(self.fresh, original)
        self.assertEqual(result, original)
        self.fresh["function"]["parameters"]["required"].append("unexpected")
        self.assertEqual(result, original)
        self.assertEqual(tool_function_sha256(result), self.policy["new_function_sha256"])

    def test_second_migration_and_unchanged_contract_are_noops(self):
        result = self.migrate()
        self.assertIs(self.migrate(pinned=result), result)
        self.assertIs(self.migrate(new_function_sha256=self.policy["old_function_sha256"]),
                      self.old)

    def test_unknown_wrapper_non_json_nonfinite_and_large_shapes_hold(self):
        invalid = [None, {}, {**self.fresh, "strict": True},
                   {"type": "custom", "function": self.fresh["function"]}]
        for value in (float("nan"), object(), "x" * 131073):
            changed = copy.deepcopy(self.fresh)
            changed["function"]["unexpected"] = value
            invalid.append(changed)
        for changed in invalid:
            with self.subTest(changed_type=type(changed).__name__):
                self.assertIsNone(tool_function_sha256(changed))
                self.assertIs(migrate_known_tool_schema(self.old, changed, **self.policy),
                              self.old)


if __name__ == "__main__":
    unittest.main()
