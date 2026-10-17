"""Compare selected Python functions using paired bytes and one local parser."""

import ast
import hashlib
import sys


def compare_named_functions(left, right, names, max_source_bytes=131072):
    """Return source identity and selected AST comparisons without executing code.

    Names identify top-level sync or async functions and must occur exactly once
    in each source. Both sources are parsed in this call. AST hashes describe
    this parser's dump format; do not compare them across runtimes. Matching
    selected ASTs does not establish whole-source or behavioural equivalence.
    """
    if type(max_source_bytes) is not int or max_source_bytes <= 0:
        raise ValueError("Source byte limit must be a positive integer")
    if type(names) not in (list, tuple) or not 1 <= len(names) <= 32:
        raise ValueError("Provide 1..32 function names")
    if not all(type(name) is str and name.isidentifier() for name in names):
        raise ValueError("Function names must be identifiers")
    if len(set(names)) != len(names):
        raise ValueError("Function names must be distinct")

    def inspect(source, label):
        if type(source) is not bytes or not 0 < len(source) <= max_source_bytes:
            raise ValueError(label + " source must fit its byte limit")
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            raise ValueError(label + " source is not valid Python") from None
        functions = {}
        for name in names:
            found = [node for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and node.name == name]
            if len(found) != 1:
                raise ValueError(label + " source requires one function named " + name)
            dumped = ast.dump(found[0], include_attributes=False).encode("utf-8")
            functions[name] = hashlib.sha256(dumped).hexdigest()
        return {
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "source_bytes": len(source),
            "function_asts": functions,
        }

    left_result = inspect(left, "Left")
    right_result = inspect(right, "Right")
    equal = {name: left_result["function_asts"][name]
             == right_result["function_asts"][name] for name in names}
    return {
        "parser": sys.implementation.name,
        "parser_version": ".".join(str(value) for value in sys.version_info[:3]),
        "ast_format": "ast.dump(include_attributes=False), same call",
        "left": left_result,
        "right": right_result,
        "source_bytes_equal": left == right,
        "functions_equal": equal,
        "all_selected_functions_equal": all(equal.values()),
    }
