"""Read a complete literal H2 section from immutable source bytes without I/O."""
import hashlib


def complete_section(source, section, max_body_bytes=4096, max_source_bytes=524288):
    """Refuse missing, ambiguous or oversized sections; never truncate or summarize.

    Headings are exact lines beginning with ``## ``. This is not a Markdown
    parser. The owner must qualify the document format and source association.
    Hashes describe these bytes, not source freshness or execution authority.
    """
    if type(source) is not bytes or type(section) is not str:
        raise TypeError("Source must be bytes and section must be a string")
    if (not section or section.strip() != section
            or "\r" in section or "\n" in section):
        raise ValueError("One nonempty literal section name is required")
    for limit in (max_body_bytes, max_source_bytes):
        if type(limit) is not int or limit <= 0:
            raise ValueError("Byte limits must be positive integers")
    if not 0 < len(source) <= max_source_bytes:
        raise ValueError("Source exceeds its byte limit or is empty")
    source.decode("utf-8", errors="strict")
    lines = source.splitlines(keepends=True)
    heading = b"## " + section.encode("utf-8")
    starts = [index for index, line in enumerate(lines)
              if line.rstrip(b"\r\n") == heading]
    if len(starts) != 1:
        raise ValueError("Exactly one matching section is required")
    start = starts[0]
    end = next((index for index in range(start + 1, len(lines))
                if lines[index].startswith(b"## ")), len(lines))
    body = b"".join(lines[start:end])
    if len(body) > max_body_bytes:
        raise ValueError("Complete section exceeds its byte limit")
    return {
        "section": section,
        "body": body,
        "body_bytes": len(body),
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "source_bytes": len(source),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "start_line": start + 1,
        "end_line": end,
        "section_complete": True,
        "full_source_in_body": body == source,
    }
