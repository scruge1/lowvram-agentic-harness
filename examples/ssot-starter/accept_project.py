import json
import sys
from pathlib import Path


def valid(plan, result):
    return (
        isinstance(plan, dict)
        and plan.get("project") == "starter"
        and "starter" in result
        and "plan-used" in result
    )


if "--negative-control" in sys.argv:
    raise SystemExit(0 if not valid({}, "invalid") else 1)

plan = json.loads(Path("artifacts/plan.json").read_text(encoding="utf-8"))
result = Path("artifacts/result.txt").read_text(encoding="utf-8")
raise SystemExit(0 if valid(plan, result) else 1)
