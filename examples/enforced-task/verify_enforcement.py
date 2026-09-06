"""SSOT stage verifier for a live enforcement receipt."""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if (REPO / "harness").is_dir():
    sys.path.insert(0, str(REPO))

from harness.enforcement import EnforcementError, verify_receipt  # noqa: E402


negative = "--negative-control" in sys.argv
try:
    result = verify_receipt(
        Path.cwd(),
        Path("task.json"),
        Path("artifacts/enforcement-receipt.json"),
        negative_control=negative,
    )
except EnforcementError:
    raise SystemExit(0 if negative else 1)

raise SystemExit(1 if negative else (0 if result["status"] == "verified" else 1))
