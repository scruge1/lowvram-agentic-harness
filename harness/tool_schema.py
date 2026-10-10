"""Compare or replace one reviewed tool definition without changing host state."""

import hashlib
import json


def _snapshot(definition):
    if type(definition) is not dict or set(definition) != {"type", "function"}:
        return None
    if definition["type"] != "function" or type(definition["function"]) is not dict:
        return None
    try:
        raw = json.dumps(definition, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(raw) > 131072:
            return None
        copied = json.loads(raw)
        name = copied["function"].get("name")
        if type(name) is not str or not name:
            return None
        function = json.dumps(copied["function"], sort_keys=True,
                              separators=(",", ":"), ensure_ascii=False,
                              allow_nan=False).encode("utf-8")
        return copied, hashlib.sha256(function).hexdigest()
    except (TypeError, ValueError, UnicodeError, RuntimeError):
        return None


def tool_function_sha256(definition):
    """Hash a bounded JSON function field; unknown shapes return None."""
    snapshot = _snapshot(definition)
    return snapshot[1] if snapshot is not None else None


def migrate_known_tool_schema(pinned, fresh, *, scope, expected_scope, tool_name,
                              old_function_sha256, new_function_sha256):
    """Return an independent fresh snapshot only for an exact reviewed migration.

    Unmatched cases return the original pinned object. The caller supplies the
    authenticated scope, reviewed policy and already available fresh definition.
    This function grants no authority and performs no persistence or execution.
    """
    policy = (scope, expected_scope, tool_name,
              old_function_sha256, new_function_sha256)
    if any(type(value) is not str or not value for value in policy):
        return pinned
    if scope != expected_scope or old_function_sha256 == new_function_sha256:
        return pinned
    old, new = _snapshot(pinned), _snapshot(fresh)
    if old is None or new is None:
        return pinned
    if (old[0]["function"]["name"] != tool_name
            or new[0]["function"]["name"] != tool_name
            or old[1] != old_function_sha256 or new[1] != new_function_sha256):
        return pinned
    return new[0]
