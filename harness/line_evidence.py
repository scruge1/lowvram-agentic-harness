"""Resolve complete numbered source lines without executing or reading files."""

import hashlib
import re


def resolve_numbered_line(excerpt, span, line_number, *, excerpt_sha256,
                          content_sha256):
    """Check a bounded window and return one complete factual witness location.

    Expected hashes must come from the caller's bound source reference. This
    checks byte consistency; it does not authenticate the reference or establish
    that the selected line supports a claim. It performs no source-file reads.
    """
    if type(excerpt) is not str:
        raise ValueError("Numbered excerpt must be text")
    try:
        raw = excerpt.encode("utf-8")
    except UnicodeError:
        raise ValueError("Numbered excerpt must be valid UTF-8") from None
    if not 0 < len(raw) <= 8000 or "\r" in excerpt:
        raise ValueError("Numbered excerpt exceeds its format or byte limit")
    if (type(span) not in (list, tuple) or len(span) != 2
            or not all(type(n) is int and n > 0 for n in span)
            or not 0 <= span[1] - span[0] < 64):
        raise ValueError("Source span must contain 1..64 contiguous lines")
    if type(line_number) is not int or not span[0] <= line_number <= span[1]:
        raise ValueError("Selected line must be an integer inside the source span")
    for digest in (excerpt_sha256, content_sha256):
        if type(digest) is not str or re.fullmatch("[a-f0-9]{64}", digest) is None:
            raise ValueError("Expected source hashes must be lowercase SHA256")
    if hashlib.sha256(raw).hexdigest() != excerpt_sha256:
        raise ValueError("Numbered excerpt hash differs")
    lines = excerpt.split("\n")
    if len(lines) != span[1] - span[0] + 1:
        raise ValueError("Numbered excerpt does not match its source span")
    contents = []
    for number, line in zip(range(span[0], span[1] + 1), lines):
        prefix = str(number) + ": "
        if not line.startswith(prefix):
            raise ValueError("Source line numbers must be exact and contiguous")
        contents.append(line[len(prefix):])
    content_bytes = "\n".join(contents).encode("utf-8")
    if hashlib.sha256(content_bytes).hexdigest() != content_sha256:
        raise ValueError("Unnumbered window content hash differs")

    offset = line_number - span[0]
    content = contents[offset]

    def underline(text):
        return re.fullmatch(r" {0,3}(?:=+|-+)\s*", text) is not None

    heading = re.match(r"^ {0,3}#{1,6}(?:\s|$)", content) is not None
    next_underline = offset + 1 < len(contents) and underline(contents[offset + 1])
    if not content.strip() or heading or underline(content) or next_underline:
        raise ValueError("Blank or Markdown heading lines are not factual witnesses")
    numbered_line = lines[offset]
    return {
        "span": list(span),
        "line_number": line_number,
        "numbered_line": numbered_line,
        "content": content,
        "numbered_line_sha256": hashlib.sha256(numbered_line.encode()).hexdigest(),
        "selected_content_sha256": hashlib.sha256(content.encode()).hexdigest(),
        "excerpt_sha256": excerpt_sha256,
        "window_content_sha256": content_sha256,
        "location_is_not_entailment": True,
    }
