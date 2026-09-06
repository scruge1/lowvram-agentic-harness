import json
import sys
from pathlib import Path


def valid(plan):
    return (
        isinstance(plan, dict)
        and plan.get("project") == "starter"
        and isinstance(plan.get("steps"), list)
        and bool(plan["steps"])
    )


if "--negative-control" in sys.argv:
    raise SystemExit(0 if not valid({"project": "wrong", "steps": []}) else 1)

plan = json.loads(Path("artifacts/plan.json").read_text(encoding="utf-8"))
raise SystemExit(0 if valid(plan) else 1)
