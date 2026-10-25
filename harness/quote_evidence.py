"""Attribute an exact quote to one host-supplied field without model inference."""

import hashlib


def attribute_quote(quote, fields):
    """Return the unique field and every UTF-8 byte span, or refuse.

    Quote length is 8..120 Unicode characters. Fields must be a host-bound dict
    of string identifiers and string values. Multiple occurrences in one field
    are allowed; matches in multiple fields are ambiguous. No normalization or
    first-match fallback occurs. Spans include overlaps and use exclusive ends.

    This checks attribution only, not meaning, completeness, source freshness or
    authority. Keep the raw model response separately. The caller must bind the
    candidate, request and this extractor's source bytes before using the result.
    """
    if type(quote) is not str or not 8 <= len(quote) <= 120:
        raise ValueError("Quote must contain 8..120 characters")
    if "\r" in quote or "\n" in quote:
        raise ValueError("Quote must be one line")
    if type(fields) is not dict or not all(
        type(key) is str and type(value) is str for key, value in fields.items()
    ):
        raise ValueError("Fields must map string identifiers to string values")
    matches = [(key, value) for key, value in fields.items() if quote in value]
    if len(matches) != 1:
        raise ValueError("Quote must match exactly one field")
    field, value = matches[0]
    field_bytes = value.encode("utf-8", errors="strict")
    quote_bytes = quote.encode("utf-8", errors="strict")
    spans = []
    offset = 0
    while True:
        start = field_bytes.find(quote_bytes, offset)
        if start < 0:
            break
        spans.append({"start": start, "end": start + len(quote_bytes)})
        offset = start + 1
    return {
        "field": field,
        "field_sha256": hashlib.sha256(field_bytes).hexdigest(),
        "quote_sha256": hashlib.sha256(quote_bytes).hexdigest(),
        "utf8_spans": spans,
    }
