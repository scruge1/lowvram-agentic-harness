import sys
from pathlib import Path


def valid(text):
    return "starter" in text and "plan-used" in text


if "--negative-control" in sys.argv:
    raise SystemExit(0 if not valid("unrelated result") else 1)

text = Path("artifacts/result.txt").read_text(encoding="utf-8")
raise SystemExit(0 if valid(text) else 1)
