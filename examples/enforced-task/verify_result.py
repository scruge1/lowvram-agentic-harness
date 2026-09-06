"""Independent positive and same-program negative control for the example."""

import sys
from pathlib import Path


EXPECTED = "accepted: admitted research and corrective retry were used\n"


def valid(value):
    return value == EXPECTED


if "--negative-control" in sys.argv:
    raise SystemExit(0 if not valid("invalid result\n") else 1)

raise SystemExit(
    0 if valid(Path("artifacts/result.txt").read_text(encoding="utf-8")) else 1
)
