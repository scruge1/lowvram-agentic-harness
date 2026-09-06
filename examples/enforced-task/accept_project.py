"""Independent whole-project acceptance for the composed example."""

import json
import sys
from pathlib import Path


EXPECTED = "accepted: admitted research and corrective retry were used\n"


def valid(result, receipt):
    return (
        result == EXPECTED
        and isinstance(receipt, dict)
        and receipt.get("status") == "accepted"
        and receipt.get("accepted_attempt") == 2
        and receipt.get("research", {}).get("min_sources") == 2
    )


if "--negative-control" in sys.argv:
    raise SystemExit(0 if not valid("invalid", {}) else 1)

result = Path("artifacts/result.txt").read_text(encoding="utf-8")
receipt = json.loads(
    Path("artifacts/enforcement-receipt.json").read_text(encoding="utf-8")
)
raise SystemExit(0 if valid(result, receipt) else 1)
