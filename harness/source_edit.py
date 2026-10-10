"""Make one unambiguous byte edit without writing or publishing a file."""


def replace_exact_once(source, old, new):
    """Refuse missing, repeated, overlapping or ineffective replacements."""
    if any(type(value) is not bytes for value in (source, old, new)):
        raise TypeError("Source and replacement values must be bytes")
    if not old or old == new:
        raise ValueError("Replacement must have a nonempty, changed source value")
    index = source.find(old)
    if index < 0 or source.find(old, index + 1) >= 0:
        raise ValueError("Expected exactly one source occurrence")
    return source[:index] + new + source[index + len(old):]
